from pathlib import Path

from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.props import Edge

FIXTURE = Path(__file__).parent / "fixtures" / "biolean" / "go-mini.obo"


def _parsed():
    return parse_go_basic(FIXTURE.read_text(encoding="utf-8"))


def test_terms_are_sorted_and_counted():
    terms, _, report = _parsed()
    assert [t.id for t in terms] == sorted(t.id for t in terms)
    assert report["term_stanzas"] == 17
    assert report["obsolete_terms"] == 2


def test_obo_alt_id_maps_to_primary_and_primary_maps_to_itself():
    terms, _, _ = _parsed()
    c = next(t for t in terms if t.id == "GO:0000010")
    assert c.alt_ids == ("GO:0000011",)
    assert all(t.alt_ids == () for t in terms if t.id != "GO:0000010")


def test_obo_obsolete_term_keeps_replaced_by_and_consider():
    terms, _, _ = _parsed()
    old = next(t for t in terms if t.id == "GO:0000110")
    assert old.obsolete is True
    assert old.replaced_by == ("GO:0000010",)
    assert old.consider == ("GO:0000020",)
    orphan = next(t for t in terms if t.id == "GO:0000120")
    assert orphan.obsolete is True and orphan.replaced_by == () and orphan.consider == ()


def test_obo_typedef_stanzas_are_skipped_and_counted():
    terms, _, report = _parsed()
    assert report["typedef_stanzas"] == 2
    assert not any(t.id in ("part_of", "regulates") for t in terms)


def test_edges_carry_relation_and_trailing_comments_are_stripped():
    _, edges, report = _parsed()
    assert Edge("GO:0000030", "part_of", "GO:0000010") in edges
    assert Edge("GO:0000005", "is_a", "GO:0000010") in edges
    assert Edge("GO:0000100", "regulates", "GO:0000010") in edges
    assert edges == sorted(edges, key=lambda e: (e.child, e.relation, e.parent))
    assert report["edges"] == len(edges) == 14


def test_unknown_relation_is_kept_and_counted():
    _, edges, report = _parsed()
    assert Edge("GO:0000310", "has_part", "GO:0000300") in edges
    assert report["unknown_relation"] == 1


def test_namespaces_and_names_are_read():
    terms, _, _ = _parsed()
    by_id = {t.id: t for t in terms}
    assert by_id["GO:0000210"].namespace == "molecular_function"
    assert by_id["GO:0000310"].namespace == "cellular_component"
    assert by_id["GO:0000030"].name == "A"


def test_last_term_stanza_at_eof_is_flushed():
    text = ("format-version: 1.2\n\n[Term]\nid: GO:0000001\nname: first\nnamespace: biological_process\n\n"
            "[Term]\nid: GO:0000002\nname: last\nnamespace: biological_process\nis_a: GO:0000001 ! first")
    terms, edges, report = parse_go_basic(text)
    assert [t.id for t in terms] == ["GO:0000001", "GO:0000002"]
    assert edges == [Edge("GO:0000002", "is_a", "GO:0000001")]
    assert report["term_stanzas"] == 2
