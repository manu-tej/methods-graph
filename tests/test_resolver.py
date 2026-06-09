from methods_graph.types import MethodRecord, NodeRecord, NodeKind, EdgeKind, EdgeRecord, Provenance
from methods_graph.resolve.resolver import resolve

P = Provenance("test", "x", "2026-06-08")


def _method(id, name, pkg=None, bt=None):
    return MethodRecord(id=id, name=name, kind=NodeKind.METHOD, properties={},
                        provenance=P, bioconda_pkg=pkg, biotools_id=bt)


def test_methods_merge_on_bioconda_pkg():
    a = _method("m:salmon", "salmon", pkg="salmon", bt="salmon")
    b = _method("m:salmon-dup", "Salmon", pkg="salmon")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 1


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


def test_name_only_match_becomes_same_as_candidate():
    a = _method("m:bwa", "bwa", pkg="bwa")
    b = _method("m:bwa-tooluniverse", "bwa")   # no pkg/biotools id, name only
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2            # NOT hard-merged
    assert len(same_as) == 1
    assert 0.0 < same_as[0].properties["confidence"] < 1.0


# Union-find merges via a *bridge* record that carries both keys.
# Without a bridge, pkg::salmon and bt::salmon are distinct namespaced keys and
# will never merge — which is correct because "salmon" the bioconda package and
# "salmon" the biotools entry are separate identities until a record explicitly
# carries both and acts as the bridge.
def test_partial_key_overlap_not_merged():
    # Method A has only a bioconda_pkg key; method B has only a biotools_id key.
    # Both resolve to the same logical tool ("salmon") but share no *identical* key,
    # and there is no bridge record carrying both — so union-find leaves them as two
    # separate canonical methods.
    a = _method("m:salmon-bioconda", "salmon", pkg="salmon")   # keyed by bioconda
    b = _method("m:salmon-biotools", "salmon", bt="salmon")    # keyed by biotools
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 2           # no bridge record → distinct namespaced keys stay separate


def test_transitive_merge_via_bridge_record():
    # A carries BOTH keys and acts as a bridge: B (biotools_id only) and C (bioconda_pkg only)
    # both unify with A via union-find, so all three collapse to 1 canonical Method.
    a = _method("m:a", "salmon", pkg="salmon", bt="salmon")  # bridge
    b = _method("m:b", "Salmon", bt="salmon")                # linked to A via bt::salmon
    c = _method("m:c", "Salmon", pkg="salmon")               # linked to A via pkg::salmon
    nodes, edges = resolve(method_nodes=[a, b, c], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 1


def test_transitive_merge_distinct_id_values():
    # Stronger transitivity: B and C share NO direct key with each other.
    # A=(pkg="X", bt="Y"), B=(bt="Y" only), C=(pkg="X" only)
    # B↔A via bt::y, C↔A via pkg::x → B and C merge transitively even with no shared key.
    a = _method("m:a", "toolA", pkg="X", bt="Y")
    b = _method("m:b", "toolB", bt="Y")
    c = _method("m:c", "toolC", pkg="X")
    nodes, edges = resolve(method_nodes=[a, b, c], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 1


def test_two_independent_groups_stay_separate():
    # Two methods with completely different keys must not merge.
    a = _method("m:a", "toolA", pkg="a")
    b = _method("m:b", "toolB", pkg="b")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 2


def test_property_merge_order_is_deterministic():
    """When multiple records share a bioconda_pkg and the canonical lacks a
    property, the smallest-id provider must win deterministically — regardless
    of input list order.

    Group: A (no description), B (description="from-b"), C (description="from-c").
    Canonical id must be "m:a" (lexicographically smallest).
    B's description should win over C's because "m:b" < "m:c".
    Both input orderings [A,B,C] and [C,B,A] must yield identical results.
    """
    def _make_abc():
        a = MethodRecord(id="m:a", name="tool", kind=NodeKind.METHOD,
                         properties={}, provenance=P,
                         bioconda_pkg="x", biotools_id=None)
        b = MethodRecord(id="m:b", name="tool", kind=NodeKind.METHOD,
                         properties={"description": "from-b"}, provenance=P,
                         bioconda_pkg="x", biotools_id=None)
        c = MethodRecord(id="m:c", name="tool", kind=NodeKind.METHOD,
                         properties={"description": "from-c"}, provenance=P,
                         bioconda_pkg="x", biotools_id=None)
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

    # Canonical id is always the lexicographically smallest.
    assert methods1[0].id == "m:a"
    assert methods2[0].id == "m:a"

    # Smallest-id non-canon provider (m:b) fills the missing description first.
    assert methods1[0].properties["description"] == "from-b"
    assert methods2[0].properties["description"] == "from-b"


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


# ---------------------------------------------------------------------------
# Tests for the id-union fix (duplicate-primary-key bug)
# ---------------------------------------------------------------------------

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

    # Description must be stable and from one of the two inputs.
    desc1 = methods1[0].properties.get("description")
    desc2 = methods2[0].properties.get("description")
    assert desc1 in {"desc-a", "desc-b"}
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
