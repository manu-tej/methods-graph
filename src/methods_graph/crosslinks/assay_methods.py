"""Curated, literature-grounded "analyzed by" cross-links (Assay -> Method).

OBI models wet-lab assays (RPPA, phospho-protein readouts, …) as ``Assay`` nodes,
but nothing in the harvested sources connects an assay to the tool that analyzes
the data MATRIX it produces — so an assay readout cannot ground to any method.
This module loads a small, hand-curated, **literature-grounded** map
(``assay_methods.yaml``) and turns it into ``ANALYZED_BY`` edges (Assay -> Method),
normalized onto the assay.

Grounding is not optional: every link MUST cite a DOI or PMID; the loader rejects
an ungrounded link, the build emits an edge only when BOTH endpoints resolve to
the right kinds (``Assay`` -> ``Method``), and the audit re-checks endpoint typing
and the presence of evidence.  Determinism: edges are emitted sorted by
``(assay_id, method_id)``; no clock or RNG is read.
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


def assay_methods_path() -> Path:
    """Absolute path to the shipped curated assay->method map (package data)."""
    return Path(__file__).with_name("assay_methods.yaml")


@dataclass(frozen=True)
class AssayMethodLink:
    assay_id: str
    method_id: str
    label: str            # human-readable target label (defense-in-depth check)
    evidence: Evidence
    quote: str = ""
    note: str = ""
    confidence: str = "high"


@dataclass
class AssayMethodReport:
    """What ``build_assay_method_edges`` did — every drop is recorded, never silent."""
    emitted: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)   # (assay, method, reason)
    warnings: list[str] = field(default_factory=list)                   # label mismatches


def load_assay_methods(path: Path | None = None) -> list[AssayMethodLink]:
    """Parse and validate the curated assay->method YAML.

    Raises ``ValueError`` on a malformed file: missing endpoints, an ungrounded
    link (no DOI/PMID), or a duplicate ``(assay, method)`` pair.  Endpoint
    *existence* is not checked here (that needs the graph).
    """
    path = path or assay_methods_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"assay_methods: {path} must be a mapping, got {type(raw).__name__}")

    entries = raw.get("links", [])
    if not isinstance(entries, list):
        raise ValueError(f"assay_methods: 'links' in {path} must be a list")

    links: list[AssayMethodLink] = []
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ValueError(f"assay_methods: link #{i} is not a mapping")
        assay_id = str(e.get("assay", "")).strip()
        method_id = str(e.get("method", "")).strip()
        if not assay_id or not method_id:
            raise ValueError(
                f"assay_methods: link #{i} must have non-empty 'assay' and "
                f"'method' (got {assay_id!r} -> {method_id!r})"
            )
        ev_raw = e.get("evidence") or {}
        if not isinstance(ev_raw, dict):
            raise ValueError(f"assay_methods: link #{i} 'evidence' must be a mapping")
        evidence = Evidence(
            doi=str(ev_raw.get("doi", "") or "").strip(),
            pmid=str(ev_raw.get("pmid", "") or "").strip(),
            url=str(ev_raw.get("url", "") or "").strip(),
        )
        if not evidence.is_grounded:
            raise ValueError(
                f"assay_methods: link #{i} ({assay_id} -> {method_id}) is ungrounded; "
                f"every curated link must cite a DOI or PMID under 'evidence'"
            )
        key = (assay_id, method_id)
        if key in seen:
            raise ValueError(f"assay_methods: duplicate link {assay_id} -> {method_id}")
        seen.add(key)
        confidence = str(e.get("confidence", "high") or "high").strip().lower()
        if confidence not in _CONFIDENCE:
            raise ValueError(
                f"assay_methods: link #{i} confidence must be one of "
                f"{sorted(_CONFIDENCE)}, got {confidence!r}"
            )
        links.append(AssayMethodLink(
            assay_id=assay_id,
            method_id=method_id,
            label=str(e.get("label", "") or "").strip(),
            evidence=evidence,
            quote=str(e.get("quote", "") or "").strip(),
            note=str(e.get("note", "") or "").strip(),
            confidence=confidence,
        ))
    return links


def build_assay_method_edges(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    links: list[AssayMethodLink] | None = None,
    path: Path | None = None,
) -> tuple[list[EdgeRecord], AssayMethodReport]:
    """Turn curated links into ``ANALYZED_BY`` edges (Assay -> Method).

    An edge is emitted ONLY when the source resolves to an ``Assay`` node and the
    target to a ``Method`` node — so the build never produces a dangling or
    mistyped link.  Any link that cannot be grounded in the node set is dropped
    *with a recorded reason*.  Edges are sorted by ``(assay_id, method_id)`` and
    carry ``{confidence, basis="curated", evidence, quote, note}``.
    """
    if links is None:
        links = load_assay_methods(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = AssayMethodReport()
    edges: list[EdgeRecord] = []

    for link in sorted(links, key=lambda x: (x.assay_id, x.method_id)):
        src = by_id.get(link.assay_id)
        if src is None:
            report.skipped.append((link.assay_id, link.method_id, "assay_missing"))
            continue
        if src.kind != NodeKind.ASSAY:
            report.skipped.append(
                (link.assay_id, link.method_id, f"assay_wrong_kind:{src.kind.value}")
            )
            continue
        dst = by_id.get(link.method_id)
        if dst is None:
            report.skipped.append((link.assay_id, link.method_id, "target_missing"))
            continue
        if dst.kind != NodeKind.METHOD:
            report.skipped.append(
                (link.assay_id, link.method_id, f"target_wrong_kind:{dst.kind.value}")
            )
            continue
        if link.label and link.label.lower() != (dst.name or "").lower():
            report.warnings.append(
                f"label mismatch for {link.method_id}: "
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
            link.assay_id, link.method_id, EdgeKind.ANALYZED_BY, props, prov,
        ))

    report.emitted = len(edges)
    return edges, report
