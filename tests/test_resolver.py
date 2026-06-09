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
