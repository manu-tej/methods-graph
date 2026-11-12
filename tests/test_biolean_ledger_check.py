"""The append check (spec section 2) over the ledger fixture base. No signing here: check_axiom,
check_derived and check_computed are pure functions of a body and a store. Every rejection
assertion names (code, field); every acceptance asserts errors == []."""
from methods_graph.biolean.gaf import GAF_COLUMNS, annotation_id, parse_gaf
from methods_graph.biolean.kernel import check
from methods_graph.biolean.ledger.check import (
    check_axiom, check_computed, check_derived, content_key, fact_from_body, qualifier_options, term_errors)
from methods_graph.biolean.ledger.errors import ALL_LEDGER_CODES, LedgerCode as LC
from methods_graph.biolean.ledger.format import pointer_set
from methods_graph.biolean.props import QUALIFIER_ASPECT, Prop
from methods_graph.biolean.store import StaticFactStore
from methods_graph.biolean.tactics import prove
from tests.biolean_ledger_fixture import KEY16_A, KEY16_B, base_row, context, ledger_base, new_fact

BASE = ledger_base()
CTX = context(KEY16_A)
BY_A_COL = "biolean:" + KEY16_A
P_QUALS = tuple(sorted(q for q, a in QUALIFIER_ASPECT.items() if a == "P"))
F_QUALS = ("contributes_to", "enables")
SEVEN = {"code", "message", "field", "got", "fix", "options", "context"}
TAX = "NCBITaxon:9606"


def run(fact, ctx=CTX, **kw):
    return check_axiom(fact, ctx, **kw)


def codes(res):
    return [(e.code, e.field) for e in res.errors]


def only(res, code, field):
    errs = [e for e in res.errors if e.code == code and e.field == field]
    assert len(errs) == 1, codes(res)
    return errs[0]


def apply_fixes(fact, res):
    """RFC 6901 replace of every non-null fix, all at once, on the submitted row."""
    doc = {"fact": list(fact)}
    for e in res.errors:
        if e.fix is not None:
            doc = pointer_set(doc, e.field, e.fix)
    return doc["fact"]


def prop(term, subject="UniProtKB:P10003", qualifier="involved_in", negated=False, taxon=TAX):
    return {"subject": subject, "qualifier": qualifier, "term": term, "taxon": taxon, "negated": negated}


def good_derivation():
    return {"biolean": "0.1", "goal": prop("GO:0000002"),
            "steps": [{"id": "s1", "rule": "axiom", "conclusion": prop("GO:0000003")},
                      {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                       "conclusion": prop("GO:0000002")}],
            "root": "s2"}


# ---------- steps 1, 1a, 7 ----------

def test_the_example_fact_is_admitted_with_column_15_filled_and_a_check_block():
    res = run(new_fact())
    assert res.errors == [] and res.deferred == [] and res.ok
    assert res.fact[14] == BY_A_COL and res.fact[:14] == new_fact()[:14]
    assert res.annotation.id == annotation_id(res.fact) == res.check["annotation_id"]
    assert set(res.check) == {"kernel", "annotation_id", "contested_by", "counters"}
    assert res.check["contested_by"] == [] and res.check["counters"] == {"new_subject": 0}
    assert res.gaf_report["annotations"] == 1


def test_assigned_by_empty_is_filled_and_wrong_value_rejected():
    e = only(run(new_fact(assigned_by="UniProt")), LC.LEDGER_ASSIGNED_BY, "/fact/14")
    assert (e.got, e.fix) == ("UniProt", BY_A_COL)
    assert run(new_fact(assigned_by=BY_A_COL)).ok
    # recheck mode: empty is a failure, the signer's value passes (spec section 3 base binding)
    assert (LC.LEDGER_ASSIGNED_BY, "/fact/14") in codes(run(new_fact(), mode="recheck"))
    assert run(new_fact(assigned_by=BY_A_COL), mode="recheck").ok


def test_bad_columns_rejected_with_column_names_in_context():
    for bad in (new_fact()[:16], new_fact() + [""], new_fact()[:13] + [20260925] + new_fact()[14:], "x", None):
        res = run(bad)
        [e] = res.errors
        assert (e.code, e.field, e.fix, e.options) == (LC.LEDGER_BAD_COLUMNS, "/fact", None, ())
        assert e.context == {"columns": list(GAF_COLUMNS)} and res.deferred == []


def test_bad_columns_got_is_the_fact_as_submitted():
    # Spec section 7: got is the whole value at /fact as submitted. Break: got=None for a non-list.
    for bad in ("x", 20260925, {"db": "UniProtKB"}, None, new_fact()[:16]):
        [e] = run(bad).errors
        assert (e.code, e.field, e.got) == (LC.LEDGER_BAD_COLUMNS, "/fact", bad), bad


def test_non_string_column_value_is_bad_columns():
    obj = dict(zip(GAF_COLUMNS, new_fact()))
    obj["date"] = 20260925
    fact, errs = fact_from_body(obj)
    assert errs == [] and fact[13] == 20260925
    [e] = run(fact).errors
    assert (e.code, e.field) == (LC.LEDGER_BAD_COLUMNS, "/fact")


def test_fact_from_body_object_form_and_bad_body():
    obj = dict(zip(GAF_COLUMNS, new_fact()))
    del obj["with_from"]
    fact, errs = fact_from_body(obj)
    assert errs == [] and fact == new_fact()
    fact, [e] = fact_from_body({**obj, "extra": "x"})
    assert fact is None and (e.code, e.field, e.got) == (LC.LEDGER_BAD_COLUMNS, "/fact", {**obj, "extra": "x"})
    assert "extra" in e.message                                 # got is the object as submitted; the names are in the message
    assert e.context == {"columns": list(GAF_COLUMNS)}
    fact, [e] = fact_from_body("a string")
    assert fact is None and (e.code, e.field) == (LC.LEDGER_BAD_BODY, "/fact")
    assert fact_from_body(new_fact()) == (new_fact(), [])


def test_lone_surrogate_is_bad_character_not_a_crash():
    res = run(new_fact(gene_product_form_id="\ud800"))
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_BAD_CHARACTER, "/fact/16", "U+D800", "")
    assert run(apply_fixes(new_fact(gene_product_form_id="\ud800"), res)).ok


def test_trailing_cr_in_column_17_rejected():
    # Break: strip "\r" before checking (parse_gaf would then give a different annotation id).
    res = run(new_fact(gene_product_form_id="x\r"))
    e = only(res, LC.LEDGER_BAD_CHARACTER, "/fact/16")
    assert (e.got, e.fix) == ("U+000D", "x")


def test_empty_columns_15_16_17_pass_character_check():
    assert not any(e.code == LC.LEDGER_BAD_CHARACTER for e in run(new_fact()).errors)


def test_character_fix_feeds_later_steps():
    # Refinement 1: a tab hiding a valid term id gives only the character error, not UNKNOWN_TERM.
    res = run(new_fact(go_id="GO:0000003\t"))
    assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/4")] and res.deferred == []


# ---------- step 2 ----------

def test_bad_subject_rejected_and_new_subject_counted():
    res = run(new_fact(db="1abc", db_object_id="P|1"))
    assert codes(res) == [(LC.LEDGER_BAD_SUBJECT, "/fact/0"), (LC.LEDGER_BAD_SUBJECT, "/fact/1")]
    assert res.deferred == [{"step": 8, "waits_on": [1, 2]}]
    assert (LC.LEDGER_BAD_SUBJECT, "/fact/1") in codes(run(new_fact(db_object_id="")))
    assert (LC.LEDGER_BAD_SUBJECT, "/fact/0") in codes(run(new_fact(db="")))
    # a space in column 2 is a step 1a fault first; step 2 then sees the cleaned value
    assert codes(run(new_fact(db_object_id="P1 2"))) == [(LC.LEDGER_BAD_CHARACTER, "/fact/1")]
    res = run(new_fact(db_object_id="P99999"))
    assert res.ok and res.check["counters"] == {"new_subject": 1}


# ---------- step 3 ----------

def test_unknown_term_rejected():
    res = run(new_fact(go_id="GO:0009999"))
    e = only(res, LC.UNKNOWN_TERM, "/fact/4")
    assert (e.got, e.fix, e.options) == ("GO:0009999", None, ())
    assert res.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]


def test_obsolete_term_rejected_with_replaced_by_fix():
    res = run(new_fact(go_id="GO:0000010"))
    e = only(res, LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix == "GO:0000002" and e.context == {"replaced_by": ["GO:0000002"], "consider": []}
    assert res.deferred == [] and codes(res) == [(LC.OBSOLETE_TERM, "/fact/4")]
    assert run(apply_fixes(new_fact(go_id="GO:0000010"), res)).ok


def test_alt_id_rejected_with_primary_fix():
    e = only(run(new_fact(go_id="GO:0000102")), LC.LEDGER_ALT_ID, "/fact/4")
    assert (e.got, e.fix, e.options) == ("GO:0000102", "GO:0000002", ())


def test_alt_id_with_obsolete_primary_fixes_to_the_replacement():
    # Break: fix = the obsolete primary GO:0000010 (what the kernel's ALT_ID_IN_KERNEL carries).
    e = only(run(new_fact(go_id="GO:0000110")), LC.LEDGER_ALT_ID, "/fact/4")
    assert e.fix == "GO:0000002" and "GO:0000010" in e.message and "GO:0000110" in e.message


def test_obsolete_without_single_replaced_by_uses_consider_options():
    # Break: offer the raw consider list (GO:0000999 is not a term); or fix = replaced_by[0].
    e = only(run(new_fact(go_id="GO:0000012")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ("GO:0000002", "GO:0000003")
    assert e.context == {"replaced_by": [], "consider": ["GO:0000002", "GO:0000003", "GO:0000999"]}
    e = only(run(new_fact(go_id="GO:0000014")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ("GO:0000002", "GO:0000003")
    e = only(run(new_fact(go_id="GO:0000013")), LC.OBSOLETE_TERM, "/fact/4")
    assert e.fix is None and e.options == ()
    assert term_errors("GO:0000003", CTX.store, "/x") == []


# ---------- step 4 ----------

def test_qualifier_illegal_for_aspect_rejected_with_legal_options():
    e = only(run(new_fact(qualifier="enables")), LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3")
    assert (e.got, e.fix, e.options) == ("enables", None, P_QUALS)
    assert qualifier_options("F") == F_QUALS and len(qualifier_options(None)) == 13


def test_aspect_must_match_term_namespace():
    e = only(run(new_fact(aspect="F")), LC.LEDGER_ASPECT_MISMATCH, "/fact/8")
    assert (e.got, e.fix) == ("F", "P")


def test_unknown_qualifier_options_match_aspect_and_keep_not():
    # Break: offer all 13 for a resolved term; or strip NOT|.
    e = only(run(new_fact(qualifier="NOT|bogus")), LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert e.got == "NOT|bogus" and e.options == tuple("NOT|" + q for q in P_QUALS)
    res = run(new_fact(qualifier="NOT|bogus", go_id="GO:0009999"))
    e = only(res, LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert len(e.options) == 13 and all(o.startswith("NOT|") for o in e.options)
    assert res.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [4, 5]}]
    e = only(run(new_fact(qualifier="a|b")), LC.UNKNOWN_QUALIFIER, "/fact/3")
    assert e.options == ()


def test_qualifier_fix_preserves_not():
    # Break: emit the kernel's bare `expected` list. Caught by the negated assertion, not by ACCEPTED.
    for q, code in (("NOT|involved in", LC.UNKNOWN_QUALIFIER), ("NOT|enables", LC.QUALIFIER_ASPECT_MISMATCH)):
        res = run(new_fact(qualifier=q))
        e = only(res, code, "/fact/3")
        assert e.options and all(o.startswith("NOT|") for o in e.options)
        for option in e.options:
            fixed = run(pointer_set({"fact": new_fact(qualifier=q)}, "/fact/3", option)["fact"])
            assert fixed.ok and fixed.annotation.negated is True, (q, option)


# ---------- step 5 ----------

def test_reference_must_carry_doi_pmid_or_go_ref():
    for refs in ("foo:1", "", "|"):
        e = only(run(new_fact(db_reference=refs)), LC.LEDGER_REFERENCE_REQUIRED, "/fact/5")
        assert e.fix is None and e.options == () and e.got == refs
    assert run(new_fact(db_reference="foo:1|PMID:5")).ok
    assert run(new_fact(db_reference="GO_REF:0000002")).ok


def test_bad_reference_syntax_rejected():
    res = run(new_fact(db_reference="DOI:10.1/x|PMID:0|GO_REF:12"))
    errs = [e for e in res.errors if e.code == LC.LEDGER_BAD_REFERENCE]
    assert len(errs) == 3 and all(e.field == "/fact/5" and e.got == "DOI:10.1/x|PMID:0|GO_REF:12" and e.fix is None for e in errs)
    assert not any(e.code == LC.LEDGER_REFERENCE_REQUIRED for e in res.errors)
    assert run(new_fact(db_reference="DOI:10.1234/abc.def-1|PMID:12|GO_REF:0000001")).ok


def test_unmapped_evidence_code_rejected():
    e = only(run(new_fact(evidence_code="XYZ")), LC.LEDGER_ECO_UNMAPPED, "/fact/6")
    assert (e.fix, e.options) == (None, ("IDA", "IEA", "IMP", "IPI"))


# ---------- step 6 ----------

def test_bad_taxon_date_and_empty_object_type_rejected():
    e = only(run(new_fact(taxon="taxon:abc")), LC.LEDGER_BAD_TAXON, "/fact/12")
    assert e.fix is None and e.context == {"form": "taxon:<digits>"}
    assert only(run(new_fact(taxon="taxon:1|taxon:2|taxon:3")), LC.LEDGER_BAD_TAXON, "/fact/12").fix is None
    assert only(run(new_fact(taxon="taxon:9606|")), LC.LEDGER_BAD_TAXON, "/fact/12").fix is None
    for date in ("2026-13-01", "20261301", "2026925", "yesterday"):
        e = only(run(new_fact(date=date)), LC.LEDGER_BAD_DATE, "/fact/13")
        assert e.fix is None and e.context == {"form": "YYYYMMDD"}, date
    e = only(run(new_fact(db_object_type="")), LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11")
    assert e.fix == "protein"                                   # P10002 is known to the base
    e = only(run(new_fact(db_object_id="P99999", db_object_type="")), LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11")
    assert e.fix is None
    # ordered by step, then by column (spec section 2). Break: emit taxon and date before object type.
    res = run(new_fact(taxon="taxon:abc", date="bad", db_object_type=""))
    assert codes(res) == [(LC.LEDGER_BAD_OBJECT_TYPE, "/fact/11"), (LC.LEDGER_BAD_TAXON, "/fact/12"),
                          (LC.LEDGER_BAD_DATE, "/fact/13")]
    assert res.deferred == [{"step": 8, "waits_on": [13, 14]}]


def test_bad_taxon_spelling_gets_rewritten_fix():
    # Break: fix only the first value; or emit NCBITaxon: (parse_gaf accepts it, GAF 2.2 does not).
    for got, fix in (("NCBITaxon:9606", "taxon:9606"), ("9606", "taxon:9606"),
                     ("9606|NCBITaxon:562", "taxon:9606|taxon:562"), ("taxon:9606|562", "taxon:9606|taxon:562")):
        res = run(new_fact(taxon=got))
        e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
        assert (e.got, e.fix) == (got, fix)
        assert run(apply_fixes(new_fact(taxon=got), res)).ok
    e = only(run(new_fact(date="2026-09-25")), LC.LEDGER_BAD_DATE, "/fact/13")
    assert e.fix == "20260925"


def test_non_ascii_taxon_digits_are_a_bad_taxon_never_a_crash():
    # Break: drop the ASCII guard before int(). normalize_taxon accepts any str.isdigit()
    # character; int() refuses U+00B2, so recheck (no step 1a cleaning) raised ValueError.
    for taxon in ("taxon:\u00b2", "\u00b2", "taxon:9606|taxon:\u00b2", "taxon:\u0662"):
        res = run(new_fact(taxon=taxon, assigned_by=BY_A_COL), mode="recheck")
        assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/12"), (LC.LEDGER_BAD_TAXON, "/fact/12")], taxon
        e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
        assert (e.got, e.fix, e.context) == (taxon, None, {"form": "taxon:<digits>"}), taxon
    # append is unchanged: step 1a strips the digit first, so step 6 sees "taxon:"
    res = run(new_fact(taxon="taxon:\u00b2"))
    assert [(e.code, e.field, e.got, e.fix, e.context) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/fact/12", "U+00B2", "taxon:", None),
        (LC.LEDGER_BAD_TAXON, "/fact/12", "taxon:", None, {"form": "taxon:<digits>"})]
    assert res.deferred == [{"step": 8, "waits_on": [13]}] and res.fact is None and res.annotation is None


def test_taxon_longer_than_the_int_digit_limit_is_checked_not_raised():
    # Break: build the canonical fix with str(int(d)). int() refuses more than 4300 digits
    # (CPython's default limit), so a long taxon raised ValueError in both modes. The long
    # spellings must give what the short ones give.
    for digits in ("562", "7" * 4301):
        for got, fix in (("NCBITaxon:" + digits, "taxon:" + digits), (digits, "taxon:" + digits),
                         ("taxon:9606|" + digits, "taxon:9606|taxon:" + digits)):
            for mode in ("append", "recheck"):
                res = run(new_fact(taxon=got, assigned_by=BY_A_COL), mode=mode)
                assert [(e.code, e.field, e.got, e.fix) for e in res.errors] == [
                    (LC.LEDGER_BAD_TAXON, "/fact/12", got, fix)], (mode, got[:24], len(got))


def test_leading_zero_taxon_is_not_canonical_and_cannot_dodge_the_duplicate_check():
    # Refinement 22. Break: accept leading zeros in column 13. "taxon:09606" then parses to
    # NCBITaxon:09606, a different key from the base row's NCBITaxon:9606, and is admitted again.
    row = base_row(1)
    row[12], row[14] = "taxon:09606", BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.LEDGER_BAD_TAXON, "/fact/12"), (LC.LEDGER_DUPLICATE, "/fact")]
    e = only(res, LC.LEDGER_BAD_TAXON, "/fact/12")
    assert (e.got, e.fix) == ("taxon:09606", "taxon:9606")
    assert codes(run(apply_fixes(row, res))) == [(LC.LEDGER_DUPLICATE, "/fact")]
    e = only(run(row, mode="recheck"), LC.LEDGER_BAD_TAXON, "/fact/12")
    assert (e.got, e.fix) == ("taxon:09606", "taxon:9606")
    # the second value too; an all-zero value keeps one zero, and each fix clears its error
    for got, fix in (("taxon:9606|taxon:0562", "taxon:9606|taxon:562"), ("taxon:00", "taxon:0")):
        res = run(new_fact(taxon=got))
        assert only(res, LC.LEDGER_BAD_TAXON, "/fact/12").fix == fix
        assert (LC.LEDGER_BAD_TAXON, "/fact/12") not in codes(run(apply_fixes(new_fact(taxon=got), res)))


# ---------- step 8 ----------

def test_content_key_ignores_display_columns_date_and_assigned_by():
    r1, r2 = base_row(1), base_row(2)
    anns, _ = parse_gaf(["\t".join(r1), "\t".join(r2)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert len(anns) == 2 and content_key(anns[0]) == content_key(anns[1]) and anns[0].id != anns[1].id
    r3 = list(r1)
    r3[6] = "IMP"
    [a3], _ = parse_gaf(["\t".join(r3)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert content_key(a3) != content_key(anns[0])


def test_base_row_resubmitted_with_own_assigned_by_is_duplicate():
    # Mutations that must fail: compare annotation ids; use a raw-column key.
    row = base_row(1)
    row[5] = "PMID:99|PMID:100"                 # reordered
    row[9] = row[10] = ""                       # display columns emptied
    row[12] = "NCBITaxon:9606"                  # spelling corrected by the taxon fix
    row[13] = "20260925"                        # new date
    row[14] = BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.LEDGER_BAD_TAXON, "/fact/12"), (LC.LEDGER_DUPLICATE, "/fact")]
    dup = only(res, LC.LEDGER_DUPLICATE, "/fact")
    ids = sorted([annotation_id(base_row(1)), annotation_id(base_row(2))])
    assert dup.context == {"existing": [{"annotation_id": i, "source": "base"} for i in ids]}
    assert dup.fix is None and dup.options == () and res.deferred == []
    assert dup.got == row and dup.got[12] == "NCBITaxon:9606"   # spec section 7: got is the row as submitted, not the fixed row


def test_duplicate_of_ledger_row_rejected():
    # The existing row is in a second signer's file. With one signer this passes against the bug
    # (the ids would then be equal): column 15 differs between signers, the content key does not.
    row = new_fact(assigned_by="biolean:" + KEY16_B)
    [ann], _ = parse_gaf(["\t".join(row)], BASE.eco_map, BASE.primary_id, BASE.term)
    store = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations + [ann])
    ctx = context(KEY16_A, store=store, sources={ann.id: f"ledger/{KEY16_B}.jsonl:1"})
    res = run(new_fact(), ctx)
    dup = only(res, LC.LEDGER_DUPLICATE, "/fact")
    assert dup.context == {"existing": [{"annotation_id": ann.id, "source": f"ledger/{KEY16_B}.jsonl:1"}]}


def test_same_prop_different_reference_is_a_new_row():
    row = base_row(1)
    row[5], row[14] = "PMID:200", ""
    res = run(row)
    assert res.ok and res.annotation.id not in {annotation_id(base_row(1)), annotation_id(base_row(2))}


def test_fix_that_creates_duplicate_is_reported_first_try():
    # Break: run step 8 on the unfixed row (the obsolete term then matches nothing). An alt id
    # would not do: parse_gaf canonicalizes it to the primary on its own, so step 8 would find
    # the duplicate whether or not the LEDGER_ALT_ID fix was applied.
    row = base_row(1)
    row[4], row[14] = "GO:0000010", BY_A_COL
    res = run(row)
    assert codes(res) == [(LC.OBSOLETE_TERM, "/fact/4"), (LC.LEDGER_DUPLICATE, "/fact")]
    assert res.deferred == []
    # the alt-id form also reports both in one response, but cannot detect the mutation
    row = base_row(1)
    row[4], row[14] = "GO:0000102", BY_A_COL
    assert codes(run(row)) == [(LC.LEDGER_ALT_ID, "/fact/4"), (LC.LEDGER_DUPLICATE, "/fact")]


# ---------- step 9 ----------

def test_positive_fact_against_base_not_row_is_admitted_and_contested():
    not_id = annotation_id(base_row(3))
    res = run(new_fact(db_object_id="P10001", db_object_symbol="G1", db_reference="PMID:300"))
    assert res.ok and res.check["contested_by"] == [not_id]
    store = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations + [res.annotation])
    d = prove(Prop("UniProtKB:P10001", "involved_in", "GO:0000003", TAX, False), store)
    verdict = check(d, store)
    assert verdict["verdict"] == "ACCEPTED" and [c["annotation"] for c in verdict["conflicts"]] == [not_id]


# ---------- combinations ----------

def test_independent_faults_reported_in_one_response():
    # Break: stop at the first failing step.
    res = run(new_fact(db="1x", db_reference="foo:1", date="bad"))
    assert codes(res) == [(LC.LEDGER_BAD_SUBJECT, "/fact/0"), (LC.LEDGER_REFERENCE_REQUIRED, "/fact/5"),
                          (LC.LEDGER_BAD_DATE, "/fact/13")]
    assert res.deferred == [{"step": 8, "waits_on": [1, 6, 14]}]


def test_cross_namespace_replacement_reports_aspect_errors_together():
    # Break: evaluate step 4 against the submitted term (no aspect errors would appear).
    fact = new_fact(go_id="GO:0000011")
    res = run(fact)
    assert codes(res) == [(LC.OBSOLETE_TERM, "/fact/4"), (LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3"),
                          (LC.LEDGER_ASPECT_MISMATCH, "/fact/8")]
    assert only(res, LC.OBSOLETE_TERM, "/fact/4").fix == "GO:0000021"
    assert only(res, LC.LEDGER_ASPECT_MISMATCH, "/fact/8").fix == "F"
    assert only(res, LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3").options == F_QUALS
    assert res.deferred == [{"step": 8, "waits_on": [4]}]
    fixed = apply_fixes(fact, res)
    res2 = run(fixed)
    assert codes(res2) == [(LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3")]
    for option in only(res2, LC.QUALIFIER_ASPECT_MISMATCH, "/fact/3").options:
        assert run(pointer_set({"fact": fixed}, "/fact/3", option)["fact"]).ok


def test_recheck_mode_applies_no_fix_and_requires_assigned_by():
    res = run(new_fact(go_id="GO:0000102"), mode="recheck")
    assert codes(res) == [(LC.LEDGER_ALT_ID, "/fact/4"), (LC.LEDGER_ASSIGNED_BY, "/fact/14")]
    assert res.deferred == [] and res.annotation is not None and res.annotation.term == "GO:0000002"
    assert res.fact == new_fact(go_id="GO:0000102")


def test_recheck_trailing_newline_fails_each_anchored_column_check():
    # Break: end any column regex in `$`, which also matches just before a final "\n". Append
    # cleans the "\n" at step 1a before these checks run, so only recheck (the row as signed)
    # reaches them with it.
    for column, value, code, fix in (
            ("db", "UniProtKB\n", LC.LEDGER_BAD_SUBJECT, None),
            ("db_reference", "DOI:10.1038/s41586-026-00001-0\n", LC.LEDGER_BAD_REFERENCE, None),
            ("db_reference", "PMID:12\n", LC.LEDGER_BAD_REFERENCE, None),
            ("db_reference", "GO_REF:0000001\n", LC.LEDGER_BAD_REFERENCE, None),
            ("taxon", "taxon:9606\n", LC.LEDGER_BAD_TAXON, "taxon:9606"),
            ("date", "20260925\n", LC.LEDGER_BAD_DATE, None),
            ("date", "2026-09-25\n", LC.LEDGER_BAD_DATE, None)):
        res = run(new_fact(**{column: value, "assigned_by": BY_A_COL}), mode="recheck")
        field = f"/fact/{GAF_COLUMNS.index(column)}"
        assert (LC.LEDGER_BAD_CHARACTER, field) in codes(res), (column, value)
        e = only(res, code, field)
        assert (e.got, e.fix) == (value, fix), (column, value)


def test_recheck_of_an_unencodable_row_reports_and_does_not_raise():
    # Break: drop the UTF-8 guard before step 7a. Recheck hashes the row as signed and
    # annotation_id encodes it as UTF-8, so a lone surrogate raised UnicodeEncodeError.
    for i, want in ((0, [(LC.LEDGER_BAD_CHARACTER, "/fact/0"), (LC.LEDGER_BAD_SUBJECT, "/fact/0")]),
                    (16, [(LC.LEDGER_BAD_CHARACTER, "/fact/16")])):
        fact = new_fact(assigned_by=BY_A_COL)
        fact[i] = "\ud800"
        res = run(fact, mode="recheck")
        assert codes(res) == want and res.annotation is None and res.gaf_report is None, i
        assert res.fact == fact and res.check is None, i
    # every column: one LEDGER_BAD_CHARACTER at that column (no second one), nothing hashed
    for i in range(len(GAF_COLUMNS)):
        fact = new_fact(assigned_by=BY_A_COL)
        fact[i] += "\ud800"
        res = run(fact, mode="recheck")
        chars = [e for e in res.errors if e.code == LC.LEDGER_BAD_CHARACTER]
        assert [(e.field, e.got) for e in chars] == [(f"/fact/{i}", "U+D800")], i
        assert res.annotation is None, i


def test_recheck_step_7a_parses_the_row_as_signed():
    # Pins step 7a: other step 1a faults do not skip it. Break: feed parse_gaf the joined row
    # split with str.splitlines(). That changes nothing for "a b", but U+2028 splits the row: form
    # "a", a different annotation id, and a dropped fragment.
    for form in ("a b", "a\u2028b"):
        fact = new_fact(gene_product_form_id=form, assigned_by=BY_A_COL)
        res = run(fact, mode="recheck")
        assert codes(res) == [(LC.LEDGER_BAD_CHARACTER, "/fact/16")], form
        assert res.annotation is not None and res.annotation.id == annotation_id(fact), form
        assert res.annotation.form == form and res.gaf_report["rows"] == 1, form


# ---------- derived ----------

def test_derived_is_admitted_with_axioms_and_conflicts_in_check():
    res = check_derived({"derivation": good_derivation()}, CTX)
    assert res.errors == [] and res.ok
    assert res.conclusion == prop("GO:0000002") and res.derivation["steps"][1]["id"] == "s2"
    assert res.check == {"kernel": CTX.kernel_version, "axioms": [annotation_id(base_row(6))], "conflicts": []}


def test_derived_with_used_sorry_refused():
    d = good_derivation()
    d["steps"].append({"id": "s3", "rule": "sorry", "conclusion": prop("GO:0000002"),
                       "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    d["root"] = "s3"
    res = check_derived({"derivation": d}, CTX)
    assert check(d, CTX.store)["verdict"] == "ACCEPTED"           # the kernel accepts; the ledger does not
    [e] = res.errors
    assert (e.code, e.field, e.fix) == (LC.LEDGER_SORRY_USED, "/derivation/steps/2", None)
    assert e.got["step"] == "s3" and e.got["used"] is True


def test_derived_with_unused_sorry_refused():
    d = good_derivation()
    d["steps"].insert(0, {"id": "s0", "rule": "sorry", "conclusion": prop("GO:0000002"),
                          "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    res = check_derived({"derivation": d}, CTX)
    [e] = res.errors
    assert (e.code, e.field) == (LC.LEDGER_SORRY_UNUSED, "/derivation/steps/0")


def test_derived_conclusion_must_equal_goal():
    res = check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000001")}, CTX)
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_CONCLUSION_MISMATCH, "/conclusion", prop("GO:0000001"), prop("GO:0000002"))
    assert check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000002")}, CTX).ok


def test_derived_stores_elaborated_derivation():
    d = good_derivation()
    d["goal"]["subject"] = "G3"
    d["steps"][0]["conclusion"]["taxon"] = "taxon:9606"
    res = check_derived({"derivation": d}, CTX)
    assert res.ok
    assert res.derivation["goal"]["subject"] == "UniProtKB:P10003"
    assert res.derivation["steps"][0]["conclusion"]["taxon"] == TAX
    assert res.conclusion["subject"] == "UniProtKB:P10003"


def test_derived_rejected_carries_kernel_errors_in_context():
    d = good_derivation()
    d["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    res = check_derived({"derivation": d}, CTX)
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_DERIVATION_REJECTED, "/derivation", None, None)
    kernel = e.context["kernel"]
    assert set(kernel) == {"errors", "elaboration"}
    assert {(x["step"], x["code"]) for x in kernel["errors"]} >= {("s2", "EDGE_NOT_FOUND")}
    assert set(kernel["errors"][0]) == {"step", "code", "message", "expected", "actual", "suggestions"}
    for bad in ("nope", {"derivation": "x"}, {"derivation": d, "extra": 1}, {}):
        res = check_derived(bad, CTX)
        assert res.errors and res.errors[0].code in (LC.LEDGER_BAD_BODY, LC.LEDGER_DERIVATION_REJECTED)


def test_derived_body_key_errors_report_the_value_as_submitted():
    # Spec section 7: got is the whole value at field as submitted, or null if absent. Break: got=None.
    d = good_derivation()
    res = check_derived({"derivation": d, "extra": 1}, CTX)
    assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/extra", 1)]
    res = check_derived({"a/b~c": [1]}, CTX)                     # absent derivation: got null
    assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None),
                                                             (LC.LEDGER_BAD_BODY, "/a~1b~0c", [1])]


# ---------- computed ----------

def good_computed():
    return {"method": "m:bcftools plugin fill-tags",
            "dataset": {"id": "GEO:GSE12345", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x@sha256:ab", "exit_code": 0},
            "conclusion": prop("GO:0000003")}


def test_computed_schema_checked_then_refused():
    errs = check_computed(good_computed(), CTX)
    assert [(e.code, e.field) for e in errs] == [(LC.NOT_YET_DISCHARGEABLE, None)] and errs[0].fix is None
    cases = {
        "/graph_hash": {**good_computed(), "graph_hash": "cd" * 32},
        "/method": {**good_computed(), "method": "m:DESeq2"},
        "/run/exit_code": {**good_computed(), "run": {**good_computed()["run"], "exit_code": True}},
        "/preconditions/0/status": {**good_computed(), "preconditions": [{"id": "x", "status": "maybe", "diagnostic": ""}]},
        "/dataset/id": {**good_computed(), "dataset": {"id": "", "sha256": "x"}},
        "/extra": {**good_computed(), "extra": 1},
        "/run": {**good_computed(), "run": {"command": "x"}},
    }
    for field, body in cases.items():
        errs = check_computed(body, CTX)
        assert errs[0].code == LC.LEDGER_BAD_COMPUTED and errs[0].field == field, (field, [(e.code, e.field) for e in errs])
        assert errs[-1].code == LC.NOT_YET_DISCHARGEABLE
    e = check_computed({**good_computed(), "preconditions": [{"id": "x", "status": "maybe", "diagnostic": ""}]}, CTX)[0]
    assert e.options == ("met", "unknown", "unmet")
    for m in ("m:x\u0085y", "m:x\u0080y", "m:x\ty"):                    # C1 and C0 controls mid-string
        e = check_computed({**good_computed(), "method": m}, CTX)[0]
        assert (e.code, e.field, e.got) == (LC.LEDGER_BAD_COMPUTED, "/method", m)
    errs = check_computed({**good_computed(), "conclusion": prop("GO:0000003", qualifier="enables", taxon="9606")}, CTX)
    assert [(e.code, e.field) for e in errs[:-1]] == [(LC.QUALIFIER_ASPECT_MISMATCH, "/conclusion/qualifier"),
                                                     (LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon")]
    assert errs[0].options == P_QUALS and errs[1].fix == TAX
    errs = check_computed({**good_computed(), "conclusion": prop("GO:0000010")}, CTX)
    assert [(e.code, e.field) for e in errs[:-1]] == [(LC.OBSOLETE_TERM, "/conclusion/term")] and errs[0].fix == "GO:0000002"
    assert [(e.code, e.field) for e in check_computed("x", CTX)] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]


def test_computed_taxon_fix_clears_its_error():
    # Spec section 2 fix rule: a non-null fix, written at its field, removes that error. Break:
    # fix = normalize_taxon(taxon), which for U+00B2 is "NCBITaxon:\u00b2", rejected again.
    # A non-ASCII digit gets no fix (as step 6 of an axiom does), even U+0662, which TAXON_RE's
    # \d would accept.
    for taxon, fix in (("NCBITaxon:\u00b2", None), ("taxon:\u00b2", None), ("\u00b2", None),
                       ("taxon:\u0662", None), ("taxon:abc", None),
                       ("taxon:9606", "NCBITaxon:9606"), ("9606", "NCBITaxon:9606")):
        body = {**good_computed(), "conclusion": prop("GO:0000003", taxon=taxon)}
        errs = check_computed(body, CTX)
        assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon"),
                                                     (LC.NOT_YET_DISCHARGEABLE, None)], taxon
        assert (errs[0].got, errs[0].fix) == (taxon, fix), taxon
        assert errs[0].context == (None if fix else {"form": "NCBITaxon:<digits>"}), taxon
        for e in errs:
            if e.fix is not None:
                again = check_computed(pointer_set(body, e.field, e.fix), CTX)
                assert (e.code, e.field) not in [(x.code, x.field) for x in again], (taxon, e.fix)


def test_computed_conclusion_taxon_is_ascii_digits_with_no_trailing_newline():
    # Break: validate with props.TAXON_RE (^NCBITaxon:\d+$): \d takes U+0662 and $ matches just
    # before a final "\n". The newline case keeps a fix: stripped, its digits are ASCII.
    def result(taxon):
        body = {**good_computed(), "conclusion": prop("GO:0000003", taxon=taxon)}
        return [(e.code, e.field, e.fix) for e in check_computed(body, CTX)]
    assert {t: result(t) for t in ("NCBITaxon:\u0662", "NCBITaxon:9606\n", "NCBITaxon:9606")} == {
        "NCBITaxon:\u0662": [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon", None), (LC.NOT_YET_DISCHARGEABLE, None, None)],
        "NCBITaxon:9606\n": [(LC.LEDGER_BAD_COMPUTED, "/conclusion/taxon", "NCBITaxon:9606"),
                             (LC.NOT_YET_DISCHARGEABLE, None, None)],
        "NCBITaxon:9606": [(LC.NOT_YET_DISCHARGEABLE, None, None)]}


def test_computed_unknown_key_is_reported_at_its_escaped_pointer():
    # RFC 6901, as the derived path does. Break: an unescaped f"/{k}", which points into /a/b~c.
    errs = check_computed({**good_computed(), "a/b~c": [1]}, CTX)
    assert [(e.code, e.field, e.got) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/a~1b~0c", [1]),
                                                       (LC.NOT_YET_DISCHARGEABLE, None, None)]


def test_computed_graph_hash_with_trailing_newline_is_reported():
    # Break: `$` in _GRAPH_HASH_RE (it matches before a final "\n"). character_errors does not
    # flag "\n" outside the fact columns, so this check is the only one that sees it.
    body = {**good_computed(), "graph_hash": "sha256:" + "cd" * 32 + "\n"}
    errs = check_computed(body, CTX)
    assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_COMPUTED, "/graph_hash"), (LC.NOT_YET_DISCHARGEABLE, None)]
    assert errs[0].got == body["graph_hash"]


# ---------- the shape ----------

def test_rejection_shape_is_ledger_not_kernel():
    # Break: pass a kernel Error.to_dict() through anywhere.
    results = [run(new_fact(go_id="GO:0009999")), run(new_fact(qualifier="enables")), run(new_fact(go_id="GO:0000012")),
               run(new_fact(db="1x", db_reference="foo:1", date="bad")), run(new_fact()[:16]),
               run(base_row(1)[:14] + [BY_A_COL, "", ""])]
    errors = [e for r in results for e in r.errors]
    d = good_derivation()
    d["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    errors += check_derived({"derivation": d}, CTX).errors
    errors += check_computed({**good_computed(), "conclusion": prop("GO:0000010", qualifier="enables")}, CTX)
    assert len(errors) >= 11
    for e in errors:
        d = e.to_dict()
        assert set(d) == SEVEN and d["code"] in ALL_LEDGER_CODES
        assert not isinstance(d["fix"], list) and isinstance(d["options"], list)
        assert d["field"] is None or d["field"].startswith("/")


# ---------------------------------------------------------------------------
# the north star (spec section 7 table, section 9): fix is substitutable, options are complete
# ---------------------------------------------------------------------------
import pytest

from methods_graph.biolean.ledger.append import append_entry
from methods_graph.biolean.ledger.errors import LedgerIntegrityError
from methods_graph.biolean.ledger.format import shape_errors
from methods_graph.biolean.ledger.integrity import verify_ledger
from tests.biolean_ledger_fixture import KEY16_A, KEY_A, LFIX, TS, copy_signed, fake_runner, signed_store
from tests.test_biolean_ledger_format import entry as shape_entry

VALUE_FIX_ROWS = {
    LC.LEDGER_ALT_ID: new_fact(go_id="GO:0000102"),
    LC.OBSOLETE_TERM: new_fact(go_id="GO:0000010"),
    LC.LEDGER_ASPECT_MISMATCH: new_fact(aspect="F"),
    LC.LEDGER_ASSIGNED_BY: new_fact(assigned_by="UniProt"),
    LC.LEDGER_BAD_TAXON: new_fact(taxon="9606"),
    LC.LEDGER_BAD_DATE: new_fact(date="2026-09-25"),
    LC.LEDGER_BAD_CHARACTER: new_fact(gene_product_form_id="x\r"),
    LC.LEDGER_BAD_OBJECT_TYPE: new_fact(db_object_type=""),
}
OPTIONS_ROWS = {
    LC.UNKNOWN_QUALIFIER: new_fact(qualifier="bogus", go_id="GO:0000021", aspect="F"),      # an F term: 2 options, not 13
    LC.QUALIFIER_ASPECT_MISMATCH: new_fact(qualifier="enables"),
    LC.OBSOLETE_TERM: new_fact(go_id="GO:0000014"),                                        # several replaced_by
    "OBSOLETE_TERM/consider": new_fact(go_id="GO:0000012"),                                # only consider
    LC.LEDGER_ALT_ID: new_fact(go_id="GO:0000112"),                                        # alt of an obsolete with consider only
    LC.LEDGER_ECO_UNMAPPED: new_fact(evidence_code="XYZ"),
}
NULL_ROWS = {
    LC.UNKNOWN_TERM: new_fact(go_id="GO:0009999"),
    "OBSOLETE_TERM/none": new_fact(go_id="GO:0000013"),
    LC.LEDGER_BAD_SUBJECT: new_fact(db="1x"),
    LC.LEDGER_BAD_REFERENCE: new_fact(db_reference="PMID:0"),
    LC.LEDGER_REFERENCE_REQUIRED: new_fact(db_reference="foo:1"),
    "LEDGER_BAD_TAXON/none": new_fact(taxon="taxon:abc"),
    "LEDGER_BAD_DATE/none": new_fact(date="yesterday"),
    "LEDGER_BAD_OBJECT_TYPE/none": new_fact(db_object_id="P99999", db_object_type=""),
    LC.LEDGER_BAD_COLUMNS: new_fact()[:16],
    "LEDGER_BAD_COLUMNS/unknown-key": {**dict(zip(GAF_COLUMNS, new_fact())), "extra": "x"},   # fact_from_body's path
    LC.LEDGER_DUPLICATE: base_row(1)[:14] + [BY_A_COL, "", ""],
}


def _negated(fact):
    return fact[3].startswith("NOT|")


def test_rejection_fix_is_substitutable(tmp_path):
    """Every code in the section 7 table, from a row that triggers only that code and matches no base row.
    A value fix, written at `field`, gives ACCEPTED on re-check with the submitted polarity; each
    option does the same; the null rows return fix None. Must fail under: LEDGER_BAD_COLUMNS
    returning the names as fix; a column-4 option without NOT|; UNKNOWN_QUALIFIER returning all 13
    for an F term; a non-live id in OBSOLETE_TERM options."""
    for code, fact in VALUE_FIX_ROWS.items():
        res = run(fact)
        [e] = [x for x in res.errors if x.code == code]
        assert len(res.errors) == 1, (code, codes(res))
        assert e.fix is not None and not isinstance(e.fix, list) and e.options == (), code
        fixed = pointer_set({"fact": fact}, e.field, e.fix)["fact"]
        again = run(fixed)
        assert again.ok and _negated(again.fact) == _negated(fact), (code, codes(again))
    # the same, negated: every value fix keeps the NOT| prefix out of its way
    for code, fact in VALUE_FIX_ROWS.items():
        neg = list(fact)
        neg[3] = "NOT|" + neg[3]
        res = run(neg)
        [e] = [x for x in res.errors if x.code == code]
        again = run(pointer_set({"fact": neg}, e.field, e.fix)["fact"])
        assert again.ok and again.annotation.negated is True, code
    for label, fact in OPTIONS_ROWS.items():
        code = label.split("/")[0]
        res = run(fact)
        [e] = [x for x in res.errors if x.code == code]
        assert len(res.errors) == 1 and e.fix is None and e.options, (label, codes(res))
        assert list(e.options) == sorted(set(e.options))
        for option in e.options:
            again = run(pointer_set({"fact": fact}, e.field, option)["fact"])
            assert again.ok and _negated(again.fact) == _negated(fact), (label, option, codes(again))
    for label, body in NULL_ROWS.items():                       # through fact_from_body first, as append_entry does
        code = label.split("/")[0]
        fact, body_errs = fact_from_body(body)
        found = body_errs if fact is None else run(fact).errors
        errs = [x for x in found if x.code == code]
        assert errs and all(x.fix is None and x.options == () for x in errs), (label, [(x.code, x.field) for x in found])
    # the qualifier options with NOT| in play
    res = run(new_fact(qualifier="NOT|enables"))
    [e] = res.errors
    assert all(o.startswith("NOT|") for o in e.options) and len(e.options) == 7
    # shape-level codes
    [e] = [x for x in shape_errors(shape_entry(v=True)) if x.field == "/v"]
    assert e.fix == 1 and shape_errors(pointer_set(shape_entry(v=True), "/v", e.fix)) == []
    [e] = shape_errors(shape_entry(kind="rule"))
    assert e.fix is None and e.options == ("axiom", "computed", "derived")
    # derived: the conclusion fix is the elaborated goal
    res = check_derived({"derivation": good_derivation(), "conclusion": prop("GO:0000001")}, CTX)
    [e] = res.errors
    assert check_derived({"derivation": good_derivation(), "conclusion": e.fix}, CTX).ok
    for d in (dict(good_derivation(), root="s1"),):
        d["steps"].append({"id": "s9", "rule": "sorry", "conclusion": prop("GO:0000002"),
                           "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
        errs = check_derived({"derivation": d}, CTX).errors
        assert errs and all(x.fix is None for x in errs)
    bad = good_derivation()
    bad["steps"][1]["edge"] = ["GO:0000003", "GO:0000001"]
    errs = check_derived({"derivation": bad}, CTX).errors
    assert [x.code for x in errs] == [LC.LEDGER_DERIVATION_REJECTED] and all(x.fix is None for x in errs)
    used = good_derivation()                                    # a sorry on the used chain: null, no options
    used["steps"].append({"id": "s9", "rule": "sorry", "conclusion": prop("GO:0000002"),
                          "provenance": {"method": "m:x", "inputs": ["GEO:1"], "parameters": {}, "claim": "c"}})
    used["root"] = "s9"
    [e] = check_derived({"derivation": used}, CTX).errors
    assert e.code == LC.LEDGER_SORRY_USED and e.fix is None and e.options == ()
    # computed and body: terminal or null
    errs = check_computed(good_computed(), CTX)
    assert [x.code for x in errs] == [LC.NOT_YET_DISCHARGEABLE]
    assert all(x.fix is None or x.field == "/conclusion/taxon" for x in errs)
    [e, _] = check_computed({**good_computed(), "graph_hash": "cd" * 32}, CTX)
    assert (e.code, e.field, e.fix, e.options) == (LC.LEDGER_BAD_COMPUTED, "/graph_hash", None, ())
    _, [e] = fact_from_body("x")
    assert e.fix is None
    # integrity-level codes (exit 2) carry no fix
    ledger, store = signed_store(tmp_path)
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert [(x.code, x.context["file"]) for x in exc.value.errors] == [(LC.LEDGER_MALFORMED, f"ledger/{KEY16_B}.jsonl")]
    assert all(x.fix is None and x.context and "file" in x.context for x in exc.value.errors)
    ledger, store = signed_store(tmp_path / "two")             # the base mismatch: null, its context the digests
    (store / "gaf-eco-mapping.txt").write_text("# changed\nIDA\tDefault\tECO:0000314\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_BASE_MISMATCH and e.fix is None and e.options == () and set(e.context) == {"obo", "gaf", "eco"}
    ledger = copy_signed(tmp_path / "three")                   # a shape/character fault at integrity: null, no options
    (ledger / f"ledger/{KEY16_A}.jsonl").write_bytes((LFIX / "signed-variants" / "surrogate.jsonl").read_bytes())
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(ledger)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.fix is None and e.options == () and e.context["line"] == 1
