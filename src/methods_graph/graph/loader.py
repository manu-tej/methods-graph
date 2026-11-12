"""Build a fresh Kùzu DB from canonical node/edge records via Parquet COPY."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)

import kuzu
import polars as pl

from methods_graph.graph import schema
from methods_graph.types import EdgeRecord, NodeRecord


def _node_row(n: NodeRecord) -> dict:
    row = n.to_row()
    row.setdefault("bioconda_pkg", "")
    row.setdefault("biotools_id", "")
    row.setdefault("source", "")
    row.setdefault("source_url", "")
    row.setdefault("ingested_at", "")
    return {c: row.get(c, "") for c in schema.NODE_COLUMNS}


def _edge_row(e: EdgeRecord) -> dict:
    row = e.to_row()
    row.setdefault("source", "")
    row.setdefault("source_url", "")
    row.setdefault("ingested_at", "")
    return {c: row.get(c, "") for c in schema.REL_COLUMNS}


def build_graph(nodes: list[NodeRecord], edges: list[EdgeRecord],
                db_path: Path, *, staging_dir: Path) -> dict:
    """Build a fresh Kùzu DB.

    Returns a summary dict with keys ``nodes``, ``edges_loaded``, and
    ``edges_dropped`` so callers can report honest counts.
    """
    db_path = Path(db_path)
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Idempotent: drop any prior DB so a rebuild yields an identical graph.
    if db_path.exists():
        shutil.rmtree(db_path) if db_path.is_dir() else db_path.unlink()
    # Remove any WAL/shadow/lock files kuzu left from a prior crashed build (else
    # it replays).  Skip directories: this cleanup targets FILES only, and the
    # default staging dir (cmd_build uses '<db>.staging') matches this glob —
    # unlinking a directory raises EPERM ("Operation not permitted") on macOS.
    for sib in db_path.parent.glob(db_path.name + ".*"):
        if sib.is_dir():
            continue
        sib.unlink(missing_ok=True)

    node_ids = {n.id for n in nodes}
    # Drop dangling edges whose endpoints are not in the current node set.
    valid_edges = [e for e in edges if e.from_id in node_ids and e.to_id in node_ids]
    dropped = len(edges) - len(valid_edges)
    if dropped:
        _log.warning(
            "build_graph: dropped %d dangling edge(s) whose endpoints are not in the node set",
            dropped,
        )

    nodes_pq = staging_dir / "nodes.parquet"
    edges_pq = staging_dir / "edges.parquet"
    pl.DataFrame([_node_row(n) for n in nodes],
                 schema=schema.NODE_COLUMNS).write_parquet(nodes_pq)

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    try:
        conn.execute(schema.NODE_TABLE)
        conn.execute(schema.REL_TABLE)
        conn.execute(f'COPY Entity FROM "{nodes_pq.as_posix()}"')
        if valid_edges:
            pl.DataFrame([_edge_row(e) for e in valid_edges],
                         schema=schema.REL_COLUMNS).write_parquet(edges_pq)
            conn.execute(f'COPY Rel FROM "{edges_pq.as_posix()}"')
    finally:
        conn.close()
        db.close()

    return {"nodes": len(nodes), "edges_loaded": len(valid_edges), "edges_dropped": dropped}
