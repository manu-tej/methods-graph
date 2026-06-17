"""Curated data-type layer: semantic Method->Data INPUT/OUTPUT edges.

nf-core ``meta.yml`` declares tool I/O by file *pattern* (``*.tsv``, ``*.gz``),
which the connector maps to coarse EDAM **Format** nodes (TSV, GZIP, "Textual
format").  Joining pipelines on those formats produces false handoffs — a raw
count matrix "matches" a functional-enrichment tool just because both touch TSV.

This layer types tool I/O on data **content** instead: a small curated catalog of
canonical RNA-seq data types (count matrix, DE results, gene set, ...) mapped to
EDAM **Data** ids, plus each tool's true ``produces``/``consumes``.  It emits:

  * ``produces`` -> ``Method -[OUTPUT]-> Data``
  * ``consumes`` -> ``Method -[INPUT]->  Data``

Edges are emitted ONLY when both the ``Method`` and the ``Data`` node exist with
the right kinds (never dangling/mistyped); every dropped edge is recorded with a
reason.  Determinism: sorted by ``(method_id, direction, data_id)``; no clock/RNG.
The curated map ships as ``data_types.yaml`` beside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance


def data_types_path() -> Path:
    """Absolute path to the shipped curated data-type map (package data)."""
    return Path(__file__).with_name("data_types.yaml")


def _dataid(raw: str) -> str:
    """Normalise an EDAM data local name to the graph id (``data:data_NNNN``)."""
    raw = str(raw).strip()
    return raw if raw.startswith("data:") else f"data:{raw}"


@dataclass(frozen=True)
class DataIO:
    """A tool's curated content-level I/O (data ids already resolved)."""
    method_id: str                  # m:<name>
    produces: tuple[str, ...] = ()  # data:data_NNNN this tool outputs
    consumes: tuple[str, ...] = ()  # data:data_NNNN this tool inputs


@dataclass
class DataIOReport:
    """What ``build_data_io_edges`` did — every dropped edge is recorded."""
    produced: int = 0
    consumed: int = 0
    skipped: list[tuple[str, str, str, str]] = field(  # (method, data, direction, reason)
        default_factory=list)


def load_data_types(
    path: Path | None = None, *, spec: dict | None = None,
) -> tuple[dict[str, str], list[DataIO]]:
    """Parse the curated YAML into (catalog, io).

    Schema::

        data_types:
          count_matrix: {edam: data_3917, label: "Count matrix"}
        tool_io:
          m:tximeta: {produces: [count_matrix]}
          m:deseq2:  {consumes: [count_matrix], produces: [de_results]}

    ``catalog`` maps a data-type key -> normalised ``data:data_NNNN`` id.  ``io``
    resolves each tool's produce/consume keys through the catalog (a key not in
    the catalog raises — a silent typo would drop the handoff).
    """
    if spec is None:
        path = path or data_types_path()
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(spec, dict):
        raise ValueError("data_types: top level must be a mapping")

    raw_types = spec.get("data_types", {})
    if not isinstance(raw_types, dict):
        raise ValueError("data_types: 'data_types' must be a mapping")
    catalog: dict[str, str] = {}
    for key, entry in raw_types.items():
        entry = entry or {}
        if not isinstance(entry, dict) or not entry.get("edam"):
            raise ValueError(f"data_types: entry {key!r} must declare an 'edam' id")
        catalog[str(key)] = _dataid(entry["edam"])

    def _resolve(keys, method, direction):
        out = []
        for k in keys or []:
            if k not in catalog:
                raise ValueError(
                    f"data_types: {method} {direction} unknown data type {k!r}")
            out.append(catalog[k])
        return tuple(out)

    tool_io = spec.get("tool_io", {})
    if not isinstance(tool_io, dict):
        raise ValueError("data_types: 'tool_io' must be a mapping")
    io: list[DataIO] = []
    for name, entry in tool_io.items():
        entry = entry or {}
        if not isinstance(entry, dict):
            raise ValueError(f"data_types: tool_io {name!r} must be a mapping")
        method_id = str(name).strip()
        method_id = method_id if method_id.startswith("m:") else f"m:{method_id}"
        produces = _resolve(entry.get("produces"), method_id, "produces")
        consumes = _resolve(entry.get("consumes"), method_id, "consumes")
        if not produces and not consumes:
            raise ValueError(
                f"data_types: tool_io {name!r} declares neither produces nor consumes")
        io.append(DataIO(method_id=method_id, produces=produces, consumes=consumes))
    return catalog, sorted(io, key=lambda d: d.method_id)


def build_data_io_edges(
    nodes: list[NodeRecord],
    *,
    ingested_at: str,
    io: list[DataIO] | None = None,
    path: Path | None = None,
) -> tuple[list[EdgeRecord], DataIOReport]:
    """Turn curated I/O into grounded Method->Data INPUT/OUTPUT edges.

    An edge is emitted only when the Method node and the Data node both exist
    with the right kinds; anything unresolved is dropped with a recorded reason.
    """
    if io is None:
        _catalog, io = load_data_types(path)

    by_id: dict[str, NodeRecord] = {n.id: n for n in nodes}
    report = DataIOReport()
    prov = Provenance("curated", "", ingested_at)

    # (method_id, data_id, EdgeKind) flattened + sorted for determinism
    triples: list[tuple[str, str, EdgeKind]] = []
    for d in io:
        for data_id in d.produces:
            triples.append((d.method_id, data_id, EdgeKind.OUTPUT))
        for data_id in d.consumes:
            triples.append((d.method_id, data_id, EdgeKind.INPUT))

    edges: list[EdgeRecord] = []
    for method_id, data_id, kind in sorted(
            set(triples), key=lambda t: (t[0], t[2].value, t[1])):
        src = by_id.get(method_id)
        if src is None:
            report.skipped.append((method_id, data_id, kind.value, "method_missing"))
            continue
        if src.kind != NodeKind.METHOD:
            report.skipped.append(
                (method_id, data_id, kind.value, f"method_wrong_kind:{src.kind.value}"))
            continue
        dst = by_id.get(data_id)
        if dst is None:
            report.skipped.append((method_id, data_id, kind.value, "data_missing"))
            continue
        if dst.kind != NodeKind.DATA:
            report.skipped.append(
                (method_id, data_id, kind.value, f"target_wrong_kind:{dst.kind.value}"))
            continue
        edges.append(EdgeRecord(method_id, data_id, kind, {"basis": "curated"}, prov))

    report.produced = sum(1 for e in edges if e.kind == EdgeKind.OUTPUT)
    report.consumed = sum(1 for e in edges if e.kind == EdgeKind.INPUT)
    return edges, report
