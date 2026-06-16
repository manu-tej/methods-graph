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
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/salmon:1.10.0"}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
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
        assert "Read summarisation" in salmon["tags"]  # tags = operation labels (topics removed)
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


def test_get_methods_category_and_modalities_default(db_path):
    """The Topic layer was removed, so category/modalities fall back to defaults."""
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    assert salmon["category"] == "custom", salmon["category"]
    assert salmon["supported_modalities"] == [], salmon["supported_modalities"]


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


def test_build_analysis_method_happy_path(db_path):
    """When quration IS installed, the enriched dict constructs a valid AnalysisMethod."""
    pytest.importorskip("quration")
    from methods_graph.provider.quration_provider import build_analysis_method
    with KuzuMethodsGraphProvider(db_path) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    method = build_analysis_method(salmon)
    assert method.id == "m:salmon"
    assert method.category.value == "custom"  # Topic layer removed -> default category


# ---------------------------------------------------------------------------
# I/O edges — populate inputs/outputs from EDAM Data/Format nodes (TDD)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path_with_io(tmp_path):
    """Graph where salmon has INPUT->FASTQ(Format) and OUTPUT->JSON(Format) edges."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                     {"version": "1.10.0", "description": "quant", "implementation_type": "nextflow"},
                     P, bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("fmt:format_1930", "FASTQ", NodeKind.FORMAT, {}, P),
        NodeRecord("fmt:format_3464", "JSON", NodeKind.FORMAT, {}, P),
        # A second method with NO I/O edges, to verify back-compat empty lists.
        MethodRecord("m:fastp", "fastp", NodeKind.METHOD,
                     {"version": "0.23.0", "description": "qc", "implementation_type": "tool"},
                     P),
    ]
    edges = [
        EdgeRecord("m:salmon", "fmt:format_1930", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:salmon", "fmt:format_3464", EdgeKind.OUTPUT, {}, P),
    ]
    path = tmp_path / "io.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    return path


def test_get_methods_populates_inputs_outputs(db_path_with_io):
    with KuzuMethodsGraphProvider(db_path_with_io) as provider:
        methods = provider.get_methods()

    salmon = next(m for m in methods if m["name"] == "salmon")
    fastp = next(m for m in methods if m["name"] == "fastp")

    # salmon inputs
    assert len(salmon["inputs"]) == 1
    inp = salmon["inputs"][0]
    assert inp["name"] == "FASTQ"
    assert inp["data_type"] == "FASTQ"
    assert inp["required"] is True
    assert inp["multiple"] is False
    assert "description" in inp

    # salmon outputs
    assert len(salmon["outputs"]) == 1
    out = salmon["outputs"][0]
    assert out["name"] == "JSON"
    assert out["data_type"] == "JSON"
    assert "description" in out

    # fastp has no I/O edges → empty lists (back-compat)
    assert fastp["inputs"] == []
    assert fastp["outputs"] == []


def test_get_methods_io_description_contains_kind(db_path_with_io):
    """description must follow the 'EDAM <kind>: <name>' pattern."""
    with KuzuMethodsGraphProvider(db_path_with_io) as provider:
        salmon = next(m for m in provider.get_methods() if m["name"] == "salmon")
    assert "Format" in salmon["inputs"][0]["description"]
    assert "FASTQ" in salmon["inputs"][0]["description"]
    assert "Format" in salmon["outputs"][0]["description"]
    assert "JSON" in salmon["outputs"][0]["description"]


def test_get_methods_io_deduped_and_sorted(tmp_path):
    """Duplicate I/O edges (same name+data_type) should be collapsed; output sorted by name."""
    nodes = [
        MethodRecord("m:tool", "tool", NodeKind.METHOD,
                     {"version": "1", "description": "x", "implementation_type": "tool"}, P),
        NodeRecord("fmt:a", "AAA", NodeKind.FORMAT, {}, P),
        NodeRecord("fmt:b", "BBB", NodeKind.FORMAT, {}, P),
        NodeRecord("fmt:a2", "AAA", NodeKind.FORMAT, {}, P),  # duplicate name
    ]
    edges = [
        EdgeRecord("m:tool", "fmt:b", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:tool", "fmt:a", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:tool", "fmt:a2", EdgeKind.INPUT, {}, P),  # same name as fmt:a → deduped
    ]
    path = tmp_path / "dup.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    with KuzuMethodsGraphProvider(path) as provider:
        tool = next(m for m in provider.get_methods() if m["name"] == "tool")
    names = [i["name"] for i in tool["inputs"]]
    # deduped: only 2 unique (name, data_type) pairs
    assert names == sorted(set(names)), "inputs must be sorted and deduped"
    assert len(names) == 2  # AAA and BBB


@pytest.fixture
def assum_db_path(tmp_path):
    """deseq2 -USES_STATISTICAL_METHOD-> Wald test -REQUIRES_ASSUMPTION-> normality.
    'normality' is a TWO-HOP inherited assumption from the method."""
    nodes = [
        MethodRecord("m:deseq2", "deseq2", NodeKind.METHOD,
                     {"description": "differential expression"}, P),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:normality", "normality", NodeKind.ASSUMPTION, {}, P),
    ]
    ev = {"basis": "curated", "evidence": "doi:10.1/x"}
    edges = [
        EdgeRecord("m:deseq2", "obo:STATO_0000559", EdgeKind.USES_STATISTICAL_METHOD, dict(ev), P),
        EdgeRecord("obo:STATO_0000559", "assum:normality", EdgeKind.REQUIRES_ASSUMPTION, dict(ev), P),
    ]
    path = tmp_path / "assum.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    return path


def test_retrieve_surfaces_inherited_assumption_and_path(assum_db_path):
    """A keyword matching a 2-hop inherited assumption surfaces the assumption AND
    its StatisticalMethod path in the RAG context (default 1-hop seed would omit it)."""
    with KuzuMethodsGraphProvider(assum_db_path) as p:
        ctx = p.retrieve_context_for_keywords(["normality"])
    assert "normality" in ctx, f"matched 2-hop assumption missing from context:\n{ctx}"
    assert "Wald test" in ctx, f"StatisticalMethod on the path missing:\n{ctx}"
    assert "REQUIRES_ASSUMPTION" in ctx, f"StatMethod->Assumption edge missing:\n{ctx}"
    assert "USES_STATISTICAL_METHOD" in ctx, f"Method->StatMethod edge missing:\n{ctx}"
