"""Gold sequences become frozen benchmark items."""
from __future__ import annotations

from typing import Any

_REQUIRED_DERIVATION = "nextflow_dsl2"


def make_items(
    *,
    pipeline: str,
    revision: str,
    nxf_ver: str,
    dag_sha256: str,
    goal: str,
    sequence: list[str],
    derivation: str,
) -> list[dict[str, Any]]:
    """One whole-pipeline item plus one next-step item per position.

    Rejects anything not derived from a real Nextflow DAG: accepting inferred
    wiring would make the answer key an artifact of the method under test.
    """
    if derivation != _REQUIRED_DERIVATION:
        raise ValueError(
            f"derivation must be {_REQUIRED_DERIVATION!r}, got {derivation!r}")
    if len(sequence) < 2:
        raise ValueError("a gold sequence needs at least two steps to test ordering")

    provenance = {
        "source": f"nf-core/{pipeline}@{revision}",
        "nxf_ver": nxf_ver,
        "dag_sha256": dag_sha256,
        "derivation": derivation,
    }
    items: list[dict[str, Any]] = [{
        "id": f"{pipeline}/whole/001",
        "task": "whole_pipeline",
        "goal": goal,
        "given": [],
        "gold": {"sequence": list(sequence), **provenance},
    }]
    for index in range(len(sequence)):
        items.append({
            "id": f"{pipeline}/next/{index:03d}",
            "task": "next_step",
            "goal": goal,
            "given": list(sequence[:index]),
            "gold": {"next": sequence[index], **provenance},
        })
    return items
