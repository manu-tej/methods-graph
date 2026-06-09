"""Deterministic entity resolution: merge methods on join keys; emit SAME_AS candidates.

Resolution uses **union-find (disjoint-set)** over strong identifiers AND over
each record's own id so that:

  1. Method records sharing ANY strong id key collapse into one canonical Method —
     including transitively through a bridge record.
  2. Two records with the SAME ``m:<name>`` id ALWAYS land in the same component,
     because ``id`` is the Kùzu primary key.  Without this guarantee a keyed and a
     keyless record that happen to share an id would each emit their own canonical
     node → duplicate primary key → load crash.

Strong identifiers are namespaced to avoid false cross-namespace unification:
  - bioconda_pkg  → key "pkg::<name>"
  - biotools_id   → key "bt::<name>"
  - own record id → key "id::<id>"   (exact-equality only — NOT fuzzy)

A record that carries BOTH bioconda/biotools keys acts as a bridge: it links the
pkg:: group to the bt:: group so that any record in either group merges with the
other.

Canonical id rule: the lexicographically smallest original id in each connected
component is chosen as the canonical id.  This is deterministic and stable
across repeated runs regardless of input ordering.

SAME_AS candidates: a component whose members contributed NO strong key
(purely keyless) may share a lowercased name with a keyed-component canonical.
When that happens a SAME_AS edge is emitted (confidence 0.5, basis "name") but
the two components are never hard-merged.  Keyless-vs-keyless name matches are
intentionally skipped (confidence too low without at least one anchor key).
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

    Uniqueness guarantee
    --------------------
    Each record's own id is used as an additional union key (``id::<m.id>``).
    This ensures two records sharing the same ``m:<name>`` id always land in
    the same component, producing exactly one canonical node per id — no
    duplicate primary keys in the output.
    """
    # Build provenance for all edges emitted by this resolver run.
    prov = Provenance("resolver", "internal", ingested_at)

    # ------------------------------------------------------------------
    # 1. Run union-find over ALL method records.
    #    Union keys per record: _strong_keys(m) PLUS "id::<m.id>".
    #    The id:: key guarantees same-id records land in the same component
    #    (exact equality — not fuzzy); strong keys give transitive cross-id
    #    merges (bridge behaviour) as before.
    # ------------------------------------------------------------------
    all_methods = list(method_nodes)
    n = len(all_methods)
    uf = _UnionFind(n)
    key_to_idx: dict[str, int] = {}  # first record index that introduced each key

    for idx, m in enumerate(all_methods):
        # Collect all union keys: strong keys + own-id key.
        union_keys = _strong_keys(m) + [f"id::{m.id}"]
        for key in union_keys:
            if key in key_to_idx:
                uf.union(idx, key_to_idx[key])
            else:
                key_to_idx[key] = idx

    # ------------------------------------------------------------------
    # 2. Group ALL records by their root index.
    #    For each component track whether ANY member contributed a strong key
    #    (needed to decide SAME_AS vs. hard-merge semantics later).
    # ------------------------------------------------------------------
    groups: dict[int, list[int]] = defaultdict(list)
    component_has_strong_key: dict[int, bool] = defaultdict(bool)

    for idx in range(n):
        root = uf.find(idx)
        groups[root].append(idx)
        if _strong_keys(all_methods[idx]):
            component_has_strong_key[root] = True

    # ------------------------------------------------------------------
    # 3. Build canonical methods.
    #    Canonical id = lexicographically smallest id in the component.
    #    Members are merged in id-sorted order into the canonical so that the
    #    smallest-id provider deterministically fills missing properties first.
    #    Record root→has_strong_key for use in SAME_AS logic below.
    # ------------------------------------------------------------------
    canonical_methods: list[MethodRecord] = []
    id_remap: dict[str, str] = {}        # original method id -> canonical id
    # Map canonical_id -> whether its component had any strong key.
    canon_has_strong_key: dict[str, bool] = {}

    for root, members in sorted(groups.items()):
        # Sort members by (original method id, serialised properties) for full
        # determinism.  The properties tiebreak ensures that when two records
        # share the same id the result is stable regardless of input order
        # (content-based ordering, not arrival-order ordering).
        members_sorted = sorted(
            members,
            key=lambda i: (all_methods[i].id,
                           str(sorted(all_methods[i].properties.items())))
        )
        canon = all_methods[members_sorted[0]]   # smallest id = canonical
        canon_id = canon.id
        for i in members_sorted:
            m = all_methods[i]
            id_remap[m.id] = canon_id
            if m is not canon:
                _merge_into(canon, m)
        canonical_methods.append(canon)
        canon_has_strong_key[canon_id] = component_has_strong_key[root]

    # ------------------------------------------------------------------
    # 4. SAME_AS candidates.
    #    A canonical method whose ENTIRE component had NO strong key
    #    ("purely keyless") that shares a lowercased NAME with a keyed-
    #    component canonical → emit a SAME_AS candidate edge (confidence 0.5,
    #    basis "name"), never a hard merge.
    #    Keyless-vs-keyless name matches stay skipped, as before.
    # ------------------------------------------------------------------
    edges: list[EdgeRecord] = []

    # Build by_name from keyed-component canonicals only.
    # Sorted by id for determinism; on a name collision the last entry
    # (lex-largest id) wins — acceptable: this is low-confidence (0.5) only.
    by_name: dict[str, MethodRecord] = {
        m.name.lower(): m
        for m in sorted(canonical_methods, key=lambda m: m.id)
        if canon_has_strong_key.get(m.id, False)
    }

    for m in canonical_methods:
        if canon_has_strong_key.get(m.id, False):
            # Keyed component — never emits a SAME_AS from this side.
            continue
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

    # Sort canonical_methods by id for a deterministic, input-order-independent
    # output list (satisfies the docstring's determinism claim and prevents
    # non-deterministic snapshot diffs).
    canonical_methods.sort(key=lambda m: m.id)

    # Deduplicate other_nodes by id (first-seen wins) so that duplicate Package
    # or Container records emitted by connectors do not propagate into the loader
    # as duplicate primary keys.  Sort by id for full input-order independence.
    seen_other: dict[str, NodeRecord] = {}
    for node in other_nodes:
        seen_other.setdefault(node.id, node)
    deduped_other = sorted(seen_other.values(), key=lambda node: node.id)

    # ------------------------------------------------------------------
    # 6. Method -[:PACKAGED_AS]-> Container (or Package if no container).
    #    Intentionally links the method to ALL container variants of its
    #    package — version selectivity (e.g., linking only a specific tag)
    #    is Phase 2.
    #    pkg_by_name is built from deduped_other so the lookup is consistent
    #    with what actually ends up in the graph.
    # ------------------------------------------------------------------
    pkg_by_name = {node.name.lower(): node for node in deduped_other if node.kind == NodeKind.PACKAGE}
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

    return canonical_methods + deduped_other, edges
