from methods_graph.biolean.elaborate import elaborate_and_check
from methods_graph.biolean.render import render_derivation, render_verdict
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, C, GOLDEN, P1, axiom, deriv, prop, prop_step, sorry

STORE = mini_store()


def test_render_derivation_names_terms_and_subjects_and_marks_sorry():
    d = deriv(prop(C), [axiom("s1", A, code="IDA"), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)], "s2")
    text = render_derivation(d, STORE)
    lines = text.splitlines()
    assert lines[0].startswith("s1: axiom") and "GA (UniProtKB:P00001)" in lines[0] and "A (GO:0000030)" in lines[0] and "[IDA]" in lines[0]
    assert lines[1].startswith("s2: part_of") and "because A (GO:0000030) part_of C (GO:0000010)" in lines[1]
    assert lines[2].startswith("s3: sorry") and "m:deseq2" in lines[2] and "unverified" in lines[2]
    assert lines[-1] == "root: s2 proves GA (UniProtKB:P00001) involved_in C (GO:0000010) in NCBITaxon:9606"


def test_render_derivation_survives_unknown_ids_and_bad_shapes():
    text = render_derivation(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999")], "s1"), STORE)
    assert "GO:0009999" in text
    assert render_derivation("nope", STORE) == "unrenderable: not a derivation object"
    assert "s?: ?" in render_derivation({"goal": {}, "steps": [1], "root": "x"}, STORE)


def test_render_verdict_accepted_and_rejected():
    ok = elaborate_and_check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert render_verdict(ok).splitlines()[0] == "ACCEPTED: 1 step, 0 sorry, 1 conflict"
    bad = elaborate_and_check(GOLDEN, STORE)
    lines = render_verdict(bad).splitlines()
    assert lines[0] == "REJECTED: 9 steps, 1 error, 2 unused sorry, 7 unused steps"
    assert any(line.startswith("  s2 AXIOM_NOT_FOUND:") for line in lines)


def test_render_verdict_shows_the_first_suggestion_and_elaboration():
    v = elaborate_and_check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", A, "GO:0000011")], "s2"), STORE)
    text = render_verdict(v)
    assert "suggest: part_of [GO:0000030, GO:0000010]" in text
    assert "elaborated: steps/1/edge/1 GO:0000011 -> GO:0000010 (ALT_ID_RESOLVED)" in text
