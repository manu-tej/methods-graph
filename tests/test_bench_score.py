import pytest

from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.score import (
    equivalence_pairs, match_steps, same_class, score_selection, score_sequencing)


def _oracle():
    """Mirrors the real graph: star/hisat2 share op AND input Data; bwa shares only op."""
    return StaticOracle(
        methods=["m:star", "m:hisat2", "m:bwa", "m:bowtie2", "m:salmon", "m:deseq2",
                 "m:fastqc"],
        operations={
            "m:star": ["op:operation_0292"],
            "m:hisat2": ["op:operation_0292"],
            "m:bwa": ["op:operation_0292", "op:operation_3198"],
            "m:bowtie2": ["op:operation_3198"],
            "m:salmon": ["op:operation_3800"],
            "m:deseq2": ["op:operation_3223"],
            "m:fastqc": ["op:operation_3218"],
        },
        inputs={
            "m:star": ["data:data_1234", "data:data_2977"],
            "m:hisat2": ["data:data_1234", "data:data_2977"],
            "m:bwa": ["data:data_2044", "data:data_3210"],
            "m:salmon": ["data:data_1234"],
            "m:deseq2": ["data:data_3917"],
            "m:fastqc": ["data:data_1234"],
        },
    )


def test_hisat2_is_credited_for_star():
    assert same_class("m:star", "m:hisat2", _oracle()) is True


def test_bwa_is_not_credited_for_spliced_alignment():
    oracle = _oracle()
    # The two DO share an operation — this is what an operation-only class would credit.
    assert oracle.operations("m:star") & oracle.operations("m:bwa")
    # Adding the input-data requirement is what rejects it.
    assert same_class("m:star", "m:bwa", oracle) is False


def test_a_method_with_no_curated_input_data_still_matches_itself():
    assert same_class("m:bowtie2", "m:bowtie2", _oracle()) is True


def test_a_method_with_no_curated_input_data_matches_nothing_else():
    assert same_class("m:bowtie2", "m:bwa", _oracle()) is False


def test_unrelated_tools_do_not_match():
    assert same_class("m:deseq2", "m:fastqc", _oracle()) is False


def test_perfect_answer_scores_one():
    gold = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    result = score_selection(gold, list(gold), _oracle())
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_equivalent_substitution_scores_one():
    result = score_selection(["m:star"], ["m:hisat2"], _oracle())
    assert result["f1"] == 1.0
    assert result["matched"] == {"m:star": "m:hisat2"}


def test_one_predicted_tool_cannot_satisfy_two_gold_steps():
    # Matching is one-to-one: hisat2 covers star, but nothing covers salmon.
    result = score_selection(["m:star", "m:salmon"], ["m:hisat2"], _oracle())
    assert result["recall"] == 0.5
    assert result["precision"] == 1.0


def test_matching_is_maximum_not_greedy():
    # Asymmetric case where greedy would fail. Gold_A can match both X and Y; Gold_B can
    # match only X. If greedy assigns A→X first, B has no match (1 total). Maximum
    # matching assigns A→Y, B→X (2 total) via augmenting path.
    oracle = StaticOracle(
        methods=[
            "m:star", "m:hisat2", "m:bwa", "m:bowtie2", "m:salmon", "m:deseq2",
            "m:fastqc",
            "m:greedy_A", "m:greedy_B", "m:greedy_X", "m:greedy_Y",
        ],
        operations={
            "m:star": ["op:operation_0292"],
            "m:hisat2": ["op:operation_0292"],
            "m:bwa": ["op:operation_0292", "op:operation_3198"],
            "m:bowtie2": ["op:operation_3198"],
            "m:salmon": ["op:operation_3800"],
            "m:deseq2": ["op:operation_3223"],
            "m:fastqc": ["op:operation_3218"],
            "m:greedy_A": ["op:operation_greedy"],
            "m:greedy_B": ["op:operation_greedy"],
            "m:greedy_X": ["op:operation_greedy"],
            "m:greedy_Y": ["op:operation_greedy"],
        },
        inputs={
            "m:star": ["data:data_1234", "data:data_2977"],
            "m:hisat2": ["data:data_1234", "data:data_2977"],
            "m:bwa": ["data:data_2044", "data:data_3210"],
            "m:salmon": ["data:data_1234"],
            "m:deseq2": ["data:data_3917"],
            "m:fastqc": ["data:data_1234"],
            "m:greedy_A": ["data:data_greedy_common", "data:data_greedy_extra"],
            "m:greedy_B": ["data:data_greedy_common"],
            "m:greedy_X": ["data:data_greedy_common", "data:data_greedy_extra"],
            "m:greedy_Y": ["data:data_greedy_extra"],
        },
    )
    gold = ["m:greedy_A", "m:greedy_B"]
    pred = ["m:greedy_X", "m:greedy_Y"]
    assert len(match_steps(gold, pred, oracle)) == 2


def test_extra_predictions_cost_precision_not_recall():
    result = score_selection(["m:star"], ["m:star", "m:deseq2", "m:fastqc"], _oracle())
    assert result["recall"] == 1.0
    assert result["precision"] == 1.0 / 3


def test_a_repeated_step_does_not_cost_score():
    result = score_selection(["m:star", "m:star"], ["m:star", "m:star"], _oracle())
    assert result["f1"] == 1.0


def test_empty_prediction_scores_zero_without_dividing_by_zero():
    result = score_selection(["m:star"], [], _oracle())
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_correct_order_scores_one():
    gold_edges = [("m:fastqc", "m:star"), ("m:star", "m:salmon"),
                  ("m:salmon", "m:deseq2")]
    pred = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    matched = match_steps(["m:fastqc", "m:star", "m:salmon", "m:deseq2"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_reversed_order_scores_zero():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:salmon", "m:star"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 0.0


def test_parallel_branches_are_not_penalized():
    # fastqc and star are both required before salmon, but nothing orders them relative
    # to each other. Either interleaving must score 1.0.
    gold_edges = [("m:fastqc", "m:salmon"), ("m:star", "m:salmon")]
    gold = ["m:fastqc", "m:star", "m:salmon"]
    for pred in (["m:fastqc", "m:star", "m:salmon"], ["m:star", "m:fastqc", "m:salmon"]):
        matched = match_steps(gold, pred, _oracle())
        assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_order_metric_is_independent_of_naming_errors():
    # Two of four steps are wrong; the ordering of the two correct ones is perfect.
    gold_edges = [("m:fastqc", "m:star"), ("m:star", "m:salmon"),
                  ("m:salmon", "m:deseq2")]
    gold = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    pred = ["m:star", "m:salmon"]
    matched = match_steps(gold, pred, _oracle())
    result = score_sequencing(gold_edges, matched, pred)
    assert result["n_scorable"] == 1        # only star->salmon has both ends matched
    assert result["score"] == 1.0


def test_equivalent_substitution_keeps_its_position():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:hisat2", "m:salmon"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_no_scorable_edges_is_none_not_zero():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:deseq2"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    result = score_sequencing(gold_edges, matched, pred)
    assert result["score"] is None
    assert result["n_scorable"] == 0


def test_one_prediction_covering_both_ends_of_an_edge_is_not_credited():
    # Nothing can precede itself; a single predicted tool matched to both endpoints
    # supplies no ordering evidence.
    gold_edges = [("m:star", "m:hisat2")]
    matched = {"m:star": "m:star", "m:hisat2": "m:star"}
    result = score_sequencing(gold_edges, matched, ["m:star"])
    assert result["score"] == 0.0


from methods_graph.bench.score import score_validity


def _io_oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:salmon", "m:deseq2", "m:bowtie2"],
        outputs={
            "m:fastqc": ["data:data_2955"],
            "m:star": ["data:data_0863"],       # Sequence alignment
            "m:salmon": ["data:data_3917"],     # Count matrix
        },
        inputs={
            "m:star": ["data:data_1234"],
            "m:salmon": ["data:data_0863"],     # consumes an alignment
            "m:deseq2": ["data:data_3917"],     # consumes a count matrix
        },
    )


def test_every_input_supplied_by_an_earlier_step_scores_one():
    result = score_validity(["m:star", "m:salmon", "m:deseq2"], _io_oracle())
    assert result["score"] == 1.0
    assert result["n_valid"] == 2      # salmon and deseq2; star's reads are a pipeline input
    assert result["n_broken"] == 0


def test_consuming_before_producing_is_broken():
    # deseq2 needs the count matrix salmon emits, and salmon runs AFTER it. salmon does
    # not itself consume a count matrix, so this is net production — a real ordering error.
    result = score_validity(["m:deseq2", "m:salmon"], _io_oracle())
    assert result["n_broken"] == 1
    assert result["score"] == 0.0
    assert result["pairs"][0] == {"step": "m:deseq2", "result": "BROKEN",
                                  "shared": ["data:data_3917"]}


def test_an_input_no_step_supplies_is_unknown_not_broken():
    # Nothing in this answer produces deseq2's count matrix. That is indistinguishable
    # from a pipeline input, so it is unverifiable — not evidence of a wrong order.
    result = score_validity(["m:star", "m:deseq2"], _io_oracle())
    assert result["n_broken"] == 0
    assert result["n_unknown"] == 2
    assert result["score"] is None


def test_unknown_is_never_counted_as_valid():
    # bowtie2 has no curated I/O at all — it can never be scored either way.
    result = score_validity(["m:star", "m:bowtie2", "m:deseq2"], _io_oracle())
    assert result["n_unknown"] == 3
    assert result["n_valid"] == 0
    assert result["score"] is None


def test_a_step_with_no_curated_io_is_excluded_from_the_denominator():
    result = score_validity(["m:star", "m:salmon", "m:bowtie2"], _io_oracle())
    assert result["n_steps"] == 3
    assert result["n_valid"] == 1                      # salmon consumes star's alignment
    assert result["n_unknown"] == 2                    # star's reads, and bowtie2 entirely
    assert result["coverage"] == 1 / 3
    assert result["score"] == 1.0                      # the one checkable step was valid
    assert [p["result"] for p in result["pairs"]] == ["UNKNOWN", "VALID", "UNKNOWN"]


def test_empty_answer_has_no_steps_to_classify():
    result = score_validity([], _io_oracle())
    assert result["n_steps"] == 0
    assert result["score"] is None
    assert result["coverage"] is None


def _real_chain():
    """nf-core/rnaseq's default path, projected into method space."""
    return ["m:fastqc", "m:trimgalore", "m:star", "m:salmon", "m:deseq2"]


def test_a_correct_real_chain_has_no_broken_steps():
    """The regression this metric was rewritten for.

    Against the real values in fixtures/bench/oracle.json, the pairwise formulation
    scored this verbatim-correct chain 0.5 while claiming coverage 1.0: fastqc is a side
    branch off the reads channel and salmon consumes reads rather than STAR's BAM, so
    two of its four adjacent pairs came out BROKEN. No model could exceed 0.5.
    """
    result = score_validity(_real_chain(), _fixture_oracle())
    assert result["n_broken"] == 0
    assert result["score"] == 1.0


def test_the_reversed_real_chain_emits_a_broken_step():
    """Discrimination check: a formulation that can never emit BROKEN is vacuous.

    Reversed, deseq2 runs first and consumes the count matrix salmon produces four
    steps later — consumed before produced.
    """
    result = score_validity(list(reversed(_real_chain())), _fixture_oracle())
    assert result["n_broken"] >= 1
    assert result["score"] < 1.0
    assert result["pairs"][0]["step"] == "m:deseq2"
    assert result["pairs"][0]["result"] == "BROKEN"


def test_a_type_preserving_step_downstream_does_not_break_an_upstream_consumer():
    """trimgalore takes reads (data_1234) and emits reads. That re-emission is not
    evidence that fastqc — which consumes reads straight off the pipeline's input
    channel — ran too early."""
    result = score_validity(["m:fastqc", "m:trimgalore"], _fixture_oracle())
    assert [p["result"] for p in result["pairs"]] == ["UNKNOWN", "UNKNOWN"]
    assert result["score"] is None


from methods_graph.bench.score import (
    aggregate_next_step, position_bucket, score_next_step)


def test_exact_next_step_is_top1():
    result = score_next_step("m:salmon", ["m:salmon", "m:deseq2"], _oracle())
    assert result["top1"] is True
    assert result["topk"] is True


def test_equivalent_next_step_is_top1():
    result = score_next_step("m:star", ["m:hisat2"], _oracle())
    assert result["top1"] is True


def test_right_answer_ranked_second_is_topk_not_top1():
    result = score_next_step("m:deseq2", ["m:salmon", "m:deseq2"], _oracle())
    assert result["top1"] is False
    assert result["topk"] is True


def test_right_answer_ranked_fourth_is_outside_k():
    ranked = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    assert score_next_step("m:deseq2", ranked, _oracle(), k=3)["topk"] is False


def test_empty_answer_scores_false_not_an_error():
    result = score_next_step("m:star", [], _oracle())
    assert result["top1"] is False
    assert result["topk"] is False


def test_position_buckets():
    assert position_bucket(0) == "0"
    assert position_bucket(1) == "1-2"
    assert position_bucket(2) == "1-2"
    assert position_bucket(3) == "3-5"
    assert position_bucket(5) == "3-5"
    assert position_bucket(6) == "6+"
    assert position_bucket(40) == "6+"


def test_headline_excludes_the_first_step_bucket():
    # Two properties are pinned here and the fixture must separate BOTH:
    #   1. macro-mean over buckets, not per-item mean (asymmetric bucket sizes: "1-2"
    #      holds 2 items and its rate differs from "3-5");
    #   2. the headline drops bucket "0" while pooled keeps it.
    # Bucket "0" therefore holds two rows at a rate (0.5) unlike the others, so
    # headline (0.75) and pooled (0.6) come out different numbers. With a single
    # bucket-0 row both land on 0.75 and property 2 stops being tested at all.
    rows = [
        {"n_given": 0, "top1": True, "topk": True},    # trivially easy, excluded
        {"n_given": 0, "top1": False, "topk": True},   # trivially easy, excluded
        {"n_given": 1, "top1": False, "topk": True},   # bucket "1-2"
        {"n_given": 2, "top1": True, "topk": True},    # bucket "1-2"
        {"n_given": 4, "top1": True, "topk": True},    # bucket "3-5"
    ]
    result = aggregate_next_step(rows)
    assert result["by_bucket"]["0"]["top1"] == 0.5    # (1 + 0) / 2
    assert result["by_bucket"]["1-2"]["top1"] == 0.5  # (0 + 1) / 2
    assert result["by_bucket"]["3-5"]["top1"] == 1.0
    # Macro-mean over non-trivial buckets: (0.5 + 1.0) / 2 = 0.75, NOT the per-item
    # mean of 2/3 ≈ 0.667 that would result if weighting by individual items.
    assert result["headline_top1"] == 0.75
    # Pooled keeps bucket 0 and weights per item: (1 + 0 + 0 + 1 + 1) / 5 = 0.6.
    assert result["pooled_top1"] == 0.6
    assert result["headline_top1"] != result["pooled_top1"]


def test_headline_is_none_when_only_first_step_items_exist():
    result = aggregate_next_step([{"n_given": 0, "top1": True, "topk": True}])
    assert result["headline_top1"] is None


def test_repeated_leading_entry_does_not_evict_from_topk():
    # Ranked list with repetitions: deduping avoids pushing a correct answer
    # outside the top-k window purely by duplication.
    ranked = ["m:star", "m:star", "m:star", "m:deseq2"]
    result = score_next_step("m:deseq2", ranked, _oracle(), k=3)
    # After deduping: ["m:star", "m:deseq2"], so deseq2 is at index 1 (within top-3).
    assert result["topk"] is True
    assert result["top1"] is False


import json
from pathlib import Path

from methods_graph.bench.baselines import gold_adapter, modal_adapter, random_adapter
from methods_graph.bench.oracle import load_oracle
from methods_graph.bench.run import run_items, summarize

_FIXTURES = Path(__file__).parent / "fixtures" / "bench"


def _fixture_items():
    return json.loads((_FIXTURES / "rnaseq.json").read_text())


def _fixture_oracle():
    return load_oracle(json_path=_FIXTURES / "oracle.json")


def test_ceiling_gold_fed_back_scores_one_on_every_metric():
    # EVERY axis, not just selection and sequencing. Leaving validity out of this gate
    # is what let the pairwise handoff formulation cap a verbatim-correct answer at 0.5
    # for a whole branch: the fixture's gold chain is nf-core/rnaseq's real default
    # path, and a correct answer to it must score 1.0 on the axis that asks whether the
    # pipeline runs.
    items = [i for i in _fixture_items() if i["task"] == "whole_pipeline"]
    oracle = _fixture_oracle()
    rows = run_items(items, gold_adapter(items, oracle), oracle, model="gold")
    summary = summarize(rows)
    assert summary["whole_pipeline"]["selection_f1"] == 1.0
    assert summary["whole_pipeline"]["sequencing"] == 1.0
    assert summary["whole_pipeline"]["validity"] == 1.0
    assert summary["n_errors"] == 0


def test_random_baseline_is_deterministic_for_a_seed():
    oracle = _fixture_oracle()
    first = random_adapter(oracle, k=4, seed=7)("any prompt")
    second = random_adapter(oracle, k=4, seed=7)("any prompt")
    assert first == second


def test_random_baseline_differs_across_seeds():
    oracle = _fixture_oracle()
    assert (random_adapter(oracle, k=4, seed=7)("p")
            != random_adapter(oracle, k=4, seed=8)("p"))


def test_modal_baseline_ignores_the_goal():
    items = [i for i in _fixture_items() if i["task"] == "whole_pipeline"]
    adapter = modal_adapter(items, _fixture_oracle())
    assert adapter("Goal: A") == adapter("Goal: something completely different")


def test_match_steps_returns_identity_pairing_when_gold_contains_a_mutual_equivalence():
    """`m:star` and `m:hisat2` are mutually `same_class` in the fixture oracle: they
    share EDAM operation_0292 and input data:data_1234. Feeding gold back as its own
    pred must match every step to itself, not merely reach maximum cardinality —
    Kuhn's algorithm can return any maximum matching, and a non-identity one that
    happens to have the same size silently swaps the pair's positions. That swap is
    exactly what corrupted the ceiling test's sequencing score (0.5 instead of 1.0) on
    a verbatim-correct answer before match_steps preferred identity pairs.
    """
    oracle = _fixture_oracle()
    assert same_class("m:star", "m:hisat2", oracle) is True
    assert same_class("m:hisat2", "m:star", oracle) is True
    gold = ["m:fastqc", "m:star", "m:hisat2", "m:deseq2"]
    assert match_steps(gold, list(gold), oracle) == {g: g for g in gold}


def test_bridging_operations_do_not_make_a_qc_tool_a_quantifier():
    """fastqc and salmon share EDAM operation_0236 (*Sequence composition calculation*)
    and input data:data_1234, so the operation+input rule alone treats a read-QC tool
    and a transcript quantifier as interchangeable — the same failure shape
    test_bwa_is_not_credited_for_spliced_alignment guards against, surfacing on the
    operation side. Both appear in essentially every RNA-seq gold sequence, so this
    single pair inflated the selection headline on the project's target domain.
    """
    oracle = _fixture_oracle()
    # The bridge really is there — this is what an un-denylisted rule would credit.
    assert oracle.operations("m:fastqc") & oracle.operations("m:salmon")
    assert oracle.inputs("m:fastqc") & oracle.inputs("m:salmon")
    assert same_class("m:fastqc", "m:salmon", oracle) is False


_DB_PATH = Path("data/methods.kuzu")

# Every non-identity `same_class` pair the real 905-method graph admits, after the
# bridging-operation denylist. Pinned rather than described: the relation is small
# enough to hand-audit, and a re-curation that introduces an eighth pair must fail CI
# and get looked at instead of silently changing what the benchmark credits.
#
# The two pairs the denylist removes, both wrong:
#   m:affy   <-> m:gsea    via op:operation_2495 (Expression analysis)
#   m:fastqc <-> m:salmon  via op:operation_0236 (Sequence composition calculation)
_EXPECTED_EQUIVALENCE_PAIRS = [
    ["m:bwa", "m:bwamem2"],        # op:operation_0292 — short-read aligners
    ["m:bwa", "m:strobealign"],    # op:operation_3198, op:operation_3211
    ["m:deseq2", "m:limma"],       # op:operation_3223, op:operation_3680 — DE testing
    ["m:fastp", "m:fastqc"],       # op:operation_3218 — sequencing quality control
    ["m:hisat2", "m:star"],        # op:operation_0292 — spliced aligners
    ["m:kraken2", "m:metabuli"],   # op:operation_3460 — taxonomic classification
    ["m:rsem", "m:salmon"],        # op:operation_3800 — RNA-seq quantification
]


@pytest.mark.skipif(not _DB_PATH.exists(), reason="no built graph at data/methods.kuzu")
def test_equivalence_relation_over_the_real_graph_is_exactly_the_expected_set():
    """Enumerate the whole relation and pin it.

    A pair needs a shared non-bridging operation AND a shared input Data node, so only
    the 49 methods carrying curated input Data can appear — the scan below is the
    complete enumeration, not a sample.
    """
    from methods_graph.bench.oracle import KuzuOracle

    oracle = KuzuOracle(_DB_PATH)
    candidates = [m for m in oracle.method_ids() if oracle.inputs(m)]
    pairs = [
        [a, b]
        for index, a in enumerate(candidates)
        for b in candidates[index + 1:]
        if same_class(a, b, oracle)
    ]
    assert pairs == _EXPECTED_EQUIVALENCE_PAIRS
    # The published report must show the same list the test pins.
    assert equivalence_pairs(oracle) == _EXPECTED_EQUIVALENCE_PAIRS


def test_equivalence_pairs_excludes_identity_and_is_sorted():
    pairs = equivalence_pairs(_fixture_oracle())
    assert all(a < b for a, b in pairs)
    assert pairs == sorted(pairs)
    assert ["m:hisat2", "m:star"] in pairs
    assert ["m:fastqc", "m:salmon"] not in pairs
