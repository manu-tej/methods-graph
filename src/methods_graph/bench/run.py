"""Walk a directory of nf-core clones and emit the frozen benchmark item set."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import yaml

from methods_graph.bench.adapters import AdapterError
from methods_graph.bench.build import build_manifest, make_items
from methods_graph.bench.gold import gold_edges, gold_sequence
from methods_graph.bench.normalize import (
    normalize_answer, project_edges, project_sequence)
from methods_graph.bench.oracle import Oracle
from methods_graph.bench.render import parse_tool_list, render_prompt
from methods_graph.bench.score import (
    aggregate_next_step, match_steps, position_bucket, score_next_step,
    score_selection, score_sequencing, score_validity)
from methods_graph.connectors.nfcore_pipeline import (
    iter_module_metas, module_paths_from_modules_json, process_to_modid)


def _module_map(pipeline_dir: Path) -> dict[str, str]:
    """DSL2 process label -> module id, using the SAME resolution the graph connector uses.

    The answer key has to speak the graph's ids or it references nothing: ``iter_module_metas``
    is the one place ``mod:<meta.yml name>`` is defined, so gold sequences cannot drift onto a
    parallel scheme.
    """
    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = module_paths_from_modules_json(modules_json)
    path_to_modid = {
        rel: mod_id for rel, mod_id, _meta in iter_module_metas(pipeline_dir, rel_paths)
    }
    return process_to_modid(pipeline_dir, path_to_modid)


def _revision(pipeline_dir: Path) -> str:
    """The clone's checked-out commit, or ``"unknown"`` if it cannot be read.

    A frozen item names the tree it was derived from; ``nf-core/rnaseq@unknown`` is not
    auditable. Never fatal — a missing git, a tarball rather than a clone, or a detached
    worktree all degrade to the honest "unknown" instead of losing the whole build.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(pipeline_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else "unknown"


def load_pipeline_manifests(snapshot_path: Path) -> dict[str, dict[str, Any]]:
    """Per-pipeline fetch manifests from a snapshot.json, or ``{}`` if absent.

    Missing is not an error: an offline build from a plain directory of clones is a
    supported path, and it degrades to "unknown" provenance rather than failing.
    """
    if not snapshot_path.exists():
        return {}
    try:
        blob = json.loads(snapshot_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return (blob.get("sources") or {}).get("nfcore_pipelines") or {}


def build_from_clones(
    pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str],
    manifests: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build items for every clone under *pipelines_dir*; write items + manifest.

    *manifests* carries the ``fetch_nfcore_pipeline`` record per pipeline. It supplies
    the RELEASE tag and the NXF_VER the DAG was previewed under — provenance a bare
    clone cannot report, and which spec §1 requires so a disputed item can be re-derived.
    """
    if not pipelines_dir.exists():
        raise FileNotFoundError(f"--pipelines path does not exist: {pipelines_dir}")

    manifests = manifests or {}

    items_dir, gold_dir = out_dir / "items", out_dir / "gold"
    items_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for pipeline_dir in sorted(p for p in pipelines_dir.iterdir() if p.is_dir()):
        name = pipeline_dir.name
        manifest_entry = manifests.get(name) or {}
        # The release tag names what a reader can check out; the commit is the fallback
        # when no manifest recorded a tag.
        revision = manifest_entry.get("revision") or _revision(pipeline_dir)
        nxf_ver = manifest_entry.get("nxf_ver") or "unknown"
        dag_path = pipeline_dir / "dag.mmd"
        if not dag_path.exists():
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": "no dag.mmd produced by nextflow -preview"})
            continue

        # Every read of the clone lives inside the guard: one unreadable checkout
        # (bad JSON, a non-UTF-8 file, a malformed meta.yml) drops that pipeline
        # with a recorded reason rather than discarding the whole build.
        try:
            text = dag_path.read_text()
            module_map = _module_map(pipeline_dir)
            sequence = gold_sequence(text, module_map)
            edges = gold_edges(text, module_map)
        except (FileNotFoundError, json.JSONDecodeError, KeyError,
                UnicodeDecodeError, yaml.YAMLError) as exc:
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": f"could not read pipeline metadata: "
                                       f"{type(exc).__name__}: {exc}"})
            continue

        if len(sequence) < 2:
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": f"gold sequence too short ({len(sequence)} steps)"})
            continue

        items = make_items(
            pipeline=name, revision=revision, nxf_ver=nxf_ver,
            dag_sha256=hashlib.sha256(text.encode()).hexdigest(),
            goal=goals.get(name, name), sequence=sequence, edges=edges,
            derivation="nextflow_dsl2",
        )
        (items_dir / f"{name}.json").write_text(json.dumps(items, indent=2, sort_keys=True))
        outcomes.append({"pipeline": name, "revision": revision, "status": "used",
                         "reason": None, "n_items": len(items)})

    manifest = build_manifest(outcomes)
    (gold_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def load_items(items_dir: Path) -> list[dict[str, Any]]:
    """Every item under *items_dir*, ordered by id so runs are comparable."""
    items: list[dict[str, Any]] = []
    for path in sorted(items_dir.glob("*.json")):
        items.extend(json.loads(path.read_text()))
    return sorted(items, key=lambda item: item["id"])


def score_item(item: dict[str, Any], raw: str, oracle: Oracle) -> dict[str, Any]:
    """One model answer, scored on every axis its task type supports.

    ``raw`` is kept on the row: every score here is a pure function of it, so a metric
    can be redefined and the whole run re-scored without spending another API call.
    """
    names = parse_tool_list(raw)
    pred, unresolved = normalize_answer(names, oracle)
    row: dict[str, Any] = {
        "item": item["id"], "task": item["task"], "raw": raw,
        "parsed": bool(names), "pred": pred, "unresolved": unresolved, "error": None,
        # The item's own gold and prefix, verbatim. Together with `raw` these are
        # everything `rescore` needs, so a redefined metric can be applied to a finished
        # run without re-reading the item set — or paying for the API calls again.
        "gold_raw": item["gold"], "given": list(item.get("given") or []),
    }

    if item["task"] == "whole_pipeline":
        gold_modules = item["gold"]["sequence"]
        gold, gold_unresolved = project_sequence(gold_modules, oracle)
        edges, n_cyclic = project_edges(
            item["gold"].get("edges") or [], gold_modules, oracle)
        selection = score_selection(gold, pred, oracle)
        row.update({
            "gold": gold,
            "gold_unresolved": gold_unresolved,
            "n_cyclic_edges_dropped": n_cyclic,
            "selection": selection,
            "sequencing": score_sequencing(edges, selection["matched"], pred),
            "validity": score_validity(pred, oracle),
        })
        return row

    if item["task"] == "next_step":
        gold_next = oracle.method_for_module(item["gold"]["next"])
        n_given = len(item.get("given") or [])
        row.update({"gold": gold_next, "n_given": n_given,
                    "bucket": position_bucket(n_given)})
        # An unresolvable gold answer cannot be scored against; it is reported, not zeroed.
        row["next"] = (None if gold_next is None
                       else score_next_step(gold_next, pred, oracle))
        return row

    raise ValueError(f"unknown task type: {item['task']!r}")


def run_items(
    items: list[dict[str, Any]], adapter: Callable[[str], str], oracle: Oracle,
    *, model: str,
) -> list[dict[str, Any]]:
    """Render, call, score — one row per item, in item order.

    An adapter failure is recorded against its item and the run continues: a rate limit
    partway through a 500-item set must not discard the 300 answers already paid for.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        prompt = render_prompt(item, oracle)
        try:
            raw = adapter(prompt)
        except AdapterError as exc:
            rows.append({"item": item["id"], "task": item["task"], "model": model,
                         "raw": None, "parsed": False, "pred": [], "unresolved": [],
                         "error": str(exc), "selection": None, "sequencing": None,
                         "validity": None, "next": None})
            continue
        rows.append({**score_item(item, raw, oracle), "model": model})
    return rows


def rescore(rows: list[dict[str, Any]], oracle: Oracle) -> list[dict[str, Any]]:
    """Re-derive every score from the retained raw output, leaving failures untouched."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("raw") is None:
            out.append(dict(row))
            continue
        item = {"id": row["item"], "task": row["task"], "goal": "",
                "given": row.get("given") or [], "gold": row["gold_raw"]}
        out.append({**score_item(item, row["raw"], oracle), "model": row.get("model")})
    return out


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline table: two task types, never pooled into one accuracy figure."""
    whole = [r for r in rows if r["task"] == "whole_pipeline" and not r["error"]]
    nxt = [r for r in rows if r["task"] == "next_step" and not r["error"] and r["next"]]

    return {
        "n_rows": len(rows),
        "n_errors": sum(1 for r in rows if r["error"]),
        "n_unparsed": sum(1 for r in rows if not r["parsed"] and not r["error"]),
        "whole_pipeline": {
            "n": len(whole),
            "selection_f1": _mean([r["selection"]["f1"] for r in whole]),
            "selection_precision": _mean([r["selection"]["precision"] for r in whole]),
            "selection_recall": _mean([r["selection"]["recall"] for r in whole]),
            "sequencing": _mean([r["sequencing"]["score"] for r in whole]),
            "sequencing_n_scored": sum(
                1 for r in whole if r["sequencing"]["score"] is not None),
            "validity": _mean([r["validity"]["score"] for r in whole]),
            "validity_coverage": _mean([r["validity"]["coverage"] for r in whole]),
        },
        "next_step": {
            "n": len(nxt),
            **aggregate_next_step([
                {"n_given": r["n_given"], "top1": r["next"]["top1"],
                 "topk": r["next"]["topk"]} for r in nxt]),
        },
    }
