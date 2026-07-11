"""Traceability: explain WHY a method/skill carries the evaluability it does, by surfacing
the full provenance chain the guardrail discards — assumption -> the statistical-method or
operation it is inherited through (`via`) -> the literature evidence (DOI/PMID) -> the source
curated YAML file. Read-only over the built graph.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _default_crosslinks_dir() -> Path:
    return Path(__file__).with_name("crosslinks")


def _resolve_yaml_source(evidence_token: str, crosslinks_dir: Path) -> list[str]:
    """Every curated YAML file that carries this evidence token (sorted).

    Resolves by scanning ``crosslinks/*.yaml`` for the bare id (the token minus its
    ``doi:``/``pmid:`` prefix). Returns ALL matches rather than a single guess: a DOI can
    ground entries in more than one file (e.g. a `requires` edge and a diagnostic `ref`),
    so naming just the first would misattribute provenance. Empty list = no match.
    """
    if not evidence_token:
        return []
    bare = evidence_token.split(":", 1)[1] if ":" in evidence_token else evidence_token
    if not bare:
        return []
    return [yml.name for yml in sorted(crosslinks_dir.glob("*.yaml"))
            if bare in yml.read_text(encoding="utf-8")]


def explain(
    provider: Any,
    *,
    method: str | None = None,
    skill: str | None = None,
    crosslinks_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Trace each grounded assumption of a method (or a skill's wrapped methods).

    Returns one dict per assumption: ``{assumption, checkable, threshold, source, via,
    evidence, source_yaml}`` (``source_yaml`` is the list of curated YAML files carrying the
    evidence token). An empty list means no evaluability chain (registry-only / honest gap).
    Raises ``KeyError`` for an unknown ``method`` id (an unknown/unwired ``skill`` honestly
    yields an empty list, mirroring the guardrail).
    """
    if skill is not None:
        pre = provider.skill_preconditions(skill)
    elif method is not None:
        pre = provider.method_preconditions(method)
    else:
        raise ValueError("explain() needs either method= or skill=")

    cdir = crosslinks_dir or _default_crosslinks_dir()
    traces: list[dict[str, Any]] = []
    for a in pre.get("assumptions") or []:
        evidence = a.get("evidence") or ""
        traces.append({
            "assumption": a.get("name", ""),
            "checkable": a.get("checkable", ""),
            "threshold": a.get("threshold"),
            "source": a.get("source", ""),
            "via": a.get("via") or [],
            "evidence": evidence,
            "source_yaml": _resolve_yaml_source(evidence, cdir),
        })
    return traces


def format_traces(target: str, traces: list[dict[str, Any]]) -> str:
    """Human-readable rendering of explain() output."""
    if not traces:
        return f"{target}: no evaluability chain (registry-only / honest gap)"
    lines = [f"{target}: {len(traces)} grounded assumption(s)"]
    for t in traces:
        via = "; ".join(
            v.get("operation") or v.get("statistical_method") or "?" for v in t["via"]
        ) or "(direct)"
        gate = t["checkable"] or "?"
        if t.get("threshold"):
            gate += f" {t['threshold']}"
        src = ", ".join(t["source_yaml"]) or "?"
        lines.append(f"  • {t['assumption']}  [{gate}]")
        lines.append(f"      via:      {via}  (source={t['source']})")
        lines.append(f"      evidence: {t['evidence'] or '(none)'}  ->  {src}")
    return "\n".join(lines)
