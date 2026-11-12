from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping

FIXTURE = Path(__file__).parent / "fixtures" / "biolean" / "eco-mini.txt"


def test_eco_mapping_default_rows_win():
    mapping, report = parse_eco_mapping(FIXTURE.read_text())
    assert mapping["IDA"] == "ECO:0000314"
    assert report["non_default_row"] == 1


def test_eco_mapping_counts_every_line_kind():
    mapping, report = parse_eco_mapping(FIXTURE.read_text())
    assert len(mapping) == 8
    assert report == {"comment_lines": 1, "default_rows": 8, "non_default_row": 1, "bad_row": 1}


def test_first_default_row_per_code_wins():
    text = "IDA\tDefault\tECO:0000314\nIDA\tDefault\tECO:0000001\n"
    mapping, report = parse_eco_mapping(text)
    assert mapping == {"IDA": "ECO:0000314"}
    assert report["default_rows"] == 2
