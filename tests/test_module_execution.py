"""Tests for the execution-spec layer: extract a module's runnable recipe
(pinned container + command + typed I/O) from main.nf / environment.yml."""
from __future__ import annotations

from pathlib import Path

from methods_graph.connectors.module_execution import (
    build_execution_records, extract_module_execution,
    parse_command, parse_conda, parse_container, parse_io,
)
from methods_graph.types import EdgeKind, NodeKind

# A realistic nf-core container directive (the singularity/docker ternary).
_DESEQ2_MAIN = '''process DESEQ2_DIFFERENTIAL {
    label 'process_single'
    conda "${moduleDir}/environment.yml"
    container "${ workflow.containerEngine == 'singularity' && !task.ext.singularity_pull_docker_container ?
        'https://depot.galaxyproject.org/singularity/bioconductor-deseq2:1.34.0--r41hc247a5b_3' :
        'biocontainers/bioconductor-deseq2:1.34.0--r41hc247a5b_3' }"

    input:
    tuple val(meta), val(contrast_variable), val(reference), val(target)
    tuple val(meta2), path(samplesheet), path(counts)

    output:
    tuple val(meta), path("*.deseq2.results.tsv")     , emit: results
    tuple val(meta), path("*.normalised_counts.tsv")  , emit: normalised_counts
    path "versions.yml"                               , emit: versions

    script:
    template 'deseq_de.R'
}
'''

_INLINE_MAIN = '''process FASTQC {
    container 'biocontainers/fastqc:0.12.1--hdfd78af_0'
    input:
    tuple val(meta), path(reads)
    output:
    tuple val(meta), path("*.html"), emit: html
    script:
    """
    fastqc $reads
    """
}
'''

# Modern nf-core / Seqera-community form: the ternary CONDITION contains the literal
# tokens 'singularity'/'apptainer', and the real singularity image is an https blob URL
# that contains neither "singularity" nor "depot.galaxyproject".
_SEQERA_MAIN = '''process MULTIQC {
    container "${workflow.containerEngine in ['singularity', 'apptainer'] && !task.ext.singularity_pull_docker_container
        ? 'https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/1b/1bef8af6/data'
        : 'community.wave.seqera.io/library/multiqc:1.34--db7c73dae76bc9e6'}"
    script:
    """
    multiqc .
    """
}
'''


# --- pure parsers ---


def test_parse_container_ternary_splits_singularity_and_docker():
    c = parse_container(_DESEQ2_MAIN)
    assert c["docker"] == "biocontainers/bioconductor-deseq2:1.34.0--r41hc247a5b_3"
    assert c["singularity"] == "https://depot.galaxyproject.org/singularity/bioconductor-deseq2:1.34.0--r41hc247a5b_3"


def test_parse_container_single_image():
    c = parse_container(_INLINE_MAIN)
    assert c["docker"] == "biocontainers/fastqc:0.12.1--hdfd78af_0"


def test_parse_container_seqera_form_classifies_by_url_not_condition_token():
    # regression: the literal 'singularity'/'apptainer' condition tokens must NOT
    # be taken as images, and the real https blob must be the singularity image.
    c = parse_container(_SEQERA_MAIN)
    assert c["docker"] == "community.wave.seqera.io/library/multiqc:1.34--db7c73dae76bc9e6"
    assert c["singularity"].startswith("https://community-cr-prod.seqera.io")
    assert c["singularity"] not in ("singularity", "apptainer")


def test_parse_container_none_when_absent():
    assert parse_container("process X { script: 'echo hi' }") is None


def test_parse_command_template():
    assert parse_command(_DESEQ2_MAIN) == {"kind": "template", "ref": "deseq_de.R"}


def test_parse_command_inline_script_captures_body():
    cmd = parse_command(_INLINE_MAIN)
    assert cmd["kind"] == "script"
    assert "fastqc $reads" in cmd["ref"]


def test_parse_io_inputs_and_output_emits():
    io = parse_io(_DESEQ2_MAIN)
    assert "counts" in io["inputs"] and "samplesheet" in io["inputs"]
    assert io["outputs"] == ["results", "normalised_counts", "versions"]


def test_parse_conda_packages():
    env = "dependencies:\n  - bioconda::bioconductor-deseq2=1.34.0\n  - conda-forge::r-base=4.1\n"
    assert parse_conda(env) == ["bioconductor-deseq2=1.34.0", "r-base=4.1"]


# --- extraction from a module dir ---


def _write_module(root: Path, name: str, main_nf: str) -> Path:
    d = root / "modules" / "nf-core" / "deseq2" / "differential"
    d.mkdir(parents=True)
    (d / "main.nf").write_text(main_nf)
    (d / "meta.yml").write_text(f"name: {name}\n")
    (d / "environment.yml").write_text("dependencies:\n  - bioconda::bioconductor-deseq2=1.34.0\n")
    return root


def test_extract_module_execution_full_spec(tmp_path):
    _write_module(tmp_path, "deseq2_differential", _DESEQ2_MAIN)
    mod_dir = tmp_path / "modules" / "nf-core" / "deseq2" / "differential"
    spec = extract_module_execution(mod_dir)
    assert spec["module"] == "deseq2_differential"
    assert spec["container"] == "biocontainers/bioconductor-deseq2:1.34.0--r41hc247a5b_3"
    assert spec["conda"] == ["bioconductor-deseq2=1.34.0"]
    assert spec["command"] == {"kind": "template", "ref": "deseq_de.R"}
    assert "results" in spec["outputs"]


def test_extract_returns_none_without_main_or_name(tmp_path):
    d = tmp_path / "modules" / "nf-core" / "x" / "y"
    d.mkdir(parents=True)
    (d / "meta.yml").write_text("name: x_y\n")           # no main.nf
    assert extract_module_execution(d) is None


# --- grounded builder ---


def test_build_emits_execution_spec_and_runs_as_when_module_exists(tmp_path):
    root = _write_module(tmp_path, "deseq2_differential", _DESEQ2_MAIN)
    nodes, edges, rep = build_execution_records(
        [root], {"mod:deseq2_differential"}, ingested_at="2026-06-17")
    assert len(nodes) == 1 and nodes[0].kind == NodeKind.EXECUTION_SPEC
    assert nodes[0].id == "exec:deseq2_differential"
    assert nodes[0].properties["container"] == "biocontainers/bioconductor-deseq2:1.34.0--r41hc247a5b_3"
    assert len(edges) == 1
    e = edges[0]
    assert (e.from_id, e.to_id, e.kind) == ("mod:deseq2_differential", "exec:deseq2_differential", EdgeKind.RUNS_AS)
    assert rep.specs == 1


def test_build_skips_when_module_node_absent(tmp_path):
    root = _write_module(tmp_path, "deseq2_differential", _DESEQ2_MAIN)
    nodes, edges, rep = build_execution_records([root], set(), ingested_at="2026-06-17")
    assert nodes == [] and edges == []
    assert ("mod:deseq2_differential", "module_missing") in rep.skipped


def _write_multiqc(root: Path, container: str) -> Path:
    d = root / "modules" / "nf-core" / "multiqc"
    d.mkdir(parents=True)
    (d / "main.nf").write_text(
        f"process MULTIQC {{\n    container '{container}'\n    script:\n    \"\"\"\n    multiqc .\n    \"\"\"\n}}\n")
    (d / "meta.yml").write_text("name: multiqc\n")
    return root


def test_build_captures_container_variants_across_pipelines(tmp_path):
    # a module vendored at DIFFERENT versions across pipelines must not silently
    # drop the other versions — they are recorded as container_variants.
    r1 = _write_multiqc(tmp_path / "pa", "biocontainers/multiqc:1.34--db7c73d")
    r2 = _write_multiqc(tmp_path / "pb", "biocontainers/multiqc:1.23--abc1234")
    nodes, edges, rep = build_execution_records(
        [r1, r2], {"mod:multiqc"}, ingested_at="2026-06-18")
    assert len(nodes) == 1 and len(edges) == 1          # one exec node for the shared module
    variants = nodes[0].properties.get("container_variants")
    assert set(variants) == {
        "biocontainers/multiqc:1.34--db7c73d", "biocontainers/multiqc:1.23--abc1234"}
