import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.extract.seed import Subgraph, seed, method_neighborhood

P = Provenance("test", "x", "2026-06-08")


@pytest.fixture
def conn(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"version": "1.10.0"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_3170", "RNA-Seq", NodeKind.TOPIC, {}, P),
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/salmon:1.10.0"}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "topic:topic_3170", EdgeKind.HAS_TOPIC, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P),
    ]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db_path)))


def test_seed_one_hop_returns_neighbors(conn):
    sg = seed(conn, ["m:salmon"], k_hops=1)
    ids = {n["id"] for n in sg.nodes}
    assert {"m:salmon", "op:operation_3798", "topic:topic_3170", "ctr:salmon"} <= ids


def test_method_neighborhood_groups_by_edge_kind(conn):
    nb = method_neighborhood(conn, "m:salmon")
    assert nb["method"]["name"] == "salmon"
    assert any(o["id"] == "op:operation_3798" for o in nb["operations"])
    assert any(t["id"] == "topic:topic_3170" for t in nb["topics"])
    assert any(c["id"] == "ctr:salmon" for c in nb["containers"])


def test_seed_empty_returns_empty(conn):
    sg = seed(conn, [])
    assert sg.nodes == []
    assert sg.edges == []


def test_seed_missing_id_is_graceful(conn):
    sg = seed(conn, ["nonexistent"])
    assert sg.nodes == []
    assert sg.edges == []


def test_method_neighborhood_missing_raises(conn):
    with pytest.raises(KeyError):
        method_neighborhood(conn, "m:nope")
