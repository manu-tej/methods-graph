"""Guardrail engine: turn the evaluability substrate into an LLM-facing verdict.

The graph already exposes, per method, the stable ``method_preconditions`` contract
(assumptions + diagnostics + machine-readable thresholds, across the curated domains).
This module composes that contract — plus any dataset facts the caller supplies — into a
single VERDICT an LLM keys off to do bioinformatics analysis rigorously:

  * ``EVALUABLE``     — the graph can certify this analysis step; here are the checks.
  * ``BLOCKED``       — a pre-run gate FAILED (e.g. too few replicates) — refuse as-is.
  * ``NOT_EVALUABLE`` — honest coverage gap (unknown method, or no evaluability edges).
  * ``FACTS_REQUIRED`` — a hard pre-run gate exists but its fact was never supplied;
    uncertified, and deliberately NOT reported as EVALUABLE.

The core (:func:`evaluate_preconditions`) is PURE — it takes the preconditions dict and a
facts dict and needs no database, so the methodological logic is unit-testable in isolation.
:func:`evaluate` wires it to a provider (resolve the method, fetch its preconditions).
"""
from __future__ import annotations

from typing import Any

# Top-level verdict statuses.
EVALUABLE = "EVALUABLE"
BLOCKED = "BLOCKED"
NOT_EVALUABLE = "NOT_EVALUABLE"
# A hard pre-run gate exists but the caller never supplied the fact it needs. Distinct from
# EVALUABLE (checked and passed) and from NOT_EVALUABLE (no coverage at all): the analysis
# is uncertified, and treating it as approval is how an agent optimised for task completion
# routes around its own guardrail by simply not measuring.
FACTS_REQUIRED = "FACTS_REQUIRED"

# Per-gate results.
PASS = "PASS"                          # supplied fact meets the threshold
FAIL = "FAIL"                          # supplied fact is below the threshold (blocks)
INSUFFICIENT_INFO = "INSUFFICIENT_INFO"  # numeric gate, fact not supplied (never blocks)
REQUIRES_REVIEW = "REQUIRES_REVIEW"    # qualitative pre-run check the caller must attest

# Numeric threshold keys the graph carries, and the caller-facing fact key for each
# (the threshold key minus its ``min_`` prefix).
_MIN_PREFIX = "min_"


def _fact_key(threshold_key: str) -> str:
    """Caller-facing fact name for a precondition threshold key (drop ``min_``)."""
    return threshold_key[len(_MIN_PREFIX):] if threshold_key.startswith(_MIN_PREFIX) else threshold_key


def _refusal(method_id: Any, reason: str) -> dict[str, Any]:
    return {
        "status": NOT_EVALUABLE,
        "method_id": method_id,
        "refusal_reason": reason,
        "required_facts": [],
        "gates": [],
        "post_run_checks": [],
    }


def evaluate_preconditions(
    preconditions: dict[str, Any], facts: dict[str, int] | None = None
) -> dict[str, Any]:
    """Map a ``method_preconditions`` dict + dataset facts to a verdict (pure).

    ``facts`` maps a fact key (e.g. ``"replicates_per_group"``) to an integer the caller
    measured for its dataset. A method with no assumptions is an honest coverage gap.
    """
    facts = facts or {}
    method_id = preconditions.get("method_id")
    assumptions = preconditions.get("assumptions") or []
    if not assumptions:
        return _refusal(method_id, "no evaluability coverage for this method")

    gates: list[dict[str, Any]] = []
    post_run_checks: list[dict[str, Any]] = []
    required_facts: list[str] = []
    any_fail = False
    any_missing = False

    for a in assumptions:
        name = a.get("name", "")
        diagnostics = a.get("diagnostics") or []
        evidence = a.get("evidence", "")
        checkable = a.get("checkable") or ""
        threshold = a.get("threshold")  # {min_<dim>: int} or None
        # {fact_key: True} or None. A presence predicate, for preconditions that are not
        # "enough of something" but "was this done at all" — an appropriate background
        # gene set, multiple-testing correction, a statistical test having been run. These
        # are the dominant documented failure modes in real analyses and no numeric
        # minimum can express any of them.
        requires = a.get("requires")

        if checkable == "post_run":
            post_run_checks.append({"assumption": name, "diagnostics": diagnostics})
            continue

        # AMENABLE_TO records statistics runnable DOWNSTREAM of this tool's output, not
        # statistics the tool itself performs — so an amenable-only inheritance must not
        # gate the tool (that is how a read aligner acquired a replicate floor). When the
        # tool genuinely runs the test, a separate source="used" record carries the gate.
        gateable = (a.get("source") or "") != "amenable"

        if checkable == "pre_run" and threshold and gateable:
            # One numeric gate per threshold dimension (sorted for determinism).
            for tkey in sorted(threshold):
                tval = threshold[tkey]
                fkey = _fact_key(tkey)
                if fkey not in required_facts:
                    required_facts.append(fkey)
                supplied = facts.get(fkey)
                if supplied is None:
                    result = INSUFFICIENT_INFO
                    any_missing = True
                elif supplied >= tval:
                    result = PASS
                else:
                    result = FAIL
                    any_fail = True
                gates.append({
                    "assumption": name, "diagnostics": diagnostics, "phase": "pre_run",
                    "threshold_key": fkey, "threshold": tval, "supplied": supplied,
                    "result": result, "evidence": evidence,
                })
        elif checkable == "pre_run" and requires and gateable:
            # Presence gate: the fact must equal the required value. Keys are already
            # caller-facing (no ``min_`` prefix to strip).
            for rkey in sorted(requires):
                expected = requires[rkey]
                if rkey not in required_facts:
                    required_facts.append(rkey)
                supplied = facts.get(rkey)
                if supplied is None:
                    result = INSUFFICIENT_INFO
                    any_missing = True
                elif bool(supplied) == bool(expected):
                    result = PASS
                else:
                    result = FAIL
                    any_fail = True
                gates.append({
                    "assumption": name, "diagnostics": diagnostics, "phase": "pre_run",
                    "threshold_key": rkey, "threshold": expected, "supplied": supplied,
                    "result": result, "evidence": evidence,
                })
        else:
            # Qualitative pre-run check, or an assumption with no diagnostic at all:
            # surfaced honestly as a manual review the caller must perform/attest.
            gates.append({
                "assumption": name, "diagnostics": diagnostics, "phase": "pre_run",
                "threshold_key": None, "threshold": None, "supplied": None,
                "result": REQUIRES_REVIEW, "evidence": evidence,
            })

    # The substrate keys assumptions by (id, source), so the SAME methodological gate can
    # arrive twice (tool-internal + downstream). Present each gate / post-run check once,
    # preserving order.
    # An assumption already carrying a numeric gate needs no parallel "review this manually"
    # entry — that is what the non-gating amenable twin would otherwise contribute.
    keyed = {(g["assumption"], g["phase"]) for g in gates if g["threshold_key"]}
    gates = [
        g for g in gates
        if g["threshold_key"] or (g["assumption"], g["phase"]) not in keyed
    ]
    gates = _dedupe(gates, lambda g: (g["assumption"], g["threshold_key"], g["phase"]))
    post_run_checks = _dedupe(
        post_run_checks, lambda c: (c["assumption"], tuple(c["diagnostics"]))
    )

    return {
        "status": (BLOCKED if any_fail else
                   FACTS_REQUIRED if any_missing else EVALUABLE),
        "method_id": method_id,
        "refusal_reason": None,
        "required_facts": required_facts,
        "gates": gates,
        "post_run_checks": post_run_checks,
    }


def merge_skill_preconditions(pres: list[dict], skill_id: str) -> dict:
    """Max-merge assumption lists from multiple method_preconditions dicts into one.

    Keyed by (assumption id, source).  When the same key appears in two dicts:
    - threshold: per threshold-key, take max(prior, new).
    - checkable: pre_run beats post_run beats blank.
    - diagnostics: union, preserving order.
    - name, evidence, via: keep first (from first pre that carries this key).
    Returns {method_id: skill_id, assumptions: [...], diagnostics: [...]}.
    """
    import copy
    merged_a: dict[tuple, dict] = {}
    merged_d: dict[str, dict] = {}
    for pre in pres:
        for a in pre.get("assumptions") or []:
            key = (a.get("id", a.get("name", "")), a.get("source", ""))
            rec = merged_a.get(key)
            if rec is None:
                rec = copy.deepcopy(a)
                merged_a[key] = rec
            else:
                # max-merge threshold per key
                new_thr = a.get("threshold") or {}
                old_thr = rec.get("threshold") or {}
                if new_thr:
                    merged_thr = dict(old_thr)
                    for tkey, tval in new_thr.items():
                        merged_thr[tkey] = max(merged_thr.get(tkey, tval), tval)
                    rec["threshold"] = merged_thr
                # checkable: pre_run > post_run > ""
                new_c = a.get("checkable", "")
                old_c = rec.get("checkable", "")
                if new_c == "pre_run" or (new_c == "post_run" and old_c != "pre_run"):
                    rec["checkable"] = new_c
                # diagnostics: union preserving order
                for did in (a.get("diagnostics") or []):
                    if did not in rec["diagnostics"]:
                        rec["diagnostics"].append(did)
        for d in pre.get("diagnostics") or []:
            did = d.get("id", d.get("name", ""))
            if did not in merged_d:
                merged_d[did] = d
    return {
        "method_id": skill_id,
        "assumptions": list(merged_a.values()),
        "diagnostics": list(merged_d.values()),
    }


def _dedupe(items: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    """Order-preserving de-duplication of dicts by a derived key."""
    seen: set = set()
    out: list[dict[str, Any]] = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


# --- pipeline-chain evaluation -------------------------------------------------

# Handoff between consecutive steps (does step N's output feed step N+1's input?).
HANDOFF_VALID = "VALID"        # a curated Data type is shared
HANDOFF_BROKEN = "BROKEN"      # both have curated Data I/O but it is disjoint
HANDOFF_UNKNOWN = "UNKNOWN"    # a step lacks curated Data I/O — un-verifiable (never blocks)


def classify_handoff(
    producer_out_data: set[str], consumer_in_data: set[str]
) -> tuple[str, list[str]]:
    """Classify a data handoff from one step's Data outputs to the next's Data inputs (pure).

    Returns ``(result, shared)`` where ``shared`` is the sorted list of shared Data ids.
    Matching is on curated semantic Data ids only (Format-level joins are excluded by the
    caller as they produce false handoffs).
    """
    if not producer_out_data or not consumer_in_data:
        return HANDOFF_UNKNOWN, []
    shared = sorted(producer_out_data & consumer_in_data)
    return (HANDOFF_VALID, shared) if shared else (HANDOFF_BROKEN, [])


def _data_ids(neighborhood: dict[str, Any], key: str) -> set[str]:
    """The set of curated Data-node ids on a neighborhood's ``inputs`` or ``outputs``."""
    return {n["id"] for n in (neighborhood.get(key) or []) if n.get("kind") == "Data"}


def _resolve_step(provider: Any, step: str, facts: dict[str, int] | None) -> dict[str, Any]:
    """A single pipeline step: a method id (``m:...``) or analysis-intent keywords."""
    if step.startswith("m:"):
        return evaluate(provider, method=step, facts=facts)
    return evaluate(provider, analysis=step.split(), facts=facts)


def evaluate_chain(
    provider: Any, steps: list[str], facts: dict[str, int] | None = None
) -> dict[str, Any]:
    """Evaluate a whole proposed analysis pipeline: per-step verdicts + data handoffs.

    ``steps`` is the ordered list of pipeline steps (each a ``m:<id>`` or intent keywords).
    ``facts`` are DATASET-level (e.g. ``replicates_per_group``) and apply to every step.
    Chain status, in precedence order: ``BLOCKED`` if any step is BLOCKED or any handoff is
    BROKEN; else ``NOT_EVALUABLE`` if any step is a coverage gap; else ``FACTS_REQUIRED`` if
    any step has an unmeasured hard gate; else ``EVALUABLE``.
    """
    step_results: list[dict[str, Any]] = []
    io: list[tuple[str | None, set[str], set[str]]] = []  # (method_id, out_data, in_data)

    for step in steps:
        verdict = _resolve_step(provider, step, facts)
        method_id = verdict.get("method_id")
        out_data: set[str] = set()
        in_data: set[str] = set()
        if method_id and verdict["status"] != NOT_EVALUABLE:
            nb = provider.neighborhood(method_id)
            out_data = _data_ids(nb, "outputs")
            in_data = _data_ids(nb, "inputs")
        step_results.append({"step": step, **verdict})
        io.append((method_id, out_data, in_data))

    handoffs: list[dict[str, Any]] = []
    for (from_id, out_data, _), (to_id, _, in_data) in zip(io, io[1:]):
        result, shared = classify_handoff(out_data, in_data)
        handoffs.append({"from": from_id, "to": to_id, "result": result, "shared": shared})

    # Precedence, most-actionable first. A definite violation outranks a coverage gap:
    # reporting "gap" while a step provably fails hides the known behind the unknown. A gap
    # outranks FACTS_REQUIRED, because an uncovered step can never be certified and saying
    # "supply facts" would imply otherwise.
    if (any(s["status"] == BLOCKED for s in step_results)
            or any(h["result"] == HANDOFF_BROKEN for h in handoffs)):
        status = BLOCKED
    elif any(s["status"] == NOT_EVALUABLE for s in step_results):
        status = NOT_EVALUABLE
    elif any(s["status"] == FACTS_REQUIRED for s in step_results):
        status = FACTS_REQUIRED
    else:
        status = EVALUABLE

    return {"status": status, "steps": step_results, "handoffs": handoffs}


def evaluate(
    provider: Any,
    *,
    skill: str | None = None,
    method: str | None = None,
    analysis: list[str] | None = None,
    facts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Resolve an analysis step to a method and return its guardrail verdict.

    ``provider`` must expose ``resolve_method_ids(keywords)``,
    ``method_preconditions(method_id)``, ``skill_wraps_method_ids(skill_id)``,
    and ``skill_preconditions(skill_id)`` (the :class:`KuzuMethodsGraphProvider` does).
    Pass ONE of ``skill`` (a Skill id whose WRAPS methods are aggregated), ``method``
    (a precise ``m:<id>``), or ``analysis`` (intent keywords resolved best-match-first).
    An unknown method or an unmatched intent is an honest coverage gap.
    """
    if skill is not None:
        method_ids = provider.skill_wraps_method_ids(skill)
        if not method_ids:
            return _refusal(skill, "skill wraps no evaluable method")
        pres = []
        for mid in method_ids:
            try:
                pres.append(provider.method_preconditions(mid))
            except KeyError:
                continue
        return evaluate_preconditions(merge_skill_preconditions(pres, skill), facts)

    method_id = method
    if method_id is None:
        if not analysis:
            raise ValueError("evaluate() needs either skill=, method= or analysis=")
        ids = provider.resolve_method_ids(analysis)
        if not ids:
            return _refusal(None, f"no method matched: {' '.join(analysis)}")
        method_id = ids[0]

    try:
        preconditions = provider.method_preconditions(method_id)
    except KeyError:
        return _refusal(method_id, "unknown method")

    return evaluate_preconditions(preconditions, facts)
