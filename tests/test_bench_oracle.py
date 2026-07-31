from methods_graph.bench.oracle import StaticOracle, coverage


def _oracle():
    return StaticOracle(
        methods=["m:star", "m:hisat2", "m:bwa", "m:bowtie2"],
        modules={
            "mod:star_align": "m:star",
            "mod:star_genomegenerate": "m:star",
            "mod:hisat2_align": "m:hisat2",
            "mod:custom_orfnormalise": "m:bwa",
        },
        operations={
            "m:star": ["op:operation_0292"],
            "m:hisat2": ["op:operation_0292"],
            "m:bwa": ["op:operation_0292", "op:operation_3198"],
            "m:bowtie2": ["op:operation_3198"],
        },
        inputs={
            "m:star": ["data:data_1234", "data:data_2977"],
            "m:hisat2": ["data:data_1234", "data:data_2977"],
            "m:bwa": ["data:data_2044"],
        },
        outputs={"m:star": ["data:data_0863"], "m:hisat2": ["data:data_0863"]},
    )


def test_module_resolves_to_method():
    assert _oracle().method_for_module("mod:star_align") == "m:star"


def test_unknown_module_is_none_not_a_guess():
    assert _oracle().method_for_module("mod:nowhere") is None


def test_missing_method_has_empty_sets_not_a_keyerror():
    oracle = _oracle()
    assert oracle.operations("m:nowhere") == frozenset()
    assert oracle.inputs("m:bowtie2") == frozenset()


def test_coverage_reports_each_denominator_separately():
    report = coverage(_oracle(), [
        "mod:star_align", "mod:hisat2_align", "mod:custom_orfnormalise", "mod:nowhere",
    ])
    assert report["n_modules"] == 4
    assert report["n_resolved"] == 3
    assert report["unresolved"] == ["mod:nowhere"]
    # m:star, m:hisat2, m:bwa all have operations; only star+hisat2 have output Data.
    assert report["n_methods"] == 3
    assert report["n_with_operations"] == 3
    assert report["n_with_input_data"] == 3
    assert report["n_with_output_data"] == 2


def test_coverage_of_empty_input_is_zero_not_a_crash():
    report = coverage(_oracle(), [])
    assert report["n_modules"] == 0
    assert report["resolved_fraction"] is None


def test_method_ids_returns_methods_sorted():
    oracle = _oracle()
    assert oracle.method_ids() == ["m:bowtie2", "m:bwa", "m:hisat2", "m:star"]


def _ambiguous_oracle():
    """``mod:custom_orfnormalise`` wraps six methods on the real graph; the projection
    keeps the lexicographically first and discards five."""
    return StaticOracle(
        methods=["m:bwa", "m:star", "m:hisat2"],
        modules={"mod:custom_orfnormalise": "m:bwa", "mod:star_align": "m:star"},
        multi_wrapped={"mod:custom_orfnormalise": ["m:bwa", "m:hisat2", "m:star"]},
    )


def test_coverage_reports_the_arbitrary_pick_it_made_for_multi_wrapped_modules():
    """The plan requires the deterministic pick to be REPORTED, not merely made. Without
    this, five discarded candidates are invisible in every report."""
    report = coverage(_ambiguous_oracle(),
                      ["mod:custom_orfnormalise", "mod:star_align"])
    assert report["n_multi_wrapped"] == 1
    assert report["multi_wrapped"] == {
        "mod:custom_orfnormalise": ["m:bwa", "m:hisat2", "m:star"]}


def test_coverage_multi_wrapped_is_scoped_to_the_modules_under_test():
    report = coverage(_ambiguous_oracle(), ["mod:star_align"])
    assert report["n_multi_wrapped"] == 0
    assert report["multi_wrapped"] == {}


def test_multi_wrapped_is_part_of_the_oracle_contract():
    """On the protocol, not just on StaticOracle — a coverage report that calls it must
    be able to rely on any Oracle providing it."""
    from methods_graph.bench.oracle import Oracle

    assert "multi_wrapped" in Oracle.__protocol_attrs__
    assert _oracle().multi_wrapped() == {}
