# tests/test_edam.py
from pathlib import Path
from methods_graph.connectors.edam import parse_edam
from methods_graph.types import NodeKind, EdgeKind

FIXTURE = Path(__file__).parent / "fixtures" / "edam_sample.tsv"


def test_parse_edam_extracts_typed_nodes():
    nodes, edges = parse_edam(FIXTURE, ingested_at="2026-06-08")
    by_kind = {n.kind for n in nodes}
    assert NodeKind.OPERATION in by_kind
    assert NodeKind.TOPIC in by_kind
    assert NodeKind.DATA in by_kind
    assert NodeKind.FORMAT in by_kind


def test_parse_edam_skips_obsolete():
    nodes, _ = parse_edam(FIXTURE, ingested_at="2026-06-08")
    assert all("operation_0000" not in n.id for n in nodes)


def test_parse_edam_builds_is_a_edges():
    _, edges = parse_edam(FIXTURE, ingested_at="2026-06-08")
    is_a = [e for e in edges if e.kind == EdgeKind.IS_A]
    assert any(e.from_id.endswith("operation_3798") and e.to_id.endswith("operation_2495")
               for e in is_a)
