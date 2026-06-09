from pathlib import Path
from methods_graph.connectors.nfcore import parse_module
from methods_graph.types import NodeKind, EdgeKind

MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "salmon_quant"


def test_parse_module_creates_method_with_join_keys():
    nodes, _ = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.name == "salmon"
    assert method.bioconda_pkg == "salmon"
    assert method.biotools_id == "salmon"
    assert method.properties["version"] == "1.10.0"


def test_parse_module_links_to_edam():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    performs = [e for e in edges if e.kind == EdgeKind.PERFORMS]
    has_topic = [e for e in edges if e.kind == EdgeKind.HAS_TOPIC]
    assert any(e.from_id == method.id and e.to_id == "op:operation_3798" for e in performs)
    assert any(e.from_id == method.id and e.to_id == "topic:topic_3170" for e in has_topic)


def test_parse_module_emits_module_and_wraps_edge():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    module = next(n for n in nodes if n.kind == NodeKind.MODULE)
    assert module.name == "salmon_quant"
    assert any(e.kind == EdgeKind.WRAPS and e.from_id == module.id for e in edges)
