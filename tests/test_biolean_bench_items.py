"""Population, hiders, item construction, sampling, live cut, modal fit (spec §6)."""
import json

import pytest

from methods_graph.biolean import store as store_mod
from methods_graph.biolean.bench.items import (
    BuildError, DROP_REASONS, apply_since, below, build_items, fit_modal, hide_exact, hide_subtree,
    hypothesize_items, load_items, population, prove_items, read_release, sample, visible_descendants)
from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Annotation, Edge, Prop, Term
from methods_graph.biolean.store import MaskedFactStore, StaticFactStore
from methods_graph.biolean.tactics import prove
from tests.biolean_fixture import RELEASE, copy_store, mini_store, reversed_store
from tests.test_biolean_kernel import (
    A, B, C, D, MF1, MF2, P1, P2, P3, P5, P7, R, T, TAX, X, Y)

STORE = mini_store()
C1, C2, T0, CC2 = "GO:0000080", "GO:0000090", "GO:0000070", "GO:0000310"
P4, P6, P8, P9 = "UniProtKB:P00004", "UniProtKB:P00006", "UniProtKB:P00008", "UniProtKB:P00009"

EXPECTED_TRIPLES = sorted([
    (P1, "involved_in", A, TAX), (P1, "involved_in", B, TAX), (P1, "involved_in", C, TAX),
    (P1, "involved_in", D, TAX), (P2, "involved_in", X, TAX), (P2, "involved_in", Y, TAX),
    (P2, "involved_in", T, TAX), (P3, "enables", MF1, TAX), (P3, "enables", MF2, TAX),
    (P4, "located_in", CC2, TAX), (P6, "involved_in", C, TAX), (P7, "involved_in", R, TAX),
    (P7, "involved_in", C2, TAX),
])


def _p(term, subject=P1, qualifier="involved_in"):
    return Prop(subject, qualifier, term, TAX, False)


def _ann(i, subject, qualifier, term, *, code="IDA", negated=False, object_type="protein",
         date="2020-01-01"):
    return Annotation(i, subject, subject.split(":")[1], qualifier, negated, term, term, ("PMID:1",),
                      code, "ECO:0000314", (), "P", object_type, TAX, "", date, "UniProt", "", "")


def _term(i, ns="biological_process", obsolete=False):
    return Term(i, i, ns, obsolete, (), (), ())


# ---------- population ----------

def test_population_over_the_fixture_is_thirteen_triples_with_every_drop_counted():
    triples, report = population(STORE)
    assert triples == EXPECTED_TRIPLES
    assert report["rows"] == 24 and report["eligible_rows"] == 15 and report["triples"] == 13
    assert report["n_subjects"] == 9
    assert set(report["dropped"]) == set(DROP_REASONS)
    assert report["dropped"] == {
        "negated": 2, "qualifier_out_of_scope": 1, "evidence_class": 4, "object_type": 0,
        "term_not_in_ontology": 1, "term_alt_id": 0, "term_obsolete": 1}
    assert report["rows"] == report["eligible_rows"] + sum(report["dropped"].values())


def test_population_filters_count_the_first_failure_in_order():
    """A row failing several filters is counted once, under the first in spec order:
    negated, qualifier, evidence class, object type, term."""
    store = StaticFactStore([_term("GO:1")], [], [
        _ann("a1", "UniProtKB:S", "involved_in", "GO:9", code="IEA", negated=True),   # negated+IEA+unknown
        _ann("a2", "UniProtKB:S", "colocalizes_with", "GO:9", code="IEA"),           # qualifier+IEA+unknown
        _ann("a3", "UniProtKB:S", "involved_in", "GO:9", code="IEA"),                # IEA+unknown
        _ann("a4", "UniProtKB:S", "involved_in", "GO:9", object_type="gene"),         # object_type+unknown
        _ann("a5", "UniProtKB:S", "involved_in", "GO:9"),                            # unknown only
        _ann("a6", "UniProtKB:S", "involved_in", "GO:1"),                            # eligible
    ])
    triples, report = population(store)
    assert triples == [("UniProtKB:S", "involved_in", "GO:1", TAX)]
    assert report["dropped"] == {
        "negated": 1, "qualifier_out_of_scope": 1, "evidence_class": 1, "object_type": 1,
        "term_not_in_ontology": 1, "term_alt_id": 0, "term_obsolete": 0}


def test_population_excludes_obsolete_terms():
    """P00005's IDA row sits at the obsolete GO:0000110; it is counted, not eligible."""
    triples, report = population(STORE)
    assert (P5, "involved_in", "GO:0000110", TAX) not in triples
    assert report["dropped"]["term_obsolete"] == 1
    # The alt_id counter exists even though the loader canonicalizes alt ids before the
    # store is built (a StaticFactStore cannot hold one), so it is 0 by construction here.
    assert report["dropped"]["term_alt_id"] == 0


def test_population_can_be_restricted_to_named_subjects_and_says_so():
    triples, report = population(STORE, subjects=[P2, P1])
    assert {t[0] for t in triples} == {P1, P2} and report["n_subjects"] == 2
    assert report["rows"] == 12


def test_population_is_independent_of_row_order():
    assert population(reversed_store())[0] == population(STORE)[0]


# ---------- hiders ----------

def test_prove_item_hides_only_the_exact_rows():
    hidden = hide_exact(STORE, _p(C))
    codes = sorted(a.code for a in STORE.annotations(P1) if a.id in hidden)
    assert codes == ["IDA", "IEA"]                                  # every evidence class at the tuple
    masked = MaskedFactStore(STORE, hidden)
    remaining = {(a.qualifier, a.term, a.negated) for a in masked.annotations(P1)}
    assert ("acts_upstream_of_or_within", C, False) in remaining    # other qualifier stays
    assert ("involved_in", C, True) in remaining                    # the NOT row stays
    assert ("involved_in", B, False) in remaining                   # the descendant stays


def test_hypothesize_subtree_is_closure_of_the_union():
    """C2 is_a C1 part_of T0: is_a-closure(T0) ∪ part_of-closure(T0) is {C1}; the closure of
    the union is {C1, C2}. P00007's rows at C2 must be hidden for goal T0."""
    assert below(T0, STORE) == frozenset({T0, C1, C2})
    hidden = hide_subtree(STORE, _p(T0, subject=P7))
    hidden_terms = sorted(a.term for a in STORE.annotations(P7) if a.id in hidden)
    assert hidden_terms == [C2, C2]                                 # the IDA row and the XYZ row


def test_hypothesize_never_hides_not_rows():
    hidden = hide_subtree(STORE, _p(T, subject=P2))
    rows = [a for a in STORE.annotations(P2) if a.id in hidden]
    assert sorted(a.term for a in rows) == [X, Y, T]
    assert all(not a.negated for a in rows)
    not_row = next(a for a in STORE.annotations(P2) if a.negated)
    assert not_row.id not in hidden
    assert hide_subtree(STORE, _p(C)) == hide_subtree(STORE, _p(C), cache={})   # the cache is transparent


def test_subtree_stops_at_namespace_and_non_propagating_edges():
    hidden = hide_subtree(STORE, _p(C))
    assert sorted({a.term for a in STORE.annotations(P1) if a.id in hidden}) == [B, C, D, A]
    assert not any(a.id in hidden for a in STORE.annotations(P3))    # MF2 part_of C is cross-namespace
    assert not any(a.id in hidden for a in STORE.annotations(P7))    # R regulates C


def test_visible_descendants_are_the_subjects_visible_rows_strictly_below_the_term():
    masked = MaskedFactStore(STORE, hide_exact(STORE, _p(C)))
    assert visible_descendants(masked, _p(C)) == [B, D, A]          # sorted; C itself excluded
    assert visible_descendants(STORE, _p(C)) == [B, D, A]           # the direct row is not a descendant
    assert visible_descendants(STORE, _p(T, subject=P2)) == [X, Y]
    assert visible_descendants(STORE, _p(X, subject=P2)) == []
    # A NOT row below the term is never a visible descendant.
    assert visible_descendants(STORE, _p(Y, subject=P2)) == [X]


# ---------- release ----------

def test_read_release_comes_from_the_file_headers(tmp_path):
    store_dir = copy_store(tmp_path)
    assert read_release(store_dir, gaf="goa_human.gaf") == RELEASE
    obo = store_dir / "go-basic.obo"
    obo.write_text(obo.read_text().replace("releases/2026-01-01", "releases/2026-02-02"))
    assert read_release(store_dir, gaf="goa_human.gaf")["go_basic_data_version"] == "releases/2026-02-02"


PROVE_IDS = [f"prove/{P1}/involved_in/{B}", f"prove/{P1}/involved_in/{C}",
             f"prove/{P1}/involved_in/{D}", f"prove/{P2}/involved_in/{Y}",
             f"prove/{P2}/involved_in/{T}", f"prove/{P3}/enables/{MF1}"]


def _prove_items(store=STORE):
    return prove_items(store, population(store)[0])


# ---------- prove items ----------

def test_prove_items_are_the_six_rederivable_triples_with_accepted_gold():
    items, report = _prove_items()
    assert report == {"eligible": 6, "not_rederivable": 7}
    assert [i["id"] for i in items] == PROVE_IDS
    for item in items:
        masked = MaskedFactStore(STORE, frozenset(item["hidden"]))
        assert check(item["gold"], masked)["errors"] == [], item["id"]
        assert item["gold"]["goal"] == item["goal"]
        assert item["gold_depth"] == len(item["gold"]["steps"]) - 1 == 1
        assert item["track"] == "prove" and item["hidden"] == sorted(item["hidden"])
    c_item = items[1]
    assert c_item["symbol"] == "GA" and c_item["term_name"] == "C"
    assert c_item["hidden_dates"] == ["2019-01-01", "2026-03-01"]
    assert c_item["cut_date"] == "2019-01-01"
    assert c_item["hidden_classes"] == ["electronic", "experimental"]
    assert [s["rule"] for s in c_item["gold"]["steps"]] == ["axiom", "is_a"]
    assert c_item["gold"]["steps"][0]["conclusion"]["term"] == B        # sorted tie-break, not D or A


def test_not_rederivable_triples_are_counted_not_dropped_silently():
    triples, _ = population(STORE)
    items, report = _prove_items()
    assert report["eligible"] + report["not_rederivable"] == len(triples) == 13
    assert f"prove/{P1}/involved_in/{A}" not in {i["id"] for i in items}     # A is a leaf
    assert f"prove/{P3}/enables/{MF2}" not in {i["id"] for i in items}       # only the parent remains


# ---------- hypothesize items ----------

def test_hypothesize_items_hide_the_subtree_and_every_fixture_triple_is_statable():
    triples, _ = population(STORE)
    items, report = hypothesize_items(STORE, triples)
    assert report == {"eligible": 13, "goal_not_statable": {}, "goal_not_statable_total": 0}
    assert len(items) == 13 and all("gold" not in i and "gold_depth" not in i for i in items)
    t_item = next(i for i in items if i["id"] == f"hypothesize/{P2}/involved_in/{T}")
    assert sorted(a.term for a in STORE.annotations(P2) if a.id in t_item["hidden"]) == [X, Y, T]
    assert len(t_item["hidden_dates"]) == 3
    for item in items:
        masked = MaskedFactStore(STORE, frozenset(item["hidden"]))
        assert prove(Prop.from_dict(item["goal"]), masked) is None, item["id"]


def test_hypothesize_still_derivable_raises_build_error():
    """The hider is injectable and a wrong one is a defect, not a dropped item."""
    triples, _ = population(STORE)
    with pytest.raises(BuildError) as ex:
        hypothesize_items(STORE, triples, hide=hide_exact)
    assert ex.value.triple == (P1, "involved_in", B, TAX)                   # the first rederivable
    assert [s["rule"] for s in ex.value.derivation["steps"]] == ["axiom", "is_a"]
    assert "still derivable" in str(ex.value)


def test_hypothesize_goal_not_statable_is_counted_with_its_code():
    """A release-skewed row: located_in (C aspect) at a biological_process term passes the
    population filters but no sorry can state it — the kernel says QUALIFIER_ASPECT_MISMATCH."""
    store = StaticFactStore([_term("GO:1")], [], [
        _ann("a1", "UniProtKB:S", "located_in", "GO:1"),
        _ann("a2", "UniProtKB:S", "involved_in", "GO:1"),
    ])
    triples, _ = population(store)
    assert len(triples) == 2
    items, report = hypothesize_items(store, triples)
    assert report == {"eligible": 1, "goal_not_statable": {"QUALIFIER_ASPECT_MISMATCH": 1},
                      "goal_not_statable_total": 1}
    assert [i["goal"]["qualifier"] for i in items] == ["involved_in"]


# ---------- live cut, sampling, modal fit ----------

def test_live_cut_uses_min_hidden_date():
    items, _ = _prove_items()
    kept, excluded = apply_since(items, "2020-01-01")
    assert excluded == 1 and f"prove/{P1}/involved_in/{C}" not in {i["id"] for i in kept}
    assert apply_since(items, "2019-01-01") == (items, 0)
    assert apply_since(items, None) == (items, 0)
    # Under a max-or-any rule the C item (IEA row dated 2026-03-01) would survive this cut.
    assert apply_since(items, "2026-03-01") == ([], 6)


def test_sampling_is_seeded_and_sorted_first():
    forward, _ = _prove_items(STORE)
    backward, _ = _prove_items(reversed_store())
    assert forward == backward                                    # content ids, sorted collections
    s1 = [i["id"] for i in sample(forward, 3, seed=1)]
    assert s1 == [i["id"] for i in sample(backward, 3, seed=1)]
    assert s1 == [i["id"] for i in sample(list(reversed(forward)), 3, seed=1)]
    assert len(s1) == 3 and s1 == sorted(s1) and set(s1) < set(PROVE_IDS)
    assert any([i["id"] for i in sample(forward, 3, seed=s)] != s1 for s in range(2, 8))
    assert sample(forward, None, 0) == forward and sample(forward, 10, 0) == forward


def test_modal_is_fit_on_the_full_eligible_set_before_sampling(tmp_path):
    items, _ = _prove_items()
    full = fit_modal(STORE, items)
    assert full == {"enables": {MF1: {MF2: 1}},
                    "involved_in": {B: {A: 1}, C: {B: 1, D: 1, A: 1}, D: {A: 1},
                                    Y: {X: 1}, T: {X: 1, Y: 1}}}
    build_items(STORE, tmp_path, release=RELEASE, per_track=1, seed=0)
    assert json.loads((tmp_path / "modal.json").read_text()) == full   # not the 1-item sample's fit


# ---------- build and load ----------

def test_build_writes_items_manifest_and_modal_and_is_byte_reproducible(tmp_path):
    manifest = build_items(STORE, tmp_path / "b", release=RELEASE, per_track=3, seed=0)
    items, loaded = load_items(tmp_path / "b")
    assert loaded == manifest
    assert [i["track"] for i in items] == ["hypothesize"] * 3 + ["prove"] * 3
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)
    assert manifest["prove"] == {"eligible": 6, "not_rederivable": 7, "excluded_by_since": 0, "sampled": 3}
    assert manifest["hypothesize"] == {"eligible": 13, "goal_not_statable": {}, "goal_not_statable_total": 0,
                                       "excluded_by_since": 0, "sampled": 3}
    assert manifest["population"]["triples"] == 13 and manifest["population"]["n_subjects"] == 9
    assert manifest["hypothesize_gold"] is None and manifest["since"] is None
    assert manifest["release"] == RELEASE and manifest["seed"] == 0 and manifest["per_track"] == 3
    for name in ("manifest.json", "modal.json", "items/prove.json", "items/hypothesize.json"):
        text = (tmp_path / "b" / name).read_text()
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    build_items(STORE, tmp_path / "c", release=RELEASE, per_track=3, seed=0)
    for name in ("manifest.json", "modal.json", "items/prove.json", "items/hypothesize.json"):
        assert (tmp_path / "b" / name).read_bytes() == (tmp_path / "c" / name).read_bytes()


def test_build_with_since_records_the_cut_on_both_tracks(tmp_path):
    manifest = build_items(STORE, tmp_path, release=RELEASE, since="2020-01-01")
    assert manifest["since"] == "2020-01-01"
    assert manifest["prove"]["excluded_by_since"] == 1 and manifest["prove"]["sampled"] == 5
    assert manifest["hypothesize"]["excluded_by_since"] == 1 and manifest["hypothesize"]["sampled"] == 12
    items, _ = load_items(tmp_path)
    assert all(i["cut_date"] >= "2020-01-01" for i in items)
    # The modal prior is fit on every prove-eligible item BEFORE the live cut, not on the
    # since-filtered survivors: it must match the full-population fit regardless of --since.
    assert json.loads((tmp_path / "modal.json").read_text()) == fit_modal(STORE, _prove_items()[0])


def test_build_restricted_to_subjects_reports_the_restriction(tmp_path):
    manifest = build_items(STORE, tmp_path, release=RELEASE, subjects=[P2])
    assert manifest["population"]["n_subjects"] == 1
    assert manifest["prove"]["eligible"] == 2 and manifest["hypothesize"]["eligible"] == 3


def test_load_items_refuses_a_missing_or_empty_item_set(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_items(tmp_path / "nope")
    (tmp_path / "items").mkdir()
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="no benchmark items"):
        load_items(tmp_path)


def test_bench_items_imports_release_identity_from_store_not_fetch():
    import inspect
    from methods_graph.biolean.bench import items as items_mod
    src = inspect.getsource(items_mod)
    assert "methods_graph.fetch" not in src
    assert items_mod.read_release is store_mod.read_release
