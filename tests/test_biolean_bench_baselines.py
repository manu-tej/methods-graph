"""gold (ceiling), random (floor), modal (gene-blind prior), template (hypothesize constant)."""
import json

import pytest

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.baselines import (
    BASELINE_TRACK, baseline_adapter, is_baseline_spec, modal_answer, template_answer)
from methods_graph.biolean.bench.items import build_items, fit_modal, hypothesize_items, population, prove_items
from methods_graph.biolean.bench.render import render_prompt
from methods_graph.biolean.bench.score import score_row, summarize
from methods_graph.biolean.props import Annotation, Edge, Term
from methods_graph.biolean.store import StaticFactStore
from tests.biolean_fixture import RELEASE, mini_store
from tests.test_biolean_kernel import TAX

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)


def _rows(items, adapter, resolve=None):
    return [score_row(item, adapter(render_prompt(item)), STORE, resolve=resolve) for item in items]


def _axiom_terms(rows):
    return [json.loads(r["raw"])["steps"][0]["conclusion"]["term"] for r in rows]


def test_baseline_specs_are_recognized():
    assert all(is_baseline_spec(s) for s in ("gold:", "random:3", "modal:", "template:"))
    assert not is_baseline_spec("claude:opus") and not is_baseline_spec("static:x.json")
    assert BASELINE_TRACK["template"] == "hypothesize"


def test_gold_hits_every_prove_item():
    rows = _rows(PROVE, baseline_adapter("gold:", PROVE, STORE))
    assert all(r["hit"] for r in rows) and summarize(rows)["prove"]["hit_rate"] == 1.0
    assert [r["depth"] for r in rows] == [1] * 6


def test_random_baseline_is_structurally_valid_and_seeded():
    rows = _rows(PROVE, baseline_adapter("random:0", PROVE, STORE))
    for r in rows:
        assert r["parsed"] and (r["hit"] or r["error_codes"] == ["ROOT_MISMATCH"]), r["error_codes"]
    again = _rows(PROVE, baseline_adapter("random:0", PROVE, STORE))
    assert [r["raw"] for r in again] == [r["raw"] for r in rows]
    others = [[r["raw"] for r in _rows(PROVE, baseline_adapter(f"random:{s}", PROVE, STORE))] for s in range(1, 6)]
    assert any(o != [r["raw"] for r in rows] for o in others)
    with pytest.raises(AdapterError, match="integer seed"):
        baseline_adapter("random:x", PROVE, STORE)


def test_modal_with_singleton_keys_emits_the_hidden_axiom_and_misses(tmp_path):
    """Every fixture key has one subject, so leaving it out empties the counter."""
    build_items(STORE, tmp_path, release=RELEASE)
    rows = _rows(PROVE, baseline_adapter("modal:", PROVE, STORE, modal_path=tmp_path / "modal.json"))
    assert [r["hit"] for r in rows] == [False] * 6
    assert all(r["error_codes"] == ["AXIOM_NOT_FOUND"] for r in rows)
    assert _axiom_terms(rows) == [r["goal"]["term"] for r in rows]
    with pytest.raises(AdapterError, match="modal.json"):
        baseline_adapter("modal:", PROVE, STORE, modal_path=None)


def _three_subject_store():
    """T with is_a children C1 < C2. S1 sits at T and C1; S2 and S3 at T and C2."""
    T, C1, C2 = "GO:0000001", "GO:0000002", "GO:0000003"
    terms = [Term(t, t, "biological_process", False, (), (), ()) for t in (T, C1, C2)]
    edges = [Edge(C1, "is_a", T), Edge(C2, "is_a", T)]

    def ann(i, subject, term):
        return Annotation(i, subject, subject[-2:], "involved_in", False, term, term, ("PMID:1",),
                          "IDA", "ECO:0000314", (), "P", "protein", TAX, "", "2020-01-01", "UniProt", "", "")
    anns = [ann("a1", "UniProtKB:S1", T), ann("a2", "UniProtKB:S1", C1),
            ann("a3", "UniProtKB:S2", T), ann("a4", "UniProtKB:S2", C2),
            ann("a5", "UniProtKB:S3", T), ann("a6", "UniProtKB:S3", C2)]
    return StaticFactStore(terms, edges, anns), T, C1, C2


def test_modal_leaves_the_subject_out_and_breaks_ties_by_sorted_term_id():
    store, T, C1, C2 = _three_subject_store()
    items, _ = prove_items(store, population(store)[0])
    t_items = [i for i in items if i["goal"]["term"] == T]
    assert [i["goal"]["subject"] for i in t_items] == ["UniProtKB:S1", "UniProtKB:S2", "UniProtKB:S3"]
    modal = fit_modal(store, items)
    assert modal == {"involved_in": {T: {C1: 1, C2: 2}}}
    answers = [modal_answer(i, store, modal) for i in t_items]
    # S1 left out: {C1: 0, C2: 2} -> C2 (S1 has no row there: a miss).
    # S2 / S3 left out: {C1: 1, C2: 1} -> tie -> C1 by sorted term id (a miss for both).
    assert [a["steps"][0]["conclusion"]["term"] for a in answers] == [C2, C1, C1]
    rows = [score_row(i, json.dumps(a), store) for i, a in zip(t_items, answers)]
    assert [r["hit"] for r in rows] == [False, False, False]
    assert all(r["error_codes"] == ["AXIOM_NOT_FOUND"] for r in rows)
    assert all([s["rule"] for s in a["steps"]] == ["axiom", "is_a"] for a in answers)


def test_template_baseline_scores_one_on_every_hypothesize_rate():
    resolve = lambda name: name if name == "m:deseq2" else None
    rows = _rows(HYP, baseline_adapter("template:", HYP, STORE), resolve=resolve)
    block = summarize(rows)["hypothesize"]
    assert block["n"] == 13
    for key in ("format_ok", "goal_match", "inputs_nonempty", "method_resolves"):
        assert block[key] == {"n": 13, "rate": 1.0}, key
    answer = template_answer(HYP[0])
    assert answer["steps"][0]["provenance"]["method"] == "m:deseq2"
    assert answer["steps"][0]["provenance"]["inputs"] == ["GEO:GSE0"]
    assert HYP[0]["symbol"] in answer["steps"][0]["provenance"]["claim"]


def test_baseline_on_the_wrong_track_is_a_usage_error():
    with pytest.raises(AdapterError, match="--track prove"):
        baseline_adapter("gold:", HYP, STORE)
    with pytest.raises(AdapterError, match="--track hypothesize"):
        baseline_adapter("template:", PROVE, STORE)
    with pytest.raises(AdapterError, match="--track prove"):
        baseline_adapter("random:1", PROVE + HYP, STORE)
    with pytest.raises(AdapterError, match="not a baseline"):
        baseline_adapter("static:x", PROVE, STORE)
    adapter = baseline_adapter("gold:", PROVE, STORE)
    with pytest.raises(AdapterError, match="no answer"):
        adapter("a prompt no item rendered")
