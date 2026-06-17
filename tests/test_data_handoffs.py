"""Tests for the curated data-type layer: semantic Method->Data INPUT/OUTPUT edges
that make cross-pipeline workflow composition real (rnaseq counts -> DE)."""
from __future__ import annotations

import pytest

from methods_graph.crosslinks.data_handoffs import (
    DataIO, build_data_io_edges, load_data_types,
)
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-17")


def _nodes(*specs):
    return [NodeRecord(i, i.split(":")[-1], k, {}, P) for i, k in specs]


# --- shipped YAML ---


def test_shipped_yaml_loads_catalog_and_io():
    catalog, io = load_data_types()
    assert catalog["count_matrix"] == "data:data_3917"
    by = {d.method_id: d for d in io}
    # rnaseq producers of the count matrix
    assert "data:data_3917" in by["m:tximeta"].produces
    assert "data:data_3917" in by["m:summarizedexperiment"].produces
    # the load-bearing rnaseq->DE handoff: deseq2 consumes the raw count matrix
    assert "data:data_3917" in by["m:deseq2"].consumes
    # limma consumes an expression/intensity matrix, NOT raw counts (microarray path)
    assert "data:data_3917" not in by["m:limma"].consumes
    assert "data:data_3112" in by["m:limma"].consumes


def test_unknown_data_type_key_raises():
    spec = {"data_types": {"count_matrix": {"edam": "data_3917"}},
            "tool_io": {"m:deseq2": {"consumes": ["nonsuch_type"]}}}
    with pytest.raises(ValueError, match="unknown data type"):
        load_data_types(spec=spec)


# --- builder: produces -> OUTPUT, consumes -> INPUT ---


def test_build_emits_output_edge_for_produces():
    nodes = _nodes(("m:tximeta", NodeKind.METHOD), ("data:data_3917", NodeKind.DATA))
    io = [DataIO("m:tximeta", produces=("data:data_3917",))]
    adds, rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert len(adds) == 1
    e = adds[0]
    assert (e.from_id, e.to_id, e.kind) == ("m:tximeta", "data:data_3917", EdgeKind.OUTPUT)
    assert e.provenance.source == "curated"
    assert rep.produced == 1


def test_build_emits_input_edge_for_consumes():
    nodes = _nodes(("m:deseq2", NodeKind.METHOD), ("data:data_3917", NodeKind.DATA))
    io = [DataIO("m:deseq2", consumes=("data:data_3917",))]
    adds, rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert len(adds) == 1
    e = adds[0]
    assert (e.from_id, e.to_id, e.kind) == ("m:deseq2", "data:data_3917", EdgeKind.INPUT)
    assert rep.consumed == 1


def test_build_skips_when_data_node_missing():
    nodes = _nodes(("m:tximeta", NodeKind.METHOD))
    io = [DataIO("m:tximeta", produces=("data:data_3917",))]
    adds, rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert adds == []
    assert ("m:tximeta", "data:data_3917", "OUTPUT", "data_missing") in rep.skipped


def test_build_skips_when_method_node_missing():
    nodes = _nodes(("data:data_3917", NodeKind.DATA))
    io = [DataIO("m:tximeta", produces=("data:data_3917",))]
    adds, rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert adds == []
    assert ("m:tximeta", "data:data_3917", "OUTPUT", "method_missing") in rep.skipped


def test_build_skips_when_target_not_a_data_node():
    nodes = _nodes(("m:tximeta", NodeKind.METHOD), ("data:data_3917", NodeKind.OPERATION))
    io = [DataIO("m:tximeta", produces=("data:data_3917",))]
    adds, rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert adds == []
    assert any(r[3].startswith("target_wrong_kind") for r in rep.skipped)


def test_edges_deterministically_sorted():
    nodes = _nodes(
        ("m:b", NodeKind.METHOD), ("m:a", NodeKind.METHOD),
        ("data:data_0001", NodeKind.DATA), ("data:data_0002", NodeKind.DATA),
    )
    io = [
        DataIO("m:b", consumes=("data:data_0001",)),
        DataIO("m:a", produces=("data:data_0002",)),
    ]
    adds, _rep = build_data_io_edges(nodes, ingested_at="2026-06-17", io=io)
    assert [(e.from_id, e.to_id, e.kind.value) for e in adds] == [
        ("m:a", "data:data_0002", "OUTPUT"),
        ("m:b", "data:data_0001", "INPUT"),
    ]
