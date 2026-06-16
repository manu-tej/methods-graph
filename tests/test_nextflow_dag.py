from methods_graph.connectors.nextflow_dag import parse_dag_edges

# TRIM -> ALIGN -> SORT -> {QC, INDEX}, plus a versions/multiqc accumulator hub
# (v10) that 5 processes feed and that flows to MULTIQC. The accumulator (in>=5)
# must be excluded so it does NOT wire every process -> MULTIQC (the hairball).
DAG = """flowchart TB
    v0(["TRIM"])
    v1["ch_reads"]
    v2(["ALIGN"])
    v3["ch_bam"]
    v4(["SORT"])
    v5["ch_sorted"]
    v6(["QC"])
    v7(["INDEX"])
    v10[" "]
    v11(["MULTIQC"])
    v0 --> v1
    v1 --> v2
    v2 --> v3
    v3 --> v4
    v4 --> v5
    v5 --> v6
    v5 --> v7
    v0 --> v10
    v2 --> v10
    v4 --> v10
    v6 --> v10
    v7 --> v10
    v10 --> v11
"""


def test_collapses_channels_to_direct_process_edges():
    edges = set(parse_dag_edges(DAG))
    assert edges == {("TRIM", "ALIGN"), ("ALIGN", "SORT"),
                     ("SORT", "QC"), ("SORT", "INDEX")}


def test_excludes_accumulator_hub_no_hairball():
    edges = set(parse_dag_edges(DAG))
    # nothing routes to MULTIQC through the fan-in accumulator
    assert not any(b == "MULTIQC" for _, b in edges)
    # and no transitively-implied false edge (TRIM is not DIRECTLY -> SORT)
    assert ("TRIM", "SORT") not in edges


def test_excludes_versions_channel_by_label():
    dag = """flowchart TB
    v0(["A"])
    v1["ch_versions"]
    v2(["B"])
    v0 --> v1
    v1 --> v2
"""
    # the only path A->B is through a 'versions' channel -> excluded -> no edge
    assert parse_dag_edges(dag) == []


def test_deterministic_sorted_output():
    assert parse_dag_edges(DAG) == sorted(parse_dag_edges(DAG))


# --- integration: parse_pipeline prefers a cached dag.mmd over I/O-overlap ---

import shutil
from pathlib import Path

from methods_graph.connectors.nfcore_pipeline import parse_pipeline
from methods_graph.types import EdgeKind

MINI = Path(__file__).parent / "fixtures" / "nfcore_pipeline" / "mini"


def test_parse_pipeline_uses_cached_dag(tmp_path):
    p = tmp_path / "mini"
    shutil.copytree(MINI, p)
    (p / "workflows").mkdir()
    (p / "workflows" / "main.nf").write_text(
        "include { FASTQC } from '../modules/nf-core/fastqc'\n"
        "include { SALMON } from '../modules/nf-core/salmon'\n"
        "include { TXIMPORT } from '../modules/nf-core/tximport'\n"
    )
    (p / "dag.mmd").write_text(
        'flowchart TB\n v0(["FASTQC"])\n v1["c1"]\n v2(["SALMON"])\n'
        ' v3["c2"]\n v4(["TXIMPORT"])\n'
        ' v0 --> v1\n v1 --> v2\n v2 --> v3\n v3 --> v4\n'
    )
    _nodes, edges = parse_pipeline(p, ingested_at="2026-06-16")
    ds = [e for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF]
    pairs = {(e.from_id, e.to_id): e.properties["derivation"] for e in ds}
    assert pairs == {
        ("mod:fastqc_qc", "mod:salmon_pe"): "nextflow_dsl2",
        ("mod:salmon_pe", "mod:tximport_agg"): "nextflow_dsl2",
    }


def test_parse_pipeline_falls_back_to_io_overlap_without_dag():
    _nodes, edges = parse_pipeline(MINI, ingested_at="2026-06-16")
    ds = [e for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF]
    assert ds and all(e.properties["derivation"] == "io_inferred" for e in ds)


# --- fetch-time: nextflow preview generates + caches dag.mmd (injected runner) ---

from methods_graph.fetch import _stub_missing_includes, fetch_nfcore_pipeline

_DAG = 'flowchart TB\n v0(["A"])\n v1(["B"])\n v0 --> v1\n'   # has an edge -> a "real" DAG


class _R:
    def __init__(self, stdout=""):
        self.stdout = stdout


def _base_runner(on_nextflow):
    def runner(cmd, **kw):
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
            return _R()
        if "rev-parse" in cmd:
            return _R("deadbeef\n")
        if cmd[0] == "nextflow":
            return on_nextflow(cmd, kw)
        return _R()
    return runner


def test_fetch_generates_and_caches_dag(tmp_path):
    def on_nf(cmd, kw):
        Path(cmd[cmd.index("-with-dag") + 1]).write_text(_DAG)
        return _R()

    m = fetch_nfcore_pipeline("rnaseq", tmp_path, revision="3.14",
                              fetched_at="2026-06-16", runner=_base_runner(on_nf))
    assert m["dag"] == "dag.mmd"
    assert m["commit"] == "deadbeef"
    assert (tmp_path / "pipelines" / "rnaseq" / "dag.mmd").exists()


def test_fetch_falls_back_to_v1_parser(tmp_path):
    # v2 (default) compile fails; legacy v1 parser succeeds -> DAG still produced.
    def on_nf(cmd, kw):
        if (kw.get("env") or {}).get("NXF_SYNTAX_PARSER") == "v1":
            Path(cmd[cmd.index("-with-dag") + 1]).write_text(_DAG)
            return _R()
        raise RuntimeError("Script compilation failed (v2 parser)")

    m = fetch_nfcore_pipeline("methylseq", tmp_path, revision="4.2.0",
                              fetched_at="2026-06-16", runner=_base_runner(on_nf))
    assert m["dag"] == "dag.mmd"


def test_fetch_degrades_gracefully_when_nextflow_missing(tmp_path):
    def on_nf(cmd, kw):
        raise FileNotFoundError("nextflow not installed")

    m = fetch_nfcore_pipeline("rnaseq", tmp_path, revision="3.14",
                              fetched_at="2026-06-16", runner=_base_runner(on_nf))
    assert m["dag"] is None
    assert not (tmp_path / "pipelines" / "rnaseq" / "dag.mmd").exists()


def test_fetch_ignores_empty_header_dag(tmp_path):
    # a failed run leaves a header-only file (no edges) -> not treated as a DAG
    def on_nf(cmd, kw):
        Path(cmd[cmd.index("-with-dag") + 1]).write_text("flowchart TB\n")
        return _R()

    m = fetch_nfcore_pipeline("rnaseq", tmp_path, revision="3.14",
                              fetched_at="2026-06-16", runner=_base_runner(on_nf))
    assert m["dag"] is None


def test_stub_missing_includes(tmp_path):
    (tmp_path / "nextflow.config").write_text(
        "profiles { aws_batch { includeConfig 'conf/aws/batch/nextflow.config' } }\n"
    )
    stubbed = _stub_missing_includes(tmp_path)
    assert (tmp_path / "conf" / "aws" / "batch" / "nextflow.config").exists()
    assert len(stubbed) == 1
