# tests/test_integration.py
import json
from pathlib import Path

from methods_graph.connectors.edam import parse_edam
from methods_graph.connectors.nfcore import parse_module
from methods_graph.connectors.biocontainers import parse_biocontainer
from methods_graph.resolve.resolver import resolve
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
from methods_graph.types import NodeKind, MethodRecord

FX = Path(__file__).parent / "fixtures"


def test_full_pipeline_salmon(tmp_path):
    edam_nodes, edam_edges = parse_edam(FX / "edam_sample.tsv", ingested_at="2026-06-08")
    nf_nodes, nf_edges = parse_module(FX / "nfcore" / "salmon_quant", ingested_at="2026-06-08")
    bc_nodes, bc_edges = parse_biocontainer(
        json.loads((FX / "biocontainers_salmon.json").read_text()), ingested_at="2026-06-08")

    method_nodes = [n for n in nf_nodes if isinstance(n, MethodRecord)]
    other_nodes = ([n for n in nf_nodes if not isinstance(n, MethodRecord)]
                   + edam_nodes + bc_nodes)
    src_edges = nf_edges + edam_edges + bc_edges

    nodes, edges = resolve(method_nodes=method_nodes, other_nodes=other_nodes, src_edges=src_edges,
                           ingested_at="2026-06-08")

    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")

    with KuzuMethodsGraphProvider(db_path) as provider:
        methods = provider.get_methods()
        salmon = next(m for m in methods if m["name"] == "salmon")

        # End-to-end assertions spanning all three sources:
        assert "RNA-Seq" in salmon["tags"]                                 # EDAM topic via nf-core ref
        assert "salmon:1.10.0" in salmon["compute_requirements"]["container_image"]  # BioContainers
        ctx = provider.retrieve_context_for_keywords(["salmon"])
        assert "Read summarisation" in ctx                                 # EDAM operation in RAG text


def test_pipeline_is_rebuildable(tmp_path):
    nf_nodes, nf_edges = parse_module(FX / "nfcore" / "salmon_quant", ingested_at="2026-06-08")
    method_nodes = [n for n in nf_nodes if isinstance(n, MethodRecord)]
    other = [n for n in nf_nodes if not isinstance(n, MethodRecord)]
    nodes, edges = resolve(method_nodes=method_nodes, other_nodes=other, src_edges=nf_edges,
                           ingested_at="2026-06-08")
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")  # rebuild must not error
    with KuzuMethodsGraphProvider(db_path) as provider:
        assert any(m["name"] == "salmon" for m in provider.get_methods())
