"""Tests for src/methods_graph/audit.py (fixture-based, offline, no network)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import kuzu
import pytest

from methods_graph.audit import AuditResult, Invariant, audit_graph
from methods_graph.graph.loader import build_graph
from methods_graph.types import (
    EdgeKind,
    EdgeRecord,
    MethodRecord,
    NodeKind,
    NodeRecord,
    Provenance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

P = Provenance("test", "https://example.com/test", "2026-06-10")
P_NULL = None  # used for missing-provenance tests


def _make_db(tmp_path: Path, nodes: list, edges: list) -> Path:
    """Build a Kùzu DB and return its path."""
    db_path = tmp_path / "test.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return db_path


def _open_conn(db_path: Path):
    """Return (db, conn) — caller is responsible for closing both."""
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    return db, conn


# ---------------------------------------------------------------------------
# test_audit_clean_graph_passes
# ---------------------------------------------------------------------------


def test_audit_clean_graph_passes(tmp_path):
    """A small, structurally valid graph should produce ok=True with correct counts."""
    nodes = [
        MethodRecord(
            "m:salmon", "salmon", NodeKind.METHOD, {}, P,
            bioconda_pkg="salmon", biotools_id="salmon",
        ),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_3170", "RNA-Seq", NodeKind.TOPIC, {}, P),
        NodeRecord("cnt:salmon_1.10.0", "salmon:1.10.0", NodeKind.CONTAINER, {}, P),
        NodeRecord("fmt:data_2044", "Sequence", NodeKind.FORMAT, {}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "topic:topic_3170", EdgeKind.HAS_TOPIC, {}, P),
        EdgeRecord("m:salmon", "cnt:salmon_1.10.0", EdgeKind.PACKAGED_AS, {}, P),
        EdgeRecord("m:salmon", "fmt:data_2044", EdgeKind.INPUT, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, edges)
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    assert result.ok is True
    assert all(inv.ok for inv in result.invariants)
    assert result.duplicate_ids_ok is True
    assert result.provenance_missing == 0

    # Coverage counts
    cov = result.coverage
    assert cov["methods_total"] == 1
    assert cov["with_biotools_id"]["count"] == 1
    assert cov["with_bioconda_pkg"]["count"] == 1
    assert cov["with_container"]["count"] == 1
    assert cov["with_edam_operation"]["count"] == 1
    assert cov["with_topic"]["count"] == 1
    assert cov["with_io_contract"]["count"] == 1

    # No SAME_AS edges
    assert result.same_as["total"] == 0

    # Reconciliation not requested
    assert result.reconciliation is None


# ---------------------------------------------------------------------------
# test_audit_detects_invalid_edge_kind
# ---------------------------------------------------------------------------


def test_audit_detects_invalid_edge_kind(tmp_path):
    """A PERFORMS edge from Method→Container violates the PERFORMS invariant."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P),
        NodeRecord("cnt:salmon_1.10.0", "salmon:1.10.0", NodeKind.CONTAINER, {}, P),
    ]
    # PERFORMS should only go Method→Operation; pointing it at a Container is invalid
    edges = [
        EdgeRecord("m:salmon", "cnt:salmon_1.10.0", EdgeKind.PERFORMS, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, edges)
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    assert result.ok is False
    performs_inv = next(inv for inv in result.invariants if "PERFORMS" in inv.name and "IS_A" not in inv.name)
    assert not performs_inv.ok
    assert performs_inv.violations >= 1


# ---------------------------------------------------------------------------
# test_audit_detects_missing_provenance
# ---------------------------------------------------------------------------


def test_audit_detects_missing_provenance(tmp_path):
    """A node with no provenance source should be flagged, making ok=False."""
    # Build one node with provenance, one without
    good_node = NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P)
    bad_node = NodeRecord("op:operation_0001", "Unknown op", NodeKind.OPERATION, {}, P_NULL)
    db_path = _make_db(tmp_path, [good_node, bad_node], [])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    assert result.provenance_missing > 0
    assert result.ok is False


# ---------------------------------------------------------------------------
# test_audit_counts_same_as
# ---------------------------------------------------------------------------


def test_audit_counts_same_as(tmp_path):
    """A SAME_AS edge with basis='biotools_id' is counted in by_basis correctly."""
    method_a = MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P, biotools_id="salmon")
    method_b = MethodRecord("m:salmon_ng", "salmon-ng", NodeKind.METHOD, {}, P, biotools_id="salmon")
    same_as_edge = EdgeRecord(
        "m:salmon", "m:salmon_ng", EdgeKind.SAME_AS,
        {"basis": "biotools_id"}, P,
    )
    db_path = _make_db(tmp_path, [method_a, method_b], [same_as_edge])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    assert result.same_as["total"] == 1
    assert result.same_as["by_basis"].get("biotools_id", 0) == 1


# ---------------------------------------------------------------------------
# test_audit_coverage_metrics
# ---------------------------------------------------------------------------


def test_audit_coverage_metrics(tmp_path):
    """Two-method graph: one enriched, one bare. Coverage counts should reflect this."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P, bioconda_pkg="salmon"),
        MethodRecord("m:bare", "bare", NodeKind.METHOD, {}, P),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
        NodeRecord("cnt:salmon_1.10.0", "salmon:1.10.0", NodeKind.CONTAINER, {}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "cnt:salmon_1.10.0", EdgeKind.PACKAGED_AS, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, edges)
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    cov = result.coverage
    assert cov["methods_total"] == 2
    assert cov["with_edam_operation"]["count"] == 1
    assert cov["with_edam_operation"]["pct"] == 50.0
    assert cov["with_container"]["count"] == 1
    assert cov["with_container"]["pct"] == 50.0
    assert cov["with_bioconda_pkg"]["count"] == 1
    assert cov["with_bioconda_pkg"]["pct"] == 50.0
    # bare method has nothing
    assert cov["with_topic"]["count"] == 0
    assert cov["with_io_contract"]["count"] == 0


# ---------------------------------------------------------------------------
# test_audit_reconciliation_edam  (two variants: match=True and mismatch)
# ---------------------------------------------------------------------------


def _write_edam_tsv(path: Path, rows: list[dict]) -> None:
    """Write a minimal EDAM TSV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("Class ID\tPreferred Label\tParents\tObsolete\n")
        for r in rows:
            f.write(
                f"http://edamontology.org/{r['local']}\t"
                f"{r.get('label', r['local'])}\t\t"
                f"{r.get('obsolete', 'FALSE')}\n"
            )


def test_audit_reconciliation_edam_match(tmp_path):
    """Graph nodes match TSV counts → reconciliation match=True for loaded kinds."""
    snap = tmp_path / "snap"
    # Two operations + one topic; one obsolete operation (should be excluded from count)
    _write_edam_tsv(snap / "EDAM.tsv", [
        {"local": "operation_0001", "label": "Op1"},
        {"local": "operation_0002", "label": "Op2"},
        {"local": "operation_0003", "label": "ObsoleteOp", "obsolete": "TRUE"},
        {"local": "topic_0001", "label": "Topic1"},
    ])
    # Build graph with exactly 2 Operation nodes and 1 Topic node (matching non-obsolete TSV counts)
    nodes = [
        NodeRecord("op:operation_0001", "Op1", NodeKind.OPERATION, {}, P),
        NodeRecord("op:operation_0002", "Op2", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_0001", "Topic1", NodeKind.TOPIC, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, [])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn, snapshot_dir=snap)
    finally:
        conn.close()
        db.close()

    assert result.reconciliation is not None
    edam = result.reconciliation["edam"]
    assert edam["operation"]["tsv"] == 2
    assert edam["operation"]["graph"] == 2
    assert edam["operation"]["match"] is True
    assert edam["topic"]["tsv"] == 1
    assert edam["topic"]["match"] is True
    # data/format: tsv=0, graph=0 → match
    assert edam["data"]["match"] is True
    assert edam["format"]["match"] is True
    # ok should still be True (all pass)
    assert result.ok is True


def test_audit_reconciliation_edam_mismatch(tmp_path):
    """TSV has 2 operations but graph has only 1 → match=False and ok=False."""
    snap = tmp_path / "snap"
    _write_edam_tsv(snap / "EDAM.tsv", [
        {"local": "operation_0001", "label": "Op1"},
        {"local": "operation_0002", "label": "Op2"},
    ])
    # Graph has only ONE operation (missing operation_0002)
    nodes = [
        NodeRecord("op:operation_0001", "Op1", NodeKind.OPERATION, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, [])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn, snapshot_dir=snap)
    finally:
        conn.close()
        db.close()

    assert result.reconciliation is not None
    edam = result.reconciliation["edam"]
    assert edam["operation"]["match"] is False
    assert result.ok is False


# ---------------------------------------------------------------------------
# test_audit_isa_cross_kind_edam_is_valid
# ---------------------------------------------------------------------------


def test_audit_isa_cross_kind_edam_is_valid(tmp_path):
    """IS_A edge from an Operation to a Topic (cross-kind EDAM) must NOT be a violation.

    EDAM itself carries cross-branch subClassOf edges (e.g. operation_3923 →
    topic_3168).  Our graph faithfully represents that, so the IS_A invariant
    must accept any IS_A where both endpoints are EDAM classes.
    """
    nodes = [
        NodeRecord("op:operation_3923", "Genome resequencing", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_3168", "Sequencing", NodeKind.TOPIC, {}, P),
    ]
    edges = [
        EdgeRecord("op:operation_3923", "topic:topic_3168", EdgeKind.IS_A, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, edges)
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    isa_inv = next(inv for inv in result.invariants if "IS_A" in inv.name)
    assert isa_inv.ok is True, (
        f"Cross-kind EDAM IS_A should not be a violation, got {isa_inv.violations}"
    )
    assert result.ok is True


def test_audit_isa_non_edam_endpoint_is_violation(tmp_path):
    """IS_A edge whose source is a Method (not an EDAM class) must be a violation."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
    ]
    edges = [
        # A Method as IS_A source is structurally wrong — only EDAM hierarchy edges
        # should use IS_A.
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.IS_A, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, edges)
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    isa_inv = next(inv for inv in result.invariants if "IS_A" in inv.name)
    assert not isa_inv.ok, "Method→Operation IS_A should be a violation"
    assert isa_inv.violations >= 1
    assert result.ok is False


# ---------------------------------------------------------------------------
# test_audit_to_json_roundtrips
# ---------------------------------------------------------------------------


def test_audit_to_json_roundtrips(tmp_path):
    """to_dict() must be JSON-serialisable and contain the expected top-level keys."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, [])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    d = result.to_dict()
    # Must serialise without error
    serialised = json.dumps(d)
    parsed = json.loads(serialised)

    expected_keys = {
        "node_count", "distinct_ids", "duplicate_ids_ok", "provenance_missing",
        "invariants", "same_as", "coverage", "reconciliation", "ok",
    }
    assert expected_keys <= set(parsed.keys()), (
        f"Missing keys: {expected_keys - set(parsed.keys())}"
    )
    assert isinstance(parsed["invariants"], list)
    assert isinstance(parsed["coverage"], dict)
    assert "methods_total" in parsed["coverage"]


# ---------------------------------------------------------------------------
# test_audit_to_text_format
# ---------------------------------------------------------------------------


def test_audit_to_text_format(tmp_path):
    """to_text() should include expected section headers and final AUDIT RESULT line."""
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P),
    ]
    db_path = _make_db(tmp_path, nodes, [])
    db, conn = _open_conn(db_path)
    try:
        result = audit_graph(conn)
    finally:
        conn.close()
        db.close()

    text = result.to_text()
    assert "SCHEMA INVARIANTS" in text
    assert "PROVENANCE" in text
    assert "AUDIT RESULT:" in text
    # With no issues except missing provenance on the method (provenance IS set)
    # so we expect PASS or FAILED in the result line
    assert "ALL CHECKS PASSED" in text or "CHECK(S) FAILED" in text
