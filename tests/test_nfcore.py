from pathlib import Path
from methods_graph.connectors.nfcore import (
    parse_module,
    _collect_ontology_edam_uris,
    _edam_uri_to_node_id,
    _pattern_to_fmt_id,
    _pattern_to_fmt_ids,
    _collect_io_patterns,
)
from methods_graph.types import NodeKind, EdgeKind

MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "salmon_quant"
MULTIDEP_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "multidep_quant"
MULTI_TOOL_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_stats"
SAMTOOLS_HELPER_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_helper"
FASTQC_MOD_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "fastqc_mod"
FASTP_IO_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "fastp_io"
BCFTOOLS_SORT_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "bcftools_sort"


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
    assert any(e.from_id == method.id and e.to_id == "op:operation_3798" for e in performs)
    # HAS_TOPIC no longer emitted (Topic layer removed)
    assert not any(e.kind == EdgeKind.HAS_TOPIC for e in edges)


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
    """Per-tool PERFORMS edges are emitted (HAS_TOPIC dropped with the Topic layer)."""
    _, edges = parse_module(MULTI_TOOL_MODULE, ingested_at="2026-06-09")

    performs = [e for e in edges if e.kind == EdgeKind.PERFORMS]

    assert any(e.from_id == "m:samtools" and e.to_id == "op:operation_2403" for e in performs)
    assert not any(e.kind == EdgeKind.HAS_TOPIC for e in edges)


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

# ---------------------------------------------------------------------------
# Single-tool module where tool key differs from bioconda package name
# ---------------------------------------------------------------------------

def test_parse_module_tolerates_null_tool_body(tmp_path):
    """A `tools:` entry with an empty body (`- toolx:`) yields a None value in the
    parsed YAML; parse_module must coerce it and not crash (seen across the nf-core
    catalog). Regression for AttributeError: 'NoneType' has no attribute 'get'."""
    d = tmp_path / "toolx"
    d.mkdir()
    (d / "meta.yml").write_text("name: toolx\ntools:\n  - toolx:\n")
    (d / "environment.yml").write_text("dependencies:\n  - bioconda::toolx=1.0\n")
    (d / "main.nf").write_text("process TOOLX { script: 'toolx' }\n")
    nodes, _edges = parse_module(d, ingested_at="2026-06-18")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.id == "m:toolx"


def test_single_tool_dep_assigned_even_when_names_differ():
    """A single-tool module with a single bioconda dep must get pkg/version
    even when the tools: key (fastqc_check) differs from the package name (fastqc).
    """
    nodes, _ = parse_module(FASTQC_MOD_MODULE, ingested_at="2026-06-09")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.id == "m:fastqc_check"
    assert method.bioconda_pkg == "fastqc"
    assert method.properties["version"] == "0.12.1"


def test_multitool_single_dep_only_matching_tool_gets_pkg():
    """In a multi-tool module with ONE bioconda dep, only the name-matching
    tool gets bioconda_pkg; sibling tools with no matching dep get None/empty.
    """
    nodes, _ = parse_module(SAMTOOLS_HELPER_MODULE, ingested_at="2026-06-09")
    samtools = next(n for n in nodes if n.id == "m:samtools")
    helperscript = next(n for n in nodes if n.id == "m:helperscript")

    assert samtools.bioconda_pkg == "samtools"
    assert samtools.properties["version"] == "1.19"

    assert helperscript.bioconda_pkg is None
    assert helperscript.properties["version"] == ""


# ---------------------------------------------------------------------------
# Malformed tool entry in meta.yml tools list
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# I/O ontology (INPUT / OUTPUT) edge tests
# ---------------------------------------------------------------------------

def test_parse_module_links_edam_via_io_ontologies():
    """fastp_io fixture: INPUT edge m:fastp->fmt:format_1930, OUTPUT m:fastp->fmt:format_3464."""
    _, edges = parse_module(FASTP_IO_MODULE, ingested_at="2026-06-09")
    input_edges = [e for e in edges if e.kind == EdgeKind.INPUT]
    output_edges = [e for e in edges if e.kind == EdgeKind.OUTPUT]
    assert any(
        e.from_id == "m:fastp" and e.to_id == "fmt:format_1930" for e in input_edges
    ), f"INPUT edge missing; got: {[(e.from_id, e.to_id) for e in input_edges]}"
    assert any(
        e.from_id == "m:fastp" and e.to_id == "fmt:format_3464" for e in output_edges
    ), f"OUTPUT edge missing; got: {[(e.from_id, e.to_id) for e in output_edges]}"


def test_collect_ontology_edam_uris_walks_nested():
    """_collect_ontology_edam_uris handles list-of-lists, plain dicts, empty/absent ontologies."""
    # Mirrors real nf-core grouped input (- - YAML syntax → list of lists)
    section = [
        # grouped channels: outer list item is itself a list
        [
            {"meta": {"type": "map", "description": "sample info"}},
            {
                "reads": {
                    "type": "file",
                    "description": "fastq",
                    "ontologies": [
                        {"edam": "http://edamontology.org/format_1930"},
                    ],
                }
            },
        ],
        # plain channel dict with no ontologies key
        {"index": {"type": "file", "description": "index"}},
        # channel with empty ontologies list
        {"bam": {"type": "file", "ontologies": []}},
    ]
    uris = _collect_ontology_edam_uris(section)
    # Compare as a set so future fixture additions don't break on ordering.
    assert set(uris) == {"http://edamontology.org/format_1930"}

    # None / absent section → empty
    assert _collect_ontology_edam_uris(None) == []
    assert _collect_ontology_edam_uris([]) == []


def test_collect_ontology_edam_uris_no_spurious_nested():
    """A channel edam entry that itself contains an 'ontologies' sub-key must
    not cause the nested URIs to be collected a second time.

    Shape under test:
        channel -> {type: file, ontologies: [{edam: "format_1930",
                                              ontologies: [{edam: "format_9999"}]}]}

    Only format_1930 (the top-level channel ontologies entry) should be
    collected; format_9999 (nested inside the edam entry) must be ignored.
    """
    section = [
        {
            "reads": {
                "type": "file",
                "description": "fastq reads",
                "ontologies": [
                    {
                        "edam": "http://edamontology.org/format_1930",
                        # Spurious nested ontologies key — simulates a
                        # malformed/future edam entry carrying its own
                        # ontologies child.
                        "ontologies": [
                            {"edam": "http://edamontology.org/format_9999"}
                        ],
                    }
                ],
            }
        }
    ]
    uris = _collect_ontology_edam_uris(section)
    assert "http://edamontology.org/format_1930" in uris, (
        "format_1930 must be collected from the top-level ontologies list"
    )
    assert "http://edamontology.org/format_9999" not in uris, (
        "format_9999 must NOT be collected — it is nested inside an edam entry, "
        "not inside a top-level channel ontologies list"
    )


def test_edam_uri_to_node_id_classifies():
    """_edam_uri_to_node_id maps each EDAM prefix to the correct graph id prefix."""
    assert _edam_uri_to_node_id("http://edamontology.org/format_1930") == "fmt:format_1930"
    assert _edam_uri_to_node_id("http://edamontology.org/data_3494") == "data:data_3494"
    assert _edam_uri_to_node_id("http://edamontology.org/operation_3798") == "op:operation_3798"
    assert _edam_uri_to_node_id("http://edamontology.org/topic_3170") == "topic:topic_3170"
    # Unclassifiable inputs must return None
    assert _edam_uri_to_node_id("http://example.com/garbage") is None
    assert _edam_uri_to_node_id("not_a_uri") is None


def test_io_ontologies_attributed_to_all_wrapped_tools(tmp_path):
    """Multi-tool module: both wrapped methods get INPUT edges from module-level ontologies."""
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: dual_tool_io\n"
        "tools:\n"
        "  - samtools:\n"
        "      description: SAM utilities\n"
        "      identifier: biotools:samtools\n"
        "  - bcftools:\n"
        "      description: BCF utilities\n"
        "      identifier: biotools:bcftools\n"
        "input:\n"
        "  - - reads:\n"
        "          type: file\n"
        "          ontologies:\n"
        "            - edam: http://edamontology.org/format_2572\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: dual_tool_io\n"
        "dependencies:\n"
        "  - bioconda::samtools=1.19\n"
        "  - bioconda::bcftools=1.19\n"
    )

    _, edges = parse_module(tmp_path, ingested_at="2026-06-09")
    input_edges = [e for e in edges if e.kind == EdgeKind.INPUT]
    from_ids = {e.from_id for e in input_edges}
    assert "m:samtools" in from_ids, "samtools must get INPUT edge"
    assert "m:bcftools" in from_ids, "bcftools must get INPUT edge"
    assert all(e.to_id == "fmt:format_2572" for e in input_edges)


def test_io_ontologies_skip_non_data_format_edam(tmp_path):
    """I/O channel ontologies that carry an operation URI must NOT produce an INPUT edge.

    Real nf-core meta.yml files occasionally mis-place an EDAM operation URI
    inside an input/output channel's ontologies list.  parse_module must emit an
    INPUT edge only to the valid format node (fmt:format_1930) and must NOT emit
    an INPUT edge to the operation node (op:operation_3800).
    """
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: mixed_edam_io\n"
        "tools:\n"
        "  - fastp:\n"
        "      description: A tool for fast adapter trimming\n"
        "      identifier: biotools:fastp\n"
        "input:\n"
        "  - - reads:\n"
        "          type: file\n"
        "          description: Input FASTQ reads\n"
        "          ontologies:\n"
        "            - edam: http://edamontology.org/format_1930\n"
        "            - edam: http://edamontology.org/operation_3800\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: mixed_edam_io\n"
        "channels:\n"
        "  - bioconda\n"
        "dependencies:\n"
        "  - 'bioconda::fastp=0.23.4'\n"
    )

    _, edges = parse_module(tmp_path, ingested_at="2026-06-10")
    input_edges = [e for e in edges if e.kind == EdgeKind.INPUT]

    to_ids = {e.to_id for e in input_edges}
    assert "fmt:format_1930" in to_ids, (
        f"INPUT edge to fmt:format_1930 must be emitted; got to_ids={to_ids}"
    )
    assert "op:operation_3800" not in to_ids, (
        f"INPUT edge to op:operation_3800 must NOT be emitted; got to_ids={to_ids}"
    )


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


# ---------------------------------------------------------------------------
# tool_id override tests (directory-derived authoritative identity)
# ---------------------------------------------------------------------------

def test_tool_id_overrides_generic_meta_key():
    """Single-tool module with a generic meta key ('sort') + tool_id='bcftools':
    the Method must use id m:bcftools, name bcftools, and preserve the original
    meta key as properties['tool_label'].  The WRAPS edge must point to m:bcftools.
    The bioconda_pkg must be correctly resolved to 'bcftools' despite the tool
    key being 'sort'.
    """
    nodes, edges = parse_module(
        BCFTOOLS_SORT_MODULE, ingested_at="2026-06-10", tool_id="bcftools"
    )
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)

    # Identity override
    assert method.id == "m:bcftools", f"Expected m:bcftools; got {method.id}"
    assert method.name == "bcftools", f"Expected name 'bcftools'; got {method.name}"

    # Original meta key preserved for traceability
    assert method.properties.get("tool_label") == "sort", (
        f"Expected tool_label='sort'; got {method.properties.get('tool_label')}"
    )

    # Bioconda package resolved via authoritative tool_id
    assert method.bioconda_pkg == "bcftools", (
        f"Expected bioconda_pkg='bcftools'; got {method.bioconda_pkg}"
    )

    # WRAPS edge must point to the overridden id
    module_node = next(n for n in nodes if n.kind == NodeKind.MODULE)
    wraps_edges = [e for e in edges if e.kind == EdgeKind.WRAPS]
    assert any(
        e.from_id == module_node.id and e.to_id == "m:bcftools" for e in wraps_edges
    ), f"Expected WRAPS edge to m:bcftools; got {[(e.from_id, e.to_id) for e in wraps_edges]}"

    # The generic key must NOT appear as a method id
    method_ids = {n.id for n in nodes if n.kind == NodeKind.METHOD}
    assert "m:sort" not in method_ids, "m:sort must not be emitted when tool_id overrides it"


def test_tool_id_ignored_for_multitool_module():
    """Multi-tool module with tool_id provided: tool_id must be ignored.
    Each tool must get its own m:<meta_key> id (original behaviour).
    """
    nodes, edges = parse_module(
        MULTI_TOOL_MODULE, ingested_at="2026-06-10", tool_id="whatever"
    )
    method_ids = {n.id for n in nodes if n.kind == NodeKind.METHOD}

    # Both original meta keys must be present
    assert "m:samtools" in method_ids, f"Expected m:samtools; got {method_ids}"
    assert "m:bcftools" in method_ids, f"Expected m:bcftools; got {method_ids}"

    # The supplied tool_id must NOT appear as a method id
    assert "m:whatever" not in method_ids, (
        f"tool_id='whatever' must be ignored for multi-tool modules; got {method_ids}"
    )

    # Neither method should have a tool_label property (override not applied)
    for n in nodes:
        if n.kind == NodeKind.METHOD:
            assert "tool_label" not in n.properties, (
                f"tool_label must not be set on multi-tool method {n.id}"
            )


def test_parse_module_without_tool_id_unchanged():
    """Back-compat: calling parse_module without tool_id on the salmon_quant
    fixture still yields m:salmon (not affected by tool_id feature).
    """
    nodes, _ = parse_module(MODULE, ingested_at="2026-06-10")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.id == "m:salmon", f"Back-compat broken: expected m:salmon, got {method.id}"
    assert method.name == "salmon"
    assert "tool_label" not in method.properties, (
        "tool_label must not be set when tool_id is not provided"
    )


# ---------------------------------------------------------------------------
# Duplicate bio.tools identifier across tools in one module (copy-paste error)
# ---------------------------------------------------------------------------

def test_duplicate_biotools_id_across_tools_is_rejected(tmp_path):
    """Multi-tool module where homer/samtools/deseq2 all share identifier
    biotools:homer (copy-paste error in meta.yml).

    Only the tool whose name matches the identifier should keep biotools_id;
    the mismatched entries must have biotools_id=None to prevent entity-resolution
    fusion of distinct tools in the graph.
    """
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: homer_maketagdirectory\n"
        "tools:\n"
        "  - homer:\n"
        "      description: Tools for motif discovery and next-gen sequencing analysis\n"
        "      homepage: http://homer.ucsd.edu/homer/\n"
        "      identifier: biotools:homer\n"
        "  - samtools:\n"
        "      description: Tools for manipulating next-generation sequencing data\n"
        "      homepage: http://www.htslib.org/\n"
        "      identifier: biotools:homer\n"
        "  - deseq2:\n"
        "      description: Differential gene expression analysis\n"
        "      homepage: https://bioconductor.org/packages/DESeq2/\n"
        "      identifier: biotools:homer\n"
        "input: []\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: homer_maketagdirectory\n"
        "dependencies:\n"
        "  - bioconda::homer=4.11\n"
        "  - bioconda::samtools=1.19\n"
    )

    nodes, _ = parse_module(tmp_path, ingested_at="2026-06-10")
    methods = {n.id: n for n in nodes if n.kind == NodeKind.METHOD}

    # homer's name matches the identifier — it keeps biotools_id
    assert methods["m:homer"].biotools_id == "homer", (
        "homer must keep biotools_id='homer' because its name matches the identifier"
    )
    # samtools and deseq2 carry a copy-pasted homer id — must be cleared
    assert methods["m:samtools"].biotools_id is None, (
        "samtools must have biotools_id=None: identifier 'homer' is shared and name doesn't match"
    )
    assert methods["m:deseq2"].biotools_id is None, (
        "deseq2 must have biotools_id=None: identifier 'homer' is shared and name doesn't match"
    )


# ---------------------------------------------------------------------------
# Case-insensitive method identity tests
# ---------------------------------------------------------------------------

def test_method_id_is_lowercased(tmp_path):
    """Single-tool module with tool_id='DESeq2': method id must be 'm:deseq2' (lowercased)
    while name preserves the original case 'DESeq2'.  The WRAPS edge must target 'm:deseq2'.
    """
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: deseq2_test\n"
        "tools:\n"
        "  - deseq2:\n"
        "      description: Differential expression analysis\n"
        "      homepage: https://bioconductor.org/packages/DESeq2/\n"
        "      identifier: biotools:DESeq2\n"
        "input: []\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: deseq2_test\n"
        "dependencies:\n"
        "  - bioconda::deseq2=1.40.0\n"
    )

    nodes, edges = parse_module(tmp_path, ingested_at="2026-06-10", tool_id="DESeq2")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)

    # id must be lowercased
    assert method.id == "m:deseq2", (
        f"Expected method id 'm:deseq2' (lowercased); got '{method.id}'"
    )
    # display name preserves original case
    assert method.name == "DESeq2", (
        f"Expected name 'DESeq2' (original case preserved); got '{method.name}'"
    )

    # WRAPS edge must target the lowercased id
    module_node = next(n for n in nodes if n.kind == NodeKind.MODULE)
    wraps_edges = [e for e in edges if e.kind == EdgeKind.WRAPS]
    assert any(
        e.from_id == module_node.id and e.to_id == "m:deseq2" for e in wraps_edges
    ), f"Expected WRAPS edge to 'm:deseq2'; got {[(e.from_id, e.to_id) for e in wraps_edges]}"


def test_meta_key_method_id_lowercased(tmp_path):
    """No tool_id override: meta key 'Comet' must yield method id 'm:comet' (lowercased)
    while name preserves 'Comet'.
    """
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: comet_search\n"
        "tools:\n"
        "  - Comet:\n"
        "      description: Tandem mass spectrometry database search\n"
        "      homepage: https://uwpr.github.io/Comet/\n"
        "input: []\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: comet_search\n"
        "dependencies:\n"
        "  - bioconda::comet=2023010\n"
    )

    nodes, edges = parse_module(tmp_path, ingested_at="2026-06-10")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)

    # id must be lowercased
    assert method.id == "m:comet", (
        f"Expected method id 'm:comet' (lowercased); got '{method.id}'"
    )
    # display name preserves the original meta key case
    assert method.name == "Comet", (
        f"Expected name 'Comet' (original case preserved); got '{method.name}'"
    )


def test_parse_module_io_from_pattern_when_no_ontologies():
    """salmon_quant has type/pattern but no ontologies; pattern fallback must
    still emit INPUT (FASTQ→known EDAM fmt) and OUTPUT (*.sf→synthetic Format)."""
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)

    inputs = {e.to_id for e in edges if e.kind == EdgeKind.INPUT and e.from_id == method.id}
    outputs = {e.to_id for e in edges if e.kind == EdgeKind.OUTPUT and e.from_id == method.id}

    # *.fastq.gz maps to a known EDAM format id (node provided by EDAM ingestion).
    assert "fmt:format_1930" in inputs
    # *.sf has no EDAM mapping → synthetic Format node, which MUST also be emitted.
    assert "fmt:pat:.sf" in outputs
    fmt_node = next(n for n in nodes if n.id == "fmt:pat:.sf")
    assert fmt_node.kind == NodeKind.FORMAT


def test_parse_module_ontology_io_still_wins():
    """fastp_io declares EDAM ontology URIs; those must still be emitted
    (the pattern fallback must not regress ontology-based extraction)."""
    nodes, edges = parse_module(FASTP_IO_MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    inputs = {e.to_id for e in edges if e.kind == EdgeKind.INPUT and e.from_id == method.id}
    outputs = {e.to_id for e in edges if e.kind == EdgeKind.OUTPUT and e.from_id == method.id}
    assert "fmt:format_1930" in inputs   # from ontologies
    assert "fmt:format_3464" in outputs  # from ontologies


def test_distinct_biotools_ids_preserved(tmp_path):
    """Multi-tool module where each tool has a DIFFERENT, name-matching identifier.

    No identifier is shared, so the deduplication logic must leave every
    biotools_id intact — no false rejection.
    """
    meta_yml = tmp_path / "meta.yml"
    meta_yml.write_text(
        "name: samtools_bcftools\n"
        "tools:\n"
        "  - samtools:\n"
        "      description: Tools for manipulating next-generation sequencing data\n"
        "      homepage: http://www.htslib.org/\n"
        "      identifier: biotools:samtools\n"
        "  - bcftools:\n"
        "      description: Tools for variant calling and manipulating VCFs and BCFs\n"
        "      homepage: http://www.htslib.org/\n"
        "      identifier: biotools:bcftools\n"
        "input: []\n"
        "output: []\n"
    )
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: samtools_bcftools\n"
        "dependencies:\n"
        "  - bioconda::samtools=1.19\n"
        "  - bioconda::bcftools=1.19\n"
    )

    nodes, _ = parse_module(tmp_path, ingested_at="2026-06-10")
    methods = {n.id: n for n in nodes if n.kind == NodeKind.METHOD}

    assert methods["m:samtools"].biotools_id == "samtools", (
        "samtools must keep biotools_id='samtools' — distinct identifiers, no conflict"
    )
    assert methods["m:bcftools"].biotools_id == "bcftools", (
        "bcftools must keep biotools_id='bcftools' — distinct identifiers, no conflict"
    )


# ---------------------------------------------------------------------------
# Format-map plumbing: pattern -> EDAM id, and pattern collection
# ---------------------------------------------------------------------------

def test_pattern_to_fmt_id_known_unknown_and_case():
    # Known genomics formats map to their EDAM fmt: ids.
    assert _pattern_to_fmt_id("*.bam") == "fmt:format_2572"
    assert _pattern_to_fmt_id("*.vcf.gz") == "fmt:format_3016"
    assert _pattern_to_fmt_id("*.fastq.gz") == "fmt:format_1930"
    # Case-insensitive.
    assert _pattern_to_fmt_id("*.BAM") == "fmt:format_2572"
    # Mid-string glob still resolves by suffix.
    assert _pattern_to_fmt_id("sample_*.bam") == "fmt:format_2572"
    # Unknown extension → synthetic Format id.
    assert _pattern_to_fmt_id("*.sf") == "fmt:pat:.sf"
    assert _pattern_to_fmt_id("*.xyz") == "fmt:pat:.xyz"


def test_pattern_to_fmt_ids_expands_braces():
    # THE bug: nf-core's dominant '*.{bam}' form used to fall through to junk.
    assert _pattern_to_fmt_ids("*.{bam}") == ["fmt:format_2572"]
    # multi-extension brace -> one EDAM id per alternative (an input that accepts
    # bam OR cram OR sam relates to all three formats).
    assert set(_pattern_to_fmt_ids("*.{bam,cram,sam}")) == {
        "fmt:format_2572", "fmt:format_3462", "fmt:format_2573"}
    # alternatives that collapse to the same format dedupe to one id.
    assert _pattern_to_fmt_ids("*.{fastq,fq}.gz") == ["fmt:format_1930"]
    # pipe-separated alternation with mixed known/unknown extensions.
    assert set(_pattern_to_fmt_ids("*.bai|csi|crai")) == {
        "fmt:format_3327", "fmt:pat:.csi", "fmt:pat:.crai"}


def test_pattern_to_fmt_ids_suffix_and_template():
    # prefixed real extensions resolve by suffix ('_fastqc.html' -> HTML).
    assert _pattern_to_fmt_ids("*_fastqc.html") == ["fmt:format_2331"]
    # a Nextflow template prefix is ignored; the real extension wins.
    assert _pattern_to_fmt_ids("*.${prefix}.{gtf}") == ["fmt:format_2306"]
    # gff3 is more specific than generic gff.
    assert _pattern_to_fmt_ids("*.gff3") == ["fmt:format_1975"]
    # unknown extension stays synthetic.
    assert _pattern_to_fmt_ids("*.sf") == ["fmt:pat:.sf"]
    # optional-suffix bracket '[.gz]' is stripped to the base extension.
    assert _pattern_to_fmt_ids("*.fasta[.gz]") == ["fmt:format_1929"]
    assert _pattern_to_fmt_ids("*.fastq[.gz]") == ["fmt:format_1930"]


def test_pattern_to_fmt_id_returns_primary_of_ids():
    # the singular form (kept for back-compat) returns the first mapped id.
    assert _pattern_to_fmt_id("*.{bam}") == "fmt:format_2572"


def test_collect_io_patterns_handles_list_of_lists():
    # Mimics the nf-core meta.yml "- -" grouped-channel (list-of-lists) shape.
    section = [
        [
            {"meta": {"type": "map", "description": "sample info"}},
            {"reads": {"type": "file", "pattern": "*.fastq.gz"}},
        ],
        {"bam": {"type": "file", "pattern": "*.bam"}},
    ]
    pats = _collect_io_patterns(section)
    assert "*.fastq.gz" in pats
    assert "*.bam" in pats
