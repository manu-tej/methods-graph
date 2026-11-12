"""Curated data-modality layer: map nf-core pipelines to the data modality they
operate on (bulk RNA-seq, scRNA-seq, microarray, proteomics, …).

We deliberately removed the EDAM topic/modality firehose (most topics are out of
scope).  Modality returns as a SMALL curated controlled vocabulary mapped directly to
pipelines: ``Pipeline -HAS_MODALITY-> Modality``.  Tools and data inherit a modality
transitively via their pipeline (Pipeline → HAS_MODULE → Module → WRAPS → Method), so
no per-tool edges are needed.

A Modality node is minted only when referenced by a Pipeline node that exists in the
build (no orphan vocab); skips are recorded.  Deterministic: sorted id order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)


def modalities_path() -> Path:
    """Absolute path to the shipped curated modality map (package data)."""
    return Path(__file__).with_name("modalities.yaml")


def _pipe_id(name: str) -> str:
    name = str(name).strip()
    return name if name.startswith("pipe:") else f"pipe:{name}"


@dataclass
class ModalityReport:
    modalities: int = 0
    edges: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (pipe_id, reason)


def load_modalities(
    path: Path | None = None, *, spec: dict | None = None,
) -> tuple[dict[str, dict], dict[str, tuple[str, ...]]]:
    """Parse the curated YAML into (catalog, pipeline_map).

    Schema::

        modalities:
          bulk_rnaseq: {name: "Bulk RNA-seq", description: "..."}
        pipelines:
          rnaseq: [bulk_rnaseq]
          differentialabundance: [bulk_rnaseq, microarray, proteomics]

    ``catalog`` maps a modality key -> {name, description}.  ``pipeline_map`` maps
    ``pipe:<name>`` -> tuple of modality keys, validated against the catalog (an
    unknown key raises rather than silently dropping the modality).
    """
    if spec is None:
        path = path or modalities_path()
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(spec, dict):
        raise ValueError("modalities: top level must be a mapping")
    raw = spec.get("modalities", {})
    if not isinstance(raw, dict):
        raise ValueError("modalities: 'modalities' must be a mapping")
    catalog: dict[str, dict] = {}
    for key, entry in raw.items():
        entry = entry or {}
        if not isinstance(entry, dict) or not entry.get("name"):
            raise ValueError(f"modalities: entry {key!r} must declare a 'name'")
        catalog[str(key)] = {"name": str(entry["name"]),
                             "description": str(entry.get("description", "") or "")}

    raw_pipes = spec.get("pipelines", {})
    if not isinstance(raw_pipes, dict):
        raise ValueError("modalities: 'pipelines' must be a mapping")
    pipe_map: dict[str, tuple[str, ...]] = {}
    for name, mods in raw_pipes.items():
        if mods is not None and not isinstance(mods, list):
            raise ValueError(f"modalities: pipeline {name!r} modalities must be a list")
        keys = []
        for k in (mods or []):
            if k not in catalog:
                raise ValueError(f"modalities: pipeline {name!r} maps to unknown modality {k!r}")
            keys.append(k)
        pipe_map[_pipe_id(name)] = tuple(keys)
    return catalog, pipe_map


def build_modality_records(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    spec: dict | None = None,
    path: Path | None = None,
) -> tuple[list[NodeRecord], list[EdgeRecord], ModalityReport]:
    """Mint ``Modality`` nodes + grounded ``Pipeline -HAS_MODALITY-> Modality`` edges.

    Emitted only for pipelines present in *nodes*; a modality node is minted only
    when referenced by a present pipeline.
    """
    catalog, pipe_map = (load_modalities(path) if spec is None
                         else load_modalities(spec=spec))
    present = {n.id for n in nodes if n.kind == NodeKind.PIPELINE}
    prov = Provenance("curated", "", ingested_at)
    report = ModalityReport()
    edges: list[EdgeRecord] = []
    referenced: set[str] = set()

    for pipe_id in sorted(pipe_map):
        mods = pipe_map[pipe_id]
        if pipe_id not in present:
            report.skipped.append((pipe_id, "pipeline_missing"))
            continue
        for key in sorted(set(mods)):
            referenced.add(key)
            edges.append(EdgeRecord(
                pipe_id, f"modality:{key}", EdgeKind.HAS_MODALITY, {"basis": "curated"}, prov))

    mod_nodes = [
        NodeRecord(f"modality:{key}", catalog[key]["name"], NodeKind.MODALITY,
                   {"description": catalog[key]["description"]}, prov)
        for key in sorted(referenced)
    ]
    report.modalities = len(mod_nodes)
    report.edges = len(edges)
    return mod_nodes, edges, report
