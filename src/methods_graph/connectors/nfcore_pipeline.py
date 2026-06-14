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
from pathlib import Path
from typing import Any

import yaml

from methods_graph.connectors.nfcore import _io_module_targets
from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)


def _module_paths_from_modules_json(modules_json: dict[str, Any]) -> list[str]:
    """Return sorted 'nf-core/<path>' module keys from a modules.json."""
    paths: list[str] = []
    for _repo, repo_body in (modules_json.get("repos") or {}).items():
        nfcore = ((repo_body.get("modules") or {}).get("nf-core") or {})
        paths.extend(nfcore.keys())
    return sorted(set(paths))


def _module_name(pipeline_dir: Path, rel_path: str) -> str | None:
    """Read the vendored module's meta.yml `name` (the mod: join key)."""
    meta_path = pipeline_dir / "modules" / "nf-core" / rel_path / "meta.yml"
    if not meta_path.exists():
        return None
    meta = yaml.safe_load(meta_path.read_text()) or {}
    if not isinstance(meta, dict):
        return None
    name = meta.get("name")
    return name if isinstance(name, str) and name else None


def _module_io(pipeline_dir: Path, rel_path: str) -> tuple[set[str], set[str]]:
    """(inputs, outputs) EDAM/synthetic-format id sets for a vendored module."""
    meta_path = pipeline_dir / "modules" / "nf-core" / rel_path / "meta.yml"
    meta = yaml.safe_load(meta_path.read_text()) or {}
    if not isinstance(meta, dict):
        return set(), set()
    return _io_module_targets(meta, "input"), _io_module_targets(meta, "output")


def parse_pipeline(
    pipeline_dir: Path,
    *,
    ingested_at: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    pipeline_dir = Path(pipeline_dir)
    name = pipeline_dir.name
    pipe_id = f"pipe:{name}"
    prov = Provenance("nfcore_pipeline",
                      f"https://github.com/nf-core/{name}", ingested_at)

    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = _module_paths_from_modules_json(modules_json)

    # path → mod:<meta.yml name>; drop any path whose meta.yml is missing.
    path_to_modid: dict[str, str] = {}
    for rel in rel_paths:
        mname = _module_name(pipeline_dir, rel)
        if mname:
            path_to_modid[rel] = f"mod:{mname}"

    nodes: list[NodeRecord] = [NodeRecord(
        pipe_id, name, NodeKind.PIPELINE,
        {"url": prov.source_url, "n_modules": len(path_to_modid)}, prov,
    )]
    edges: list[EdgeRecord] = [
        EdgeRecord(pipe_id, mod_id, EdgeKind.HAS_MODULE, {}, prov)
        for mod_id in sorted(set(path_to_modid.values()))
    ]

    # Option-2 wiring: A -DOWNSTREAM_OF-> B when OUTPUT(A) ∩ INPUT(B) ≠ ∅.
    io: dict[str, tuple[set[str], set[str]]] = {
        rel: _module_io(pipeline_dir, rel) for rel in path_to_modid
    }
    seen_pairs: set[tuple[str, str]] = set()
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
