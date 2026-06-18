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
    # Executable recipe for a module — pinned container + command + typed I/O,
    # extracted from the module's main.nf / environment.yml (connectors/module_execution.py).
    EXECUTION_SPEC = "ExecutionSpec"
    # Data modality (bulk RNA-seq, scRNA-seq, microarray, proteomics, …) — a small
    # curated controlled vocab mapped to pipelines (crosslinks/modalities.py), NOT the
    # EDAM topic firehose (deliberately removed).
    MODALITY = "Modality"


class EdgeKind(str, Enum):
    HAS_MODULE = "HAS_MODULE"          # pipeline DAG — emitted by connectors/nfcore_pipeline.py
    WRAPS = "WRAPS"
    DOWNSTREAM_OF = "DOWNSTREAM_OF"   # pipeline DAG — emitted by connectors/nfcore_pipeline.py
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
    # Curated, literature-grounded Method→StatisticalMethod link. Carries
    # confidence + basis + evidence (DOI/PMID) in its properties; the build path
    # only emits it when BOTH endpoints exist (Method, StatisticalMethod) and the
    # link is grounded, and the audit enforces both of those as invariants.
    USES_STATISTICAL_METHOD = "USES_STATISTICAL_METHOD"
    # Curated, grounded StatisticalMethod→Assumption link (the assumptions a
    # statistical method classically requires).  Assumptions attach to the
    # StatisticalMethod, not the tool — a Method inherits them transitively via
    # USES_STATISTICAL_METHOD.  Same grounding/typed-endpoint invariants apply.
    REQUIRES_ASSUMPTION = "REQUIRES_ASSUMPTION"
    # Curated, grounded Operation→StatisticalMethod link: the downstream statistics
    # *applicable to* the results of an operation (e.g. RNA-Seq quantification →
    # Wald test / FDR).  Normalized onto the operation, not the tool — a Method is
    # amenable to a statistic transitively via PERFORMS.  Distinct from
    # USES_STATISTICAL_METHOD (what a tool uses *internally*).  Same grounding +
    # typed-endpoint invariants apply.
    AMENABLE_TO = "AMENABLE_TO"
    # Module→ExecutionSpec: the runnable recipe for a module (pinned container +
    # command + typed I/O), emitted only when the Module node exists.
    RUNS_AS = "RUNS_AS"
    # Curated, grounded Assumption→Diagnostic link: the test/plot/procedure that
    # checks whether the available data MEETS an assumption (normality → Shapiro–Wilk
    # / Q–Q plot, independence → batch-design review, …).  Turns "edge is evaluable"
    # into "edge result is trustworthy".  Carries an evidence token; emitted only when
    # the Assumption node exists.
    CHECKED_BY = "CHECKED_BY"
    # Pipeline→Modality: the data modality a pipeline operates on (curated map),
    # emitted only when the Pipeline node exists.  Tools/data inherit it transitively.
    HAS_MODALITY = "HAS_MODALITY"


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
