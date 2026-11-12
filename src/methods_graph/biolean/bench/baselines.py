"""Ceiling, floor, the gene-blind prior, and the constant reply that saturates hypothesize.

Dispatched by item track; a baseline on the wrong track is a usage error raised as
``AdapterError`` so the CLI turns it into exit 2. Every answer is a derivation dict the
kernel will either accept or reject for a stated reason — no baseline emits malformed JSON.
"""
from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path
from typing import Any, Callable

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.items import visible_descendants
from methods_graph.biolean.bench.render import claim_text, render_prompt
from methods_graph.biolean.kernel import propagating_parents
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import FactStore, MaskedFactStore
from methods_graph.biolean.tactics import _starts, prove

BASELINE_TRACK = {"gold": "prove", "random": "prove", "modal": "prove", "template": "hypothesize"}
TEMPLATE_PROVENANCE = {"method": "m:deseq2", "inputs": ["GEO:GSE0"], "parameters": {}}
_MAX_RANDOM_LENGTH = 4


def is_baseline_spec(spec: str) -> bool:
    return spec.partition(":")[0] in BASELINE_TRACK


# ---------------------------------------------------------------------------
# derivation builders
# ---------------------------------------------------------------------------

def _derivation(goal: Prop, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"biolean": "0.1", "goal": goal.to_dict(), "steps": steps, "root": steps[-1]["id"]}


def _at(goal: Prop, term: str) -> dict[str, Any]:
    return Prop(goal.subject, goal.qualifier, term, goal.taxon, False).to_dict()


def _axiom_only(goal: Prop) -> dict[str, Any]:
    """An axiom at the goal term itself. The item hides that row, so this is a counted miss."""
    return _derivation(goal, [{"id": "s1", "rule": "axiom", "conclusion": goal.to_dict()}])


def _chain(goal: Prop, start: str, path: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Axiom at ``start`` then one propagation step per ``(child, relation, parent)`` hop."""
    steps: list[dict[str, Any]] = [{"id": "s1", "rule": "axiom", "conclusion": _at(goal, start)}]
    for i, (child, relation, parent) in enumerate(path, start=2):
        steps.append({"id": f"s{i}", "rule": relation, "premises": [f"s{i - 1}"],
                      "edge": [child, parent], "conclusion": _at(goal, parent)})
    return _derivation(goal, steps)


def _shortest_path(start: str, target: str, store: FactStore) -> list[tuple[str, str, str]] | None:
    """Hops from ``start`` up to ``target`` over propagating edges (sorted expansion), or ``None``."""
    if start == target:
        return []
    came_from: dict[str, tuple[str, str]] = {}
    seen = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        for parent, relation in propagating_parents(cur, store):
            if parent in seen:
                continue
            seen.add(parent)
            came_from[parent] = (cur, relation)
            if parent == target:
                path: list[tuple[str, str, str]] = []
                node = target
                while node != start:
                    child, rel = came_from[node]
                    path.append((child, rel, node))
                    node = child
                return list(reversed(path))
            queue.append(parent)
    return None


def _masked(item: dict[str, Any], store: FactStore) -> tuple[Prop, MaskedFactStore]:
    goal = Prop.from_dict(item["goal"])
    assert goal is not None, item["id"]
    return goal, MaskedFactStore(store, frozenset(item["hidden"]))


# ---------------------------------------------------------------------------
# the four baselines
# ---------------------------------------------------------------------------

def gold_answer(item: dict[str, Any], store: FactStore) -> dict[str, Any]:
    """The mechanical prover over the item's masked store: the ceiling, a CI gate at 1.0."""
    goal, masked = _masked(item, store)
    derivation = prove(goal, masked)
    return derivation if derivation is not None else _axiom_only(goal)


def random_answer(item: dict[str, Any], store: FactStore, rng: random.Random) -> dict[str, Any]:
    """A seeded random visible start under the item's qualifier, a seeded random upward walk of
    seeded random length, root at its end. Structurally valid, so accepted exactly when the
    walk ends at the target. The floor."""
    goal, masked = _masked(item, store)
    starts = _starts(goal.subject, goal.qualifier, goal.taxon, masked)
    if not starts:
        return _axiom_only(goal)
    start = cur = rng.choice(starts)
    path: list[tuple[str, str, str]] = []
    for _ in range(rng.randint(1, _MAX_RANDOM_LENGTH)):
        parents = propagating_parents(cur, masked)
        if not parents:
            break
        parent, relation = rng.choice(parents)
        path.append((cur, relation, parent))
        cur = parent
    return _chain(goal, start, path)


def modal_answer(item: dict[str, Any], store: FactStore, modal: dict[str, Any]) -> dict[str, Any]:
    """The gene-blind prior: the descendant most often annotated across other eligible items
    with the same ``(qualifier, goal term)``, the item's own subject subtracted, ties by sorted
    term id, plus the shortest path up. An empty counter emits the hidden axiom (a miss)."""
    goal, masked = _masked(item, store)
    counts = dict(modal.get(goal.qualifier, {}).get(goal.term, {}))
    for descendant in visible_descendants(masked, goal):
        counts[descendant] = counts.get(descendant, 0) - 1        # leave this subject out
    ranked = sorted((-n, term) for term, n in counts.items() if n > 0)
    if not ranked:
        return _axiom_only(goal)
    best = ranked[0][1]
    path = _shortest_path(best, goal.term, masked)
    return _chain(goal, best, path) if path is not None else _axiom_only(goal)


def template_answer(item: dict[str, Any]) -> dict[str, Any]:
    """A constant sorry-root reply carrying the item's claim. Saturates every hypothesize rate;
    printed beside every model so the ceiling is visible."""
    goal = Prop.from_dict(item["goal"])
    assert goal is not None, item["id"]
    step = {"id": "s1", "rule": "sorry", "conclusion": goal.to_dict(),
            "provenance": {**TEMPLATE_PROVENANCE, "claim": claim_text(item)}}
    return _derivation(goal, [step])


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------

def _table(items: list[dict[str, Any]], answer: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[str], str]:
    """Answers keyed by rendered prompt, computed in item order so a seeded RNG is deterministic.
    An adapter only ever sees the prompt, so this also asserts prompts are unique per item —
    a collision would silently drop one item's answer from the table."""
    table = {render_prompt(item): json.dumps(answer(item), sort_keys=True) for item in items}
    if len(table) != len(items):
        raise AdapterError("baseline prompts are not unique per item")

    def _adapter(prompt: str) -> str:
        if prompt not in table:
            raise AdapterError("baseline has no answer for this prompt")
        return table[prompt]
    return _adapter


def baseline_adapter(
    spec: str, items: list[dict[str, Any]], store: FactStore, *, modal_path: Path | None = None,
) -> Callable[[str], str]:
    """``gold:`` / ``random:<seed>`` / ``modal:`` / ``template:`` over a specific item set."""
    provider, _, argument = spec.partition(":")
    if provider not in BASELINE_TRACK:
        raise AdapterError(f"{spec!r} is not a baseline spec (gold:, random:<seed>, modal:, template:)")
    track = BASELINE_TRACK[provider]
    wrong = sorted({item["track"] for item in items} - {track})
    if wrong:
        raise AdapterError(f"{provider}: is a {track}-track baseline but the item set also holds "
                           f"{', '.join(wrong)} items; pass --track {track}")
    if provider == "gold":
        return _table(items, lambda item: gold_answer(item, store))
    if provider == "random":
        try:
            rng = random.Random(int(argument))
        except ValueError:
            raise AdapterError(f"random baseline needs an integer seed: random:<seed>, got {spec!r}") from None
        return _table(items, lambda item: random_answer(item, store, rng))
    if provider == "modal":
        if modal_path is None or not Path(modal_path).exists():
            raise AdapterError(f"modal baseline needs modal.json beside the items (looked at {modal_path})")
        modal = json.loads(Path(modal_path).read_text())
        return _table(items, lambda item: modal_answer(item, store, modal))
    return _table(items, template_answer)
