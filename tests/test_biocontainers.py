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
    pkg = next(n for n in nodes if n.kind == NodeKind.PACKAGE)
    ctr = next(n for n in nodes if n.kind == NodeKind.CONTAINER)
    edge = next(e for e in edges if e.kind == EdgeKind.FROM_PACKAGE)
    assert edge.from_id == ctr.id
    assert edge.to_id == pkg.id


def test_parse_biocontainer_handles_missing_fields():
    # No versions key — should return just the package node, no containers or edges
    nodes, edges = parse_biocontainer({"name": "salmon"}, ingested_at="2026-06-08")
    assert len([n for n in nodes if n.kind == NodeKind.PACKAGE]) == 1
    assert len([n for n in nodes if n.kind == NodeKind.CONTAINER]) == 0
    assert len(edges) == 0

    # Image dict missing image_name — container should be skipped
    data_missing_image_name = {
        "name": "x",
        "versions": [{"meta_version": "1", "images": [{"registry": "quay.io"}]}],
    }
    nodes2, edges2 = parse_biocontainer(data_missing_image_name, ingested_at="2026-06-08")
    assert len([n for n in nodes2 if n.kind == NodeKind.CONTAINER]) == 0
    assert len(edges2) == 0
