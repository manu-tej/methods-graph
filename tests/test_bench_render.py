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
    # Test whole_pipeline task: must not leak answer keys from gold
    whole_prompt = render_prompt(_whole_item(), _oracle())
    for leaked in ("star", "salmon", "fastqc", "mod:"):
        assert leaked not in whole_prompt.lower(), \
            f"Whole pipeline prompt leaked {leaked!r}"

    # Test next_step task: must not leak the gold next step, and _display_name must hide mod: ids
    next_prompt = render_prompt(_next_item(["mod:fastqc", "mod:star_align"]), _oracle())
    # Should contain display names for the given steps
    assert "fastqc" in next_prompt
    assert "star" in next_prompt
    # Should NOT contain module ids or gold answer
    assert "mod:" not in next_prompt
    assert "salmon" not in next_prompt  # salmon is the gold next step, must not leak


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


def test_stray_bracket_before_real_array_does_not_prevent_parsing():
    # Models write "Step [1]: run QC, then [...]". First [1] is not JSON, second is.
    raw = 'Steps [1] then the answer: ["fastqc", "star"]'
    assert parse_tool_list(raw) == ["fastqc", "star"]


def test_stray_bracket_after_valid_array_still_returns_first():
    # A valid array followed by dangling brackets should still work.
    raw = '["fastqc", "star"] (wait, also consider [other])'
    assert parse_tool_list(raw) == ["fastqc", "star"]


def test_unterminated_bracket_before_valid_array_still_parses_valid():
    # [unterminated before a real array at the end.
    raw = 'Consider this: [incomplete sentence, then the answer: ["fastqc", "star"]'
    assert parse_tool_list(raw) == ["fastqc", "star"]


def test_all_candidates_unusable_still_returns_empty():
    # Every bracket pair is either invalid JSON, non-list, or contains only non-strings.
    raw = '[not json here] and [42] and ["  "] and null'
    # [not json here] is not valid JSON
    # [42] is valid JSON but not a list
    # ["  "] is a list but only whitespace strings (filtered)
    # null is not a bracket pair
    assert parse_tool_list(raw) == []
