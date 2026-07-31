"""End-to-end gold build over a directory of pipeline clones."""
from __future__ import annotations

import json

import pytest

from methods_graph.bench.run import build_from_clones

DAG = """flowchart TB
    v0(["TRIM"])
    v1["ch_reads"]
    v2(["ALIGN"])
    v0 --> v1
    v1 --> v2
"""

MODULES_JSON = {
    "repos": {"https://github.com/nf-core/modules.git": {"modules": {"nf-core": {
        "trimgalore": {"branch": "master", "git_sha": "abc"},
        "star": {"branch": "master", "git_sha": "def"},
    }}}}
}

NF_INCLUDES = """
include { TRIMGALORE as TRIM } from '../modules/nf-core/trimgalore/main'
include { STAR_ALIGN as ALIGN } from '../modules/nf-core/star/main'
"""


def _clone(root, name, *, dag: str | None):
    directory = root / name
    (directory / "modules" / "nf-core").mkdir(parents=True)
    (directory / "workflows").mkdir(parents=True)
    (directory / "workflows" / "test.nf").write_text(NF_INCLUDES)
    (directory / "modules.json").write_text(json.dumps(MODULES_JSON))
    if dag is not None:
        (directory / "dag.mmd").write_text(dag)
    return directory


def test_pipeline_without_a_dag_is_dropped_with_a_reason(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "sarek", dag=None)
    manifest = build_from_clones(clones, tmp_path / "bench", goals={"sarek": "Variant calling"})
    assert manifest["n_used"] == 0
    assert manifest["n_dropped"] == 1
    assert "dag.mmd" in manifest["dropped"][0]["reason"]


def test_manifest_and_items_are_written(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    out = tmp_path / "bench"
    build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    assert (out / "gold" / "manifest.json").exists()
    written = json.loads((out / "items" / "rnaseq.json").read_text())
    assert any(item["task"] == "whole_pipeline" for item in written)


def test_malformed_modules_json_is_dropped_not_fatal(tmp_path):
    """One bad clone must not discard the whole build."""
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    bad = _clone(clones, "broken", dag=DAG)
    (bad / "modules.json").write_text("{not valid json")
    manifest = build_from_clones(clones, tmp_path / "bench",
                                 goals={"rnaseq": "Bulk RNA-seq", "broken": "Broken"})
    assert manifest["n_used"] == 1
    assert manifest["n_dropped"] == 1
    assert manifest["dropped"][0]["pipeline"] == "broken"
    assert manifest["dropped"][0]["reason"]


def test_missing_pipelines_directory_is_reported_clearly(tmp_path):
    """Must match our own message, not the OS's — Path.iterdir() raises
    FileNotFoundError by itself, so a loose match would pass unfixed code too."""
    with pytest.raises(FileNotFoundError, match=r"--pipelines path does not exist"):
        build_from_clones(tmp_path / "nope", tmp_path / "bench", goals={})
