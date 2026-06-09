"""Export a Subgraph to NetworkX or to RAG-grounding text."""
from __future__ import annotations

import networkx as nx

from methods_graph.extract.seed import Subgraph


def to_networkx(sg: Subgraph) -> nx.DiGraph:
    g = nx.DiGraph()
    for n in sg.nodes:
        g.add_node(n["id"], name=n["name"], kind=n["kind"], **n.get("properties", {}))
    for e in sg.edges:
        g.add_edge(e["from"], e["to"], kind=e["kind"])
    return g


def to_rag_text(sg: Subgraph) -> str:
    """Render a subgraph as a structured markdown block for LLM grounding."""
    by_id = {n["id"]: n for n in sg.nodes}
    lines: list[str] = ["# Method subgraph", "", "## Entities"]
    for n in sg.nodes:
        props = ", ".join(f"{k}={v}" for k, v in n.get("properties", {}).items() if v)
        suffix = f" ({props})" if props else ""
        lines.append(f"- [{n['kind']}] {n['name']}{suffix}")
    lines += ["", "## Relationships"]
    for e in sg.edges:
        src = by_id.get(e["from"], {}).get("name", e["from"])
        dst = by_id.get(e["to"], {}).get("name", e["to"])
        lines.append(f"- {src} —{e['kind']}→ {dst}")
    return "\n".join(lines)
