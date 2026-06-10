from pathlib import Path
from methods_graph.connectors.nfcore import (
    parse_module,
    _collect_ontology_edam_uris,
    _edam_uri_to_node_id,
)
from methods_graph.types import NodeKind, EdgeKind

MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "salmon_quant"
MULTIDEP_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "multidep_quant"
MULTI_TOOL_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_stats"
SAMTOOLS_HELPER_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "samtools_helper"
FASTQC_MOD_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "fastqc_mod"
FASTP_IO_MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "fastp_io"


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

# ---------------------------------------------------------------------------
# Single-tool module where tool key differs from bioconda package name
# ---------------------------------------------------------------------------

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
