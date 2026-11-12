"""Runs only when snapshots/go holds the real files. Not a CI gate.

Builds over up to a 300-subject slice (the same slice tests/test_biolean_scale.py uses; only
118 of them are actually annotated on the shipped GO/GOA pair) so the whole check stays under
two minutes, then asserts:

- every counter reconciles (population rows == eligible + dropped; prove eligible +
  not_rederivable, and hypothesize eligible + goal_not_statable_total, both equal the
  population's triples)
- gold hits every prove item
- modal is accepted exactly when it hits (its only other outcome is AXIOM_NOT_FOUND)
- random fails only by ROOT_MISMATCH
- template saturates hypothesize's format_ok and goal_match
"""
import random
import time
from pathlib import Path

import pytest

from methods_graph.biolean.bench.baselines import baseline_adapter
from methods_graph.biolean.bench.items import build_items, load_items, read_release
from methods_graph.biolean.bench.run import items_manifest, run_items
from methods_graph.biolean.bench.score import summarize
from methods_graph.biolean.store import load_store

SNAP = Path("snapshots/go")
pytestmark = pytest.mark.skipif(
    not all((SNAP / f).exists() for f in ("go-basic.obo", "goa_human.gaf.gz", "gaf-eco-mapping.txt")),
    reason="real GO/GOA snapshot not present")


def test_real_snapshot_build_reconciles_and_every_baseline_behaves(tmp_path):
    store, _ = load_store(SNAP)
    rng = random.Random(0)
    subjects = sorted({a.subject for s in rng.sample(range(1, 40_000), 2_000)
                       for a in store.annotations(f"UniProtKB:P{s:05d}")})[:300]
    t0 = time.monotonic()
    manifest = build_items(store, tmp_path, release=read_release(SNAP), per_track=100, seed=0,
                           subjects=subjects)
    assert time.monotonic() - t0 < 120, manifest["population"]

    pop = manifest["population"]
    assert pop["n_subjects"] == len(subjects)
    assert pop["rows"] == pop["eligible_rows"] + sum(pop["dropped"].values())
    assert pop["dropped"]["negated"] > 0 and pop["dropped"]["evidence_class"] > 0
    assert manifest["prove"]["eligible"] + manifest["prove"]["not_rederivable"] == pop["triples"]
    assert manifest["hypothesize"]["eligible"] + manifest["hypothesize"]["goal_not_statable_total"] == pop["triples"]
    assert manifest["prove"]["sampled"] == 100 and manifest["hypothesize"]["sampled"] == 100
    assert manifest["release"]["go_basic_data_version"].startswith("releases/")
    assert manifest["release"]["goa_go_version"]           # the real GAF names its GO release

    items, _ = load_items(tmp_path)
    prove = [i for i in items if i["track"] == "prove"]
    hyp = [i for i in items if i["track"] == "hypothesize"]
    im = items_manifest(manifest)

    gold = summarize(run_items(prove, baseline_adapter("gold:", prove, store), store,
                               model="gold:", items_manifest=im))
    assert gold["n_errors"] == 0 and gold["n_unparsed"] == 0
    assert gold["prove"]["hit_rate"] == 1.0
    assert sum(b["n"] for b in gold["prove"]["by_gold_depth"].values()) == 100

    modal = summarize(run_items(prove, baseline_adapter("modal:", prove, store, modal_path=tmp_path / "modal.json"),
                                store, model="modal:", items_manifest=im))
    # Every modal reply is structurally valid at a visible or hidden axiom, so it is accepted
    # exactly when it hits; the only other outcome is AXIOM_NOT_FOUND.
    assert modal["prove"]["acceptance_rate"] == modal["prove"]["hit_rate"]
    assert set(modal["prove"]["error_items"]) <= {"AXIOM_NOT_FOUND"}

    randoms = summarize(run_items(prove, baseline_adapter("random:0", prove, store), store,
                                  model="random:0", items_manifest=im))
    assert set(randoms["prove"]["error_items"]) <= {"ROOT_MISMATCH"}

    template = summarize(run_items(hyp, baseline_adapter("template:", hyp, store), store,
                                   model="template:", items_manifest=im))
    assert template["hypothesize"]["format_ok"] == {"n": 100, "rate": 1.0}
    assert template["hypothesize"]["goal_match"] == {"n": 100, "rate": 1.0}
