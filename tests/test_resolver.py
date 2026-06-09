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
