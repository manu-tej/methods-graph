import pytest

from methods_graph.bench.normalize import (
    normalize_answer, normalize_name, project_edges, project_sequence)
from methods_graph.bench.oracle import StaticOracle


def _oracle():
    return StaticOracle(
        methods=["m:star", "m:trimgalore", "m:bwamem2", "m:bwa", "m:deseq2",
                 "m:ea-utils", "m:salmon", "m:samtools"],
        modules={
            "mod:star_genomegenerate": "m:star",
            "mod:star_align": "m:star",
            "mod:samtools_sort": "m:samtools",
            "mod:salmon_quant": "m:salmon",
            "mod:deseq2_differential": "m:deseq2",
        },
    )


@pytest.mark.parametrize("text,expected", [
    ("star", "m:star"),
    ("STAR", "m:star"),
    ("  DESeq2  ", "m:deseq2"),
    ("Trim Galore", "m:trimgalore"),      # punctuation+space compaction
    ("Trim Galore!", "m:trimgalore"),
    ("BWA-MEM2", "m:bwamem2"),
    ("ea utils", "m:ea-utils"),           # hyphen reconstruction
    ("m:star", "m:star"),                 # already an id
    ("bwa mem", "m:bwa"),                 # curated alias
])
def test_names_resolve_exactly(text, expected):
    assert normalize_name(text, _oracle()) == expected


@pytest.mark.parametrize("text", ["", "   ", "some tool I invented", "aligner"])
def test_unresolvable_names_return_none(text):
    assert normalize_name(text, _oracle()) is None


def test_answer_keeps_order_dedupes_and_reports_unresolved():
    ids, unresolved = normalize_answer(
        ["STAR", "salmon", "STAR", "MyAligner", "DESeq2"], _oracle())
    assert ids == ["m:star", "m:salmon", "m:deseq2"]
    assert unresolved == ["MyAligner"]


def test_projection_collapses_two_modules_of_one_tool():
    seq, unresolved = project_sequence(
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant"], _oracle())
    assert seq == ["m:star", "m:salmon"]
    assert unresolved == []


def test_projection_reports_unresolvable_modules_rather_than_dropping_them_quietly():
    seq, unresolved = project_sequence(
        ["mod:star_align", "mod:some_local_process"], _oracle())
    assert seq == ["m:star"]
    assert unresolved == ["mod:some_local_process"]


def test_projected_edges_drop_self_loops_from_the_collapse():
    edges, n_cyclic = project_edges(
        [("mod:star_genomegenerate", "mod:star_align"),
         ("mod:star_align", "mod:salmon_quant")],
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant"],
        _oracle())
    assert edges == [("m:star", "m:salmon")]
    assert n_cyclic == 0


def test_projected_edges_drop_contradictions_the_collapse_created_and_count_them():
    # star -> salmon -> star in module space becomes a 2-cycle once collapsed.
    edges, n_cyclic = project_edges(
        [("mod:star_genomegenerate", "mod:salmon_quant"),
         ("mod:salmon_quant", "mod:star_align")],
        ["mod:star_genomegenerate", "mod:salmon_quant", "mod:star_align"],
        _oracle())
    assert edges == [("m:star", "m:salmon")]
    assert n_cyclic == 1


def test_projected_edges_are_sorted_and_deduped():
    edges, _ = project_edges(
        [("mod:star_align", "mod:salmon_quant"),
         ("mod:star_genomegenerate", "mod:salmon_quant"),
         ("mod:salmon_quant", "mod:deseq2_differential")],
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant",
         "mod:deseq2_differential"],
        _oracle())
    assert edges == [("m:salmon", "m:deseq2"), ("m:star", "m:salmon")]


from pathlib import Path

from methods_graph.bench.normalize import _ALIASES
from methods_graph.bench.oracle import KuzuOracle

_DB = Path("data/methods.kuzu")


@pytest.mark.skipif(not _DB.exists(), reason="built graph not present")
def test_every_alias_names_a_method_the_graph_actually_has():
    oracle = KuzuOracle(_DB)
    missing = sorted(t for t in set(_ALIASES.values()) if not oracle.has_method(f"m:{t}"))
    assert missing == [], f"aliases pointing at non-existent methods: {missing}"
