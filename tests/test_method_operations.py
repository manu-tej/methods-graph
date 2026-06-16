"""Tests for the curated module-context operation layer (I2 corrections + I1 backfill)."""
from __future__ import annotations

from methods_graph.crosslinks.method_operations import (
    OperationEdit, build_operation_edits, load_method_operations,
)
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-16")


def _nodes(*specs):
    return [NodeRecord(i, i.split(":")[-1], k, {}, P) for i, k in specs]


# --- shipped YAML ---


def test_shipped_yaml_loads_with_corrections_and_backfill():
    edits = load_method_operations()
    by = {e.method_id: e for e in edits}
    # I2 corrections
    assert "op:operation_3197" in by["m:picard"].remove        # Genetic variation analysis
    assert "op:operation_3963" in by["m:picard"].add           # Duplication detection
    assert {"op:operation_0524", "op:operation_3630"} <= set(by["m:tximeta"].remove)
    # I1 backfill
    assert "op:operation_3198" in by["m:bowtie2"].add          # Read mapping
    assert "op:operation_3460" in by["m:sylphtax"].add         # Taxonomic classification
    # m:custom intentionally NOT curated (collapses heterogeneous modules)
    assert "m:custom" not in by


# --- builder: add ---


def test_build_adds_edge_when_method_and_operation_exist():
    nodes = _nodes(("m:bowtie2", NodeKind.METHOD), ("op:operation_3198", NodeKind.OPERATION))
    edits = [OperationEdit("m:bowtie2", add=("op:operation_3198",), remove=())]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert removes == set()
    assert len(adds) == 1
    e = adds[0]
    assert (e.from_id, e.to_id, e.kind) == ("m:bowtie2", "op:operation_3198", EdgeKind.PERFORMS)
    assert e.provenance.source == "curated"
    assert rep.added == 1


def test_build_skips_add_when_operation_node_missing():
    nodes = _nodes(("m:bowtie2", NodeKind.METHOD))
    edits = [OperationEdit("m:bowtie2", add=("op:operation_3198",), remove=())]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert adds == []
    assert ("m:bowtie2", "op:operation_3198", "operation_missing") in rep.skipped


def test_build_skips_add_when_method_node_missing():
    nodes = _nodes(("op:operation_3198", NodeKind.OPERATION))
    edits = [OperationEdit("m:bowtie2", add=("op:operation_3198",), remove=())]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert adds == []
    assert ("m:bowtie2", "op:operation_3198", "method_missing") in rep.skipped


def test_build_skips_add_when_target_not_an_operation():
    nodes = _nodes(("m:bowtie2", NodeKind.METHOD), ("op:operation_3198", NodeKind.TOPIC))
    edits = [OperationEdit("m:bowtie2", add=("op:operation_3198",), remove=())]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert adds == []
    assert any(r[2].startswith("target_wrong_kind") for r in rep.skipped)


# --- builder: remove (independent of node existence — it is an edge filter) ---


def test_build_emits_remove_key_with_replacement_add():
    nodes = _nodes(("m:picard", NodeKind.METHOD), ("op:operation_3963", NodeKind.OPERATION))
    edits = [OperationEdit("m:picard", add=("op:operation_3963",), remove=("op:operation_3197",))]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert ("m:picard", "op:operation_3197", "PERFORMS") in removes
    assert rep.removed_keys == 1
    assert len(adds) == 1  # the corrected operation


def test_remove_is_independent_of_add_node_existence():
    # the wrong edge must be removable even if the replacement op node is absent
    nodes = _nodes(("m:picard", NodeKind.METHOD))
    edits = [OperationEdit("m:picard", add=("op:operation_3963",), remove=("op:operation_3197",))]
    adds, removes, rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert ("m:picard", "op:operation_3197", "PERFORMS") in removes
    assert adds == []


def test_edits_are_deterministically_sorted():
    nodes = _nodes(
        ("m:b", NodeKind.METHOD), ("m:a", NodeKind.METHOD),
        ("op:operation_0001", NodeKind.OPERATION), ("op:operation_0002", NodeKind.OPERATION),
    )
    edits = [
        OperationEdit("m:b", add=("op:operation_0001",), remove=()),
        OperationEdit("m:a", add=("op:operation_0002",), remove=()),
    ]
    adds, _removes, _rep = build_operation_edits(nodes, ingested_at="2026-06-16", edits=edits)
    assert [(e.from_id, e.to_id) for e in adds] == [
        ("m:a", "op:operation_0002"), ("m:b", "op:operation_0001")]
