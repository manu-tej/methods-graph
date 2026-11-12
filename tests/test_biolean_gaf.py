from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import annotation_id, parse_gaf
from methods_graph.biolean.obo import parse_go_basic

FIX = Path(__file__).parent / "fixtures" / "biolean"


def _ontology():
    terms, _, _ = parse_go_basic((FIX / "go-mini.obo").read_text(encoding="utf-8"))
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}

    def primary_id(go_id: str) -> str | None:
        return go_id if go_id in by_id else alt.get(go_id)

    return primary_id, by_id.get


def _parse(lines=None):
    eco_map, _ = parse_eco_mapping((FIX / "eco-mini.txt").read_text())
    primary_id, term = _ontology()
    if lines is None:
        lines = (FIX / "goa-mini.gaf").read_text(encoding="utf-8").splitlines()
    return parse_gaf(lines, eco_map, primary_id, term)


def test_report_has_every_key_and_the_fixture_counts():
    _, report = _parse()
    assert report == {
        "comment_lines": 3, "rows": 28, "bad_column_count": 1, "unknown_qualifier": 1,
        "bad_taxon_cardinality": 1, "bad_taxon_format": 0, "multi_taxon": 1,
        "duplicate_row": 1, "term_alt_id": 1, "term_not_in_ontology": 1,
        "term_obsolete": 1, "eco_unmapped": 1, "annotations": 24,
    }


def _rows(subject, qualifier=None, term=None, negated=None):
    anns, _ = _parse()
    return [a for a in anns if a.subject == subject
            and (qualifier is None or a.qualifier == qualifier)
            and (term is None or a.term == term)
            and (negated is None or a.negated == negated)]


def test_gaf_not_qualifier_sets_negated_and_strips_prefix():
    [row] = _rows("UniProtKB:P00001", negated=True)
    assert row.qualifier == "involved_in" and row.term == "GO:0000010"
    anns, _ = _parse()
    assert not any("NOT" in a.qualifier for a in anns)
    assert sum(a.negated for a in anns) == 2


def test_gaf_bad_column_count_is_counted_and_dropped():
    assert not any(a.references == ("PMID:18",) for a in _parse()[0])


def test_gaf_unknown_qualifier_is_counted_and_dropped():
    assert not any(a.qualifier == "binds" for a in _parse()[0])


def test_gaf_alt_id_term_is_canonicalized_and_counted():
    [row] = _rows("UniProtKB:P00006")
    assert row.term == "GO:0000010" and row.term_raw == "GO:0000011"


def test_gaf_term_not_in_ontology_is_kept_and_counted():
    [row] = _rows("UniProtKB:P00007", term="GO:0009999")
    assert row.term == row.term_raw == "GO:0009999"


def test_gaf_obsolete_term_row_is_kept_and_counted():
    [row] = _rows("UniProtKB:P00005")
    assert row.term == "GO:0000110"


def test_gaf_first_taxon_is_normalized_and_second_retained():
    [row] = [a for a in _rows("UniProtKB:P00001", term="GO:0000030") if a.code == "IPI"]
    assert row.taxon == "NCBITaxon:9606"
    assert row.interacting_taxon == "NCBITaxon:562"
    assert row.with_from == ("UniProtKB:Q0001",)
    [ida] = [a for a in _rows("UniProtKB:P00001", term="GO:0000030") if a.code == "IDA"]
    assert ida.interacting_taxon == ""


def test_gaf_bad_taxon_cardinality_is_counted_and_dropped():
    assert not any(a.term == "GO:0000300" for a in _rows("UniProtKB:P00004"))


def test_gaf_duplicate_rows_are_collapsed_and_counted():
    rows = _rows("UniProtKB:P00004", term="GO:0000310")
    assert len(rows) == 1 and rows[0].code == "HDA"


def test_gaf_two_references_are_split_and_sorted():
    [row] = [a for a in _rows("UniProtKB:P00003", term="GO:0000210") if a.code == "IDA"]
    assert row.references == ("PMID:11", "PMID:12")


def test_eco_is_mapped_and_unmapped_is_empty_string():
    by_code = {a.code: a for a in _rows("UniProtKB:P00007", term="GO:0000090")}
    assert by_code["IDA"].eco == "ECO:0000314"
    assert by_code["XYZ"].eco == ""


def test_date_is_iso_and_annotations_are_sorted_by_id():
    anns, _ = _parse()
    assert all(len(a.date) == 10 and a.date[4] == "-" for a in anns)
    assert [a.id for a in anns] == sorted(a.id for a in anns)


def test_annotation_id_is_stable_across_loads_and_row_order():
    lines = (FIX / "goa-mini.gaf").read_text(encoding="utf-8").splitlines()
    forward = {a.id: a for a in _parse(lines)[0]}
    header, data = lines[:3], lines[3:]
    backward = {a.id: a for a in _parse(header + list(reversed(data)))[0]}
    assert forward == backward
    cols = data[0].split("\t")
    assert annotation_id(cols).startswith("gaf:") and len(annotation_id(cols)) == 20
    assert annotation_id(cols) != annotation_id(cols[:-1] + ["x"])


from methods_graph.biolean.gaf import GAF_COLUMNS, _COLUMNS


def test_gaf_columns_are_the_seventeen_gaf22_names_in_order():
    assert GAF_COLUMNS == (
        "db", "db_object_id", "db_object_symbol", "qualifier", "go_id", "db_reference",
        "evidence_code", "with_from", "aspect", "db_object_name", "db_object_synonym",
        "db_object_type", "taxon", "date", "assigned_by", "annotation_extension",
        "gene_product_form_id")
    assert _COLUMNS == len(GAF_COLUMNS) == 17
