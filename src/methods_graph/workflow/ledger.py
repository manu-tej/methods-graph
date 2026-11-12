"""Append-only provenance ledger for workflow execution.

No calls to datetime.now or random — all timestamps and ids are injected by
the caller so the ledger remains deterministic and testable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from methods_graph.workflow.ir import Decision, Step


@dataclass
class LedgerEntry:
    """An immutable record of a single step execution."""

    step_id: str
    method_id: str
    graph_snapshot: str          # opaque snapshot id / ISO timestamp / commit SHA
    inputs: list[str]
    outputs: list[str]
    parameters: dict[str, Any]
    decision_id: str | None
    decision_rationale: str | None
    recorded_at: str             # ISO string, passed in by caller

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision_rationale": self.decision_rationale,
            "graph_snapshot": self.graph_snapshot,
            "inputs": self.inputs,
            "method_id": self.method_id,
            "outputs": self.outputs,
            "parameters": self.parameters,
            "recorded_at": self.recorded_at,
            "step_id": self.step_id,
        }


class ProvenanceLedger:
    """Append-only collection of LedgerEntry objects."""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    @property
    def entries(self) -> list[LedgerEntry]:
        """Ordered list of all recorded entries (newest last)."""
        return list(self._entries)

    def record(
        self,
        step: Step,
        *,
        graph_snapshot: str,
        recorded_at: str,
        decision: Decision | None = None,
    ) -> LedgerEntry:
        """Append and return a new LedgerEntry for *step*.

        Parameters
        ----------
        step:
            The workflow step being recorded.
        graph_snapshot:
            An opaque identifier for the graph version at execution time
            (e.g. the snapshot's ``created_at`` ISO string or a git SHA).
        recorded_at:
            ISO datetime string for when this record was created.  Must be
            provided by the caller — the ledger never calls datetime.now().
        decision:
            Optional Decision that triggered this step.  If supplied, its
            ``id`` and ``rationale`` are captured in the entry.
        """
        entry = LedgerEntry(
            step_id=step.id,
            method_id=step.method_id,
            graph_snapshot=graph_snapshot,
            inputs=list(step.inputs),
            outputs=list(step.outputs),
            parameters=dict(step.parameters),
            decision_id=decision.id if decision is not None else None,
            decision_rationale=decision.rationale if decision is not None else None,
            recorded_at=recorded_at,
        )
        self._entries.append(entry)
        return entry

    def to_json(self) -> str:
        """Return a deterministic JSON array of all entry dicts."""
        return json.dumps(
            [e.to_dict() for e in self._entries],
            indent=2,
            sort_keys=True,
        )
