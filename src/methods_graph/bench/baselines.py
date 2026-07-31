"""Floor, ceiling and the one baseline that can embarrass the benchmark.

A model score means nothing without them. The modal baseline is the sharp one: if
"always answer the most common gold pipeline, ignoring the question" scores close to a
model, the benchmark is measuring pipeline-shape priors rather than method knowledge.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from typing import Any, Callable

from methods_graph.bench.normalize import project_sequence
from methods_graph.bench.oracle import Oracle
from methods_graph.bench.render import render_prompt


def _bare(method_id: str) -> str:
    return method_id.split(":", 1)[1] if ":" in method_id else method_id


def _as_answer(method_ids: list[str]) -> str:
    return json.dumps([_bare(m) for m in method_ids])


def gold_adapter(
    items: list[dict[str, Any]], oracle: Oracle,
) -> Callable[[str], str]:
    """The ceiling: answer each item with its own gold. Must score 1.0, and is a CI gate.

    Keyed by rendered prompt rather than item id because an adapter only ever sees the
    prompt — which also means this quietly asserts that prompts are unique per item.
    """
    table: dict[str, str] = {}
    for item in items:
        if item["task"] == "whole_pipeline":
            sequence, _ = project_sequence(item["gold"]["sequence"], oracle)
            table[render_prompt(item, oracle)] = _as_answer(sequence)
        else:
            gold_next = oracle.method_for_module(item["gold"]["next"])
            table[render_prompt(item, oracle)] = _as_answer(
                [gold_next] if gold_next else [])
    return lambda prompt: table.get(prompt, "[]")


def modal_adapter(
    items: list[dict[str, Any]], oracle: Oracle,
) -> Callable[[str], str]:
    """Always answer the single most common gold sequence, ignoring the goal entirely."""
    counts: Counter[tuple[str, ...]] = Counter()
    for item in items:
        if item["task"] == "whole_pipeline":
            sequence, _ = project_sequence(item["gold"]["sequence"], oracle)
            counts[tuple(sequence)] += 1
    # Ties break on the lexicographically smallest sequence, so the baseline is stable
    # across item-set revisions rather than shifting with dict ordering.
    best = min(seq for seq, n in counts.items() if n == max(counts.values())) if counts else ()
    answer = _as_answer(list(best))
    return lambda _prompt: answer


def random_adapter(
    oracle: Oracle, *, k: int, seed: int,
) -> Callable[[str], str]:
    """The floor: *k* methods drawn uniformly from the catalog, seeded for determinism."""
    catalog = oracle.method_ids()
    if not catalog:
        raise ValueError("oracle exposes no methods to sample from")
    rng = random.Random(seed)
    answer = _as_answer(rng.sample(catalog, min(k, len(catalog))))
    return lambda _prompt: answer
