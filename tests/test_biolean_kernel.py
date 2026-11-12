"""Kernel tests. Every rejection test asserts the (step, code) pair; every acceptance test
asserts errors == []. Fixture: tests/fixtures/biolean via mini_store()."""
import json

from methods_graph.biolean.errors import ALL_CODES, Code
from methods_graph.biolean.kernel import ancestors, check, descendants
from methods_graph.biolean.props import Prop
from tests.biolean_fixture import mini_store

P1, P2, P3, P5, P7 = ("UniProtKB:P00001", "UniProtKB:P00002", "UniProtKB:P00003",
                      "UniProtKB:P00005", "UniProtKB:P00007")
TAX = "NCBITaxon:9606"
A, B, C, D = "GO:0000030", "GO:0000005", "GO:0000010", "GO:0000020"
X, Y, T = "GO:0000040", "GO:0000050", "GO:0000060"
R, OBS, ALT, MF1, MF2 = "GO:0000100", "GO:0000110", "GO:0000011", "GO:0000200", "GO:0000210"


def prop(term, subject=P1, qualifier="involved_in", negated=False, taxon=TAX):
    return {"subject": subject, "qualifier": qualifier, "term": term, "taxon": taxon,
            "negated": negated}


def axiom(sid, term, **kw):
    extra = {k: kw.pop(k) for k in ("code", "reference") if k in kw}
    return {"id": sid, "rule": "axiom", "conclusion": prop(term, **kw), **extra}


def prop_step(sid, rule, premise, child, parent, **kw):
    return {"id": sid, "rule": rule, "premises": [premise], "edge": [child, parent],
            "conclusion": prop(parent, **kw)}


def sorry(sid, term, provenance=None, **kw):
    if provenance is None:
        provenance = {"method": "m:deseq2", "inputs": ["GEO:GSE1"], "parameters": {},
                      "claim": "computed"}
    return {"id": sid, "rule": "sorry", "conclusion": prop(term, **kw), "provenance": provenance}


def deriv(goal, steps, root):
    return {"biolean": "0.1", "goal": goal, "steps": steps, "root": root}


def codes(verdict, step):
    return sorted(e["code"] for e in verdict["errors"] if e["step"] == step)


def only(verdict, step, code):
    """The single error on `step`, which must carry `code`."""
    errs = [e for e in verdict["errors"] if e["step"] == step]
    assert [e["code"] for e in errs] == [code], verdict["errors"]
    return errs[0]


STORE = mini_store()


# ---------- structure ----------

def test_non_object_derivation_is_malformed():
    v = check("not a derivation", STORE)
    assert v["verdict"] == "REJECTED"
    assert [(e["step"], e["code"]) for e in v["errors"]] == [(None, Code.MALFORMED)]
    assert v["steps_checked"] == 0 and v["goal"] is None


def test_verdict_has_exactly_the_documented_keys():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert set(v) == {"verdict", "goal", "steps_checked", "sorry_count", "unused_sorries",
                      "unused_steps", "premise_failed", "errors", "axioms", "sorries",
                      "conflicts", "elaboration"}
    assert v["elaboration"] == []
    assert all(e["code"] in ALL_CODES for e in v["errors"])


def test_duplicate_step_ids_are_reported():
    v = check(deriv(prop(A), [axiom("s1", A), axiom("s1", A)], "s1"), STORE)
    assert Code.DUPLICATE_STEP in codes(v, "s1")


def test_unknown_step_ref_and_unknown_root():
    v = check(deriv(prop(C), [prop_step("s2", "is_a", "s1", B, C)], "nope"), STORE)
    assert Code.UNKNOWN_STEP_REF in codes(v, "s2")
    assert (None, Code.UNKNOWN_STEP_REF) in [(e["step"], e["code"]) for e in v["errors"]]


def test_premise_after_use_is_step_order_not_a_hang():
    s1 = {"id": "s1", "rule": "is_a", "premises": ["s2"], "edge": [B, C], "conclusion": prop(C)}
    s2 = {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": [B, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s1, s2], "s2"), STORE)
    assert Code.STEP_ORDER in codes(v, "s1")
    assert Code.STEP_ORDER not in codes(v, "s2")


def test_is_a_with_no_premise_is_premise_arity():
    s = {"id": "s1", "rule": "is_a", "premises": [], "edge": [B, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s], "s1"), STORE)
    e = only(v, "s1", Code.PREMISE_ARITY)
    assert e["expected"] == 1 and e["actual"] == 0


def test_axiom_with_a_premise_is_premise_arity():
    steps = [axiom("s1", A), {**axiom("s2", B), "premises": ["s1"]}]
    v = check(deriv(prop(B), steps, "s2"), STORE)
    e = only(v, "s2", Code.PREMISE_ARITY)
    assert e["expected"] == 0 and e["actual"] == 1


def test_non_list_premises_is_malformed_not_premise_arity():
    s = {"id": "s1", "rule": "is_a", "premises": "s0", "edge": [B, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s], "s1"), STORE)
    assert Code.MALFORMED in codes(v, "s1")
    assert Code.PREMISE_ARITY not in codes(v, "s1")
    # A missing "premises" key entirely (not just the wrong type) must not also add
    # PREMISE_ARITY on top of the MALFORMED for "is_a step needs premises".
    missing = {"id": "s2", "rule": "is_a", "edge": [B, C], "conclusion": prop(C)}
    v2 = check(deriv(prop(C), [missing], "s2"), STORE)
    assert Code.MALFORMED in codes(v2, "s2")
    assert Code.PREMISE_ARITY not in codes(v2, "s2")


def test_unknown_rule_is_reported_and_nothing_else_on_that_step():
    s = {"id": "s1", "rule": "regulates", "premises": [], "edge": [R, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s], "s1"), STORE)
    only(v, "s1", Code.UNKNOWN_RULE)


def test_unknown_keys_are_malformed_naming_the_key():
    v = check(deriv(prop(A), [{**axiom("s1", A), "edge": [A, B]}], "s1"), STORE)
    e = only(v, "s1", Code.MALFORMED)
    assert "edge" in e["message"] and e["actual"] == ["edge"]


def test_code_on_a_non_axiom_step_is_malformed():
    v = check(deriv(prop(C), [axiom("s1", A), {**prop_step("s2", "part_of", "s1", A, C), "code": "IDA"}], "s2"), STORE)
    assert Code.MALFORMED in codes(v, "s2")


def test_conclusion_with_wrong_shape_is_malformed():
    bad = {"id": "s1", "rule": "axiom", "conclusion": {"subject": P1, "term": A}}
    v = check(deriv(prop(A), [bad], "s1"), STORE)
    only(v, "s1", Code.MALFORMED)


def test_id_less_steps_are_attributed_by_position():
    v = check(deriv(prop(A), ["nope", {"rule": "axiom", "conclusion": prop(A)}, axiom("s1", A)],
                    "s1"), STORE)
    steps_seen = {e["step"] for e in v["errors"]}
    assert "#0" in steps_seen and "#1" in steps_seen
    assert None not in steps_seen
    assert [e["step"] for e in v["errors"]] == ["#0", "#1"]


def test_user_ids_starting_with_hash_sort_by_position():
    """A step's *own* id may look like "#3" or "#-1" (ids are unrestricted strings). Sorting
    must use the carried position, never re-parse the label, or a user id colliding with the
    id-less-step display format would be mis-sorted (or, for "#-1", land in the goal's slot)."""
    steps = [
        axiom("#3", "GO:0009999"),          # a real id that looks like a position-3 label,
        axiom("s1", A, qualifier="enables"),  # but this step is actually at index 0.
        axiom("s2", A),                       # clean root, so no incidental ROOT_MISMATCH.
    ]
    v = check(deriv(prop(A), steps, "s2"), STORE)
    assert v["errors"][0]["step"] == "#3"
    assert v["errors"][1]["step"] == "s1"

    # A step id of "#-1" must not tie with (or precede) the goal's own -1 slot.
    hashneg = {"id": "#-1", "rule": "axiom", "conclusion": prop(ALT)}
    v2 = check(deriv(prop("GO:0009999"), [hashneg], "nope"), STORE)
    assert v2["errors"][0]["step"] is None


# ---------- identifiers ----------

def test_unknown_term_is_reported():
    v = check(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999")], "s1"), STORE)
    assert Code.UNKNOWN_TERM in codes(v, "s1")
    assert Code.UNKNOWN_TERM in codes(v, None)


def test_obsolete_term_error_carries_replaced_by():
    v = check(deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1"), STORE)
    e = only(v, "s1", Code.OBSOLETE_TERM)
    assert e["expected"] == {"replaced_by": [C], "consider": [D]}


def test_alt_id_reaching_the_kernel_is_an_error():
    v = check(deriv(prop(ALT), [axiom("s1", ALT)], "s1"), STORE)
    e = only(v, "s1", Code.ALT_ID_IN_KERNEL)
    assert e["expected"] == C
    good = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert good["errors"] == []
    via_edge = deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, ALT)], "s2")
    v2 = check(via_edge, STORE)
    assert Code.ALT_ID_IN_KERNEL in codes(v2, "s2")
    assert check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"), STORE)["errors"] == []
    # The conclusion here is the clean primary term C; only the edge carries the alt id.
    edge_alt_parent = deriv(prop(C), [axiom("s1", A),
        {"id": "s2", "rule": "part_of", "premises": ["s1"], "edge": [A, ALT], "conclusion": prop(C)}], "s2")
    v3 = check(edge_alt_parent, STORE)
    assert Code.ALT_ID_IN_KERNEL in codes(v3, "s2")
    edge_alt_child = deriv(prop(C), [axiom("s1", A),
        {"id": "s2", "rule": "part_of", "premises": ["s1"], "edge": [ALT, C], "conclusion": prop(C)}], "s2")
    v4 = check(edge_alt_child, STORE)
    assert Code.ALT_ID_IN_KERNEL in codes(v4, "s2")
    edge_unknown_term = deriv(prop(C), [axiom("s1", A),
        {"id": "s2", "rule": "part_of", "premises": ["s1"], "edge": ["GO:0009999", C], "conclusion": prop(C)}], "s2")
    v5 = check(edge_unknown_term, STORE)
    assert Code.UNKNOWN_TERM in codes(v5, "s2")


def test_unknown_subject_carries_symbol_candidates():
    v = check(deriv(prop(A, subject="DUP"), [axiom("s1", A, subject="DUP")], "s1"), STORE)
    e = only(v, "s1", Code.UNKNOWN_SUBJECT)
    assert e["expected"] == ["UniProtKB:P00008", "UniProtKB:P00009"]


def test_taxon_must_be_ncbitaxon_curie():
    v = check(deriv(prop(A, taxon="human"), [axiom("s1", A, taxon="human")], "s1"), STORE)
    assert Code.MALFORMED in codes(v, "s1") and Code.MALFORMED in codes(v, None)


def test_unknown_qualifier_and_aspect_mismatch():
    v = check(deriv(prop(A, qualifier="binds"), [axiom("s1", A, qualifier="binds")], "s1"), STORE)
    assert Code.UNKNOWN_QUALIFIER in codes(v, "s1")
    v = check(deriv(prop(A, qualifier="enables"), [axiom("s1", A, qualifier="enables")], "s1"), STORE)
    assert Code.QUALIFIER_ASPECT_MISMATCH in codes(v, "s1")


def test_root_differing_only_in_qualifier_is_root_mismatch():
    v = check(deriv(prop(A, qualifier="acts_upstream_of"), [axiom("s1", A)], "s1"), STORE)
    e = only(v, None, Code.ROOT_MISMATCH)
    assert e["expected"]["qualifier"] == "acts_upstream_of" and e["actual"]["qualifier"] == "involved_in"


def test_goal_errors_carry_step_none_and_sort_first():
    v = check(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999"), axiom("s2", A)], "s1"), STORE)
    assert v["errors"][0]["step"] is None
    steps_in_order = [e["step"] for e in v["errors"]]
    assert steps_in_order == sorted(steps_in_order, key=lambda s: -1 if s is None else int(s[1:]))


def test_errors_are_json_serializable_and_sorted_by_step_code_message():
    steps = [
        axiom("s1", "GO:0009999", taxon="human"),   # two different codes on one step
        axiom("s2", A, qualifier="enables"),
        axiom("s3", ALT),
        axiom("s4", A),                             # clean, so root has no ROOT_MISMATCH
    ]
    v = check(deriv(prop(A), steps, "s4"), STORE)
    json.dumps(v, sort_keys=True)
    position = {"s1": 0, "s2": 1, "s3": 2, "s4": 3}
    keyed = [(-1 if e["step"] is None else position[e["step"]], e["code"], e["message"])
             for e in v["errors"]]
    assert keyed == sorted(keyed)
    assert len(keyed) >= 3
    assert len({p for p, _, _ in keyed}) >= 2
    by_position: dict = {}
    for p, c, _ in keyed:
        by_position.setdefault(p, set()).add(c)
    assert any(len(codes) >= 2 for codes in by_position.values())


# ---------- closure helpers ----------

def test_ancestors_follow_is_a_and_part_of_within_namespace_only():
    assert ancestors(A, STORE) == (B, C, D)
    assert ancestors(MF2, STORE) == (MF1,)        # the part_of into BP is not followed
    assert ancestors(R, STORE) == ()               # regulates is not followed
    assert ancestors("GO:0009999", STORE) == ()


def test_descendants_are_the_dual_within_namespace():
    assert descendants(C, STORE) == tuple(sorted((A, B, D)))   # MF2 and R are not followed
    assert descendants("GO:0000070", STORE) == ("GO:0000080", "GO:0000090")
    assert descendants(Y, STORE) == (X,)


def test_closures_skip_obsolete_terms():
    from methods_graph.biolean.props import Edge, Term
    from methods_graph.biolean.store import StaticFactStore

    terms = [
        Term(id="GO:1", name="one", namespace="biological_process", obsolete=False,
             replaced_by=(), consider=(), alt_ids=()),
        Term(id="GO:2", name="two", namespace="biological_process", obsolete=True,
             replaced_by=(), consider=(), alt_ids=()),
        Term(id="GO:3", name="three", namespace="biological_process", obsolete=False,
             replaced_by=(), consider=(), alt_ids=()),
    ]
    edges = [
        Edge(child="GO:1", relation="is_a", parent="GO:2"),
        Edge(child="GO:2", relation="is_a", parent="GO:3"),
        Edge(child="GO:1", relation="part_of", parent="GO:3"),
    ]
    s = StaticFactStore(terms, edges, [])
    assert ancestors("GO:1", s) == ("GO:3",)
    assert descendants("GO:3", s) == ("GO:1",)


# ---------- rules ----------

def test_axiom_only_derivation_is_accepted_and_lists_its_rows():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert sorted(a["code"] for a in v["axioms"]) == ["IDA", "IPI"]
    assert [a["annotation"] for a in v["axioms"]] == sorted(a["annotation"] for a in v["axioms"])
    assert v["axioms"][0]["eco"] in ("ECO:0000314", "ECO:0000353")


def test_axiom_requires_the_exact_qualifier():
    v = check(deriv(prop(MF2, subject=P3, qualifier="contributes_to"),
                    [axiom("s1", MF2, subject=P3, qualifier="contributes_to")], "s1"), STORE)
    e = only(v, "s1", Code.AXIOM_NOT_FOUND)
    assert {"rule": "axiom", "conclusion": prop(MF2, subject=P3, qualifier="enables")} in e["suggestions"]


def test_axiom_with_code_requires_a_row_with_that_code():
    v = check(deriv(prop(A, subject="UniProtKB:P00008"),
                    [axiom("s1", A, subject="UniProtKB:P00008", code="IDA")], "s1"), STORE)
    only(v, "s1", Code.AXIOM_NOT_FOUND)
    ok = check(deriv(prop(A, subject="UniProtKB:P00008"),
                     [axiom("s1", A, subject="UniProtKB:P00008", code="IEA")], "s1"), STORE)
    assert ok["errors"] == []


def test_axiom_code_and_reference_must_be_on_one_row():
    split = axiom("s1", MF2, subject=P3, qualifier="enables", code="IPI", reference="PMID:11")
    v = check(deriv(prop(MF2, subject=P3, qualifier="enables"), [split], "s1"), STORE)
    only(v, "s1", Code.AXIOM_NOT_FOUND)
    same = axiom("s1", MF2, subject=P3, qualifier="enables", code="IDA", reference="PMID:12")
    ok = check(deriv(prop(MF2, subject=P3, qualifier="enables"), [same], "s1"), STORE)
    assert ok["errors"] == [] and [a["code"] for a in ok["axioms"]] == ["IDA"]


def test_axiom_without_code_lists_every_matching_row():
    v = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert v["errors"] == []
    assert sorted(a["code"] for a in v["axioms"]) == ["IDA", "IEA"]


def test_axiom_at_obsolete_term_is_rejected_even_though_the_row_exists():
    assert STORE.matching(Prop(P5, "involved_in", OBS, TAX, False))   # the row IS in the store
    v = check(deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1"), STORE)
    e = only(v, "s1", Code.OBSOLETE_TERM)
    assert e["expected"]["replaced_by"] == [C]


def test_is_a_and_part_of_chains_are_accepted():
    v = check(deriv(prop(C), [axiom("s1", B), prop_step("s2", "is_a", "s1", B, C)], "s2"), STORE)
    assert v["errors"] == [] and v["unused_steps"] == [] and v["premise_failed"] == []
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"), STORE)
    assert v["errors"] == []
    two = [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B), prop_step("s3", "is_a", "s2", B, C)]
    assert check(deriv(prop(C), two, "s3"), STORE)["errors"] == []


def test_regulates_edge_is_not_a_rule():
    s2 = {"id": "s2", "rule": "regulates", "premises": ["s1"], "edge": [R, C],
          "conclusion": prop(C, subject=P7)}
    v = check(deriv(prop(C, subject=P7), [axiom("s1", R, subject=P7), s2], "s2"), STORE)
    only(v, "s2", Code.UNKNOWN_RULE)
    assert codes(v, "s1") == []            # the mutant that adds `regulates` ACCEPTS this


def test_is_a_step_citing_a_regulates_edge_is_edge_not_found_with_actual_relation():
    v = check(deriv(prop(C, subject=P7),
                    [axiom("s1", R, subject=P7), prop_step("s2", "is_a", "s1", R, C, subject=P7)], "s2"), STORE)
    e = only(v, "s2", Code.EDGE_NOT_FOUND)
    assert e["actual"] == {"parents_of_child": [["regulates", C]]}
    assert e["suggestions"] == []


def test_edge_not_found_suggests_the_other_propagating_relation():
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", A, C)], "s2"), STORE)
    e = only(v, "s2", Code.EDGE_NOT_FOUND)
    assert e["suggestions"] == [{"rule": "part_of", "edge": [A, C]}]
    assert e["actual"]["parents_of_child"] == [["is_a", B], ["part_of", C], ["part_of", D]]


def test_part_of_across_namespaces_is_namespace_crossed():
    steps = [axiom("s1", MF2, subject=P3, qualifier="enables"),
             prop_step("s2", "part_of", "s1", MF2, C, subject=P3, qualifier="enables")]
    v = check(deriv(prop(C, subject=P3, qualifier="enables"), steps, "s2"), STORE)
    assert codes(v, "s2") == [Code.NAMESPACE_CROSSED, Code.QUALIFIER_ASPECT_MISMATCH]
    assert codes(v, "s1") == []


def test_negated_premise_cannot_propagate():
    for stated_negated in (False, True):
        steps = [axiom("s1", X, subject=P2, negated=True),
                 prop_step("s2", "is_a", "s1", X, Y, subject=P2, negated=stated_negated)]
        v = check(deriv(prop(Y, subject=P2, negated=stated_negated), steps, "s2"), STORE)
        assert Code.NEGATED_PREMISE in codes(v, "s2"), stated_negated
        assert codes(v, "s1") == []
    v = check(deriv(prop(Y, subject=P2), [axiom("s1", X, subject=P2, negated=True),
                                          prop_step("s2", "is_a", "s1", X, Y, subject=P2)], "s2"), STORE)
    assert codes(v, "s2") == [Code.NEGATED_PREMISE]


def test_conclusion_must_equal_computed_conclusion():
    bad = {**prop_step("s2", "is_a", "s1", B, C), "conclusion": prop(D)}
    v = check(deriv(prop(D), [axiom("s1", B), bad], "s2"), STORE)
    e = only(v, "s2", Code.CONCLUSION_MISMATCH)
    assert e["expected"] == prop(C) and e["actual"] == prop(D)


def test_premise_mismatch_when_edge_starts_elsewhere():
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", B, C)], "s2"), STORE)
    e = only(v, "s2", Code.PREMISE_MISMATCH)
    assert e["expected"] == B and e["actual"] == A


def test_every_error_is_reported_not_just_the_first():
    steps = [axiom("s1", "GO:0009999"), axiom("s2", C, qualifier="enables")]
    v = check(deriv(prop(C, qualifier="enables"), steps, "s2"), STORE)
    assert Code.UNKNOWN_TERM in codes(v, "s1")
    assert Code.QUALIFIER_ASPECT_MISMATCH in codes(v, "s2")


def test_one_broken_axiom_yields_one_error_down_a_chain():
    steps = [axiom("s1", X), prop_step("s2", "is_a", "s1", X, Y), prop_step("s3", "is_a", "s2", Y, T)]
    v = check(deriv(prop(T), steps, "s3"), STORE)
    assert [(e["step"], e["code"]) for e in v["errors"]] == [("s1", Code.AXIOM_NOT_FOUND)]
    assert v["premise_failed"] == ["s2"]


def test_dependent_step_is_still_checked_when_premise_failed():
    steps = [axiom("s1", X), prop_step("s2", "is_a", "s1", X, T)]
    v = check(deriv(prop(T), steps, "s2"), STORE)
    assert codes(v, "s1") == [Code.AXIOM_NOT_FOUND]
    assert codes(v, "s2") == [Code.EDGE_NOT_FOUND]
    assert v["premise_failed"] == ["s2"]


def test_sorry_is_counted_and_does_not_reject():
    v = check(deriv(prop(T), [sorry("s1", T)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert v["sorry_count"] == 1 and v["unused_sorries"] == 0
    assert v["sorries"] == [{"step": "s1", "used": True, "method": "m:deseq2", "inputs": ["GEO:GSE1"]}]


def test_unused_sorry_does_not_count_toward_sorry_count():
    steps = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)]
    v = check(deriv(prop(C), steps, "s2"), STORE)
    assert v["errors"] == []
    assert v["sorry_count"] == 0 and v["unused_sorries"] == 1
    assert v["unused_steps"] == ["s3"] and v["sorries"][0]["used"] is False


def test_error_in_unused_step_still_rejects():
    steps = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), axiom("s3", "GO:0009999")]
    v = check(deriv(prop(C), steps, "s2"), STORE)
    assert v["verdict"] == "REJECTED" and codes(v, "s3") == [Code.UNKNOWN_TERM]
    assert v["unused_steps"] == ["s3"]


def test_sorry_with_missing_inputs_is_malformed():
    bad = sorry("s1", T, provenance={"method": "m:x", "parameters": {}, "claim": "c"})
    only(check(deriv(prop(T), [bad], "s1"), STORE), "s1", Code.SORRY_MALFORMED)
    empty = sorry("s1", T, provenance={"method": "m:x", "inputs": [], "parameters": {}, "claim": "c"})
    only(check(deriv(prop(T), [empty], "s1"), STORE), "s1", Code.SORRY_MALFORMED)
    missing = {"id": "s1", "rule": "sorry", "conclusion": prop(T)}
    only(check(deriv(prop(T), [missing], "s1"), STORE), "s1", Code.SORRY_MALFORMED)


def test_sorry_negated_is_rejected():
    v = check(deriv(prop(T, negated=True), [sorry("s1", T, negated=True)], "s1"), STORE)
    only(v, "s1", Code.SORRY_NEGATED)


def test_sorry_at_unknown_subject_is_unknown_subject():
    v = check(deriv(prop(T, subject="UniProtKB:NOPE"), [sorry("s1", T, subject="UniProtKB:NOPE")], "s1"), STORE)
    assert Code.UNKNOWN_SUBJECT in codes(v, "s1")


def test_suggestions_are_always_spliceable():
    from methods_graph.biolean.props import Annotation, Edge, Term
    from methods_graph.biolean.store import StaticFactStore

    terms = [
        Term(id="GO:1", name="one", namespace="biological_process", obsolete=False,
             replaced_by=(), consider=(), alt_ids=()),
        Term(id="GO:2", name="two", namespace="biological_process", obsolete=True,
             replaced_by=(), consider=(), alt_ids=()),
    ]
    edges = [Edge(child="GO:2", relation="is_a", parent="GO:1")]
    annotations = [
        Annotation(id="a1", subject="UniProtKB:X", symbol="X", qualifier="involved_in",
                   negated=False, term="GO:2", term_raw="GO:2", references=("PMID:1",),
                   code="IDA", eco="ECO:0000314", with_from=(), aspect="P",
                   object_type="protein", taxon="NCBITaxon:9606", interacting_taxon="",
                   date="20200101", assigned_by="UniProt", extension="", form=""),
        # An aspect-inconsistent row (located_in on a biological_process term) that the
        # loader keeps as-is; the kernel must never suggest splicing it back in.
        Annotation(id="a2", subject="UniProtKB:X", symbol="X", qualifier="located_in",
                   negated=False, term="GO:1", term_raw="GO:1", references=("PMID:2",),
                   code="IDA", eco="ECO:0000314", with_from=(), aspect="C",
                   object_type="protein", taxon="NCBITaxon:9606", interacting_taxon="",
                   date="20200101", assigned_by="UniProt", extension="", form=""),
    ]
    store = StaticFactStore(terms, edges, annotations)
    v = check(deriv(prop("GO:1", subject="UniProtKB:X"),
                    [axiom("s1", "GO:1", subject="UniProtKB:X")], "s1"), store)
    e = only(v, "s1", Code.AXIOM_NOT_FOUND)
    assert e["suggestions"] == []


def test_axiom_suggests_same_qualifier_at_a_descendant():
    v = check(deriv(prop("GO:0000070", subject=P7), [axiom("s1", "GO:0000070", subject=P7)], "s1"), STORE)
    e = only(v, "s1", Code.AXIOM_NOT_FOUND)
    assert {"rule": "axiom", "conclusion": prop("GO:0000090", subject=P7)} in e["suggestions"]


def test_axiom_suggests_the_same_proposition_under_another_taxon():
    from methods_graph.biolean.props import Annotation, Term
    from methods_graph.biolean.store import StaticFactStore

    terms = [Term(id="GO:1", name="one", namespace="biological_process", obsolete=False,
                  replaced_by=(), consider=(), alt_ids=())]
    annotations = [
        Annotation(id="a1", subject="UniProtKB:X", symbol="X", qualifier="involved_in",
                   negated=False, term="GO:1", term_raw="GO:1", references=("PMID:1",),
                   code="IDA", eco="ECO:0000314", with_from=(), aspect="P",
                   object_type="protein", taxon="NCBITaxon:10090", interacting_taxon="",
                   date="20200101", assigned_by="UniProt", extension="", form=""),
    ]
    store = StaticFactStore(terms, [], annotations)
    v = check(deriv(prop("GO:1", subject="UniProtKB:X", taxon="NCBITaxon:9606"),
                    [axiom("s1", "GO:1", subject="UniProtKB:X", taxon="NCBITaxon:9606")], "s1"), store)
    e = only(v, "s1", Code.AXIOM_NOT_FOUND)
    assert {"rule": "axiom",
            "conclusion": prop("GO:1", subject="UniProtKB:X", taxon="NCBITaxon:10090")} in e["suggestions"]


# ---------- conflicts ----------

def test_conflict_at_the_term_is_listed_without_changing_the_verdict():
    v = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    [c] = v["conflicts"]
    assert c["step"] == "s1" and c["negated"] is True and c["code"] == "IDA"
    assert c["at"] == "term" and c["via"] == C


def test_conflict_at_an_ancestor_is_listed():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert v["errors"] == []
    [c] = v["conflicts"]
    assert c == {"step": "s1", "annotation": c["annotation"], "negated": True, "code": "IDA",
                 "at": "ancestor", "via": C}


def test_conflict_at_a_descendant_of_a_negated_conclusion_is_listed():
    v = check(deriv(prop(C, negated=True), [axiom("s1", C, negated=True)], "s1"), STORE)
    assert v["errors"] == []
    ats = sorted((c["at"], c["via"]) for c in v["conflicts"])
    assert ("term", C) in ats                                  # the positive IDA/IEA rows at C
    assert {via for at, via in ats if at == "descendant"} == {A, B, D}
    assert all(c["negated"] is False for c in v["conflicts"])
    assert [c["annotation"] for c in v["conflicts"]] == sorted(c["annotation"] for c in v["conflicts"])


def test_conflicts_never_follow_regulates_and_list_each_annotation_once():
    # P00001's NOT row is at C = GO:0000010, and R regulates C; if regulates were followed,
    # this would surface that row as an ancestor conflict. A sorry keeps the step valid
    # without needing an axiom row at R (there is none for P00001).
    v = check(deriv(prop(R), [sorry("s1", R)], "s1"), STORE)
    assert v["errors"] == [] and v["conflicts"] == []
    two = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)]
    v = check(deriv(prop(C), two, "s2"), STORE)
    ids = [c["annotation"] for c in v["conflicts"]]
    assert len(ids) == len(set(ids)) == 1 and v["conflicts"][0]["step"] == "s1"


def test_sorry_conclusions_participate_in_conflicts():
    v = check(deriv(prop(C), [sorry("s1", C)], "s1"), STORE)
    assert v["errors"] == []
    assert len(v["conflicts"]) == 1
    [c] = v["conflicts"]
    assert c["step"] == "s1" and c["at"] == "term" and c["via"] == C and c["negated"] is True


# ---------- sortedness and the golden verdict ----------

GOLDEN = deriv(prop(T, subject=P2), [
    axiom("s9", Y, subject=P2),
    prop_step("s8", "is_a", "s9", Y, T, subject=P2),
    sorry("s7", T, subject=P2),
    axiom("s6", A),
    prop_step("s5", "part_of", "s6", A, C),
    sorry("s4", D),
    axiom("s3", MF2, subject=P3, qualifier="enables", code="IDA"),
    axiom("s2", X),
    prop_step("s1", "is_a", "s2", X, Y),
], "s8")

IDX = {s["id"]: i for i, s in enumerate(GOLDEN["steps"])}   # step id -> position

# Collection -> the key §3 declares. `sorries` and `conflicts` sort by step POSITION (the
# derivation's order), `unused_steps`/`premise_failed` by step id string.
_SORT_KEYS = {
    "unused_steps": lambda x: x,
    "premise_failed": lambda x: x,
    "axioms": lambda d: d["annotation"],
    "sorries": lambda d: IDX[d["step"]],
    "conflicts": lambda d: (IDX[d["step"]], d["annotation"]),
    "references": lambda x: x,
    "suggestions": lambda d: json.dumps(d, sort_keys=True),
}


def test_report_collections_are_sorted_by_their_declared_keys():
    v = check(GOLDEN, STORE)
    assert v["verdict"] == "REJECTED" and len(v["errors"]) == 1
    assert v["unused_steps"] == ["s1", "s2", "s3", "s4", "s5", "s6", "s7"]  # id order, not position
    assert v["premise_failed"] == ["s1"]
    assert [s["step"] for s in v["sorries"]] == ["s7", "s4"]        # position order
    for key, sort_key in _SORT_KEYS.items():
        found = False
        for node in _walk(v, key):
            found = True
            assert node == sorted(node, key=sort_key), key
        assert found, key    # a dropped or renamed collection must not pass silently


def _walk(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, list):
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)


def test_verdict_matches_committed_golden():
    from pathlib import Path
    from methods_graph.biolean.kernel import dumps
    golden = Path(__file__).parent / "fixtures" / "biolean" / "golden_verdict.json"
    assert dumps(check(GOLDEN, STORE)) + "\n" == golden.read_text(encoding="utf-8")


def test_axioms_are_sorted_by_annotation_id_not_step_order():
    """On GOLDEN, `axioms` happens to already be in both step order and id order, so a
    constant sort key would pass by coincidence. Here the steps are built in DESCENDING
    matched-annotation-id order, so id order and step order disagree."""
    candidates = [
        (P1, "involved_in", B), (P1, "involved_in", D),
        (P2, "involved_in", X), (P2, "involved_in", Y), (P2, "involved_in", T),
        (P3, "enables", MF1),
        ("UniProtKB:P00004", "located_in", "GO:0000310"),
        (P7, "involved_in", R),
    ]
    rows = []
    for subject, qualifier, term in candidates:
        matches = STORE.matching(Prop(subject, qualifier, term, TAX, False))
        assert len(matches) == 1, (subject, qualifier, term, matches)
        rows.append((matches[0].id, subject, qualifier, term))
    assert len(rows) >= 5
    rows.sort(key=lambda r: r[0], reverse=True)   # steps built in DESCENDING id order

    steps = [axiom(f"s{i}", term, subject=subject, qualifier=qualifier)
             for i, (_ann_id, subject, qualifier, term) in enumerate(rows, start=1)]
    root = steps[0]["id"]
    goal = steps[0]["conclusion"]
    v = check(deriv(goal, steps, root), STORE)

    assert v["errors"] == []
    assert len(v["axioms"]) >= 5
    ids_in_output = [a["annotation"] for a in v["axioms"]]
    step_order_ids = [r[0] for r in rows]
    assert ids_in_output == sorted(ids_in_output)
    assert ids_in_output != step_order_ids


def test_premise_failed_is_sorted_by_id_not_position():
    """Two independent broken chains whose consumer steps are named so that id order
    disagrees with position order: s8 (position 1) comes before s1 (position 3), but
    "s1" < "s8" lexicographically."""
    steps = [
        axiom("s9", X),                                    # P1 has no row at X: AXIOM_NOT_FOUND
        prop_step("s8", "is_a", "s9", X, Y),                # premise_failed, otherwise clean
        axiom("s3", B, subject=P2),                         # P2 has no row at B: AXIOM_NOT_FOUND
        prop_step("s1", "is_a", "s3", B, C, subject=P2),    # premise_failed, otherwise clean
    ]
    v = check(deriv(prop(Y), steps, "s8"), STORE)
    assert codes(v, "s9") == [Code.AXIOM_NOT_FOUND]
    assert codes(v, "s3") == [Code.AXIOM_NOT_FOUND]
    assert codes(v, "s8") == []
    assert codes(v, "s1") == []
    assert v["premise_failed"] == ["s1", "s8"]         # id order, though s8 comes first


def test_propagating_parents_and_children_are_duals_over_the_fixture():
    from methods_graph.biolean.kernel import propagating_children, propagating_parents
    # A's parents: is_a B, part_of C, part_of D — sorted by parent id.
    assert propagating_parents(A, STORE) == ((B, "is_a"), (C, "part_of"), (D, "part_of"))
    # C's children exclude the regulates edge (R) and the cross-namespace part_of (MF2).
    assert propagating_children(C, STORE) == ((B, "is_a"), (D, "is_a"), (A, "part_of"))
    assert propagating_parents("GO:0009999", STORE) == ()
    for term in (A, B, C, D, X, Y, T, MF1, MF2):
        for parent, relation in propagating_parents(term, STORE):
            assert (term, relation) in propagating_children(parent, STORE)


from methods_graph.biolean import kernel as kernel_mod
from methods_graph.biolean.kernel import check_qualifier_aspect, check_term


def test_check_term_is_public_and_the_private_name_is_gone():
    assert not hasattr(kernel_mod, "_check_term")
    assert check_term(C, STORE, None) == []
    assert [e.code for e in check_term(ALT, STORE, None)] == [Code.ALT_ID_IN_KERNEL]
    assert [e.code for e in check_term(OBS, STORE, None)] == [Code.OBSOLETE_TERM]
    assert check_term(OBS, STORE, None)[0].expected == {"replaced_by": [C], "consider": [D]}
    assert [e.code for e in check_term("GO:0009999", STORE, None)] == [Code.UNKNOWN_TERM]


def test_check_qualifier_aspect_is_the_prop_check_minus_subject_and_taxon():
    # Legal pair: nothing. Unknown qualifier: the 13. Mismatch: aspect letters.
    assert check_qualifier_aspect("involved_in", C, STORE) == []
    [e] = check_qualifier_aspect("binds", C, STORE)
    assert e.code == Code.UNKNOWN_QUALIFIER and e.expected == sorted(kernel_mod.QUALIFIER_ASPECT) and e.actual == "binds"
    [e] = check_qualifier_aspect("enables", C, STORE)
    assert e.code == Code.QUALIFIER_ASPECT_MISMATCH and (e.expected, e.actual) == ("F", "P")
    # Unknown or obsolete term: the qualifier is still checked, the aspect is not.
    assert check_qualifier_aspect("enables", "GO:0009999", STORE) == []
    assert check_qualifier_aspect("enables", OBS, STORE) == []
    assert [e.code for e in check_qualifier_aspect("binds", OBS, STORE)] == [Code.UNKNOWN_QUALIFIER]
    # It is what _check_prop emits for these two codes, so the extraction changed nothing.
    for q, t in (("binds", C), ("enables", C), ("involved_in", C), ("enables", OBS)):
        via_prop = [e.code for e in kernel_mod._check_prop(Prop(P1, q, t, TAX, False), STORE, "s", 0)
                    if e.code in (Code.UNKNOWN_QUALIFIER, Code.QUALIFIER_ASPECT_MISMATCH)]
        assert via_prop == [e.code for e in check_qualifier_aspect(q, t, STORE, "s", 0)]
