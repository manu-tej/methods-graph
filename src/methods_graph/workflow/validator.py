"""Validate a WorkflowIR against the Kùzu methods graph."""
from __future__ import annotations

from dataclasses import dataclass, field

import kuzu

from methods_graph.extract.seed import seed
from methods_graph.workflow.ir import Workflow


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    step_id: str  # "" for workflow-level issues
    code: str
    detail: str


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper — derive the allowed method set from a seed subgraph
# ---------------------------------------------------------------------------


def allowed_methods_from_seed(
    conn: kuzu.Connection,
    seed_ids: list[str],
    *,
    k_hops: int = 1,
) -> set[str]:
    """Run seed(…) and return the set of node ids where kind == 'Method'."""
    sg = seed(conn, seed_ids, k_hops=k_hops)
    return {n["id"] for n in sg.nodes if n["kind"] == "Method"}


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------


def validate_workflow(
    conn: kuzu.Connection,
    workflow: Workflow,
    *,
    allowed_method_ids: set[str],
    approved_expansions: frozenset[str] = frozenset(),
) -> ValidationResult:
    """Validate every step and decision in *workflow* against the graph.

    All issues are collected (no early exit). Returns a ValidationResult
    whose ``ok`` flag is True only when no issues were found.

    Issue codes
    -----------
    method_not_found         — method node doesn't exist in the graph
    method_not_allowed       — method exists but is outside the allowed set
    container_not_packaged   — no PACKAGED_AS edge from method to container
    evidence_missing         — evidence node absent or no semantic edge to it
    input_artifact_unknown   — step.inputs references undeclared artifact
    output_artifact_unknown  — step.outputs references undeclared artifact
    output_not_produced_here — artifact.produced_by conflicts with this step
    decision_input_unknown   — decision.inputs references undeclared artifact
    decision_leads_to_unknown — decision.leads_to references unknown step
    input_contract_violation — artifact edam_format not in method's INPUT contract
    output_contract_violation — artifact edam_format not in method's OUTPUT contract

    Contract-check rule (opt-in)
    ----------------------------
    A contract issue is raised only when BOTH conditions hold:
      1. The method has a non-empty INPUT (or OUTPUT) contract in the graph
         (i.e. at least one edge of that kind exists).
      2. The artifact declares a non-empty edam_format.
    If either condition is absent, no issue is raised — absence of a declared
    contract is not treated as a violation.
    """
    issues: list[ValidationIssue] = []

    # Pre-build known artifact and step id sets for O(1) lookups.
    known_artifact_ids: set[str] = {a.id for a in workflow.artifacts}
    known_step_ids: set[str] = {s.id for s in workflow.steps}

    # Effective allow-list is the union of seeded methods and explicit expansions.
    effective_allowed = allowed_method_ids | set(approved_expansions)

    for step in workflow.steps:
        sid = step.id
        mid = step.method_id

        # 1. method_not_found — check that the node actually exists in the graph.
        exists_res = list(conn.execute(
            "MATCH (m:Entity {id: $id, kind: 'Method'}) RETURN m.id",
            parameters={"id": mid},
        ))
        method_exists = len(exists_res) > 0

        if not method_exists:
            issues.append(ValidationIssue(
                step_id=sid,
                code="method_not_found",
                detail=f"Method node '{mid}' does not exist in the graph.",
            ))
            # Skip further step checks that depend on the method existing.
            continue

        # 2. method_not_allowed — in graph but outside allow-list.
        if mid not in effective_allowed:
            issues.append(ValidationIssue(
                step_id=sid,
                code="method_not_allowed",
                detail=(
                    f"Method '{mid}' exists in the graph but is not in the allowed "
                    "set. Add it to approved_expansions to permit it."
                ),
            ))

        # 3. container_not_packaged — if container_id set, must have PACKAGED_AS edge.
        if step.container_id is not None:
            cid = step.container_id
            pkg_res = list(conn.execute(
                "MATCH (m:Entity {id: $mid})-[r:Rel {kind: 'PACKAGED_AS'}]->(c:Entity {id: $cid}) "
                "RETURN c.id",
                parameters={"mid": mid, "cid": cid},
            ))
            if not pkg_res:
                issues.append(ValidationIssue(
                    step_id=sid,
                    code="container_not_packaged",
                    detail=(
                        f"No PACKAGED_AS edge from '{mid}' to container '{cid}'."
                    ),
                ))

        # 4. evidence_missing — each evidence id must exist AND have an edge from method.
        for eid in step.evidence:
            # Check node existence.
            node_res = list(conn.execute(
                "MATCH (e:Entity {id: $eid}) RETURN e.id",
                parameters={"eid": eid},
            ))
            if not node_res:
                issues.append(ValidationIssue(
                    step_id=sid,
                    code="evidence_missing",
                    detail=f"Evidence node '{eid}' does not exist in the graph.",
                ))
                continue

            # Check semantic edge from method to evidence node.
            # Only PERFORMS, INPUT, and OUTPUT count as genuine EDAM grounding;
            # non-semantic edges (e.g. PACKAGED_AS) do not.  (HAS_TOPIC was dropped
            # with the Topic layer.)
            edge_res = list(conn.execute(
                "MATCH (m:Entity {id: $mid})-[r:Rel]->(e:Entity {id: $eid}) "
                "WHERE r.kind IN ['PERFORMS','INPUT','OUTPUT'] RETURN e.id",
                parameters={"mid": mid, "eid": eid},
            ))
            if not edge_res:
                issues.append(ValidationIssue(
                    step_id=sid,
                    code="evidence_missing",
                    detail=(
                        f"No semantic grounding edge (PERFORMS/INPUT/OUTPUT) "
                        f"from method '{mid}' to evidence node '{eid}'."
                    ),
                ))

        # 5a. input_artifact_unknown
        for art_id in step.inputs:
            if art_id not in known_artifact_ids:
                issues.append(ValidationIssue(
                    step_id=sid,
                    code="input_artifact_unknown",
                    detail=f"Input artifact '{art_id}' is not declared in workflow.artifacts.",
                ))

        # 5b. output_artifact_unknown + output_not_produced_here
        for art_id in step.outputs:
            if art_id not in known_artifact_ids:
                issues.append(ValidationIssue(
                    step_id=sid,
                    code="output_artifact_unknown",
                    detail=f"Output artifact '{art_id}' is not declared in workflow.artifacts.",
                ))
            else:
                art = workflow.artifact(art_id)
                if art is not None and art.produced_by is not None and art.produced_by != sid:
                    issues.append(ValidationIssue(
                        step_id=sid,
                        code="output_not_produced_here",
                        detail=(
                            f"Artifact '{art_id}' has produced_by='{art.produced_by}' "
                            f"but is listed in outputs of step '{sid}'."
                        ),
                    ))

        # 6. Contract checks: input_contract_violation / output_contract_violation
        #
        # These checks are opt-in — both conditions must hold before an issue is raised:
        #   1. The method declares a non-empty contract for that direction
        #      (has at least one INPUT or OUTPUT edge in the graph).
        #   2. The artifact declares a non-empty edam_format.
        # If EITHER condition is absent (no contract OR no edam_format), no issue.
        # This prevents false positives for methods whose I/O contracts are not yet
        # described in the graph and for artifacts that omit EDAM annotation.
        input_contract: set[str] = {
            row[0]
            for row in conn.execute(
                "MATCH (m:Entity {id: $mid})-[:Rel {kind: 'INPUT'}]->(d:Entity)"
                " RETURN d.id",
                parameters={"mid": mid},
            )
        }
        output_contract: set[str] = {
            row[0]
            for row in conn.execute(
                "MATCH (m:Entity {id: $mid})-[:Rel {kind: 'OUTPUT'}]->(d:Entity)"
                " RETURN d.id",
                parameters={"mid": mid},
            )
        }

        if input_contract:
            for art_id in step.inputs:
                art = workflow.artifact(art_id)
                if art is not None and art.edam_format:
                    if art.edam_format not in input_contract:
                        issues.append(ValidationIssue(
                            step_id=sid,
                            code="input_contract_violation",
                            detail=(
                                f"Artifact '{art_id}' declares edam_format "
                                f"'{art.edam_format}' but method '{mid}' does not "
                                f"list it as an INPUT (contract: {sorted(input_contract)})."
                            ),
                        ))

        if output_contract:
            for art_id in step.outputs:
                art = workflow.artifact(art_id)
                if art is not None and art.edam_format:
                    if art.edam_format not in output_contract:
                        issues.append(ValidationIssue(
                            step_id=sid,
                            code="output_contract_violation",
                            detail=(
                                f"Artifact '{art_id}' declares edam_format "
                                f"'{art.edam_format}' but method '{mid}' does not "
                                f"list it as an OUTPUT (contract: {sorted(output_contract)})."
                            ),
                        ))

    # Workflow-level decision checks (step_id = "")
    for decision in workflow.decisions:
        # 6. decision_input_unknown
        for art_id in decision.inputs:
            if art_id not in known_artifact_ids:
                issues.append(ValidationIssue(
                    step_id="",
                    code="decision_input_unknown",
                    detail=(
                        f"Decision '{decision.id}' references unknown artifact '{art_id}'."
                    ),
                ))

        # 7. decision_leads_to_unknown
        if decision.leads_to is not None and decision.leads_to not in known_step_ids:
            issues.append(ValidationIssue(
                step_id="",
                code="decision_leads_to_unknown",
                detail=(
                    f"Decision '{decision.id}' leads_to unknown step '{decision.leads_to}'."
                ),
            ))

    return ValidationResult(ok=not issues, issues=issues)
