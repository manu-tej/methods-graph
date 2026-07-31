import pytest

from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.render import parse_tool_list, render_prompt


def _oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:salmon"],
        modules={"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                 "mod:salmon_quant": "m:salmon"},
    )


def _whole_item():
    return {
        "id": "rnaseq/whole/001", "task": "whole_pipeline",
        "goal": "Bulk RNA-seq differential expression from paired-end human FASTQ",
        "given": [],
        "gold": {"sequence": ["mod:fastqc", "mod:star_align", "mod:salmon_quant"]},
    }


def _next_item(given):
    return {"id": "rnaseq/next/002", "task": "next_step", "goal": "Bulk RNA-seq",
            "given": given, "gold": {"next": "mod:salmon_quant"}}


def test_whole_pipeline_prompt_states_the_goal_and_asks_for_a_json_array():
    prompt = render_prompt(_whole_item(), _oracle())
    assert "Bulk RNA-seq differential expression" in prompt
    assert "JSON array" in prompt


def test_prompt_never_leaks_the_answer():
    prompt = render_prompt(_whole_item(), _oracle())
    for leaked in ("star", "salmon", "fastqc", "mod:"):
        assert leaked not in prompt.lower()


def test_next_step_prompt_renders_given_as_tool_names_not_module_ids():
    prompt = render_prompt(_next_item(["mod:fastqc", "mod:star_align"]), _oracle())
    assert "fastqc" in prompt
    assert "star" in prompt
    assert "mod:" not in prompt
    assert "star_align" not in prompt


def test_next_step_prompt_falls_back_to_the_bare_module_name_when_unresolvable():
    prompt = render_prompt(_next_item(["mod:some_local_process"]), _oracle())
    assert "some_local_process" in prompt
    assert "mod:" not in prompt


def test_next_step_prompt_asks_for_a_ranked_shortlist():
    prompt = render_prompt(_next_item(["mod:fastqc"]), _oracle())
    assert "3" in prompt
    assert "best first" in prompt.lower()


def test_unknown_task_type_raises_rather_than_rendering_something_wrong():
    with pytest.raises(ValueError, match="unknown task"):
        render_prompt({"id": "x", "task": "freeform", "goal": "g", "given": [],
                       "gold": {}}, _oracle())


@pytest.mark.parametrize("raw,expected", [
    ('["fastqc", "STAR", "salmon"]', ["fastqc", "STAR", "salmon"]),
    ('Here you go:\n["fastqc", "STAR"]\nHope that helps!', ["fastqc", "STAR"]),
    ('```json\n["fastqc", "STAR"]\n```', ["fastqc", "STAR"]),
    ('["fastqc"]', ["fastqc"]),
    ('[]', []),
])
def test_parses_the_json_array_out_of_a_chatty_response(raw, expected):
    assert parse_tool_list(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "I cannot help with that.", "fastqc, STAR, salmon", "[unclosed",
])
def test_unparseable_responses_return_empty_rather_than_guessing(raw):
    assert parse_tool_list(raw) == []


def test_non_string_elements_are_discarded_not_stringified():
    assert parse_tool_list('["fastqc", 42, null, {"tool": "star"}, "salmon"]') == [
        "fastqc", "salmon"]
