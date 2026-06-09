import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph

P = Provenance("test", "x", "2026-06-08")


def test_build_graph_loads_nodes_and_edges(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"version": "1.10.0"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
    ]
    edges = [EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P)]
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    res = conn.execute("MATCH (m:Entity {kind:'Method'})-[r:Rel]->(o:Entity) "
                       "RETURN m.id, r.kind, o.id")
    rows = [row for row in res]
    assert ["m:salmon", "PERFORMS", "op:operation_3798"] in rows


def test_build_graph_is_idempotent(tmp_path):
    nodes = [NodeRecord("op:x", "X", NodeKind.OPERATION, {}, P)]
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")   # rebuild, no error
    conn = kuzu.Connection(kuzu.Database(str(db_path)))
    count = [r for r in conn.execute("MATCH (n:Entity) RETURN count(n)")][0][0]
    assert count == 1
