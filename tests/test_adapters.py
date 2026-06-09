import networkx as nx
from methods_graph.extract.seed import Subgraph
from methods_graph.extract.adapters import to_networkx, to_rag_text


def _sg():
    sg = Subgraph()
    sg.nodes = [
        {"id": "m:salmon", "name": "salmon", "kind": "Method", "properties": {"version": "1.10.0"}},
        {"id": "op:3798", "name": "Read summarisation", "kind": "Operation", "properties": {}},
    ]
    sg.edges = [{"from": "m:salmon", "to": "op:3798", "kind": "PERFORMS"}]
    return sg


def test_to_networkx_builds_digraph():
    g = to_networkx(_sg())
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == 2
    assert g.nodes["m:salmon"]["kind"] == "Method"
    assert g.edges["m:salmon", "op:3798"]["kind"] == "PERFORMS"


def test_to_rag_text_mentions_method_and_relations():
    txt = to_rag_text(_sg())
    assert "salmon" in txt
    assert "Read summarisation" in txt
    assert "PERFORMS" in txt
