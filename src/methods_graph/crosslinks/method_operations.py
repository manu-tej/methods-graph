"""Curated module-context EDAM operation corrections + backfill (review I2 + I1).

bio.tools annotates the *tool* (e.g. ``picard`` the toolkit → "Genetic variation
analysis"), but an nf-core pipeline invokes a specific *subcommand* (the rnaseq
module is ``picard_markduplicates`` → duplicate marking).  So tool-level PERFORMS
edges can be **wrong** for the module context, or **missing** entirely for utility
tools bio.tools doesn't list (``cat``/``gunzip``/``umitools``/…).

This curated layer is applied AFTER bio.tools enrichment:

  * ``remove`` deletes a wrong ``(Method, Operation)`` PERFORMS edge — an edge
    filter, so it does not depend on node existence.
  * ``add`` backfills a correct module-context operation, emitted ONLY when BOTH
    the ``Method`` and the ``Operation`` node exist (never dangling/mistyped);
    any unresolved add is dropped *with a recorded reason*.

Determinism: emitted edges are sorted by ``(method_id, operation_id)``; no clock
or RNG.  The curated map ships as ``method_operations.yaml`` beside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance


def method_operations_path() -> Path:
    """Absolute path to the shipped curated operation map (package data)."""
    return Path(__file__).with_name("method_operations.yaml")


def _opid(raw: str) -> str:
    """Normalise an EDAM operation local name to the graph id (``op:operation_NNNN``)."""
    raw = str(raw).strip()
    return raw if raw.startswith("op:") else f"op:{raw}"


@dataclass(frozen=True)
class OperationEdit:
    """A curated per-method correction: drop wrong ops, add correct ones."""
    method_id: str               # m:<name>
    add: tuple[str, ...] = ()     # op:operation_NNNN to add (backfill / correction)
    remove: tuple[str, ...] = ()  # op:operation_NNNN PERFORMS edges to delete
    note: str = ""


@dataclass
class OperationEditReport:
    """What ``build_operation_edits`` did — every dropped add is recorded."""
    added: int = 0
    removed_keys: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)  # (method, op, reason)


def load_method_operations(path: Path | None = None) -> list[OperationEdit]:
    """Parse the curated YAML into ``OperationEdit`` records (ids normalised).

    Schema::

        methods:
          picard:   {remove: [operation_3197], add: [operation_3963], note: "..."}
          bowtie2:  {add: [operation_3198]}

    Raises ``ValueError`` on a malformed file or a method declaring neither
    ``add`` nor ``remove`` (a no-op entry is almost always a typo).
    """
    path = path or method_operations_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"method_operations: {path} must be a mapping")
    methods = raw.get("methods", {})
    if not isinstance(methods, dict):
        raise ValueError(f"method_operations: 'methods' in {path} must be a mapping")

    edits: list[OperationEdit] = []
    for name, spec in methods.items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise ValueError(f"method_operations: entry {name!r} must be a mapping")
        add = tuple(_opid(o) for o in (spec.get("add") or []))
        remove = tuple(_opid(o) for o in (spec.get("remove") or []))
        if not add and not remove:
            raise ValueError(
                f"method_operations: entry {name!r} has neither 'add' nor 'remove'"
            )
        method_id = str(name).strip()
        method_id = method_id if method_id.startswith("m:") else f"m:{method_id}"
        edits.append(OperationEdit(
            method_id=method_id, add=add, remove=remove,
            note=str(spec.get("note", "") or "").strip(),
        ))
    return sorted(edits, key=lambda e: e.method_id)


def build_operation_edits(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    edits: list[OperationEdit] | None = None,
    path: Path | None = None,
) -> tuple[list[EdgeRecord], set[tuple[str, str, str]], OperationEditReport]:
    """Turn curated edits into (add PERFORMS edges, remove keys, report).

    ``remove`` keys are emitted unconditionally (they are filter keys for the
    caller; a key that matches no edge is a harmless no-op).  ``add`` edges are
    emitted only when both endpoints resolve to the right kinds.
    """
    if edits is None:
        edits = load_method_operations(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = OperationEditReport()
    add_edges: list[EdgeRecord] = []
    remove_keys: set[tuple[str, str, str]] = set()
    prov = Provenance("curated", "", ingested_at)

    pairs: list[tuple[str, str]] = []
    for edit in edits:
        for op_id in edit.remove:
            remove_keys.add((edit.method_id, op_id, EdgeKind.PERFORMS.value))
        for op_id in edit.add:
            pairs.append((edit.method_id, op_id))

    for method_id, op_id in sorted(set(pairs)):
        src = by_id.get(method_id)
        if src is None:
            report.skipped.append((method_id, op_id, "method_missing"))
            continue
        if src.kind != NodeKind.METHOD:
            report.skipped.append((method_id, op_id, f"method_wrong_kind:{src.kind.value}"))
            continue
        dst = by_id.get(op_id)
        if dst is None:
            report.skipped.append((method_id, op_id, "operation_missing"))
            continue
        if dst.kind != NodeKind.OPERATION:
            report.skipped.append((method_id, op_id, f"target_wrong_kind:{dst.kind.value}"))
            continue
        add_edges.append(EdgeRecord(
            method_id, op_id, EdgeKind.PERFORMS, {"basis": "curated"}, prov))

    report.added = len(add_edges)
    report.removed_keys = len(remove_keys)
    return add_edges, remove_keys, report
