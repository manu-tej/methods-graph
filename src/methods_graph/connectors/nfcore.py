"""Parse an nf-core module directory into Module + Method nodes and edges.

Each module's ``meta.yml`` may declare multiple tools under the ``tools:`` key.
``parse_module`` emits one ``Module`` node and one ``Method`` node per tool,
connected by a ``WRAPS`` edge.  All EDAM PERFORMS / HAS_TOPIC edges are also
emitted per tool.  This captures **intra-module composition** — a module that
wraps both ``samtools`` and ``bcftools`` will have two WRAPS edges, one to each
Method.

Pipeline-level DAG gap (Phase 2)
---------------------------------
Intra-module multi-tool composition is now captured via multiple WRAPS edges
from a Module to its Methods.  The PIPELINE-LEVEL DAG — i.e. the
``DOWNSTREAM_OF`` ordering between modules across a pipeline's ``main.nf``
workflow file — is STILL NOT ingested and remains Phase 2.  ``parse_module``
operates on a single module directory and does not read pipeline workflow files.
The ``DOWNSTREAM_OF`` EdgeKind stays declared-but-unemitted.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_DEP_RE = re.compile(r"(?:(?P<chan>[\w-]+)::)?(?P<pkg>[\w.-]+)=(?P<ver>[\w.+-]+)")


def _bioconda_dep(env_path: Path, prefer_pkg: str | None = None, *,
                  allow_single_fallback: bool = False) -> tuple[str | None, str | None]:
    """Return (pkg, version) for the bioconda dependency in *env_path*.

    Matching rules (in priority order):

    1. If *prefer_pkg* matches a dep's package name (case-insensitive) →
       return that dep immediately.  This ensures each tool gets its own
       package even in a multi-dep environment.yml.
    2. Elif there is exactly ONE bioconda dep AND either no *prefer_pkg* was
       given OR *allow_single_fallback* is True → return it.
       The *allow_single_fallback* flag is set by the caller when the module
       has exactly one valid tool, making it unambiguous to assign the sole
       dep to that tool even when the tool key name differs from the package
       name (e.g. tool key ``fastqc_check``, package ``fastqc``).
    3. Else → return ``(None, None)``.  Multiple deps exist but none matches
       *prefer_pkg*, or this is a multi-tool module and no name match was
       found; refusing to guess avoids mis-assignment.
    """
    if not env_path.exists():
        return None, None
    env = yaml.safe_load(env_path.read_text()) or {}
    bioconda_deps: list[tuple[str, str]] = []
    for dep in env.get("dependencies", []):
        if not isinstance(dep, str):
            continue
        m = _DEP_RE.match(dep)
        if m and (m.group("chan") in (None, "bioconda")):
            pkg, ver = m.group("pkg"), m.group("ver")
            # Rule 1: prefer-match wins immediately.
            if prefer_pkg and pkg.lower() == prefer_pkg.lower():
                return pkg, ver
            bioconda_deps.append((pkg, ver))
    # Rule 2: unambiguous single dep — fires when there is no prefer_pkg at
    # all, OR when the caller explicitly allows the single-tool fallback (i.e.
    # a single-tool module with a single dep, even if names differ).
    if len(bioconda_deps) == 1 and (allow_single_fallback or not prefer_pkg):
        return bioconda_deps[0]
    # Rule 3: ambiguous — don't guess.
    return None, None


def parse_module(module_dir: Path, *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    prov = Provenance("nfcore", f"https://github.com/nf-core/modules/tree/master/{module_dir.name}",
                      ingested_at)
    meta = yaml.safe_load((module_dir / "meta.yml").read_text()) or {}
    if not isinstance(meta, dict):
        meta = {}
    module_name = meta.get("name", module_dir.name)
    env_path = module_dir / "environment.yml"

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    module_id = f"mod:{module_name}"
    nodes.append(NodeRecord(module_id, module_name, NodeKind.MODULE,
                            {"description": meta.get("description", "")}, prov))

    tools = meta.get("tools") or []

    # Count valid (non-empty dict) tool entries to detect single-tool modules.
    # Note: if the same tool name appears twice, single_tool will be False and
    # only an exact name-match can assign the dep — degenerate but safe.
    valid_tools = [t for t in tools if isinstance(t, dict) and t]
    single_tool = len(valid_tools) == 1

    # Dedupe: track emitted method ids within this module so that if two tool
    # entries share the same name we emit one Method + one WRAPS.
    emitted_method_ids: set[str] = set()

    for tool_entry in valid_tools:
        tool_name, tool_meta = next(iter(tool_entry.items()))
        method_id = f"m:{tool_name}"

        # Per-tool bioconda resolution: prefer_pkg=tool_name guarantees the
        # correct package is selected even in multi-dep environment.yml files.
        # allow_single_fallback lets a single-tool module claim the sole dep
        # even when the tool key name differs from the package name.
        pkg, ver = _bioconda_dep(env_path, prefer_pkg=tool_name,
                                 allow_single_fallback=single_tool)

        biotools_id = (tool_meta.get("identifier") or "").replace("biotools:", "") or None

        if method_id not in emitted_method_ids:
            emitted_method_ids.add(method_id)
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
            # Keep WRAPS and EDAM edges inside the dedup guard so that a
            # repeated tool name yields exactly one Method + one WRAPS + one
            # set of EDAM edges (no duplicates).
            edges.append(EdgeRecord(module_id, method_id, EdgeKind.WRAPS, {}, prov))
            for op in tool_meta.get("edam_operations", []):
                edges.append(EdgeRecord(method_id, f"op:{op}", EdgeKind.PERFORMS, {}, prov))
            for tp in tool_meta.get("edam_topics", []):
                edges.append(EdgeRecord(method_id, f"topic:{tp}", EdgeKind.HAS_TOPIC, {}, prov))

    return nodes, edges
