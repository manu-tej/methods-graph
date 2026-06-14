from pathlib import Path

from methods_graph.connectors.nfcore_pipeline import parse_pipeline
from methods_graph.types import NodeKind, EdgeKind

PIPE = Path(__file__).parent / "fixtures" / "nfcore_pipeline" / "mini"


def test_parse_pipeline_emits_pipeline_node():
    nodes, _ = parse_pipeline(PIPE, ingested_at="2026-06-13")
    pipe = next(n for n in nodes if n.kind == NodeKind.PIPELINE)
    assert pipe.id == "pipe:mini"
    assert pipe.properties["n_modules"] == 3


def test_parse_pipeline_has_module_uses_meta_yml_name():
    """HAS_MODULE must target mod:<meta.yml name>, NOT mod:<dir leaf>.
    salmon dir → name 'salmon_pe' → mod:salmon_pe (the riskiest join)."""
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    has_mod = {e.to_id for e in edges if e.kind == EdgeKind.HAS_MODULE}
    assert has_mod == {"mod:fastqc_qc", "mod:salmon_pe", "mod:tximport_agg"}
    assert all(e.from_id == "pipe:mini" for e in edges if e.kind == EdgeKind.HAS_MODULE)


def test_parse_pipeline_drops_module_with_missing_meta():
    """A modules.json entry with no vendored meta.yml is dropped; n_modules
    reflects only resolved modules."""
    nodes, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    pipe = next(n for n in nodes if n.kind == NodeKind.PIPELINE)
    assert pipe.properties["n_modules"] == 3  # ghost dropped
    has_mod = {e.to_id for e in edges if e.kind == EdgeKind.HAS_MODULE}
    assert "mod:ghost" not in has_mod
    assert has_mod == {"mod:fastqc_qc", "mod:salmon_pe", "mod:tximport_agg"}


def test_parse_pipeline_infers_downstream_of_by_io_overlap():
    """salmon_pe OUTPUT *.sf feeds tximport_agg INPUT *.sf → one DOWNSTREAM_OF.
    fastqc_qc OUTPUT *.html does NOT match salmon INPUT → no edge (honest Option-2)."""
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    dse = [e for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF]
    pairs = {(e.from_id, e.to_id) for e in dse}
    assert ("mod:salmon_pe", "mod:tximport_agg") in pairs
    assert ("mod:fastqc_qc", "mod:salmon_pe") not in pairs  # no I/O overlap

    edge = next(e for e in dse if e.from_id == "mod:salmon_pe")
    assert edge.properties["derivation"] == "io_inferred"
    assert edge.properties["pipelines"] == ["mini"]
    assert edge.properties["attestations"] == 1
    assert edge.properties["confidence"] == 0.5


def test_parse_pipeline_no_self_loops():
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    assert all(e.from_id != e.to_id
               for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF)


def test_parse_pipeline_deterministic():
    a = parse_pipeline(PIPE, ingested_at="2026-06-13")
    b = parse_pipeline(PIPE, ingested_at="2026-06-13")
    assert [(n.id, n.kind) for n in a[0]] == [(n.id, n.kind) for n in b[0]]
    assert [(e.from_id, e.to_id, e.kind) for e in a[1]] == \
           [(e.from_id, e.to_id, e.kind) for e in b[1]]
