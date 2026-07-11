"""KGX TSV export for the methods graph.

Writes KGX-compatible TSV files (Knowledge Graph eXchange format):
  nodes.tsv  — header: id, name, category, source, source_url, ingested_at
  edges.tsv  — header: subject, predicate, object, source, source_url, ingested_at

Usage::

    from methods_graph.kgx import export_kgx
    node_count, edge_count = export_kgx(conn, Path("out/"))
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import kuzu

_NODE_HEADER = ["id", "name", "category", "source", "source_url", "ingested_at"]
_EDGE_HEADER = ["subject", "predicate", "object", "source", "source_url", "ingested_at"]


def _sanitize(value: object) -> str:
    """Convert a field value to a tab/newline-safe string.

    - None / empty → empty string (never the literal "None")
    - Replaces embedded ``\\t``, ``\\n``, ``\\r`` with a single space.
    """
    if value is None:
        return ""
    s = str(value)
    if s == "None":
        return ""
    # Replace tab and newline variants with a single space for TSV safety.
    s = s.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return s


def export_kgx(conn: "kuzu.Connection", out_dir: Path) -> tuple[int, int]:
    """Export the Kùzu graph to KGX TSV format.

    Parameters
    ----------
    conn:
        An open ``kuzu.Connection`` to the database.
    out_dir:
        Destination directory.  Created (including parents) if it does not
        exist.

    Returns
    -------
    tuple[int, int]
        ``(node_count, edge_count)`` — number of rows written (excluding header).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    res = conn.execute(
        "MATCH (n:Entity) "
        "RETURN n.id, n.name, n.kind, n.source, n.source_url, n.ingested_at"
    )
    node_rows: list[list[str]] = []
    for row in res:
        node_id, name, kind, source, source_url, ingested_at = row
        node_rows.append([
            _sanitize(node_id),
            _sanitize(name),
            _sanitize(kind),
            _sanitize(source),
            _sanitize(source_url),
            _sanitize(ingested_at),
        ])

    # Sort by id for determinism.
    node_rows.sort(key=lambda r: r[0])

    with (out_dir / "nodes.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(_NODE_HEADER)
        writer.writerows(node_rows)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------
    res = conn.execute(
        "MATCH (a:Entity)-[r:Rel]->(b:Entity) "
        "RETURN a.id, r.kind, b.id, r.source, r.source_url, r.ingested_at"
    )
    edge_rows: list[list[str]] = []
    for row in res:
        subject, predicate, obj, source, source_url, ingested_at = row
        edge_rows.append([
            _sanitize(subject),
            _sanitize(predicate),
            _sanitize(obj),
            _sanitize(source),
            _sanitize(source_url),
            _sanitize(ingested_at),
        ])

    # Sort by (subject, predicate, object) for determinism.
    edge_rows.sort(key=lambda r: (r[0], r[1], r[2]))

    with (out_dir / "edges.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(_EDGE_HEADER)
        writer.writerows(edge_rows)

    return len(node_rows), len(edge_rows)
