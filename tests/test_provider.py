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


# ---------------------------------------------------------------------------
# AnalysisMethod enrichment (TDD — new behaviour)
#
# get_methods() must emit dicts that are COMPLETE enough to construct a quration
# AnalysisMethod without further enrichment: a category, modalities mapped to
# quration's DataModality *value* vocabulary, input/output lists, and quality
# metrics. quration is not installed in this venv, so we assert on the dict shape
# here; full AnalysisMethod construction is proven in the quration repo.
# ---------------------------------------------------------------------------

# Required AnalysisMethod fields that have no default and must be present in the
# emitted dict for AnalysisMethod(**d) to validate.
REQUIRED_METHOD_KEYS = {
    "id", "name", "category", "description", "implementation_type", "version",
    "inputs", "outputs", "supported_modalities", "quality_metrics",
}


def test_get_methods_dict_has_all_required_fields(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    missing = REQUIRED_METHOD_KEYS - salmon.keys()
    assert not missing, f"emitted method dict missing required keys: {missing}"


def test_get_methods_maps_topic_to_modality_value(db_path):
    """EDAM topic 'RNA-Seq' must become the quration DataModality value 'rna_seq'."""
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    assert salmon["supported_modalities"] == ["rna_seq"], salmon["supported_modalities"]
    # human-readable topic label is preserved separately in tags
    assert "RNA-Seq" in salmon["tags"]


def test_get_methods_derives_category(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    assert salmon["category"] == "rna_seq", salmon["category"]


def test_get_methods_quality_metrics_shape(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    qm = salmon["quality_metrics"]
    assert {"reproducibility_score", "code_availability", "documentation_quality"} <= qm.keys()
    assert 0.0 <= qm["reproducibility_score"] <= 1.0
    # salmon has a container → packaging is reproducible → code is available
    assert qm["code_availability"] is True


def test_get_methods_inputs_outputs_are_lists(db_path):
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    assert isinstance(salmon["inputs"], list)
    assert isinstance(salmon["outputs"], list)


# --- pure mapping helpers (no graph / no quration needed) ------------------

def test_map_modalities_known_and_unknown():
    from methods_graph.provider.quration_provider import _map_modalities
    assert _map_modalities(["RNA-Seq"]) == ["rna_seq"]
    assert _map_modalities(["ChIP-seq"]) == ["chip_seq"]
    # unknown topics are dropped, not guessed
    assert _map_modalities(["Phylogenetics"]) == []
    # de-duplicated, order-stable
    assert _map_modalities(["RNA-Seq", "RNA-Seq"]) == ["rna_seq"]


def test_derive_category_known_and_default():
    from methods_graph.provider.quration_provider import _derive_category
    assert _derive_category(["RNA-Seq"]) == "rna_seq"
    assert _derive_category(["Sequence assembly"]) == "assembly"
    # no recognisable topic → custom (never silently mislabel)
    assert _derive_category(["Phylogenetics"]) == "custom"
    assert _derive_category([]) == "custom"


def test_build_analysis_method_happy_path(db_path):
    """When quration IS installed, the enriched dict constructs a valid AnalysisMethod."""
    pytest.importorskip("quration")
    from methods_graph.provider.quration_provider import build_analysis_method
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    method = build_analysis_method(salmon)
    assert method.id == "m:salmon"
    assert method.category.value == "rna_seq"
