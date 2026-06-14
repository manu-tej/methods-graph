import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.extract.seed import method_ids_matching

P = Provenance("test", "x", "2026-06-14")


def _kw_graph(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"description": "rna quant"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:quant", "Expression quantification", NodeKind.OPERATION, {}, P),
    ]
    edges = [EdgeRecord("m:salmon", "op:quant", EdgeKind.PERFORMS, {}, P)]
    db = tmp_path / "kw.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_ids_matching_direct_name_hit(tmp_path):
    conn = _kw_graph(tmp_path)
    assert method_ids_matching(conn, ["salmon"]) == ["m:salmon"]


def test_method_ids_matching_transitive_via_operation(tmp_path):
    conn = _kw_graph(tmp_path)
    # "quantification" hits the Operation node; the method that PERFORMS it resolves.
    assert "m:salmon" in method_ids_matching(conn, ["quantification"])


def test_provider_delegates_to_helper(tmp_path):
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    db = tmp_path / "kw.kuzu"
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P,
                          bioconda_pkg="salmon", biotools_id="salmon")]
    build_graph(nodes, [], db, staging_dir=tmp_path / "stg")
    with KuzuMethodsGraphProvider(db) as prov:
        assert prov._method_ids_matching(["salmon"]) == method_ids_matching(prov._conn, ["salmon"])
