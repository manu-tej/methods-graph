import pytest

from methods_graph.biolean.props import Annotation, Edge, Prop, Term
from methods_graph.biolean.store import MaskedFactStore, StaticFactStore
from tests.biolean_fixture import mini_report, mini_store

P1 = "UniProtKB:P00001"


def test_load_report_has_every_section_and_every_key_even_when_zero():
    report = mini_report()
    assert set(report) == {"obo", "eco", "gaf"}
    assert report["gaf"]["bad_taxon_format"] == 0
    assert report["obo"]["other_stanzas"] == 0


def test_primary_id_resolves_alt_and_identity_and_unknown():
    s = mini_store()
    assert s.primary_id("GO:0000011") == "GO:0000010"
    assert s.primary_id("GO:0000010") == "GO:0000010"
    assert s.primary_id("GO:0009999") is None
    assert s.term("GO:0000011") is None            # alt ids are not terms
    assert s.term("GO:0000010").name == "C"


def test_parents_and_children_are_sorted_and_carry_relations():
    s = mini_store()
    assert s.parents("GO:0000030") == (
        Edge("GO:0000030", "is_a", "GO:0000005"),
        Edge("GO:0000030", "part_of", "GO:0000010"),
        Edge("GO:0000030", "part_of", "GO:0000020"),
    )
    assert s.children("GO:0000010") == (
        Edge("GO:0000005", "is_a", "GO:0000010"),
        Edge("GO:0000020", "is_a", "GO:0000010"),
        Edge("GO:0000030", "part_of", "GO:0000010"),
        Edge("GO:0000210", "part_of", "GO:0000010"),
        Edge("GO:0000100", "regulates", "GO:0000010"),
    )
    assert s.parents("GO:0000060") == ()


def test_matching_is_exact_on_all_five_fields():
    s = mini_store()
    pos = Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    assert sorted(a.code for a in s.matching(pos)) == ["IDA", "IEA"]
    assert [a.code for a in s.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", True))] == ["IDA"]
    assert s.matching(Prop(P1, "enables", "GO:0000010", "NCBITaxon:9606", False)) == ()
    assert s.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:10090", False)) == ()


def test_annotations_are_sorted_by_id_and_subject_lookups_work():
    s = mini_store()
    anns = s.annotations(P1)
    assert [a.id for a in anns] == sorted(a.id for a in anns) and len(anns) == 8
    assert s.subject_exists(P1) and not s.subject_exists("UniProtKB:NOPE")
    assert s.subject_for_symbol("GA") == (P1,)
    assert s.subject_for_symbol("DUP") == ("UniProtKB:P00008", "UniProtKB:P00009")
    assert s.subject_for_symbol("nope") == ()
    assert len(s.annotations("UniProtKB:P00002")) == 4


def _term(i, ns="biological_process", alt=()):
    return Term(i, i, ns, False, (), (), tuple(alt))


def _ann(i, term, subject="UniProtKB:X"):
    return Annotation(i, subject, "X", "involved_in", False, term, term, (), "IDA",
                      "ECO:0000314", (), "P", "protein", "NCBITaxon:9606", "", "2020-01-01",
                      "UniProt", "", "")


def test_store_rejects_duplicate_ids_and_alt_id_terms():
    terms = [_term("GO:1", alt=["GO:9"])]
    with pytest.raises(ValueError, match="duplicate"):
        StaticFactStore(terms, [], [_ann("gaf:a", "GO:1"), _ann("gaf:a", "GO:1")])
    with pytest.raises(ValueError, match="alt_id"):
        StaticFactStore(terms, [], [_ann("gaf:b", "GO:9")])


def test_masked_store_hides_only_the_listed_ids():
    s = mini_store()
    pos = Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    ida = next(a for a in s.matching(pos) if a.code == "IDA")
    m = MaskedFactStore(s, frozenset({ida.id}))
    assert [a.code for a in m.matching(pos)] == ["IEA"]
    assert len(m.annotations(P1)) == 7
    assert len(m.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", True))) == 1


def test_masked_store_keeps_a_fully_hidden_subject_visible():
    s = mini_store()
    hidden = frozenset(a.id for a in s.annotations("UniProtKB:P00005"))
    m = MaskedFactStore(s, hidden)
    assert m.annotations("UniProtKB:P00005") == ()
    assert m.subject_exists("UniProtKB:P00005") is True
    assert m.subject_for_symbol("GE") == ("UniProtKB:P00005",)
    assert m.term("GO:0000010") is s.term("GO:0000010")
    assert m.parents("GO:0000030") == s.parents("GO:0000030")


def test_subjects_are_sorted_and_the_masked_universe_is_whole():
    s = mini_store()
    subjects = s.subjects()
    assert list(subjects) == sorted(subjects) and len(subjects) == 9
    assert subjects[0] == "UniProtKB:P00001" and subjects[-1] == "UniProtKB:P00009"
    m = MaskedFactStore(s, frozenset(a.id for a in s.annotations("UniProtKB:P00005")))
    assert m.subjects() == subjects                  # a fully hidden subject is still a subject


import hashlib
import gzip

from methods_graph.biolean import store as store_mod
from tests.biolean_fixture import FIX, RELEASE, copy_store


def test_read_release_and_gaf_header_live_in_store(tmp_path):
    store_dir = copy_store(tmp_path)
    assert store_mod.read_release(store_dir, gaf="goa_human.gaf") == RELEASE
    gaf = (FIX / "goa-mini.gaf").read_bytes()
    assert store_mod.gaf_header(gzip.compress(gaf)) == store_mod.gaf_header(gaf)
    assert store_mod.gaf_header(gaf)["date_generated"] == "2026-01-01"


def test_base_digests_hash_decompressed_content_so_gz_and_plain_agree(tmp_path):
    plain = copy_store(tmp_path / "plain")
    gz = copy_store(tmp_path / "gz")
    body = (gz / "goa_human.gaf").read_bytes()
    (gz / "goa_human.gaf.gz").write_bytes(gzip.compress(body, mtime=12345))
    (gz / "goa_human.gaf").unlink()
    a = store_mod.base_digests(plain, gaf="goa_human.gaf")
    b = store_mod.base_digests(gz, gaf="goa_human.gaf.gz")
    assert a == b
    assert a["gaf"] == hashlib.sha256(body).hexdigest()
    assert set(a) == {"obo", "gaf", "eco"} and all(len(v) == 64 for v in a.values())


def test_load_base_carries_digests_callables_and_the_same_report_as_load_store(tmp_path):
    store_dir = copy_store(tmp_path)
    base = store_mod.load_base(store_dir, obo="go-basic.obo", gaf="goa_human.gaf", eco="gaf-eco-mapping.txt")
    _, report = store_mod.load_store(store_dir, gaf="goa_human.gaf")
    assert base.report == report
    assert base.digests == store_mod.base_digests(store_dir, gaf="goa_human.gaf")
    assert base.primary_id("GO:0000011") == "GO:0000010" and base.primary_id("GO:0009999") is None
    assert base.term("GO:0000010").name == "C" and base.term("GO:0000011") is None
    assert base.eco_map["IDA"] == "ECO:0000314"
    assert len(base.annotations) == 24
    # The production store is goa_human.gaf.gz: load_base parses and hashes the decompressed bytes,
    # so the gz store loads the same base. Break: read the .gz bytes raw in load_base.
    gz = copy_store(tmp_path / "gz")
    (gz / "goa_human.gaf.gz").write_bytes(gzip.compress((gz / "goa_human.gaf").read_bytes(), mtime=12345))
    (gz / "goa_human.gaf").unlink()
    zbase = store_mod.load_base(gz, obo="go-basic.obo", gaf="goa_human.gaf.gz", eco="gaf-eco-mapping.txt")
    assert zbase.digests == base.digests and zbase.report == base.report
    assert zbase.annotations == base.annotations and zbase.eco_map == base.eco_map
