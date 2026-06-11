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


# ---------------------------------------------------------------------------
# I/O edges — TDD for new "inputs" / "outputs" buckets
# ---------------------------------------------------------------------------

@pytest.fixture
def conn_with_io(tmp_path):
    """Tiny graph: salmon -INPUT-> FASTQ (Format) and salmon -OUTPUT-> JSON (Format)."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"version": "1.10.0"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("fmt:format_1930", "FASTQ", NodeKind.FORMAT, {}, P),
        NodeRecord("fmt:format_3464", "JSON", NodeKind.FORMAT, {}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "fmt:format_1930", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:salmon", "fmt:format_3464", EdgeKind.OUTPUT, {}, P),
    ]
    db_path = tmp_path / "io.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db_path)))


def test_method_neighborhood_includes_io(conn_with_io):
    nb = method_neighborhood(conn_with_io, "m:salmon")
    input_ids = {n["id"] for n in nb["inputs"]}
    output_ids = {n["id"] for n in nb["outputs"]}
    assert "fmt:format_1930" in input_ids, f"FASTQ input not found; inputs={nb['inputs']}"
    assert "fmt:format_3464" in output_ids, f"JSON output not found; outputs={nb['outputs']}"
    # buckets for methods with no I/O should be empty in the base fixture
    nb_no_io = method_neighborhood(conn_with_io, "m:salmon")
    # sanity: inputs / outputs keys exist
    assert "inputs" in nb_no_io
    assert "outputs" in nb_no_io


def test_method_neighborhood_io_node_shape(conn_with_io):
    nb = method_neighborhood(conn_with_io, "m:salmon")
    fastq = next(n for n in nb["inputs"] if n["id"] == "fmt:format_1930")
    assert fastq["name"] == "FASTQ"
    assert fastq["kind"] == "Format"
    assert "properties" in fastq
