import json
from pathlib import Path
from methods_graph.connectors.biocontainers import parse_biocontainer
from methods_graph.types import NodeKind, EdgeKind

FIXTURE = Path(__file__).parent / "fixtures" / "biocontainers_salmon.json"


def test_parse_biocontainer_emits_package_and_container():
    data = json.loads(FIXTURE.read_text())
    nodes, edges = parse_biocontainer(data, ingested_at="2026-06-08")
    pkg = next(n for n in nodes if n.kind == NodeKind.PACKAGE)
    container = next(n for n in nodes if n.kind == NodeKind.CONTAINER)
    assert pkg.name == "salmon"
    assert "salmon:1.10.0" in container.properties["image_name"]


def test_container_links_to_package():
    data = json.loads(FIXTURE.read_text())
    nodes, edges = parse_biocontainer(data, ingested_at="2026-06-08")
    assert any(e.kind == EdgeKind.FROM_PACKAGE for e in edges)
