"""Method-layer planner: advisory, attestation-ranked next-step suggestions.

Pure / deterministic / read-only over a built Kùzu methods graph. Given a frontier
(the Module step-nodes and/or EDAM Format/Data nodes the user currently has),
expand() returns the attestation-ranked next analysis steps, each resolved to a
concrete executor (the wrapped Method) with its container and inherited assumptions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import kuzu

from methods_graph.extract.seed import method_ids_matching, method_neighborhood


@dataclass(frozen=True)
class Executor:
    method_id: str
    name: str
    container: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"method_id": self.method_id, "name": self.name, "container": self.container}


@dataclass(frozen=True)
class Suggestion:
    module_id: str
    module_name: str
    chosen_executor: Executor
    alternatives: list[Executor] = field(default_factory=list)
    rank_signal: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "chosen_executor": self.chosen_executor.to_dict(),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "rank_signal": self.rank_signal,
            "evidence": self.evidence,
            "assumptions": self.assumptions,
            "why": self.why,
        }
