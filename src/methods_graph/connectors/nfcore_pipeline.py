"""Parse an nf-core PIPELINE checkout into a Pipeline node + HAS_MODULE edges.

Reads ``modules.json`` for membership and each vendored module's ``meta.yml``
for the canonical ``name`` join key (so HAS_MODULE targets ``mod:<name>``, the
same id the module connector mints — NOT the directory path).

The connector also emits ``DOWNSTREAM_OF`` edges inferred from module I/O
type-overlap within the pipeline (Option 2): A → B when OUTPUT(A) ∩ INPUT(B)
is non-empty.

Offline + deterministic: no network, no clock; ``ingested_at`` is injected.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from methods_graph.connectors.nextflow_dag import (
    break_cycles, parse_dag_process_edges)
from methods_graph.connectors.nfcore import _io_module_targets
from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)

_INCLUDE = re.compile(r"include\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
_NAME_AS = re.compile(r"([A-Za-z_]\w*)(?:\s+as\s+([A-Za-z_]\w*))?")
_REL_FROM_PATH = re.compile(r"modules/nf-core/(.+?)(?:/main)?$")


def _module_paths_from_modules_json(modules_json: dict[str, Any]) -> list[str]:
    """Return sorted 'nf-core/<path>' module keys from a modules.json."""
    paths: list[str] = []
    for _repo, repo_body in (modules_json.get("repos") or {}).items():
        nfcore = ((repo_body.get("modules") or {}).get("nf-core") or {})
        paths.extend(nfcore.keys())
    return sorted(set(paths))


def _load_meta(pipeline_dir: Path, rel_path: str) -> dict[str, Any] | None:
    """Load a vendored module's meta.yml as a dict, or None if missing / not a dict."""
    meta_path = pipeline_dir / "modules" / "nf-core" / rel_path / "meta.yml"
    if not meta_path.exists():
        return None
    meta = yaml.safe_load(meta_path.read_text()) or {}
    return meta if isinstance(meta, dict) else None


def _process_to_modid(pipeline_dir: Path, path_to_modid: dict[str, str]) -> dict[str, str]:
    """Map each DSL2 process invocation name (the alias used at the call site, e.g.
    ``KRAKEN2`` from ``include { KRAKEN2_KRAKEN2 as KRAKEN2 }``) to ``mod:<name>``
    by scanning the pipeline's ``.nf`` files for module includes and resolving the
    include path to the module's meta.yml-name id. Only nf-core modules already
    resolved into ``path_to_modid`` are mapped, so a DAG edge can never dangle."""
    out: dict[str, str] = {}
    for nf in sorted(pipeline_dir.rglob("*.nf")):
        for body, path in _INCLUDE.findall(nf.read_text(errors="ignore")):
            m = _REL_FROM_PATH.search(path)
            if not m:
                continue
            mod_id = path_to_modid.get(m.group(1))
            if not mod_id:
                continue
            for piece in re.split(r"[;\n]", body):
                nm = _NAME_AS.match(piece.strip())
                if nm:
                    out[nm.group(2) or nm.group(1)] = mod_id
    return out


def parse_pipeline(
    pipeline_dir: Path,
    *,
    ingested_at: str,
    emit_wiring: bool = True,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    pipeline_dir = Path(pipeline_dir)
    name = pipeline_dir.name
    pipe_id = f"pipe:{name}"
    prov = Provenance("nfcore_pipeline",
                      f"https://github.com/nf-core/{name}", ingested_at)

    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = _module_paths_from_modules_json(modules_json)

    # Single pass: read each vendored module's meta.yml ONCE.  A module is
    # resolved only if its meta.yml exists and declares a usable `name`
    # (the mod:<name> join key — NOT the directory path).
    path_to_modid: dict[str, str] = {}
    io: dict[str, tuple[set[str], set[str]]] = {}
    for rel in rel_paths:
        meta = _load_meta(pipeline_dir, rel)
        if meta is None:
            continue
        name_field = meta.get("name")
        if not (isinstance(name_field, str) and name_field):
            continue  # name-less module is dropped, like a missing meta.yml
        path_to_modid[rel] = f"mod:{name_field}"
        io[rel] = (_io_module_targets(meta, "input"), _io_module_targets(meta, "output"))

    # A pipeline whose modules all failed to resolve (nameless meta.yml, odd layout)
    # would be an orphan Pipeline node with no HAS_MODULE — useless, and it trips the
    # "Pipeline has >=1 HAS_MODULE" invariant.  Skip it entirely.
    if not path_to_modid:
        return [], []

    nodes: list[NodeRecord] = [NodeRecord(
        pipe_id, name, NodeKind.PIPELINE,
        {"url": prov.source_url, "n_modules": len(path_to_modid)}, prov,
    )]
    edges: list[EdgeRecord] = [
        EdgeRecord(pipe_id, mod_id, EdgeKind.HAS_MODULE, {}, prov)
        for mod_id in sorted(set(path_to_modid.values()))
    ]

    # Wiring.  Prefer the GROUND-TRUTH Nextflow DAG (cached at fetch time as
    # dag.mmd) when present: real channel wiring, derivation="nextflow_dsl2".
    # Otherwise fall back to Option-2 I/O-overlap inference (derivation=
    # "io_inferred", a permissive candidate graph).  Same DOWNSTREAM_OF contract.
    # `emit_wiring=False` skips DOWNSTREAM_OF entirely — used for bulk catalog
    # imports where no DAG was generated and io_inferred would be O(modules^2) noise.
    dag_path = pipeline_dir / "dag.mmd"
    seen_pairs: set[tuple[str, str]] = set()
    if not emit_wiring:
        return nodes, edges
    if dag_path.exists():
        proc2mod = _process_to_modid(pipeline_dir, path_to_modid)
        # Collapse process-label edges onto module ids, keeping each module pair's
        # EARLIEST rank.  Aliased instances of one tool (e.g. SAMTOOLS_SORT and
        # SAMTOOLS_SORT_QUALIMAP both -> mod:samtools_sort) collapse distinct DAG
        # positions into a single node, which can produce BOTH A->B and B->A — a
        # cycle.  break_cycles keeps the primary (first-occurring) direction so the
        # ground-truth DOWNSTREAM_OF layer is a trustworthy DAG.
        mod_rank: dict[tuple[str, str], int] = {}
        for a_label, b_label, r in parse_dag_process_edges(dag_path.read_text()):
            a_id, b_id = proc2mod.get(a_label), proc2mod.get(b_label)
            if not a_id or not b_id or a_id == b_id:   # unmapped or self-loop
                continue
            key = (a_id, b_id)
            if r < mod_rank.get(key, r + 1):
                mod_rank[key] = r
        for a_id, b_id in break_cycles([(a, b, r) for (a, b), r in mod_rank.items()]):
            seen_pairs.add((a_id, b_id))
            edges.append(EdgeRecord(
                a_id, b_id, EdgeKind.DOWNSTREAM_OF,
                {"pipelines": [name], "attestations": 1,
                 "derivation": "nextflow_dsl2", "confidence": 0.95},
                prov,
            ))
    else:
        # Option-2: A -DOWNSTREAM_OF-> B when OUTPUT(A) ∩ INPUT(B) ≠ ∅.  Mutually
        # I/O-compatible modules emit BOTH directions — a candidate graph, not a DAG.
        for a_rel, (_a_in, a_out) in sorted(io.items()):
            for b_rel, (b_in, _b_out) in sorted(io.items()):
                a_id, b_id = path_to_modid[a_rel], path_to_modid[b_rel]
                if a_id == b_id:           # no self-loops (incl. name collisions)
                    continue
                if a_out & b_in and (a_id, b_id) not in seen_pairs:
                    seen_pairs.add((a_id, b_id))
                    edges.append(EdgeRecord(
                        a_id, b_id, EdgeKind.DOWNSTREAM_OF,
                        {"pipelines": [name], "attestations": 1,
                         "derivation": "io_inferred", "confidence": 0.5},
                        prov,
                    ))
    return nodes, edges
