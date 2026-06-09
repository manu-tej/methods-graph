"""Build a fresh Kùzu DB from canonical node/edge records via Parquet COPY."""
from __future__ import annotations

import shutil
from pathlib import Path

import kuzu
import polars as pl

from methods_graph.graph import schema
from methods_graph.types import EdgeRecord, MethodRecord, NodeRecord


def _node_row(n: NodeRecord) -> dict:
    row = n.to_row()
    row.setdefault("bioconda_pkg", n.bioconda_pkg if isinstance(n, MethodRecord) else "")
    row.setdefault("biotools_id", n.biotools_id if isinstance(n, MethodRecord) else "")
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
                db_path: Path, *, staging_dir: Path) -> None:
    db_path = Path(db_path)
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Idempotent: drop any prior DB so a rebuild yields an identical graph.
    if db_path.exists():
        shutil.rmtree(db_path) if db_path.is_dir() else db_path.unlink()

    nodes_pq = staging_dir / "nodes.parquet"
    edges_pq = staging_dir / "edges.parquet"
    pl.DataFrame([_node_row(n) for n in nodes],
                 schema=schema.NODE_COLUMNS).write_parquet(nodes_pq)

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    conn.execute(schema.NODE_TABLE)
    conn.execute(schema.REL_TABLE)
    conn.execute(f'COPY Entity FROM "{nodes_pq.as_posix()}"')
    if edges:
        pl.DataFrame([_edge_row(e) for e in edges],
                     schema=schema.REL_COLUMNS).write_parquet(edges_pq)
        conn.execute(f'COPY Rel FROM "{edges_pq.as_posix()}"')
    conn.close()
    db.close()
