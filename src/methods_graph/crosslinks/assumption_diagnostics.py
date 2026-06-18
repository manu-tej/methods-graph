"""Curated, grounded assumption diagnostics.

The graph already knows what assumptions a method relies on (Method →
USES_STATISTICAL_METHOD → StatisticalMethod → REQUIRES_ASSUMPTION → Assumption).
What it lacked is the *diagnostic*: the test / plot / procedure that checks whether
the AVAILABLE DATA actually meets each assumption.  That is what turns "this edge is
evaluable" into "this edge's result is trustworthy".

This module mints ``Diagnostic`` nodes and emits grounded ``Assumption -CHECKED_BY->
Diagnostic`` edges from a curated file (``assumption_diagnostics.yaml``).  Each edge
carries an evidence token (``doi:`` / ``pmid:`` / ``url:`` / ``isbn:``); the audit
re-checks endpoint typing + evidence.  A diagnostic is emitted only when at least one
of the assumptions it checks already exists as a node (skips are recorded).

Determinism: diagnostics and edges are emitted in sorted id order; no clock/RNG.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)

_EVIDENCE_PREFIXES = ("doi:", "pmid:", "url:", "isbn:")


def assumption_diagnostics_path() -> Path:
    """Absolute path to the shipped curated diagnostics map (package data)."""
    return Path(__file__).with_name("assumption_diagnostics.yaml")


def _assum_id(slug: str) -> str:
    slug = str(slug).strip()
    return slug if slug.startswith("assum:") else f"assum:{slug}"


@dataclass(frozen=True)
class DiagnosticDef:
    """A curated diagnostic: which assumptions it checks + how, with grounding."""
    diag_id: str                  # diag:<slug>
    name: str
    kind: str                     # test | plot | procedure
    how: str
    checks: tuple[str, ...]       # assum:<slug> ids it evaluates
    ref: str                      # evidence token (doi:/pmid:/url:/isbn:)


@dataclass
class DiagnosticReport:
    diagnostics: int = 0
    edges: int = 0
    skipped: list[tuple[str, str, str]] = field(  # (diag_id, assum_id, reason)
        default_factory=list)


def load_assumption_diagnostics(
    path: Path | None = None, *, spec: dict | None = None,
) -> list[DiagnosticDef]:
    """Parse the curated YAML into ``DiagnosticDef`` records.

    Schema::

        diagnostics:
          shapiro_wilk:
            name: "Shapiro–Wilk normality test"
            kind: test
            checks: [normality, asymptotic_normality]
            how: "..."
            ref: "doi:10.1093/biomet/52.3-4.591"

    Raises ``ValueError`` on a malformed entry, a missing ``checks`` list, or a
    missing/ungrounded ``ref`` (an ungrounded diagnostic would defeat the point).
    """
    if spec is None:
        path = path or assumption_diagnostics_path()
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(spec, dict):
        raise ValueError("assumption_diagnostics: top level must be a mapping")
    raw = spec.get("diagnostics", {})
    if not isinstance(raw, dict):
        raise ValueError("assumption_diagnostics: 'diagnostics' must be a mapping")

    defs: list[DiagnosticDef] = []
    for slug, entry in raw.items():
        entry = entry or {}
        if not isinstance(entry, dict):
            raise ValueError(f"assumption_diagnostics: entry {slug!r} must be a mapping")
        checks = tuple(_assum_id(c) for c in (entry.get("checks") or []))
        if not checks:
            raise ValueError(f"assumption_diagnostics: {slug!r} declares no 'checks'")
        ref = str(entry.get("ref", "") or "").strip()
        if not ref.startswith(_EVIDENCE_PREFIXES):
            raise ValueError(
                f"assumption_diagnostics: {slug!r} needs a grounded 'ref' "
                f"(one of {_EVIDENCE_PREFIXES})")
        diag_id = str(slug).strip()
        diag_id = diag_id if diag_id.startswith("diag:") else f"diag:{diag_id}"
        defs.append(DiagnosticDef(
            diag_id=diag_id, name=str(entry.get("name", slug)).strip(),
            kind=str(entry.get("kind", "test")).strip(), how=str(entry.get("how", "")).strip(),
            checks=checks, ref=ref))
    return sorted(defs, key=lambda d: d.diag_id)


def build_diagnostic_records(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    defs: list[DiagnosticDef] | None = None,
    path: Path | None = None,
) -> tuple[list[NodeRecord], list[EdgeRecord], DiagnosticReport]:
    """Mint ``Diagnostic`` nodes + grounded ``Assumption -CHECKED_BY-> Diagnostic`` edges.

    A diagnostic node is minted only if at least one assumption it checks exists;
    each checked assumption that is absent is recorded as a skip.
    """
    if defs is None:
        defs = load_assumption_diagnostics(path)
    assum_ids = {n.id for n in nodes if n.kind == NodeKind.ASSUMPTION}
    prov = Provenance("curated", "", ingested_at)
    diag_nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    report = DiagnosticReport()

    for d in sorted(defs, key=lambda x: x.diag_id):
        present = [a for a in d.checks if a in assum_ids]
        for a in d.checks:
            if a not in assum_ids:
                report.skipped.append((d.diag_id, a, "assumption_missing"))
        if not present:
            continue
        diag_nodes.append(NodeRecord(
            d.diag_id, d.name, NodeKind.DIAGNOSTIC, {"form": d.kind, "how": d.how}, prov))
        for a in sorted(present):
            edges.append(EdgeRecord(
                a, d.diag_id, EdgeKind.CHECKED_BY,
                {"evidence": d.ref, "basis": "curated"}, prov))
        report.diagnostics += 1
    report.edges = len(edges)
    return diag_nodes, edges, report
