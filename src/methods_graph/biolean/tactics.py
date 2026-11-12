"""Untrusted convenience over the kernel: what can be proved, and how.

``goals_for`` enumerates every well-typed proposition derivable for a subject, ``applicable``
lists the rule applications that would conclude a proposition now, and ``prove`` is the
mechanical breadth-first prover (the gold baseline). Every derivation ``prove`` emits is
accepted by the kernel; a test pins that.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from methods_graph.biolean.kernel import propagating_children, propagating_parents
from methods_graph.biolean.props import NAMESPACE_ASPECT, QUALIFIER_ASPECT, Prop
from methods_graph.biolean.store import FactStore

_REPORT_KEYS = ("skipped_negated", "skipped_obsolete", "skipped_unknown_term",
                "skipped_aspect_mismatch")


def _aspect_legal(namespace: str, qualifier: str) -> bool:
    """Whether ``qualifier`` is legal for a term of this namespace (a loaded pair can be
    skewed by release, so this can be false even for a row the store faithfully kept)."""
    return NAMESPACE_ASPECT.get(namespace) == QUALIFIER_ASPECT.get(qualifier)


def _live_parents(term_id: str, store: FactStore) -> list[tuple[str, str]]:
    """(parent, relation) over propagating relations within namespace, sorted by parent id."""
    return list(propagating_parents(term_id, store))


def _starts(subject: str, qualifier: str, taxon: str, store: FactStore) -> list[str]:
    """Live, non-negated direct annotation terms of the subject under (qualifier, taxon)."""
    terms: set[str] = set()
    for a in store.annotations(subject):
        if a.negated or a.qualifier != qualifier or a.taxon != taxon:
            continue
        t = store.term(a.term)
        if t is None or t.obsolete or not _aspect_legal(t.namespace, a.qualifier):
            continue
        terms.add(a.term)
    return sorted(terms)


def goals_for(
    subject: str, store: FactStore, *, aspect: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    depth: dict[tuple[str, str, str], int] = {}
    direct: set[tuple[str, str, str]] = set()
    for a in store.annotations(subject):
        if a.negated:
            report["skipped_negated"] += 1
            continue
        t = store.term(a.term)
        if t is None:
            report["skipped_unknown_term"] += 1
            continue
        if t.obsolete:
            report["skipped_obsolete"] += 1
            continue
        if not _aspect_legal(t.namespace, a.qualifier):
            report["skipped_aspect_mismatch"] += 1
            continue
        if aspect is not None and NAMESPACE_ASPECT.get(t.namespace) != aspect:
            continue
        key = (a.qualifier, a.term, a.taxon)
        direct.add(key)
        depth[key] = 0
        queue: deque[tuple[str, int]] = deque([(a.term, 0)])
        while queue:
            cur, d = queue.popleft()
            for parent, _relation in _live_parents(cur, store):
                k = (a.qualifier, parent, a.taxon)
                if k in depth and depth[k] <= d + 1:
                    continue
                depth[k] = d + 1
                queue.append((parent, d + 1))
    goals = [
        {"prop": Prop(subject, q, t, tax, False).to_dict(), "direct": (q, t, tax) in direct,
         "depth": depth[(q, t, tax)]}
        for (q, t, tax) in sorted(depth, key=lambda k: (k[1], k[0], k[2]))
    ]
    return goals, report


def applicable(prop: Prop, store: FactStore) -> list[dict[str, Any]]:
    """Rule applications that would conclude ``prop`` against this store, sorted."""
    if prop.negated:
        return []
    target = store.term(prop.term)
    if target is None or target.obsolete:
        return []            # the kernel refuses every step concluding this (UNKNOWN_TERM / OBSOLETE_TERM)
    if not _aspect_legal(target.namespace, prop.qualifier):
        return []            # ... as QUALIFIER_ASPECT_MISMATCH
    frags: list[dict[str, Any]] = []
    if store.matching(prop):
        frags.append({"rule": "axiom", "conclusion": prop.to_dict()})
    derivable = {(g["prop"]["term"]) for g in goals_for(prop.subject, store)[0]
                 if g["prop"]["qualifier"] == prop.qualifier and g["prop"]["taxon"] == prop.taxon}
    for child, relation in propagating_children(prop.term, store):
        if child in derivable:
            frags.append({"rule": relation, "edge": [child, prop.term], "conclusion": prop.to_dict()})
    return sorted(frags, key=lambda f: (f["rule"], f.get("edge", [])))


def prove(prop: Prop, store: FactStore) -> dict[str, Any] | None:
    """Shortest derivation of ``prop`` by multi-source breadth-first search, or ``None``.

    Starts simultaneously from every direct annotation of the subject under the same
    qualifier and taxon, expands parents in sorted term-id order, and reconstructs the first
    path that reaches the target. Ties are therefore broken by sorted term id.
    """
    if prop.negated:
        return None
    target = store.term(prop.term)
    if target is None or target.obsolete:
        return None
    starts = _starts(prop.subject, prop.qualifier, prop.taxon, store)
    if not starts:
        return None
    came_from: dict[str, tuple[str, str] | None] = {s: None for s in starts}
    queue: deque[str] = deque(starts)
    found: str | None = prop.term if prop.term in came_from else None
    while queue and found is None:
        cur = queue.popleft()
        for parent, relation in _live_parents(cur, store):
            if parent in came_from:
                continue
            came_from[parent] = (cur, relation)
            if parent == prop.term:
                found = parent
                break
            queue.append(parent)
    if found is None:
        return None
    chain: list[tuple[str, str, str]] = []     # (child, relation, parent), root-most last
    node = found
    while came_from[node] is not None:
        child, relation = came_from[node]        # type: ignore[misc]
        chain.append((child, relation, node))
        node = child
    chain.reverse()
    start = node
    steps: list[dict[str, Any]] = [{
        "id": "s1", "rule": "axiom",
        "conclusion": Prop(prop.subject, prop.qualifier, start, prop.taxon, False).to_dict(),
    }]
    for i, (child, relation, parent) in enumerate(chain, start=2):
        steps.append({
            "id": f"s{i}", "rule": relation, "premises": [f"s{i - 1}"], "edge": [child, parent],
            "conclusion": Prop(prop.subject, prop.qualifier, parent, prop.taxon, False).to_dict(),
        })
    return {"biolean": "0.1", "goal": prop.to_dict(), "steps": steps, "root": steps[-1]["id"]}
