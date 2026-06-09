"""Parse an nf-core module directory into Module + Method nodes and edges."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_DEP_RE = re.compile(r"(?:(?P<chan>[\w-]+)::)?(?P<pkg>[\w.-]+)=(?P<ver>[\w.+-]+)")


def _bioconda_dep(env_path: Path, prefer_pkg: str | None = None) -> tuple[str | None, str | None]:
    """Return (pkg, version) for the bioconda dependency in *env_path*.

    When *prefer_pkg* is given, prefer the dep whose parsed package name
    matches it (case-insensitive); fall back to the first bioconda dep found.
    """
    if not env_path.exists():
        return None, None
    env = yaml.safe_load(env_path.read_text()) or {}
    first_match: tuple[str, str] | None = None
    for dep in env.get("dependencies", []):
        if not isinstance(dep, str):
            continue
        m = _DEP_RE.match(dep)
        if m and (m.group("chan") in (None, "bioconda")):
            pkg, ver = m.group("pkg"), m.group("ver")
            if first_match is None:
                first_match = (pkg, ver)
            if prefer_pkg and pkg.lower() == prefer_pkg.lower():
                return pkg, ver
    return first_match if first_match else (None, None)


def parse_module(module_dir: Path, *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    prov = Provenance("nfcore", f"https://github.com/nf-core/modules/tree/master/{module_dir.name}",
                      ingested_at)
    meta = yaml.safe_load((module_dir / "meta.yml").read_text()) or {}
    if not isinstance(meta, dict):
        meta = {}
    module_name = meta.get("name", module_dir.name)

    # Resolve tool name first so _bioconda_dep can prefer-match against it.
    tools = meta.get("tools") or []
    tool_name: str | None = None
    if tools:
        tool_name = next(iter(tools[0].keys()))

    pkg, ver = _bioconda_dep(module_dir / "environment.yml", prefer_pkg=tool_name)

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    module_id = f"mod:{module_name}"
    nodes.append(NodeRecord(module_id, module_name, NodeKind.MODULE,
                            {"description": meta.get("description", "")}, prov))

    # First tool entry is the primary wrapped method.
    if tools:
        tool_name, tool_meta = next(iter(tools[0].items()))
        biotools_id = (tool_meta.get("identifier") or "").replace("biotools:", "") or None
        method_id = f"m:{tool_name}"
        nodes.append(MethodRecord(
            id=method_id, name=tool_name, kind=NodeKind.METHOD,
            properties={
                "description": tool_meta.get("description", ""),
                "homepage": tool_meta.get("homepage", ""),
                "version": ver or "",
                "implementation_type": "nextflow",
            },
            provenance=prov, bioconda_pkg=pkg, biotools_id=biotools_id,
        ))
        edges.append(EdgeRecord(module_id, method_id, EdgeKind.WRAPS, {}, prov))
        for op in tool_meta.get("edam_operations", []):
            edges.append(EdgeRecord(method_id, f"op:{op}", EdgeKind.PERFORMS, {}, prov))
        for tp in tool_meta.get("edam_topics", []):
            edges.append(EdgeRecord(method_id, f"topic:{tp}", EdgeKind.HAS_TOPIC, {}, prov))

    return nodes, edges
