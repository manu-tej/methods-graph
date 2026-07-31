"""Four metric families: did it pick the right tools, did it order them correctly,
does the pipeline run, and given progress, can it name the next step.

A single accuracy figure hides interesting failures — a model that knows every tool
and orders them wrongly, a model that names the right tools in an unrunnable order,
or a model that can plan but struggles to sequence individual steps. Each metric
returns ``None`` when its denominator is empty; ``0.0`` would claim a measurement
that was never made. Exception: :func:`score_selection` returns ``0.0`` for an empty
prediction list, since precision over an empty answer is genuinely zero, not undefined.
"""
from __future__ import annotations

from typing import Any

from methods_graph.bench.oracle import Oracle
from methods_graph.guardrail import (
    HANDOFF_BROKEN, HANDOFF_UNKNOWN, HANDOFF_VALID, classify_handoff)


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


def score_sequencing(
    gold_edges: list[tuple[str, str]] | list[list[str]],
    matched: dict[str, str],
    pred: list[str],
) -> dict[str, Any]:
    """What order — the fraction of REQUIRED precedences the answer respects.

    Scores the DAG's edges, never the gold sequence's adjacent pairs. Linearizing a DAG
    puts parallel branches next to each other though nothing orders them, so an
    adjacency metric marks a correct interleaving wrong. Only edges whose BOTH endpoints
    were selected are scorable, which is what makes this independent of the selection
    score rather than a second copy of it.
    """
    position = {method_id: index for index, method_id in enumerate(pred)}
    scorable = [
        (source, target) for source, target in gold_edges
        if source in matched and target in matched
    ]
    if not scorable:
        return {"score": None, "n_scorable": 0, "n_respected": 0,
                "n_gold_edges": len(gold_edges)}

    respected = sum(
        1 for source, target in scorable
        if position[matched[source]] < position[matched[target]]
    )
    return {
        "score": respected / len(scorable),
        "n_scorable": len(scorable),
        "n_respected": respected,
        "n_gold_edges": len(gold_edges),
    }


def score_validity(pred: list[str], oracle: Oracle) -> dict[str, Any]:
    """Does it run — the share of consecutive handoffs whose data types meet.

    ``UNKNOWN`` (a step with no curated Data I/O) is excluded from the score's
    denominator and reported as its own count. Folding it into "valid" would inflate the
    number with ignorance, and folding it into "invalid" would punish a correct answer
    for a curation gap. ``coverage`` says how much of the answer was checkable at all —
    with output Data curated for 39 of 905 methods, that caveat is the headline, not a
    footnote.
    """
    pairs: list[dict[str, Any]] = []
    counts = {HANDOFF_VALID: 0, HANDOFF_BROKEN: 0, HANDOFF_UNKNOWN: 0}
    for producer, consumer in zip(pred, pred[1:]):
        result, shared = classify_handoff(
            set(oracle.outputs(producer)), set(oracle.inputs(consumer)))
        counts[result] += 1
        pairs.append({"from": producer, "to": consumer,
                      "result": result, "shared": shared})

    classified = counts[HANDOFF_VALID] + counts[HANDOFF_BROKEN]
    return {
        "score": counts[HANDOFF_VALID] / classified if classified else None,
        "n_pairs": len(pairs),
        "n_valid": counts[HANDOFF_VALID],
        "n_broken": counts[HANDOFF_BROKEN],
        "n_unknown": counts[HANDOFF_UNKNOWN],
        "coverage": classified / len(pairs) if pairs else None,
        "pairs": pairs,
    }


# Position buckets for next-step items, by how many steps were already given. "0" is
# broken out because "name the first step" is nearly always a QC tool and is the easiest
# item in the set; pooling it with the rest inflates the headline.
_BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (0, 0, "0"), (1, 2, "1-2"), (3, 5, "3-5"), (6, None, "6+"),
)
_FIRST_STEP_BUCKET = "0"


def score_next_step(
    gold_next: str, ranked: list[str], oracle: Oracle, k: int = 3,
) -> dict[str, Any]:
    """One next-step item: is the gold step (or its equivalent) ranked first, or in top-k?

    Dedupes the ranked list first, matching the behavior of match_steps and
    score_selection. A model answering ["STAR","STAR","STAR","HISAT2"] would
    otherwise push HISAT2 outside top-3 purely by repetition.
    """
    ranked = _unique(ranked)
    return {
        "top1": bool(ranked) and same_class(gold_next, ranked[0], oracle),
        "topk": any(same_class(gold_next, candidate, oracle) for candidate in ranked[:k]),
        "k": k,
    }


def position_bucket(n_given: int) -> str:
    """Which difficulty bucket a next-step item falls in, by prefix length."""
    for low, high, label in _BUCKETS:
        if n_given >= low and (high is None or n_given <= high):
            return label
    raise ValueError(f"no bucket for n_given={n_given}")  # pragma: no cover - total


def aggregate_next_step(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Next-step accuracy by position bucket, plus a headline that skips the free one.

    The headline is a macro-mean over the non-trivial buckets: pooling weights the
    benchmark by pipeline length, so long pipelines would quietly dominate, and the
    first-step bucket would lift every model's number by the same free amount.
    """
    by_bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_bucket.setdefault(
            position_bucket(row["n_given"]), {"n": 0, "top1": 0, "topk": 0})
        bucket["n"] += 1
        bucket["top1"] += int(row["top1"])
        bucket["topk"] += int(row["topk"])

    for bucket in by_bucket.values():
        bucket["top1"] = bucket["top1"] / bucket["n"]
        bucket["topk"] = bucket["topk"] / bucket["n"]

    scored = [v for label, v in sorted(by_bucket.items()) if label != _FIRST_STEP_BUCKET]
    return {
        "n": len(rows),
        "by_bucket": by_bucket,
        "headline_top1": (
            None if not scored else sum(b["top1"] for b in scored) / len(scored)),
        "headline_topk": (
            None if not scored else sum(b["topk"] for b in scored) / len(scored)),
        "pooled_top1": (
            None if not rows else sum(int(r["top1"]) for r in rows) / len(rows)),
        "pooled_topk": (
            None if not rows else sum(int(r["topk"]) for r in rows) / len(rows)),
    }
