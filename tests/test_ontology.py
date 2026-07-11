"""Offline, deterministic tests for the STATO+OBI OWL ontology connector.

All tests run against small hand-crafted RDF/XML fixtures; no network I/O.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from methods_graph.connectors.ontology import parse_obi, parse_stato
from methods_graph.types import EdgeKind, NodeKind

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures" / "ontology"
STATO_MINI = _FIXTURES / "stato_mini.owl"
OBI_MINI = _FIXTURES / "obi_mini.owl"

_INGESTED_AT = "2026-06-11"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _node_ids(nodes) -> set[str]:
    return {n.id for n in nodes}


def _edge_pairs(edges) -> set[tuple[str, str]]:
    return {(e.from_id, e.to_id) for e in edges}


# ---------------------------------------------------------------------------
# STATO tests
# ---------------------------------------------------------------------------


def test_parse_stato_classifies_statistical_methods():
    nodes, edges = parse_stato(STATO_MINI, ingested_at=_INGESTED_AT)
    ids = _node_ids(nodes)

    # Root is ingested as StatisticalMethod.
    assert "obo:OBI_0200000" in ids, "Root OBI_0200000 must be ingested"
    root_node = next(n for n in nodes if n.id == "obo:OBI_0200000")
    assert root_node.kind == NodeKind.STATISTICAL_METHOD
    assert root_node.name == "data transformation"

    # Mid-level descendant.
    assert "obo:OBI_0000673" in ids, "Mid-level OBI_0000673 must be ingested"
    mid_node = next(n for n in nodes if n.id == "obo:OBI_0000673")
    assert mid_node.kind == NodeKind.STATISTICAL_METHOD
    assert mid_node.name == "statistical hypothesis test"

    # Leaf descendant: Student's t-test.
    assert "obo:STATO_0000304" in ids, "Leaf STATO_0000304 must be ingested"
    leaf = next(n for n in nodes if n.id == "obo:STATO_0000304")
    assert leaf.kind == NodeKind.STATISTICAL_METHOD
    assert leaf.name == "Student's t-test"

    # Unrelated class must NOT be present.
    assert "obo:STATO_9999999" not in ids, "Unrelated STATO_9999999 must be excluded"

    # Deprecated class must be skipped.
    assert "obo:STATO_0000001" not in ids, "Deprecated STATO_0000001 must be skipped"

    # IS_A edges: leaf → mid-level, mid-level → root.
    pairs = _edge_pairs(edges)
    assert ("obo:STATO_0000304", "obo:OBI_0000673") in pairs, (
        "IS_A edge STATO_0000304 → OBI_0000673 must be present"
    )
    assert ("obo:OBI_0000673", "obo:OBI_0200000") in pairs, (
        "IS_A edge OBI_0000673 → OBI_0200000 must be present"
    )


def test_parse_stato_classifies_correlation_coefficient_root():
    """The correlation-coefficient branch (STATO_0000142) is a second StatisticalMethod
    root: STATO files it under 'measure of correlation', not under data transformation,
    so without it correlation/co-expression operations have no groundable statistic."""
    nodes, edges = parse_stato(STATO_MINI, ingested_at=_INGESTED_AT)
    by = {n.id: n for n in nodes}
    assert "obo:STATO_0000142" in by
    assert by["obo:STATO_0000142"].kind == NodeKind.STATISTICAL_METHOD
    assert "obo:STATO_0000201" in by, "Spearman's rank correlation must be ingested"
    assert by["obo:STATO_0000201"].kind == NodeKind.STATISTICAL_METHOD
    assert ("obo:STATO_0000201", "obo:STATO_0000142") in _edge_pairs(edges)


def test_parse_obi_classifies_assay_protocol_instrument():
    nodes, edges = parse_obi(OBI_MINI, ingested_at=_INGESTED_AT)
    ids = _node_ids(nodes)

    # Assay root and descendant.
    assert "obo:OBI_0000070" in ids
    assay_root = next(n for n in nodes if n.id == "obo:OBI_0000070")
    assert assay_root.kind == NodeKind.ASSAY
    assert "obo:OBI_0001234" in ids
    assay_node = next(n for n in nodes if n.id == "obo:OBI_0001234")
    assert assay_node.kind == NodeKind.ASSAY
    assert assay_node.name == "DNA sequencing assay"
    # synonyms / alternative terms are restored for keyword search (P4)
    assert assay_node.properties.get("synonyms") == ["DNA-seq assay"]
    assert ("obo:OBI_0001234", "obo:OBI_0000070") in _edge_pairs(edges)

    # Protocol root and descendant.
    assert "obo:OBI_0000272" in ids
    proto_root = next(n for n in nodes if n.id == "obo:OBI_0000272")
    assert proto_root.kind == NodeKind.PROTOCOL
    assert "obo:OBI_0001975" in ids
    proto_node = next(n for n in nodes if n.id == "obo:OBI_0001975")
    assert proto_node.kind == NodeKind.PROTOCOL
    assert ("obo:OBI_0001975", "obo:OBI_0000272") in _edge_pairs(edges)

    # Instrument (device) root and descendant.
    assert "obo:COB_0001300" in ids
    dev_root = next(n for n in nodes if n.id == "obo:COB_0001300")
    assert dev_root.kind == NodeKind.INSTRUMENT
    assert "obo:OBI_0001913" in ids
    instr_node = next(n for n in nodes if n.id == "obo:OBI_0001913")
    assert instr_node.kind == NodeKind.INSTRUMENT
    assert instr_node.name == "Illumina sequencing instrument"
    assert ("obo:OBI_0001913", "obo:COB_0001300") in _edge_pairs(edges)

    # StudyDesign root.
    assert "obo:OBI_0500000" in ids
    sd_root = next(n for n in nodes if n.id == "obo:OBI_0500000")
    assert sd_root.kind == NodeKind.STUDY_DESIGN

    # Material (specimen) root.
    assert "obo:OBI_0100051" in ids
    mat_root = next(n for n in nodes if n.id == "obo:OBI_0100051")
    assert mat_root.kind == NodeKind.MATERIAL

    # Unrelated class must NOT be present.
    assert "obo:OBI_9999999" not in ids, "Unrelated OBI_9999999 must be excluded"


def test_ontology_ids_use_obo_prefix_and_provenance():
    nodes, _edges = parse_stato(STATO_MINI, ingested_at=_INGESTED_AT)
    for n in nodes:
        assert n.id.startswith("obo:"), f"Node id {n.id!r} must start with 'obo:'"
        assert n.provenance is not None
        assert n.provenance.source == "stato"
        assert n.provenance.source_url == "http://purl.obolibrary.org/obo/stato.owl"
        assert n.provenance.ingested_at == _INGESTED_AT

    nodes_obi, _edges_obi = parse_obi(OBI_MINI, ingested_at=_INGESTED_AT)
    for n in nodes_obi:
        assert n.id.startswith("obo:")
        assert n.provenance is not None
        assert n.provenance.source == "obi"
        assert n.provenance.source_url == "http://purl.obolibrary.org/obo/obi.owl"
        assert n.provenance.ingested_at == _INGESTED_AT


def test_ontology_deterministic():
    """Parsing the same file twice must yield identical node and edge lists."""
    nodes1, edges1 = parse_stato(STATO_MINI, ingested_at=_INGESTED_AT)
    nodes2, edges2 = parse_stato(STATO_MINI, ingested_at=_INGESTED_AT)

    assert [n.id for n in nodes1] == [n.id for n in nodes2]
    assert [(n.name, n.kind) for n in nodes1] == [(n.name, n.kind) for n in nodes2]
    assert [(e.from_id, e.to_id, e.kind) for e in edges1] == [
        (e.from_id, e.to_id, e.kind) for e in edges2
    ]

    nodes3, edges3 = parse_obi(OBI_MINI, ingested_at=_INGESTED_AT)
    nodes4, edges4 = parse_obi(OBI_MINI, ingested_at=_INGESTED_AT)
    assert [n.id for n in nodes3] == [n.id for n in nodes4]
    assert [(e.from_id, e.to_id) for e in edges3] == [
        (e.from_id, e.to_id) for e in edges4
    ]
