"""PreToolUse hook: enforcement that does not depend on the model cooperating.

The model does not choose whether this runs, and it does not supply the facts — the hook
reads the samplesheet itself. That is what makes the verdict a property of the data and the
curated rules rather than of the model's instruction-following.

Every function here is deterministic: same command, same samplesheet, same decision.
"""
from __future__ import annotations

from methods_graph import hook


def _samplesheet(tmp_path, rows, name="samplesheet.csv"):
    path = tmp_path / name
    path.write_text("sample,fastq_1,condition\n" + "".join(
        f"{s},{s}_R1.fq.gz,{c}\n" for s, c in rows), encoding="utf-8")
    return path


# --- deterministic fact extraction ---

def test_replicates_per_group_takes_the_smallest_arm(tmp_path):
    _samplesheet(tmp_path, [("s1", "ctrl"), ("s2", "ctrl"), ("s3", "ctrl"),
                            ("s4", "treat")])
    assert hook.replicates_per_group(tmp_path) == 1


def test_replicates_per_group_is_none_without_a_samplesheet(tmp_path):
    """No samplesheet is not zero replicates. Guessing a number here would invent a fact."""
    assert hook.replicates_per_group(tmp_path) is None


# --- method detection from the command the agent is about to run ---

def test_detects_deseq2_invocation():
    assert hook.detect_method("Rscript -e 'library(DESeq2); dds <- DESeq(dds)'") == "m:deseq2"


def test_ignores_unrelated_commands():
    assert hook.detect_method("ls -la results/") is None
    assert hook.detect_method("samtools sort in.bam -o out.bam") is None


# --- the decision ---

def test_underpowered_design_is_denied_with_the_citation(tmp_path):
    _samplesheet(tmp_path, [("s1", "ctrl"), ("s2", "treat")])
    out = hook.decide({"tool_name": "Bash",
                       "tool_input": {"command": "Rscript run_deseq2.R"}}, tmp_path)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert "BLOCKED" in reason
    assert "10.1261/rna.053959.115" in reason, f"no citation in refusal: {reason}"


def test_adequate_design_is_not_denied(tmp_path):
    _samplesheet(tmp_path, [("s1", "ctrl"), ("s2", "ctrl"), ("s3", "ctrl"),
                            ("s4", "treat"), ("s5", "treat"), ("s6", "treat")])
    out = hook.decide({"tool_name": "Bash",
                       "tool_input": {"command": "Rscript run_deseq2.R"}}, tmp_path)
    # An adequate design draws no opinion at all, which is itself "not denied".
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


def test_unrelated_command_is_passed_through(tmp_path):
    out = hook.decide({"tool_name": "Bash", "tool_input": {"command": "git status"}},
                      tmp_path)
    assert out == {}, "the hook must stay silent on commands it has no rule for"


def test_missing_samplesheet_asks_rather_than_allowing(tmp_path):
    """A gate exists and the fact is unavailable. Allowing would let 'no samplesheet' be
    the cheapest route past the guardrail; denying outright would block legitimate work
    the hook simply cannot see. Escalate to the human instead."""
    out = hook.decide({"tool_name": "Bash",
                       "tool_input": {"command": "Rscript run_deseq2.R"}}, tmp_path)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "FACTS_REQUIRED" in decision["permissionDecisionReason"]
