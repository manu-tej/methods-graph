"""Roll up DOWNSTREAM_OF attestation metadata after resolution.

Runs AFTER resolve() (which already remaps ids and dedupes (from,to,kind)).
This step is metadata accumulation ONLY, not deduplication.
"""
from __future__ import annotations

from methods_graph.types import EdgeKind, EdgeRecord


def merge_downstream_of(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    """Return a new edge list with DOWNSTREAM_OF edges sharing (from,to)
    collapsed into one whose ``pipelines`` is the sorted/deduped union,
    ``attestations`` is its length, and ``confidence`` is the max. All other
    edges pass through unchanged and in their original order."""
    out: list[EdgeRecord] = []
    by_pair: dict[tuple[str, str], EdgeRecord] = {}
    for e in edges:
        if e.kind != EdgeKind.DOWNSTREAM_OF:
            out.append(e)
            continue
        key = (e.from_id, e.to_id)
        if key not in by_pair:
            # Copy so the input list is never mutated.
            merged = EdgeRecord(e.from_id, e.to_id, e.kind,
                                dict(e.properties), e.provenance)
            merged.properties.setdefault("pipelines", [])
            merged.properties["pipelines"] = sorted(set(merged.properties["pipelines"]))
            merged.properties["attestations"] = len(merged.properties["pipelines"])
            by_pair[key] = merged
            out.append(merged)
        else:
            merged = by_pair[key]
            pipes = set(merged.properties.get("pipelines", [])) | \
                set(e.properties.get("pipelines", []))
            merged.properties["pipelines"] = sorted(pipes)
            merged.properties["attestations"] = len(pipes)
            merged.properties["confidence"] = max(
                merged.properties.get("confidence", 0.0),
                e.properties.get("confidence", 0.0),
            )
    return out
