"""Minimal WorkflowIR — in-memory representation of a bioinformatics workflow.

All types are plain mutable dataclasses with no graph dependency so they can
be constructed, validated, and serialised in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    """An input/output data artifact in a workflow."""

    id: str
    name: str
    kind: str  # e.g. "plot", "table", "matrix", "file"
    produced_by: str | None = None  # Step.id that produced it; None for initial inputs
    edam_format: str | None = None  # optional fmt: id
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """A user-level analytical decision that connects observations to actions."""

    id: str
    rationale: str  # free-text user interpretation
    inputs: list[str] = field(default_factory=list)   # Artifact ids the decision is based on
    leads_to: str | None = None  # Step.id this decision triggers
    made_by: str = "user"


@dataclass
class Step:
    """One processing step in the workflow, linked to a graph method node."""

    id: str
    method_id: str          # graph id, e.g. "m:salmon"
    container_id: str | None = None  # selected ctr: id
    inputs: list[str] = field(default_factory=list)   # Artifact ids consumed
    outputs: list[str] = field(default_factory=list)  # Artifact ids produced
    parameters: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)  # graph node ids grounding this step


@dataclass
class Workflow:
    """Top-level container for steps, artifacts, and decisions."""

    id: str
    steps: list[Step] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def artifact(self, artifact_id: str) -> Artifact | None:
        """Return the Artifact with the given id, or None if not found."""
        for a in self.artifacts:
            if a.id == artifact_id:
                return a
        return None

    def step(self, step_id: str) -> Step | None:
        """Return the Step with the given id, or None if not found."""
        for s in self.steps:
            if s.id == step_id:
                return s
        return None
