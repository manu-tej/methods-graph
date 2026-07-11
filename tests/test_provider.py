# tests/test_provider.py
import pathlib
import types
import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

_DB_PATH = pathlib.Path("data/methods.kuzu")

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


# ---------------------------------------------------------------------------
# quration methods-graph lane: resolve_method_ids + neighborhood
# ---------------------------------------------------------------------------

@pytest.fixture
def db_grounded(tmp_path):
    """A method grounded with a statistical method + transitive assumption."""
    nodes = [
        MethodRecord("m:deseq2", "deseq2", NodeKind.METHOD, {}, P,
                     bioconda_pkg="deseq2", biotools_id="deseq2"),
        NodeRecord("sm:wald", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:normality", "asymptotic normality", NodeKind.ASSUMPTION, {}, P),
    ]
    edges = [
        EdgeRecord("m:deseq2", "sm:wald", EdgeKind.USES_STATISTICAL_METHOD,
                   {"evidence": "doi:10.1/x"}, P),
        EdgeRecord("sm:wald", "assum:normality", EdgeKind.REQUIRES_ASSUMPTION,
                   {"evidence": "doi:10.1/y"}, P),
    ]
    path = tmp_path / "g.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    return path


def test_resolve_method_ids_returns_matching_ids(db_path):
    with KuzuMethodsGraphProvider(db_path) as p:
        assert p.resolve_method_ids(["salmon"]) == ["m:salmon"]
        assert p.resolve_method_ids(["no_such_tool_xyz"]) == []


def test_neighborhood_returns_stats_and_assumptions(db_grounded):
    with KuzuMethodsGraphProvider(db_grounded) as p:
        nb = p.neighborhood("m:deseq2")
        # shape the quration methods-eval lane reads: name + evidence / name + via
        sm = nb["statistical_methods"]
        assert any(s["name"] == "Wald test" and s["evidence"] == "doi:10.1/x" for s in sm)
        a = nb["assumptions"]
        match = next(x for x in a if x["name"] == "asymptotic normality")
        assert match["via"] and match["via"][0]["statistical_method"] == "Wald test"


def test_neighborhood_unknown_method_raises_keyerror(db_path):
    with KuzuMethodsGraphProvider(db_path) as p:
        with pytest.raises(KeyError):
            p.neighborhood("m:does_not_exist")


# ---------------------------------------------------------------------------
# Proteomics evaluability integration tests (Task 6)
# Require the built DB artifact at data/methods.kuzu — skipped if absent.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _DB_PATH.exists(), reason="DB not built")
def test_percolator_grounds_target_decoy_contract():
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider as _P
    with _P(_DB_PATH) as p:
        pre = p.method_preconditions("m:percolator")
        anames = {a["name"] for a in pre["assumptions"]}
        dnames = {d["name"] for d in pre["diagnostics"]}
    assert any("decoy" in n.lower() for n in anames)
    assert any("score-distribution overlap" in n.lower() for n in dnames)
    # the RNA-seq dispersion plot must NOT appear for a proteomics identification tool
    assert not any("dispersion" in n.lower() for n in dnames)
    diag_ids = [d["id"] for d in pre["diagnostics"]]
    assert not any("dispersion" in d for d in diag_ids)


@pytest.mark.skipif(not _DB_PATH.exists(), reason="DB not built")
def test_maxquant_no_dispersion_has_decoy():
    """maxquant (the original bug locus) must not leak dispersion diagnostics
    and must surface a decoy assumption after re-pointing to target_decoy_fdr."""
    with KuzuMethodsGraphProvider(_DB_PATH) as p:
        pre = p.method_preconditions("m:maxquant")
    diag_ids = [d["id"] for d in pre["diagnostics"]]
    assert not any("dispersion" in d for d in diag_ids), (
        "maxquant must not expose dispersion diagnostics (re-pointing bug regression)")
    assum_ids = [a["id"] for a in pre["assumptions"]]
    assert any("decoy" in a for a in assum_ids), (
        "maxquant must expose a decoy assumption via target_decoy_fdr")


def test_proteomics_assumptions_do_not_leak_to_rnaseq_methods():
    import pathlib
    db = pathlib.Path("data/methods.kuzu")
    if not db.exists():
        import pytest; pytest.skip("built DB artifact not present")
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider as _P
    leak_terms = ("decoy", "missing", "quantification linear", "peptide")
    with _P(db) as p:
        for mid in ("m:deseq2", "m:salmon"):
            pre = p.method_preconditions(mid)
            anames = {a["name"].lower() for a in pre["assumptions"]}
            assert not any(t in n for n in anames for t in leak_terms), \
                f"{mid} leaked: {anames}"


# ---------------------------------------------------------------------------
# Task 6: quration skill lane — resolve_skill_ids + skill_preconditions
# ---------------------------------------------------------------------------

def test_provider_skill_preconditions_and_resolve(tmp_path):
    import pathlib
    db = pathlib.Path("data/methods.kuzu")
    if not db.exists():
        import pytest; pytest.skip("built DB artifact not present")
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    with KuzuMethodsGraphProvider(db) as p:
        ids = p.resolve_skill_ids(["differential", "expression"])
        assert "skill:bioclaw/differential-expression" in ids
        pre = p.skill_preconditions("skill:bioclaw/differential-expression")
        assert pre["method_id"] == "skill:bioclaw/differential-expression"
        assert any("normal" in a["name"].lower() for a in pre["assumptions"])


def test_resolve_skill_ids_no_match_and_does_not_match_property_keys(tmp_path):
    """resolve_skill_ids matches Skill name + description VALUES only — it must return
    [] for an unmatched keyword and for empty input, and must NOT match on the literal
    JSON property KEYS ('primary_tool', 'source', 'description') that the Skill node
    serialises in its properties blob."""
    db = pathlib.Path("data/methods.kuzu")
    if not db.exists():
        pytest.skip("built DB artifact not present")
    with KuzuMethodsGraphProvider(db) as p:
        assert p.resolve_skill_ids(["zzznotarealkeyword"]) == []
        assert p.resolve_skill_ids([]) == []
        assert p.resolve_skill_ids([""]) == []
        # Property KEYS of the serialised node must never be treated as searchable text.
        # ('description'/'domain' are excluded — those happen to be real English words in
        # some skill descriptions; 'primary_tool'/'source' are pure serialisation keys.)
        for key in ("primary_tool", "source"):
            assert p.resolve_skill_ids([key]) == [], f"{key} key leaked into match"
        # A real description token DOES resolve, and the result is sorted/deduped.
        ids = p.resolve_skill_ids(["differential", "expression"])
        assert "skill:bioclaw/differential-expression" in ids
        assert ids == sorted(set(ids))


def test_skill_preconditions_skips_keyerror_wraps_targets():
    """A WRAPS target whose method_preconditions raises KeyError (stale / evaluability-less
    edge) is skipped — not propagated — so the quration-facing path matches the guardrail's
    resilient skill path and `skills --coverage` can't crash on one bad edge. No DB needed."""
    class _P(KuzuMethodsGraphProvider):
        def __init__(self):                       # bypass DB connection
            pass
        def skill_wraps_method_ids(self, skill_id):
            return ["m:ok", "m:gone"]
        def method_preconditions(self, method_id):
            if method_id == "m:gone":
                raise KeyError(method_id)
            return {"method_id": method_id, "assumptions": [
                {"id": "a1", "name": "adequate replicates", "source": "used",
                 "checkable": "pre_run", "threshold": {"min_replicates_per_group": 3},
                 "diagnostics": [], "evidence": "", "via": []}], "diagnostics": []}
    out = _P().skill_preconditions("skill:test/s")
    assert out["method_id"] == "skill:test/s"
    assert len(out["assumptions"]) == 1           # m:ok survives, m:gone skipped, no crash


# ---------------------------------------------------------------------------
# Single-cell evaluability — scanpy worked example + leakage guards (DB-gated)
# ---------------------------------------------------------------------------

def _threshold_blob(pre):
    """All non-empty assumption thresholds of a method_preconditions dict, as one string."""
    return str([a.get("threshold") for a in pre["assumptions"] if a.get("threshold")])


@pytest.mark.skipif(not _DB_PATH.exists(), reason="DB not built")
def test_scanpy_gains_single_cell_contract_and_drops_bulk_replicate_gate():
    with KuzuMethodsGraphProvider(_DB_PATH) as p:
        pre = p.method_preconditions("m:scanpy")
    anames = {a["name"].lower() for a in pre["assumptions"]}
    # scanpy now carries the single-cell clustering contract...
    assert any("unsupervised" in n or "raw umi" in n or "adaptive" in n for n in anames), anames
    # ...and NO bulk per-group replicate floor leaks in via the old operation_3223 chain.
    assert "replicates_per_group" not in _threshold_blob(pre), \
        f"scanpy still carries a replicate gate: {_threshold_blob(pre)}"


@pytest.mark.skipif(not _DB_PATH.exists(), reason="DB not built")
def test_single_cell_assumptions_do_not_leak_to_bulk_methods():
    sc_terms = ("raw umi", "adaptive", "unsupervised", "cluster", "highly-variable", "variance stab")
    with KuzuMethodsGraphProvider(_DB_PATH) as p:
        for mid in ("m:deseq2", "m:salmon"):
            anames = {a["name"].lower() for a in p.method_preconditions(mid)["assumptions"]}
            assert not any(t in n for n in anames for t in sc_terms), f"{mid} leaked sc assumptions: {anames}"
        # the bulk replicate floor is unchanged on deseq2 (the correction did not weaken bulk DE)
        assert "replicates_per_group" in _threshold_blob(p.method_preconditions("m:deseq2"))
