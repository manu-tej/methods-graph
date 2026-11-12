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


def test_shipped_yaml_covers_variant_and_de_operations():
    """The scalable expansion: variant ops -> GWAS association stats, DE ops -> DE stats."""
    by_op = {}
    for l in load_amenable():
        by_op.setdefault(l.operation_id, set()).add(l.statistical_method_id)
    # variant calling is amenable to the GWAS association toolkit (PLINK)
    assert {"obo:STATO_0000149", "obo:STATO_0000073", "obo:STATO_0000081",
            "obo:STATO_0000181"} <= by_op.get("op:operation_3227", set())
    # genotyping too (operation-mediated, so every genotyping tool inherits it)
    assert "obo:STATO_0000149" in by_op.get("op:operation_3196", set())
    # DE profiling is amenable to the count-model + FDR toolkit
    assert {"obo:STATO_0000559", "obo:OBI_0200036"} <= by_op.get("op:operation_3223", set())


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


def test_proteomics_identification_ops_amenable_to_target_decoy():
    links = load_amenable()
    pairs = {(l.operation_id, l.statistical_method_id) for l in links}
    for op in ("op:operation_3631", "op:operation_3767", "op:operation_3649"):
        assert (op, "stat:target_decoy_fdr") in pairs
    assert all(l.evidence.is_grounded for l in links)


def test_protein_de_op_amenable_to_protein_lfq_de_and_bh():
    pairs = {(l.operation_id, l.statistical_method_id) for l in load_amenable()}
    assert ("op:operation_3741", "stat:protein_lfq_de") in pairs
    assert ("op:operation_3741", "obo:OBI_0200036") in pairs


def test_sc_clustering_op_amenable_to_sc_workflow():
    links = load_amenable()
    pairs = {(l.operation_id, l.statistical_method_id) for l in links}
    # expression-profile clustering (scanpy's op) is amenable to the single-cell workflow stat
    assert ("op:operation_0313", "stat:sc_clustering_workflow") in pairs
    sc = [l for l in links if l.statistical_method_id == "stat:sc_clustering_workflow"]
    assert sc and all(l.evidence.is_grounded for l in sc)   # every sc amenability link is grounded
