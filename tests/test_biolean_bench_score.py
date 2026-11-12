"""Per-item scoring reads the kernel's verdict over the item's masked store (spec §6)."""
import json

import pytest

from methods_graph.bench.normalize import normalize_name
from methods_graph.bench.oracle import StaticOracle
from methods_graph.biolean.bench.items import hypothesize_items, population, prove_items
from methods_graph.biolean.bench.score import (
    COMMON_KEYS, DEPTH_BUCKETS, HYPOTHESIZE_KEYS, PROVE_KEYS, UNPARSED, failure_row, score_hypothesize,
    score_prove, score_row, summarize)
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, B, C, D, P1, TAX, axiom, deriv, prop, prop_step, sorry

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)
# score_row attaches no model/manifest; run.py does. The scorer's own key sets:
SCORED_COMMON = COMMON_KEYS - {"model", "items_manifest"}


def _item(track, term, subject=P1):
    pool = PROVE if track == "prove" else HYP
    return next(i for i in pool if i["goal"]["term"] == term and i["goal"]["subject"] == subject)


def _gold_rows():
    return [score_prove(i, json.dumps(i["gold"]), STORE) for i in PROVE]


C_ITEM = _item("prove", C)
GOAL_C = prop(C)


# ---------- prove ----------

def test_gold_derivations_score_as_hits_with_depth_equal_to_gold_depth():
    for item in PROVE:
        row = score_prove(item, json.dumps(item["gold"]), STORE)
        assert (row["accepted"], row["goal_match"], row["goal_rewritten"]) == (True, True, False), item["id"]
        assert row["hit"] is True and row["hit_with_sorry"] is False
        assert row["sorry_count"] == 0 and row["unused_sorries"] == 0
        assert row["depth"] == row["gold_depth"] == 1 and row["error_codes"] == []
        assert row["parsed"] is True and row["raw"] == json.dumps(item["gold"])
        assert set(row) == SCORED_COMMON | PROVE_KEYS


def test_scorer_uses_the_masked_store():
    """The direct row at C is hidden for this item; citing it is AXIOM_NOT_FOUND over the masked
    store though the unmasked store holds two rows there."""
    raw = json.dumps(deriv(GOAL_C, [axiom("s1", C)], "s1"))
    row = score_prove(C_ITEM, raw, STORE)
    assert row["accepted"] is False and row["hit"] is False
    assert row["error_codes"] == ["AXIOM_NOT_FOUND"]
    assert row["goal_match"] is True and row["goal_rewritten"] is False     # right claim, no proof
    assert row["depth"] is None


def test_hit_requires_goal_match_and_zero_used_sorries():
    # (a) an accepted sorry at the goal is hit_with_sorry, never hit
    row = score_prove(C_ITEM, json.dumps(deriv(GOAL_C, [sorry("s1", C)], "s1")), STORE)
    assert row["accepted"] is True and row["goal_match"] is True and row["sorry_count"] == 1
    assert row["hit"] is False and row["hit_with_sorry"] is True
    # (b) an accepted proof of a DIFFERENT (visible) claim: goal_match is judged against the
    # item, not the reply's own goal, so rewriting both consistently is not a hit
    rewritten = deriv(prop(D), [axiom("s1", D)], "s1")
    row = score_prove(C_ITEM, json.dumps(rewritten), STORE)
    assert row["accepted"] is True and row["error_codes"] == []
    assert row["goal_match"] is False and row["goal_rewritten"] is True
    assert row["hit"] is False and row["hit_with_sorry"] is False
    # (c) the stated top-level goal matches the item's claim, but the root step actually
    # concludes a different (visible) term: the kernel itself rejects this as ROOT_MISMATCH,
    # and goal_match must be judged against the root's real conclusion, not the stated goal
    # (which trivially equals the target here) — so goal_match is False and goal_rewritten,
    # which does compare the stated goal to the target, is False.
    mismatched_root = deriv(GOAL_C, [axiom("s1", D)], "s1")
    row = score_prove(C_ITEM, json.dumps(mismatched_root), STORE)
    assert row["error_codes"] == ["ROOT_MISMATCH"] and row["accepted"] is False
    assert row["goal_match"] is False and row["goal_rewritten"] is False
    assert row["hit"] is False and row["hit_with_sorry"] is False


def test_goal_rewritten_is_counted():
    rows = [
        score_prove(C_ITEM, json.dumps(C_ITEM["gold"]), STORE),                             # faithful
        score_prove(C_ITEM, json.dumps(deriv(prop(D), [axiom("s1", D)], "s1")), STORE),      # rewritten
        score_prove(C_ITEM, json.dumps({**C_ITEM["gold"], "goal": "C"}), STORE),             # malformed goal
    ]
    assert [r["goal_rewritten"] for r in rows] == [False, True, True]
    assert rows[2]["error_codes"] == ["MALFORMED"] and rows[2]["goal_match"] is True
    assert summarize(rows)["prove"]["n_goal_rewritten"] == 2


def test_depth_counts_propagation_steps_in_the_used_chain():
    two_hops = deriv(GOAL_C, [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B),
                              prop_step("s3", "is_a", "s2", B, C)], "s3")
    row = score_prove(C_ITEM, json.dumps(two_hops), STORE)
    assert row["hit"] is True and row["depth"] == 2
    with_unused = deriv(GOAL_C, [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B), axiom("s3", D),
                                 prop_step("s4", "is_a", "s2", B, C)], "s4")
    row = score_prove(C_ITEM, json.dumps(with_unused), STORE)
    assert row["hit"] is True and row["depth"] == 2                       # s3 is not on the chain


def test_truncated_reply_is_unparsed_not_malformed():
    """A formatting failure (a cut-off document) must never surface as MALFORMED — that code
    is for a parsed-but-invalid derivation, and a truncated reply never gets that far."""
    row = score_prove(C_ITEM, json.dumps(C_ITEM["gold"])[:-5], STORE)
    assert row["parsed"] is False and row["error_codes"] == [UNPARSED]


def test_unparsed_reply_is_a_miss_with_unparsed_code():
    row = score_prove(C_ITEM, "I do not know this gene.", STORE)
    assert row["parsed"] is False and row["hit"] is False and row["accepted"] is False
    assert row["error_codes"] == [UNPARSED]
    assert row["goal_match"] is None and row["goal_rewritten"] is None
    assert row["sorry_count"] is None and row["depth"] is None
    rows = _gold_rows()[:5] + [row]
    summary = summarize(rows)
    assert summary["n_unparsed"] == 1 and summary["n_checked"] == 5 and summary["n_errors"] == 0
    assert summary["prove"]["n"] == 6 and summary["prove"]["hit_rate"] == 5 / 6   # a miss, in the denominator
    assert summary["prove"]["error_items"] == {UNPARSED: 1}
    assert summary["prove"]["error_items_denominator"] == 6
    assert summary["prove"]["error_occurrences"] == {UNPARSED: 1}


def test_error_histograms_count_items_and_occurrences():
    two_and_one = deriv(GOAL_C, [axiom("s1", "GO:0009999"), axiom("s2", "GO:0009998"), axiom("s3", C)], "s3")
    row = score_prove(C_ITEM, json.dumps(two_and_one), STORE)
    assert row["error_codes"] == ["AXIOM_NOT_FOUND", "UNKNOWN_TERM", "UNKNOWN_TERM"]
    summary = summarize([row])["prove"]
    assert summary["error_items"] == {"AXIOM_NOT_FOUND": 1, "UNKNOWN_TERM": 1}
    assert summary["error_items_denominator"] == 1
    assert summary["error_occurrences"] == {"AXIOM_NOT_FOUND": 1, "UNKNOWN_TERM": 2}
    assert summary["error_occurrences_denominator"] == 3


def test_prove_aggregates_carry_denominators_and_every_depth_bucket():
    summary = summarize(_gold_rows())
    assert summary["n_rows"] == 6 and summary["n_checked"] == 6
    p = summary["prove"]
    assert p["n"] == 6 and p["n_hits"] == 6 and p["hit_rate"] == 1.0
    assert p["hit_with_sorry_rate"] == 0.0 and p["acceptance_rate"] == 1.0 and p["mean_depth"] == 1.0
    assert p["by_evidence_class"] == {"electronic": {"n": 1, "hit_rate": 1.0},
                                      "experimental": {"n": 6, "hit_rate": 1.0}}
    assert tuple(p["by_gold_depth"]) == DEPTH_BUCKETS
    assert p["by_gold_depth"]["1"] == {"n": 6, "hit_rate": 1.0}
    assert p["by_gold_depth"]["4+"] == {"n": 0, "hit_rate": None}       # None, never 0.0
    assert summarize([])["prove"]["hit_rate"] is None and summarize([])["prove"]["mean_depth"] is None


# ---------- hypothesize ----------

def _sorry_reply(item, **provenance):
    prov = {"method": "m:deseq2", "inputs": ["GEO:GSE0"], "parameters": {}, "claim": "computed",
            **provenance}
    goal = item["goal"]
    return json.dumps({"biolean": "0.1", "goal": goal, "root": "s1",
                       "steps": [{"id": "s1", "rule": "sorry", "conclusion": goal, "provenance": prov}]})


B_HYP = _item("hypothesize", B)


def test_format_ok_requires_an_accepted_sorry_root():
    ok = score_hypothesize(B_HYP, _sorry_reply(B_HYP), STORE, None)
    assert ok["format_ok"] is True and ok["goal_match"] is True and ok["inputs_nonempty"] is True
    assert ok["error_codes"] == [] and set(ok) == SCORED_COMMON | HYPOTHESIZE_KEYS
    # An ACCEPTED axiom derivation of a visible claim is not format-compliant for this track.
    visible = json.dumps(deriv(prop(D), [axiom("s1", D)], "s1"))
    row = score_hypothesize(B_HYP, visible, STORE, None)
    assert row["error_codes"] == [] and row["format_ok"] is False
    assert row["goal_match"] is False and row["inputs_nonempty"] is None and row["method"] is None
    # A sorry with empty inputs is SORRY_MALFORMED: rejected, inputs_nonempty False.
    row = score_hypothesize(B_HYP, _sorry_reply(B_HYP, inputs=[]), STORE, None)
    assert row["format_ok"] is False and row["inputs_nonempty"] is False
    assert row["error_codes"] == ["SORRY_MALFORMED"]
    # Unparsed.
    row = score_hypothesize(B_HYP, "no", STORE, None)
    assert row["format_ok"] is False and row["goal_match"] is None and row["error_codes"] == [UNPARSED]
    assert row["inputs_nonempty"] is None and row["method_resolves"] is None


def test_method_resolves_is_none_without_a_graph():
    row = score_hypothesize(B_HYP, _sorry_reply(B_HYP), STORE, None)
    assert row["method"] == "m:deseq2" and row["method_normalized"] is None
    assert row["method_resolves"] is None                                  # None, never False
    summary = summarize([row])["hypothesize"]
    assert summary["method_resolves"] == {"n": 0, "rate": None}
    assert summary["n_method_resolves_none"] == 1 and summary["method_unresolved"] == []


def test_method_is_resolved_by_exact_lookup_not_search():
    oracle = StaticOracle(methods=["m:deseq2", "m:star"], modules={}, operations={}, inputs={}, outputs={})
    resolve = lambda name: normalize_name(name, oracle)
    rows = [score_hypothesize(B_HYP, _sorry_reply(B_HYP, method=m), STORE, resolve)
            for m in ("DESeq2", "deseq", "m:star", "edgeR")]
    assert [r["method_normalized"] for r in rows] == ["m:deseq2", "m:deseq2", "m:star", None]
    assert [r["method_resolves"] for r in rows] == [True, True, True, False]
    assert [r["method"] for r in rows] == ["DESeq2", "deseq", "m:star", "edgeR"]        # verbatim
    summary = summarize(rows)["hypothesize"]
    assert summary["method_resolves"] == {"n": 4, "rate": 0.75}
    assert summary["method_unresolved"] == [["edgeR", 1]]


def test_hypothesize_rows_and_summary_carry_no_hit_keys():
    row = score_row(B_HYP, _sorry_reply(B_HYP), STORE)
    assert not {"hit", "hit_with_sorry", "accepted", "depth", "gold_depth"} & set(row)
    prove_row = score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)
    assert set(prove_row) & set(row) == SCORED_COMMON
    block = summarize([row])["hypothesize"]
    assert not {"hit", "hit_rate", "accepted", "acceptance_rate", "hit_with_sorry_rate"} & set(block)
    assert block["note"].startswith("format compliance only")
    assert block["format_ok"] == {"n": 1, "rate": 1.0} and block["n"] == 1


def test_score_row_dispatches_on_track_and_rejects_unknown_tracks():
    assert score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)["hit"] is True
    with pytest.raises(ValueError, match="unknown track"):
        score_row({**C_ITEM, "track": "guess"}, "{}", STORE)


def test_failure_row_has_exactly_the_tracks_key_set():
    scored = score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)
    failed = failure_row(C_ITEM, error="rate limited", render_error=None)
    assert set(failed) == set(scored)
    assert failed["error"] == "rate limited" and failed["raw"] is None and failed["parsed"] is False
    assert failed["hit"] is None and failed["error_codes"] is None and failed["gold_depth"] == 1
    assert set(failure_row(B_HYP, error="x", render_error=None)) == set(score_row(B_HYP, "{}", STORE))
    assert set(failure_row({"id": "?"}, error="render failed", render_error="KeyError")) \
        >= SCORED_COMMON | PROVE_KEYS | HYPOTHESIZE_KEYS
