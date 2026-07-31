"""End-to-end gold build over a directory of pipeline clones."""
from __future__ import annotations

import json
import subprocess

import pytest

from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.run import build_from_clones, rescore, run_items, score_item, summarize
from methods_graph.cli import main

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


def _oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:hisat2", "m:salmon", "m:deseq2"],
        modules={"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                 "mod:salmon_quant": "m:salmon",
                 "mod:deseq2_differential": "m:deseq2"},
        operations={"m:star": ["op:0292"], "m:hisat2": ["op:0292"]},
        inputs={"m:star": ["data:1234"], "m:hisat2": ["data:1234"],
                "m:salmon": ["data:0863"], "m:deseq2": ["data:3917"]},
        outputs={"m:star": ["data:0863"], "m:salmon": ["data:3917"]},
    )


def _whole_item():
    return {
        "id": "rnaseq/whole/001", "task": "whole_pipeline", "goal": "Bulk RNA-seq",
        "given": [],
        "gold": {
            "sequence": ["mod:fastqc", "mod:star_align", "mod:salmon_quant",
                         "mod:deseq2_differential"],
            "edges": [["mod:fastqc", "mod:star_align"],
                      ["mod:star_align", "mod:salmon_quant"],
                      ["mod:salmon_quant", "mod:deseq2_differential"]],
        },
    }


def test_ceiling_feeding_the_gold_answer_back_scores_one():
    row = score_item(_whole_item(), '["fastqc","star","salmon","deseq2"]', _oracle())
    assert row["selection"]["f1"] == 1.0
    assert row["sequencing"]["score"] == 1.0
    assert row["unresolved"] == []


def test_row_retains_the_raw_output_so_scores_can_be_rederived():
    raw = 'Sure!\n["fastqc","star"]'
    assert score_item(_whole_item(), raw, _oracle())["raw"] == raw


def test_unparseable_response_is_recorded_not_silently_zeroed():
    row = score_item(_whole_item(), "I cannot help with that.", _oracle())
    assert row["parsed"] is False
    assert row["pred"] == []
    assert row["selection"]["f1"] == 0.0


def test_next_step_row_carries_its_bucket():
    item = {"id": "rnaseq/next/002", "task": "next_step", "goal": "Bulk RNA-seq",
            "given": ["mod:fastqc", "mod:star_align"],
            "gold": {"next": "mod:salmon_quant"}}
    row = score_item(item, '["salmon","kallisto"]', _oracle())
    assert row["n_given"] == 2
    assert row["next"]["top1"] is True


def test_adapter_failure_is_recorded_against_the_item_and_the_run_continues():
    from methods_graph.bench.adapters import AdapterError

    def _flaky(prompt):
        if "Bulk" in prompt:
            raise AdapterError("rate limited")
        return '["fastqc"]'

    items = [_whole_item(), {**_whole_item(), "id": "other/whole/001", "goal": "Other"}]
    rows = run_items(items, _flaky, _oracle(), model="test")
    assert rows[0]["error"] == "rate limited"
    assert rows[0]["selection"] is None
    assert rows[1]["error"] is None


def test_rescore_reproduces_the_original_scores_from_raw_alone():
    rows = run_items([_whole_item()], lambda p: '["fastqc","star","salmon","deseq2"]',
                     _oracle(), model="test")
    stripped = [{k: v for k, v in r.items()
                 if k in ("item", "task", "raw", "model", "gold_raw", "given")}
                for r in rows]
    assert rescore(stripped, _oracle())[0]["selection"]["f1"] == 1.0


def test_summary_separates_the_two_task_types():
    rows = run_items([_whole_item()], lambda p: '["fastqc","star","salmon","deseq2"]',
                     _oracle(), model="test")
    summary = summarize(rows)
    assert summary["whole_pipeline"]["n"] == 1
    assert summary["whole_pipeline"]["selection_f1"] == 1.0
    assert summary["next_step"]["n"] == 0


def test_cli_run_writes_one_jsonl_row_per_item(tmp_path):
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    (items_dir / "rnaseq.json").write_text(json.dumps([_whole_item()]))
    canned = tmp_path / "canned.json"
    canned.write_text(json.dumps(['["fastqc","star","salmon","deseq2"]']))
    out = tmp_path / "results.jsonl"

    code = main(["bench", "run", "--items", str(items_dir),
                 "--model", f"static:{canned}", "--out", str(out),
                 "--oracle-json", str(_write_oracle_json(tmp_path))])
    assert code == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["selection"]["f1"] == 1.0


def _write_oracle_json(tmp_path):
    """A serialized StaticOracle, so the CLI test needs no Kuzu database."""
    path = tmp_path / "oracle.json"
    path.write_text(json.dumps({
        "methods": ["m:fastqc", "m:star", "m:salmon", "m:deseq2"],
        "modules": {"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                    "mod:salmon_quant": "m:salmon",
                    "mod:deseq2_differential": "m:deseq2"},
        "operations": {}, "inputs": {}, "outputs": {},
    }))
    return path
