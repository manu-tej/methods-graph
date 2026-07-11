"""Tests for the assumption-diagnostic layer: Assumption -CHECKED_BY-> Diagnostic
(the test/plot/procedure that checks whether the data meets an assumption)."""
from __future__ import annotations

import pytest

from methods_graph.crosslinks.assumption_diagnostics import (
    DiagnosticDef, build_diagnostic_records, load_assumption_diagnostics,
)
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-17")


def _nodes(*specs):
    return [NodeRecord(i, i.split(":")[-1], k, {}, P) for i, k in specs]


@pytest.fixture
def shipped_defs():
    return load_assumption_diagnostics()


@pytest.fixture
def assum_nodes(shipped_defs):
    """Assumption nodes for every assumption referenced in the shipped YAML."""
    ids = {a for d in shipped_defs for a in d.checks}
    return [NodeRecord(i, i.split(":")[-1], NodeKind.ASSUMPTION, {}, P) for i in sorted(ids)]


# --- shipped YAML ---


def test_shipped_yaml_loads_and_grounds_key_diagnostics():
    defs = load_assumption_diagnostics()
    by = {d.diag_id: d for d in defs}
    sw = by["diag:shapiro_wilk"]
    assert "assum:asymptotic_normality" in sw.checks
    assert sw.ref.startswith(("doi:", "pmid:", "url:", "isbn:"))
    # every diagnostic carries grounding evidence
    assert all(d.ref.startswith(("doi:", "pmid:", "url:", "isbn:")) for d in defs)


def test_shipped_sample_size_check_carries_machine_readable_threshold():
    """P2: the replicate floor + pre-run flag are structured, not prose-only."""
    by = {d.diag_id: d for d in load_assumption_diagnostics()}
    ssc = by["diag:sample_size_power_check"]
    assert ssc.checkable == "pre_run"
    assert ssc.min_replicates_per_group == 3
    assert ssc.applies_to_assumption == "assum:asymptotic_normality"


def test_structured_fields_emitted_onto_diagnostic_node():
    """P2: build_diagnostic_records surfaces the structured fields as node props."""
    nodes = _nodes(("assum:asymptotic_normality", NodeKind.ASSUMPTION))
    d = DiagnosticDef("diag:ssc", "SSC", "procedure", "h", ("assum:asymptotic_normality",),
                      "doi:1", checkable="pre_run",
                      applies_to_assumption="assum:asymptotic_normality",
                      min_replicates_per_group=3)
    dn, _edges, _rep = build_diagnostic_records(nodes, ingested_at="2026-06-17", defs=[d])
    assert dn[0].properties["checkable"] == "pre_run"
    assert dn[0].properties["min_replicates_per_group"] == 3
    assert dn[0].properties["applies_to_assumption"] == "assum:asymptotic_normality"


def test_bad_checkable_raises():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test", "checks": ["normality"],
            "ref": "doi:1", "checkable": "sometimes"}}}
    with pytest.raises(ValueError, match="checkable"):
        load_assumption_diagnostics(spec=spec)


def test_applies_to_assumption_must_be_among_checks():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test", "checks": ["normality"],
            "ref": "doi:1", "applies_to_assumption": "independence"}}}
    with pytest.raises(ValueError, match="applies_to_assumption"):
        load_assumption_diagnostics(spec=spec)


def test_non_positive_min_replicates_raises():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test", "checks": ["normality"],
            "ref": "doi:1", "min_replicates_per_group": 0}}}
    with pytest.raises(ValueError, match="min_replicates_per_group"):
        load_assumption_diagnostics(spec=spec)


def test_unknown_assumption_slug_is_normalised_to_id():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test",
            "checks": ["normality"], "ref": "doi:1"}}}
    defs = load_assumption_diagnostics(spec=spec)
    assert defs[0].checks == ("assum:normality",)


def test_missing_ref_raises():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test", "checks": ["normality"]}}}
    with pytest.raises(ValueError, match="ref"):
        load_assumption_diagnostics(spec=spec)


def test_scalar_checks_raises_clear_list_error():
    spec = {"diagnostics": {"x": {"name": "X", "kind": "test",
            "checks": "normality", "ref": "doi:1"}}}
    with pytest.raises(ValueError, match="must be a list"):
        load_assumption_diagnostics(spec=spec)


# --- grounded builder ---

_DEF = DiagnosticDef(diag_id="diag:shapiro_wilk", name="Shapiro–Wilk", kind="test",
                     how="...", checks=("assum:normality", "assum:asymptotic_normality"),
                     ref="doi:10.1093/biomet/52.3-4.591")


def test_build_emits_checked_by_and_mints_diagnostic():
    nodes = _nodes(("assum:normality", NodeKind.ASSUMPTION),
                   ("assum:asymptotic_normality", NodeKind.ASSUMPTION))
    dn, edges, rep = build_diagnostic_records(nodes, ingested_at="2026-06-17", defs=[_DEF])
    assert len(dn) == 1 and dn[0].kind == NodeKind.DIAGNOSTIC and dn[0].id == "diag:shapiro_wilk"
    assert len(edges) == 2                       # one per existing assumption
    e = edges[0]
    assert (e.from_id, e.to_id, e.kind) == ("assum:asymptotic_normality", "diag:shapiro_wilk", EdgeKind.CHECKED_BY)
    assert e.properties["evidence"] == "doi:10.1093/biomet/52.3-4.591"
    assert rep.diagnostics == 1 and rep.edges == 2


def test_build_skips_assumption_not_present():
    nodes = _nodes(("assum:normality", NodeKind.ASSUMPTION))   # asymptotic_normality absent
    dn, edges, rep = build_diagnostic_records(nodes, ingested_at="2026-06-17", defs=[_DEF])
    assert len(edges) == 1                                      # only the present one
    assert ("diag:shapiro_wilk", "assum:asymptotic_normality", "assumption_missing") in rep.skipped


def test_build_drops_diagnostic_with_no_resolved_assumptions():
    nodes = _nodes(("assum:other", NodeKind.ASSUMPTION))
    dn, edges, rep = build_diagnostic_records(nodes, ingested_at="2026-06-17", defs=[_DEF])
    assert dn == [] and edges == []


def test_edges_deterministically_sorted():
    nodes = _nodes(("assum:a", NodeKind.ASSUMPTION), ("assum:b", NodeKind.ASSUMPTION))
    d = DiagnosticDef("diag:d", "D", "test", "h", ("assum:b", "assum:a"), "doi:1")
    _dn, edges, _rep = build_diagnostic_records(nodes, ingested_at="2026-06-17", defs=[d])
    assert [e.from_id for e in edges] == ["assum:a", "assum:b"]


def test_shipped_yaml_grounds_target_decoy_diagnostics():
    by = {d.diag_id: d for d in load_assumption_diagnostics()}
    assert "assum:decoy_faithfulness" in by["diag:target_decoy_score_overlap"].checks
    assert "assum:decoy_faithfulness" in by["diag:qvalue_pep_calibration"].checks
    assert by["diag:decoy_count_adequacy"].checkable == "pre_run"
    assert by["diag:target_decoy_score_overlap"].ref.startswith(("doi:", "pmid:", "url:", "isbn:"))


def test_shipped_yaml_grounds_protein_de_diagnostics():
    by = {d.diag_id: d for d in load_assumption_diagnostics()}
    assert "assum:missing_not_at_random" in by["diag:missingness_pattern_check"].checks
    assert "assum:quantification_linearity" in by["diag:normalization_ma_plot"].checks
    ppc = by["diag:peptides_per_protein_check"]
    assert ppc.checkable == "pre_run"
    assert ppc.applies_to_assumption == "assum:sufficient_peptides_per_protein"


def test_shipped_yaml_grounds_sc_clustering_diagnostics():
    by = {d.diag_id: d for d in load_assumption_diagnostics()}
    design = by["diag:sc_raw_counts_and_design_check"]
    assert {"assum:raw_umi_counts_input",
            "assum:clustering_unsupervised_no_replicate_floor"} <= set(design.checks)
    assert design.checkable == "pre_run"                         # surfaces as REQUIRES_REVIEW
    assert by["diag:sc_adaptive_qc_check"].checkable == "pre_run"
    assert by["diag:sc_normalization_mean_variance_plot"].checkable == "post_run"
    assert by["diag:sc_hvg_dispersion_plot"].checkable == "post_run"
    assert "assum:cluster_resolution_stability" in by["diag:sc_cluster_stability_check"].checks
    # the single-cell layer carries NO numeric replicate floor on any of its diagnostics
    for did in ("diag:sc_raw_counts_and_design_check", "diag:sc_adaptive_qc_check",
                "diag:sc_normalization_mean_variance_plot", "diag:sc_hvg_dispersion_plot",
                "diag:sc_cluster_stability_check"):
        assert by[did].min_replicates_per_group is None


def test_min_peptides_per_protein_emitted_onto_node(shipped_defs, assum_nodes):
    """min_peptides_per_protein surfaces as a Diagnostic node property."""
    diag_nodes, _, _ = build_diagnostic_records(assum_nodes, ingested_at="2026-06-19", defs=shipped_defs)
    by_id = {n.id: n for n in diag_nodes}
    ppc = by_id["diag:peptides_per_protein_check"]
    assert ppc.properties["min_peptides_per_protein"] == 2
    # must NOT carry min_replicates_per_group (it's a different diagnostic)
    assert "min_replicates_per_group" not in ppc.properties


def test_non_positive_min_peptides_raises():
    """min_peptides_per_protein must be a positive integer."""
    with pytest.raises(ValueError, match="min_peptides_per_protein"):
        load_assumption_diagnostics(spec={"diagnostics": {
            "x_diag": {
                "name": "x", "kind": "test", "checks": ["some_assum"],
                "how": "check", "ref": "doi:1", "min_peptides_per_protein": 0}}})
