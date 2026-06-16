from pathlib import Path

import pytest

from methods_graph.crosslinks.amenable import (
    AmenableLink, build_amenable_edges, load_amenable,
)
from methods_graph.crosslinks import Evidence
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-15")


def test_shipped_yaml_loads_and_is_grounded():
    links = load_amenable()
    assert len(links) >= 5
    # every shipped link must be grounded (DOI/PMID)
    assert all(l.evidence.is_grounded for l in links)
    # the RNA-Seq quantification -> Wald test link is present
    assert any(l.operation_id == "op:operation_3800"
               and l.statistical_method_id == "obo:STATO_0000559" for l in links)


def test_build_emits_edge_when_both_endpoints_resolve():
    nodes = [
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
    ]
    link = AmenableLink("op:operation_3800", "obo:STATO_0000559", "Wald test",
                        Evidence(doi="10.1/x"))
    edges, report = build_amenable_edges(nodes, ingested_at="2026-06-15", links=[link])
    assert report.emitted == 1
    e = edges[0]
    assert (e.from_id, e.to_id, e.kind) == ("op:operation_3800", "obo:STATO_0000559", EdgeKind.AMENABLE_TO)
    assert e.properties["evidence"] == "doi:10.1/x"
    assert e.properties["basis"] == "curated"


def test_build_skips_when_operation_missing():
    nodes = [NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P)]
    link = AmenableLink("op:operation_3800", "obo:STATO_0000559", "Wald test", Evidence(doi="10.1/x"))
    edges, report = build_amenable_edges(nodes, ingested_at="2026-06-15", links=[link])
    assert edges == []
    assert report.skipped == [("op:operation_3800", "obo:STATO_0000559", "operation_missing")]


def test_build_skips_when_target_wrong_kind():
    nodes = [
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P),
        NodeRecord("obo:STATO_0000559", "not a stat method", NodeKind.TOPIC, {}, P),
    ]
    link = AmenableLink("op:operation_3800", "obo:STATO_0000559", "Wald test", Evidence(doi="10.1/x"))
    edges, report = build_amenable_edges(nodes, ingested_at="2026-06-15", links=[link])
    assert edges == []
    assert report.skipped[0][2].startswith("target_wrong_kind")


def test_load_rejects_ungrounded_link(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("links:\n  - operation: op:x\n    statistical_method: obo:y\n    evidence: {}\n")
    with pytest.raises(ValueError, match="ungrounded"):
        load_amenable(bad)


# --- integration: edges land + surface per-method via method_neighborhood ---

def _amenable_graph(tmp_path, *, evidence="doi:10.1/x"):
    import kuzu
    from methods_graph.types import MethodRecord, EdgeRecord
    from methods_graph.graph.loader import build_graph
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P, bioconda_pkg="salmon"),
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P),
        NodeRecord("obo:STATO_0000559", "Wald test", NodeKind.STATISTICAL_METHOD, {}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3800", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("op:operation_3800", "obo:STATO_0000559", EdgeKind.AMENABLE_TO,
                   {"evidence": evidence, "basis": "curated"}, P),
    ]
    db = tmp_path / "am.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_neighborhood_surfaces_amenable_statistics(tmp_path):
    from methods_graph.extract.seed import method_neighborhood
    conn = _amenable_graph(tmp_path)
    nb = method_neighborhood(conn, "m:salmon")
    assert [s["name"] for s in nb["amenable_statistics"]] == ["Wald test"]
    via = nb["amenable_statistics"][0]["via"][0]
    assert via["operation"] == "RNA-Seq quantification"
    assert via["evidence"] == "doi:10.1/x"


def test_audit_has_amenable_invariants_and_passes_when_grounded(tmp_path):
    from methods_graph.audit import audit_graph
    conn = _amenable_graph(tmp_path)
    res = audit_graph(conn)
    names = {inv.name for inv in res.invariants}
    assert "AMENABLE_TO: Operation→StatisticalMethod" in names
    assert "AMENABLE_TO: grounded (doi:/pmid: evidence)" in names
    assert all(inv.ok for inv in res.invariants if "AMENABLE_TO" in inv.name)


def test_audit_flags_ungrounded_amenable_edge(tmp_path):
    from methods_graph.audit import audit_graph
    conn = _amenable_graph(tmp_path, evidence="")   # ungrounded
    res = audit_graph(conn)
    grounded = [inv for inv in res.invariants
                if inv.name == "AMENABLE_TO: grounded (doi:/pmid: evidence)"][0]
    assert grounded.violations == 1 and not grounded.ok
