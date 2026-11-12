"""Prose for humans reviewing a derivation, and text an agent reads for a verdict."""
from __future__ import annotations

import json
from typing import Any

from methods_graph.biolean.store import FactStore


def _name(term_id: Any, store: FactStore) -> str:
    if not isinstance(term_id, str):
        return "?"
    t = store.term(term_id)
    return f"{t.name} ({term_id})" if t is not None else term_id


def _subject(subject: Any, store: FactStore) -> str:
    if not isinstance(subject, str):
        return "?"
    anns = store.annotations(subject)
    return f"{anns[0].symbol} ({subject})" if anns else subject


def _prop(p: Any, store: FactStore) -> str:
    if not isinstance(p, dict):
        return "?"
    neg = "NOT " if p.get("negated") is True else ""
    return (f"{_subject(p.get('subject'), store)} {neg}{p.get('qualifier', '?')} "
            f"{_name(p.get('term'), store)} in {p.get('taxon', '?')}")


def render_derivation(derivation: Any, store: FactStore) -> str:
    if not isinstance(derivation, dict) or not isinstance(derivation.get("steps"), list):
        return "unrenderable: not a derivation object"
    lines: list[str] = []
    for step in derivation["steps"]:
        if not isinstance(step, dict):
            lines.append("s?: ? (not an object)")
            continue
        sid, rule = step.get("id", "s?"), step.get("rule", "?")
        concl = _prop(step.get("conclusion"), store)
        if rule == "axiom":
            code = f" [{step['code']}]" if isinstance(step.get("code"), str) else ""
            lines.append(f"{sid}: axiom — {concl}{code}")
        elif rule in ("is_a", "part_of") and isinstance(step.get("edge"), list) and len(step["edge"]) == 2:
            child, parent = step["edge"]
            lines.append(f"{sid}: {rule} — because {_name(child, store)} {rule} {_name(parent, store)}, {concl}")
        elif rule == "sorry":
            prov = step.get("provenance") if isinstance(step.get("provenance"), dict) else {}
            method = prov.get("method", "?")
            inputs = ", ".join(str(i) for i in prov.get("inputs", [])) if isinstance(prov.get("inputs"), list) else "?"
            lines.append(f"{sid}: sorry — {concl} via {method} on {inputs} (unverified)")
        else:
            lines.append(f"{sid}: {rule} — {concl}")
    lines.append(f"root: {derivation.get('root', '?')} proves {_prop(derivation.get('goal'), store)}")
    return "\n".join(lines)


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 or noun == "sorry" else "s")


def render_verdict(verdict: dict[str, Any]) -> str:
    lines: list[str] = []
    n_steps = verdict.get("steps_checked", 0)
    if verdict.get("verdict") == "ACCEPTED":
        lines.append(f"ACCEPTED: {_plural(n_steps, 'step')}, {verdict.get('sorry_count', 0)} sorry, "
                     f"{_plural(len(verdict.get('conflicts', [])), 'conflict')}")
    else:
        lines.append(f"REJECTED: {_plural(n_steps, 'step')}, {_plural(len(verdict.get('errors', [])), 'error')}, "
                     f"{verdict.get('unused_sorries', 0)} unused sorry, "
                     f"{_plural(len(verdict.get('unused_steps', [])), 'unused step')}")
    for e in verdict.get("errors", []):
        step = e.get("step") or "goal"
        lines.append(f"  {step} {e.get('code')}: {e.get('message')}")
        suggestions = e.get("suggestions") or []
        if suggestions:
            s = suggestions[0]
            if "edge" in s:
                lines.append(f"    suggest: {s['rule']} [{s['edge'][0]}, {s['edge'][1]}]")
            else:
                lines.append(f"    suggest: {s['rule']} {json.dumps(s.get('conclusion'), sort_keys=True)}")
    for c in verdict.get("conflicts", []):
        lines.append(f"  conflict: {c.get('step')} contradicted at {c.get('at')} {c.get('via')} "
                     f"by {c.get('annotation')} [{c.get('code')}]")
    for el in verdict.get("elaboration", []):
        lines.append(f"  elaborated: {el.get('path')} {el.get('before')} -> {el.get('after')} ({el.get('kind')})")
    return "\n".join(lines)
