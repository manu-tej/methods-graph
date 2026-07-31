"""Gold sequence extraction: a Nextflow DAG becomes an ordered list of module ids."""
from __future__ import annotations

from methods_graph.bench.gold import BOOKKEEPING, gold_sequence

# TRIM -> ALIGN -> SORT -> {QC, INDEX}, plus a versions/multiqc accumulator hub
# (v10) that five processes feed. The parser already excludes that hub.
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

PROC_TO_MODULE = {
    "TRIM": "mod:trimgalore",
    "ALIGN": "mod:star",
    "SORT": "mod:samtools_sort",
    "QC": "mod:qualimap",
    "INDEX": "mod:samtools_index",
    "MULTIQC": "mod:multiqc",
}


def test_orders_modules_by_dataflow():
    assert gold_sequence(DAG, PROC_TO_MODULE) == [
        "mod:trimgalore", "mod:star", "mod:samtools_sort",
        "mod:qualimap", "mod:samtools_index",
    ]


def test_unmapped_processes_are_dropped():
    partial = {k: v for k, v in PROC_TO_MODULE.items() if k != "QC"}
    assert "mod:qualimap" not in gold_sequence(DAG, partial)


def test_bookkeeping_steps_are_stripped():
    """A directly-wired multiqc must still be removed: it is reporting, not method choice."""
    wired = """flowchart TB
    v0(["ALIGN"])
    v1["ch_bam"]
    v2(["MULTIQC"])
    v0 --> v1
    v1 --> v2
"""
    assert gold_sequence(wired, PROC_TO_MODULE) == ["mod:star"]
    assert "multiqc" in BOOKKEEPING


def test_is_deterministic():
    first = gold_sequence(DAG, PROC_TO_MODULE)
    assert all(gold_sequence(DAG, PROC_TO_MODULE) == first for _ in range(5))
