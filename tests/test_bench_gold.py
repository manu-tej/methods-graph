"""Gold sequence extraction: a Nextflow DAG becomes an ordered list of module ids."""
from __future__ import annotations

from methods_graph.bench.gold import BOOKKEEPING, gold_edges, gold_sequence

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


# --- the DAG itself, not just one linearization ---
#
# QC and INDEX both hang off SORT: they are PARALLEL, and their order in the sequence is
# an arbitrary tie-break. A metric that scores adjacent pairs of the linearization marks
# a correct answer wrong. The edge list is what actually constrains the ordering, and it
# has to be frozen alongside the items — it cannot be recovered afterwards.

def test_edges_are_the_dag_not_a_linearization():
    assert gold_edges(DAG, PROC_TO_MODULE) == [
        ("mod:samtools_sort", "mod:qualimap"),
        ("mod:samtools_sort", "mod:samtools_index"),
        ("mod:star", "mod:samtools_sort"),
        ("mod:trimgalore", "mod:star"),
    ]


def test_parallel_branches_are_not_ordered_relative_to_each_other():
    """qualimap and samtools_index are adjacent in the sequence but unrelated in the DAG."""
    sequence = gold_sequence(DAG, PROC_TO_MODULE)
    assert sequence.index("mod:samtools_index") - sequence.index("mod:qualimap") == 1
    edges = gold_edges(DAG, PROC_TO_MODULE)
    assert ("mod:qualimap", "mod:samtools_index") not in edges
    assert ("mod:samtools_index", "mod:qualimap") not in edges


def test_edges_exclude_bookkeeping_at_either_end():
    wired = """flowchart TB
    v0(["ALIGN"])
    v1["ch_bam"]
    v2(["MULTIQC"])
    v0 --> v1
    v1 --> v2
"""
    assert gold_edges(wired, PROC_TO_MODULE) == []


def test_edges_are_deduped_sorted_and_deterministic():
    first = gold_edges(DAG, PROC_TO_MODULE)
    assert first == sorted(set(first))
    assert all(gold_edges(DAG, PROC_TO_MODULE) == first for _ in range(5))


def test_edges_only_reference_modules_in_the_sequence():
    """Every endpoint must be a node the sequence also contains, or the two disagree."""
    sequence = set(gold_sequence(DAG, PROC_TO_MODULE))
    for source, target in gold_edges(DAG, PROC_TO_MODULE):
        assert source in sequence and target in sequence
