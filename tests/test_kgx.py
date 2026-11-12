"""Tests for src/methods_graph/kgx.py (offline, deterministic, no network)."""
from __future__ import annotations

import csv
from pathlib import Path

import kuzu
import pytest

from methods_graph.cli import main
from methods_graph.graph.loader import build_graph
from methods_graph.kgx import export_kgx
from methods_graph.types import (
    EdgeKind,
    EdgeRecord,
    MethodRecord,
    NodeKind,
    NodeRecord,
    Provenance,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

P = Provenance("nfcore", "https://nf-co.re/modules/salmon", "2026-06-10")
P_OP = Provenance("edam", "http://edamontology.org/operation_3800", "2026-06-10")
P_CTR = Provenance("biocontainers", "https://biocontainers.pro/tools/salmon", "2026-06-10")


def _make_db(tmp_path: Path) -> Path:
    """Build a small 3-node / 2-edge Kùzu DB for KGX tests."""
    nodes = [
        MethodRecord(
            "m:salmon", "salmon", NodeKind.METHOD, {}, P,
            bioconda_pkg="salmon", biotools_id="salmon",
        ),
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P_OP),
        NodeRecord("ctr:salmon", "salmon container", NodeKind.CONTAINER, {}, P_CTR),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3800", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P_CTR),
    ]
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return db_path


def _open_conn(db_path: Path):
    """Return (db, conn) — caller must close both."""
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    return db, conn


# ---------------------------------------------------------------------------
# test_export_writes_node_and_edge_files
# ---------------------------------------------------------------------------


def test_export_writes_node_and_edge_files(tmp_path):
    db_path = _make_db(tmp_path)
    out_dir = tmp_path / "kgx_out"
    db, conn = _open_conn(db_path)
    try:
        node_count, edge_count = export_kgx(conn, out_dir)
    finally:
        conn.close()
        db.close()

    assert (out_dir / "nodes.tsv").exists(), "nodes.tsv must be created"
    assert (out_dir / "edges.tsv").exists(), "edges.tsv must be created"
    assert node_count == 3
    assert edge_count == 2


# ---------------------------------------------------------------------------
# test_nodes_tsv_columns_and_content
# ---------------------------------------------------------------------------


def test_nodes_tsv_columns_and_content(tmp_path):
    db_path = _make_db(tmp_path)
    out_dir = tmp_path / "kgx_out"
    db, conn = _open_conn(db_path)
    try:
        export_kgx(conn, out_dir)
    finally:
        conn.close()
        db.close()

    with open(out_dir / "nodes.tsv", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)

    # Header check
    assert rows[0] == ["id", "name", "category", "source", "source_url", "ingested_at"], (
        f"Unexpected header: {rows[0]}"
    )

    # Find the salmon method row
    salmon_row = next((r for r in rows[1:] if r[0] == "m:salmon"), None)
    assert salmon_row is not None, "m:salmon node must be present"
    assert salmon_row[1] == "salmon", f"name wrong: {salmon_row[1]}"
    assert salmon_row[2] == "Method", f"category should be 'Method', got: {salmon_row[2]}"
    assert salmon_row[3] == "nfcore", f"source should be 'nfcore', got: {salmon_row[3]}"
    assert salmon_row[4] == "https://nf-co.re/modules/salmon", (
        f"source_url wrong: {salmon_row[4]}"
    )
    assert salmon_row[5] == "2026-06-10", f"ingested_at wrong: {salmon_row[5]}"

    # All 3 nodes must be present
    ids = {r[0] for r in rows[1:]}
    assert "m:salmon" in ids
    assert "op:operation_3800" in ids
    assert "ctr:salmon" in ids


# ---------------------------------------------------------------------------
# test_edges_tsv_columns_and_content
# ---------------------------------------------------------------------------


def test_edges_tsv_columns_and_content(tmp_path):
    db_path = _make_db(tmp_path)
    out_dir = tmp_path / "kgx_out"
    db, conn = _open_conn(db_path)
    try:
        export_kgx(conn, out_dir)
    finally:
        conn.close()
        db.close()

    with open(out_dir / "edges.tsv", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)

    # Header check
    assert rows[0] == ["subject", "predicate", "object", "source", "source_url", "ingested_at"], (
        f"Unexpected header: {rows[0]}"
    )

    # Find the PERFORMS row
    performs_row = next(
        (r for r in rows[1:] if r[0] == "m:salmon" and r[1] == "PERFORMS"), None
    )
    assert performs_row is not None, "m:salmon -PERFORMS-> op:operation_3800 must be present"
    assert performs_row[0] == "m:salmon"
    assert performs_row[1] == "PERFORMS"
    assert performs_row[2] == "op:operation_3800"
    # provenance columns should be non-empty (came from P)
    assert performs_row[3] != "", "source must not be empty for PERFORMS edge"
    assert performs_row[4] != "", "source_url must not be empty for PERFORMS edge"
    assert performs_row[5] != "", "ingested_at must not be empty for PERFORMS edge"

    # Both edges must be present
    triples = {(r[0], r[1], r[2]) for r in rows[1:]}
    assert ("m:salmon", "PERFORMS", "op:operation_3800") in triples
    assert ("m:salmon", "PACKAGED_AS", "ctr:salmon") in triples


# ---------------------------------------------------------------------------
# test_export_is_deterministic
# ---------------------------------------------------------------------------


def test_export_is_deterministic(tmp_path):
    db_path = _make_db(tmp_path)
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    for out_dir in (out_a, out_b):
        db, conn = _open_conn(db_path)
        try:
            export_kgx(conn, out_dir)
        finally:
            conn.close()
            db.close()

    nodes_a = (out_a / "nodes.tsv").read_bytes()
    nodes_b = (out_b / "nodes.tsv").read_bytes()
    assert nodes_a == nodes_b, "nodes.tsv is not byte-identical across two exports"

    edges_a = (out_a / "edges.tsv").read_bytes()
    edges_b = (out_b / "edges.tsv").read_bytes()
    assert edges_a == edges_b, "edges.tsv is not byte-identical across two exports"


# ---------------------------------------------------------------------------
# test_null_provenance_exported_as_empty_string
# ---------------------------------------------------------------------------


def test_null_provenance_exported_as_empty_string(tmp_path):
    """Nodes/edges with no provenance must export empty strings, not 'None'."""
    nodes = [NodeRecord("op:x", "X", NodeKind.OPERATION, {}, None)]
    edges = []
    db_path = tmp_path / "null_prov.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")

    out_dir = tmp_path / "kgx_out"
    db, conn = _open_conn(db_path)
    try:
        export_kgx(conn, out_dir)
    finally:
        conn.close()
        db.close()

    with open(out_dir / "nodes.tsv", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)

    node_row = next((r for r in rows[1:] if r[0] == "op:x"), None)
    assert node_row is not None
    assert node_row[3] != "None", "source should be empty string, not 'None'"
    assert node_row[4] != "None", "source_url should be empty string, not 'None'"
    assert node_row[5] != "None", "ingested_at should be empty string, not 'None'"


# ---------------------------------------------------------------------------
# test_cli_export_kgx
# ---------------------------------------------------------------------------


def test_cli_export_kgx(tmp_path):
    db_path = _make_db(tmp_path)
    out_dir = tmp_path / "cli_kgx_out"

    rc = main(["export-kgx", "--db", str(db_path), "--out", str(out_dir)])
    assert rc == 0, f"main() returned non-zero exit code: {rc}"

    assert (out_dir / "nodes.tsv").exists(), "CLI must create nodes.tsv"
    assert (out_dir / "edges.tsv").exists(), "CLI must create edges.tsv"

    # Verify headers via CLI-produced files
    with open(out_dir / "nodes.tsv", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
    assert header == ["id", "name", "category", "source", "source_url", "ingested_at"]

    with open(out_dir / "edges.tsv", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
    assert header == ["subject", "predicate", "object", "source", "source_url", "ingested_at"]
