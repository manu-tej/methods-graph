"""Tests for the CLI entry points (query, methods, and build subcommands)."""
import json
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

    # salmon should exist with RNA-Seq tag and container image
    assert "salmon" in method_by_name, f"salmon not found; methods: {list(method_by_name)}"
    salmon = method_by_name["salmon"]
    assert any("RNA-Seq" in t or "rna" in t.lower() for t in salmon["tags"]) or \
           any("salmon" in t.lower() for t in salmon["tags"]) or \
           salmon["compute_requirements"].get("container_image", "").find("salmon") != -1, \
        f"Expected salmon tags or container_image to mention salmon: tags={salmon['tags']}, compute={salmon['compute_requirements']}"
    container_image = salmon["compute_requirements"].get("container_image", "")
    assert "salmon:1.10.0" in container_image, \
        f"Expected container_image to contain 'salmon:1.10.0', got: {container_image!r}"

    # samtools and bcftools should exist from the multi-tool samtools_stats module
    assert "samtools" in method_by_name, f"samtools not found; methods: {list(method_by_name)}"
    assert "bcftools" in method_by_name, f"bcftools not found; methods: {list(method_by_name)}"


def test_cmd_build_is_deterministic(tmp_path):
    """Building the same sources twice produces identical method id sets."""
    db_path_1 = tmp_path / "methods1.kuzu"
    db_path_2 = tmp_path / "methods2.kuzu"

    kwargs = dict(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=FX / "biocontainers",
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-08",
    )

    cmd_build(db_path=db_path_1, **kwargs)
    cmd_build(db_path=db_path_2, **kwargs)

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
