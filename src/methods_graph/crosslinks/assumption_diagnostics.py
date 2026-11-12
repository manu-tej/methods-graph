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
    """A curated diagnostic: which assumptions it checks + how, with grounding.

    The trailing fields are machine-readable structured metadata (optional) so a
    consumer can act on a diagnostic WITHOUT parsing the prose ``how``:

    * ``checkable`` — ``"pre_run"`` (evaluable from a dataset's metadata/design
      before running the tool) or ``"post_run"`` (needs the tool's output).  Empty
      string when the curated entry does not declare it.
    * ``applies_to_assumption`` — the single ``assum:<slug>`` a numeric threshold
      pertains to (empty when not applicable).
    * ``min_replicates_per_group`` — the replicate floor a pre-run gate enforces
      (``None`` when the diagnostic carries no such threshold).
    * ``min_peptides_per_protein`` — the peptide-support floor a pre-run gate enforces
      (``None`` when the diagnostic carries no such threshold).
    """
    diag_id: str                  # diag:<slug>
    name: str
    kind: str                     # test | plot | procedure
    how: str
    checks: tuple[str, ...]       # assum:<slug> ids it evaluates
    ref: str                      # evidence token (doi:/pmid:/url:/isbn:)
    checkable: str = ""           # "pre_run" | "post_run" | ""
    applies_to_assumption: str = ""   # assum:<slug> the threshold pertains to
    min_replicates_per_group: int | None = None
    min_peptides_per_protein: int | None = None


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
        raw_checks = entry.get("checks")
        if raw_checks is not None and not isinstance(raw_checks, list):
            raise ValueError(f"assumption_diagnostics: {slug!r} 'checks' must be a list")
        checks = tuple(_assum_id(c) for c in (raw_checks or []))
        if not checks:
            raise ValueError(f"assumption_diagnostics: {slug!r} declares no 'checks'")
        ref = str(entry.get("ref", "") or "").strip()
        if not ref.startswith(_EVIDENCE_PREFIXES):
            raise ValueError(
                f"assumption_diagnostics: {slug!r} needs a grounded 'ref' "
                f"(one of {_EVIDENCE_PREFIXES})")
        diag_id = str(slug).strip()
        diag_id = diag_id if diag_id.startswith("diag:") else f"diag:{diag_id}"

        # --- optional machine-readable structured fields (P2) ---
        checkable = str(entry.get("checkable", "") or "").strip()
        if checkable and checkable not in ("pre_run", "post_run"):
            raise ValueError(
                f"assumption_diagnostics: {slug!r} 'checkable' must be "
                f"'pre_run' or 'post_run' (got {checkable!r})")
        applies_raw = entry.get("applies_to_assumption")
        applies_to = _assum_id(applies_raw) if applies_raw else ""
        if applies_to and applies_to not in checks:
            raise ValueError(
                f"assumption_diagnostics: {slug!r} 'applies_to_assumption' "
                f"{applies_to!r} is not among its 'checks' {list(checks)}")
        min_reps = entry.get("min_replicates_per_group")
        if min_reps is not None:
            if not isinstance(min_reps, int) or isinstance(min_reps, bool) or min_reps < 1:
                raise ValueError(
                    f"assumption_diagnostics: {slug!r} 'min_replicates_per_group' "
                    f"must be a positive integer (got {min_reps!r})")
        min_pep = entry.get("min_peptides_per_protein")
        if min_pep is not None:
            if not isinstance(min_pep, int) or isinstance(min_pep, bool) or min_pep < 1:
                raise ValueError(
                    f"assumption_diagnostics: {slug!r} 'min_peptides_per_protein' "
                    f"must be a positive integer (got {min_pep!r})")

        defs.append(DiagnosticDef(
            diag_id=diag_id, name=str(entry.get("name", slug)).strip(),
            kind=str(entry.get("kind", "test")).strip(), how=str(entry.get("how", "")).strip(),
            checks=checks, ref=ref, checkable=checkable,
            applies_to_assumption=applies_to, min_replicates_per_group=min_reps,
            min_peptides_per_protein=min_pep))
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
        props: dict = {"form": d.kind, "how": d.how}
        # Machine-readable structured fields (P2) — emitted only when present so
        # the node stays compact and a consumer can read them without prose parsing.
        if d.checkable:
            props["checkable"] = d.checkable
        # Only surface applies_to_assumption when that assumption is actually present
        # in the graph (so the node never points at an assumption it has no
        # CHECKED_BY edge to).
        if d.applies_to_assumption and d.applies_to_assumption in present:
            props["applies_to_assumption"] = d.applies_to_assumption
        if d.min_replicates_per_group is not None:
            props["min_replicates_per_group"] = d.min_replicates_per_group
        if d.min_peptides_per_protein is not None:
            props["min_peptides_per_protein"] = d.min_peptides_per_protein
        diag_nodes.append(NodeRecord(
            d.diag_id, d.name, NodeKind.DIAGNOSTIC, props, prov))
        for a in sorted(present):
            edges.append(EdgeRecord(
                a, d.diag_id, EdgeKind.CHECKED_BY,
                {"evidence": d.ref, "basis": "curated"}, prov))
        report.diagnostics += 1
    report.edges = len(edges)
    return diag_nodes, edges, report
