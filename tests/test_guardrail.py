"""Tests for the guardrail engine: preconditions dict + dataset facts -> verdict.

The pure core (`evaluate_preconditions`) needs no DB — it maps the stable
`method_preconditions` contract + supplied facts to a methodological verdict.
"""
from __future__ import annotations

from methods_graph import guardrail
from methods_graph.guardrail import evaluate_preconditions


def _pre(method_id="m:x", assumptions=None):
    return {"method_id": method_id, "assumptions": assumptions or [], "diagnostics": []}


# --- top-level status ---

def test_no_assumptions_is_not_evaluable():
    v = evaluate_preconditions(_pre(assumptions=[]))
    assert v["status"] == "NOT_EVALUABLE"
    assert "no evaluability" in v["refusal_reason"]
    assert v["gates"] == [] and v["post_run_checks"] == []


def test_pre_run_numeric_gate_pass_is_evaluable():
    pre = _pre(assumptions=[{"name": "asymptotic normality", "checkable": "pre_run",
        "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"],
        "evidence": "doi:x"}])
    v = evaluate_preconditions(pre, {"replicates_per_group": 3})
    assert v["status"] == "EVALUABLE"
    g = v["gates"][0]
    assert g["result"] == "PASS"
    assert g["threshold_key"] == "replicates_per_group"
    assert g["threshold"] == 3 and g["supplied"] == 3
    assert "replicates_per_group" in v["required_facts"]


def test_pre_run_numeric_gate_fail_blocks():
    pre = _pre(assumptions=[{"name": "asymptotic normality", "checkable": "pre_run",
        "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"]}])
    v = evaluate_preconditions(pre, {"replicates_per_group": 2})
    assert v["status"] == "BLOCKED"
    assert v["gates"][0]["result"] == "FAIL"
    assert v["gates"][0]["supplied"] == 2


def test_missing_fact_neither_blocks_nor_certifies():
    """A fact that was never measured is neither a violation nor a pass. It must not BLOCK
    (no failure was observed) and must not report EVALUABLE (no success was observed
    either) — otherwise not measuring becomes the cheapest route to approval.
    """
    pre = _pre(assumptions=[{"name": "asymptotic normality", "checkable": "pre_run",
        "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"]}])
    v = evaluate_preconditions(pre, {})
    assert v["status"] == guardrail.FACTS_REQUIRED
    assert v["status"] != guardrail.BLOCKED
    assert v["gates"][0]["result"] == "INSUFFICIENT_INFO"
    assert v["gates"][0]["supplied"] is None
    assert v["required_facts"] == ["replicates_per_group"]


def test_post_run_routed_to_checks_not_gates():
    pre = _pre(assumptions=[{"name": "correct model specification", "checkable": "post_run",
        "threshold": None, "diagnostics": ["diag:pvalue_histogram"]}])
    v = evaluate_preconditions(pre, {})
    assert v["status"] == "EVALUABLE"
    assert v["gates"] == []
    assert v["post_run_checks"][0]["assumption"] == "correct model specification"
    assert v["post_run_checks"][0]["diagnostics"] == ["diag:pvalue_histogram"]


def test_pre_run_qualitative_is_requires_review():
    pre = _pre(assumptions=[{"name": "independence", "checkable": "pre_run",
        "threshold": None, "diagnostics": ["diag:design_batch_review"]}])
    v = evaluate_preconditions(pre, {})
    assert v["status"] == "EVALUABLE"
    assert v["gates"][0]["result"] == "REQUIRES_REVIEW"


def test_assumption_without_diagnostic_is_requires_review_empty():
    pre = _pre(assumptions=[{"name": "some bare assumption", "checkable": "",
        "threshold": None, "diagnostics": []}])
    v = evaluate_preconditions(pre, {})
    assert v["gates"][0]["result"] == "REQUIRES_REVIEW"
    assert v["gates"][0]["diagnostics"] == []


def test_peptides_per_protein_threshold_key():
    pre = _pre(assumptions=[{"name": "peptide support", "checkable": "pre_run",
        "threshold": {"min_peptides_per_protein": 2}, "diagnostics": ["diag:ppc"]}])
    v = evaluate_preconditions(pre, {"peptides_per_protein": 1})
    assert v["status"] == "BLOCKED"
    assert v["gates"][0]["threshold_key"] == "peptides_per_protein"


def test_mixed_pass_and_fail_blocks_on_the_fail():
    pre = _pre(assumptions=[
        {"name": "a", "checkable": "pre_run", "threshold": {"min_replicates_per_group": 3},
         "diagnostics": ["d1"]},
        {"name": "b", "checkable": "pre_run", "threshold": {"min_peptides_per_protein": 2},
         "diagnostics": ["d2"]},
    ])
    v = evaluate_preconditions(pre, {"replicates_per_group": 5, "peptides_per_protein": 1})
    assert v["status"] == "BLOCKED"
    results = {g["assumption"]: g["result"] for g in v["gates"]}
    assert results["a"] == "PASS" and results["b"] == "FAIL"


# --- evaluate() resolution + refusal, with a fake provider ---

class _FakeProvider:
    def __init__(self, pre_by_id, ids_by_kw=None, io_by_id=None):
        self._pre = pre_by_id
        self._ids = ids_by_kw or {}
        self._io = io_by_id or {}   # mid -> {"inputs": [(id, name)], "outputs": [(id, name)]}

    def method_preconditions(self, mid):
        if mid not in self._pre:
            raise KeyError(mid)
        return self._pre[mid]

    def resolve_method_ids(self, kws):
        return self._ids.get(tuple(kws), [])

    def neighborhood(self, mid):
        io = self._io.get(mid, {})
        to_nodes = lambda pairs: [{"id": i, "name": n, "kind": "Data"} for i, n in pairs]
        return {"inputs": to_nodes(io.get("inputs", [])),
                "outputs": to_nodes(io.get("outputs", []))}


def test_evaluate_unknown_method_is_not_evaluable():
    v = guardrail.evaluate(_FakeProvider({}), method="m:bogus")
    assert v["status"] == "NOT_EVALUABLE"
    assert v["refusal_reason"] == "unknown method"
    assert v["method_id"] == "m:bogus"


def test_evaluate_resolves_analysis_keywords():
    pre = _pre("m:deseq2", [{"name": "n", "checkable": "pre_run",
        "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["d"]}])
    p = _FakeProvider({"m:deseq2": pre}, {("deseq2",): ["m:deseq2"]})
    v = guardrail.evaluate(p, analysis=["deseq2"], facts={"replicates_per_group": 3})
    assert v["status"] == "EVALUABLE" and v["method_id"] == "m:deseq2"


def test_evaluate_no_keyword_match_is_not_evaluable():
    v = guardrail.evaluate(_FakeProvider({}, {}), analysis=["nope"])
    assert v["status"] == "NOT_EVALUABLE"
    assert "no method matched" in v["refusal_reason"]


def test_same_gate_from_two_sources_is_deduped():
    # method_preconditions keys assumptions by (id, source): the SAME assumption reached
    # both tool-internally ("used") and downstream ("amenable") yields two records. The
    # guardrail verdict should present ONE gate, not a duplicate.
    pre = _pre(assumptions=[
        {"name": "asymptotic normality", "source": "used", "checkable": "pre_run",
         "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"]},
        {"name": "asymptotic normality", "source": "amenable", "checkable": "pre_run",
         "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"]},
    ])
    v = evaluate_preconditions(pre, {"replicates_per_group": 3})
    assert len(v["gates"]) == 1
    assert v["required_facts"] == ["replicates_per_group"]


def test_duplicate_post_run_checks_are_deduped():
    pre = _pre(assumptions=[
        {"name": "PRDS", "source": "used", "checkable": "post_run", "threshold": None,
         "diagnostics": ["diag:pvalue_histogram"]},
        {"name": "PRDS", "source": "amenable", "checkable": "post_run", "threshold": None,
         "diagnostics": ["diag:pvalue_histogram"]},
    ])
    v = evaluate_preconditions(pre, {})
    assert len(v["post_run_checks"]) == 1


# --- pipeline-chain evaluation ---

from methods_graph.guardrail import classify_handoff


def test_classify_handoff_valid_returns_sorted_shared():
    result, shared = classify_handoff({"data:b", "data:a"}, {"data:b", "data:c"})
    assert result == "VALID"
    assert shared == ["data:b"]


def test_classify_handoff_broken_when_disjoint():
    result, shared = classify_handoff({"data:a"}, {"data:b"})
    assert result == "BROKEN" and shared == []


def test_classify_handoff_unknown_when_either_side_empty():
    assert classify_handoff(set(), {"data:b"})[0] == "UNKNOWN"
    assert classify_handoff({"data:a"}, set())[0] == "UNKNOWN"


def _chain_provider():
    """a -[D1]-> b -[D2]-> c ; each step evaluable, gated on replicates>=3."""
    def pre(mid):
        return {"method_id": mid, "assumptions": [
            {"name": "asymptotic normality", "checkable": "pre_run",
             "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["diag:ssc"]}]}
    return _FakeProvider(
        pre_by_id={"m:a": pre("m:a"), "m:b": pre("m:b"), "m:c": pre("m:c")},
        io_by_id={
            "m:a": {"outputs": [("data:1", "D1")]},
            "m:b": {"inputs": [("data:1", "D1")], "outputs": [("data:2", "D2")]},
            "m:c": {"inputs": [("data:2", "D2")]},
        })


def test_chain_all_valid_and_powered_is_evaluable():
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:b", "m:c"],
                                 {"replicates_per_group": 3})
    assert v["status"] == "EVALUABLE"
    assert [h["result"] for h in v["handoffs"]] == ["VALID", "VALID"]
    assert [s["method_id"] for s in v["steps"]] == ["m:a", "m:b", "m:c"]


def test_chain_broken_handoff_blocks():
    # a outputs D1, c inputs D2 -> disjoint -> BROKEN -> chain BLOCKED
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:c"],
                                 {"replicates_per_group": 3})
    assert v["handoffs"][0]["result"] == "BROKEN"
    assert v["status"] == "BLOCKED"


def test_chain_underpowered_step_blocks():
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:b", "m:c"],
                                 {"replicates_per_group": 2})
    assert v["status"] == "BLOCKED"


def test_chain_unknown_step_is_not_evaluable():
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:bogus"],
                                 {"replicates_per_group": 3})
    assert v["status"] == "NOT_EVALUABLE"


def test_chain_unknown_handoff_when_no_data_io_does_not_block():
    p = _FakeProvider(
        pre_by_id={
            "m:a": {"method_id": "m:a", "assumptions": [
                {"name": "x", "checkable": "post_run", "threshold": None, "diagnostics": ["d"]}]},
            "m:b": {"method_id": "m:b", "assumptions": [
                {"name": "y", "checkable": "post_run", "threshold": None, "diagnostics": ["d"]}]}},
        io_by_id={})  # no curated Data I/O
    v = guardrail.evaluate_chain(p, ["m:a", "m:b"])
    assert v["handoffs"][0]["result"] == "UNKNOWN"
    assert v["status"] == "EVALUABLE"


def test_chain_resolves_keyword_steps():
    p = _chain_provider()
    p._ids = {("salmon",): ["m:a"]}
    v = guardrail.evaluate_chain(p, ["salmon", "m:b", "m:c"], {"replicates_per_group": 3})
    assert v["steps"][0]["method_id"] == "m:a"
    assert v["status"] == "EVALUABLE"


# --- skill aggregation ---

def test_evaluate_skill_aggregates_wrapped_method_preconditions():
    class P(_FakeProvider):
        def __init__(self):
            super().__init__(
                pre_by_id={"m:deseq2": {"method_id": "m:deseq2", "assumptions": [
                    {"name": "asymptotic normality", "checkable": "pre_run",
                     "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["d"]}]}})
            self._wraps = {"skill:bioclaw/differential-expression": ["m:deseq2"]}
        def skill_wraps_method_ids(self, sid):
            return self._wraps.get(sid, [])
    v = guardrail.evaluate(P(), skill="skill:bioclaw/differential-expression",
                           facts={"replicates_per_group": 2})
    assert v["status"] == "BLOCKED"
    assert v["method_id"] == "skill:bioclaw/differential-expression"


def test_evaluate_skill_with_no_wraps_is_not_evaluable():
    class P(_FakeProvider):
        def skill_wraps_method_ids(self, sid): return []
    v = guardrail.evaluate(P({}), skill="skill:bioclaw/query-uniprot")
    assert v["status"] == "NOT_EVALUABLE"
    assert "no evaluable" in v["refusal_reason"]


def test_merge_skill_preconditions_max_merges_threshold():
    """Stricter threshold (5) wins over lenient (3) when same assumption appears twice."""
    pre_a = {"method_id": "m:a", "assumptions": [
        {"id": "assum-1", "name": "adequate replicates", "source": "used",
         "checkable": "pre_run", "threshold": {"min_replicates_per_group": 3},
         "diagnostics": ["d1"], "evidence": "ref-a", "via": []}
    ], "diagnostics": []}
    pre_b = {"method_id": "m:b", "assumptions": [
        {"id": "assum-1", "name": "adequate replicates", "source": "used",
         "checkable": "pre_run", "threshold": {"min_replicates_per_group": 5},
         "diagnostics": ["d2"], "evidence": "ref-b", "via": []}
    ], "diagnostics": []}
    merged = guardrail.merge_skill_preconditions([pre_a, pre_b], "skill:test/s")
    assert merged["method_id"] == "skill:test/s"
    assert len(merged["assumptions"]) == 1
    a = merged["assumptions"][0]
    assert a["threshold"]["min_replicates_per_group"] == 5
    assert set(a["diagnostics"]) == {"d1", "d2"}


def test_evaluate_skill_strict_threshold_not_dropped():
    """BLOCKED verdict at facts=4 when one method needs 3, another needs 5 (max wins)."""
    class P:
        def skill_wraps_method_ids(self, sid):
            return ["m:a", "m:b"]
        def method_preconditions(self, mid):
            thresh = {"min_replicates_per_group": 3 if mid == "m:a" else 5}
            return {"method_id": mid, "assumptions": [
                {"id": "assum-1", "name": "adequate replicates", "source": "used",
                 "checkable": "pre_run", "threshold": thresh,
                 "diagnostics": [], "evidence": "", "via": []}
            ], "diagnostics": []}
    v = guardrail.evaluate(P(), skill="skill:test/strict", facts={"replicates_per_group": 4})
    assert v["status"] == guardrail.BLOCKED
    # The surviving gate must show threshold=5, not 3
    thresh_gates = [g for g in v["gates"] if g["threshold_key"] == "replicates_per_group"]
    assert thresh_gates, "expected a threshold gate"
    assert thresh_gates[0]["threshold"] == 5, f"got {thresh_gates[0]['threshold']}, expected 5"


def test_evaluate_skill_all_wrapped_methods_unknown_is_not_evaluable():
    """A skill WRAPS methods but EVERY one raises KeyError (no preconditions): the
    per-method KeyError is swallowed, leaving no assumptions -> honest coverage gap,
    not a crash and not a spurious EVALUABLE."""
    class P:
        def skill_wraps_method_ids(self, sid):
            return ["m:gone1", "m:gone2"]
        def method_preconditions(self, mid):
            raise KeyError(mid)
    v = guardrail.evaluate(P(), skill="skill:test/all-missing",
                           facts={"replicates_per_group": 2})
    assert v["status"] == guardrail.NOT_EVALUABLE
    assert v["method_id"] == "skill:test/all-missing"
    assert v["gates"] == [] and v["required_facts"] == []


# --- boolean preconditions (presence facts, not numeric minimums) ---
#
# The dominant documented failure modes in real enrichment analyses are not "too few
# of something" but "was this done at all": an appropriate background gene set
# (1,364/1,628 labelled rows in Wijesooriya et al.) and multiple-testing correction
# (~760 rows). Neither is expressible as min_<dim> >= n.

def test_boolean_precondition_fail_blocks():
    pre = _pre(assumptions=[{
        "name": "background set is the assayed gene universe", "source": "used",
        "checkable": "pre_run", "requires": {"background_is_assayed_universe": True},
        "diagnostics": ["diag:background_set_review"], "evidence": "doi:10.1093/nar/gkac017",
    }])
    v = evaluate_preconditions(pre, {"background_is_assayed_universe": False})
    assert v["status"] == "BLOCKED"
    g = v["gates"][0]
    assert g["result"] == "FAIL"
    assert g["threshold_key"] == "background_is_assayed_universe"
    assert g["threshold"] is True and g["supplied"] is False


# --- fail-closed: an unchecked hard gate must not read as approval ---
#
# In an agent session the agent chooses which facts to pass. Returning EVALUABLE when a
# required pre-run fact was never supplied asks a system optimised for task completion to
# volunteer the evidence against itself. A gate that exists but was not evaluated is a
# distinct state from one that passed.

def test_unsupplied_required_fact_does_not_certify():
    pre = _pre(assumptions=[{"name": "asymptotic normality", "source": "used",
        "checkable": "pre_run", "threshold": {"min_replicates_per_group": 3},
        "diagnostics": ["diag:sample_size_power_check"]}])
    v = evaluate_preconditions(pre, {})          # agent supplied nothing
    assert v["status"] == guardrail.FACTS_REQUIRED
    assert v["gates"][0]["result"] == "INSUFFICIENT_INFO"
    assert "replicates_per_group" in v["required_facts"]


def test_a_failed_gate_outranks_a_missing_fact():
    """A known violation is more actionable than an unknown one."""
    pre = _pre(assumptions=[
        {"name": "asymptotic normality", "source": "used", "checkable": "pre_run",
         "threshold": {"min_replicates_per_group": 3}, "diagnostics": ["d1"]},
        {"name": "background is assayed universe", "source": "used", "checkable": "pre_run",
         "requires": {"background_is_assayed_universe": True}, "diagnostics": ["d2"]},
    ])
    v = evaluate_preconditions(pre, {"replicates_per_group": 1})   # one FAIL, one unsupplied
    assert v["status"] == guardrail.BLOCKED


# --- chain hardening ---

def test_chain_with_an_unmeasured_gate_does_not_certify():
    """A pipeline is only as certified as its least-measured step. With no facts supplied,
    every step has an unevaluated hard gate, so the chain must not report EVALUABLE."""
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:b", "m:c"])
    assert v["status"] == guardrail.FACTS_REQUIRED


def test_chain_definite_violation_outranks_a_coverage_gap():
    """One step definitely fails and another is uncovered. Reporting 'coverage gap' hides a
    known violation behind an unknown one — the failure is the actionable fact."""
    v = guardrail.evaluate_chain(_chain_provider(), ["m:a", "m:bogus"],
                                 {"replicates_per_group": 1})
    statuses = {s["status"] for s in v["steps"]}
    assert guardrail.BLOCKED in statuses and guardrail.NOT_EVALUABLE in statuses
    assert v["status"] == guardrail.BLOCKED
