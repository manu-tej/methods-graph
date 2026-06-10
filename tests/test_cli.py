"""Tests for the CLI entry points (query, methods, and build subcommands)."""
import json
import pytest
import kuzu
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


def test_cmd_build_biotools_adds_performs_and_has_topic(tmp_path):
    """bio.tools enrichment adds PERFORMS and HAS_TOPIC edges that connect to EDAM nodes.

    Setup:
    - edam_sample.tsv has operation_3798, operation_2495, and topic_3170
    - nfcore/salmon_quant has salmon with biotools_id "salmon" and edam_operations:
        [operation_3798] (but NOT operation_2495)
    - biotools_build/salmon.json maps salmon → operation_3798, operation_2495, topic_3170
      (all three are in edam_sample.tsv so edges survive the loader)

    operation_2495 is present in biotools_build/salmon.json but NOT in salmon_quant/meta.yml,
    so the PERFORMS edge m:salmon -> op:operation_2495 can ONLY come from the bio.tools
    enrichment path.  Its presence proves the enrichment code contributed it.
    """
    db_path = tmp_path / "methods.kuzu"
    cmd_build(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=None,
        biotools=FX / "biotools_build",
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-09",
    )

    # Verify salmon method exists via the provider
    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
    method_names = {m["name"] for m in methods}
    assert "salmon" in method_names, f"salmon not found in methods: {method_names}"

    # Query the kuzu DB directly for PERFORMS and HAS_TOPIC edges from salmon.
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    try:
        # PERFORMS edge: salmon → op:operation_3798 (present in both nf-core and bio.tools)
        performs_rows = list(conn.execute(
            "MATCH (m:Entity {id: 'm:salmon'})-[r:Rel {kind: 'PERFORMS'}]->(op:Entity {id: 'op:operation_3798'}) "
            "RETURN m.id, op.id"
        ))
        assert len(performs_rows) >= 1, (
            f"Expected PERFORMS edge m:salmon -> op:operation_3798; got {performs_rows}"
        )

        # HAS_TOPIC edge: salmon → topic:topic_3170 (present in both nf-core and bio.tools)
        topic_rows = list(conn.execute(
            "MATCH (m:Entity {id: 'm:salmon'})-[r:Rel {kind: 'HAS_TOPIC'}]->(t:Entity {id: 'topic:topic_3170'}) "
            "RETURN m.id, t.id"
        ))
        assert len(topic_rows) >= 1, (
            f"Expected HAS_TOPIC edge m:salmon -> topic:topic_3170; got {topic_rows}"
        )

        # Enrichment-only edge: salmon → op:operation_2495 (bio.tools ONLY — not in meta.yml).
        # This edge can ONLY exist if the bio.tools enrichment path ran successfully.
        enrichment_only_rows = list(conn.execute(
            "MATCH (m:Entity {id: 'm:salmon'})-[r:Rel {kind: 'PERFORMS'}]->(op:Entity {id: 'op:operation_2495'}) "
            "RETURN m.id, op.id"
        ))
        assert len(enrichment_only_rows) >= 1, (
            f"Expected enrichment-only PERFORMS edge m:salmon -> op:operation_2495 "
            f"(proves bio.tools enrichment path ran); got {enrichment_only_rows}"
        )
    finally:
        conn.close()
        db.close()


def test_cmd_build_biotools_missing_path_raises(tmp_path):
    """Passing a non-existent --biotools path raises FileNotFoundError."""
    bogus = tmp_path / "does_not_exist_biotools"
    with pytest.raises(FileNotFoundError):
        cmd_build(
            edam=None,
            nfcore_modules=None,
            biocontainers=None,
            biotools=bogus,
            db_path=tmp_path / "m.kuzu",
            staging_dir=tmp_path / "stg",
            ingested_at="2026-06-09",
        )


def test_cmd_build_biotools_deduplicates_existing_edges(tmp_path, capsys):
    """bio.tools edges that already exist from nf-core are NOT duplicated.

    salmon_quant/meta.yml already has edam_operations: [operation_3798] and
    edam_topics: [topic_3170]. The biotools_build fixture adds the same ones.
    The loaded graph should have exactly one PERFORMS and one HAS_TOPIC for salmon.
    """
    db_path = tmp_path / "methods.kuzu"
    cmd_build(
        edam=FX / "edam_sample.tsv",
        nfcore_modules=FX / "nfcore",
        biocontainers=None,
        biotools=FX / "biotools_build",
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-09",
    )

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    try:
        performs_rows = list(conn.execute(
            "MATCH (m:Entity {id: 'm:salmon'})-[r:Rel {kind: 'PERFORMS'}]->(op:Entity {id: 'op:operation_3798'}) "
            "RETURN m.id, op.id"
        ))
        # Should not be duplicated — exactly 1 edge
        assert len(performs_rows) == 1, (
            f"Expected exactly 1 PERFORMS edge (deduped); got {len(performs_rows)}"
        )
    finally:
        conn.close()
        db.close()


def test_build_uses_tool_directory_identity(tmp_path):
    """Regression test: two bcftools subcommand modules (sort, view) whose meta.yml
    tool keys are generic ('sort', 'view') must BOTH resolve to the single canonical
    method m:bcftools — not to separate m:sort / m:view methods.

    This is the over-merge fix: generic subcommand keys no longer create distinct,
    colliding method ids when the nf-core directory hierarchy is used as the
    authoritative tool identity.
    """
    db_path = tmp_path / "tool_id.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=FX / "nfcore_tool_id",
        biocontainers=None,
        db_path=db_path,
        staging_dir=tmp_path / "stg",
        ingested_at="2026-06-10",
    )

    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()

    method_ids = {m["id"] for m in methods}
    method_names = {m["name"] for m in methods}

    # The canonical tool must be present
    assert "m:bcftools" in method_ids, (
        f"Expected m:bcftools in method ids; got {method_ids}"
    )
    assert "bcftools" in method_names, (
        f"Expected 'bcftools' in method names; got {method_names}"
    )

    # Generic subcommand keys must NOT appear as distinct method ids
    assert "m:sort" not in method_ids, (
        f"m:sort must not exist — generic key should be overridden by directory identity; "
        f"got {method_ids}"
    )
    assert "m:view" not in method_ids, (
        f"m:view must not exist — generic key should be overridden by directory identity; "
        f"got {method_ids}"
    )

    # Only one bcftools method (both subcommand modules collapsed to one)
    assert sum(1 for m in methods if m["name"] == "bcftools") == 1, (
        f"Expected exactly 1 bcftools method; got methods={[m['name'] for m in methods]}"
    )


def test_case_variant_modules_merge_to_one_method(tmp_path):
    """Two single-tool modules whose tool_ids differ only in case
    (tool_id='DESeq2' and tool_id='deseq2') must produce exactly ONE method
    node 'm:deseq2' after building — case-variants collapse because ids are
    lowercased before deduplication in the resolver.

    On macOS (case-insensitive HFS+) we cannot create two real directories
    that differ only in case, so we build the node+edge lists directly via
    parse_module with explicit tool_id values and run resolve+build_graph to
    verify the merge.
    """
    from methods_graph.connectors.nfcore import parse_module
    from methods_graph.resolve.resolver import resolve
    from methods_graph.graph.loader import build_graph
    from methods_graph.types import MethodRecord

    # Shared module directory with a minimal meta.yml
    mod_dir = tmp_path / "deseq2_module"
    mod_dir.mkdir()
    (mod_dir / "meta.yml").write_text(
        "name: deseq2_run\n"
        "tools:\n"
        "  - deseq2:\n"
        "      description: Differential expression analysis\n"
        "      homepage: https://bioconductor.org/packages/DESeq2/\n"
        "input: []\n"
        "output: []\n"
    )
    (mod_dir / "environment.yml").write_text(
        "name: deseq2_env\n"
        "dependencies:\n"
        "  - bioconda::deseq2=1.40.0\n"
    )

    # Simulate two separate parse_module calls with case-variant tool_ids
    nodes_a, edges_a = parse_module(mod_dir, ingested_at="2026-06-10", tool_id="DESeq2")
    nodes_b, edges_b = parse_module(mod_dir, ingested_at="2026-06-10", tool_id="deseq2")

    all_nodes = nodes_a + nodes_b
    all_edges = edges_a + edges_b

    method_nodes = [n for n in all_nodes if isinstance(n, MethodRecord)]
    other_nodes = [n for n in all_nodes if not isinstance(n, MethodRecord)]

    resolved_nodes, resolved_edges = resolve(
        method_nodes=method_nodes,
        other_nodes=other_nodes,
        src_edges=all_edges,
        ingested_at="2026-06-10",
    )

    db_path = tmp_path / "case_merge.kuzu"
    build_graph(resolved_nodes, resolved_edges, db_path, staging_dir=tmp_path / "stg")

    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()

    method_ids = {m["id"] for m in methods}

    # Case-variants must collapse to a single lowercased id
    assert "m:deseq2" in method_ids, (
        f"Expected 'm:deseq2' after case-folding merge; got {method_ids}"
    )
    # No uppercase variant should appear as a separate node
    assert "m:DESeq2" not in method_ids, (
        f"'m:DESeq2' must not exist as a separate node; got {method_ids}"
    )
    # Exactly one deseq2 method (the two case-variants collapsed)
    assert sum(1 for m in methods if m["id"] == "m:deseq2") == 1, (
        f"Expected exactly 1 'm:deseq2' method; got methods={[m['id'] for m in methods]}"
    )
