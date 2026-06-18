"""Tests for the modality layer: a curated pipeline -> data-modality map
(Pipeline -HAS_MODALITY-> Modality), NOT the EDAM topic firehose."""
from __future__ import annotations

import pytest

from methods_graph.crosslinks.modalities import (
    build_modality_records, load_modalities,
)
from methods_graph.types import EdgeKind, NodeKind, NodeRecord, Provenance

P = Provenance("test", "x", "2026-06-18")


def _nodes(*specs):
    return [NodeRecord(i, i.split(":")[-1], k, {}, P) for i, k in specs]


# --- shipped YAML ---


def test_shipped_yaml_maps_rnaseq_to_bulk():
    catalog, pipe_map = load_modalities()
    assert "bulk_rnaseq" in catalog and catalog["bulk_rnaseq"]["name"]
    assert "bulk_rnaseq" in pipe_map["pipe:rnaseq"]


def test_unknown_modality_key_raises():
    spec = {"modalities": {"bulk_rnaseq": {"name": "Bulk RNA-seq"}},
            "pipelines": {"rnaseq": ["nonsuch"]}}
    with pytest.raises(ValueError, match="unknown modality"):
        load_modalities(spec=spec)


# --- grounded builder ---

_SPEC = {
    "modalities": {
        "bulk_rnaseq": {"name": "Bulk RNA-seq"},
        "microarray": {"name": "Microarray expression"},
        "proteomics": {"name": "Mass-spectrometry proteomics"},
    },
    "pipelines": {
        "rnaseq": ["bulk_rnaseq"],
        "differentialabundance": ["bulk_rnaseq", "microarray", "proteomics"],
    },
}


def test_build_emits_has_modality_when_pipeline_exists():
    nodes = _nodes(("pipe:rnaseq", NodeKind.PIPELINE))
    mn, edges, rep = build_modality_records(nodes, ingested_at="2026-06-18", spec=_SPEC)
    assert [n.id for n in mn] == ["modality:bulk_rnaseq"]
    assert mn[0].kind == NodeKind.MODALITY
    assert len(edges) == 1
    e = edges[0]
    assert (e.from_id, e.to_id, e.kind) == ("pipe:rnaseq", "modality:bulk_rnaseq", EdgeKind.HAS_MODALITY)


def test_build_mints_each_modality_once_across_pipelines():
    nodes = _nodes(("pipe:rnaseq", NodeKind.PIPELINE),
                   ("pipe:differentialabundance", NodeKind.PIPELINE))
    mn, edges, rep = build_modality_records(nodes, ingested_at="2026-06-18", spec=_SPEC)
    # bulk_rnaseq shared by both -> minted once
    assert sorted(n.id for n in mn) == ["modality:bulk_rnaseq", "modality:microarray", "modality:proteomics"]
    assert len(edges) == 4   # rnaseq:1 + differentialabundance:3


def test_build_skips_when_pipeline_absent():
    mn, edges, rep = build_modality_records([], ingested_at="2026-06-18", spec=_SPEC)
    assert mn == [] and edges == []
    assert any(r[1] == "pipeline_missing" for r in rep.skipped)


def test_edges_deterministically_sorted():
    nodes = _nodes(("pipe:differentialabundance", NodeKind.PIPELINE))
    _mn, edges, _rep = build_modality_records(nodes, ingested_at="2026-06-18", spec=_SPEC)
    assert [e.to_id for e in edges] == [
        "modality:bulk_rnaseq", "modality:microarray", "modality:proteomics"]
