"""Gate precision: only methods that genuinely perform group-level inference may BLOCK.

A pre-run replicate floor is a property of a cross-condition statistical test. A tool
that performs no such test — a read aligner, a per-sample quantifier, a gene-cluster
detector — must never be BLOCKED by a replicate count, however few replicates exist.

These tests need the built DB because the defect lives in how `method_preconditions`
assembles assumptions from the graph, not in the pure verdict function.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from methods_graph import guardrail
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

_DB = Path("data/methods.kuzu")
pytestmark = pytest.mark.skipif(not _DB.exists(), reason="built DB artifact not present")

_STARVED = {"replicates_per_group": 1, "peptides_per_protein": 1}


def _status(method_id: str) -> str:
    with KuzuMethodsGraphProvider(_DB) as provider:
        return guardrail.evaluate(provider, method=method_id, facts=_STARVED)["status"]


def test_read_aligner_is_not_blocked_by_a_replicate_floor():
    """bbmap aligns reads per sample; a replicate count cannot gate it."""
    assert _status("m:bbmap") != "BLOCKED"


def test_quantifier_is_not_blocked_by_a_replicate_floor():
    """salmon runs maximum-likelihood estimation per sample, so it legitimately carries
    'regularity conditions'. But sample_size_power_check declares
    ``applies_to_assumption: asymptotic_normality``, so its replicate floor must not
    attach to regularity conditions — salmon has no experimental groups at all.
    """
    assert _status("m:salmon") != "BLOCKED"


def test_differential_expression_still_blocks_at_one_replicate():
    """The precision fixes must not cost the one gate that is correct."""
    assert _status("m:deseq2") == "BLOCKED"


# --- regression pin ---------------------------------------------------------------
# Which methods may refuse work is a curation decision. It must never be an emergent
# property of third-party EDAM tags: before source/scope were honoured, bio.tools'
# annotation of antiSMASH as "Differential gene expression analysis" was enough to make a
# gene-cluster detector refuse an experiment.
#
# A characterization test, not a TDD cycle: it passes by construction today, and its job is
# to fail LATER if a curation or inheritance change silently re-widens the set. Adding an id
# here should require justifying that the precondition is intrinsic to that method rather
# than inherited from an operation-level tag.

GATEABLE = {"m:deseq2"}


def test_the_gateable_set_is_pinned():
    """Enumerate all methods; exactly GATEABLE may reach BLOCKED under starved facts."""
    import kuzu

    db = kuzu.Database(str(_DB), read_only=True)
    conn = kuzu.Connection(db)
    try:
        result = conn.execute("MATCH (n) WHERE n.kind='Method' RETURN n.id ORDER BY n.id")
        method_ids = []
        while result.has_next():
            method_ids.append(result.get_next()[0])
    finally:
        conn.close()
        db.close()

    assert len(method_ids) > 800, "expected the full method registry"
    with KuzuMethodsGraphProvider(_DB) as provider:
        blocked = {
            mid for mid in method_ids
            if guardrail.evaluate(provider, method=mid, facts=_STARVED)["status"] == "BLOCKED"
        }
    assert blocked == GATEABLE
