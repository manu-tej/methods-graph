"""Deterministic entity resolution: merge methods on shared id; emit SAME_AS candidates.

Resolution uses **union-find (disjoint-set)** over each record's own id ONLY so
that:

  1. Method records sharing the SAME ``m:<name>`` id collapse into one canonical
     Method — ensuring no duplicate primary keys in the output (Kùzu PK safety).
  2. Distinct tool ids are NEVER hard-merged, even if they share a bioconda
     package or bio.tools entry.  Shared bioconda packages are frequently shared
     *dependencies* (e.g. many tools depend on ``htslib``), and bio.tools ids are
     sometimes mislabelled in nf-core meta.yml — either would cause distinct tools
     (e.g. bcftools↔samtools) to be wrongly fused.

Strong-identifier semantics (post-merge):
  - bioconda_pkg  — **attribute only**.  Carried on the canonical record and used
                    for PACKAGED_AS linking.  Does NOT trigger a hard merge and
                    does NOT produce SAME_AS candidates (shared-dependency risk).
  - biotools_id   — **SAME_AS candidate only**.  Canonical methods with DIFFERENT
                    ids that share the same biotools_id (case-insensitive, non-
                    empty) get a SAME_AS edge (confidence 0.7, basis "biotools_id").
  - name          — **SAME_AS candidate only**.  Canonical methods with DIFFERENT
                    ids whose lowercased names match get a SAME_AS edge (confidence
                    0.5, basis "name").

When a pair qualifies for BOTH biotools_id and name, ONE edge is emitted with the
higher-confidence basis (biotools_id, 0.7).

Clique-blow-up cap: if a single biotools_id or name maps to more than 8 canonical
methods the candidates for that value are skipped entirely and a warning is logged.

Canonical id rule: for a same-id group the lexicographically smallest id is
canonical (trivially: all members share the same id, so the canonical id IS that
shared id). Members are merged in a stable order (properties tiebreak) so the
filled-property result is deterministic regardless of input ordering.

SAME_AS edges are candidate-only — no hard merge ever occurs from them.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

log = logging.getLogger(__name__)

# Maximum number of canonical methods a single biotools_id / name may map to
# before the whole candidate clique is suppressed (avoids generic-label explosion).
_CLIQUE_CAP = 8


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
    """Return namespaced strong-id keys for m (0, 1, or 2 entries).

    Retained for potential future use but no longer used in the hard-union
    key set — bioconda_pkg and biotools_id are demoted to attribute-only and
    SAME_AS-candidate semantics respectively.
    """
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
    Each record's own id is used as the sole union key (``id::<m.id>``).
    This ensures two records sharing the same ``m:<name>`` id always land in
    the same component, producing exactly one canonical node per id — no
    duplicate primary keys in the output.

    Hard-merge semantics
    --------------------
    Records are hard-merged **only** when they share the same id.  bioconda_pkg
    and biotools_id are NOT union keys — they demote to attribute fill and
    SAME_AS candidates respectively.
    """
    # Build provenance for all edges emitted by this resolver run.
    prov = Provenance("resolver", "internal", ingested_at)

    # ------------------------------------------------------------------
    # 1. Run union-find over ALL method records.
    #    Union key per record: "id::<m.id>" ONLY.
    #    bioconda_pkg and biotools_id are no longer union keys.
    # ------------------------------------------------------------------
    all_methods = list(method_nodes)
    n = len(all_methods)
    uf = _UnionFind(n)
    key_to_idx: dict[str, int] = {}  # first record index that introduced each key

    for idx, m in enumerate(all_methods):
        key = f"id::{m.id}"
        if key in key_to_idx:
            uf.union(idx, key_to_idx[key])
        else:
            key_to_idx[key] = idx

    # ------------------------------------------------------------------
    # 2. Group ALL records by their root index.
    # ------------------------------------------------------------------
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(idx)

    # ------------------------------------------------------------------
    # 3. Build canonical methods.
    #    Within a same-id group, canonical id = the shared id (all members
    #    have the same id by construction).  Members are merged in stable
    #    order: (id, sorted-properties-str) so that property fill is
    #    deterministic regardless of input order.
    # ------------------------------------------------------------------
    canonical_methods: list[MethodRecord] = []
    id_remap: dict[str, str] = {}        # original method id -> canonical id

    for root, members in sorted(groups.items()):
        members_sorted = sorted(
            members,
            key=lambda i: (all_methods[i].id,
                           str(sorted(all_methods[i].properties.items())))
        )
        canon = all_methods[members_sorted[0]]
        canon_id = canon.id
        for i in members_sorted:
            m = all_methods[i]
            id_remap[m.id] = canon_id
            if m is not canon:
                _merge_into(canon, m)
        canonical_methods.append(canon)

    # ------------------------------------------------------------------
    # 4. SAME_AS candidates — two independent passes, then merge.
    #
    #    Pass A — biotools_id: canonical methods with DIFFERENT ids that
    #    share the same biotools_id (case-insensitive, non-empty).
    #    confidence=0.7, basis="biotools_id".
    #
    #    Pass B — name: canonical methods with DIFFERENT ids whose
    #    lowercased names match.
    #    confidence=0.5, basis="name".
    #
    #    If a pair qualifies for both, emit ONE edge with higher confidence
    #    (biotools_id, 0.7).
    #
    #    Cap: if a single key maps to more than _CLIQUE_CAP canonicals, skip
    #    emitting candidates for it and log a warning.
    # ------------------------------------------------------------------
    edges: list[EdgeRecord] = []

    # candidate_pairs: (min_id, max_id) -> best (confidence, basis)
    candidate_pairs: dict[tuple[str, str], tuple[float, str]] = {}

    def _register_pair(id_a: str, id_b: str, confidence: float, basis: str) -> None:
        """Record (or upgrade) a candidate pair, keeping highest confidence."""
        key = (min(id_a, id_b), max(id_a, id_b))
        existing = candidate_pairs.get(key)
        if existing is None or confidence > existing[0]:
            candidate_pairs[key] = (confidence, basis)

    # Pass A: biotools_id candidates.
    bt_map: dict[str, list[str]] = defaultdict(list)
    for m in canonical_methods:
        if m.biotools_id:
            bt_map[m.biotools_id.lower()].append(m.id)

    for bt_val, ids in bt_map.items():
        if len(ids) <= 1:
            continue
        if len(ids) > _CLIQUE_CAP:
            log.warning(
                "resolver: biotools_id %r maps to %d canonical methods (> cap %d); "
                "skipping SAME_AS candidates for this id.",
                bt_val, len(ids), _CLIQUE_CAP,
            )
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                _register_pair(ids[i], ids[j], 0.7, "biotools_id")

    # Pass B: name candidates.
    name_map: dict[str, list[str]] = defaultdict(list)
    for m in canonical_methods:
        if m.name:
            name_map[m.name.lower()].append(m.id)

    for name_val, ids in name_map.items():
        if len(ids) <= 1:
            continue
        if len(ids) > _CLIQUE_CAP:
            log.warning(
                "resolver: name %r maps to %d canonical methods (> cap %d); "
                "skipping SAME_AS candidates for this name.",
                name_val, len(ids), _CLIQUE_CAP,
            )
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                _register_pair(ids[i], ids[j], 0.5, "name")

    # Emit all candidate edges, sorted deterministically by (from_id, to_id).
    for (id_a, id_b), (confidence, basis) in sorted(candidate_pairs.items()):
        edges.append(EdgeRecord(id_a, id_b, EdgeKind.SAME_AS,
                                {"confidence": confidence, "basis": basis}, prov))

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
    #    bioconda_pkg is still used as the attribute for linking — only its
    #    role as a hard-union key has been removed.
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
