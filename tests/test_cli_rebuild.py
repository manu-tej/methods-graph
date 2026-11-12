"""CLI tests for `mg rebuild`. The full verify->build->audit->lock path is exercised by
the real `mg rebuild` that produces the committed lock and by CI; here we test the fast,
non-building branches (diff-only, lock loading, error paths)."""
from __future__ import annotations

from methods_graph import cli
from methods_graph.pipeline import build_lock, write_lock


def test_rebuild_diff_only_without_lock_errors(tmp_path, capsys):
    rc = cli.main(["rebuild", "--diff-only", "--db", str(tmp_path / "m.kuzu")])
    assert rc == 1
    assert "no lock" in capsys.readouterr().err


def test_rebuild_diff_only_with_lock_reports_baseline(tmp_path, capsys):
    lock = build_lock(snapshot_json={"sources": {}}, ingested_at="2026-06-19",
                      counts={"nodes": 1, "edges": 0}, coverage={}, graph_hash="sha256:x",
                      flags={})
    write_lock(tmp_path / "methods.lock.json", lock)
    rc = cli.main(["rebuild", "--diff-only", "--db", str(tmp_path / "m.kuzu")])
    assert rc == 0
    # a tmp path has no committed (git HEAD) lock -> baseline, not a crash
    assert "baseline" in capsys.readouterr().out
