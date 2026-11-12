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


EDGES = [("mod:trimgalore", "mod:star"), ("mod:star", "mod:salmon"),
         ("mod:star", "mod:deseq2")]


def test_gold_edges_are_frozen_with_the_whole_pipeline_item():
    """The sequencing metric needs the DAG, not one of its linearizations — and after the
    items are frozen the DAG is unrecoverable, so it has to be stored now."""
    whole = [i for i in make_items(**COMMON, edges=EDGES)
             if i["task"] == "whole_pipeline"][0]
    assert whole["gold"]["edges"] == [["mod:trimgalore", "mod:star"],
                                      ["mod:star", "mod:salmon"],
                                      ["mod:star", "mod:deseq2"]]


def test_items_are_unchanged_when_no_edges_are_supplied():
    assert make_items(**COMMON) == make_items(**COMMON, edges=None)
    assert all("edges" not in item["gold"] for item in make_items(**COMMON))


_INDEX_THEN_USE = ["mod:fastqc", "mod:star_genomegenerate", "mod:star_align",
                   "mod:salmon_quant"]
_WRAPS = {"mod:fastqc": "m:fastqc", "mod:star_genomegenerate": "m:star",
          "mod:star_align": "m:star", "mod:salmon_quant": "m:salmon"}


def test_a_next_step_item_is_not_built_when_the_prompt_would_contain_its_own_answer():
    """`given` is rendered in METHOD space, so `star_genomegenerate` then `star_align`
    shows the model "Completed so far: fastqc, star" and asks it to name star. The
    whole index-then-use family (salmon, bwa, samtools) is degenerate the same way —
    free marks for every model and both baselines."""
    items = make_items(**{**COMMON, "sequence": _INDEX_THEN_USE},
                       method_for_module=_WRAPS.get)
    nxt = [i for i in items if i["task"] == "next_step"]

    assert [i["gold"]["next"] for i in nxt] == [
        "mod:fastqc", "mod:star_genomegenerate", "mod:salmon_quant"]
    for item in nxt:
        given_methods = {_WRAPS[m] for m in item["given"]}
        assert _WRAPS[item["gold"]["next"]] not in given_methods


def test_next_step_items_are_unchanged_without_a_projection():
    """The default must preserve existing behaviour exactly — callers with no oracle
    build the same set they always did."""
    assert (make_items(**{**COMMON, "sequence": _INDEX_THEN_USE})
            == make_items(**{**COMMON, "sequence": _INDEX_THEN_USE},
                          method_for_module=None))
    assert len([i for i in make_items(**{**COMMON, "sequence": _INDEX_THEN_USE})
                if i["task"] == "next_step"]) == 4


def test_an_unresolvable_gold_module_still_gets_its_item():
    """No method means nothing could have leaked; the scorer reports it as
    gold_unresolved rather than dropping it."""
    items = make_items(**{**COMMON, "sequence": ["mod:fastqc", "mod:local_process"]},
                       method_for_module={"mod:fastqc": "m:fastqc"}.get)
    assert len([i for i in items if i["task"] == "next_step"]) == 2


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


def test_unrecognized_status_is_rejected():
    """An unknown status would otherwise be filed under 'used', hiding the drop entirely."""
    with pytest.raises(ValueError, match="status"):
        build_manifest([
            {"pipeline": "x", "revision": "1", "status": "skipped",
             "reason": "typo in caller", "n_items": 0},
        ])
