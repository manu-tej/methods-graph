"""Deterministic entity resolution: merge methods on join keys; emit SAME_AS candidates.

Resolution uses **union-find (disjoint-set)** over strong identifiers so that
method records sharing ANY strong id key collapse into one canonical Method —
including transitively through a bridge record.

Strong identifiers are namespaced to avoid false cross-namespace unification:
  - bioconda_pkg  → key "pkg::<name>"
  - biotools_id   → key "bt::<name>"

A record that carries BOTH keys acts as a bridge: it links the pkg:: group to
the bt:: group so that any record in either group merges with the other.

Canonical id rule: the lexicographically smallest original id in each connected
component is chosen as the canonical id.  This is deterministic and stable
across repeated runs regardless of input ordering.
"""
from __future__ import annotations

from collections import defaultdict

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)


# ---------------------------------------------------------------------------
# Union-Find (path-compressed, union-by-rank)
# ---------------------------------------------------------------------------

class _UnionFind:
    """Disjoint-set over integer indices."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _strong_keys(m: MethodRecord) -> list[str]:
    """Return namespaced strong-id keys for m (0, 1, or 2 entries)."""
    keys = []
    if m.bioconda_pkg:
        keys.append(f"pkg::{m.bioconda_pkg.lower()}")
    if m.biotools_id:
        keys.append(f"bt::{m.biotools_id.lower()}")
    return keys


def _merge_into(canon: MethodRecord, other: MethodRecord) -> None:
    """Fill missing-only fields on *canon* from *other* (mutation in place)."""
    for k, v in other.properties.items():
        canon.properties.setdefault(k, v)
    canon.bioconda_pkg = canon.bioconda_pkg or other.bioconda_pkg
    # If the group somehow has two different non-empty values for biotools_id,
    # the first (deterministically chosen canonical) wins — acceptable for MVP.
    canon.biotools_id = canon.biotools_id or other.biotools_id


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

def resolve(*, method_nodes: list[MethodRecord], other_nodes: list[NodeRecord],
            src_edges: list[EdgeRecord],
            ingested_at: str = "") -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Resolve method nodes into canonical records and emit derived edges.

    method_nodes objects may be mutated in place (enriched) during merging —
    callers should treat the list as consumed after this call.

    Parameters
    ----------
    method_nodes:   Raw MethodRecord objects from all connectors.
    other_nodes:    Non-method nodes (packages, containers, …).
    src_edges:      Raw edges from connectors (will be remapped and deduped).
    ingested_at:    ISO-8601 timestamp for resolver provenance; defaults to "".
    """
    # Build provenance for all edges emitted by this resolver run.
    prov = Provenance("resolver", "internal", ingested_at)

    # ------------------------------------------------------------------
    # 1. Partition into keyed and keyless records.
    # ------------------------------------------------------------------
    keyed: list[MethodRecord] = []
    keyless: list[MethodRecord] = []
    for m in method_nodes:
        if _strong_keys(m):
            keyed.append(m)
        else:
            keyless.append(m)

    # ------------------------------------------------------------------
    # 2. Union-find over keyed records by shared namespaced key strings.
    #    A record carrying two keys acts as a bridge between their groups.
    # ------------------------------------------------------------------
    uf = _UnionFind(len(keyed))
    key_to_idx: dict[str, int] = {}  # first record index that introduced each key

    for idx, m in enumerate(keyed):
        for key in _strong_keys(m):
            if key in key_to_idx:
                uf.union(idx, key_to_idx[key])
            else:
                key_to_idx[key] = idx

    # ------------------------------------------------------------------
    # 3. Group keyed records by their root index.
    #    Choose the lexicographically smallest original id as canonical id.
    # ------------------------------------------------------------------
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(keyed)):
        groups[uf.find(idx)].append(idx)

    canonical_methods: list[MethodRecord] = []
    id_remap: dict[str, str] = {}  # original method id -> canonical id

    for root, members in sorted(groups.items()):  # sort for determinism
        # Canonical id = lexicographically smallest id in the group.
        canon_id = min(keyed[i].id for i in members)
        canon_idx = min(members, key=lambda i: keyed[i].id)
        canon = keyed[canon_idx]
        for i in members:
            m = keyed[i]
            id_remap[m.id] = canon_id
            if m is not canon:
                _merge_into(canon, m)
        canonical_methods.append(canon)

    # ------------------------------------------------------------------
    # 4. Keyless records are never hard-merged by union-find.
    #    A keyless method whose name matches a keyed canonical emits a
    #    SAME_AS candidate edge (confidence 0.5, basis "name") — no merge.
    #    Keyless-vs-keyless is intentionally skipped (confidence too low
    #    without at least one anchor key).
    # ------------------------------------------------------------------
    edges: list[EdgeRecord] = []
    # Build by_name in a deterministic order (sorted by id) so that on a
    # lowercased-name collision the last entry (lexicographically-largest id)
    # wins.  Acceptable because name-match is a low-confidence (0.5)
    # SAME_AS candidate only — never a hard merge.
    by_name: dict[str, MethodRecord] = {
        m.name.lower(): m for m in sorted(canonical_methods, key=lambda m: m.id)
    }
    for m in keyless:
        id_remap[m.id] = m.id
        canonical_methods.append(m)
        match = by_name.get(m.name.lower())
        if match and match.id != m.id:
            edges.append(EdgeRecord(m.id, match.id, EdgeKind.SAME_AS,
                                    {"confidence": 0.5, "basis": "name"}, prov))

    # ------------------------------------------------------------------
    # 5. Remap and dedupe source edges against merged ids.
    # ------------------------------------------------------------------
    seen: set[tuple] = set()
    for e in src_edges:
        f = id_remap.get(e.from_id, e.from_id)
        t = id_remap.get(e.to_id, e.to_id)
        sig = (f, t, e.kind.value)
        if sig in seen:
            continue
        seen.add(sig)
        edges.append(EdgeRecord(f, t, e.kind, e.properties, e.provenance))

    # ------------------------------------------------------------------
    # 6. Method -[:PACKAGED_AS]-> Container (or Package if no container).
    #    Intentionally links the method to ALL container variants of its
    #    package — version selectivity (e.g., linking only a specific tag)
    #    is Phase 2.
    # ------------------------------------------------------------------
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
        targets = sorted(ctrs) if ctrs else [pkg.id]
        for tgt in targets:
            edges.append(EdgeRecord(m.id, tgt, EdgeKind.PACKAGED_AS, {}, prov))

    # Sort canonical_methods by id for a deterministic, input-order-independent
    # output list (satisfies the docstring's determinism claim and prevents
    # non-deterministic snapshot diffs).
    canonical_methods.sort(key=lambda m: m.id)

    return canonical_methods + list(other_nodes), edges
