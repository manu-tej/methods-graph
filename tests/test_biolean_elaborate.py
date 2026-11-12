import copy

from methods_graph.biolean.elaborate import elaborate, elaborate_and_check
from methods_graph.biolean.errors import Code
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, ALT, C, OBS, P1, P5, axiom, deriv, prop, prop_step

STORE = mini_store()


def test_symbol_alt_id_and_taxon_are_rewritten_and_reported_with_paths():
    d = deriv({**prop(ALT, subject="GA", taxon="9606")},
              [{**axiom("s1", A, subject="GA", taxon="taxon:9606")},
               prop_step("s2", "part_of", "s1", A, ALT, subject="GA")], "s2")
    out, report = elaborate(d, STORE)
    assert out["goal"] == prop(C)
    assert out["steps"][0]["conclusion"]["subject"] == P1
    assert out["steps"][1]["edge"] == [A, C]
    assert out["steps"][1]["conclusion"] == prop(C)
    assert report == sorted(report, key=lambda e: e["path"])
    kinds = {(e["path"], e["kind"]) for e in report}
    assert ("goal/subject", "SYMBOL_RESOLVED") in kinds
    assert ("goal/term", "ALT_ID_RESOLVED") in kinds
    assert ("goal/taxon", "TAXON_NORMALIZED") in kinds
    assert ("steps/0/conclusion/taxon", "TAXON_NORMALIZED") in kinds
    assert ("steps/1/edge/1", "ALT_ID_RESOLVED") in kinds
    assert ("steps/1/conclusion/term", "ALT_ID_RESOLVED") in kinds
    assert all(set(e) == {"path", "kind", "before", "after"} for e in report)


def test_every_rewrite_is_reported_with_its_path():
    d = deriv(prop(A, taxon="9606"), [axiom("s1", A, taxon="9606")], "s1")
    _, report = elaborate(d, STORE)
    assert [(e["path"], e["before"], e["after"]) for e in report] == [
        ("goal/taxon", "9606", "NCBITaxon:9606"),
        ("steps/0/conclusion/taxon", "9606", "NCBITaxon:9606"),
    ]


def test_input_is_not_mutated():
    d = deriv(prop(ALT), [axiom("s1", ALT)], "s1")
    snapshot = copy.deepcopy(d)
    elaborate(d, STORE)
    assert d == snapshot


def test_ambiguous_symbol_is_not_resolved():
    d = deriv(prop(A, subject="DUP"), [axiom("s1", A, subject="DUP")], "s1")
    out, report = elaborate(d, STORE)
    assert out["steps"][0]["conclusion"]["subject"] == "DUP"
    assert [e["kind"] for e in report] == ["SYMBOL_AMBIGUOUS", "SYMBOL_AMBIGUOUS"]
    assert report[0]["after"] is None
    v = elaborate_and_check(d, STORE)
    assert any(e["code"] == Code.UNKNOWN_SUBJECT and e["step"] == "s1" for e in v["errors"])


def test_obsolete_term_is_not_silently_replaced():
    d = deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1")
    out, report = elaborate(d, STORE)
    assert out == d and report == []
    v = elaborate_and_check(d, STORE)
    assert any(e["code"] == Code.OBSOLETE_TERM for e in v["errors"])


def test_elaborate_and_check_fills_the_elaboration_field():
    d = deriv(prop(ALT), [axiom("s1", ALT)], "s1")
    v = elaborate_and_check(d, STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert [e["kind"] for e in v["elaboration"]] == ["ALT_ID_RESOLVED", "ALT_ID_RESOLVED"]


def test_malformed_shapes_pass_through_untouched():
    for bad in ("nope", {"goal": 1, "steps": "x", "root": 2}, {"goal": {}, "steps": [1, {"edge": "y"}], "root": "s"}):
        out, report = elaborate(bad, STORE)
        assert out == bad and report == []
