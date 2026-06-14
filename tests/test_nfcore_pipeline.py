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
