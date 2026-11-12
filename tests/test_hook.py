"""PreToolUse hook: enforcement that does not depend on the model cooperating.

The model does not choose whether this runs, and it does not supply the facts — the hook
reads the samplesheet itself. That is what makes the verdict a property of the data and the
curated rules rather than of the model's instruction-following.

Every function here is deterministic: same command, same samplesheet, same decision.
"""
from __future__ import annotations

import io
import json
import sys

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


def test_a_samplesheet_one_directory_down_is_still_read(tmp_path):
    """nf-core convention puts it in assets/ — the common real case."""
    assets = tmp_path / "assets"
    assets.mkdir()
    _samplesheet(assets, [("s1", "ctrl"), ("s2", "treat"), ("s3", "treat")])
    assert hook.replicates_per_group(tmp_path) == 1


def test_a_test_fixture_samplesheet_is_never_used(tmp_path):
    """A false deny is the worst thing an enforcement hook can do. A recursive walk finds
    tests/fixtures/samplesheet.csv and denies a real run while citing a fixture that has
    nothing to do with it."""
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    _samplesheet(fixtures, [("s1", "ctrl"), ("s2", "treat")])
    assert hook.replicates_per_group(tmp_path) is None


def test_test_directories_are_skipped_even_at_the_top_level(tmp_path):
    for directory in ("tests", "test", "fixtures"):
        (tmp_path / directory).mkdir()
        _samplesheet(tmp_path / directory, [("s1", "ctrl"), ("s2", "treat")])
    assert hook.replicates_per_group(tmp_path) is None


def test_a_deep_samplesheet_is_out_of_scope(tmp_path):
    """Depth <= 1 only: anything further away is not plausibly this run's design."""
    deep = tmp_path / "work" / "ab" / "cd12ef"
    deep.mkdir(parents=True)
    _samplesheet(deep, [("s1", "ctrl"), ("s2", "treat")])
    assert hook.replicates_per_group(tmp_path) is None


# --- method detection from the command the agent is about to run ---

def test_detects_deseq2_invocation():
    assert hook.detect_method("Rscript -e 'library(DESeq2); dds <- DESeq(dds)'") == "m:deseq2"


def test_ignores_unrelated_commands():
    assert hook.detect_method("ls -la results/") is None
    assert hook.detect_method("samtools sort in.bam -o out.bam") is None


def test_only_methods_with_a_gate_that_can_fire_are_detected():
    """A pattern whose method has no firing precondition advertises enforcement the
    curation cannot deliver: m:edger carries no replicate floor at all, and m:limma's
    exists only on the amenable path, which no longer gates. Detecting them produces a
    silent no-op at best and an 'ask' the user cannot resolve at worst."""
    assert hook.detect_method("Rscript -e 'library(edgeR); exactTest(y)'") is None
    assert hook.detect_method("Rscript -e 'library(limma); lmFit(v, design)'") is None
    assert hook.detect_method("kallisto quant -i idx -o out r1.fq r2.fq") is None


def test_every_detected_method_can_actually_reach_a_verdict():
    """Structural guard against re-adding a decorative pattern: each id in the table must
    resolve to curated preconditions with at least one gateable numeric threshold."""
    from methods_graph import rules

    engine = rules.load_rules()
    for _pattern, method_id in hook._METHOD_PATTERNS:
        pre = engine.method_preconditions(method_id)
        assert any(a.get("threshold") for a in pre["assumptions"]), (
            f"{method_id} is detected by the hook but has no threshold that can fire")


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


def test_main_never_wedges_the_session_when_the_rules_cannot_be_read(monkeypatch, capsys):
    """The module promises a malformed input can never break a Bash call. An unreadable
    crosslinks YAML is the same failure with a different cause, and it would traceback on
    EVERY command rather than just one."""
    def _explode(*_args, **_kwargs):
        raise RuntimeError("crosslinks yaml is corrupt")

    monkeypatch.setattr(hook, "decide", _explode)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Bash", "cwd": ".", "tool_input": {"command": "Rscript deseq2.R"}})))
    assert hook.main() == 0
    assert capsys.readouterr().out == ""


def test_missing_samplesheet_asks_rather_than_allowing(tmp_path):
    """A gate exists and the fact is unavailable. Allowing would let 'no samplesheet' be
    the cheapest route past the guardrail; denying outright would block legitimate work
    the hook simply cannot see. Escalate to the human instead."""
    out = hook.decide({"tool_name": "Bash",
                       "tool_input": {"command": "Rscript run_deseq2.R"}}, tmp_path)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "FACTS_REQUIRED" in decision["permissionDecisionReason"]
