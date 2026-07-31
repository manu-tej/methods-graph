from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.score import match_steps, same_class, score_selection, score_sequencing


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


def test_typechecking_handoffs_score_one():
    result = score_validity(["m:star", "m:salmon", "m:deseq2"], _io_oracle())
    assert result["score"] == 1.0
    assert result["n_valid"] == 2
    assert result["n_broken"] == 0


def test_disjoint_handoff_is_broken():
    result = score_validity(["m:star", "m:deseq2"], _io_oracle())
    assert result["n_broken"] == 1
    assert result["score"] == 0.0


def test_unknown_is_never_counted_as_valid():
    # bowtie2 has no curated I/O at all — both its pairs are unverifiable.
    result = score_validity(["m:star", "m:bowtie2", "m:deseq2"], _io_oracle())
    assert result["n_unknown"] == 2
    assert result["n_valid"] == 0
    assert result["score"] is None


def test_coverage_reports_how_much_of_the_answer_was_checkable():
    result = score_validity(["m:star", "m:salmon", "m:bowtie2"], _io_oracle())
    assert result["n_pairs"] == 2
    assert result["n_unknown"] == 1
    assert result["coverage"] == 0.5
    assert result["score"] == 1.0     # the one checkable pair was valid


def test_single_step_answer_has_no_pairs():
    result = score_validity(["m:star"], _io_oracle())
    assert result["n_pairs"] == 0
    assert result["score"] is None
    assert result["coverage"] is None


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
    # Asymmetric bucket sizes: bucket "1-2" has 2 items (rates differ from "3-5"),
    # so macro-mean over buckets diverges from per-item mean over non-bucket-0 rows.
    # Macro-mean: (0.5 + 1.0) / 2 = 0.75. Per-item mean: 2/3 ≈ 0.667.
    # The assertion pins the macro-mean, not the per-item alternative.
    rows = [
        {"n_given": 0, "top1": True, "topk": True},    # trivially easy, excluded
        {"n_given": 1, "top1": False, "topk": True},   # bucket "1-2"
        {"n_given": 2, "top1": True, "topk": True},    # bucket "1-2"
        {"n_given": 4, "top1": True, "topk": True},    # bucket "3-5"
    ]
    result = aggregate_next_step(rows)
    assert result["by_bucket"]["0"]["top1"] == 1.0
    assert result["by_bucket"]["1-2"]["top1"] == 0.5  # (0 + 1) / 2
    assert result["by_bucket"]["3-5"]["top1"] == 1.0
    # Macro-mean over non-trivial buckets: (0.5 + 1.0) / 2 = 0.75, NOT the per-item
    # mean of 2/3 ≈ 0.667 that would result if weighting by individual items.
    assert result["headline_top1"] == 0.75
    assert result["pooled_top1"] == 0.75  # (1 + 0 + 1 + 1) / 4


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
    # The fixture's one whole_pipeline item deliberately runs fastqc -> trimgalore ->
    # hisat2_align -> deseq2_differential rather than nf-core/rnaseq's default
    # star_align + salmon_quant path. star and salmon are still in the fixture oracle
    # (exercised by the next_step items below and by the known-limitation test), but
    # putting BOTH fastqc and salmon in one gold sequence would poison this exact
    # test: they are same_class per the fixture oracle (both carry op:operation_0236
    # and input data:data_1234, see the known-limitation test), and match_steps's
    # maximum-cardinality matching does not prefer identity pairs when a mutual
    # same_class collision is present in gold==pred — it provably swaps them instead
    # (verified directly against match_steps/score_sequencing: swapping the fastqc/
    # salmon assignment drops sequencing from 1.0 to 0.5 even though the answer is
    # gold verbatim). That is a real, separate gap in match_steps's tie-breaking
    # this task is not scoped to fix; the HISAT2 path sidesteps it so this CI gate
    # measures the baselines under test, not that unrelated gap.
    items = [i for i in _fixture_items() if i["task"] == "whole_pipeline"]
    oracle = _fixture_oracle()
    rows = run_items(items, gold_adapter(items, oracle), oracle, model="gold")
    summary = summarize(rows)
    assert summary["whole_pipeline"]["selection_f1"] == 1.0
    assert summary["whole_pipeline"]["sequencing"] == 1.0
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


def test_known_limitation_coarse_edam_operation_bridges_fastqc_and_salmon():
    """KNOWN LIMITATION, recorded so it stays visible rather than latent.

    Against the fixture oracle's real values, fastqc and salmon share EDAM
    operation_0236 (Sequence composition calculation) AND input data:data_1234, so
    same_class's operation+input-overlap rule treats a QC tool and a quantifier as
    interchangeable — the same failure shape test_bwa_is_not_credited_for_spliced_
    alignment guards against above, surfacing on a different pair because
    operation_0236 is coarse enough to bridge them.

    This assertion describes CURRENT behaviour; it is not a desired property, and
    same_class must not be changed to make this test pass. If same_class is ever
    tightened (e.g. requiring ALL shared operations, or blacklisting bridging
    operations like operation_0236), this assertion should flip to False as part of
    that change — the point of pinning it here is that the flip happens on purpose,
    not that the current value is correct.
    """
    assert same_class("m:fastqc", "m:salmon", _fixture_oracle()) is True
