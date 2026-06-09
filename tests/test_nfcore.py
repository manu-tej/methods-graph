from pathlib import Path
from methods_graph.connectors.nfcore import parse_module
from methods_graph.types import NodeKind, EdgeKind

MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "salmon_quant"
MULTIDEP_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "multidep_quant"
MULTI_TOOL_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_stats"
SAMTOOLS_HELPER_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_helper"


def test_parse_module_creates_method_with_join_keys():
    nodes, _ = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.name == "salmon"
    assert method.bioconda_pkg == "salmon"
    assert method.biotools_id == "salmon"
    assert method.properties["version"] == "1.10.0"


def test_parse_module_links_to_edam():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    performs = [e for e in edges if e.kind == EdgeKind.PERFORMS]
    has_topic = [e for e in edges if e.kind == EdgeKind.HAS_TOPIC]
    assert any(e.from_id == method.id and e.to_id == "op:operation_3798" for e in performs)
    assert any(e.from_id == method.id and e.to_id == "topic:topic_3170" for e in has_topic)


def test_parse_module_emits_module_and_wraps_edge():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    module = next(n for n in nodes if n.kind == NodeKind.MODULE)
    assert module.name == "salmon_quant"
    assert any(e.kind == EdgeKind.WRAPS and e.from_id == module.id for e in edges)


def test_parse_module_matches_dep_to_tool_name():
    """When environment.yml lists a secondary dep (htslib) before salmon,
    the resolver must pick salmon — not htslib — as bioconda_pkg/version."""
    nodes, _ = parse_module(MULTIDEP_MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.bioconda_pkg == "salmon"
    assert method.properties["version"] == "1.10.0"


# ---------------------------------------------------------------------------
# Multi-tool module tests (samtools_stats fixture)
# ---------------------------------------------------------------------------

def test_parse_module_ingests_all_tools():
    """Module with two tools emits 2 Method nodes and 2 WRAPS edges."""
    nodes, edges = parse_module(MULTI_TOOL_MODULE, ingested_at="2026-06-09")
    method_nodes = [n for n in nodes if n.kind == NodeKind.METHOD]
    method_ids = {n.id for n in method_nodes}
    assert method_ids == {"m:samtools", "m:bcftools"}

    module = next(n for n in nodes if n.kind == NodeKind.MODULE)
    wraps_edges = [e for e in edges if e.kind == EdgeKind.WRAPS and e.from_id == module.id]
    assert len(wraps_edges) == 2
    wraps_targets = {e.to_id for e in wraps_edges}
    assert wraps_targets == {"m:samtools", "m:bcftools"}


def test_parse_module_assigns_correct_pkg_per_tool():
    """Each tool is matched to its own bioconda package — not swapped or mis-assigned.

    environment.yml lists bcftools BEFORE samtools, so a naive first-dep approach
    would assign bcftools to the samtools Method.  The prefer_pkg rule must prevent
    this.
    """
    nodes, _ = parse_module(MULTI_TOOL_MODULE, ingested_at="2026-06-09")
    samtools = next(n for n in nodes if n.id == "m:samtools")
    bcftools = next(n for n in nodes if n.id == "m:bcftools")

    assert samtools.bioconda_pkg == "samtools"
    assert samtools.properties["version"] == "1.19"

    assert bcftools.bioconda_pkg == "bcftools"
    assert bcftools.properties["version"] == "1.19"


def test_parse_module_per_tool_edam():
    """PERFORMS edge from m:samtools and HAS_TOPIC edge from m:bcftools are emitted."""
    _, edges = parse_module(MULTI_TOOL_MODULE, ingested_at="2026-06-09")

    performs = [e for e in edges if e.kind == EdgeKind.PERFORMS]
    has_topic = [e for e in edges if e.kind == EdgeKind.HAS_TOPIC]

    assert any(e.from_id == "m:samtools" and e.to_id == "op:operation_2403" for e in performs)
    assert any(e.from_id == "m:bcftools" and e.to_id == "topic:topic_3168" for e in has_topic)


# ---------------------------------------------------------------------------
# Secondary tool without matching bioconda dep (bug fix: rule 2 guard)
# ---------------------------------------------------------------------------

def test_secondary_tool_without_dep_gets_no_pkg():
    """When environment.yml lists ONLY samtools, helperscript must get bioconda_pkg=None.

    Before the fix, rule 2 (single bioconda dep fallback) would incorrectly
    assign 'samtools' to helperscript because prefer_pkg='helperscript' didn't
    match rule 1, then fell through to the single-dep rule.
    """
    nodes, _ = parse_module(SAMTOOLS_HELPER_MODULE, ingested_at="2026-06-09")
    samtools = next(n for n in nodes if n.id == "m:samtools")
    helperscript = next(n for n in nodes if n.id == "m:helperscript")

    assert samtools.bioconda_pkg == "samtools"
    assert helperscript.bioconda_pkg is None


# ---------------------------------------------------------------------------
# Malformed tool entry in meta.yml tools list
# ---------------------------------------------------------------------------

def test_malformed_tool_entry_is_skipped(tmp_path):
    """A bare string / None / empty-dict entry in tools: must not raise; valid tool still emitted."""
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: test_malformed\n"
        "tools:\n"
        "  - salmon:\n"
        "      description: Selective alignment and quantification\n"
        "      homepage: https://salmon.readthedocs.io\n"
        "      identifier: biotools:salmon\n"
        "      edam_operations: []\n"
        "      edam_topics: []\n"
        "  - just_a_string\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: test_malformed\n"
        "channels:\n"
        "  - bioconda\n"
        "dependencies:\n"
        "  - 'bioconda::salmon=1.10.0'\n"
    )

    # Must not raise despite the malformed entry
    nodes, edges = parse_module(tmp_path, ingested_at="2026-06-09")

    method_ids = {n.id for n in nodes if n.kind == NodeKind.METHOD}
    assert "m:salmon" in method_ids
    # The bare string should NOT have produced a Method node
    assert len(method_ids) == 1
