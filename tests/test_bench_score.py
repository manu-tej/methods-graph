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
