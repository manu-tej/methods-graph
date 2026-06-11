"""Shared record types for staging and canonical layers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(str, Enum):
    METHOD = "Method"
    PIPELINE = "Pipeline"
    MODULE = "Module"
    CONTAINER = "Container"
    PACKAGE = "Package"
    OPERATION = "Operation"
    TOPIC = "Topic"
    DATA = "Data"
    FORMAT = "Format"
    PAPER = "Paper"
    # STATO/OBI ontology-term kinds — values match LinkML class names exactly.
    STATISTICAL_METHOD = "StatisticalMethod"
    ASSUMPTION = "Assumption"
    DIAGNOSTIC = "Diagnostic"
    ASSAY = "Assay"
    PROTOCOL = "Protocol"
    STUDY_DESIGN = "StudyDesign"
    MATERIAL = "Material"
    INSTRUMENT = "Instrument"


class EdgeKind(str, Enum):
    HAS_MODULE = "HAS_MODULE"          # Phase 2 — declared for the pipeline DAG; no emitter in MVP
    WRAPS = "WRAPS"
    DOWNSTREAM_OF = "DOWNSTREAM_OF"   # Phase 2 — declared for the pipeline DAG; no emitter in MVP
    PACKAGED_AS = "PACKAGED_AS"
    FROM_PACKAGE = "FROM_PACKAGE"
    PERFORMS = "PERFORMS"
    HAS_TOPIC = "HAS_TOPIC"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    HAS_FORMAT = "HAS_FORMAT"
    IS_A = "IS_A"
    CITES = "CITES"
    SAME_AS = "SAME_AS"


@dataclass(frozen=True)
class Provenance:
    source: str          # "edam" | "nfcore" | "biocontainers"
    source_url: str
    ingested_at: str     # ISO date, passed in (never call datetime.now in pure code)


@dataclass
class NodeRecord:
    id: str
    name: str
    kind: NodeKind
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def to_row(self) -> dict[str, Any]:
        row = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "properties": json.dumps(self.properties, sort_keys=True),
        }
        if self.provenance:
            row.update(source=self.provenance.source,
                       source_url=self.provenance.source_url,
                       ingested_at=self.provenance.ingested_at)
        return row


@dataclass
class MethodRecord(NodeRecord):
    """A Method node carries the extra join keys used by the resolver."""
    bioconda_pkg: str | None = None
    biotools_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        row = super().to_row()
        row["bioconda_pkg"] = self.bioconda_pkg or ""
        row["biotools_id"] = self.biotools_id or ""
        return row


@dataclass
class EdgeRecord:
    from_id: str
    to_id: str
    kind: EdgeKind
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def to_row(self) -> dict[str, Any]:
        row = {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "kind": self.kind.value,
            "properties": json.dumps(self.properties, sort_keys=True),
        }
        if self.provenance:
            row.update(source=self.provenance.source,
                       source_url=self.provenance.source_url,
                       ingested_at=self.provenance.ingested_at)
        return row
