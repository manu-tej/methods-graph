"""Curated, grounded statistical-method assumptions.

STATO *describes* the assumptions of each method in free-text definitions but
never modeled them as classes or a ``has_assumption`` relation — so, like the
Method→StatisticalMethod bridge, they cannot be harvested and must be authored
as grounded claims.

This module does two things from one curated file
(``statistical_method_assumptions.yaml``):

1. mints a small controlled **Assumption vocabulary** (normality, independence,
   homoscedasticity, ...) as ``Assumption`` nodes, and
2. emits grounded ``REQUIRES_ASSUMPTION`` edges **StatisticalMethod→Assumption**.

Assumptions attach to the *statistical method*, not the tool: a t-test requires
normality regardless of which software runs it, so a ``Method`` inherits its
assumptions transitively through ``USES_STATISTICAL_METHOD``.  Every edge carries
an evidence token (``doi:`` / ``url:`` / ``isbn:`` / ``stato:``); the loader
rejects an ungrounded edge and the audit re-checks endpoint typing + evidence.

Determinism: assumption nodes and edges are emitted in sorted id order; no clock
or RNG is read.
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

_CONFIDENCE = {"high": 1.0, "medium": 0.8, "low": 0.6}


def assumptions_path() -> Path:
    """Absolute path to the shipped curated assumptions map (package data)."""
    return Path(__file__).with_name("statistical_method_assumptions.yaml")


def _ref_url(token: str) -> str:
    """Best-effort URL for an evidence/reference token like 'doi:..'|'url:..'|'stato:..'."""
    token = (token or "").strip()
    if token.startswith("url:"):
        return token[4:]
    if token.startswith("doi:"):
        return f"https://doi.org/{token[4:]}"
    if token.startswith("stato:"):
        return f"http://purl.obolibrary.org/obo/{token[6:]}"
    if token.startswith("isbn:"):
        return f"https://isbnsearch.org/isbn/{token[5:]}"
    return ""


@dataclass(frozen=True)
class AssumptionTerm:
    id: str            # 'assum:<slug>' (minted) or 'obo:<id>' (if an ontology has it)
    name: str
    definition: str = ""
    reference: str = ""   # citable source token for the concept itself


@dataclass(frozen=True)
class AssumptionLink:
    statistical_method_id: str
    assumption_id: str
    evidence_token: str
    source_url: str = ""
    quote: str = ""
    note: str = ""
    confidence: str = "high"


@dataclass
class AssumptionReport:
    nodes_emitted: int = 0
    edges_emitted: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)  # (stat, assum, reason)


def load_assumptions(
    path: Path | None = None,
) -> tuple[dict[str, AssumptionTerm], list[AssumptionLink]]:
    """Parse and validate the curated assumptions file.

    Returns ``(vocab_by_id, links)``.  Raises ``ValueError`` on a malformed file:
    an edge referencing an unknown assumption id, an ungrounded edge (empty
    evidence token), or a duplicate ``(statistical_method, assumption)`` pair.
    """
    path = path or assumptions_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"assumptions: {path} must be a mapping")

    vocab: dict[str, AssumptionTerm] = {}
    for i, a in enumerate(raw.get("assumptions", []) or []):
        if not isinstance(a, dict):
            raise ValueError(f"assumptions: vocab entry #{i} is not a mapping")
        aid = str(a.get("id", "")).strip()
        name = str(a.get("name", "")).strip()
        if not aid or not name:
            raise ValueError(f"assumptions: vocab entry #{i} needs non-empty 'id' and 'name'")
        if aid in vocab:
            raise ValueError(f"assumptions: duplicate vocab id {aid}")
        vocab[aid] = AssumptionTerm(
            id=aid, name=name,
            definition=str(a.get("definition", "") or "").strip(),
            reference=str(a.get("reference", "") or "").strip(),
        )

    links: list[AssumptionLink] = []
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(raw.get("requires", []) or []):
        if not isinstance(e, dict):
            raise ValueError(f"assumptions: requires entry #{i} is not a mapping")
        stat_id = str(e.get("statistical_method", "")).strip()
        assum_id = str(e.get("assumption", "")).strip()
        if not stat_id or not assum_id:
            raise ValueError(
                f"assumptions: requires #{i} needs 'statistical_method' and 'assumption'"
            )
        if assum_id not in vocab:
            raise ValueError(
                f"assumptions: requires #{i} references unknown assumption id {assum_id!r}"
            )
        evidence = str(e.get("evidence", "") or "").strip()
        if not evidence:
            raise ValueError(
                f"assumptions: requires #{i} ({stat_id} -> {assum_id}) is ungrounded; "
                f"every edge needs a non-empty 'evidence' token"
            )
        key = (stat_id, assum_id)
        if key in seen:
            raise ValueError(f"assumptions: duplicate requires {stat_id} -> {assum_id}")
        seen.add(key)
        confidence = str(e.get("confidence", "high") or "high").strip().lower()
        if confidence not in _CONFIDENCE:
            raise ValueError(f"assumptions: requires #{i} bad confidence {confidence!r}")
        links.append(AssumptionLink(
            statistical_method_id=stat_id, assumption_id=assum_id,
            evidence_token=evidence, source_url=str(e.get("source_url", "") or "").strip(),
            quote=str(e.get("quote", "") or "").strip(),
            note=str(e.get("note", "") or "").strip(), confidence=confidence,
        ))
    return vocab, links


def build_curated_statistical_method_nodes(
    *, ingested_at: str, path: Path | None = None,
) -> list[NodeRecord]:
    """Mint curated ``StatisticalMethod`` nodes from the ``statistical_methods:`` section.

    For statistics STATO/OBI does not model as a clean class (e.g. GSEA's weighted
    enrichment score), so a method can USE / be AMENABLE_TO them and inherit their
    *correct* assumptions instead of being force-fitted onto a near-but-wrong ontology
    term.  Ids are ``stat:<slug>``.  Must be added to the node set BEFORE the curated
    cross-link / amenable / assumption builders run, so their edges resolve.

    Raises ``ValueError`` on a malformed entry (missing id/name or duplicate id).
    Deterministic: returned sorted by id.
    """
    path = path or assumptions_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"assumptions: {path} must be a mapping")
    out: list[NodeRecord] = []
    seen: set[str] = set()
    for i, sm in enumerate(raw.get("statistical_methods", []) or []):
        if not isinstance(sm, dict):
            raise ValueError(f"assumptions: statistical_methods #{i} is not a mapping")
        sid = str(sm.get("id", "")).strip()
        name = str(sm.get("name", "")).strip()
        if not sid or not name:
            raise ValueError(
                f"assumptions: statistical_methods #{i} needs non-empty 'id' and 'name'")
        if sid in seen:
            raise ValueError(f"assumptions: duplicate statistical_methods id {sid}")
        seen.add(sid)
        reference = str(sm.get("reference", "") or "").strip()
        props: dict[str, Any] = {"basis": "curated"}
        if sm.get("definition"):
            props["definition"] = str(sm["definition"]).strip()
        if reference:
            props["reference"] = reference
        prov = Provenance("curated", _ref_url(reference), ingested_at)
        out.append(NodeRecord(sid, name, NodeKind.STATISTICAL_METHOD, props, prov))
    return sorted(out, key=lambda n: n.id)


def build_assumption_records(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    vocab: dict[str, AssumptionTerm] | None = None,
    links: list[AssumptionLink] | None = None,
    path: Path | None = None,
) -> tuple[list[NodeRecord], list[EdgeRecord], AssumptionReport]:
    """Mint Assumption nodes and grounded REQUIRES_ASSUMPTION edges over ``nodes``.

    An edge is emitted ONLY when its source resolves to a ``StatisticalMethod``
    node (so no dangling/mistyped edge).  An Assumption node is minted only for a
    vocab term actually referenced by an emitted edge AND not already present in
    the node set (so no orphan or duplicate nodes).  Every drop is recorded in
    the report (never silent).
    """
    if vocab is None or links is None:
        vocab, links = load_assumptions(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = AssumptionReport()
    edges: list[EdgeRecord] = []
    used: set[str] = set()

    for link in sorted(links, key=lambda x: (x.statistical_method_id, x.assumption_id)):
        src = by_id.get(link.statistical_method_id)
        if src is None:
            report.skipped.append((link.statistical_method_id, link.assumption_id, "method_missing"))
            continue
        if src.kind != NodeKind.STATISTICAL_METHOD:
            report.skipped.append(
                (link.statistical_method_id, link.assumption_id,
                 f"method_wrong_kind:{src.kind.value}")
            )
            continue
        props: dict[str, Any] = {
            "confidence": _CONFIDENCE[link.confidence],
            "basis": "curated",
            "evidence": link.evidence_token,
        }
        if link.quote:
            props["quote"] = link.quote
        if link.note:
            props["note"] = link.note
        prov = Provenance("curated", link.source_url or _ref_url(link.evidence_token), ingested_at)
        edges.append(EdgeRecord(
            link.statistical_method_id, link.assumption_id,
            EdgeKind.REQUIRES_ASSUMPTION, props, prov,
        ))
        used.add(link.assumption_id)

    # Mint Assumption nodes for referenced terms not already in the graph.
    assumption_nodes: list[NodeRecord] = []
    for aid in sorted(used):
        if aid in by_id:
            continue   # already provided (e.g. a real ontology term) — don't duplicate
        term = vocab[aid]
        node_props: dict[str, Any] = {}
        if term.definition:
            node_props["definition"] = term.definition
        if term.reference:
            node_props["reference"] = term.reference
        prov = Provenance("curated", _ref_url(term.reference), ingested_at)
        assumption_nodes.append(
            NodeRecord(term.id, term.name, NodeKind.ASSUMPTION, node_props, prov)
        )

    report.nodes_emitted = len(assumption_nodes)
    report.edges_emitted = len(edges)
    return assumption_nodes, edges, report
