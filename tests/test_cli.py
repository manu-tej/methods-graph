"""Tests for the CLI entry points (query, methods, and build subcommands)."""
import json
import pytest
from pathlib import Path
from methods_graph.cli import cmd_query, cmd_build, main
from methods_graph.types import MethodRecord, NodeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

P = Provenance("test", "x", "2026-06-08")

# Path to the shared test fixtures directory
FX = Path(__file__).parent / "fixtures"


def test_cmd_query_prints_rag_text(tmp_path, capsys):
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                          {"version": "1.10.0"}, P, bioconda_pkg="salmon")]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")
    cmd_query(db_path=db_path, keywords=["salmon"], k_hops=1)
    out = capsys.readouterr().out
    assert "salmon" in out


def test_cmd_build_end_to_end(tmp_path):
    """Build from all sources and assert key nodes exist in the graph."""
    db_path = tmp_path / "methods.kuzu"
    cmd_build(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=FX / "biocontainers",
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-08",
    )
    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
    method_by_name = {m["name"]: m for m in methods}
    method_names = {m["name"] for m in methods}

    # salmon should exist with RNA-Seq tag and container image
    assert "salmon" in method_by_name, f"salmon not found; methods: {list(method_by_name)}"
    salmon = method_by_name["salmon"]
    assert "RNA-Seq" in salmon["tags"], f"expected EDAM RNA-Seq tag; got {salmon['tags']}"
    assert "salmon:1.10.0" in salmon["compute_requirements"]["container_image"]

    # Cross-module dedup: samtools appears in BOTH samtools_stats and samtools_helper;
    # union-find must collapse them to exactly ONE canonical samtools method.
    assert sum(1 for m in methods if m["name"] == "samtools") == 1, (
        f"expected exactly 1 samtools after cross-module merge; got methods: {list(method_by_name)}"
    )

    # All four expected methods must be present:
    #   - salmon (from salmon_quant)
    #   - samtools (merged from samtools_stats + samtools_helper)
    #   - bcftools (from samtools_stats)
    #   - helperscript (keyless method from samtools_helper — must NOT be dropped)
    assert {"salmon", "samtools", "bcftools", "helperscript"} <= method_names, (
        f"expected {{salmon, samtools, bcftools, helperscript}} in methods; got {method_names}"
    )


def test_cmd_build_is_deterministic(tmp_path):
    """Building the same sources twice produces identical method id sets."""
    db_path_1 = tmp_path / "methods1.kuzu"
    db_path_2 = tmp_path / "methods2.kuzu"

    cmd_build(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=FX / "biocontainers",
        staging_dir=tmp_path / "stg1",
        db_path=db_path_1,
        ingested_at="2026-06-08",
    )
    cmd_build(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=FX / "biocontainers",
        staging_dir=tmp_path / "stg2",
        db_path=db_path_2,
        ingested_at="2026-06-08",
    )

    with KuzuMethodsGraphProvider(db_path_1) as p1:
        ids_1 = sorted(m["id"] for m in p1.get_methods())
    with KuzuMethodsGraphProvider(db_path_2) as p2:
        ids_2 = sorted(m["id"] for m in p2.get_methods())

    assert ids_1 == ids_2, f"Non-deterministic build: {ids_1} vs {ids_2}"


def test_cmd_build_partial_sources(tmp_path):
    """Build with only nf-core modules (no EDAM, no biocontainers) succeeds."""
    db_path = tmp_path / "methods.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=FX / "nfcore",
        biocontainers=None,
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-08",
    )
    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
    method_names = {m["name"] for m in methods}
    assert "salmon" in method_names, f"Expected salmon in methods: {method_names}"


def test_cmd_build_missing_path_raises(tmp_path):
    """Passing a non-existent path for any source raises FileNotFoundError."""
    bogus = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        cmd_build(
            edam=None,
            nfcore_modules=None,
            biocontainers=bogus,
            db_path=tmp_path / "m.kuzu",
            staging_dir=tmp_path / "stg",
            ingested_at="2026-06-08",
        )
    with pytest.raises(FileNotFoundError):
        cmd_build(
            edam=None,
            nfcore_modules=bogus,
            biocontainers=None,
            db_path=tmp_path / "m.kuzu",
            staging_dir=tmp_path / "stg",
            ingested_at="2026-06-08",
        )
    with pytest.raises(FileNotFoundError):
        cmd_build(
            edam=bogus,
            nfcore_modules=None,
            biocontainers=None,
            db_path=tmp_path / "m.kuzu",
            staging_dir=tmp_path / "stg",
            ingested_at="2026-06-08",
        )


def test_cmd_build_discovers_nested_modules(tmp_path):
    """Recursive rglob discovery finds modules at any nesting depth.

    nfcore_nested/ layout:
      salmon/quant/meta.yml   -- 2-level nested module (tool: salmon)
      fastqc/meta.yml         -- 1-level nested module (tool: fastqc)

    Both must be discovered and loaded into the graph.
    """
    db_path = tmp_path / "nested.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=FX / "nfcore_nested",
        biocontainers=None,
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-09",
    )
    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
    method_names = {m["name"] for m in methods}
    assert "salmon" in method_names, f"Expected salmon in methods from nested fixture; got {method_names}"
    assert "fastqc" in method_names, f"Expected fastqc in methods from nested fixture; got {method_names}"


def test_main_build_subcommand(tmp_path):
    """main() with build subcommand returns 0 and creates the db."""
    db_path = tmp_path / "m.kuzu"
    stg_path = tmp_path / "s"
    result = main([
        "build",
        "--edam", str(FX / "edam_sample.tsv"),
        "--nfcore-modules", str(FX / "nfcore"),
        "--biocontainers", str(FX / "biocontainers"),
        "--db", str(db_path),
        "--staging", str(stg_path),
        "--ingested-at", "2026-06-08",
    ])
    assert result == 0
    assert db_path.exists()
