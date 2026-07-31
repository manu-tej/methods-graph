"""End-to-end gold build over a directory of pipeline clones."""
from __future__ import annotations

import json
import subprocess

import pytest

from methods_graph.bench.run import build_from_clones

DAG = """flowchart TB
    v0(["TRIM"])
    v1["ch_reads"]
    v2(["ALIGN"])
    v0 --> v1
    v1 --> v2
"""

# Real nf-core module directories are frequently NESTED (``star/align``), and the
# meta.yml ``name`` is not the last path segment (``star_align``, not ``align``).
# A fixture built only from single-segment paths cannot see either fact — which is
# how an id scheme derived from the directory leaf survived four reviews.
MODULES_JSON = {
    "repos": {"https://github.com/nf-core/modules.git": {"modules": {"nf-core": {
        "trimgalore": {"branch": "master", "git_sha": "abc"},
        "star/align": {"branch": "master", "git_sha": "def"},
    }}}}
}

# rel path -> the ``name`` its vendored meta.yml declares (the mod:<name> join key).
MODULE_META_NAMES = {"trimgalore": "trimgalore", "star/align": "star_align"}

NF_INCLUDES = """
include { TRIMGALORE as TRIM } from '../modules/nf-core/trimgalore/main'
include { STAR_ALIGN as ALIGN } from '../modules/nf-core/star/align/main'
"""


def _clone(root, name, *, dag: str | None, meta_names=MODULE_META_NAMES):
    directory = root / name
    (directory / "modules" / "nf-core").mkdir(parents=True)
    for rel, meta_name in meta_names.items():
        module_dir = directory / "modules" / "nf-core" / rel
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "meta.yml").write_text(f"name: {meta_name}\n")
    (directory / "workflows").mkdir(parents=True)
    (directory / "workflows" / "test.nf").write_text(NF_INCLUDES)
    (directory / "modules.json").write_text(json.dumps(MODULES_JSON))
    if dag is not None:
        (directory / "dag.mmd").write_text(dag)
    return directory


def _sequence(out_dir, pipeline):
    written = json.loads((out_dir / "items" / f"{pipeline}.json").read_text())
    whole = next(item for item in written if item["task"] == "whole_pipeline")
    return whole["gold"]["sequence"]


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


def test_module_ids_use_the_meta_yml_name_not_the_directory_leaf(tmp_path):
    """The gold answer key must speak the graph's ids.

    ``parse_pipeline`` mints ``mod:<meta.yml name>``; a leaf-of-path scheme yields
    ``mod:align`` for ``star/align`` — an id no graph node carries — and collapses
    every ``*/align`` module onto one node, which then looks like a self-edge and is
    silently deleted.
    """
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    out = tmp_path / "bench"
    build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    assert _sequence(out, "rnaseq") == ["mod:trimgalore", "mod:star_align"]


def test_a_module_without_a_resolvable_meta_yml_is_dropped_not_guessed(tmp_path):
    """No meta.yml name means no id. Inventing one would put a dangling id in the key."""
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG, meta_names={"trimgalore": "trimgalore"})
    out = tmp_path / "bench"
    manifest = build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    # Only one module resolves, so the sequence is too short to be an item.
    assert manifest["n_used"] == 0
    assert "too short" in manifest["dropped"][0]["reason"]


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


def test_provenance_records_the_real_commit(tmp_path):
    """``nf-core/rnaseq@unknown`` is not an auditable answer key. The clone knows its own
    revision; the item has to carry it."""
    clones = tmp_path / "pipelines"
    clones.mkdir()
    clone = _clone(clones, "rnaseq", dag=DAG)
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "clone"], cwd=clone, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                          capture_output=True, text=True, check=True).stdout.strip()

    out = tmp_path / "bench"
    manifest = build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    assert manifest["used"][0]["revision"] == head
    written = json.loads((out / "items" / "rnaseq.json").read_text())
    assert all(item["gold"]["source"] == f"nf-core/rnaseq@{head}" for item in written)


def test_a_clone_that_is_not_a_repo_records_unknown_rather_than_crashing(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    manifest = build_from_clones(clones, tmp_path / "bench",
                                 goals={"rnaseq": "Bulk RNA-seq"})
    assert manifest["used"][0]["revision"] == "unknown"


def test_gold_edges_are_frozen_alongside_the_sequence(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    out = tmp_path / "bench"
    build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    written = json.loads((out / "items" / "rnaseq.json").read_text())
    whole = next(item for item in written if item["task"] == "whole_pipeline")
    assert whole["gold"]["edges"] == [["mod:trimgalore", "mod:star_align"]]


def test_missing_pipelines_directory_is_reported_clearly(tmp_path):
    """Must match our own message, not the OS's — Path.iterdir() raises
    FileNotFoundError by itself, so a loose match would pass unfixed code too."""
    with pytest.raises(FileNotFoundError, match=r"--pipelines path does not exist"):
        build_from_clones(tmp_path / "nope", tmp_path / "bench", goals={})
