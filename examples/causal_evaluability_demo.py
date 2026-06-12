"""Make a biological hypothesis an EVALUABLE causal graph.

Scenario query:
    "How does AXL inhibition affect pAKT signalling in paclitaxel-resistant cancers?"

An LLM decomposes that into a causal DAG. This demo plays the *methods broker*:
for every edge it runs the causal-inference loop

    model  ->  IDENTIFY  ->  ESTIMATE  ->  REFUTE

  * IDENTIFY (evaluability)  — is the causal effect recoverable from the proposed
    design?  Records the estimand, the identification strategy, the *causal*
    assumptions (exchangeability / positivity / consistency-SUTVA / cross-world),
    and refutation tests.  A non-identifiable edge is flagged WITH the intervention
    that would make it evaluable.  (This in-script structure is a prototype of the
    future Estimand / IdentificationStrategy / CausalAssumption / RefutationTest
    graph layer.)
  * ESTIMATE — the estimator + its *statistical* assumptions are pulled live from
    the methods graph (USES_STATISTICAL_METHOD / REQUIRES_ASSUMPTION), each cited.
    A missing tool is reported as a coverage gap, never invented.
  * The identifiable + grounded edges are assembled into a Workflow and checked by
    validate_workflow against the graph (hallucinated method + forged evidence are
    rejected).

Run (self-contained):           python examples/causal_evaluability_demo.py
Run against the real graph:     MG_DB=/tmp/mg-as.kuzu python examples/causal_evaluability_demo.py
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import kuzu

from methods_graph.extract.seed import method_neighborhood
from methods_graph.graph.loader import build_graph
from methods_graph.types import (
    EdgeKind, EdgeRecord, MethodRecord, NodeKind, NodeRecord, Provenance,
)
from methods_graph.workflow import Step, Workflow, allowed_methods_from_seed, validate_workflow


# ───────────────────────── the causal hypothesis DAG ─────────────────────────
# Each edge is a *causal claim* plus everything needed to decide whether it is
# evaluable. `design` drives identifiability; `estimator_method` is the KG id the
# broker grounds (None = no tool exists → measurement coverage gap).
@dataclass
class HypothesisEdge:
    eid: str
    src: str
    dst: str
    claim: str
    estimand: str
    design: str                       # 'interventional' | 'observational' | 'descriptive'
    estimator_method: str | None      # graph Method id, or None if unmethoded
    strategy: str = ""                # identification strategy
    causal_assumptions: list[str] = field(default_factory=list)
    refutations: list[str] = field(default_factory=list)
    id_evidence: str = ""             # citation grounding the identification strategy
    fix: str = ""                     # if not identifiable: the design change that unlocks it


DAG = [
    HypothesisEdge(
        "H1", "paclitaxel-resistant vs sensitive", "AXL expression",
        "Resistant cells over-express AXL vs sensitive.",
        "group contrast in AXL mRNA (resistant − sensitive)",
        design="descriptive", estimator_method="m:deseq2",
        strategy="two-group differential expression (association, not a causal effect)",
        causal_assumptions=[],
        refutations=["independent cohort replication", "protein-level confirmation (WB/IHC)"],
        id_evidence="descriptive contrast — no interventional claim",
    ),
    HypothesisEdge(
        "H2", "AXL kinase activity", "pAKT (S473)",
        "AXL inhibition lowers pAKT.",
        "ATE of do(AXL inhibited) on pAKT intensity",
        design="interventional", estimator_method="m:limma",
        strategy="experimental intervention (R428 vs vehicle / shAXL vs scramble), randomized across wells",
        causal_assumptions=["exchangeability (by randomized perturbation)",
                            "positivity (both arms realized)",
                            "consistency / SUTVA  ⚠ paracrine GAS6 may break no-interference"],
        refutations=["vehicle + scramble control", "orthogonal inhibitor (TP-0903) replication",
                     "AKT-rescue: myr-AKT abolishes the effect", "dose–response monotonicity"],
        id_evidence="Pearl, Causality (do-operator); Hernán & Robins, What If (exchangeability)",
    ),
    HypothesisEdge(
        "H3", "pAKT (S473)", "paclitaxel resistance",
        "Baseline pAKT predicts resistance (as measured by correlation).",
        "effect of pAKT on resistance",
        design="observational", estimator_method=None,
        strategy="",  # none as stated
        causal_assumptions=["exchangeability — VIOLATED: confounded by proliferation, p53/PTEN status"],
        refutations=[],
        id_evidence="",
        fix="intervene on the mediator: do(pAKT) via MK-2206 (AKT-i) or myr-AKT (constitutive) — "
            "converts the edge to an interventional, identifiable design",
    ),
    HypothesisEdge(
        "H4", "AXL inhibition + paclitaxel", "resensitization",
        "AXL inhibition resensitizes resistant cells to paclitaxel.",
        "interaction: shift in paclitaxel dose–response under AXL inhibition (ΔIC50 / synergy)",
        design="interventional", estimator_method=None,   # no dose-response tool node in KG
        strategy="factorial combination (paclitaxel dose-series ± AXL inhibitor)",
        causal_assumptions=["positivity (full dose grid)", "consistency / SUTVA"],
        refutations=["Bliss/Loewe null model", "single-agent controls", "isobologram"],
        id_evidence="Loewe additivity / Bliss independence (synergy null models)",
    ),
    HypothesisEdge(
        "H5", "AXL-high resistance", "EMT program",
        "AXL-high resistance rides an EMT transcriptional program.",
        "enrichment of an EMT signature in AXL-high / resistant",
        design="descriptive", estimator_method="m:gsea",
        strategy="gene-set enrichment (association)",
        causal_assumptions=[],
        refutations=["independent EMT signature", "permutation null"],
        id_evidence="descriptive enrichment — no interventional claim",
    ),
]


# ───────────────────────────── the methods broker ────────────────────────────
def broker_ground(conn, method_id):
    """Pull the estimator's grounding from the KG, or report a coverage gap."""
    if method_id is None:
        return {"found": False}
    try:
        nb = method_neighborhood(conn, method_id)
    except KeyError:
        return {"found": False}
    return {
        "found": True,
        "name": nb["method"]["name"],
        "operations": [(o["id"], o["name"]) for o in nb["operations"]],
        "statistical_methods": [(s["name"], s["evidence"]) for s in nb["statistical_methods"]],
        "assumptions": [(a["name"], a["via"], a["evidence"]) for a in nb["assumptions"]],
    }


def evaluability(edge: HypothesisEdge) -> tuple[str, str]:
    """The identification verdict: identified | descriptive | NOT identifiable."""
    if edge.design == "descriptive":
        return "DESCRIPTIVE", "evaluable as association (no causal effect claimed)"
    if edge.design == "interventional":
        return "IDENTIFIED", "causal effect recoverable by design"
    return "NOT IDENTIFIABLE", "confounded — no valid adjustment under the proposed design"


# ──────────────────────────────── reporting ─────────────────────────────────
def banner(s):
    print("\n" + "═" * 78 + f"\n{s}\n" + "═" * 78)


def report_edge(conn, e: HypothesisEdge):
    status, why = evaluability(e)
    mark = {"IDENTIFIED": "✅", "DESCRIPTIVE": "◑", "NOT IDENTIFIABLE": "⛔"}[status]
    print(f"\n[{e.eid}] {e.src}  ──▶  {e.dst}")
    print(f"     claim    : {e.claim}")
    print(f"     estimand : {e.estimand}")
    print(f"  ① IDENTIFY  {mark} {status} — {why}")
    if e.strategy:
        print(f"     strategy : {e.strategy}")
    for a in e.causal_assumptions:
        print(f"       · causal assumption: {a}")
    if status == "NOT IDENTIFIABLE":
        print(f"     ⮑ FIX    : {e.fix}")
    if e.id_evidence:
        print(f"     grounded : {e.id_evidence}")

    print("  ② ESTIMATE")
    g = broker_ground(conn, e.estimator_method)
    if not g["found"]:
        gap = e.estimator_method or "(measurement)"
        print(f"     ⚠ COVERAGE GAP: no estimator node for {gap} in the methods graph — "
              f"reporting the gap rather than inventing a tool")
    else:
        ops = ", ".join(n for _, n in g["operations"][:3]) or "—"
        print(f"     estimator : {g['name']}  (EDAM: {ops})")
        for nm, ev in g["statistical_methods"]:
            print(f"       statistical method: {nm}   [{ev}]")
        for nm, via, ev in g["assumptions"]:
            print(f"       ! stat assumption : {nm:42.42} via {', '.join(via)}  [{ev}]")

    print(f"  ③ REFUTE    : {'; '.join(e.refutations) if e.refutations else '(pending identification)'}")


# ───────────────────────────── self-contained graph ─────────────────────────
def _build_demo_graph(db_path: Path) -> None:
    """A compact, faithfully-grounded graph (uses the shipped curated maps)."""
    from methods_graph.crosslinks import load_crosslinks, build_crosslink_edges
    from methods_graph.crosslinks.assumptions import load_assumptions, build_assumption_records

    P = Provenance("demo", "https://example.org", "2026-06-11")
    method_ids = {"m:deseq2", "m:salmon", "m:gsea", "m:limma"}
    ops = {
        "m:deseq2": ("op:operation_3223", "Differential gene expression analysis"),
        "m:salmon": ("op:operation_3800", "RNA-Seq quantification"),
        "m:gsea":   ("op:operation_2436", "Gene-set enrichment analysis"),
        "m:limma":  ("op:operation_3223", "Differential gene expression analysis"),
    }
    nodes: list = [MethodRecord(m, m.split(":")[1], NodeKind.METHOD, {}, P, bioconda_pkg=m.split(":")[1])
                   for m in sorted(method_ids)]
    edges: list = []
    for oid, oname in {v for v in ops.values()}:
        nodes.append(NodeRecord(oid, oname, NodeKind.OPERATION, {}, P))
    for m, (oid, _) in ops.items():
        edges.append(EdgeRecord(m, oid, EdgeKind.PERFORMS, {}, P))

    links = [l for l in load_crosslinks() if l.method_id in method_ids]
    for sid, label in {(l.statistical_method_id, l.label) for l in links}:
        nodes.append(NodeRecord(sid, label, NodeKind.STATISTICAL_METHOD, {}, P))
    edges += build_crosslink_edges(nodes, ingested_at="2026-06-11", links=links)[0]

    stat_ids = {l.statistical_method_id for l in links}
    vocab, alinks = load_assumptions()
    alinks = [l for l in alinks if l.statistical_method_id in stat_ids]
    a_nodes, a_edges, _ = build_assumption_records(nodes, ingested_at="2026-06-11",
                                                   vocab=vocab, links=alinks)
    nodes += a_nodes
    edges += a_edges
    build_graph(nodes, edges, db_path, staging_dir=db_path.parent / "stg")


# ──────────────────────────────────── main ──────────────────────────────────
def main() -> None:
    tmp = tempfile.TemporaryDirectory()
    db_env = os.environ.get("MG_DB")
    if db_env and Path(db_env).exists():
        db_path = Path(db_env)
        print(f"methods broker: real graph at {db_path}")
    elif Path("/tmp/mg-as.kuzu").exists():
        db_path = Path("/tmp/mg-as.kuzu")
        print(f"methods broker: real graph at {db_path}")
    else:
        db_path = Path(tmp.name) / "demo.kuzu"
        _build_demo_graph(db_path)
        print(f"methods broker: self-contained grounded graph at {db_path}")
    conn = kuzu.Connection(kuzu.Database(str(db_path)))

    banner('QUERY  "How does AXL inhibition affect pAKT signalling in paclitaxel-resistant cancers?"')
    print("\nThe target is a MEDIATION estimand:  AXL ─▶ pAKT ─▶ resistance")
    print("  natural indirect effect through pAKT — identified only under sequential")
    print("  ignorability (cross-world); refutation = does myr-AKT rescue abolish the")
    print("  resensitization?  Testable implication of 'pAKT is the sole mediator':")
    print("     AXL ⟂ resistance | pAKT   (a conditional-independence test of the DAG)")

    banner("PER-EDGE:  identify → estimate → refute")
    for e in DAG:
        report_edge(conn, e)

    # ── the evaluable + grounded edges become a guarded Workflow ──────────────
    banner("GUARDRAIL: validate the executable edges against the graph")
    grounded = [e for e in DAG
                if evaluability(e)[0] in ("IDENTIFIED", "DESCRIPTIVE")
                and broker_ground(conn, e.estimator_method)["found"]]

    def first_op(mid):
        nb = method_neighborhood(conn, mid)
        return nb["operations"][0]["id"] if nb["operations"] else None

    steps = []
    for e in grounded:
        ev = first_op(e.estimator_method)
        steps.append(Step(id=e.eid, method_id=e.estimator_method,
                          evidence=[ev] if ev else []))
    # two things the LLM might smuggle in — the validator must reject both:
    steps.append(Step(id="halluc", method_id="m:axl_phospho_quant_pro"))          # not a node
    real = grounded[0].estimator_method
    steps.append(Step(id="forged", method_id=real, evidence=[real]))              # self-edge, no semantic grounding

    wf = Workflow(id="axl-pakt", steps=steps)
    allowed = allowed_methods_from_seed(conn, [e.estimator_method for e in grounded], k_hops=1)
    res = validate_workflow(conn, wf, allowed_method_ids=allowed)
    print(f"\n  grounded executable steps : {[e.eid + ':' + e.estimator_method for e in grounded]}")
    print(f"  workflow valid?           : {res.ok}")
    for i in res.issues:
        print(f"    ⛔ {i.code:24} [{i.step_id}] {i.detail}")

    banner("VERDICT")
    n_id = sum(1 for e in DAG if evaluability(e)[0] == "IDENTIFIED")
    n_gap = sum(1 for e in DAG if not broker_ground(conn, e.estimator_method)["found"])
    n_bad = sum(1 for e in DAG if evaluability(e)[0] == "NOT IDENTIFIABLE")
    print(f"  {len(DAG)} edges:  {n_id} causally identified · "
          f"{n_bad} NON-identifiable (design fix prescribed) · "
          f"{n_gap} estimator coverage gaps")
    print("  Every estimator + statistical assumption is cited from the graph; every")
    print("  causal claim is tagged identifiable-or-not; nothing is invented.")
    conn.close()
    tmp.cleanup()


if __name__ == "__main__":
    main()
