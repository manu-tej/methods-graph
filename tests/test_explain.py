"""Tests for `mg explain` traceability (verdict -> chain -> evidence -> source YAML)."""
from __future__ import annotations

import pathlib

import pytest

from methods_graph.explain import _resolve_yaml_source, explain

_DB = pathlib.Path("data/methods.kuzu")
_gated = pytest.mark.skipif(not _DB.exists(), reason="built DB artifact not present")


def test_resolve_yaml_source_matches_token_to_all_files(tmp_path):
    (tmp_path / "a.yaml").write_text("note: grounded by doi:10.1234/real\n")
    (tmp_path / "b.yaml").write_text("note: something else\n")
    (tmp_path / "c.yaml").write_text("ref: doi:10.1234/real (also here)\n")
    # returns ALL files carrying the token (sorted), not a single guess
    assert _resolve_yaml_source("doi:10.1234/real", tmp_path) == ["a.yaml", "c.yaml"]
    assert _resolve_yaml_source("doi:10.0000/absent", tmp_path) == []
    assert _resolve_yaml_source("", tmp_path) == []


@_gated
def test_explain_scanpy_traces_single_cell_chain_to_yaml():
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    with KuzuMethodsGraphProvider(_DB) as p:
        traces = explain(p, method="m:scanpy")
    assert traces, "scanpy should have grounded assumptions"
    t = next(t for t in traces if "unsupervised" in t["assumption"].lower())
    # the via-chain names the operation it is inherited through
    assert any(v.get("operation") == "Expression profile clustering" for v in t["via"])
    # the evidence DOI resolves to the curating YAML file
    assert t["evidence"] == "doi:10.1038/s41467-021-25960-2"
    assert "statistical_method_assumptions.yaml" in t["source_yaml"]


@_gated
def test_explain_registry_only_method_is_honest():
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    with KuzuMethodsGraphProvider(_DB) as p:
        # m:anndata is a registry-only data container with no evaluability chain
        assert explain(p, method="m:anndata") == []


@_gated
def test_explain_unknown_method_raises_keyerror():
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    with KuzuMethodsGraphProvider(_DB) as p:
        with pytest.raises(KeyError):
            explain(p, method="m:does-not-exist")
