"""Walk a directory of nf-core clones and emit the frozen benchmark item set."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from methods_graph.bench.build import build_manifest, make_items
from methods_graph.bench.gold import gold_edges, gold_sequence
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


def build_from_clones(
    pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str],
) -> dict[str, Any]:
    """Build items for every clone under *pipelines_dir*; write items + manifest."""
    if not pipelines_dir.exists():
        raise FileNotFoundError(f"--pipelines path does not exist: {pipelines_dir}")

    items_dir, gold_dir = out_dir / "items", out_dir / "gold"
    items_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for pipeline_dir in sorted(p for p in pipelines_dir.iterdir() if p.is_dir()):
        name = pipeline_dir.name
        revision = _revision(pipeline_dir)
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
            pipeline=name, revision=revision, nxf_ver="unknown",
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
