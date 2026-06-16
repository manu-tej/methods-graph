"""Offline tests that validate representative objects against the LinkML schema.

All tests are deterministic and do no network I/O.  The LinkML validator runs
entirely from the local schema file.

Key invariant: every dict passed to ``validate()`` must conform to the slot
types declared in the schema.  ``parameters`` and ``properties`` on the
workflow IR classes are declared as ``range: string``; because the Python
dataclasses store them as ``dict``, we pre-serialise those fields to JSON
strings via :func:`_ir_to_dict`.  All other fields map directly.
"""
from __future__ import annotations

import dataclasses
import json

import pytest
from linkml.validator import validate
from linkml.validator.report import Severity
from linkml_runtime.utils.schemaview import SchemaView

from methods_graph.schema import schema_path
from methods_graph.workflow import Artifact, Decision, Step, Workflow

# ---------------------------------------------------------------------------
# Module-scoped fixtures — compile the schema once per session for speed
# ---------------------------------------------------------------------------

_SCHEMA_STR: str | None = None
_SCHEMA_PATH: str | None = None


def _sp() -> str:
    """Return the schema file path as a string (cached)."""
    global _SCHEMA_PATH
    if _SCHEMA_PATH is None:
        _SCHEMA_PATH = str(schema_path())
    return _SCHEMA_PATH


def _sv() -> SchemaView:
    """Return a module-scoped SchemaView (cached at import time)."""
    global _SCHEMA_STR
    if _SCHEMA_STR is None:
        _SCHEMA_STR = schema_path().read_text()
    return SchemaView(_SCHEMA_STR)


@pytest.fixture(scope="module")
def schema_view() -> SchemaView:
    return _sv()


def _errors(report) -> list:
    """Return only ERROR-severity results from a ValidationReport."""
    return [r for r in report.results if r.severity == Severity.ERROR]


def _ir_to_dict(obj) -> dict:
    """Convert a workflow IR dataclass to a validation-ready dict.

    ``dict``-valued fields (``parameters``, ``properties``) are serialised to
    JSON strings to match the schema's ``range: string`` declaration.
    """
    raw = dataclasses.asdict(obj)

    def _coerce(node):
        if isinstance(node, dict):
            return {k: (json.dumps(v) if isinstance(v, dict) else _coerce(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [_coerce(i) for i in node]
        return node

    return _coerce(raw)


# ---------------------------------------------------------------------------
# Graph node tests
# ---------------------------------------------------------------------------


def test_method_node_validates():
    method = {
        "id": "m:salmon",
        "name": "salmon",
        "source": "nfcore",
        "source_url": "https://nf-co.re/modules/salmon_quant",
        "ingested_at": "2026-06-10",
        "bioconda_pkg": "salmon",
        "biotools_id": "salmon",
        "version": "1.10.0",
        "description": "Highly accurate and fast RNA-seq quantifier.",
    }
    report = validate(method, _sp(), target_class="Method")
    assert _errors(report) == [], _errors(report)


def test_edam_nodes_validate():
    operation = {
        "id": "edam:operation_3258",
        "name": "Transcriptome assembly",
        "source": "edam",
        "source_url": "http://edamontology.org/operation_3258",
        "ingested_at": "2026-06-10",
    }
    report_op = validate(operation, _sp(), target_class="Operation")
    assert _errors(report_op) == [], _errors(report_op)

    fmt = {
        "id": "edam:format_1929",
        "name": "FASTA",
        "source": "edam",
        "source_url": "http://edamontology.org/format_1929",
        "ingested_at": "2026-06-10",
    }
    report_fmt = validate(fmt, _sp(), target_class="Format")
    assert _errors(report_fmt) == [], _errors(report_fmt)


def test_container_validates():
    container = {
        "id": "ctr:biocontainers-salmon-1.10.0",
        "name": "salmon:1.10.0--h7e5ed60_0",
        "source": "biocontainers",
        "source_url": "https://depot.galaxyproject.org/singularity/salmon:1.10.0--h7e5ed60_0",
        "ingested_at": "2026-06-10",
    }
    report = validate(container, _sp(), target_class="Container")
    assert _errors(report) == [], _errors(report)


def test_package_validates():
    package = {
        "id": "pkg:bioconda-salmon",
        "name": "salmon",
        "source": "bioconda",
        "source_url": "https://anaconda.org/bioconda/salmon",
        "ingested_at": "2026-06-10",
    }
    report = validate(package, _sp(), target_class="Package")
    assert _errors(report) == [], _errors(report)


# ---------------------------------------------------------------------------
# Workflow IR tests
# ---------------------------------------------------------------------------


def _make_workflow() -> Workflow:
    """Build a representative Workflow IR object."""
    return Workflow(
        id="wf:rnaseq-01",
        steps=[
            Step(
                id="s1",
                method_id="m:salmon",
                container_id="ctr:salmon-1.10",
                inputs=["a:reads"],
                outputs=["a:quant"],
                parameters={"threads": "8", "libType": "A"},
                evidence=["m:salmon"],
            )
        ],
        artifacts=[
            Artifact(
                id="a:reads",
                name="raw reads",
                kind="file",
                edam_format="edam:format_1930",
                properties={"paired": "true"},
            ),
            Artifact(
                id="a:quant",
                name="quantification matrix",
                kind="plot",
                produced_by="s1",
                properties={},
            ),
        ],
        decisions=[
            Decision(
                id="d1",
                rationale="Salmon chosen for speed and accuracy on bulk RNA-seq data.",
                inputs=["a:quant"],
                leads_to="s1",
                made_by="user",
            )
        ],
    )


def test_workflow_validates():
    wf = _make_workflow()
    wf_dict = _ir_to_dict(wf)
    report = validate(wf_dict, _sp(), target_class="Workflow")
    assert _errors(report) == [], _errors(report)


def test_step_artifact_decision_validate():
    wf = _make_workflow()

    step_dict = _ir_to_dict(wf.steps[0])
    r_step = validate(step_dict, _sp(), target_class="Step")
    assert _errors(r_step) == [], _errors(r_step)

    artifact_dict = _ir_to_dict(wf.artifacts[0])
    r_artifact = validate(artifact_dict, _sp(), target_class="Artifact")
    assert _errors(r_artifact) == [], _errors(r_artifact)

    decision_dict = _ir_to_dict(wf.decisions[0])
    r_decision = validate(decision_dict, _sp(), target_class="Decision")
    assert _errors(r_decision) == [], _errors(r_decision)


# ---------------------------------------------------------------------------
# Negative test
# ---------------------------------------------------------------------------


def test_invalid_object_fails():
    """A Method dict missing the required 'id' field must produce validation errors."""
    bad_method = {"name": "salmon"}
    report = validate(bad_method, _sp(), target_class="Method")
    assert len(_errors(report)) >= 1, "Expected at least one ERROR for missing required id"
    error_messages = [r.message for r in _errors(report)]
    assert any("id" in m for m in error_messages), (
        f"Expected error mentioning 'id', got: {error_messages}"
    )


# ---------------------------------------------------------------------------
# Schema structural tests
# ---------------------------------------------------------------------------

EXPECTED_NODE_CLASSES = {
    "Method",
    "Module",
    "Pipeline",
    "Container",
    "Package",
    "Operation",
    "Data",
    "Format",
    "Paper",
}

EXPECTED_WORKFLOW_CLASSES = {
    "Workflow",
    "Step",
    "Artifact",
    "Decision",
}

EXPECTED_EXTENSION_CLASSES = {
    "StatisticalMethod",
    "Assumption",
    "Diagnostic",
    "Assay",
    "Protocol",
    "StudyDesign",
    "Material",
    "Instrument",
}


def test_extension_point_classes_present(schema_view: SchemaView):
    """All 8 extension-point classes, all 9 node classes, and all 4 workflow
    classes must be defined in the schema."""
    all_class_names = set(schema_view.all_classes().keys())

    missing_extensions = EXPECTED_EXTENSION_CLASSES - all_class_names
    assert missing_extensions == set(), (
        f"Missing extension-point classes: {missing_extensions}"
    )

    missing_nodes = EXPECTED_NODE_CLASSES - all_class_names
    assert missing_nodes == set(), (
        f"Missing node classes: {missing_nodes}"
    )

    missing_workflow = EXPECTED_WORKFLOW_CLASSES - all_class_names
    assert missing_workflow == set(), (
        f"Missing workflow IR classes: {missing_workflow}"
    )


# ---------------------------------------------------------------------------
# Grounded cross-link slots: uses_statistical_method / requires_assumption
# ---------------------------------------------------------------------------


def test_crosslink_slots_present(schema_view: SchemaView):
    """Both grounded cross-link relationship slots must be defined in the schema."""
    slot_names = set(schema_view.all_slots().keys())
    missing = {"uses_statistical_method", "requires_assumption"} - slot_names
    assert missing == set(), f"Missing cross-link slots: {missing}"


def test_method_uses_statistical_method_validates():
    """A Method may declare uses_statistical_method referencing StatisticalMethod ids."""
    method = {
        "id": "m:deseq2",
        "name": "deseq2",
        "source": "nfcore",
        "source_url": "https://nf-co.re/modules/deseq2",
        "ingested_at": "2026-06-10",
        "uses_statistical_method": ["obo:STATO_0000559", "obo:OBI_0200036"],
    }
    report = validate(method, _sp(), target_class="Method")
    assert _errors(report) == [], _errors(report)


def test_statistical_method_requires_assumption_validates():
    """A StatisticalMethod may declare requires_assumption referencing Assumption ids."""
    sm = {
        "id": "obo:STATO_0000559",
        "name": "Wald test",
        "source": "stato",
        "source_url": "http://purl.obolibrary.org/obo/STATO_0000559",
        "ingested_at": "2026-06-10",
        "requires_assumption": ["assum:asymptotic_normality", "assum:independence"],
    }
    report = validate(sm, _sp(), target_class="StatisticalMethod")
    assert _errors(report) == [], _errors(report)
