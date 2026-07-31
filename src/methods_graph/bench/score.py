"""Three numbers, deliberately separate: did it pick, did it order, does it run.

A single accuracy figure hides both interesting failures — a model that knows every
tool and orders them wrongly, and a model that names the right tools in an unrunnable
order. Each metric returns ``None`` when its denominator is empty; ``0.0`` would claim a
measurement that was never made. Exception: :func:`score_selection` returns ``0.0`` for
an empty prediction list, since precision over an empty answer is genuinely zero, not
undefined.
"""
from __future__ import annotations

from typing import Any

from methods_graph.bench.oracle import Oracle


def _unique(items: list[str]) -> list[str]:
    """Order-preserving dedupe. Callers upstream already dedupe; this makes the
    metric total rather than silently collapsing a repeat into a lost match.
    """
    return list(dict.fromkeys(items))


def same_class(a: str, b: str, oracle: Oracle) -> bool:
    """Are these two methods interchangeable for the benchmark's purposes?

    Class = shared EDAM operation AND shared input data type. Operation alone is too
    coarse: ``bwa`` and ``STAR`` both perform *Sequence alignment*, but ``bwa`` accepts
    ``Sequence``/``Genome index`` while ``STAR`` accepts ``Sequence set (nucleic acid)``,
    so operation-only equivalence would credit an unspliced aligner for spliced RNA
    alignment.

    Identity is a separate disjunct because input Data is curated for only 49 of 905
    methods — without it a method with no curated inputs would fail to match itself.
    """
    if a == b:
        return True
    if not (oracle.operations(a) & oracle.operations(b)):
        return False
    return bool(oracle.inputs(a) & oracle.inputs(b))


def match_steps(
    gold: list[str], pred: list[str], oracle: Oracle,
) -> dict[str, str]:
    """Maximum one-to-one matching of gold steps to predicted steps.

    Maximum, not greedy: equivalence is not transitive and not a partition, so a greedy
    left-to-right pass can bind a predicted tool to the first gold step it fits and
    strand a later gold step that only that tool could have covered. Kuhn's augmenting
    path, with both sides iterated in their given order, is deterministic.
    """
    gold = _unique(gold)
    pred = _unique(pred)
    adjacency = {g: [p for p in pred if same_class(g, p, oracle)] for g in gold}
    owner: dict[str, str] = {}  # predicted id -> gold id currently holding it

    def _augment(g: str, seen: set[str]) -> bool:
        for p in adjacency[g]:
            if p in seen:
                continue
            seen.add(p)
            if p not in owner or _augment(owner[p], seen):
                owner[p] = g
                return True
        return False

    for g in gold:
        _augment(g, set())
    return {g: p for p, g in owner.items()}


def score_selection(
    gold: list[str], pred: list[str], oracle: Oracle,
) -> dict[str, Any]:
    """Which methods — step-set F1, order ignored, equivalence classes applied."""
    gold = _unique(gold)
    pred = _unique(pred)
    matched = match_steps(gold, pred, oracle)
    true_positives = len(matched)
    precision = true_positives / len(pred) if pred else 0.0
    recall = true_positives / len(gold) if gold else 0.0
    denominator = precision + recall
    return {
        "precision": precision,
        "recall": recall,
        "f1": 0.0 if denominator == 0 else 2 * precision * recall / denominator,
        "n_gold": len(gold),
        "n_pred": len(pred),
        "n_matched": true_positives,
        "matched": matched,
    }
