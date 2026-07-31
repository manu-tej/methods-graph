"""Item to prompt, and model response back to a list of tool names.

Prompts are identical across models and carry no methods-graph context: the baseline
being measured is what the model knows unaided. They present no candidate list either —
a closed multiple choice would hand over the answer set.
"""
from __future__ import annotations

import json

from methods_graph.bench.oracle import Oracle

_WHOLE_PIPELINE = (
    "Goal: {goal}\n"
    "Return a JSON array of tool names, in execution order.\n"
    "Return only the JSON array, with no commentary."
)

_NEXT_STEP = (
    "Goal: {goal}\n"
    "Completed so far: {given}\n"
    "Return a JSON array of up to 3 candidate tool names for the NEXT step, "
    "best first.\n"
    "Return only the JSON array, with no commentary."
)

_NOTHING_YET = "nothing yet"


def _display_name(module_id: str, oracle: Oracle) -> str:
    """A completed step as a human would name it.

    ``mod:star_align`` is nf-core's vocabulary, not the field's; putting it in the prompt
    would tell the model which registry the answer key came from. Unresolvable modules
    fall back to their bare name — honest, and rare (94% of modules reach a method).
    """
    method_id = oracle.method_for_module(module_id)
    if method_id:
        return method_id.split(":", 1)[1]
    return module_id.split(":", 1)[1] if ":" in module_id else module_id


def render_prompt(item: dict, oracle: Oracle) -> str:
    """The exact text sent to every model for one item."""
    task = item.get("task")
    if task == "whole_pipeline":
        return _WHOLE_PIPELINE.format(goal=item["goal"])
    if task == "next_step":
        names = [_display_name(m, oracle) for m in item.get("given") or []]
        return _NEXT_STEP.format(
            goal=item["goal"], given=", ".join(names) if names else _NOTHING_YET)
    raise ValueError(f"unknown task type: {task!r}")


def _json_array_spans(text: str):
    """Generator yielding all balanced ``[...]`` spans left to right.

    Allows parsing to try each candidate in turn, so a chatty preamble with
    stray brackets (e.g., "Step [1]: ..." before the answer) does not break parsing.
    """
    start = text.find("[")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    yield text[start:index + 1]
                    break
        start = text.find("[", start + 1)


def parse_tool_list(raw: str) -> list[str]:
    """Tool names from a model response, or ``[]`` if none can be read.

    Tries each balanced JSON array span left to right. Never falls back to splitting
    prose on commas. A guessed parse would be scored as though the model had answered,
    turning a formatting failure into a knowledge result. The caller counts empty
    parses so refusals stay visible.
    """
    if not raw:
        return []
    for span in _json_array_spans(raw):
        try:
            parsed = json.loads(span)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        # Filter to usable strings. Note: nested arrays (e.g., [["a"], ["b"]]) filter
        # to nothing and fall through to the next span, where the first inner span
        # yields its usable strings.
        result = [element for element in parsed if isinstance(element, str) and element.strip()]
        # Empty list is a real answer (e.g., "no more steps needed"); non-empty list
        # with usable strings is also an answer. Only keep searching if the list was
        # non-empty but filtered to nothing (e.g., [1, 2, 3]).
        if not parsed or result:
            return result
    return []
