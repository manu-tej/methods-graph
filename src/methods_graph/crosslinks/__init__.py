"""Curated, literature-grounded Method→StatisticalMethod cross-links.

The methods graph derives most of its edges mechanically from sources (EDAM,
nf-core, bio.tools, STATO/OBI).  But *which statistical method a tool actually
uses* is not recorded in any of those sources — it lives in the tool's primary
publication.  This module loads a small, hand-curated, **literature-grounded**
map (``method_statistical_methods.yaml``) and turns it into
``USES_STATISTICAL_METHOD`` edges.

Grounding is not optional.  Every curated link MUST cite a DOI or PMID; the
loader rejects an ungrounded link, the build only emits an edge when BOTH
endpoints resolve to the right node kinds, and the audit re-checks both the
endpoint typing and the presence of evidence.  Nothing here ever merges nodes
or invents an edge from a fuzzy match — a link is a *claim with a citation*,
exactly like the resolver's ``SAME_AS`` candidates carry ``confidence``/``basis``.

Determinism: links are emitted sorted by ``(method_id, statistical_method_id)``;
no clock or RNG is read.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from methods_graph.types import (
    EdgeKind,
    EdgeRecord,
    NodeKind,
    NodeRecord,
    Provenance,
)

log = logging.getLogger(__name__)

# high/medium/low literature confidence → numeric edge confidence, matching the
# resolver's convention of storing a float ``confidence`` on candidate edges.
_CONFIDENCE = {"high": 1.0, "medium": 0.8, "low": 0.6}


def crosslinks_path() -> Path:
    """Absolute path to the shipped curated cross-link map (package data)."""
    return Path(__file__).with_name("method_statistical_methods.yaml")


@dataclass(frozen=True)
class Evidence:
    """A literature citation grounding a single cross-link."""
    doi: str = ""
    pmid: str = ""
    url: str = ""

    @property
    def is_grounded(self) -> bool:
        return bool(self.doi.strip() or self.pmid.strip())

    def as_token(self) -> str:
        """Compact, stable token stored on the edge (and checked by the audit)."""
        if self.doi.strip():
            return f"doi:{self.doi.strip()}"
        if self.pmid.strip():
            return f"pmid:{self.pmid.strip()}"
        return ""

    def best_url(self) -> str:
        if self.url.strip():
            return self.url.strip()
        if self.doi.strip():
            return f"https://doi.org/{self.doi.strip()}"
        if self.pmid.strip():
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid.strip()}/"
        return ""


@dataclass(frozen=True)
class CuratedLink:
    method_id: str
    statistical_method_id: str
    label: str            # human-readable target label (defense-in-depth check)
    evidence: Evidence
    quote: str = ""
    note: str = ""
    confidence: str = "high"


@dataclass
class CrosslinkReport:
    """What ``build_crosslink_edges`` did — every drop is recorded, never silent."""
    emitted: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)   # (method, stat, reason)
    warnings: list[str] = field(default_factory=list)                   # e.g. label mismatches


def load_crosslinks(path: Path | None = None) -> list[CuratedLink]:
    """Parse and validate the curated cross-link YAML.

    Raises ``ValueError`` on a malformed file: missing endpoints, an ungrounded
    link (no DOI/PMID), or a duplicate ``(method, statistical_method)`` pair.
    Endpoint *existence* is not checked here (that needs the graph) — see
    :func:`build_crosslink_edges`.
    """
    path = path or crosslinks_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"crosslinks: {path} must be a mapping, got {type(raw).__name__}")

    entries = raw.get("links", [])
    if not isinstance(entries, list):
        raise ValueError(f"crosslinks: 'links' in {path} must be a list")

    links: list[CuratedLink] = []
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ValueError(f"crosslinks: link #{i} is not a mapping")
        method_id = str(e.get("method", "")).strip()
        stat_id = str(e.get("statistical_method", "")).strip()
        if not method_id or not stat_id:
            raise ValueError(
                f"crosslinks: link #{i} must have non-empty 'method' and "
                f"'statistical_method' (got {method_id!r} -> {stat_id!r})"
            )
        ev_raw = e.get("evidence") or {}
        if not isinstance(ev_raw, dict):
            raise ValueError(f"crosslinks: link #{i} 'evidence' must be a mapping")
        evidence = Evidence(
            doi=str(ev_raw.get("doi", "") or "").strip(),
            pmid=str(ev_raw.get("pmid", "") or "").strip(),
            url=str(ev_raw.get("url", "") or "").strip(),
        )
        if not evidence.is_grounded:
            raise ValueError(
                f"crosslinks: link #{i} ({method_id} -> {stat_id}) is ungrounded; "
                f"every curated link must cite a DOI or PMID under 'evidence'"
            )
        key = (method_id, stat_id)
        if key in seen:
            raise ValueError(
                f"crosslinks: duplicate link {method_id} -> {stat_id}"
            )
        seen.add(key)
        confidence = str(e.get("confidence", "high") or "high").strip().lower()
        if confidence not in _CONFIDENCE:
            raise ValueError(
                f"crosslinks: link #{i} confidence must be one of "
                f"{sorted(_CONFIDENCE)}, got {confidence!r}"
            )
        links.append(CuratedLink(
            method_id=method_id,
            statistical_method_id=stat_id,
            label=str(e.get("label", "") or "").strip(),
            evidence=evidence,
            quote=str(e.get("quote", "") or "").strip(),
            note=str(e.get("note", "") or "").strip(),
            confidence=confidence,
        ))
    return links


def build_crosslink_edges(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    links: list[CuratedLink] | None = None,
    path: Path | None = None,
) -> tuple[list[EdgeRecord], CrosslinkReport]:
    """Turn curated links into ``USES_STATISTICAL_METHOD`` edges over ``nodes``.

    An edge is emitted ONLY when the source resolves to a ``Method`` node and the
    target to a ``StatisticalMethod`` node — so the build never produces a
    dangling or mistyped cross-link.  Any link that cannot be grounded in the
    node set is dropped *with a recorded reason* (``CrosslinkReport.skipped``).

    Edges are emitted sorted by ``(method_id, statistical_method_id)`` and carry
    ``{confidence, basis="curated", evidence, quote, note}`` plus per-edge
    provenance pointing at the citation URL.
    """
    if links is None:
        links = load_crosslinks(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = CrosslinkReport()
    edges: list[EdgeRecord] = []

    for link in sorted(links, key=lambda x: (x.method_id, x.statistical_method_id)):
        src = by_id.get(link.method_id)
        if src is None:
            report.skipped.append((link.method_id, link.statistical_method_id, "method_missing"))
            continue
        if src.kind != NodeKind.METHOD:
            report.skipped.append(
                (link.method_id, link.statistical_method_id, f"method_wrong_kind:{src.kind.value}")
            )
            continue
        dst = by_id.get(link.statistical_method_id)
        if dst is None:
            report.skipped.append((link.method_id, link.statistical_method_id, "target_missing"))
            continue
        if dst.kind != NodeKind.STATISTICAL_METHOD:
            report.skipped.append(
                (link.method_id, link.statistical_method_id,
                 f"target_wrong_kind:{dst.kind.value}")
            )
            continue
        # Defense-in-depth: the curated label should match the graph's node name.
        # A mismatch is a warning (the id is authoritative), not a hard skip — it
        # surfaces a stale curation entry without dropping a valid grounded edge.
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
            link.method_id, link.statistical_method_id,
            EdgeKind.USES_STATISTICAL_METHOD, props, prov,
        ))

    report.emitted = len(edges)
    return edges, report
