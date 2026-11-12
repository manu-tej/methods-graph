"""Base binding, staleness, supersession, duplicate content, contested (spec section 3), over
hand-built ledger states. Task 8 adds load_with_ledger end to end over the signed fixture."""
import pytest

from methods_graph.biolean.gaf import annotation_id, parse_gaf
from methods_graph.biolean.ledger.check import check_axiom
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.integrity import LedgerEntry, LedgerState
from methods_graph.biolean.ledger.load import bind_entries, ledger_report, superseded_by
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import StaticFactStore, load_base
from tests.biolean_ledger_fixture import (
    BASE_FILES, BY_A, BY_B, KEY16_A, KEY16_B, LEDGER_ID, LFIX, RELEASE, TS, base_row, context, ledger_base, new_fact)

BASE = ledger_base()
BASE_STORE = StaticFactStore(BASE.terms, BASE.edges, BASE.annotations)
MADE_UP = {"obo": "0" * 64, "gaf": "1" * 64, "eco": "2" * 64, "release": RELEASE}


def axiom_entry(fact, *, key16=KEY16_A, base=None, prev="", contested_by=()):
    row = list(fact)
    row[14] = row[14] or "biolean:" + key16
    return {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": row,
            "base": base or {**BASE.digests, "release": RELEASE},
            "check": {"kernel": "0.1.0", "annotation_id": annotation_id(row), "contested_by": list(contested_by),
                      "counters": {"new_subject": 0}},
            "prev": prev, "by": BY_A if key16 == KEY16_A else BY_B, "ts": TS, "sig": "x"}


def state(tmp_path, files):
    """files: {key16: [entry dicts]} -> a LedgerState as verify_ledger would build it."""
    return LedgerState(tmp_path, LEDGER_ID, [], "0" * 64,
                       {k: [LedgerEntry(f"ledger/{k}.jsonl", i, e, f"hash{i}") for i, e in enumerate(es, 1)]
                        for k, es in files.items()})


def bind(tmp_path, files, base=BASE, base_store=BASE_STORE):
    st = state(tmp_path, files)
    bound = bind_entries(st, base, base_store)
    full = StaticFactStore(base.terms, base.edges, base.annotations + [b.annotation for b in bound if b.status == "admitted"])
    return bound, ledger_report(st, bound, full), full


def modified_base(tmp_path, *, obo_edit=None, gaf_extra=None):
    d = tmp_path / "base2"
    d.mkdir()
    for name in BASE_FILES.values():
        text = (LFIX / name).read_text(encoding="utf-8")
        if name == "ledger.obo" and obo_edit:
            text = text.replace(*obo_edit)
        if name == "ledger.gaf" and gaf_extra:
            text += "\t".join(gaf_extra) + "\n"
        (d / name).write_text(text, encoding="utf-8")
    base = load_base(d, **BASE_FILES)
    return base, StaticFactStore(base.terms, base.edges, base.annotations)


def test_bind_admits_a_valid_entry_on_its_own_base_and_counts_rechecked_on_another(tmp_path):
    [b], report, full = bind(tmp_path, {KEY16_A: [axiom_entry(new_fact())]})
    assert b.status == "admitted" and b.rechecked_ok is False and b.annotation.assigned_by == "biolean:" + KEY16_A
    assert (report["admitted"], report["rechecked_ok"], report["stale"], report["entries"]) == (1, 0, 0, 1)
    assert full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))[0].id == b.annotation.id
    [b], report, _ = bind(tmp_path, {KEY16_A: [axiom_entry(new_fact(), base=MADE_UP)]})
    assert b.status == "admitted" and b.rechecked_ok is True and report["rechecked_ok"] == 1


def test_hand_signed_entry_skipping_append_is_invalid_on_matching_base(tmp_path):
    # Break: skip the section 2 re-run when the entry's base digests equal the loaded base's.
    e = axiom_entry(new_fact(assigned_by="biolean:" + KEY16_B))          # in A's file
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    [err] = exc.value.errors
    assert err.code == LC.LEDGER_INVALID_ENTRY and err.context["code"] == LC.LEDGER_ASSIGNED_BY
    assert err.context["file"] == f"ledger/{KEY16_A}.jsonl" and err.context["line"] == 1


def test_forged_base_does_not_downgrade_invalid_to_stale(tmp_path):
    # Break: send every failure on a non-matching base to `stale`.
    e = axiom_entry(new_fact(db_reference="PMID:0"), base=MADE_UP)
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    assert exc.value.errors[0].context["code"] == LC.LEDGER_BAD_REFERENCE


def test_forged_base_invalid_payload_names_the_base_independent_code(tmp_path):
    # Break: keep `first = res.errors[0]`: context.code is OBSOLETE_TERM (step 3 runs before step 5),
    # a code that would have meant `stale` on this base, so the payload contradicts the rule it enforces.
    e = axiom_entry(new_fact(go_id="GO:0000010", db_reference="PMID:0"), base=MADE_UP)   # obsolete term + bad reference
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [e]})
    [err] = exc.value.errors
    assert err.code == LC.LEDGER_INVALID_ENTRY and err.context["same_base"] is False
    assert (err.context["code"], err.field) == (LC.LEDGER_BAD_REFERENCE, "/fact/5")


def test_different_base_recheck_counts_stale_and_lists_ids(tmp_path):
    base2, store2 = modified_base(tmp_path, obo_edit=("name: process grandchild\nnamespace: biological_process\n",
                                                      "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    assert store2.term("GO:0000003").obsolete
    e = axiom_entry(new_fact(), base=MADE_UP)                              # admitted elsewhere, obsolete here
    [b], report, full = bind(tmp_path, {KEY16_A: [e]}, base2, store2)
    assert b.status == "stale" and b.code == LC.OBSOLETE_TERM
    assert report["stale"] == 1 and report["admitted"] == 0
    assert report["stale_entries"] == [{"annotation_id": e["check"]["annotation_id"], "code": LC.OBSOLETE_TERM,
                                        "file": f"ledger/{KEY16_A}.jsonl", "line": 1}]
    assert full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False)) == ()
    # the same entry on the base it names is INVALID, not stale
    with pytest.raises(LedgerIntegrityError):
        bind(tmp_path, {KEY16_A: [axiom_entry(new_fact(), base={**base2.digests, "release": RELEASE})]}, base2, store2)


def test_superseded_by_base_is_excluded_and_counted(tmp_path):
    # Mutation: compare annotation ids (they differ in column 15, so nothing would ever supersede).
    fact = new_fact()
    caught_up = list(fact)
    caught_up[9], caught_up[10], caught_up[13], caught_up[14] = "gene two", "G2|GENE2", "20261001", "UniProt"
    base2, store2 = modified_base(tmp_path, gaf_extra=caught_up)
    e = axiom_entry(fact, base=MADE_UP)
    [b], report, full = bind(tmp_path, {KEY16_A: [e]}, base2, store2)
    assert b.status == "superseded_by_base" and b.base_annotation_id == annotation_id(caught_up)
    assert report["superseded_by_base"] == 1 and report["superseded_entries"] == [
        {"annotation_id": e["check"]["annotation_id"], "base_annotation_id": annotation_id(caught_up),
         "file": f"ledger/{KEY16_A}.jsonl", "line": 1}]
    rows = full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))
    assert [r.id for r in rows] == [annotation_id(caught_up)]
    assert superseded_by(b.annotation, store2) == annotation_id(caught_up)
    assert superseded_by(b.annotation, BASE_STORE) is None


def test_superseded_wins_over_stale(tmp_path):
    fact = new_fact()
    caught_up = list(fact)
    caught_up[14] = "UniProt"
    base2, store2 = modified_base(tmp_path, gaf_extra=caught_up,
                                  obo_edit=("name: process grandchild\nnamespace: biological_process\n",
                                            "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    [b], report, _ = bind(tmp_path, {KEY16_A: [axiom_entry(fact, base=MADE_UP)]}, base2, store2)
    assert b.status == "superseded_by_base" and report["stale"] == 0


def test_base_row_differing_only_in_reference_never_supersedes(tmp_path):
    # Fails against any superseded key looser than step 8's (Prop + code, say).
    row = base_row(1)
    row[5], row[14] = "PMID:200", ""
    e = axiom_entry(row, base=MADE_UP)
    [b], report, _ = bind(tmp_path, {KEY16_A: [e]})
    assert b.status == "admitted" and report["superseded_by_base"] == 0


def test_same_fact_from_two_signers_loads_both_and_is_counted(tmp_path):
    ea = axiom_entry(new_fact(), key16=KEY16_A)
    eb = axiom_entry(new_fact(), key16=KEY16_B)
    bound, report, full = bind(tmp_path, {KEY16_A: [ea], KEY16_B: [eb]})
    assert [b.status for b in bound] == ["admitted", "admitted"]
    ids = sorted([ea["check"]["annotation_id"], eb["check"]["annotation_id"]])
    assert report["duplicate_content"] == 1 and report["duplicate_content_entries"][0]["annotation_ids"] == ids
    assert isinstance(report["duplicate_content_entries"][0]["content_key"], list)
    assert len(full.matching(Prop("UniProtKB:P10002", "involved_in", "GO:0000003", "NCBITaxon:9606", False))) == 2


def test_load_report_contested_is_recomputed(tmp_path):
    # Break: read check.contested_by (the earlier entry recorded [] when it was appended).
    pos = axiom_entry(new_fact(), key16=KEY16_A, contested_by=())
    neg = axiom_entry(new_fact(qualifier="NOT|involved_in", db_reference="PMID:77"), key16=KEY16_B)
    bound, report, _ = bind(tmp_path, {KEY16_A: [pos], KEY16_B: [neg]})
    assert report["contested"] == 2
    assert report["contested_entries"] == sorted([pos["check"]["annotation_id"], neg["check"]["annotation_id"]])
    _, report, _ = bind(tmp_path, {KEY16_A: [pos]})
    assert report["contested"] == 0 and report["contested_entries"] == []


def test_ledger_facts_enter_store_through_parse_gaf(tmp_path):
    e = axiom_entry(new_fact(taxon="taxon:9606|taxon:562"))
    st = state(tmp_path, {KEY16_A: [e]})
    bound = bind_entries(st, BASE, BASE_STORE)
    assert bound[0].gaf_report["multi_taxon"] == 1 and bound[0].gaf_report["annotations"] == 1
    assert bound[0].annotation.interacting_taxon == "NCBITaxon:562"


def test_line_separator_in_column_cannot_inject_a_row(tmp_path):
    # Break: check_axiom step 7a joining the row into one text and splitting it
    # (`parse_gaf("\t".join(final).splitlines(), ...)`). str.splitlines splits on U+2028, so a
    # splitting loader sees a different row (form "a", a different annotation id) plus a dropped
    # fragment, and neither matches what was signed.
    fact = new_fact(gene_product_form_id="a\u2028b", assigned_by="biolean:" + KEY16_A)
    anns, rep = parse_gaf(["\t".join(fact)], BASE.eco_map, BASE.primary_id, BASE.term)
    assert len(anns) == 1 and anns[0].form == "a\u2028b" and anns[0].id == annotation_id(fact) and rep["rows"] == 1
    split, rep2 = parse_gaf("\t".join(fact).splitlines(), BASE.eco_map, BASE.primary_id, BASE.term)
    assert [a.form for a in split] == ["a"] and split[0].id != annotation_id(fact) and rep2["bad_column_count"] == 1
    # the loader's own feed, called directly: at bind, step 1a's LEDGER_BAD_CHARACTER is errors[0] and
    # would hide a split, so the recheck result is what pins step 7a
    res = check_axiom(fact, context(KEY16_A), mode="recheck")
    assert [e.code for e in res.errors] == [LC.LEDGER_BAD_CHARACTER]
    assert res.annotation is not None and res.annotation.id == annotation_id(fact)
    assert res.annotation.form == "a\u2028b" and res.gaf_report["rows"] == 1
    with pytest.raises(LedgerIntegrityError) as exc:
        bind(tmp_path, {KEY16_A: [axiom_entry(fact)]})
    assert exc.value.errors[0].context["code"] == LC.LEDGER_BAD_CHARACTER


def test_derived_entries_are_recorded_and_add_nothing_to_the_store(tmp_path):
    d = {"v": 1, "kind": "derived", "ledger": LEDGER_ID,
         "derivation": {"goal": {}, "steps": [], "root": "s1"},
         "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002",
                        "taxon": "NCBITaxon:9606", "negated": False},
         "base": {**BASE.digests, "release": RELEASE}, "check": {"kernel": "0.1.0", "axioms": [], "conflicts": []},
         "prev": "", "by": BY_A, "ts": TS, "sig": "x"}
    [b], report, full = bind(tmp_path, {KEY16_A: [d]})
    assert b.status == "recorded" and b.annotation is None
    assert (report["derived"], report["admitted"], report["entries"]) == (1, 0, 1)
    assert len(full.annotations("UniProtKB:P10003")) == len(BASE_STORE.annotations("UniProtKB:P10003"))


# ---------------------------------------------------------------------------
# end to end over the signed fixture ledger
# ---------------------------------------------------------------------------
from methods_graph.biolean.ledger.load import load_with_ledger, own_base_failures, recheck_derived
from methods_graph.biolean.store import load_store
from methods_graph.biolean.tactics import prove
from tests.biolean_ledger_fixture import KEY16_A as _A, LFIX as _LFIX, signed_store


def test_load_store_with_ledger_admits_the_fixture_entries_and_reports(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, report = load_store(store_dir, gaf="goa_human.gaf", ledger_dir=ledger, use_cache=False)
    block = report["ledger"]
    assert (block["files"], block["entries"], block["axioms"], block["derived"], block["admitted"]) == (2, 5, 4, 1, 4)
    assert (block["stale"], block["superseded_by_base"], block["duplicate_content"], block["rechecked_ok"]) == (0, 0, 0, 0)
    assert block["contested"] == 1 and block["derived_rechecked"] is None
    assert report["ledger_gaf"]["annotations"] == 4 and report["gaf"]["annotations"] == 10
    assert len(store.subjects()) == len(BASE_STORE.subjects()) + 1              # P10006 is new
    assert set(block["heads"]) == {_A, KEY16_B}


def test_same_base_recheck_counts_ok(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    _, report, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    assert report["ledger"]["rechecked_ok"] == 0 and all(not b.rechecked_ok for b in loaded.admitted)


def test_prove_cites_ledger_fact_and_carries_doi(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, _, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    d = prove(Prop("UniProtKB:P10006", "involved_in", "GO:0000001", "NCBITaxon:9606", False), store)
    assert d is not None and [s["rule"] for s in d["steps"]] == ["axiom", "is_a", "is_a"]
    from methods_graph.biolean.kernel import check
    v = check(d, store)
    assert v["verdict"] == "ACCEPTED"
    [ax] = v["axioms"]
    assert ax["annotation"] in loaded.sources and any(r.startswith("DOI:") for r in ax["references"])
    assert store.matching(Prop("UniProtKB:P10006", "involved_in", "GO:0000003", "NCBITaxon:9606", False))[0].assigned_by == "biolean:" + _A


def test_verify_recheck_counts_derived(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    store, _, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    out = recheck_derived(loaded, store)
    assert out == {"derived_rechecked": 1, "derived_failed": 0, "derived_failed_entries": []}
    # Over a store missing the cited row the entry fails on the base it names: listed and counted
    # with same_base true and the kernel's codes, never LEDGER_INVALID_ENTRY (refinement 24).
    # Break: set same_base false (the CLI then exits 0 on it), or raise instead of listing.
    out = recheck_derived(loaded, StaticFactStore(BASE.terms, BASE.edges, []))     # no rows at all
    [f] = out["derived_failed_entries"]
    assert (out["derived_rechecked"], out["derived_failed"], own_base_failures(out)) == (1, 1, 1)
    assert (f["file"], f["line"], f["same_base"]) == (f"ledger/{_A}.jsonl", 4, True)
    assert f["errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED
    assert f["kernel_codes"] and all(isinstance(c, str) for c in f["kernel_codes"])


GRANDCHILD = "name: process grandchild\nnamespace: biological_process\n"


def test_derived_failing_on_another_base_is_counted_and_stays_recorded(tmp_path):
    # GO:0000003, the term the derivation's axiom step cites, is obsolete in this store: another
    # base. The entry loads and stays recorded; --recheck lists the failure with same_base false.
    ledger, store_dir = signed_store(tmp_path)
    obo = store_dir / "go-basic.obo"
    obo.write_text(obo.read_text().replace(GRANDCHILD, GRANDCHILD + "is_obsolete: true\n"))
    store, report, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    [d] = [b for b in loaded.bound if b.entry.entry["kind"] == "derived"]
    assert d.status == "recorded" and report["ledger"]["derived"] == 1
    out = recheck_derived(loaded, store)
    assert (out["derived_rechecked"], out["derived_failed"], own_base_failures(out)) == (1, 1, 0)
    [f] = out["derived_failed_entries"]
    assert (f["file"], f["line"], f["hash"], f["same_base"]) == (f"ledger/{_A}.jsonl", 4, d.entry.hash, False)
    assert f["errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED


def test_no_load_reproves_a_derived_entry(tmp_path, monkeypatch):
    # Refinement 24: a derived entry adds nothing to the store, so a derivation the kernel now
    # rejects on the entry's own base never fails a load (a revoked key's deleted file must not
    # fail every load through another signer's derived entry). No fixture signature exists for a
    # derived entry the kernel rejects, so the elaborator hands the kernel {} for the signed one.
    # Break: re-prove derived entries in load_with_ledger and raise on a failure.
    from methods_graph.biolean.ledger import check as check_mod
    ledger, store_dir = signed_store(tmp_path)
    monkeypatch.setattr(check_mod, "elaborate", lambda derivation, store: ({}, []))
    store, report, loaded = load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
    [d] = [b for b in loaded.bound if b.entry.entry["kind"] == "derived"]
    assert d.status == "recorded" and report["ledger"]["derived_failed"] is None
    [f] = recheck_derived(loaded, store)["derived_failed_entries"]
    assert (f["line"], f["same_base"], f["kernel_codes"]) == (4, True, ["MALFORMED"])


def test_hand_signed_variants_load_as_specified(tmp_path):
    ledger, store_dir = signed_store(tmp_path)
    for name, code in (("assigned-by-b.jsonl", LC.LEDGER_ASSIGNED_BY), ("made-up-base.jsonl", LC.LEDGER_BAD_REFERENCE)):
        (ledger / f"ledger/{_A}.jsonl").write_bytes((_LFIX / "signed-variants" / name).read_bytes())
        with pytest.raises(LedgerIntegrityError) as exc:
            load_with_ledger(store_dir, ledger, gaf="goa_human.gaf", use_cache=False)
        assert exc.value.errors[0].code == LC.LEDGER_INVALID_ENTRY and exc.value.errors[0].context["code"] == code, name
