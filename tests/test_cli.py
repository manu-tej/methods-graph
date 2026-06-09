"""Tests for the CLI entry points (query and methods subcommands)."""
import json
from pathlib import Path
from methods_graph.cli import cmd_query
from methods_graph.types import MethodRecord, NodeKind, Provenance
from methods_graph.graph.loader import build_graph

P = Provenance("test", "x", "2026-06-08")


def test_cmd_query_prints_rag_text(tmp_path, capsys):
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                          {"version": "1.10.0"}, P, bioconda_pkg="salmon")]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")
    cmd_query(db_path=db_path, keywords=["salmon"], k_hops=1)
    out = capsys.readouterr().out
    assert "salmon" in out
