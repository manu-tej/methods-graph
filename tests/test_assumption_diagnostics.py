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


# --- shipped YAML ---


def test_shipped_yaml_loads_and_grounds_key_diagnostics():
    defs = load_assumption_diagnostics()
    by = {d.diag_id: d for d in defs}
    sw = by["diag:shapiro_wilk"]
    assert "assum:asymptotic_normality" in sw.checks
    assert sw.ref.startswith(("doi:", "pmid:", "url:", "isbn:"))
    # every diagnostic carries grounding evidence
    assert all(d.ref.startswith(("doi:", "pmid:", "url:", "isbn:")) for d in defs)


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
