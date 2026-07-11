import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.extract.seed import method_ids_matching, method_preconditions

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


def test_method_ids_matching_resolves_via_synonym(tmp_path):
    """End-to-end: a keyword that matches ONLY a node's stored synonyms (not its label)
    still resolves — the whole point of storing EDAM/OBI synonyms in node properties."""
    nodes = [
        MethodRecord("m:foo", "foo", NodeKind.METHOD, {}, P, bioconda_pkg="foo"),
        # label deliberately does NOT contain the acronym; only the synonyms do.
        NodeRecord("op:operation_2436", "Gene-set enrichment analysis", NodeKind.OPERATION,
                   {"synonyms": ["GSEA", "Functional enrichment analysis"]}, P),
    ]
    edges = [EdgeRecord("m:foo", "op:operation_2436", EdgeKind.PERFORMS, {}, P)]
    db = tmp_path / "syn.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    conn = kuzu.Connection(kuzu.Database(str(db)))
    # "GSEA" appears only in the operation's synonyms, yet the performing method resolves.
    assert "m:foo" in method_ids_matching(conn, ["GSEA"])


def test_provider_delegates_to_helper(tmp_path):
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    db = tmp_path / "kw.kuzu"
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P,
                          bioconda_pkg="salmon", biotools_id="salmon")]
    build_graph(nodes, [], db, staging_dir=tmp_path / "stg")
    with KuzuMethodsGraphProvider(db) as prov:
        assert prov._method_ids_matching(["salmon"]) == method_ids_matching(prov._conn, ["salmon"])


# --- P5: typed precondition contract ---

def _precond_graph(tmp_path):
    """m:deseq2 -USES-> Wald -REQUIRES-> asymptotic_normality -CHECKED_BY->
    sample_size_power_check (pre_run, min_replicates_per_group=3)."""
    nodes = [
        MethodRecord("m:deseq2", "deseq2", NodeKind.METHOD, {}, P, bioconda_pkg="deseq2"),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:asymptotic_normality", "asymptotic normality", NodeKind.ASSUMPTION, {}, P),
        NodeRecord("diag:sample_size_power_check", "replicate adequacy", NodeKind.DIAGNOSTIC,
                   {"checkable": "pre_run", "min_replicates_per_group": 3,
                    "applies_to_assumption": "assum:asymptotic_normality"}, P),
    ]
    edges = [
        EdgeRecord("m:deseq2", "obo:STATO_0000559", EdgeKind.USES_STATISTICAL_METHOD,
                   {"evidence": "doi:10.1/deseq2"}, P),
        EdgeRecord("obo:STATO_0000559", "assum:asymptotic_normality", EdgeKind.REQUIRES_ASSUMPTION,
                   {"evidence": "url:wald"}, P),
        EdgeRecord("assum:asymptotic_normality", "diag:sample_size_power_check", EdgeKind.CHECKED_BY,
                   {"evidence": "doi:10.1/floor"}, P),
    ]
    db = tmp_path / "pc.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_preconditions_returns_assumption_with_threshold_and_diagnostic(tmp_path):
    conn = _precond_graph(tmp_path)
    pc = method_preconditions(conn, "m:deseq2")
    assert pc["method_id"] == "m:deseq2"
    a = pc["assumptions"][0]
    assert a["name"] == "asymptotic normality"
    assert a["source"] == "used"
    assert a["evidence"] == "url:wald"
    assert a["checkable"] == "pre_run"
    assert a["threshold"] == {"min_replicates_per_group": 3}
    assert a["diagnostics"] == ["diag:sample_size_power_check"]
    # flat diagnostics list carries name + the assumptions it checks
    d = pc["diagnostics"][0]
    assert d["id"] == "diag:sample_size_power_check"
    assert d["checks"] == ["asymptotic normality"]
    assert d["min_replicates_per_group"] == 3


def test_method_preconditions_unknown_method_raises_keyerror(tmp_path):
    conn = _precond_graph(tmp_path)
    with pytest.raises(KeyError):
        method_preconditions(conn, "m:nope")


def _amenable_precond_graph(tmp_path):
    """m:bcftools -PERFORMS-> Variant calling -AMENABLE_TO-> Fisher -REQUIRES->
    independence -CHECKED_BY-> design_batch_review (post_run). Plus a SECOND, pre_run
    diagnostic on the same assumption to exercise checkable precedence + the (id,source)
    keying when the same assumption is also reached via a USES link."""
    nodes = [
        MethodRecord("m:bcftools", "bcftools", NodeKind.METHOD, {}, P, bioconda_pkg="bcftools"),
        NodeRecord("op:operation_3227", "Variant calling", NodeKind.OPERATION, {}, P),
        NodeRecord("obo:STATO_0000073", "Fisher's exact test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:independence", "independence", NodeKind.ASSUMPTION, {}, P),
        NodeRecord("diag:design_batch_review", "batch review", NodeKind.DIAGNOSTIC,
                   {"checkable": "post_run"}, P),
        NodeRecord("diag:pre_check", "pre check", NodeKind.DIAGNOSTIC, {"checkable": "pre_run"}, P),
    ]
    edges = [
        EdgeRecord("m:bcftools", "op:operation_3227", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("op:operation_3227", "obo:STATO_0000073", EdgeKind.AMENABLE_TO,
                   {"evidence": "doi:10.1086/519795"}, P),
        EdgeRecord("obo:STATO_0000073", "assum:independence", EdgeKind.REQUIRES_ASSUMPTION,
                   {"evidence": "isbn:x"}, P),
        EdgeRecord("assum:independence", "diag:design_batch_review", EdgeKind.CHECKED_BY,
                   {"evidence": "doi:10.1038/nrg2825"}, P),
        EdgeRecord("assum:independence", "diag:pre_check", EdgeKind.CHECKED_BY,
                   {"evidence": "doi:10.1038/nrg2825"}, P),
    ]
    db = tmp_path / "amp.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_preconditions_operation_mediated_path(tmp_path):
    """The scalable path: a method with NO USES link still gets preconditions via
    PERFORMS->AMENABLE_TO, tagged source='amenable' with an operation-keyed via."""
    conn = _amenable_precond_graph(tmp_path)
    pc = method_preconditions(conn, "m:bcftools")
    assert [a["source"] for a in pc["assumptions"]] == ["amenable"]
    a = pc["assumptions"][0]
    assert a["name"] == "independence"
    assert a["via"][0]["operation"] == "Variant calling"
    # via evidence is the REQUIRES_ASSUMPTION grounding (what grounds the assumption)
    assert a["via"][0]["evidence"] == "isbn:x"
    # checkable precedence: a pre_run diagnostic wins over a post_run one for the assumption
    assert a["checkable"] == "pre_run"
    assert set(a["diagnostics"]) == {"diag:design_batch_review", "diag:pre_check"}


def test_method_preconditions_applies_to_assumption_surfaced(tmp_path):
    """The flat diagnostics list carries applies_to_assumption (guards seed.py:342)."""
    conn = _precond_graph(tmp_path)
    pc = method_preconditions(conn, "m:deseq2")
    assert pc["diagnostics"][0]["applies_to_assumption"] == "assum:asymptotic_normality"


def _multi_diag_precond_graph(tmp_path, diags):
    """m:foo -USES-> Wald -REQUIRES-> assum:y -CHECKED_BY-> each (diag_id, props)."""
    nodes = [
        MethodRecord("m:foo", "foo", NodeKind.METHOD, {}, P, bioconda_pkg="foo"),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:y", "y", NodeKind.ASSUMPTION, {}, P),
    ] + [NodeRecord(did, did.split(":")[-1], NodeKind.DIAGNOSTIC, props, P) for did, props in diags]
    edges = [
        EdgeRecord("m:foo", "obo:STATO_0000559", EdgeKind.USES_STATISTICAL_METHOD,
                   {"evidence": "doi:1"}, P),
        EdgeRecord("obo:STATO_0000559", "assum:y", EdgeKind.REQUIRES_ASSUMPTION,
                   {"evidence": "url:x"}, P),
    ] + [EdgeRecord("assum:y", did, EdgeKind.CHECKED_BY, {"evidence": "doi:1"}, P)
         for did, _ in diags]
    db = tmp_path / "md.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_preconditions_threshold_uses_strictest_floor(tmp_path):
    """When two diagnostics disagree on min_replicates_per_group, the STRICTEST (max)
    floor wins — order-independently. diag:b_loose sorts LAST by id, so last-writer-wins
    would wrongly pick 2; the max() rule must yield 5."""
    conn = _multi_diag_precond_graph(tmp_path, [
        ("diag:a_strict", {"min_replicates_per_group": 5}),
        ("diag:b_loose", {"min_replicates_per_group": 2}),   # sorts last by d.id
    ])
    pc = method_preconditions(conn, "m:foo")
    assert pc["assumptions"][0]["threshold"] == {"min_replicates_per_group": 5}


def test_method_preconditions_checkable_precedence_is_order_independent(tmp_path):
    """pre_run must win over post_run regardless of diagnostic id order. diag:z_post
    (post_run) sorts LAST, so last-writer-wins would wrongly pick post_run."""
    conn = _multi_diag_precond_graph(tmp_path, [
        ("diag:a_pre", {"checkable": "pre_run"}),     # sorts first
        ("diag:z_post", {"checkable": "post_run"}),   # sorts last
    ])
    pc = method_preconditions(conn, "m:foo")
    assert pc["assumptions"][0]["checkable"] == "pre_run"
