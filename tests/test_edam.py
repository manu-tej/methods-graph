# tests/test_edam.py
import io
import pytest
from pathlib import Path
from methods_graph.connectors.edam import parse_edam
from methods_graph.types import NodeKind, EdgeKind

FIXTURE = Path(__file__).parent / "fixtures" / "edam_sample.tsv"


def test_parse_edam_extracts_typed_nodes():
    nodes, _ = parse_edam(FIXTURE, ingested_at="2026-06-08")
    by_kind = {n.kind for n in nodes}
    assert NodeKind.OPERATION in by_kind
    assert NodeKind.TOPIC not in by_kind  # Topic layer removed: topic_ rows not ingested
    assert NodeKind.DATA in by_kind
    assert NodeKind.FORMAT in by_kind
    assert len(nodes) == 4  # 6 rows minus 1 obsolete minus 1 topic (not ingested)


def test_parse_edam_skips_obsolete():
    nodes, _ = parse_edam(FIXTURE, ingested_at="2026-06-08")
    assert all("operation_0000" not in n.id for n in nodes)


def test_parse_edam_builds_is_a_edges():
    _, edges = parse_edam(FIXTURE, ingested_at="2026-06-08")
    is_a = [e for e in edges if e.kind == EdgeKind.IS_A]
    assert len(is_a) == 1
    assert any(e.from_id.endswith("operation_3798") and e.to_id.endswith("operation_2495")
               for e in is_a)


def test_parse_edam_missing_columns_raises(tmp_path):
    """A TSV lacking required columns should raise ValueError with a clear message."""
    bad_tsv = tmp_path / "bad.tsv"
    bad_tsv.write_text("Class ID\tPreferred Label\nhttp://edamontology.org/operation_1\tFoo\n",
                       encoding="utf-8")
    with pytest.raises(ValueError, match="EDAM TSV missing required columns"):
        parse_edam(bad_tsv, ingested_at="2026-06-08")


def test_parse_edam_skips_blank_label_rows(tmp_path):
    """Rows with an empty Preferred Label should not produce nodes."""
    blank_tsv = tmp_path / "blank.tsv"
    blank_tsv.write_text(
        "Class ID\tPreferred Label\tParents\tObsolete\n"
        "http://edamontology.org/operation_1\tReal Op\t\tFALSE\n"
        "http://edamontology.org/operation_2\t   \t\tFALSE\n",
        encoding="utf-8",
    )
    nodes, _ = parse_edam(blank_tsv, ingested_at="2026-06-08")
    assert len(nodes) == 1
    assert nodes[0].name == "Real Op"
