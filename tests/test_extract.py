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


@pytest.fixture
def conn_with_assumptions(tmp_path):
    """deseq2 -USES-> {Wald test, BH-FDR}; each -REQUIRES_ASSUMPTION-> shared/distinct assumptions."""
    nodes = [
        MethodRecord("m:deseq2", "deseq2", NodeKind.METHOD, {}, P),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("obo:OBI_0200036", "BH FDR", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:independence", "independence", NodeKind.ASSUMPTION, {}, P),
        NodeRecord("assum:asymptotic_normality", "asymptotic normality", NodeKind.ASSUMPTION, {}, P),
    ]
    ev = {"basis": "curated", "evidence": "doi:10.1/x"}
    edges = [
        EdgeRecord("m:deseq2", "obo:STATO_0000559", EdgeKind.USES_STATISTICAL_METHOD, dict(ev), P),
        EdgeRecord("m:deseq2", "obo:OBI_0200036", EdgeKind.USES_STATISTICAL_METHOD, dict(ev), P),
        EdgeRecord("obo:STATO_0000559", "assum:asymptotic_normality",
                   EdgeKind.REQUIRES_ASSUMPTION, dict(ev), P),
        EdgeRecord("obo:STATO_0000559", "assum:independence", EdgeKind.REQUIRES_ASSUMPTION, dict(ev), P),
        EdgeRecord("obo:OBI_0200036", "assum:independence", EdgeKind.REQUIRES_ASSUMPTION, dict(ev), P),
    ]
    db_path = tmp_path / "a.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db_path)))


def test_method_neighborhood_surfaces_statistical_methods(conn_with_assumptions):
    nb = method_neighborhood(conn_with_assumptions, "m:deseq2")
    sm = {s["name"]: s["evidence"] for s in nb["statistical_methods"]}
    assert sm == {"Wald test": "doi:10.1/x", "BH FDR": "doi:10.1/x"}


def test_method_neighborhood_inherits_assumptions_deduped(conn_with_assumptions):
    nb = method_neighborhood(conn_with_assumptions, "m:deseq2")
    by_name = {a["name"]: a for a in nb["assumptions"]}
    # independence is reached via BOTH statistical methods -> one deduped entry, two `via`
    assert set(by_name) == {"independence", "asymptotic normality"}
    assert set(by_name["independence"]["via"]) == {"Wald test", "BH FDR"}
    assert by_name["asymptotic normality"]["via"] == ["Wald test"]
    assert by_name["independence"]["evidence"] == "doi:10.1/x"
