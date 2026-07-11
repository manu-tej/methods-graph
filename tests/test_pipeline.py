"""Tests for the reproducible-build pipeline helpers (offline, deterministic)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import kuzu

from methods_graph.graph.loader import build_graph
from methods_graph.pipeline import (
    build_lock, compute_graph_hash, diff_coverage, load_lock, verify_snapshots, write_lock,
)
from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance


def _graph(ingested: str = "2026-06-19", extra_edge: bool = False):
    P = Provenance("test", "u", ingested)
    nodes = [
        NodeRecord("m:a", "alpha", NodeKind.METHOD, {"x": 1}, P),
        NodeRecord("op:1", "op one", NodeKind.OPERATION, {}, P),
    ]
    edges = [EdgeRecord("m:a", "op:1", EdgeKind.PERFORMS, {}, P)]
    if extra_edge:
        nodes.append(NodeRecord("op:2", "op two", NodeKind.OPERATION, {}, P))
        edges.append(EdgeRecord("m:a", "op:2", EdgeKind.PERFORMS, {}, P))
    return nodes, edges


def _hash(path: Path, nodes, edges) -> str:
    build_graph(nodes, edges, path, staging_dir=path.parent / (path.name + ".stg"))
    conn = kuzu.Connection(kuzu.Database(str(path), read_only=True))
    return compute_graph_hash(conn)


def test_graph_hash_is_deterministic_and_prefixed(tmp_path):
    n, e = _graph()
    h1 = _hash(tmp_path / "a.kuzu", n, e)
    h2 = _hash(tmp_path / "b.kuzu", n, e)
    assert h1 == h2
    assert h1.startswith("sha256:") and len(h1) == len("sha256:") + 64


def test_graph_hash_is_order_independent(tmp_path):
    n, e = _graph()
    h1 = _hash(tmp_path / "a.kuzu", n, e)
    h2 = _hash(tmp_path / "b.kuzu", list(reversed(n)), list(reversed(e)))
    assert h1 == h2


def test_graph_hash_excludes_ingested_at(tmp_path):
    # Same content, different build-date provenance -> SAME hash.
    n1, e1 = _graph(ingested="2026-06-19")
    n2, e2 = _graph(ingested="2099-01-01")
    assert _hash(tmp_path / "a.kuzu", n1, e1) == _hash(tmp_path / "b.kuzu", n2, e2)


def test_graph_hash_is_sensitive_to_content(tmp_path):
    n1, e1 = _graph()
    n2, e2 = _graph(extra_edge=True)
    assert _hash(tmp_path / "a.kuzu", n1, e1) != _hash(tmp_path / "b.kuzu", n2, e2)


def test_verify_snapshots_clean_and_tampered(tmp_path):
    (tmp_path / "EDAM.tsv").write_bytes(b"hello edam")
    good = hashlib.sha256(b"hello edam").hexdigest()
    assert verify_snapshots({"sources": {"edam": {"sha256": good}}}, tmp_path) == []
    bad = verify_snapshots({"sources": {"edam": {"sha256": "deadbeef"}}}, tmp_path)
    assert len(bad) == 1 and bad[0][0] == "edam" and bad[0][2] == good


def test_verify_snapshots_missing_file_reported(tmp_path):
    m = verify_snapshots({"sources": {"obi": {"sha256": "abc"}}}, tmp_path)
    assert m == [("obi", "abc", "MISSING")]


def test_verify_snapshots_skips_unpinned_sources(tmp_path):
    # biocontainers/biotools record tool lists, not a file hash -> skipped, not errored.
    assert verify_snapshots({"sources": {"biocontainers": {"tools": {}}}}, tmp_path) == []


def test_verifiable_sources_lists_only_checksum_pinned():
    from methods_graph.pipeline import verifiable_sources
    sj = {"sources": {
        "edam": {"sha256": "a"}, "obi": {"sha256": "b"}, "stato": {"sha256": "c"},
        "nfcore_modules": {"commit": "d"},
        "biocontainers": {"tools": {}}, "biotools": {"tools": {}},  # unhashed -> excluded
        "nfcore_pipelines": None,
    }}
    assert verifiable_sources(sj) == ["edam", "nfcore_modules", "obi", "stato"]


def test_build_lock_keeps_only_pins_and_roundtrips(tmp_path):
    sj = {"created_at": "2026-06-19T00:00:00Z",
          "sources": {"edam": {"sha256": "abc", "url": "http://x", "rows": 10},
                      "nfcore_modules": {"commit": "deadbeef", "fetched_at": "t"}}}
    lock = build_lock(snapshot_json=sj, ingested_at="2026-06-19",
                      counts={"nodes": 2, "edges": 1}, coverage={"evaluable": 1},
                      graph_hash="sha256:xyz", flags={"db": "data/methods.kuzu"})
    assert lock["schema"] == 1 and lock["graph_hash"] == "sha256:xyz"
    assert lock["sources"]["edam"] == {"sha256": "abc"}            # url/rows stripped
    assert lock["sources"]["nfcore_modules"] == {"commit": "deadbeef"}
    p = tmp_path / "methods.lock.json"
    write_lock(p, lock)
    assert load_lock(p) == lock
    assert load_lock(tmp_path / "absent.json") is None


def test_diff_coverage_baseline_identical_and_delta():
    new = {"counts": {"nodes": 100, "edges": 50}, "coverage": {"evaluable": 5}}
    assert diff_coverage(None, new) == []                          # first build: no baseline
    assert diff_coverage(new, new) == []                           # unchanged: no deltas
    old = {"counts": {"nodes": 90, "edges": 50}, "coverage": {"evaluable": 4}}
    d = diff_coverage(old, new)
    assert ("counts.nodes", 90, 100) in d
    assert ("coverage.evaluable", 4, 5) in d
    assert all(k != "counts.edges" for k, _, _ in d)               # unchanged field omitted


def test_committed_lock_is_valid_if_present():
    """If the repo ships a build lock, it must parse and carry the required keys."""
    p = Path("data/methods.lock.json")
    if not p.exists():
        return
    lock = json.loads(p.read_text())
    assert {"schema", "ingested_at", "graph_hash", "counts", "coverage"} <= set(lock)
    assert str(lock["graph_hash"]).startswith("sha256:")
