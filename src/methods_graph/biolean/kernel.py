"""The trusted checker.

Imports ``props``, ``errors`` and the ``FactStore`` protocol and nothing else in the
package. No I/O. ``check`` validates structure, resolves identifiers, applies one rule per
step, checks the root, and assembles a verdict whose every collection is sorted.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from methods_graph.biolean.errors import Code, Error
from methods_graph.biolean.props import (
    NAMESPACE_ASPECT, PROPAGATING_RELATIONS, QUALIFIER_ASPECT, TAXON_RE, Annotation, Prop)
from methods_graph.biolean.store import FactStore

RULES: tuple[str, ...] = ("axiom", "is_a", "part_of", "sorry")
ARITY: dict[str, int] = {"axiom": 0, "sorry": 0, "is_a": 1, "part_of": 1}
_COMMON_KEYS = frozenset({"id", "rule", "conclusion", "premises"})
_RULE_KEYS: dict[str, frozenset[str]] = {
    "axiom": frozenset({"code", "reference"}),
    "is_a": frozenset({"edge"}),
    "part_of": frozenset({"edge"}),
    "sorry": frozenset({"provenance"}),
}
_PROVENANCE_TYPES: dict[str, type] = {
    "method": str, "inputs": list, "parameters": dict, "claim": str}
# Codes that mean an identifier did not resolve; a step carrying one gets no rule check.
_RESOLUTION_FAILURES = frozenset({
    Code.MALFORMED, Code.UNKNOWN_SUBJECT, Code.UNKNOWN_TERM, Code.OBSOLETE_TERM,
    Code.ALT_ID_IN_KERNEL, Code.UNKNOWN_QUALIFIER})


@dataclass
class _Step:
    index: int
    raw: Any
    id: str | None = None
    rule: str | None = None
    malformed: bool = False
    prop: Prop | None = None
    resolved: bool = False           # stated conclusion passed identifier resolution
    premises: list[str] = field(default_factory=list)
    premises_malformed: bool = False
    arity_ok: bool = False
    edge: tuple[str, str] | None = None
    edge_resolved: bool = False
    errors: list[Error] = field(default_factory=list)
    axioms: tuple[Annotation, ...] = ()
    premise_failed: bool = False

    def err(self, code: str, message: str, **kw: Any) -> None:
        step = self.id if self.id is not None else f"#{self.index}"
        self.errors.append(Error(code=code, message=message, step=step, position=self.index, **kw))


# ---------------------------------------------------------------------------
# closure helpers (also used by tactics)
# ---------------------------------------------------------------------------

def propagating_parents(term_id: str, store: FactStore) -> tuple[tuple[str, str], ...]:
    """``(parent, relation)`` one propagation step above ``term_id``.

    The one definition of "an annotation lifts over this edge": relation in
    ``PROPAGATING_RELATIONS``, parent known, live, and in the child's namespace. Sorted by
    ``(parent, relation)``. Empty for an unknown term. ``tactics`` and the benchmark import
    this rather than restating the filters.
    """
    start = store.term(term_id)
    if start is None:
        return ()
    out: list[tuple[str, str]] = []
    for e in store.parents(term_id):
        if e.relation not in PROPAGATING_RELATIONS:
            continue
        parent = store.term(e.parent)
        if parent is None or parent.obsolete or parent.namespace != start.namespace:
            continue
        out.append((e.parent, e.relation))
    return tuple(sorted(out))


def propagating_children(term_id: str, store: FactStore) -> tuple[tuple[str, str], ...]:
    """``(child, relation)`` one propagation step below ``term_id``: the exact dual."""
    start = store.term(term_id)
    if start is None:
        return ()
    out: list[tuple[str, str]] = []
    for e in store.children(term_id):
        if e.relation not in PROPAGATING_RELATIONS:
            continue
        child = store.term(e.child)
        if child is None or child.obsolete or child.namespace != start.namespace:
            continue
        out.append((e.child, e.relation))
    return tuple(sorted(out))


def _closure(term_id: str, store: FactStore, step) -> tuple[str, ...]:
    seen: set[str] = set()
    queue: deque[str] = deque([term_id])
    while queue:
        cur = queue.popleft()
        for nxt, _relation in step(cur, store):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return tuple(sorted(seen))


def ancestors(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict ancestors over is_a/part_of, same namespace, live terms only, sorted."""
    return _closure(term_id, store, propagating_parents)


def descendants(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict descendants: the exact dual of :func:`ancestors`, walked with children()."""
    return _closure(term_id, store, propagating_children)


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

def _parse_step(index: int, raw: Any) -> _Step:
    st = _Step(index=index, raw=raw)
    if not isinstance(raw, dict):
        st.errors.append(Error(Code.MALFORMED, f"step {index} must be an object",
                               step=f"#{index}", position=index))
        st.malformed = True
        return st
    sid = raw.get("id")
    st.id = sid if isinstance(sid, str) else None
    if st.id is None:
        st.err(Code.MALFORMED, f"step {index} needs a string id")
        st.malformed = True
    rule = raw.get("rule")
    if not isinstance(rule, str):
        st.err(Code.MALFORMED, "rule must be a string")
        st.malformed = True
        return st
    st.rule = rule
    if rule not in RULES:
        st.err(Code.UNKNOWN_RULE, f"unknown rule {rule!r}", expected=list(RULES), actual=rule)
        st.malformed = True
        return st
    unknown = sorted(set(raw) - _COMMON_KEYS - _RULE_KEYS[rule])
    if unknown:
        st.err(Code.MALFORMED, f"unknown keys for rule {rule}: {', '.join(unknown)}",
               actual=unknown)
        st.malformed = True
    premises = raw.get("premises", [])
    if isinstance(premises, list) and all(isinstance(p, str) for p in premises):
        st.premises = list(premises)
    else:
        st.err(Code.MALFORMED, "premises must be a list of step ids")
        st.malformed = True
        st.premises_malformed = True
    if rule in ("is_a", "part_of") and "premises" not in raw:
        st.err(Code.MALFORMED, f"{rule} step needs premises")
        st.malformed = True
        st.premises_malformed = True
    if "conclusion" not in raw:
        st.err(Code.MALFORMED, "step needs a conclusion")
        st.malformed = True
    else:
        st.prop = Prop.from_dict(raw["conclusion"])
        if st.prop is None:
            st.err(Code.MALFORMED, "conclusion must have exactly subject, qualifier, term, "
                                   "taxon (strings) and negated (bool)")
            st.malformed = True
    if rule in ("is_a", "part_of"):
        edge = raw.get("edge")
        if isinstance(edge, list) and len(edge) == 2 and all(isinstance(t, str) for t in edge):
            st.edge = (edge[0], edge[1])
        else:
            st.err(Code.MALFORMED, f"{rule} step needs edge: [child, parent]")
            st.malformed = True
    if rule == "axiom":
        for key in ("code", "reference"):
            if key in raw and not isinstance(raw[key], str):
                st.err(Code.MALFORMED, f"{key} must be a string")
                st.malformed = True
    return st


def _check_refs_and_arity(st: _Step, index_of: dict[str, int]) -> None:
    for p in st.premises:
        if p not in index_of:
            st.err(Code.UNKNOWN_STEP_REF, f"premise {p!r} names no step", actual=p)
        elif index_of[p] >= st.index:
            st.err(Code.STEP_ORDER, f"premise {p!r} must come before step {st.id!r}", actual=p)
    if st.rule in ARITY and not st.premises_malformed:
        expected = ARITY[st.rule]
        if len(st.premises) != expected:
            st.err(Code.PREMISE_ARITY,
                   f"{st.rule} consumes {expected} premise(s), got {len(st.premises)}",
                   expected=expected, actual=len(st.premises))
        else:
            st.arity_ok = True


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------

def check_term(term_id: str, store: FactStore, step: str | None, position: int = -1) -> list[Error]:
    """Live primary id: []. Otherwise exactly one of ALT_ID_IN_KERNEL, UNKNOWN_TERM, OBSOLETE_TERM.
    Public because the ledger's append check reuses it (spec §2 steps 3-4)."""
    term = store.term(term_id)
    if term is None:
        primary = store.primary_id(term_id)
        if primary is not None:
            return [Error(Code.ALT_ID_IN_KERNEL, f"{term_id} is an alt_id of {primary}",
                          step=step, position=position, expected=primary, actual=term_id)]
        return [Error(Code.UNKNOWN_TERM, f"unknown term {term_id}", step=step, position=position,
                      actual=term_id)]
    if term.obsolete:
        return [Error(Code.OBSOLETE_TERM, f"{term_id} is obsolete", step=step, position=position,
                      actual=term_id,
                      expected={"replaced_by": list(term.replaced_by),
                                "consider": list(term.consider)})]
    return []


def check_qualifier_aspect(
    qualifier: str, term_id: str, store: FactStore, step: str | None = None, position: int = -1,
) -> list[Error]:
    """UNKNOWN_QUALIFIER, or QUALIFIER_ASPECT_MISMATCH when the term is live and its namespace's
    aspect differs from the qualifier's. Nothing when the term is unknown or obsolete: the
    term check reports those. Extracted from ``_check_prop`` for the ledger (spec §2 step 4)."""
    if qualifier not in QUALIFIER_ASPECT:
        return [Error(Code.UNKNOWN_QUALIFIER, f"unknown qualifier {qualifier!r}",
                      step=step, position=position, expected=sorted(QUALIFIER_ASPECT),
                      actual=qualifier)]
    term = store.term(term_id)
    if term is not None and not term.obsolete:
        aspect = NAMESPACE_ASPECT.get(term.namespace)
        wanted = QUALIFIER_ASPECT[qualifier]
        if aspect != wanted:
            return [Error(
                Code.QUALIFIER_ASPECT_MISMATCH,
                f"{qualifier} is a {wanted}-aspect qualifier; {term_id} is {term.namespace}",
                step=step, position=position, expected=wanted, actual=aspect)]
    return []


def _check_prop(prop: Prop, store: FactStore, step: str | None, position: int = -1) -> list[Error]:
    errs: list[Error] = []
    if not store.subject_exists(prop.subject):
        errs.append(Error(Code.UNKNOWN_SUBJECT, f"unknown subject {prop.subject}", step=step,
                          position=position, actual=prop.subject,
                          expected=list(store.subject_for_symbol(prop.subject))))
    errs.extend(check_term(prop.term, store, step, position))
    if not TAXON_RE.match(prop.taxon):
        errs.append(Error(Code.MALFORMED, f"taxon must be NCBITaxon:<digits>, got {prop.taxon!r}",
                          step=step, position=position, actual=prop.taxon))
    errs.extend(check_qualifier_aspect(prop.qualifier, prop.term, store, step, position))
    return errs


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def _fragment(prop: Prop) -> dict[str, Any]:
    return {"rule": "axiom", "conclusion": prop.to_dict()}


def _axiom_suggestions(prop: Prop, store: FactStore) -> tuple[dict[str, Any], ...]:
    """Well-formed axiom fragments near a missing one: other qualifier at the term, same
    qualifier at a descendant, same proposition under another taxon."""
    out: dict[str, dict[str, Any]] = {}
    for a in store.annotations(prop.subject):
        if a.negated:
            continue
        same_term_other_q = a.term == prop.term and a.qualifier != prop.qualifier and a.taxon == prop.taxon
        other_taxon = a.term == prop.term and a.qualifier == prop.qualifier and a.taxon != prop.taxon
        below = (a.qualifier == prop.qualifier and a.taxon == prop.taxon and a.term != prop.term
                 and prop.term in ancestors(a.term, store))
        if same_term_other_q or other_taxon or below:
            frag_prop = Prop(a.subject, a.qualifier, a.term, a.taxon, False)
            if _check_prop(frag_prop, store, None) != []:
                continue
            frag = _fragment(frag_prop)
            out.setdefault(json.dumps(frag, sort_keys=True), frag)
    return tuple(out[k] for k in sorted(out))


def _apply_axiom(st: _Step, store: FactStore) -> None:
    assert st.prop is not None
    rows = list(store.matching(st.prop))
    code = st.raw.get("code")
    reference = st.raw.get("reference")
    if code is not None:
        rows = [r for r in rows if r.code == code]
    if reference is not None:
        rows = [r for r in rows if reference in r.references]
    if rows:
        st.axioms = tuple(sorted(rows, key=lambda a: a.id))
        return
    filters = {k: v for k, v in (("code", code), ("reference", reference)) if v is not None}
    st.err(Code.AXIOM_NOT_FOUND,
           "no annotation matches" + (f" with {filters}" if filters else ""),
           expected={**st.prop.to_dict(), **filters},
           suggestions=_axiom_suggestions(st.prop, store))


def _apply_propagation(st: _Step, premise: _Step | None, store: FactStore) -> None:
    assert st.prop is not None and st.edge is not None and st.rule is not None
    relation = st.rule
    child, parent = st.edge
    if st.edge_resolved:
        edges = store.parents(child)
        if not any(e.relation == relation and e.parent == parent for e in edges):
            suggestions = tuple(
                {"rule": e.relation, "edge": [child, parent]}
                for e in edges if e.parent == parent and e.relation in PROPAGATING_RELATIONS)
            st.err(Code.EDGE_NOT_FOUND, f"no {relation} edge {child} -> {parent}",
                   expected={"child": child, "relation": relation, "parent": parent},
                   actual={"parents_of_child": [[e.relation, e.parent] for e in edges]},
                   suggestions=suggestions)
        child_term, parent_term = store.term(child), store.term(parent)
        if child_term is not None and parent_term is not None \
                and child_term.namespace != parent_term.namespace:
            st.err(Code.NAMESPACE_CROSSED,
                   f"{child} is {child_term.namespace}, {parent} is {parent_term.namespace}",
                   expected=child_term.namespace, actual=parent_term.namespace)
    if premise is None or premise.prop is None:
        return
    pp = premise.prop
    if pp.term != child:
        st.err(Code.PREMISE_MISMATCH, f"premise concludes {pp.term}; edge starts at {child}",
               expected=child, actual=pp.term)
    if pp.negated:
        st.err(Code.NEGATED_PREMISE, "a NOT annotation does not propagate upward")
    computed = Prop(pp.subject, pp.qualifier, parent, pp.taxon, False)
    if computed != st.prop:
        st.err(Code.CONCLUSION_MISMATCH, "stated conclusion differs from the rule's conclusion",
               expected=computed.to_dict(), actual=st.prop.to_dict())


def _apply_sorry(st: _Step) -> None:
    assert st.prop is not None
    prov = st.raw.get("provenance")
    well_formed = (
        isinstance(prov, dict)
        and set(prov) == set(_PROVENANCE_TYPES)
        and all(type(prov[k]) is t for k, t in _PROVENANCE_TYPES.items())
        and bool(prov["inputs"])
        and all(isinstance(i, str) for i in prov["inputs"])
    )
    if not well_formed:
        st.err(Code.SORRY_MALFORMED,
               "provenance needs method (str), inputs (non-empty list of str), "
               "parameters (object), claim (str)",
               expected=sorted(_PROVENANCE_TYPES))
    if st.prop.negated:
        st.err(Code.SORRY_NEGATED, "a sorry step cannot conclude a NOT proposition")


# ---------------------------------------------------------------------------
# conflicts (verdict-neutral; computed after errors, never adds one)
# ---------------------------------------------------------------------------

def _conflicts(steps: list[_Step], index_of: dict[str, int], store: FactStore) -> list[dict[str, Any]]:
    """Store annotations contradicting any step's conclusion over the propagation closure.

    A positive conclusion at t is contradicted by a NOT row at t or at any is_a/part_of
    ancestor of t (within namespace); a negated conclusion at t by a positive row at t or at
    any descendant. Each annotation is listed once, against the earliest step it contradicts.
    Verdict-neutral: this is the defeasibility seam.
    """
    found: dict[str, dict[str, Any]] = {}
    for st in steps:
        p = st.prop
        if p is None or st.id is None:
            continue
        if not p.negated:
            candidates = [(p.term, "term")] + [(u, "ancestor") for u in ancestors(p.term, store)]
            flag = True
        else:
            candidates = [(p.term, "term")] + [(d, "descendant") for d in descendants(p.term, store)]
            flag = False
        for via, at in candidates:
            for a in store.matching(Prop(p.subject, p.qualifier, via, p.taxon, flag)):
                found.setdefault(a.id, {"step": st.id, "annotation": a.id, "negated": a.negated,
                                        "code": a.code, "at": at, "via": via})
    return sorted(found.values(), key=lambda c: (index_of.get(c["step"], -1), c["annotation"]))


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def check(derivation: Any, store: FactStore) -> dict[str, Any]:
    top: list[Error] = []
    if not (isinstance(derivation, dict) and isinstance(derivation.get("steps"), list)
            and "goal" in derivation and isinstance(derivation.get("root"), str)):
        top.append(Error(Code.MALFORMED,
                         "derivation must be an object with goal, steps (list) and root (string)"))
        return _assemble(None, [], top, root_id=None, index_of={}, store=store)

    goal = Prop.from_dict(derivation["goal"])
    if goal is None:
        top.append(Error(Code.MALFORMED, "goal must have exactly subject, qualifier, term, "
                                         "taxon (strings) and negated (bool)"))
    else:
        top.extend(_check_prop(goal, store, step=None))

    steps = [_parse_step(i, raw) for i, raw in enumerate(derivation["steps"])]
    index_of: dict[str, int] = {}
    for st in steps:
        if st.id is None:
            continue
        if st.id in index_of:
            st.err(Code.DUPLICATE_STEP, f"step id {st.id!r} is used more than once", actual=st.id)
        else:
            index_of[st.id] = st.index

    for st in steps:
        if st.malformed and st.rule not in RULES:
            continue
        _check_refs_and_arity(st, index_of)
        step_id = st.id if st.id is not None else f"#{st.index}"
        if st.prop is not None:
            errs = _check_prop(st.prop, store, step=step_id, position=st.index)
            st.errors.extend(errs)
            st.resolved = not any(e.code in _RESOLUTION_FAILURES for e in errs)
        if st.edge is not None:
            errs = [e for t in st.edge for e in check_term(t, store, step=step_id, position=st.index)]
            st.errors.extend(errs)
            st.edge_resolved = not errs

    for st in steps:
        premise: _Step | None = None
        if st.arity_ok and st.premises:
            p = st.premises[0]
            if p in index_of and index_of[p] < st.index:
                premise = steps[index_of[p]]
        if premise is not None and premise.errors:
            st.premise_failed = True
        if st.malformed or st.rule not in RULES or not st.resolved:
            continue
        if st.rule == "axiom":
            _apply_axiom(st, store)
        elif st.rule == "sorry":
            _apply_sorry(st)
        else:
            _apply_propagation(st, premise, store)

    root_id = derivation["root"]
    if root_id not in index_of:
        top.append(Error(Code.UNKNOWN_STEP_REF, f"root names no step: {root_id!r}", actual=root_id))
    else:
        root_step = steps[index_of[root_id]]
        if goal is not None and root_step.prop is not None and root_step.prop != goal:
            top.append(Error(Code.ROOT_MISMATCH, "root conclusion differs from goal",
                             expected=goal.to_dict(), actual=root_step.prop.to_dict()))
    return _assemble(goal, steps, top, root_id=root_id, index_of=index_of, store=store)


def _assemble(
    goal: Prop | None, steps: list[_Step], top: list[Error], *, root_id: str | None,
    index_of: dict[str, int], store: FactStore,
) -> dict[str, Any]:
    used: list[str] = []
    if root_id is not None and root_id in index_of:
        cur: _Step | None = steps[index_of[root_id]]
        guard: set[str] = set()
        while cur is not None and cur.id is not None and cur.id not in guard:
            guard.add(cur.id)
            used.append(cur.id)
            nxt = cur.premises[0] if cur.premises else None
            cur = (steps[index_of[nxt]]
                   if nxt is not None and nxt in index_of and index_of[nxt] < cur.index else None)
    used_set = set(used)
    all_ids = sorted({st.id for st in steps if st.id is not None})
    unused = [sid for sid in all_ids if sid not in used_set]

    sorries: list[dict[str, Any]] = []
    for st in steps:
        if st.rule != "sorry" or st.id is None:
            continue
        prov = st.raw.get("provenance") if isinstance(st.raw, dict) else None
        prov = prov if isinstance(prov, dict) else {}
        inputs = prov.get("inputs")
        sorries.append({
            "step": st.id, "used": st.id in used_set,
            "method": prov.get("method") if isinstance(prov.get("method"), str) else None,
            "inputs": list(inputs) if isinstance(inputs, list) else None,
        })
    sorries.sort(key=lambda s: index_of.get(s["step"], -1))
    sorry_count = sum(1 for s in sorries if s["used"])

    axioms = sorted(
        ({"step": st.id, "annotation": a.id, "code": a.code, "eco": a.eco,
          "references": sorted(a.references)}
         for st in steps for a in st.axioms),
        key=lambda d: d["annotation"])

    def _order(e: Error) -> tuple[int, str, str]:
        return (e.position, e.code, e.message)

    errors = sorted(top + [e for st in steps for e in st.errors], key=_order)
    premise_failed = sorted(st.id for st in steps if st.premise_failed and st.id is not None)
    return {
        "verdict": "ACCEPTED" if not errors else "REJECTED",
        "goal": goal.to_dict() if goal is not None else None,
        "steps_checked": len(steps),
        "sorry_count": sorry_count,
        "unused_sorries": len(sorries) - sorry_count,
        "unused_steps": unused,
        "premise_failed": premise_failed,
        "errors": [e.to_dict() for e in errors],
        "axioms": axioms,
        "sorries": sorries,
        # Must run after `errors` (above) is final: conflicts are verdict-neutral and must
        # never feed back into the verdict/errors already computed.
        "conflicts": _conflicts(steps, index_of, store),
        "elaboration": [],
    }


def dumps(verdict: dict[str, Any]) -> str:
    """The canonical serialization: sorted keys, two-space indent."""
    return json.dumps(verdict, sort_keys=True, indent=2)
