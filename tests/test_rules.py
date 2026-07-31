"""The database-free rule engine: curated YAML -> preconditions -> verdict.

The point of this module is invariance. A guardrail that can only run against a built Kùzu
artifact cannot run inside a PreToolUse hook, a CI lint step, or a notebook — so in those
places it degrades to advice, and advice is model-dependent. These tests pin the three
properties that make the engine portable: it needs no database, it agrees with the graph
path, and it cites the source of the threshold it enforced.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from methods_graph import rules
from methods_graph.guardrail import evaluate_preconditions

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB = Path("data/methods.kuzu")

# Schurch et al. 2016 — the 48-replicates-per-condition study behind the replicate floor.
_THRESHOLD_SOURCE = "10.1261/rna.053959.115"


def test_deseq2_blocks_at_one_replicate_with_no_database():
    pre = rules.load_rules().method_preconditions("m:deseq2")
    verdict = evaluate_preconditions(pre, {"replicates_per_group": 1})
    assert verdict["status"] == "BLOCKED"


def test_unmeasured_gate_does_not_certify_with_no_database():
    pre = rules.load_rules().method_preconditions("m:deseq2")
    verdict = evaluate_preconditions(pre, {})
    assert verdict["status"] == "FACTS_REQUIRED"


def test_unknown_method_raises_keyerror():
    """Same contract as the Kùzu provider, so callers need no special-casing."""
    try:
        rules.load_rules().method_preconditions("m:not-a-real-tool")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown method")


def test_the_gate_cites_the_source_of_its_threshold():
    """A refusal is only useful if it hands over the citation that justifies it. The
    threshold's provenance lives on the diagnostic (`ref:`), not on the assumption link —
    the graph path surfaces the latter, which is a statistics tutorial URL.
    """
    pre = rules.load_rules().method_preconditions("m:deseq2")
    verdict = evaluate_preconditions(pre, {"replicates_per_group": 1})
    failures = [g for g in verdict["gates"] if g["result"] == "FAIL"]
    assert failures, "expected a failing gate"
    assert any(_THRESHOLD_SOURCE in (g.get("evidence") or "") for g in failures), (
        f"no gate cited {_THRESHOLD_SOURCE}; got "
        f"{[g.get('evidence') for g in failures]}"
    )


def _imported_names(path: Path) -> set[str]:
    """Every module name imported by *path*, from its AST."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_engine_dependency_closure_excludes_the_graph_database():
    """The invariance guarantee, asserted rather than assumed.

    Checked statically over the transitive first-party import closure, not by spawning a
    probe process: the engine must be importable somewhere Kùzu is not installed and no
    database has been built, or it cannot live inside a PreToolUse hook or a CI step.
    """
    package = _REPO_ROOT / "src" / "methods_graph"
    pending = ["rules", "guardrail", "hook"]
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = package / f"{module}.py"
        if not path.exists():
            continue
        for name in _imported_names(path):
            assert "kuzu" not in name, f"methods_graph/{module}.py imports {name}"
            if name.startswith("methods_graph."):
                pending.append(name.split("methods_graph.", 1)[1])
    assert {"rules", "guardrail", "hook"} <= visited, f"nothing traversed: {visited}"


# --- parity with the graph path ---
#
# If the portable engine and the Kùzu engine disagree, "portable" is a second
# implementation rather than the same guardrail running in more places. Parity on the
# verdict is what would let the graph be removed from the enforcement path.

@pytest.mark.skipif(not _DB.exists(), reason="built DB artifact not present")
@pytest.mark.parametrize("facts", [
    {},
    {"replicates_per_group": 1, "peptides_per_protein": 1},
    {"replicates_per_group": 3, "peptides_per_protein": 2},
])
def test_yaml_engine_agrees_with_the_graph_on_every_curated_method(facts):
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

    engine = rules.load_rules()
    divergent = []
    with KuzuMethodsGraphProvider(_DB) as provider:
        for method_id in engine.method_ids():
            from_yaml = evaluate_preconditions(
                engine.method_preconditions(method_id), facts)["status"]
            try:
                from_graph = evaluate_preconditions(
                    provider.method_preconditions(method_id), facts)["status"]
            except KeyError:
                from_graph = "NOT_EVALUABLE"
            if from_yaml != from_graph:
                divergent.append((method_id, from_yaml, from_graph))
    assert not divergent, f"yaml vs graph disagreement: {divergent}"
