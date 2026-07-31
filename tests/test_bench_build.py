"""One gold sequence becomes one whole-pipeline item plus N next-step items."""
from __future__ import annotations

import pytest

from methods_graph.bench.build import make_items

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
