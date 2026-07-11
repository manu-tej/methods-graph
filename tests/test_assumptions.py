"""Tests for src/methods_graph/crosslinks/assumptions.py (offline, deterministic).

Covers loader validation, the node+edge builder (endpoint gating, node minting,
determinism, grounding), and an end-to-end integrity check that the shipped
assumptions map mints Assumption nodes + grounded REQUIRES_ASSUMPTION edges that
pass the audit.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import kuzu
import pytest

from methods_graph.audit import audit_graph
from methods_graph.crosslinks.assumptions import (
    AssumptionLink,
    AssumptionTerm,
    assumptions_path,
    build_assumption_records,
    build_curated_statistical_method_nodes,
    load_assumptions,
)
from methods_graph.graph.loader import build_graph
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "https://example.com", "2026-06-10")
INGEST = "2026-06-10"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "assum.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _stat(sid: str, name: str) -> NodeRecord:
    return NodeRecord(sid, name, NodeKind.STATISTICAL_METHOD, {}, P)


# ---------------------------------------------------------------------------
# build_curated_statistical_method_nodes
# ---------------------------------------------------------------------------


def test_shipped_yaml_mints_gsea_enrichment_node():
    nodes = build_curated_statistical_method_nodes(ingested_at=INGEST)
    by_id = {n.id: n for n in nodes}
    gsea = by_id["stat:gsea_enrichment"]
    assert gsea.kind == NodeKind.STATISTICAL_METHOD
    assert gsea.name == "GSEA weighted running-sum enrichment score"
    assert gsea.properties["basis"] == "curated"
    assert gsea.provenance.source == "curated"


def test_curated_statistical_methods_reject_missing_id(tmp_path):
    p = _write(tmp_path, """
        statistical_methods:
          - name: no id here
        assumptions: []
        requires: []
    """)
    with pytest.raises(ValueError, match="id"):
        build_curated_statistical_method_nodes(ingested_at=INGEST, path=p)


def test_curated_statistical_methods_reject_duplicate_id(tmp_path):
    p = _write(tmp_path, """
        statistical_methods:
          - {id: stat:x, name: X}
          - {id: stat:x, name: X2}
        assumptions: []
        requires: []
    """)
    with pytest.raises(ValueError, match="duplicate"):
        build_curated_statistical_method_nodes(ingested_at=INGEST, path=p)


def _shipped_requires_by_stat() -> dict:
    _vocab, links = load_assumptions(assumptions_path())
    by_stat: dict = {}
    for lk in links:
        by_stat.setdefault(lk.statistical_method_id, set()).add(lk.assumption_id)
    return by_stat


def test_shipped_fdr_assumptions_are_mechanism_correct():
    """Pins the target-decoy fix: the GENERIC FDR node carries the mechanism-agnostic
    null-calibration assumption (not BH's independence/PRDS, which would leak onto
    target-decoy and permutation methods); the BH node keeps independence/PRDS."""
    by_stat = _shipped_requires_by_stat()
    assert by_stat["obo:OBI_0200163"] == {"assum:correct_model_specification"}
    assert "assum:independence_or_prds" not in by_stat["obo:OBI_0200163"]
    assert "assum:independence_or_prds" in by_stat["obo:OBI_0200036"]


def test_shipped_gsea_node_requires_no_iid_independence():
    """Pins the GSEA fix: stat:gsea_enrichment requires exactly continuous_distribution
    + sample_exchangeability, and must NOT inherit the standard-KS i.i.d. independence."""
    by_stat = _shipped_requires_by_stat()
    assert by_stat["stat:gsea_enrichment"] == {
        "assum:continuous_distribution", "assum:sample_exchangeability"}
    assert "assum:independence" not in by_stat["stat:gsea_enrichment"]


# ---------------------------------------------------------------------------
# load_assumptions
# ---------------------------------------------------------------------------

_VALID = """
    version: 1
    assumptions:
      - id: assum:normality
        name: normality
        definition: errors are normally distributed
        reference: url:https://www.itl.nist.gov/div898/handbook/
    requires:
      - statistical_method: obo:STATO_0000086
        assumption: assum:normality
        evidence: url:https://www.itl.nist.gov/div898/handbook/eda/section3/eda35a.htm
        quote: "the F-test assumes normality"
        confidence: high
"""


def test_load_valid(tmp_path):
    vocab, links = load_assumptions(_write(tmp_path, _VALID))
    assert "assum:normality" in vocab
    assert vocab["assum:normality"].name == "normality"
    assert len(links) == 1
    assert links[0].statistical_method_id == "obo:STATO_0000086"
    assert links[0].evidence_token.startswith("url:")


def test_load_rejects_unknown_assumption(tmp_path):
    body = """
        assumptions:
          - id: assum:normality
            name: normality
        requires:
          - statistical_method: obo:STATO_0000086
            assumption: assum:does_not_exist
            evidence: doi:10.1/x
    """
    with pytest.raises(ValueError, match="unknown assumption"):
        load_assumptions(_write(tmp_path, body))


def test_load_rejects_ungrounded(tmp_path):
    body = """
        assumptions:
          - id: assum:normality
            name: normality
        requires:
          - statistical_method: obo:STATO_0000086
            assumption: assum:normality
            evidence: ""
    """
    with pytest.raises(ValueError, match="ungrounded"):
        load_assumptions(_write(tmp_path, body))


def test_load_rejects_duplicate_edge(tmp_path):
    body = """
        assumptions:
          - id: assum:normality
            name: normality
        requires:
          - statistical_method: obo:STATO_0000086
            assumption: assum:normality
            evidence: doi:10.1/x
          - statistical_method: obo:STATO_0000086
            assumption: assum:normality
            evidence: url:https://x
    """
    with pytest.raises(ValueError, match="duplicate"):
        load_assumptions(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# build_assumption_records
# ---------------------------------------------------------------------------


def _vocab():
    return {
        "assum:normality": AssumptionTerm("assum:normality", "normality", "def", "url:https://ref"),
        "assum:independence": AssumptionTerm("assum:independence", "independence"),
    }


def _links():
    return [
        AssumptionLink("obo:STATO_0000086", "assum:normality", "url:https://nist", quote="q"),
        AssumptionLink("obo:STATO_0000086", "assum:independence", "doi:10.1/x"),
    ]


def test_build_mints_nodes_and_edges():
    nodes = [_stat("obo:STATO_0000086", "F-test")]
    a_nodes, a_edges, report = build_assumption_records(
        nodes, ingested_at=INGEST, vocab=_vocab(), links=_links())
    assert report.edges_emitted == 2
    assert report.nodes_emitted == 2          # both assumptions minted
    assert {n.kind for n in a_nodes} == {NodeKind.ASSUMPTION}
    e = next(x for x in a_edges if x.to_id == "assum:normality")
    assert e.kind == EdgeKind.REQUIRES_ASSUMPTION
    assert e.from_id == "obo:STATO_0000086"
    assert e.properties["basis"] == "curated"
    assert e.properties["evidence"] == "url:https://nist"
    # node carries its definition + provenance
    n = next(x for x in a_nodes if x.id == "assum:normality")
    assert n.properties["definition"] == "def"
    assert n.provenance is not None


def test_build_skips_non_statmethod_source():
    """A source that is not a StatisticalMethod must be skipped (no dangling edge)."""
    nodes = [NodeRecord("obo:STATO_0000086", "F-test", NodeKind.OPERATION, {}, P)]
    a_nodes, a_edges, report = build_assumption_records(
        nodes, ingested_at=INGEST, vocab=_vocab(), links=_links())
    assert a_edges == [] and a_nodes == []
    assert all(r[2].startswith("method_wrong_kind") for r in report.skipped)


def test_build_skips_missing_source():
    nodes = []   # no statistical-method node
    a_nodes, a_edges, report = build_assumption_records(
        nodes, ingested_at=INGEST, vocab=_vocab(), links=_links())
    assert a_edges == [] and a_nodes == []
    assert all(r[2] == "method_missing" for r in report.skipped)


def test_build_does_not_mint_orphan_nodes():
    """An assumption referenced only by a skipped edge must NOT be minted."""
    nodes = []   # source missing -> edge skipped -> no node
    a_nodes, _, _ = build_assumption_records(
        nodes, ingested_at=INGEST, vocab=_vocab(), links=_links())
    assert a_nodes == []


def test_build_is_deterministic():
    nodes = [_stat("obo:STATO_0000086", "F-test")]
    n1, e1, _ = build_assumption_records(nodes, ingested_at=INGEST, vocab=_vocab(),
                                         links=list(reversed(_links())))
    n2, e2, _ = build_assumption_records(nodes, ingested_at=INGEST, vocab=_vocab(),
                                         links=_links())
    assert [n.id for n in n1] == [n.id for n in n2]
    assert [(e.from_id, e.to_id) for e in e1] == [(e.from_id, e.to_id) for e in e2]


# ---------------------------------------------------------------------------
# Shipped map integrity (end-to-end, offline)
# ---------------------------------------------------------------------------


def test_shipped_assumptions_load_and_are_grounded():
    vocab, links = load_assumptions(assumptions_path())
    assert vocab and links
    for lk in links:
        # ontology term (obo:) or a curated StatisticalMethod node (stat:)
        assert lk.statistical_method_id.startswith(("obo:", "stat:"))
        assert lk.assumption_id in vocab
        assert lk.evidence_token


def test_shipped_assumptions_audit_clean(tmp_path):
    """Synthesize the StatisticalMethod endpoints, build, and confirm an audit-clean graph."""
    vocab, links = load_assumptions(assumptions_path())
    stat_ids = sorted({lk.statistical_method_id for lk in links})
    nodes = [_stat(sid, sid.split(":", 1)[-1]) for sid in stat_ids]
    a_nodes, a_edges, report = build_assumption_records(
        nodes, ingested_at=INGEST, vocab=vocab, links=links)
    assert report.edges_emitted == len(links)
    assert not report.skipped

    db_path = tmp_path / "assum.kuzu"
    build_graph(nodes + a_nodes, a_edges, db_path, staging_dir=tmp_path / "stg")
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    ra = [inv for inv in result.invariants if "REQUIRES_ASSUMPTION" in inv.name]
    assert len(ra) == 2 and all(inv.ok for inv in ra)
    assert result.ok is True
    assert result.coverage["ontology_nodes"].get("Assumption", 0) >= 1


def test_shipped_assumptions_carry_no_verbose_quotes():
    """Shipped assumption edges stay lean: evidence token + source_url + note, no quote."""
    _vocab, links = load_assumptions()
    assert links
    for lk in links:
        assert lk.evidence_token, f"{lk.statistical_method_id}->{lk.assumption_id} ungrounded"
        assert lk.quote == "", (
            f"{lk.statistical_method_id}->{lk.assumption_id} still carries a quote"
        )


def test_shipped_yaml_grounds_protein_lfq_de():
    nodes = build_curated_statistical_method_nodes(ingested_at="2026-06-19")
    assert "stat:protein_lfq_de" in {n.id for n in nodes}
    vocab, links = load_assumptions()
    req = {l.assumption_id for l in links if l.statistical_method_id == "stat:protein_lfq_de"}
    assert {"assum:missing_not_at_random", "assum:quantification_linearity",
            "assum:sufficient_peptides_per_protein"} <= req


def test_shipped_yaml_grounds_sc_clustering_workflow():
    nodes = build_curated_statistical_method_nodes(ingested_at="2026-06-19")
    assert "stat:sc_clustering_workflow" in {n.id for n in nodes}
    vocab, links = load_assumptions()
    req = {l.assumption_id for l in links if l.statistical_method_id == "stat:sc_clustering_workflow"}
    assert {"assum:raw_umi_counts_input", "assum:adaptive_qc_filtering",
            "assum:normalization_appropriate_for_counts", "assum:hvg_captures_biological_variation",
            "assum:clustering_unsupervised_no_replicate_floor",
            "assum:cluster_resolution_stability"} <= req
    # leakage-negative (both directions): the unsupervised clustering workflow must NOT require the
    # bulk asymptotic-normality assumption, and the "no replicate floor" assumption must NOT attach
    # to the bulk Wald-test stat (obo:STATO_0000559).
    assert "assum:asymptotic_normality" not in req
    bulk_req = {l.assumption_id for l in links if l.statistical_method_id == "obo:STATO_0000559"}
    assert "assum:clustering_unsupervised_no_replicate_floor" not in bulk_req


def test_shipped_yaml_grounds_target_decoy_fdr():
    nodes = build_curated_statistical_method_nodes(ingested_at="2026-06-19")
    by_id = {n.id: n for n in nodes}
    assert "stat:target_decoy_fdr" in by_id
    assert by_id["stat:target_decoy_fdr"].kind.value == "StatisticalMethod"

    vocab, links = load_assumptions()
    assert "assum:decoy_faithfulness" in vocab
    assert "assum:equal_chance_random_match" in vocab
    td = {l.assumption_id for l in links if l.statistical_method_id == "stat:target_decoy_fdr"}
    assert {"assum:decoy_faithfulness", "assum:equal_chance_random_match"} <= td
    # generic FDR node must NOT carry the decoy-specific assumption (no leakage)
    fdr = {l.assumption_id for l in links if l.statistical_method_id == "obo:OBI_0200163"}
    assert "assum:decoy_faithfulness" not in fdr
