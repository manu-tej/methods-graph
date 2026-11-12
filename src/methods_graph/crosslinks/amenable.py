"""Curated, literature-grounded "applicable statistics" cross-links.

Answers "given the results of an operation, what statistics can I run?" — e.g.
RNA-Seq quantification → Wald test / FDR / normalization / PCA.  This is the
mirror image of ``USES_STATISTICAL_METHOD`` (what a tool uses *internally*): here
the relation is ``Operation -AMENABLE_TO-> StatisticalMethod``, **normalized onto
the operation** so one curated row covers every tool that performs it (a Method
is amenable to a statistic transitively via ``PERFORMS``).

Like the other curated layers, the bridge cannot be harvested (STATO has no EDAM
xref) — every link is a *claim with a citation*.  The loader rejects an
ungrounded link, the build emits an edge only when BOTH endpoints resolve to the
right kinds (``Operation`` → ``StatisticalMethod``), and the audit re-checks
endpoint typing + evidence.  Determinism: edges sorted by
``(operation_id, statistical_method_id)``; no clock or RNG.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Reuse the existing grounded-link machinery — no need to reinvent it.
from methods_graph.crosslinks import _CONFIDENCE, Evidence
from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance

log = logging.getLogger(__name__)


def amenable_path() -> Path:
    """Absolute path to the shipped curated applicable-statistics map (package data)."""
    return Path(__file__).with_name("operation_amenable_statistics.yaml")


@dataclass(frozen=True)
class AmenableLink:
    operation_id: str
    statistical_method_id: str
    label: str            # human-readable target label (defense-in-depth check)
    evidence: Evidence
    quote: str = ""
    note: str = ""
    confidence: str = "high"


@dataclass
class AmenableReport:
    """What ``build_amenable_edges`` did — every drop is recorded, never silent."""
    emitted: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)   # (op, stat, reason)
    warnings: list[str] = field(default_factory=list)                   # label mismatches


def load_amenable(path: Path | None = None) -> list[AmenableLink]:
    """Parse and validate the curated applicable-statistics YAML.

    Raises ``ValueError`` on a malformed file: missing endpoints, an ungrounded
    link (no DOI/PMID), or a duplicate ``(operation, statistical_method)`` pair.
    Endpoint *existence* is not checked here (that needs the graph).
    """
    path = path or amenable_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"amenable: {path} must be a mapping, got {type(raw).__name__}")

    entries = raw.get("links", [])
    if not isinstance(entries, list):
        raise ValueError(f"amenable: 'links' in {path} must be a list")

    links: list[AmenableLink] = []
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ValueError(f"amenable: link #{i} is not a mapping")
        op_id = str(e.get("operation", "")).strip()
        stat_id = str(e.get("statistical_method", "")).strip()
        if not op_id or not stat_id:
            raise ValueError(
                f"amenable: link #{i} must have non-empty 'operation' and "
                f"'statistical_method' (got {op_id!r} -> {stat_id!r})"
            )
        ev_raw = e.get("evidence") or {}
        if not isinstance(ev_raw, dict):
            raise ValueError(f"amenable: link #{i} 'evidence' must be a mapping")
        evidence = Evidence(
            doi=str(ev_raw.get("doi", "") or "").strip(),
            pmid=str(ev_raw.get("pmid", "") or "").strip(),
            url=str(ev_raw.get("url", "") or "").strip(),
        )
        if not evidence.is_grounded:
            raise ValueError(
                f"amenable: link #{i} ({op_id} -> {stat_id}) is ungrounded; "
                f"every curated link must cite a DOI or PMID under 'evidence'"
            )
        key = (op_id, stat_id)
        if key in seen:
            raise ValueError(f"amenable: duplicate link {op_id} -> {stat_id}")
        seen.add(key)
        confidence = str(e.get("confidence", "high") or "high").strip().lower()
        if confidence not in _CONFIDENCE:
            raise ValueError(
                f"amenable: link #{i} confidence must be one of "
                f"{sorted(_CONFIDENCE)}, got {confidence!r}"
            )
        links.append(AmenableLink(
            operation_id=op_id,
            statistical_method_id=stat_id,
            label=str(e.get("label", "") or "").strip(),
            evidence=evidence,
            quote=str(e.get("quote", "") or "").strip(),
            note=str(e.get("note", "") or "").strip(),
            confidence=confidence,
        ))
    return links


def build_amenable_edges(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    links: list[AmenableLink] | None = None,
    path: Path | None = None,
) -> tuple[list[EdgeRecord], AmenableReport]:
    """Turn curated links into ``AMENABLE_TO`` edges (Operation→StatisticalMethod).

    An edge is emitted ONLY when the source resolves to an ``Operation`` node and
    the target to a ``StatisticalMethod`` node — so the build never produces a
    dangling or mistyped link.  Any link that cannot be grounded in the node set
    is dropped *with a recorded reason*.  Edges are sorted by
    ``(operation_id, statistical_method_id)`` and carry
    ``{confidence, basis="curated", evidence, quote, note}``.
    """
    if links is None:
        links = load_amenable(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = AmenableReport()
    edges: list[EdgeRecord] = []

    for link in sorted(links, key=lambda x: (x.operation_id, x.statistical_method_id)):
        src = by_id.get(link.operation_id)
        if src is None:
            report.skipped.append((link.operation_id, link.statistical_method_id, "operation_missing"))
            continue
        if src.kind != NodeKind.OPERATION:
            report.skipped.append(
                (link.operation_id, link.statistical_method_id, f"operation_wrong_kind:{src.kind.value}")
            )
            continue
        dst = by_id.get(link.statistical_method_id)
        if dst is None:
            report.skipped.append((link.operation_id, link.statistical_method_id, "target_missing"))
            continue
        if dst.kind != NodeKind.STATISTICAL_METHOD:
            report.skipped.append(
                (link.operation_id, link.statistical_method_id,
                 f"target_wrong_kind:{dst.kind.value}")
            )
            continue
        if link.label and link.label.lower() != (dst.name or "").lower():
            report.warnings.append(
                f"label mismatch for {link.statistical_method_id}: "
                f"curated {link.label!r} != graph {dst.name!r}"
            )

        props: dict[str, Any] = {
            "confidence": _CONFIDENCE[link.confidence],
            "basis": "curated",
            "evidence": link.evidence.as_token(),
        }
        if link.quote:
            props["quote"] = link.quote
        if link.note:
            props["note"] = link.note
        prov = Provenance("curated", link.evidence.best_url(), ingested_at)
        edges.append(EdgeRecord(
            link.operation_id, link.statistical_method_id,
            EdgeKind.AMENABLE_TO, props, prov,
        ))

    report.emitted = len(edges)
    return edges, report
