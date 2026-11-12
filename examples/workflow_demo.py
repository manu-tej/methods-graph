"""Runnable demo: validate a graph-grounded analysis workflow and record provenance.

This is self-contained — it builds a tiny in-memory methods graph in a temp directory
(no prior `methods-graph fetch`/`build` required) and then exercises the
workflow/provenance layer end-to-end:

    python examples/workflow_demo.py

It shows:
  1. a valid, graph-grounded RNA-seq workflow passing validation
  2. a hallucinated method id being rejected
  3. a real method that is OUTSIDE the seed subgraph being rejected (unless approved)
  4. an exploratory PCA plot modeled as an Artifact, interpreted by a user Decision
     that leads to the next Step
  5. forged "evidence" (citing a container instead of an EDAM grounding) being rejected
  6. a provenance ledger entry capturing method id, graph snapshot, inputs, outputs,
     parameters, and the user decision

To run against a REAL built graph instead, set MG_DB to a Kùzu db path
(e.g. one produced by `methods-graph build --db methods.kuzu`).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import kuzu

from methods_graph.graph.loader import build_graph
from methods_graph.types import EdgeKind, EdgeRecord, MethodRecord, NodeKind, NodeRecord, Provenance
from methods_graph.workflow import (
    Artifact,
    Decision,
    ProvenanceLedger,
    Step,
    Workflow,
    allowed_methods_from_seed,
    validate_workflow,
)


def _build_demo_graph(db_path: Path) -> None:
    """Build a tiny methods graph: a few methods, their EDAM operations, one container."""
    P = Provenance("demo", "https://example.org", "2026-06-09")
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                     {"description": "RNA-seq quantification"}, P, bioconda_pkg="salmon"),
        MethodRecord("m:deseq2", "deseq2", NodeKind.METHOD,
                     {"description": "differential expression"}, P, bioconda_pkg="deseq2"),
        MethodRecord("m:fastqc", "fastqc", NodeKind.METHOD,
                     {"description": "read QC"}, P, bioconda_pkg="fastqc"),
        MethodRecord("m:bwa", "bwa", NodeKind.METHOD,
                     {"description": "read alignment"}, P, bioconda_pkg="bwa"),
        NodeRecord("op:operation_3800", "RNA-Seq quantification", NodeKind.OPERATION, {}, P),
        NodeRecord("op:operation_3223", "Differential gene expression analysis", NodeKind.OPERATION, {}, P),
        NodeRecord("op:operation_3218", "Sequencing quality control", NodeKind.OPERATION, {}, P),
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/salmon:1.10.0"}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3800", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P),
        EdgeRecord("m:deseq2", "op:operation_3223", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:fastqc", "op:operation_3218", EdgeKind.PERFORMS, {}, P),
    ]
    build_graph(nodes, edges, db_path, staging_dir=db_path.parent / "staging")


def main() -> None:
    tmp = tempfile.TemporaryDirectory()
    db_env = os.environ.get("MG_DB")
    if db_env:
        db_path = Path(db_env)
        print(f"Using real graph at {db_path}")
    else:
        db_path = Path(tmp.name) / "demo.kuzu"
        _build_demo_graph(db_path)
        print(f"Built a self-contained demo graph at {db_path}")

    conn = kuzu.Connection(kuzu.Database(str(db_path)))

    # The analyst's working set: seed the subgraph around the methods they've chosen.
    seed_ids = ["m:fastqc", "m:salmon", "m:deseq2"]
    allowed = allowed_methods_from_seed(conn, seed_ids, k_hops=1)
    print("\nAllowed methods (seed subgraph):", sorted(allowed))

    # A real RNA-seq workflow: QC -> quantify -> exploratory PCA -> [user decides] -> DE.
    wf = Workflow(
        id="rnaseq-de",
        steps=[
            Step(id="qc", method_id="m:fastqc", evidence=["op:operation_3218"], outputs=["art:qc"]),
            Step(id="quant", method_id="m:salmon", container_id="ctr:salmon",
                 evidence=["op:operation_3800"], outputs=["art:counts"],
                 parameters={"libType": "A"}),
            Step(id="explore", method_id="m:deseq2", evidence=["op:operation_3223"],
                 inputs=["art:counts"], outputs=["art:pca"]),
            Step(id="de", method_id="m:deseq2", evidence=["op:operation_3223"],
                 inputs=["art:counts"], outputs=["art:deg"],
                 parameters={"contrast": ["condition", "treated", "control"], "alpha": 0.05}),
        ],
        artifacts=[
            Artifact("art:qc", "FastQC report", "report", produced_by="qc"),
            Artifact("art:counts", "transcript counts", "matrix", produced_by="quant"),
            Artifact("art:pca", "PCA plot", "plot", produced_by="explore"),
            Artifact("art:deg", "DE results", "table", produced_by="de"),
        ],
        decisions=[
            Decision("d1",
                     "PCA separates treated vs control along PC1 with no outliers -> proceed to DE",
                     inputs=["art:pca"], leads_to="de"),
        ],
    )

    res = validate_workflow(conn, wf, allowed_method_ids=allowed)
    print(f"\n[1] valid graph-grounded workflow      -> ok={res.ok} issues={res.issues}")
    d1 = wf.decisions[0]
    print(f"    decision interprets '{wf.artifact(d1.inputs[0]).name}' "
          f"(from step '{wf.artifact('art:pca').produced_by}') -> next step '{wf.step(d1.leads_to).id}'")

    bad = Workflow("x", steps=[Step("s", method_id="m:made_up_tool")])
    print(f"\n[2] hallucinated method                -> "
          f"codes={[i.code for i in validate_workflow(conn, bad, allowed_method_ids=allowed).issues]}")

    out = Workflow("y", steps=[Step("s", method_id="m:bwa")])
    r3a = validate_workflow(conn, out, allowed_method_ids=allowed)
    r3b = validate_workflow(conn, out, allowed_method_ids=allowed, approved_expansions=frozenset({"m:bwa"}))
    print(f"\n[3] out-of-seed method m:bwa           -> codes={[i.code for i in r3a.issues]} "
          f"| with approved_expansions -> ok={r3b.ok}")

    forged = Workflow("z", steps=[Step("s", method_id="m:salmon", evidence=["ctr:salmon"])])
    print(f"\n[4] forged evidence (container, not EDAM) -> "
          f"codes={[i.code for i in validate_workflow(conn, forged, allowed_method_ids=allowed).issues]}")

    snapshot = "nfcore@53c5d14 + EDAM(2023-05-08) + biotools@2026-06-09"
    ledger = ProvenanceLedger()
    for s in wf.steps:
        ledger.record(s, graph_snapshot=snapshot, recorded_at="2026-06-09T22:30:00Z",
                      decision=d1 if s.id == d1.leads_to else None)
    de_entry = next(e for e in ledger.entries if e.step_id == "de")
    print(f"\n[5] provenance ledger ({len(ledger.entries)} entries); 'de' step:")
    print(json.dumps(de_entry.to_dict(), indent=2, sort_keys=True))

    tmp.cleanup()


if __name__ == "__main__":
    main()
