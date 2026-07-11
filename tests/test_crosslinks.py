"""Tests for src/methods_graph/crosslinks (offline, deterministic, no network).

Covers the loader (structure + grounding validation) and the edge builder
(endpoint gating, determinism, evidence token, provenance), plus an end-to-end
integrity check that the SHIPPED curated map is internally consistent and
produces an audit-clean graph when its endpoints exist.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import kuzu
import pytest

from methods_graph.audit import audit_graph
from methods_graph.crosslinks import (
    CuratedLink,
    Evidence,
    build_crosslink_edges,
    crosslinks_path,
    load_crosslinks,
)
from methods_graph.graph.loader import build_graph
from methods_graph.types import (
    EdgeKind,
    MethodRecord,
    NodeKind,
    NodeRecord,
    Provenance,
)

P = Provenance("test", "https://example.com", "2026-06-10")
INGEST = "2026-06-10"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "links.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _method(mid: str, name: str) -> MethodRecord:
    return MethodRecord(mid, name, NodeKind.METHOD, {}, P)


def _stat(sid: str, name: str) -> NodeRecord:
    return NodeRecord(sid, name, NodeKind.STATISTICAL_METHOD, {}, P)


# ---------------------------------------------------------------------------
# load_crosslinks — structure + grounding validation
# ---------------------------------------------------------------------------


def test_load_valid_link(tmp_path):
    p = _write(tmp_path, """
        version: 1
        links:
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            label: Wald test
            evidence:
              doi: 10.1186/s13059-014-0550-8
              pmid: "25516281"
            quote: "Wald test on the GLM coefficient"
            note: default test
            confidence: high
    """)
    links = load_crosslinks(p)
    assert len(links) == 1
    lk = links[0]
    assert lk.method_id == "m:deseq2"
    assert lk.statistical_method_id == "obo:STATO_0000559"
    assert lk.evidence.is_grounded
    assert lk.evidence.as_token() == "doi:10.1186/s13059-014-0550-8"
    assert lk.confidence == "high"


def test_load_rejects_ungrounded_link(tmp_path):
    """A link with no DOI and no PMID must raise — grounding is mandatory."""
    p = _write(tmp_path, """
        links:
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            evidence: {}
    """)
    with pytest.raises(ValueError, match="ungrounded"):
        load_crosslinks(p)


def test_load_rejects_missing_endpoint(tmp_path):
    p = _write(tmp_path, """
        links:
          - method: m:deseq2
            evidence:
              doi: 10.1/x
    """)
    with pytest.raises(ValueError, match="non-empty"):
        load_crosslinks(p)


def test_load_rejects_duplicate_pair(tmp_path):
    p = _write(tmp_path, """
        links:
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            evidence: {doi: 10.1/x}
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            evidence: {pmid: "999"}
    """)
    with pytest.raises(ValueError, match="duplicate"):
        load_crosslinks(p)


def test_load_rejects_bad_confidence(tmp_path):
    p = _write(tmp_path, """
        links:
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            evidence: {doi: 10.1/x}
            confidence: maybe
    """)
    with pytest.raises(ValueError, match="confidence"):
        load_crosslinks(p)


def test_pmid_only_is_grounded(tmp_path):
    p = _write(tmp_path, """
        links:
          - method: m:deseq2
            statistical_method: obo:STATO_0000559
            evidence: {pmid: "25516281"}
    """)
    links = load_crosslinks(p)
    assert links[0].evidence.as_token() == "pmid:25516281"
    assert "pubmed" in links[0].evidence.best_url()


# ---------------------------------------------------------------------------
# build_crosslink_edges — endpoint gating, determinism, payload
# ---------------------------------------------------------------------------


def _links() -> list[CuratedLink]:
    return [
        CuratedLink("m:deseq2", "obo:STATO_0000559", "Wald test",
                    Evidence(doi="10.1186/s13059-014-0550-8"), quote="q", note="n"),
        CuratedLink("m:edger", "obo:STATO_0000086", "F-test",
                    Evidence(pmid="20003500")),
    ]


def test_build_emits_grounded_edges():
    nodes = [
        _method("m:deseq2", "deseq2"), _method("m:edger", "edgeR"),
        _stat("obo:STATO_0000559", "Wald test"), _stat("obo:STATO_0000086", "F-test"),
    ]
    edges, report = build_crosslink_edges(nodes, ingested_at=INGEST, links=_links())
    assert report.emitted == 2
    assert not report.skipped
    e = next(x for x in edges if x.from_id == "m:deseq2")
    assert e.kind == EdgeKind.USES_STATISTICAL_METHOD
    assert e.to_id == "obo:STATO_0000559"
    assert e.properties["basis"] == "curated"
    assert e.properties["evidence"] == "doi:10.1186/s13059-014-0550-8"
    assert e.properties["confidence"] == 1.0
    assert e.provenance.source == "curated"
    assert e.provenance.source_url == "https://doi.org/10.1186/s13059-014-0550-8"


def test_build_is_deterministic():
    nodes = [
        _method("m:deseq2", "deseq2"), _method("m:edger", "edgeR"),
        _stat("obo:STATO_0000559", "Wald test"), _stat("obo:STATO_0000086", "F-test"),
    ]
    e1, _ = build_crosslink_edges(nodes, ingested_at=INGEST, links=list(reversed(_links())))
    e2, _ = build_crosslink_edges(nodes, ingested_at=INGEST, links=_links())
    assert [(e.from_id, e.to_id) for e in e1] == [(e.from_id, e.to_id) for e in e2]


def test_build_skips_missing_method():
    nodes = [_stat("obo:STATO_0000559", "Wald test")]   # no method node
    edges, report = build_crosslink_edges(
        nodes, ingested_at=INGEST,
        links=[CuratedLink("m:deseq2", "obo:STATO_0000559", "Wald test", Evidence(doi="10.1/x"))],
    )
    assert edges == []
    assert report.skipped == [("m:deseq2", "obo:STATO_0000559", "method_missing")]


def test_build_skips_missing_target():
    nodes = [_method("m:deseq2", "deseq2")]   # no stat node
    edges, report = build_crosslink_edges(
        nodes, ingested_at=INGEST,
        links=[CuratedLink("m:deseq2", "obo:STATO_0000559", "Wald test", Evidence(doi="10.1/x"))],
    )
    assert edges == []
    assert report.skipped == [("m:deseq2", "obo:STATO_0000559", "target_missing")]


def test_build_skips_wrong_target_kind():
    """A target that exists but is NOT a StatisticalMethod must be skipped (no dangling/mistyped edge)."""
    nodes = [
        _method("m:deseq2", "deseq2"),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.OPERATION, {}, P),  # wrong kind
    ]
    edges, report = build_crosslink_edges(
        nodes, ingested_at=INGEST,
        links=[CuratedLink("m:deseq2", "obo:STATO_0000559", "Wald test", Evidence(doi="10.1/x"))],
    )
    assert edges == []
    assert report.skipped[0][2].startswith("target_wrong_kind")


def test_build_warns_on_label_mismatch():
    nodes = [_method("m:deseq2", "deseq2"), _stat("obo:STATO_0000559", "Wald test")]
    edges, report = build_crosslink_edges(
        nodes, ingested_at=INGEST,
        links=[CuratedLink("m:deseq2", "obo:STATO_0000559", "WRONG LABEL", Evidence(doi="10.1/x"))],
    )
    assert report.emitted == 1           # still emits — id is authoritative
    assert any("label mismatch" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Shipped map integrity (end-to-end, offline)
# ---------------------------------------------------------------------------


def test_shipped_map_loads_and_is_grounded():
    """The shipped curated map must parse and every link must be grounded."""
    links = load_crosslinks(crosslinks_path())
    assert links, "shipped curated map should not be empty"
    for lk in links:
        assert lk.method_id.startswith("m:")
        # ontology term (obo:) or a curated StatisticalMethod node (stat:)
        assert lk.statistical_method_id.startswith(("obo:", "stat:"))
        assert lk.evidence.is_grounded


def test_shipped_map_pins_corrected_fdr_and_gsea_targets():
    """Guards the review remaps against a silent regression to the old (wrong) targets."""
    pairs = {(lk.method_id, lk.statistical_method_id) for lk in load_crosslinks(crosslinks_path())}
    # GSEA -> curated enrichment node, NOT the standard KS node (which carries i.i.d. independence)
    assert ("m:gsea", "stat:gsea_enrichment") in pairs
    assert ("m:gsea", "obo:STATO_0000083") not in pairs
    # edgeR FDR -> the BH node (carries independence/PRDS), NOT the generic FDR node
    assert ("m:edger", "obo:OBI_0200036") in pairs
    assert ("m:edger", "obo:OBI_0200163") not in pairs


def test_shipped_map_produces_audit_clean_graph(tmp_path):
    """Synthesize the exact endpoints the shipped map references, build, and audit.

    Proves the curated map + edge builder + audit invariants all agree: every
    shipped link lands as a Method→StatisticalMethod edge carrying evidence, and
    the resulting graph passes the audit gate.
    """
    links = load_crosslinks(crosslinks_path())
    nodes: dict[str, NodeRecord] = {}
    for lk in links:
        nodes.setdefault(lk.method_id, _method(lk.method_id, lk.method_id.split(":", 1)[-1]))
        nodes.setdefault(lk.statistical_method_id,
                         _stat(lk.statistical_method_id, lk.label or lk.statistical_method_id))
    edges, report = build_crosslink_edges(list(nodes.values()), ingested_at=INGEST, links=links)
    assert report.emitted == len(links)
    assert not report.skipped

    db_path = tmp_path / "xl.kuzu"
    build_graph(list(nodes.values()), edges, db_path, staging_dir=tmp_path / "stg")
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    usm = [inv for inv in result.invariants if "USES_STATISTICAL_METHOD" in inv.name]
    assert len(usm) == 2                       # typed-endpoint + grounding
    assert all(inv.ok for inv in usm)
    assert result.coverage["with_statistical_method"]["count"] >= 1


def test_shipped_crosslinks_carry_no_verbose_quotes():
    """Shipped curated links stay lean: evidence token + source_url + note, but no
    verbose `quote` text (the DOI/PMID token is the grounding of record)."""
    links = load_crosslinks()
    assert links
    for lk in links:
        assert lk.evidence.is_grounded, f"{lk.method_id} ungrounded"
        assert lk.quote == "", f"{lk.method_id}->{lk.statistical_method_id} still carries a quote"


def test_proteomics_tools_use_target_decoy_node_not_generic_fdr():
    from methods_graph.crosslinks import load_crosslinks
    links = load_crosslinks()
    by_method = {l.method_id: l.statistical_method_id for l in links}
    assert by_method.get("m:maxquant") == "stat:target_decoy_fdr"
    assert by_method.get("m:sageproteomics") == "stat:target_decoy_fdr"
