import logging

import pytest

from methods_graph.types import MethodRecord, NodeRecord, NodeKind, EdgeKind, EdgeRecord, Provenance
from methods_graph.resolve.resolver import resolve

P = Provenance("test", "x", "2026-06-08")


def _method(id, name, pkg=None, bt=None):
    return MethodRecord(id=id, name=name, kind=NodeKind.METHOD, properties={},
                        provenance=P, bioconda_pkg=pkg, biotools_id=bt)


# ---------------------------------------------------------------------------
# bioconda_pkg is attribute-only — no hard merge, no SAME_AS
# ---------------------------------------------------------------------------

def test_shared_bioconda_pkg_does_not_merge():
    """Two records with DIFFERENT ids and DIFFERENT names sharing only bioconda_pkg
    must NOT hard-merge and must NOT produce a SAME_AS candidate (shared dependency
    risk; bioconda_pkg is attribute-only).

    We use distinct names to isolate the pkg-only behaviour — with different names
    there is no name-based candidate either, proving bioconda_pkg alone produces
    neither a hard merge nor a SAME_AS edge.
    """
    a = _method("m:bcftools", "bcftools", pkg="htslib")
    b = _method("m:samtools", "samtools", pkg="htslib")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2, f"Expected 2 separate methods, got {len(methods)}"
    assert len(same_as) == 0, f"Expected no SAME_AS from shared pkg, got {same_as}"


# ---------------------------------------------------------------------------
# biotools_id → SAME_AS candidate (not a hard merge)
# ---------------------------------------------------------------------------

def test_shared_biotools_id_emits_same_as_not_merge():
    """Two records with DIFFERENT ids sharing the same biotools_id must produce
    2 canonical methods AND one SAME_AS edge (basis='biotools_id', confidence=0.7).
    """
    a = _method("m:a", "toolA", bt="x")
    b = _method("m:b", "toolB", bt="x")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2, f"Expected 2 methods, got {len(methods)}"
    assert len(same_as) == 1, f"Expected 1 SAME_AS, got {len(same_as)}"
    edge = same_as[0]
    assert edge.properties["basis"] == "biotools_id"
    assert edge.properties["confidence"] == pytest.approx(0.7)
    assert {edge.from_id, edge.to_id} == {"m:a", "m:b"}


def test_biotools_id_clique_capped(caplog):
    """9 records with distinct ids all sharing biotools_id='z' must produce no
    SAME_AS edges (capped), and a warning must be logged.
    """
    methods = [_method(f"m:tool{i}", f"tool{i}", bt="z") for i in range(9)]
    with caplog.at_level(logging.WARNING, logger="methods_graph.resolve.resolver"):
        nodes, edges = resolve(method_nodes=methods, other_nodes=[], src_edges=[])
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(same_as) == 0, f"Expected 0 SAME_AS (capped), got {len(same_as)}"
    assert any("biotools_id" in rec.message and "skipping" in rec.message
               for rec in caplog.records), \
        "Expected a warning log about skipping SAME_AS candidates for capped biotools_id"


def test_transitive_bridge_via_biotools_id_produces_candidates_not_merge():
    """Records B and C share biotools_id with A (different ids).
    Under new semantics: 3 separate canonical methods + SAME_AS candidates among
    them (NOT a single hard-merged method).
    Pairs sharing biotools_id 'salmon': (m:a, m:b) and (m:a, m:c).
    """
    a = _method("m:a", "salmon", pkg="salmon", bt="salmon")
    b = _method("m:b", "Salmon", bt="salmon")
    c = _method("m:c", "Salmon", pkg="salmon")
    nodes, edges = resolve(method_nodes=[a, b, c], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    # All three have different ids → 3 canonical methods
    assert len(methods) == 3, f"Expected 3 separate methods, got {len(methods)}"
    # b and a share bt::salmon → SAME_AS(m:a, m:b, basis=biotools_id)
    # c and a share name "salmon" (lowercased) → SAME_AS(m:a, m:c, basis=name)
    # b and c share name "salmon" (lowercased) → SAME_AS(m:b, m:c, basis=name)
    # (m:a/m:b also share name "salmon" in lowercase — covered by name pass too,
    #  but biotools_id wins at 0.7 vs 0.5 so only one edge per pair)
    assert len(same_as) >= 1, "Expected at least one SAME_AS candidate"
    # All edges must be candidates, not hard merges (methods count confirms that)
    for e in same_as:
        assert e.properties.get("confidence") is not None


def test_different_ids_shared_biotools_only_no_pkg_candidate():
    """B=(bt='Y' only) and C=(pkg='X' only) with A=(pkg='X', bt='Y').
    Under NEW semantics: 3 separate canonical methods (no transitive hard-merge).
    B and A share biotools_id 'Y' → SAME_AS candidate.
    C and A share only bioconda_pkg 'X' → NO candidate (pkg is attribute-only).
    """
    a = _method("m:a", "toolA", pkg="X", bt="Y")
    b = _method("m:b", "toolB", bt="Y")
    c = _method("m:c", "toolC", pkg="X")
    nodes, edges = resolve(method_nodes=[a, b, c], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 3, f"Expected 3 separate methods, got {[m.id for m in methods]}"
    # Only the bt-based pair (m:a, m:b) gets a SAME_AS; c shares only pkg with a → no candidate
    bt_candidates = [e for e in same_as if e.properties.get("basis") == "biotools_id"]
    assert len(bt_candidates) == 1
    assert {bt_candidates[0].from_id, bt_candidates[0].to_id} == {"m:a", "m:b"}


# ---------------------------------------------------------------------------
# PACKAGED_AS linking — unchanged
# ---------------------------------------------------------------------------

def test_resolver_links_method_to_container_via_packaged_as():
    method = _method("m:salmon", "salmon", pkg="salmon")
    pkg = NodeRecord("pkg:salmon", "salmon", NodeKind.PACKAGE, {}, P)
    container = NodeRecord("ctr:salmon", "img", NodeKind.CONTAINER, {}, P)
    from_pkg = EdgeRecord("ctr:salmon", "pkg:salmon", EdgeKind.FROM_PACKAGE, {}, P)
    nodes, edges = resolve(method_nodes=[method], other_nodes=[pkg, container],
                           src_edges=[from_pkg])
    packaged = [e for e in edges if e.kind == EdgeKind.PACKAGED_AS]
    assert any(e.from_id == "m:salmon" and e.to_id == "ctr:salmon" for e in packaged)


def test_method_links_to_package_when_no_container():
    method = _method("m:salmon", "salmon", pkg="salmon")
    pkg = NodeRecord("pkg:salmon", "salmon", NodeKind.PACKAGE, {}, P)
    nodes, edges = resolve(method_nodes=[method], other_nodes=[pkg], src_edges=[])
    packaged = [e for e in edges if e.kind == EdgeKind.PACKAGED_AS]
    assert any(e.from_id == "m:salmon" and e.to_id == "pkg:salmon" for e in packaged)


# ---------------------------------------------------------------------------
# SAME_AS candidates — name-based (general path, no strong-key prerequisite)
# ---------------------------------------------------------------------------

def test_name_only_match_becomes_same_as_candidate():
    """Two different-id records sharing only a name → SAME_AS basis='name', 0.5."""
    a = _method("m:bwa", "bwa", pkg="bwa")
    b = _method("m:bwa-tooluniverse", "bwa")   # no pkg/biotools id, name only
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2            # NOT hard-merged
    assert len(same_as) == 1
    edge = same_as[0]
    assert edge.properties["basis"] == "name"
    assert 0.0 < edge.properties["confidence"] < 1.0


def test_name_case_variant_becomes_same_as_candidate():
    """m:DESeq2 / m:deseq2 — different ids, same lowercased name → SAME_AS."""
    a = _method("m:DESeq2", "DESeq2")
    b = _method("m:deseq2", "deseq2")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2
    assert len(same_as) == 1
    assert same_as[0].properties["basis"] == "name"


# ---------------------------------------------------------------------------
# Both biotools_id and name match → ONE edge with higher confidence
# ---------------------------------------------------------------------------

def test_both_biotools_and_name_match_emits_one_edge_with_higher_confidence():
    """If two canonicals share both biotools_id and name, only ONE SAME_AS edge
    is emitted, using the higher confidence (0.7, basis='biotools_id').
    """
    a = _method("m:a", "salmon", bt="salmon")
    b = _method("m:b", "salmon", bt="salmon")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(same_as) == 1, f"Expected exactly 1 SAME_AS edge, got {len(same_as)}"
    assert same_as[0].properties["confidence"] == pytest.approx(0.7)
    assert same_as[0].properties["basis"] == "biotools_id"


# ---------------------------------------------------------------------------
# No spurious merge — different ids, no shared key
# ---------------------------------------------------------------------------

def test_partial_key_overlap_not_merged():
    """Different ids, no shared key → still 2 methods, no candidate."""
    a = _method("m:salmon-bioconda", "salmon", pkg="salmon")   # keyed by bioconda
    b = _method("m:salmon-biotools", "salmon", bt="salmon")    # keyed by biotools
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2
    # They share name "salmon" → one SAME_AS candidate (name), but NO hard-merge
    assert len(same_as) == 1
    assert same_as[0].properties["basis"] == "name"


def test_two_independent_groups_stay_separate():
    """Two methods with completely different keys/names must not merge."""
    a = _method("m:a", "toolA", pkg="a")
    b = _method("m:b", "toolB", pkg="b")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 2


# ---------------------------------------------------------------------------
# Same-id merging (id-only union) — hard merge still applies for same id
# ---------------------------------------------------------------------------

def test_property_merge_order_is_deterministic():
    """Three records sharing the SAME id but different properties must merge
    deterministically regardless of input order.

    Canonical id is "m:a" (shared id of all three).  The merge key is
    (id, sorted-properties-str); among the three, the record with no description
    sorts first (empty dict), then "from-b" < "from-c".  So "from-b" fills the
    missing description on the canonical (first non-empty wins via setdefault).
    Both input orderings must yield identical results.
    """
    def _make_abc():
        a = MethodRecord(id="m:a", name="tool", kind=NodeKind.METHOD,
                         properties={}, provenance=P,
                         bioconda_pkg=None, biotools_id=None)
        b = MethodRecord(id="m:a", name="tool", kind=NodeKind.METHOD,
                         properties={"description": "from-b"}, provenance=P,
                         bioconda_pkg=None, biotools_id=None)
        c = MethodRecord(id="m:a", name="tool", kind=NodeKind.METHOD,
                         properties={"description": "from-c"}, provenance=P,
                         bioconda_pkg=None, biotools_id=None)
        return a, b, c

    a1, b1, c1 = _make_abc()
    nodes1, _ = resolve(method_nodes=[a1, b1, c1], other_nodes=[], src_edges=[])
    methods1 = [n for n in nodes1 if n.kind == NodeKind.METHOD]

    a2, b2, c2 = _make_abc()
    nodes2, _ = resolve(method_nodes=[c2, b2, a2], other_nodes=[], src_edges=[])
    methods2 = [n for n in nodes2 if n.kind == NodeKind.METHOD]

    # Both orderings collapse to exactly one canonical method.
    assert len(methods1) == 1
    assert len(methods2) == 1

    # Canonical id is always "m:a" (the shared id).
    assert methods1[0].id == "m:a"
    assert methods2[0].id == "m:a"

    # Smallest-property-sort provider (m:a with empty props) is canon;
    # "from-b" fills the missing description first (sorts before "from-c").
    assert methods1[0].properties["description"] == "from-b"
    assert methods2[0].properties["description"] == "from-b"


def test_same_id_keyed_and_keyless_merge_to_one_node():
    """A keyed record and a keyless record sharing the same id must produce
    exactly ONE canonical method (not two nodes with duplicate primary key).
    The merged canonical must carry the strong key from the keyed member.
    """
    a = _method("m:x", "pygenprop", pkg="x")   # keyed: has bioconda_pkg
    b = _method("m:x", "pygenprop")             # keyless: no strong keys, same id
    b.properties["description"] = "from-keyless"

    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]

    # Must be exactly one canonical node, not two.
    assert len(methods) == 1, f"Expected 1 method, got {len(methods)}: {[m.id for m in methods]}"
    canon = methods[0]
    assert canon.id == "m:x"

    # bioconda_pkg must be preserved from the keyed member.
    assert canon.bioconda_pkg == "x"

    # No duplicate ids in entire returned node list.
    all_ids = [n.id for n in nodes]
    assert len(all_ids) == len(set(all_ids)), f"Duplicate ids: {all_ids}"


def test_two_keyless_same_id_merge():
    """Two keyless records sharing an id must collapse into ONE canonical method."""
    a = _method("m:y", "toolY")
    a.properties["description"] = "desc-a"
    b = _method("m:y", "toolY")
    b.properties["description"] = "desc-b"

    nodes1, _ = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods1 = [n for n in nodes1 if n.kind == NodeKind.METHOD]
    assert len(methods1) == 1, f"Expected 1, got {len(methods1)}"
    assert methods1[0].id == "m:y"

    # Stable across reversed input order.
    a2 = _method("m:y", "toolY")
    a2.properties["description"] = "desc-a"
    b2 = _method("m:y", "toolY")
    b2.properties["description"] = "desc-b"

    nodes2, _ = resolve(method_nodes=[b2, a2], other_nodes=[], src_edges=[])
    methods2 = [n for n in nodes2 if n.kind == NodeKind.METHOD]
    assert len(methods2) == 1
    assert methods2[0].id == "m:y"

    # Description must be the lexicographically-smaller provider's value.
    # Both records share the same id "m:y" so members_sorted puts "desc-a"
    # first (tiebreak: sorted(properties.items()) → "desc-a" < "desc-b").
    desc1 = methods1[0].properties.get("description")
    desc2 = methods2[0].properties.get("description")
    assert desc1 == "desc-a", f"Expected 'desc-a' (lex-smaller tiebreak), got {desc1!r}"
    assert desc1 == desc2, f"Non-deterministic: {desc1} vs {desc2}"


def test_output_ids_are_unique():
    """Mixed batch with same-id collision plus normal distinct methods:
    output canonical ids must be unique (no duplicate primary keys).
    """
    # Two records share id "m:pygenprop" — one keyed, one keyless.
    a = _method("m:pygenprop", "pygenprop", pkg="pygenprop")
    b = _method("m:pygenprop", "pygenprop")

    # Normal distinct methods.
    c = _method("m:bwa", "bwa", pkg="bwa")
    d = _method("m:star", "star", pkg="star")
    e = _method("m:keyless-only", "keyless")

    nodes, _ = resolve(method_nodes=[a, b, c, d, e], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]

    ids = [m.id for m in methods]
    assert len(ids) == len(set(ids)), f"Duplicate ids in output: {ids}"

    # The collision should have merged to one; total should be 4 distinct methods.
    assert len(ids) == 4, f"Expected 4 canonical methods, got {ids}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_resolver_output_order_is_deterministic():
    """Output method list order must be id-sorted regardless of input order."""
    def _make():
        return [
            _method("m:bwa", "bwa", pkg="bwa"),
            _method("m:star", "star", pkg="star"),
            _method("m:hisat2", "hisat2", pkg="hisat2"),
            _method("m:alpha", "alpha"),      # keyless
            _method("m:zeta", "zeta"),        # keyless
        ]

    order1 = _make()
    order2 = list(reversed(_make()))

    nodes1, _ = resolve(method_nodes=order1, other_nodes=[], src_edges=[])
    nodes2, _ = resolve(method_nodes=order2, other_nodes=[], src_edges=[])

    ids1 = [n.id for n in nodes1 if n.kind == NodeKind.METHOD]
    ids2 = [n.id for n in nodes2 if n.kind == NodeKind.METHOD]

    assert ids1 == ids2, f"Order differed: {ids1} vs {ids2}"
    # Also verify the list is actually sorted by id.
    assert ids1 == sorted(ids1)
