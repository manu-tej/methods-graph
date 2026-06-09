# tests/test_provider.py
import types
import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

P = Provenance("test", "x", "2026-06-08")


@pytest.fixture
def db_path(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                     {"version": "1.10.0", "description": "quant", "implementation_type": "nextflow"},
                     P, bioconda_pkg="salmon", biotools_id="salmon"),
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
    path = tmp_path / "m.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    return path


def test_get_methods_returns_method_dicts(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
        salmon = next(m for m in methods if m["name"] == "salmon")
        assert salmon["id"] == "m:salmon"
        assert salmon["implementation_type"] == "nextflow"
        assert "RNA-Seq" in salmon["tags"]
        assert salmon["compute_requirements"]["container_image"].endswith("salmon:1.10.0")


def test_retrieve_context_grounds_on_keywords(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        ctx = provider.retrieve_context_for_keywords(["salmon"])
        assert "salmon" in ctx
        assert "Read summarisation" in ctx


def test_score_method_is_neutral_in_mvp(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        assert provider.score_method("m:salmon", keywords=["salmon"]) == 0.0


def test_retrieve_context_duck_types_parsed_request(db_path):
    req = types.SimpleNamespace(keywords=["salmon"], original_query="")
    with KuzuMethodsGraphProvider(db_path) as provider:
        result = provider.retrieve_context(req)
    assert "salmon" in result


def test_retrieve_context_falls_back_to_original_query(db_path):
    req = types.SimpleNamespace(keywords=[], original_query="salmon quant")
    with KuzuMethodsGraphProvider(db_path) as provider:
        result = provider.retrieve_context(req)
    assert len(result) > 0
    assert "salmon" in result


def test_build_analysis_method_requires_quration():
    from methods_graph.provider.quration_provider import build_analysis_method
    with pytest.raises(RuntimeError, match="quration is not installed"):
        build_analysis_method({"id": "m:salmon", "name": "salmon"})


# ---------------------------------------------------------------------------
# Broad keyword retrieval tests (TDD — new behaviour)
# ---------------------------------------------------------------------------

def test_retrieve_matches_via_topic_label(db_path):
    """'RNA-Seq' matches Topic node 'RNA-Seq'; should resolve back to salmon Method."""
    with KuzuMethodsGraphProvider(db_path) as p:
        ctx = p.retrieve_context_for_keywords(["RNA-Seq"])
    assert ctx != "", "Expected non-empty context via topic match"
    assert "salmon" in ctx, "Expected salmon to appear in context via HAS_TOPIC → RNA-Seq"


def test_retrieve_matches_via_operation_label(db_path):
    """'summarisation' is a substring of 'Read summarisation'; should resolve to salmon."""
    with KuzuMethodsGraphProvider(db_path) as p:
        ctx = p.retrieve_context_for_keywords(["summarisation"])
    assert ctx != "", "Expected non-empty context via operation match"
    assert "salmon" in ctx, "Expected salmon to appear in context via PERFORMS → Read summarisation"


def test_retrieve_matches_via_description(db_path):
    """'quant' is in the method properties description; direct property match."""
    with KuzuMethodsGraphProvider(db_path) as p:
        ctx = p.retrieve_context_for_keywords(["quant"])
    assert ctx != "", "Expected non-empty context via description match"
    assert "salmon" in ctx, "Expected salmon to appear in context via description containing 'quant'"


def test_retrieve_matches_via_container_name(db_path):
    """'biocontainers' is a substring of the container image name; should resolve to salmon."""
    with KuzuMethodsGraphProvider(db_path) as p:
        ctx = p.retrieve_context_for_keywords(["biocontainers"])
    assert ctx != "", "Expected non-empty context via container name match"
    assert "salmon" in ctx, "Expected salmon to appear in context via PACKAGED_AS → quay.io/biocontainers/salmon"


def test_retrieve_no_match_returns_empty(db_path):
    """A keyword that matches nothing should return empty string."""
    with KuzuMethodsGraphProvider(db_path) as p:
        ctx = p.retrieve_context_for_keywords(["zzznotarealthing"])
    assert ctx == "", "Expected empty string when no keyword matches anything"


def test_method_ids_matching_is_deterministic(db_path):
    """Two successive calls to _method_ids_matching must return identical lists."""
    with KuzuMethodsGraphProvider(db_path) as p:
        first = p._method_ids_matching(["RNA-Seq"])
        second = p._method_ids_matching(["RNA-Seq"])
    assert first == second, (
        f"_method_ids_matching returned different results across calls: {first!r} vs {second!r}"
    )
