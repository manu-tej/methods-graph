"""Parse an nf-core PIPELINE checkout into Pipeline + HAS_MODULE + DOWNSTREAM_OF.

Reads ``modules.json`` (membership) and each vendored module's ``meta.yml``
(for the canonical ``name`` join key and the I/O contract used to infer
DOWNSTREAM_OF ordering — Option 2, see ``_infer_downstream``).

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
    return meta.get("name", Path(rel_path).name)


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
        for mod_id in sorted(path_to_modid.values())
    ]
    return nodes, edges
