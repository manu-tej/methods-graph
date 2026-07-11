"""CLI integration tests for the `guardrail` subcommand against the built DB.

Verifies the surface end-to-end: status verdict + the exit-code contract an agent
branches on (0=EVALUABLE, 3=BLOCKED, 4=NOT_EVALUABLE).
"""
from __future__ import annotations

import pathlib

import pytest

from methods_graph import cli

_DB = pathlib.Path("data/methods.kuzu")
pytestmark = pytest.mark.skipif(not _DB.exists(), reason="built DB artifact not present")


def test_cli_blocked_underpowered_deseq2(capsys):
    rc = cli.main(["guardrail", "--method", "m:deseq2",
                   "--fact", "replicates_per_group=2", "--json"])
    assert rc == 3
    assert '"status": "BLOCKED"' in capsys.readouterr().out


def test_cli_evaluable_when_powered():
    rc = cli.main(["guardrail", "--method", "m:deseq2", "--fact", "replicates_per_group=3"])
    assert rc == 0


def test_cli_not_evaluable_unknown_method(capsys):
    rc = cli.main(["guardrail", "--method", "m:bogus"])
    assert rc == 4
    assert "NOT_EVALUABLE" in capsys.readouterr().out


def test_cli_resolves_analysis_intent():
    # percolator is a proteomics tool with target-decoy evaluability coverage
    rc = cli.main(["guardrail", "--analysis", "percolator"])
    assert rc == 0


def test_cli_bad_fact_value_is_a_clear_error():
    with pytest.raises(SystemExit):
        cli.main(["guardrail", "--method", "m:deseq2", "--fact", "replicates_per_group=oops"])


# --- guardrail-chain ---

def test_cli_chain_valid_powered_pipeline():
    rc = cli.main(["guardrail-chain", "--step", "m:salmon", "--step", "m:tximeta",
                   "--step", "m:deseq2", "--fact", "replicates_per_group=3"])
    assert rc == 0


def test_cli_chain_blocked_on_broken_handoff(capsys):
    rc = cli.main(["guardrail-chain", "--step", "m:tximeta", "--step", "m:salmon", "--json"])
    assert rc == 3
    assert '"result": "BROKEN"' in capsys.readouterr().out


def test_cli_chain_not_evaluable_unknown_step():
    rc = cli.main(["guardrail-chain", "--step", "m:salmon", "--step", "m:bogus"])
    assert rc == 4


def test_cli_guardrail_skill_blocked_underpowered():
    rc = cli.main(["guardrail", "--skill", "skill:bioclaw/differential-expression",
                   "--fact", "replicates_per_group=2"])
    assert rc == 3


def test_cli_skills_coverage(capsys):
    import pathlib
    if not pathlib.Path("data/methods.kuzu").exists():
        import pytest; pytest.skip("built DB artifact not present")
    rc = cli.main(["skills", "--coverage", "--db", "data/methods.kuzu"])
    assert rc == 0
    import json as _j
    out = _j.loads(capsys.readouterr().out)
    assert out["skills"] >= 10 and out["guardrail_evaluable"] >= 1
    # Coverage invariants, not just floors: a skill can only be evaluable if it is
    # wired to a Method, and wiring is a subset of all skills.
    assert out["wired_to_method"] <= out["skills"]
    assert out["guardrail_evaluable"] <= out["wired_to_method"]
    # honest_gaps is the exact complement of evaluable (the math the CLI does).
    assert out["honest_gaps"] == out["skills"] - out["guardrail_evaluable"]
