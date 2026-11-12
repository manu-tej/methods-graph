"""Identifier normalization before the kernel. Every rewrite is a lookup and is reported.

Positions touched: goal.{subject,term,taxon}, steps[*].conclusion.{subject,term,taxon},
steps[*].edge[0], steps[*].edge[1]. Nothing else in the document is an identifier.
Obsolete terms are never rewritten: the kernel's OBSOLETE_TERM carries the replacement.
"""
from __future__ import annotations

import copy
from typing import Any

from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import TAXON_RE, normalize_taxon
from methods_graph.biolean.store import FactStore

SYMBOL_RESOLVED = "SYMBOL_RESOLVED"
SYMBOL_AMBIGUOUS = "SYMBOL_AMBIGUOUS"
ALT_ID_RESOLVED = "ALT_ID_RESOLVED"
TAXON_NORMALIZED = "TAXON_NORMALIZED"


def _record(report: list[dict[str, Any]], path: str, kind: str, before: str, after: str | None) -> None:
    report.append({"path": path, "kind": kind, "before": before, "after": after})


def _subject(container: Any, key: Any, path: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or store.subject_exists(value):
        return
    candidates = store.subject_for_symbol(value)
    if len(candidates) == 1:
        container[key] = candidates[0]
        _record(report, path, SYMBOL_RESOLVED, value, candidates[0])
    elif len(candidates) > 1:
        _record(report, path, SYMBOL_AMBIGUOUS, value, None)


def _term(container: Any, key: Any, path: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or store.term(value) is not None:
        return
    primary = store.primary_id(value)
    if primary is not None:
        container[key] = primary
        _record(report, path, ALT_ID_RESOLVED, value, primary)


def _taxon(container: Any, key: Any, path: str, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or TAXON_RE.match(value):
        return
    normalized = normalize_taxon(value)
    if normalized is not None:
        container[key] = normalized
        _record(report, path, TAXON_NORMALIZED, value, normalized)


def _prop_positions(d: Any, prefix: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    if not isinstance(d, dict):
        return
    if "subject" in d:
        _subject(d, "subject", f"{prefix}/subject", store, report)
    if "term" in d:
        _term(d, "term", f"{prefix}/term", store, report)
    if "taxon" in d:
        _taxon(d, "taxon", f"{prefix}/taxon", report)


def elaborate(derivation: Any, store: FactStore) -> tuple[Any, list[dict[str, Any]]]:
    """A deep copy with identifiers canonicalized, plus the sorted rewrite report."""
    out = copy.deepcopy(derivation)
    report: list[dict[str, Any]] = []
    if not isinstance(out, dict):
        return out, report
    _prop_positions(out.get("goal"), "goal", store, report)
    steps = out.get("steps")
    if isinstance(steps, list):
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            _prop_positions(step.get("conclusion"), f"steps/{i}/conclusion", store, report)
            edge = step.get("edge")
            if isinstance(edge, list):
                for j in range(min(len(edge), 2)):
                    _term(edge, j, f"steps/{i}/edge/{j}", store, report)
    report.sort(key=lambda e: e["path"])
    return out, report


def elaborate_and_check(derivation: Any, store: FactStore) -> dict[str, Any]:
    """The CLI's path: elaborate, check, attach the rewrite report to the verdict."""
    canonical, report = elaborate(derivation, store)
    verdict = check(canonical, store)
    verdict["elaboration"] = report
    return verdict
