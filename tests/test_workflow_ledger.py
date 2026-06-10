"""Tests for the ProvenanceLedger (no graph, no network)."""
import json

import pytest

from methods_graph.workflow.ir import Artifact, Decision, Step
from methods_graph.workflow.ledger import LedgerEntry, ProvenanceLedger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def step1():
    return Step(
        id="step1",
        method_id="m:salmon",
        container_id="ctr:salmon",
        inputs=["art:reads"],
        outputs=["art:quant"],
        parameters={"threads": 8, "libType": "A"},
        evidence=["op:operation_3800"],
    )


@pytest.fixture
def step2():
    return Step(
        id="step2",
        method_id="m:deseq2",
        inputs=["art:quant"],
        outputs=["art:de_results"],
        parameters={"alpha": 0.05},
    )


@pytest.fixture
def decision1():
    return Decision(
        id="d1",
        rationale="PCA shows two clusters → run differential expression",
        inputs=["art:pca"],
        leads_to="step2",
    )


# ---------------------------------------------------------------------------
# Test 5: ledger records all fields
# ---------------------------------------------------------------------------


def test_ledger_records_all_fields(step1, decision1):
    """record() captures method_id, graph_snapshot, inputs, outputs, parameters, decision."""
    ledger = ProvenanceLedger()
    entry = ledger.record(
        step1,
        graph_snapshot="2026-06-09T22:01:49Z",
        recorded_at="2026-06-09T22:05:00Z",
        decision=decision1,
    )

    # Check returned LedgerEntry
    assert isinstance(entry, LedgerEntry)
    assert entry.step_id == "step1"
    assert entry.method_id == "m:salmon"
    assert entry.graph_snapshot == "2026-06-09T22:01:49Z"
    assert entry.recorded_at == "2026-06-09T22:05:00Z"
    assert entry.inputs == ["art:reads"]
    assert entry.outputs == ["art:quant"]
    assert entry.parameters == {"threads": 8, "libType": "A"}
    assert entry.decision_id == "d1"
    assert "PCA shows two clusters" in entry.decision_rationale


def test_ledger_to_json_contains_all_fields(step1, decision1):
    """to_json() serialises all expected fields into valid JSON."""
    ledger = ProvenanceLedger()
    ledger.record(
        step1,
        graph_snapshot="2026-06-09T22:01:49Z",
        recorded_at="2026-06-09T22:05:00Z",
        decision=decision1,
    )
    raw = ledger.to_json()
    parsed = json.loads(raw)  # must be valid JSON
    assert len(parsed) == 1
    e = parsed[0]
    assert e["method_id"] == "m:salmon"
    assert e["graph_snapshot"] == "2026-06-09T22:01:49Z"
    assert e["recorded_at"] == "2026-06-09T22:05:00Z"
    assert e["inputs"] == ["art:reads"]
    assert e["outputs"] == ["art:quant"]
    assert e["parameters"]["threads"] == 8
    assert e["decision_id"] == "d1"
    assert "PCA shows two clusters" in e["decision_rationale"]


def test_ledger_second_record_appends(step1, step2, decision1):
    """A second record() call appends; ledger has 2 entries and to_json is valid."""
    ledger = ProvenanceLedger()
    ledger.record(
        step1,
        graph_snapshot="2026-06-09T22:01:49Z",
        recorded_at="2026-06-09T22:05:00Z",
        decision=decision1,
    )
    ledger.record(
        step2,
        graph_snapshot="2026-06-09T22:01:49Z",
        recorded_at="2026-06-09T22:10:00Z",
    )
    assert len(ledger.entries) == 2
    raw = ledger.to_json()
    parsed = json.loads(raw)
    assert len(parsed) == 2
    step_ids = [e["step_id"] for e in parsed]
    assert "step1" in step_ids
    assert "step2" in step_ids


# ---------------------------------------------------------------------------
# Additional ledger tests
# ---------------------------------------------------------------------------


def test_ledger_no_decision_has_none_fields(step1):
    """When no decision is passed, decision_id and decision_rationale are None."""
    ledger = ProvenanceLedger()
    entry = ledger.record(
        step1,
        graph_snapshot="snap-001",
        recorded_at="2026-06-10T00:00:00Z",
    )
    assert entry.decision_id is None
    assert entry.decision_rationale is None


def test_ledger_entries_property_returns_copy(step1):
    """entries property returns a copy, not the internal list."""
    ledger = ProvenanceLedger()
    ledger.record(step1, graph_snapshot="s", recorded_at="2026-06-10T00:00:00Z")
    entries_a = ledger.entries
    entries_b = ledger.entries
    assert entries_a is not entries_b  # separate list objects
    assert len(entries_a) == 1


def test_to_dict_keys_are_sorted(step1):
    """LedgerEntry.to_dict() must contain all expected keys."""
    ledger = ProvenanceLedger()
    entry = ledger.record(
        step1,
        graph_snapshot="sha:abc123",
        recorded_at="2026-06-10T00:00:00Z",
    )
    d = entry.to_dict()
    required_keys = {
        "step_id", "method_id", "graph_snapshot", "inputs",
        "outputs", "parameters", "decision_id", "decision_rationale",
        "recorded_at",
    }
    assert required_keys <= set(d.keys())


def test_to_json_is_deterministic(step1):
    """Two separate calls to to_json() on the same ledger produce identical output."""
    ledger = ProvenanceLedger()
    ledger.record(step1, graph_snapshot="snap", recorded_at="2026-06-10T00:00:00Z")
    assert ledger.to_json() == ledger.to_json()


def test_to_json_uses_sort_keys(step1):
    """JSON output keys must be lexicographically sorted (sort_keys=True)."""
    ledger = ProvenanceLedger()
    ledger.record(step1, graph_snapshot="snap", recorded_at="2026-06-10T00:00:00Z")
    raw = ledger.to_json()
    parsed = json.loads(raw)
    keys = list(parsed[0].keys())
    assert keys == sorted(keys)


def test_empty_ledger_to_json():
    """An empty ledger serialises to an empty JSON array."""
    ledger = ProvenanceLedger()
    assert ledger.to_json().strip() == "[]"


def test_step_mutation_does_not_affect_entry(step1):
    """Modifying step.parameters after recording does not mutate the entry."""
    ledger = ProvenanceLedger()
    entry = ledger.record(step1, graph_snapshot="s", recorded_at="2026-06-10T00:00:00Z")
    original_threads = entry.parameters["threads"]
    step1.parameters["threads"] = 9999
    assert entry.parameters["threads"] == original_threads
