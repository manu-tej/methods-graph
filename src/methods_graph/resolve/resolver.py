"""Deterministic entity resolution: merge methods on join keys; emit SAME_AS candidates."""
from __future__ import annotations

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_RESOLVER_PROV = Provenance("resolver", "internal", "")


def _merge_key(m: MethodRecord) -> str | None:
    if m.bioconda_pkg:
        return f"pkg::{m.bioconda_pkg.lower()}"
    if m.biotools_id:
        return f"bt::{m.biotools_id.lower()}"
    return None


def _merge_into(canon: MethodRecord, other: MethodRecord) -> None:
    for k, v in other.properties.items():
        canon.properties.setdefault(k, v)
    canon.bioconda_pkg = canon.bioconda_pkg or other.bioconda_pkg
    canon.biotools_id = canon.biotools_id or other.biotools_id


def resolve(*, method_nodes: list[MethodRecord], other_nodes: list[NodeRecord],
            src_edges: list[EdgeRecord]) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    canon_by_key: dict[str, MethodRecord] = {}
    keyless: list[MethodRecord] = []
    id_remap: dict[str, str] = {}     # original method id -> canonical id

    for m in method_nodes:
        key = _merge_key(m)
        if key is None:
            keyless.append(m)
            continue
        if key in canon_by_key:
            _merge_into(canon_by_key[key], m)
            id_remap[m.id] = canon_by_key[key].id
        else:
            canon_by_key[key] = m
            id_remap[m.id] = m.id

    canonical_methods = list(canon_by_key.values())
    edges: list[EdgeRecord] = []

    # Name-only matches → SAME_AS candidates (never hard-merged).
    by_name: dict[str, MethodRecord] = {m.name.lower(): m for m in canonical_methods}
    for m in keyless:
        id_remap[m.id] = m.id
        canonical_methods.append(m)
        match = by_name.get(m.name.lower())
        if match and match.id != m.id:
            edges.append(EdgeRecord(m.id, match.id, EdgeKind.SAME_AS,
                                    {"confidence": 0.5, "basis": "name"}, _RESOLVER_PROV))

    # Remap and dedupe source edges against merged ids.
    seen: set[tuple] = set()
    for e in src_edges:
        f = id_remap.get(e.from_id, e.from_id)
        t = id_remap.get(e.to_id, e.to_id)
        sig = (f, t, e.kind.value)
        if sig in seen:
            continue
        seen.add(sig)
        edges.append(EdgeRecord(f, t, e.kind, e.properties, e.provenance))

    # Method -[:PACKAGED_AS]-> Container (or Package if no container) via bioconda pkg.
    pkg_by_name = {n.name.lower(): n for n in other_nodes if n.kind == NodeKind.PACKAGE}
    containers_by_pkg: dict[str, list[str]] = {}
    for e in src_edges:
        if e.kind == EdgeKind.FROM_PACKAGE:
            containers_by_pkg.setdefault(e.to_id, []).append(e.from_id)
    for m in canonical_methods:
        if not m.bioconda_pkg:
            continue
        pkg = pkg_by_name.get(m.bioconda_pkg.lower())
        if not pkg:
            continue
        ctrs = containers_by_pkg.get(pkg.id)
        targets = ctrs if ctrs else [pkg.id]
        for tgt in targets:
            edges.append(EdgeRecord(m.id, tgt, EdgeKind.PACKAGED_AS, {}, _RESOLVER_PROV))

    return canonical_methods + list(other_nodes), edges
