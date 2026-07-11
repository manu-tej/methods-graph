from pathlib import Path

import pytest

from methods_graph.crosslinks.assay_methods import (
    AssayMethodLink, build_assay_method_edges, load_assay_methods,
)
from methods_graph.crosslinks import Evidence
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-18")


def test_shipped_yaml_loads_and_is_grounded():
    links = load_assay_methods()
    assert len(links) >= 1
    assert all(l.evidence.is_grounded for l in links)
    # the RPPA -> limma bridge is present
    assert any(l.assay_id == "obo:OBI_0002957" and l.method_id == "m:limma" for l in links)


def test_build_emits_edge_when_both_endpoints_resolve():
    nodes = [
        NodeRecord("obo:OBI_0002957", "reverse phase protein array profiling assay",
                   NodeKind.ASSAY, {}, P),
        NodeRecord("m:limma", "limma", NodeKind.METHOD, {}, P),
    ]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "limma", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert report.emitted == 1
    e = edges[0]
    assert (e.from_id, e.to_id, e.kind) == ("obo:OBI_0002957", "m:limma", EdgeKind.ANALYZED_BY)
    assert e.properties["evidence"] == "doi:10.1/x"
    assert e.properties["basis"] == "curated"


def test_build_skips_when_assay_missing():
    nodes = [NodeRecord("m:limma", "limma", NodeKind.METHOD, {}, P)]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "limma", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert edges == []
    assert report.skipped == [("obo:OBI_0002957", "m:limma", "assay_missing")]


def test_build_skips_when_source_is_not_assay():
    nodes = [
        NodeRecord("obo:OBI_0002957", "not an assay", NodeKind.OPERATION, {}, P),
        NodeRecord("m:limma", "limma", NodeKind.METHOD, {}, P),
    ]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "limma", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert edges == []
    assert report.skipped[0][2].startswith("assay_wrong_kind")


def test_build_skips_when_method_missing():
    nodes = [NodeRecord("obo:OBI_0002957", "reverse phase protein array profiling assay",
                        NodeKind.ASSAY, {}, P)]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "limma", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert edges == []
    assert report.skipped == [("obo:OBI_0002957", "m:limma", "target_missing")]


def test_build_skips_when_target_wrong_kind():
    nodes = [
        NodeRecord("obo:OBI_0002957", "rppa", NodeKind.ASSAY, {}, P),
        NodeRecord("m:limma", "limma", NodeKind.OPERATION, {}, P),   # wrong kind
    ]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "limma", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert edges == []
    assert report.skipped[0][2].startswith("target_wrong_kind")


def test_build_warns_on_label_mismatch():
    nodes = [
        NodeRecord("obo:OBI_0002957", "rppa", NodeKind.ASSAY, {}, P),
        NodeRecord("m:limma", "limma", NodeKind.METHOD, {}, P),
    ]
    link = AssayMethodLink("obo:OBI_0002957", "m:limma", "WRONG LABEL", Evidence(doi="10.1/x"))
    edges, report = build_assay_method_edges(nodes, ingested_at="2026-06-18", links=[link])
    assert report.emitted == 1   # id is authoritative — edge still emitted
    assert any("label mismatch" in w for w in report.warnings)


def test_load_rejects_ungrounded_link(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("links:\n  - assay: obo:x\n    method: m:y\n    evidence: {}\n")
    with pytest.raises(ValueError, match="ungrounded"):
        load_assay_methods(bad)


def test_load_rejects_duplicate_link(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "links:\n"
        "  - assay: obo:OBI_0002957\n    method: m:limma\n    evidence: {doi: '10.1/x'}\n"
        "  - assay: obo:OBI_0002957\n    method: m:limma\n    evidence: {doi: '10.1/y'}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_assay_methods(dup)


# --- integration: edge lands + audit gate ---

def _assay_graph(tmp_path, *, evidence="doi:10.1/x"):
    import kuzu
    from methods_graph.types import MethodRecord, EdgeRecord
    from methods_graph.graph.loader import build_graph
    nodes = [
        NodeRecord("obo:OBI_0002957", "reverse phase protein array profiling assay",
                   NodeKind.ASSAY, {}, P),
        MethodRecord("m:limma", "limma", NodeKind.METHOD, {}, P, bioconda_pkg="limma"),
    ]
    edges = [
        EdgeRecord("obo:OBI_0002957", "m:limma", EdgeKind.ANALYZED_BY,
                   {"evidence": evidence, "basis": "curated"}, P),
    ]
    db = tmp_path / "assay.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_audit_has_analyzed_by_invariants_and_passes_when_grounded(tmp_path):
    from methods_graph.audit import audit_graph
    conn = _assay_graph(tmp_path)
    res = audit_graph(conn)
    names = {inv.name for inv in res.invariants}
    assert "ANALYZED_BY: Assay→Method" in names
    assert "ANALYZED_BY: grounded (doi:/pmid: evidence)" in names
    assert all(inv.ok for inv in res.invariants if "ANALYZED_BY" in inv.name)


def test_audit_flags_ungrounded_analyzed_by_edge(tmp_path):
    from methods_graph.audit import audit_graph
    conn = _assay_graph(tmp_path, evidence="")   # ungrounded
    res = audit_graph(conn)
    grounded = [inv for inv in res.invariants
                if inv.name == "ANALYZED_BY: grounded (doi:/pmid: evidence)"][0]
    assert grounded.violations == 1 and not grounded.ok
