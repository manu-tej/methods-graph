"""PreToolUse hook: the guardrail as enforcement rather than as advice.

Wire it into ``.claude/settings.json``::

    {"hooks": {"PreToolUse": [{"matcher": "Bash",
      "hooks": [{"type": "command", "command": "python -m methods_graph.hook"}]}]}}

Why a hook and not a tool the agent calls. As a tool, the guardrail's effectiveness is
``P(model calls it) × P(model passes correct facts) × P(model honors the verdict)`` — three
model-dependent terms multiplied, with no floor as models get weaker or contexts get longer.
As a hook, the first two terms disappear: the harness decides when it runs, and the hook
reads the samplesheet itself instead of trusting a summary. What remains is a function of
the data and the curated rules, which is the same for every model.

Deliberately conservative. It stays silent unless it can identify a curated method in the
command, so it can never block unrelated work; and when a gate applies but the fact cannot
be read from disk, it escalates to the human rather than allowing — because allowing would
make "keep the samplesheet somewhere I can't see" the cheapest way past the gate.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from methods_graph import guardrail, rules

# Command patterns that indicate a curated method is about to run. Matched against the whole
# command string, case-insensitively. Keep these tight: a false positive blocks real work.
#
# A method belongs in this table ONLY when it has a ``source=used`` precondition that can
# actually fire — i.e. curated USES links reaching a diagnostic with a numeric threshold.
# Anything else is a pattern that can never deny, which advertises enforcement the curation
# cannot deliver and, when the samplesheet is unreadable, escalates to an "ask" the user
# has no way to satisfy. edgeR and limma were removed for exactly that reason: m:edger has
# no replicate floor at all, and m:limma's floors exist only via ``source=amenable``, which
# no longer gates. Re-adding them requires curating the USES links first — not editing here.
_BOUNDARY = r"(?<![a-z0-9])%s(?![a-z0-9])"
_METHOD_PATTERNS: tuple[tuple[str, str], ...] = (
    (_BOUNDARY % r"deseq2?", "m:deseq2"),
)

# Samplesheet filenames and the columns that name the experimental arm, in priority order.
_SAMPLESHEET_NAMES = ("samplesheet.csv", "samples.csv", "coldata.csv", "metadata.csv",
                      "design.csv")
_CONDITION_COLUMNS = ("condition", "group", "treatment", "sample_group", "genotype")
# Directory names whose samplesheets describe a test, never the run being gated.
_TEST_DIRS = frozenset({"test", "tests", "fixtures"})


def detect_method(command: str) -> str | None:
    """The curated method id this command would run, or ``None`` if we cannot tell."""
    lowered = command.lower()
    for pattern, method_id in _METHOD_PATTERNS:
        if re.search(pattern, lowered):
            return method_id
    return None


def replicates_per_group(workspace: Path) -> int | None:
    """Smallest number of samples in any experimental arm, read from a samplesheet.

    Returns ``None`` when no samplesheet with a recognisable condition column is found —
    an absent fact, never a guessed one. The *smallest* arm is what governs: one arm with a
    single sample makes the contrast underpowered regardless of the others.
    """
    for name in _SAMPLESHEET_NAMES:
        for path in _candidate_samplesheets(workspace, name):
            counts = _count_by_condition(path)
            if counts:
                return min(counts.values())
    return None


def _candidate_samplesheets(workspace: Path, name: str) -> list[Path]:
    """Samplesheets at the workspace root or one directory below it (e.g. ``assets/``).

    Deliberately NOT a recursive walk. ``rglob`` reaches ``tests/fixtures/samplesheet.csv``
    and a two-sample fixture would then deny an unrelated real run while citing a file that
    has nothing to do with it. A false deny is the worst failure mode this hook has — worse
    than missing a gate, which merely returns it to the pre-hook status quo — so the search
    stays shallow and skips test-data directories outright.
    """
    candidates = [workspace / name]
    try:
        subdirectories = sorted(p for p in workspace.iterdir() if p.is_dir())
    except OSError:
        subdirectories = []
    candidates.extend(directory / name for directory in subdirectories
                      if directory.name.lower() not in _TEST_DIRS)
    return [path for path in candidates if path.is_file()]


def _count_by_condition(path: Path) -> dict[str, int]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return {}
            lookup = {name.strip().lower(): name for name in reader.fieldnames}
            column = next((lookup[c] for c in _CONDITION_COLUMNS if c in lookup), None)
            if column is None:
                return {}
            counts: dict[str, int] = {}
            for row in reader:
                value = (row.get(column) or "").strip()
                if value:
                    counts[value] = counts.get(value, 0) + 1
            return counts
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}


def _output(decision: str, reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def _render(verdict: dict[str, Any], method_id: str, replicates: int | None) -> str:
    lines = [f"methods-graph: {verdict['status']} for {method_id}"]
    if replicates is not None:
        lines.append(f"  observed replicates_per_group={replicates} (read from samplesheet)")
    for gate in verdict.get("gates", []):
        if gate["result"] not in ("FAIL", "INSUFFICIENT_INFO"):
            continue
        lines.append(
            f"  [{gate['result']}] {gate['assumption']}"
            f" — needs {gate['threshold_key']} >= {gate['threshold']}"
            f", got {gate['supplied']}")
        if gate.get("evidence"):
            lines.append(f"      basis: {gate['evidence']}")
    return "\n".join(lines)


def decide(payload: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Map a PreToolUse payload to a hook decision. ``{}`` means "no opinion"."""
    if payload.get("tool_name") != "Bash":
        return {}
    command = (payload.get("tool_input") or {}).get("command") or ""
    method_id = detect_method(command)
    if method_id is None:
        return {}

    try:
        preconditions = rules.load_rules().method_preconditions(method_id)
    except KeyError:
        # Detected a tool the curation does not cover. Silence, not a guess.
        return {}

    replicates = replicates_per_group(workspace)
    facts = {} if replicates is None else {"replicates_per_group": replicates}
    verdict = guardrail.evaluate_preconditions(preconditions, facts)

    if verdict["status"] == guardrail.BLOCKED:
        return _output("deny", _render(verdict, method_id, replicates))
    if verdict["status"] == guardrail.FACTS_REQUIRED:
        return _output("ask", _render(verdict, method_id, replicates))
    return {}


def main() -> int:
    """Read a hook payload on stdin, write a decision on stdout."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0          # malformed payload must never wedge the session
    workspace = Path(payload.get("cwd") or ".")
    try:
        decision = decide(payload, workspace)
    except Exception:     # noqa: BLE001 - deliberate: see below
        # Broad on purpose. This runs before every Bash call, so any escaping exception —
        # a corrupt crosslinks YAML, an unreadable workspace — would traceback on every
        # command in the session rather than once. Staying silent returns the session to
        # the pre-hook status quo, which is the only safe direction to fail.
        return 0
    if decision:
        json.dump(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
