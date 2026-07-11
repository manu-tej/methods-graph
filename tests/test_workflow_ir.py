"""Tests for the WorkflowIR dataclasses (no graph dependency)."""
import pytest
from methods_graph.workflow.ir import Artifact, Decision, Step, Workflow


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

def test_artifact_defaults():
    a = Artifact(id="art:1", name="counts", kind="matrix")
    assert a.produced_by is None
    assert a.edam_format is None
    assert a.properties == {}


def test_artifact_with_all_fields():
    a = Artifact(
        id="art:pca",
        name="PCA plot",
        kind="plot",
        produced_by="step1",
        edam_format="fmt:format_3547",
        properties={"resolution": "300dpi"},
    )
    assert a.produced_by == "step1"
    assert a.edam_format == "fmt:format_3547"
    assert a.properties["resolution"] == "300dpi"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_decision_defaults():
    d = Decision(id="d1", rationale="Two clusters visible")
    assert d.inputs == []
    assert d.leads_to is None
    assert d.made_by == "user"


def test_decision_with_links():
    d = Decision(
        id="d1",
        rationale="PCA shows two clusters",
        inputs=["art:pca"],
        leads_to="step2",
    )
    assert d.inputs == ["art:pca"]
    assert d.leads_to == "step2"


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

def test_step_defaults():
    s = Step(id="step1", method_id="m:salmon")
    assert s.container_id is None
    assert s.inputs == []
    assert s.outputs == []
    assert s.parameters == {}
    assert s.evidence == []


def test_step_with_all_fields():
    s = Step(
        id="step1",
        method_id="m:salmon",
        container_id="ctr:salmon",
        inputs=["art:reads"],
        outputs=["art:quant"],
        parameters={"threads": 8},
        evidence=["op:operation_3800"],
    )
    assert s.container_id == "ctr:salmon"
    assert s.inputs == ["art:reads"]
    assert s.outputs == ["art:quant"]
    assert s.parameters["threads"] == 8
    assert "op:operation_3800" in s.evidence


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_workflow():
    art1 = Artifact(id="art:reads", name="raw reads", kind="file")
    art2 = Artifact(id="art:quant", name="quant matrix", kind="matrix", produced_by="step1")
    step1 = Step(id="step1", method_id="m:salmon", inputs=["art:reads"], outputs=["art:quant"])
    d1 = Decision(id="d1", rationale="looks ok", inputs=["art:quant"], leads_to="step1")
    return Workflow(id="wf:test", steps=[step1], artifacts=[art1, art2], decisions=[d1])


def test_workflow_artifact_found(simple_workflow):
    a = simple_workflow.artifact("art:reads")
    assert a is not None
    assert a.kind == "file"


def test_workflow_artifact_not_found(simple_workflow):
    assert simple_workflow.artifact("art:ghost") is None


def test_workflow_step_found(simple_workflow):
    s = simple_workflow.step("step1")
    assert s is not None
    assert s.method_id == "m:salmon"


def test_workflow_step_not_found(simple_workflow):
    assert simple_workflow.step("step:ghost") is None


def test_workflow_defaults_empty_collections():
    wf = Workflow(id="wf:empty")
    assert wf.steps == []
    assert wf.artifacts == []
    assert wf.decisions == []


def test_lists_are_independent_between_instances():
    """Mutable default_factory lists must not be shared."""
    wf1 = Workflow(id="wf:1")
    wf2 = Workflow(id="wf:2")
    wf1.steps.append(Step(id="s1", method_id="m:x"))
    assert wf2.steps == []
