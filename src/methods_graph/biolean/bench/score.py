"""Per-item scoring for both tracks, and the aggregates with their denominators.

The kernel is the only judge: every parsed reply is ``elaborate`` + ``check`` over
``MaskedFactStore(store, item.hidden)`` and this module reads the verdict. It never trusts
the reply's own ``goal``: ``goal_match`` compares the elaborated root conclusion to the
item's proposition, so a model that rewrites the claim and proves the rewrite is counted
as ``goal_rewritten``, not as a hit.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from methods_graph.biolean.bench.render import parse_reply
from methods_graph.biolean.elaborate import elaborate
from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import FactStore, MaskedFactStore

UNPARSED = "UNPARSED"
Resolver = Callable[[str], "str | None"]

# The row vocabulary every row carries, whatever its track. `model` and `items_manifest`
# are attached by run.py; score_row and failure_row emit the rest.
COMMON_KEYS = frozenset({
    "item", "track", "model", "items_manifest", "goal", "hidden", "hidden_classes",
    "raw", "parsed", "error", "render_error", "error_codes", "goal_match"})
PROVE_KEYS = frozenset({"gold_depth", "accepted", "goal_rewritten", "hit", "hit_with_sorry",
                        "sorry_count", "unused_sorries", "depth"})
HYPOTHESIZE_KEYS = frozenset({"format_ok", "inputs_nonempty", "method", "method_normalized",
                              "method_resolves"})
DEPTH_BUCKETS = ("1", "2", "3", "4+")
HYPOTHESIZE_NOTE = (
    "format compliance only: GAF records PMIDs and evidence codes, never datasets or method "
    "ids, so no data-grounded target exists for provenance and a constant reply saturates "
    "every rate; the track's knowledge measure arrives with Phase B")


# ---------------------------------------------------------------------------
# one row
# ---------------------------------------------------------------------------

def _base(item: dict[str, Any], raw: Any, parsed: bool) -> dict[str, Any]:
    return {"item": item["id"], "track": item["track"], "goal": item["goal"],
            "hidden": list(item["hidden"]),
            "hidden_classes": list(item.get("hidden_classes") or []),
            "raw": raw, "parsed": parsed, "error": None, "render_error": None}


def _root_step(canonical: dict[str, Any]) -> dict[str, Any] | None:
    """The step named by ``root``, or ``None`` when ``root`` names no step."""
    steps, root = canonical.get("steps"), canonical.get("root")
    if not isinstance(steps, list) or not isinstance(root, str):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("id") == root:
            return step
    return None


def _goal_match(root: dict[str, Any] | None, target: Prop) -> bool | None:
    if root is None:
        return None
    return Prop.from_dict(root.get("conclusion")) == target


def _checked(item: dict[str, Any], reply: dict[str, Any], store: FactStore):
    """``(canonical, verdict, root step, target)`` for a parsed reply over the item's masked store."""
    target = Prop.from_dict(item["goal"])
    assert target is not None, item["id"]
    masked = MaskedFactStore(store, frozenset(item["hidden"]))
    canonical, _report = elaborate(reply, masked)
    verdict = check(canonical, masked)
    return canonical, verdict, _root_step(canonical), target


def _codes(verdict: dict[str, Any]) -> list[str]:
    return sorted(e["code"] for e in verdict["errors"])


def score_prove(item: dict[str, Any], raw: Any, store: FactStore) -> dict[str, Any]:
    reply = parse_reply(raw)
    row = {**_base(item, raw, reply is not None), "gold_depth": item.get("gold_depth")}
    if reply is None:
        row.update(accepted=False, goal_match=None, goal_rewritten=None, hit=False,
                   hit_with_sorry=False, sorry_count=None, unused_sorries=None, depth=None,
                   error_codes=[UNPARSED])
        return row
    canonical, verdict, root, target = _checked(item, reply, store)
    accepted = verdict["verdict"] == "ACCEPTED"
    goal_match = _goal_match(root, target)
    sorry_count = verdict["sorry_count"]
    row.update(
        accepted=accepted,
        goal_match=goal_match,
        goal_rewritten=Prop.from_dict(canonical.get("goal")) != target,
        hit=accepted and goal_match is True and sorry_count == 0,
        hit_with_sorry=accepted and goal_match is True and sorry_count > 0,
        sorry_count=sorry_count,
        unused_sorries=verdict["unused_sorries"],
        # Propagation steps on the used chain: every step has an id when accepted, so the
        # used chain is steps_checked minus unused_steps; minus one for the axiom.
        depth=(verdict["steps_checked"] - len(verdict["unused_steps"]) - 1) if accepted else None,
        error_codes=_codes(verdict),
    )
    return row


def score_hypothesize(
    item: dict[str, Any], raw: Any, store: FactStore, resolve: Resolver | None,
) -> dict[str, Any]:
    reply = parse_reply(raw)
    row = _base(item, raw, reply is not None)
    if reply is None:
        row.update(format_ok=False, goal_match=None, inputs_nonempty=None, method=None,
                   method_normalized=None, method_resolves=None, error_codes=[UNPARSED])
        return row
    _canonical, verdict, root, target = _checked(item, reply, store)
    accepted = verdict["verdict"] == "ACCEPTED"
    is_sorry = root is not None and root.get("rule") == "sorry"
    prov = root.get("provenance") if is_sorry else None
    prov = prov if isinstance(prov, dict) else {}
    inputs = prov.get("inputs")
    method = prov.get("method") if isinstance(prov.get("method"), str) else None
    normalized = resolve(method) if resolve is not None and method is not None else None
    row.update(
        format_ok=accepted and is_sorry,
        goal_match=_goal_match(root, target),
        inputs_nonempty=(isinstance(inputs, list) and len(inputs) > 0) if is_sorry else None,
        method=method,
        method_normalized=normalized,
        # None (undefined) without a graph or without a method string; never False by default.
        method_resolves=None if resolve is None or method is None else normalized is not None,
        error_codes=_codes(verdict),
    )
    return row


def score_row(
    item: dict[str, Any], raw: Any, store: FactStore, *, resolve: Resolver | None = None,
) -> dict[str, Any]:
    track = item["track"]
    if track == "prove":
        return score_prove(item, raw, store)
    if track == "hypothesize":
        return score_hypothesize(item, raw, store, resolve)
    raise ValueError(f"unknown track: {track!r}")


def failure_row(item: dict[str, Any], *, error: str, render_error: str | None) -> dict[str, Any]:
    """A row for an item that never produced a scorable answer: the track's key set, ``None``
    where a score would be. ``.get`` throughout — a render failure can be a malformed item."""
    track = item.get("track")
    keys = (PROVE_KEYS if track == "prove" else HYPOTHESIZE_KEYS if track == "hypothesize"
            else PROVE_KEYS | HYPOTHESIZE_KEYS)
    row: dict[str, Any] = {
        "item": item.get("id"), "track": track, "goal": item.get("goal"),
        "hidden": list(item.get("hidden") or []),
        "hidden_classes": list(item.get("hidden_classes") or []),
        "raw": None, "parsed": False, "error": error, "render_error": render_error,
        "error_codes": None, "goal_match": None, **{key: None for key in keys}}
    if "gold_depth" in row:
        row["gold_depth"] = item.get("gold_depth")
    return row


# ---------------------------------------------------------------------------
# aggregates
# ---------------------------------------------------------------------------

def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: list[Any]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _histograms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``error_items`` (rows whose codes contain the code) and ``error_occurrences`` (error
    records carrying it), each with its denominator. Items is the headline: it is invariant
    to derivation length."""
    items: dict[str, int] = {}
    occurrences: dict[str, int] = {}
    for row in rows:
        codes = row["error_codes"] or []
        for code in set(codes):
            items[code] = items.get(code, 0) + 1
        for code in codes:
            occurrences[code] = occurrences.get(code, 0) + 1
    return {"error_items": dict(sorted(items.items())), "error_items_denominator": len(rows),
            "error_occurrences": dict(sorted(occurrences.items())),
            "error_occurrences_denominator": sum(occurrences.values())}


def _depth_bucket(gold_depth: Any) -> str | None:
    if not isinstance(gold_depth, int):
        return None
    return str(gold_depth) if gold_depth in (1, 2, 3) else "4+"


def _summarize_prove(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hits = [r for r in rows if r["hit"]]
    by_class: dict[str, Any] = {}
    for cls in sorted({c for r in rows for c in r["hidden_classes"]}):
        sub = [r for r in rows if cls in r["hidden_classes"]]
        by_class[cls] = {"n": len(sub), "hit_rate": _rate(sum(1 for r in sub if r["hit"]), len(sub))}
    by_depth: dict[str, Any] = {}
    for bucket in DEPTH_BUCKETS:
        sub = [r for r in rows if _depth_bucket(r.get("gold_depth")) == bucket]
        by_depth[bucket] = {"n": len(sub), "hit_rate": _rate(sum(1 for r in sub if r["hit"]), len(sub))}
    return {
        "n": len(rows), "n_hits": len(hits), "hit_rate": _rate(len(hits), len(rows)),
        "hit_with_sorry_rate": _rate(sum(1 for r in rows if r["hit_with_sorry"]), len(rows)),
        "acceptance_rate": _rate(sum(1 for r in rows if r["accepted"]), len(rows)),
        "n_goal_rewritten": sum(1 for r in rows if r["goal_rewritten"]),
        "mean_depth": _mean([r["depth"] for r in hits]),
        "by_evidence_class": by_class,
        "by_gold_depth": by_depth,
        **_histograms(rows),
    }


def _rate_over_defined(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    defined = [r for r in rows if r[key] is not None]
    return {"n": len(defined), "rate": _rate(sum(1 for r in defined if r[key]), len(defined))}


def _summarize_hypothesize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unresolved: dict[str, int] = {}
    for r in rows:
        if r["method_resolves"] is False:
            unresolved[r["method"]] = unresolved.get(r["method"], 0) + 1
    return {
        "note": HYPOTHESIZE_NOTE,
        "n": len(rows),
        "format_ok": _rate_over_defined(rows, "format_ok"),
        "goal_match": _rate_over_defined(rows, "goal_match"),
        "inputs_nonempty": _rate_over_defined(rows, "inputs_nonempty"),
        "method_resolves": _rate_over_defined(rows, "method_resolves"),
        "n_method_resolves_none": sum(1 for r in rows if r["method_resolves"] is None),
        "method_unresolved": [[name, n] for name, n in sorted(unresolved.items())],
        **_histograms(rows),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Two tracks, never pooled. ``n_rows == n_errors + n_unparsed + n_checked`` exactly."""
    errors = [r for r in rows if r["error"] is not None]
    scored = [r for r in rows if r["error"] is None]
    unparsed = [r for r in scored if not r["parsed"]]
    manifests = {json.dumps(r.get("items_manifest"), sort_keys=True) for r in rows}
    manifest = rows[0].get("items_manifest") if len(manifests) == 1 else None
    manifest = manifest if isinstance(manifest, dict) else {}
    return {
        "n_rows": len(rows),
        "n_errors": len(errors),
        "n_render_errors": sum(1 for r in rows if r.get("render_error")),
        "n_unparsed": len(unparsed),
        "n_checked": len(scored) - len(unparsed),
        "release": manifest.get("release"),
        "since": manifest.get("since"),
        "prove": _summarize_prove([r for r in scored if r["track"] == "prove"]),
        "hypothesize": _summarize_hypothesize([r for r in scored if r["track"] == "hypothesize"]),
    }
