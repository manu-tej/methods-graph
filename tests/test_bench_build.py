"""One gold sequence becomes one whole-pipeline item plus N next-step items."""
from __future__ import annotations

import pytest

from methods_graph.bench.build import make_items, build_manifest

SEQUENCE = ["mod:trimgalore", "mod:star", "mod:salmon", "mod:deseq2"]
COMMON = dict(
    pipeline="rnaseq", revision="3.14.0", nxf_ver="23.04.0",
    dag_sha256="9f2c", goal="Bulk RNA-seq differential expression",
    sequence=SEQUENCE, derivation="nextflow_dsl2",
)


def test_produces_one_whole_pipeline_item():
    whole = [i for i in make_items(**COMMON) if i["task"] == "whole_pipeline"]
    assert len(whole) == 1
    assert whole[0]["gold"]["sequence"] == SEQUENCE
    assert whole[0]["given"] == []


def test_produces_one_next_step_item_per_position():
    steps = [i for i in make_items(**COMMON) if i["task"] == "next_step"]
    assert len(steps) == len(SEQUENCE)
    assert steps[0]["given"] == []
    assert steps[0]["gold"]["next"] == "mod:trimgalore"
    assert steps[-1]["given"] == SEQUENCE[:-1]
    assert steps[-1]["gold"]["next"] == "mod:deseq2"


def test_every_item_carries_reproducible_provenance():
    for item in make_items(**COMMON):
        assert item["gold"]["source"] == "nf-core/rnaseq@3.14.0"
        assert item["gold"]["nxf_ver"] == "23.04.0"
        assert item["gold"]["dag_sha256"] == "9f2c"
        assert item["gold"]["derivation"] == "nextflow_dsl2"


def test_ids_are_unique_and_stable():
    ids = [i["id"] for i in make_items(**COMMON)]
    assert len(ids) == len(set(ids))
    assert ids == [i["id"] for i in make_items(**COMMON)]


def test_io_inferred_gold_is_rejected():
    """The whole point of the constraint: inferred wiring can never become an item."""
    with pytest.raises(ValueError, match="derivation"):
        make_items(**{**COMMON, "derivation": "io_inferred"})


def test_single_step_pipeline_is_rejected():
    """A one-step 'sequence' tests nothing about sequencing."""
    with pytest.raises(ValueError, match="at least two"):
        make_items(**{**COMMON, "sequence": ["mod:fastqc"]})


def test_manifest_counts_used_and_dropped():
    manifest = build_manifest([
        {"pipeline": "rnaseq", "revision": "3.14.0", "status": "used",
         "reason": None, "n_items": 5},
        {"pipeline": "sarek", "revision": "3.4.0", "status": "dropped",
         "reason": "nextflow preview failed (NXF_VER mismatch)", "n_items": 0},
    ])
    assert manifest["n_pipelines"] == 2
    assert manifest["n_used"] == 1
    assert manifest["n_dropped"] == 1
    assert manifest["n_items"] == 5


def test_dropped_pipelines_keep_their_reason():
    """A benchmark that silently omits what it could not parse misreports coverage."""
    manifest = build_manifest([
        {"pipeline": "sarek", "revision": "3.4.0", "status": "dropped",
         "reason": "no dag.mmd produced", "n_items": 0},
    ])
    assert manifest["dropped"][0]["reason"] == "no dag.mmd produced"


def test_dropped_without_a_reason_is_rejected():
    with pytest.raises(ValueError, match="reason"):
        build_manifest([
            {"pipeline": "x", "revision": "1", "status": "dropped",
             "reason": None, "n_items": 0},
        ])


def test_manifest_is_sorted_for_stable_diffs():
    manifest = build_manifest([
        {"pipeline": "sarek", "revision": "1", "status": "used",
         "reason": None, "n_items": 2},
        {"pipeline": "atacseq", "revision": "1", "status": "used",
         "reason": None, "n_items": 2},
    ])
    assert [p["pipeline"] for p in manifest["used"]] == ["atacseq", "sarek"]
