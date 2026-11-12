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

from methods_graph.bench.adapters import AdapterError
from methods_graph.bench.normalize import project_sequence
from methods_graph.bench.oracle import Oracle
from methods_graph.bench.render import render_prompt

_BASELINE_PROVIDERS = ("gold", "modal", "random")
_FALLBACK_K = 3


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


def _typical_answer_length(items: list[dict[str, Any]], oracle: Oracle) -> int:
    """How many tools the random floor should name: the mean gold answer length.

    Derived from the item set rather than fixed, so the floor is comparable to the
    models on precision as well as recall — a 3-tool guess against 12-step gold
    sequences would flatter its precision and understate its recall.
    """
    lengths = [
        len(project_sequence(item["gold"]["sequence"], oracle)[0])
        for item in items if item["task"] == "whole_pipeline"
    ]
    return max(1, round(sum(lengths) / len(lengths))) if lengths else _FALLBACK_K


def is_baseline_spec(spec: str) -> bool:
    """Does this ``--model`` spec name a baseline rather than a contestant?"""
    return spec.partition(":")[0] in _BASELINE_PROVIDERS


def baseline_adapter(
    spec: str, items: list[dict[str, Any]], oracle: Oracle,
) -> Callable[[str], str]:
    """``gold:`` / ``modal:`` / ``random:<seed>[:<k>]`` over a specific item set.

    Kept out of :func:`~methods_graph.bench.adapters.get_adapter` on purpose: these
    three need the item list and the oracle, which the other three providers have no
    use for. Giving ``get_adapter`` two optional parameters that half its branches
    ignore — and that are required-but-unenforced for the other half — buys nothing
    over resolving them at the one call site where both are already in scope.
    """
    provider, _, argument = spec.partition(":")
    if provider == "gold":
        return gold_adapter(items, oracle)
    if provider == "modal":
        return modal_adapter(items, oracle)
    if provider == "random":
        seed, _, k = argument.partition(":")
        try:
            seed_value = int(seed)
        except ValueError:
            raise AdapterError(
                f"random baseline needs an integer seed: expected random:<seed>[:<k>], "
                f"got {spec!r}") from None
        try:
            k_value = int(k) if k else _typical_answer_length(items, oracle)
        except ValueError:
            raise AdapterError(
                f"random baseline's k must be an integer, got {k!r}") from None
        return random_adapter(oracle, k=k_value, seed=seed_value)
    raise AdapterError(f"{spec!r} is not a baseline spec")
