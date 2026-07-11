"""Parse the EDAM ontology TSV into typed nodes + IS_A edges."""
from __future__ import annotations

import csv
from pathlib import Path

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance

# Topic_ rows are intentionally NOT ingested: the Topic layer was removed (it was
# coarse domain bucketing, ~90% orphan EDAM-tail, and its only consumers derived
# low-value Canvas fields).  Dropping it here means no Topic nodes and no topic
# IS_A edges (a topic parent simply fails the id_by_uri lookup in pass 2).
_PREFIX_TO_KIND = {
    "operation_": NodeKind.OPERATION,
    "data_": NodeKind.DATA,
    "format_": NodeKind.FORMAT,
}
_KIND_TO_IDPREFIX = {
    NodeKind.OPERATION: "op:",
    NodeKind.DATA: "data:",
    NodeKind.FORMAT: "fmt:",
}


def _classify(class_uri: str) -> tuple[NodeKind, str] | None:
    local = class_uri.rsplit("/", 1)[-1]
    for prefix, kind in _PREFIX_TO_KIND.items():
        if local.startswith(prefix):
            return kind, _KIND_TO_IDPREFIX[kind] + local
    return None


def parse_edam(tsv_path: Path, *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    prov = Provenance("edam", "http://edamontology.org", ingested_at)
    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    id_by_uri: dict[str, str] = {}

    with tsv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    _REQUIRED = {"Class ID", "Preferred Label", "Parents", "Obsolete"}
    if rows:
        missing = _REQUIRED - set(fieldnames)
        if missing:
            raise ValueError(
                f"EDAM TSV missing required columns: {missing}; got {fieldnames}"
            )

    # First pass: nodes + URI→id map (skip obsolete).
    kept: list[dict] = []
    for row in rows:
        if (row.get("Obsolete") or "").strip().upper() == "TRUE":
            continue
        cls = _classify(row["Class ID"])
        if cls is None:
            continue
        kind, node_id = cls
        name = row["Preferred Label"].strip()
        if not name:
            continue
        id_by_uri[row["Class ID"]] = node_id
        props: dict = {"uri": row["Class ID"]}
        # Restore synonyms so keyword search (which scans node properties) matches
        # real alternative terms / acronyms (e.g. "GSEA" for Gene-set enrichment
        # analysis), not just the single Preferred Label.  The TSV "Synonyms" column
        # is pipe-separated; emit a sorted, deduped, non-empty list only when present.
        syns = sorted({
            s.strip() for s in (row.get("Synonyms") or "").split("|") if s.strip()
        })
        if syns:
            props["synonyms"] = syns
        nodes.append(NodeRecord(id=node_id, name=name,
                                kind=kind, properties=props,
                                provenance=prov))
        kept.append(row)

    # Second pass: IS_A edges from Parents (space-separated URIs).
    for row in kept:
        child = id_by_uri[row["Class ID"]]
        for parent_uri in (row.get("Parents") or "").split():
            parent = id_by_uri.get(parent_uri)
            if parent:
                edges.append(EdgeRecord(child, parent, EdgeKind.IS_A, {}, prov))
    return nodes, edges
