"""Tests for workflow validation against the Kùzu graph.

Fixture graph:
  - m:salmon    (Method, bioconda_pkg="salmon")
  - m:bwa       (Method, bioconda_pkg="bwa")  — exists, NO edges
  - m:deseq2    (Method)                       — exists, PERFORMS op:operation_3800
  - op:operation_3800  (Operation, "RNA-Seq quantification")
  - ctr:salmon  (Container)
  Edges:
    m:salmon  -PERFORMS->    op:operation_3800
    m:salmon  -PACKAGED_AS-> ctr:salmon
    m:deseq2  -PERFORMS->    op:operation_3800
"""
import kuzu
import pytest

from methods_graph.graph.loader import build_graph
from methods_graph.types import (
    EdgeKind,
    EdgeRecord,
    MethodRecord,
    NodeKind,
    NodeRecord,
    Provenance,
)
from methods_graph.workflow.ir import Artifact, Decision, Step, Workflow
from methods_graph.workflow.validator import (
    ValidationResult,
    allowed_methods_from_seed,
    validate_workflow,
)

P = Provenance("test", "x", "2026-06-10")


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P, bioconda_pkg="salmon"),
        MethodRecord("m:bwa", "bwa", NodeKind.METHOD, {}, P, bioconda_pkg="bwa"),
        MethodRecord("m:deseq2", "DESeq2", NodeKind.METHOD, {}, P),
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P),
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER, {}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3800", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P),
        EdgeRecord("m:deseq2", "op:operation_3800", EdgeKind.PERFORMS, {}, P),
    ]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db_path)))


# ---------------------------------------------------------------------------
# Test 1: valid graph-grounded step passes
# ---------------------------------------------------------------------------


def test_valid_step_passes(conn):
    """A fully grounded step (method exists, container packaged, evidence linked) → ok."""
    art_in = Artifact(id="art:reads", name="reads", kind="file")
    art_out = Artifact(id="art:quant", name="quant", kind="matrix", produced_by="step1")
    step = Step(
        id="step1",
        method_id="m:salmon",
        container_id="ctr:salmon",
        inputs=["art:reads"],
        outputs=["art:quant"],
        evidence=["op:operation_3800"],
    )
    wf = Workflow(id="wf:1", steps=[step], artifacts=[art_in, art_out])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is True
    assert result.issues == []


# ---------------------------------------------------------------------------
# Test 2: hallucinated method id fails
# ---------------------------------------------------------------------------


def test_hallucinated_method_fails(conn):
    """A step referencing a non-existent method id → method_not_found."""
    step = Step(id="step1", method_id="m:NOTREAL")
    wf = Workflow(id="wf:2", steps=[step])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "method_not_found" in codes


# ---------------------------------------------------------------------------
# Test 3: method outside seed fails unless explicitly allowed
# ---------------------------------------------------------------------------


def test_method_outside_seed_fails(conn):
    """m:bwa exists but is not in allowed_method_ids → method_not_allowed."""
    step = Step(id="step1", method_id="m:bwa")
    wf = Workflow(id="wf:3", steps=[step])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "method_not_allowed" in codes
    assert "method_not_found" not in codes


def test_method_outside_seed_passes_with_approved_expansion(conn):
    """Same workflow but with approved_expansions={"m:bwa"} → passes."""
    step = Step(id="step1", method_id="m:bwa")
    wf = Workflow(id="wf:3", steps=[step])
    result = validate_workflow(
        conn,
        wf,
        allowed_method_ids={"m:salmon"},
        approved_expansions={"m:bwa"},
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# Test 4: decision linking artifacts across steps
# ---------------------------------------------------------------------------


def test_decision_links_plot_to_next_step(conn):
    """Decision connects a plot artifact produced by step1 to step2; validation passes."""
    art_reads = Artifact(id="art:reads", name="reads", kind="file")
    art_pca = Artifact(id="art:pca", name="PCA plot", kind="plot", produced_by="step1")
    art_de = Artifact(id="art:de", name="DE results", kind="table", produced_by="step2")

    step1 = Step(
        id="step1",
        method_id="m:salmon",
        container_id="ctr:salmon",
        inputs=["art:reads"],
        outputs=["art:pca"],
        evidence=["op:operation_3800"],
    )
    step2 = Step(
        id="step2",
        method_id="m:deseq2",
        inputs=["art:pca"],
        outputs=["art:de"],
        evidence=["op:operation_3800"],
    )
    d1 = Decision(
        id="d1",
        rationale="PCA shows two clusters → run differential expression",
        inputs=["art:pca"],
        leads_to="step2",
    )
    wf = Workflow(
        id="wf:4",
        steps=[step1, step2],
        artifacts=[art_reads, art_pca, art_de],
        decisions=[d1],
    )
    result = validate_workflow(
        conn, wf, allowed_method_ids={"m:salmon", "m:deseq2"}
    )
    assert result.ok is True

    # IR coherence checks
    art_pca_node = wf.artifact("art:pca")
    assert art_pca_node is not None
    assert art_pca_node.produced_by == "step1"

    step2_node = wf.step(d1.leads_to)
    assert step2_node is not None
    assert step2_node.id == "step2"


def test_decision_unknown_artifact_fails(conn):
    """Decision referencing an unknown input artifact → decision_input_unknown."""
    d_bad = Decision(
        id="d_bad",
        rationale="ghost artifact",
        inputs=["art:ghost"],
    )
    wf = Workflow(id="wf:4b", decisions=[d_bad])
    result = validate_workflow(conn, wf, allowed_method_ids=set())
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "decision_input_unknown" in codes


def test_decision_unknown_leads_to_fails(conn):
    """Decision with leads_to pointing to unknown step → decision_leads_to_unknown."""
    d_bad = Decision(
        id="d_bad",
        rationale="leads nowhere",
        leads_to="step:ghost",
    )
    wf = Workflow(id="wf:4c", decisions=[d_bad])
    result = validate_workflow(conn, wf, allowed_method_ids=set())
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "decision_leads_to_unknown" in codes


# ---------------------------------------------------------------------------
# Test 5: evidence_missing negatives
# ---------------------------------------------------------------------------


def test_evidence_missing_nonexistent_node(conn):
    """Evidence id that doesn't exist in the graph → evidence_missing."""
    step = Step(
        id="step1",
        method_id="m:salmon",
        evidence=["op:operation_9999"],  # does not exist
    )
    wf = Workflow(id="wf:5a", steps=[step])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "evidence_missing" in codes


def test_evidence_missing_no_edge_to_node(conn):
    """Evidence node exists but method has no edge to it → evidence_missing.

    m:bwa exists but has no edges; op:operation_3800 exists but m:bwa has
    no PERFORMS edge to it.
    """
    step = Step(
        id="step1",
        method_id="m:bwa",
        evidence=["op:operation_3800"],  # exists, but no edge from m:bwa
    )
    wf = Workflow(id="wf:5b", steps=[step])
    result = validate_workflow(
        conn, wf, allowed_method_ids={"m:bwa"}, approved_expansions={"m:bwa"}
    )
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "evidence_missing" in codes


# ---------------------------------------------------------------------------
# Test 6: container_not_packaged negative
# ---------------------------------------------------------------------------


def test_container_not_packaged(conn):
    """Container id set but no PACKAGED_AS edge → container_not_packaged."""
    step = Step(
        id="step1",
        method_id="m:salmon",
        container_id="ctr:bogus",  # no PACKAGED_AS edge to this
    )
    wf = Workflow(id="wf:6", steps=[step])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "container_not_packaged" in codes


# ---------------------------------------------------------------------------
# Test 7: allowed_methods_from_seed helper
# ---------------------------------------------------------------------------


def test_allowed_methods_from_seed(conn):
    """Seed on m:salmon should return {m:salmon} as Method nodes."""
    methods = allowed_methods_from_seed(conn, ["m:salmon"], k_hops=1)
    assert "m:salmon" in methods
    # op:operation_3800 and ctr:salmon are NOT Methods
    assert "op:operation_3800" not in methods
    assert "ctr:salmon" not in methods


def test_allowed_methods_from_seed_empty(conn):
    assert allowed_methods_from_seed(conn, []) == set()


# ---------------------------------------------------------------------------
# Test 8: all issues collected (no early exit)
# ---------------------------------------------------------------------------


def test_multiple_issues_collected(conn):
    """Two steps with separate issues — both should appear in the result."""
    step1 = Step(id="s1", method_id="m:NOTREAL")  # method_not_found
    step2 = Step(id="s2", method_id="m:bwa")       # method_not_allowed
    wf = Workflow(id="wf:multi", steps=[step1, step2])
    result = validate_workflow(conn, wf, allowed_method_ids={"m:salmon"})
    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "method_not_found" in codes
    assert "method_not_allowed" in codes
