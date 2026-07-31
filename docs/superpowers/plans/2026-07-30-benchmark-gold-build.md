# Benchmark Gold Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn nf-core pipeline DAGs into a frozen benchmark item set — `bench/items/*.json` plus `bench/gold/manifest.json` — where every gold sequence comes from a real Nextflow DAG and every excluded pipeline is recorded with a reason.

**Architecture:** Three pure functions plus a CLI command. `gold.py` turns a `dag.mmd` into a deterministic ordered list of module ids. `build.py` turns one ordered list into benchmark items and aggregates per-pipeline outcomes into a manifest. Nothing here touches Kùzu — the gold build reads Nextflow output and writes JSON.

**Tech Stack:** Python 3.10+, stdlib only (`json`, `hashlib`, `pathlib`), reusing `methods_graph.connectors.nextflow_dag`. pytest for tests.

## Global Constraints

- **Gold requires `derivation == "nextflow_dsl2"`.** The `io_inferred` fallback in `nfcore_pipeline.py:119` is rejected outright, never downweighted — inferring order from typed I/O is the same reasoning the benchmark scores.
- **Every excluded pipeline is recorded** in `bench/gold/manifest.json` with a machine-readable reason. Silent drops misreport the covered population.
- **Determinism:** identical inputs must produce byte-identical items. Sort every iteration over a set. No `Date.now()`, no RNG.
- **Bookkeeping steps stripped:** `multiqc`, `versions`, `dumpsoftwareversions`, `custom_dumpsoftwareversions`.
- **No Kùzu import** anywhere under `src/methods_graph/bench/`.

---

### Task 1: Gold sequence extraction

**Files:**
- Create: `src/methods_graph/bench/__init__.py` (empty)
- Create: `src/methods_graph/bench/gold.py`
- Test: `tests/test_bench_gold.py`

**Interfaces:**
- Consumes: `parse_dag_process_edges(mmd_text: str) -> list[tuple[str, str, int]]` and `break_cycles(edges: list[tuple[str, str, int]]) -> list[tuple[str, str]]` from `methods_graph.connectors.nextflow_dag`
- Produces: `gold_sequence(mmd_text: str, proc_to_module: dict[str, str], *, exclude: frozenset[str] = BOOKKEEPING) -> list[str]` — returns module ids in execution order. Also exports `BOOKKEEPING: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_gold.py`:

```python
"""Gold sequence extraction: a Nextflow DAG becomes an ordered list of module ids."""
from __future__ import annotations

from methods_graph.bench.gold import BOOKKEEPING, gold_sequence

# TRIM -> ALIGN -> SORT -> {QC, INDEX}, plus a versions/multiqc accumulator hub
# (v10) that five processes feed. The parser already excludes that hub.
DAG = """flowchart TB
    v0(["TRIM"])
    v1["ch_reads"]
    v2(["ALIGN"])
    v3["ch_bam"]
    v4(["SORT"])
    v5["ch_sorted"]
    v6(["QC"])
    v7(["INDEX"])
    v10[" "]
    v11(["MULTIQC"])
    v0 --> v1
    v1 --> v2
    v2 --> v3
    v3 --> v4
    v4 --> v5
    v5 --> v6
    v5 --> v7
    v0 --> v10
    v2 --> v10
    v4 --> v10
    v6 --> v10
    v7 --> v10
    v10 --> v11
"""

PROC_TO_MODULE = {
    "TRIM": "mod:trimgalore",
    "ALIGN": "mod:star",
    "SORT": "mod:samtools_sort",
    "QC": "mod:qualimap",
    "INDEX": "mod:samtools_index",
    "MULTIQC": "mod:multiqc",
}


def test_orders_modules_by_dataflow():
    assert gold_sequence(DAG, PROC_TO_MODULE) == [
        "mod:trimgalore", "mod:star", "mod:samtools_sort",
        "mod:qualimap", "mod:samtools_index",
    ]


def test_unmapped_processes_are_dropped():
    partial = {k: v for k, v in PROC_TO_MODULE.items() if k != "QC"}
    assert "mod:qualimap" not in gold_sequence(DAG, partial)


def test_bookkeeping_steps_are_stripped():
    """A directly-wired multiqc must still be removed: it is reporting, not method choice."""
    wired = """flowchart TB
    v0(["ALIGN"])
    v1["ch_bam"]
    v2(["MULTIQC"])
    v0 --> v1
    v1 --> v2
"""
    assert gold_sequence(wired, PROC_TO_MODULE) == ["mod:star"]
    assert "multiqc" in BOOKKEEPING


def test_is_deterministic():
    first = gold_sequence(DAG, PROC_TO_MODULE)
    assert all(gold_sequence(DAG, PROC_TO_MODULE) == first for _ in range(5))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_gold.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'methods_graph.bench'`

- [ ] **Step 3: Write minimal implementation**

Create `src/methods_graph/bench/__init__.py` as an empty file.

Create `src/methods_graph/bench/gold.py`:

```python
"""A Nextflow DAG becomes a deterministic, ordered list of module ids.

This is the benchmark's ground truth. It reads the pipeline's own channel wiring —
never an inference from typed I/O, which is the reasoning the benchmark scores.
"""
from __future__ import annotations

from methods_graph.connectors.nextflow_dag import break_cycles, parse_dag_process_edges

# Reporting/aggregation steps. Present in almost every pipeline, chosen by nobody,
# and predicting them measures familiarity with nf-core conventions rather than
# method knowledge.
BOOKKEEPING = frozenset({
    "multiqc", "versions", "dumpsoftwareversions", "custom_dumpsoftwareversions",
})


def _bare(module_id: str) -> str:
    """``mod:samtools_sort`` -> ``samtools_sort``."""
    return module_id.split(":", 1)[1] if ":" in module_id else module_id


def _topological_order(edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm, with every iteration sorted so output is deterministic."""
    unique = sorted(set(edges))
    nodes = sorted({node for pair in unique for node in pair})
    incoming = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in unique:
        outgoing[source].append(target)
        incoming[target] += 1

    ready = sorted(node for node in nodes if incoming[node] == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(outgoing[node]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
        ready.sort()
    return order


def gold_sequence(
    mmd_text: str,
    proc_to_module: dict[str, str],
    *,
    exclude: frozenset[str] = BOOKKEEPING,
) -> list[str]:
    """Ordered module ids for one pipeline, from its Nextflow DAG.

    Processes with no module mapping are dropped rather than guessed at.
    """
    edges: list[tuple[str, str, int]] = []
    for source_label, target_label, rank in parse_dag_process_edges(mmd_text):
        source = proc_to_module.get(source_label)
        target = proc_to_module.get(target_label)
        if not source or not target or source == target:
            continue
        edges.append((source, target, rank))

    ordered = _topological_order(break_cycles(edges))
    return [node for node in ordered if _bare(node) not in exclude]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_gold.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/__init__.py src/methods_graph/bench/gold.py tests/test_bench_gold.py
git commit -m "feat(bench): extract ordered gold sequences from Nextflow DAGs"
```

---

### Task 2: Item generation

**Files:**
- Create: `src/methods_graph/bench/build.py`
- Test: `tests/test_bench_build.py`

**Interfaces:**
- Consumes: `gold_sequence` from Task 1 (not called directly here — callers pass the resulting list)
- Produces: `make_items(*, pipeline: str, revision: str, nxf_ver: str, dag_sha256: str, goal: str, sequence: list[str], derivation: str) -> list[dict]`. Raises `ValueError` when `derivation != "nextflow_dsl2"` or `sequence` has fewer than two steps.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_build.py`:

```python
"""One gold sequence becomes one whole-pipeline item plus N next-step items."""
from __future__ import annotations

import pytest

from methods_graph.bench.build import make_items

SEQUENCE = ["mod:trimgalore", "mod:star", "mod:salmon", "mod:deseq2"]
COMMON = dict(
    pipeline="rnaseq", revision="3.14.0", nxf_ver="23.04.0",
    dag_sha256="9f2c", goal="Bulk RNA-seq differential expression",
    sequence=SEQUENCE, derivation="nextflow_dsl2",
)


def test_produces_one_whole_pipeline_item():
    whole = [i for i in make_items(**COMMON) if i["task"] == "whole_pipeline"]
    assert len(whole) == 1
    assert whole[0]["gold"]["sequence"] == SEQUENCE
    assert whole[0]["given"] == []


def test_produces_one_next_step_item_per_position():
    steps = [i for i in make_items(**COMMON) if i["task"] == "next_step"]
    assert len(steps) == len(SEQUENCE)
    assert steps[0]["given"] == []
    assert steps[0]["gold"]["next"] == "mod:trimgalore"
    assert steps[-1]["given"] == SEQUENCE[:-1]
    assert steps[-1]["gold"]["next"] == "mod:deseq2"


def test_every_item_carries_reproducible_provenance():
    for item in make_items(**COMMON):
        assert item["gold"]["source"] == "nf-core/rnaseq@3.14.0"
        assert item["gold"]["nxf_ver"] == "23.04.0"
        assert item["gold"]["dag_sha256"] == "9f2c"
        assert item["gold"]["derivation"] == "nextflow_dsl2"


def test_ids_are_unique_and_stable():
    ids = [i["id"] for i in make_items(**COMMON)]
    assert len(ids) == len(set(ids))
    assert ids == [i["id"] for i in make_items(**COMMON)]


def test_io_inferred_gold_is_rejected():
    """The whole point of the constraint: inferred wiring can never become an item."""
    with pytest.raises(ValueError, match="derivation"):
        make_items(**{**COMMON, "derivation": "io_inferred"})


def test_single_step_pipeline_is_rejected():
    """A one-step 'sequence' tests nothing about sequencing."""
    with pytest.raises(ValueError, match="at least two"):
        make_items(**{**COMMON, "sequence": ["mod:fastqc"]})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'methods_graph.bench.build'`

- [ ] **Step 3: Write minimal implementation**

Create `src/methods_graph/bench/build.py`:

```python
"""Gold sequences become frozen benchmark items."""
from __future__ import annotations

from typing import Any

_REQUIRED_DERIVATION = "nextflow_dsl2"


def make_items(
    *,
    pipeline: str,
    revision: str,
    nxf_ver: str,
    dag_sha256: str,
    goal: str,
    sequence: list[str],
    derivation: str,
) -> list[dict[str, Any]]:
    """One whole-pipeline item plus one next-step item per position.

    Rejects anything not derived from a real Nextflow DAG: accepting inferred
    wiring would make the answer key an artifact of the method under test.
    """
    if derivation != _REQUIRED_DERIVATION:
        raise ValueError(
            f"derivation must be {_REQUIRED_DERIVATION!r}, got {derivation!r}")
    if len(sequence) < 2:
        raise ValueError("a gold sequence needs at least two steps to test ordering")

    provenance = {
        "source": f"nf-core/{pipeline}@{revision}",
        "nxf_ver": nxf_ver,
        "dag_sha256": dag_sha256,
        "derivation": derivation,
    }
    items: list[dict[str, Any]] = [{
        "id": f"{pipeline}/whole/001",
        "task": "whole_pipeline",
        "goal": goal,
        "given": [],
        "gold": {"sequence": list(sequence), **provenance},
    }]
    for index in range(len(sequence)):
        items.append({
            "id": f"{pipeline}/next/{index:03d}",
            "task": "next_step",
            "goal": goal,
            "given": list(sequence[:index]),
            "gold": {"next": sequence[index], **provenance},
        })
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_build.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/build.py tests/test_bench_build.py
git commit -m "feat(bench): generate whole-pipeline and next-step items from a gold sequence"
```

---

### Task 3: Manifest with recorded exclusions

**Files:**
- Modify: `src/methods_graph/bench/build.py` (append)
- Test: `tests/test_bench_build.py` (append)

**Interfaces:**
- Produces: `build_manifest(outcomes: list[dict]) -> dict`. Each outcome is `{"pipeline": str, "revision": str, "status": "used" | "dropped", "reason": str | None, "n_items": int}`. Returns `{"schema": 1, "n_pipelines": int, "n_used": int, "n_dropped": int, "n_items": int, "used": [...], "dropped": [...]}` with both lists sorted by pipeline name.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_build.py`:

```python
from methods_graph.bench.build import build_manifest


def test_manifest_counts_used_and_dropped():
    manifest = build_manifest([
        {"pipeline": "rnaseq", "revision": "3.14.0", "status": "used",
         "reason": None, "n_items": 5},
        {"pipeline": "sarek", "revision": "3.4.0", "status": "dropped",
         "reason": "nextflow preview failed (NXF_VER mismatch)", "n_items": 0},
    ])
    assert manifest["n_pipelines"] == 2
    assert manifest["n_used"] == 1
    assert manifest["n_dropped"] == 1
    assert manifest["n_items"] == 5


def test_dropped_pipelines_keep_their_reason():
    """A benchmark that silently omits what it could not parse misreports coverage."""
    manifest = build_manifest([
        {"pipeline": "sarek", "revision": "3.4.0", "status": "dropped",
         "reason": "no dag.mmd produced", "n_items": 0},
    ])
    assert manifest["dropped"][0]["reason"] == "no dag.mmd produced"


def test_dropped_without_a_reason_is_rejected():
    with pytest.raises(ValueError, match="reason"):
        build_manifest([
            {"pipeline": "x", "revision": "1", "status": "dropped",
             "reason": None, "n_items": 0},
        ])


def test_manifest_is_sorted_for_stable_diffs():
    manifest = build_manifest([
        {"pipeline": "sarek", "revision": "1", "status": "used",
         "reason": None, "n_items": 2},
        {"pipeline": "atacseq", "revision": "1", "status": "used",
         "reason": None, "n_items": 2},
    ])
    assert [p["pipeline"] for p in manifest["used"]] == ["atacseq", "sarek"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_build.py -q -k manifest`
Expected: FAIL — `ImportError: cannot import name 'build_manifest'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/methods_graph/bench/build.py`:

```python
def build_manifest(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-pipeline outcomes, recording every exclusion with its reason.

    A dropped pipeline without a reason is an error, not a permitted shortcut:
    unexplained exclusions make the benchmark's coverage unauditable.
    """
    used, dropped = [], []
    for outcome in outcomes:
        if outcome["status"] == "dropped":
            if not outcome.get("reason"):
                raise ValueError(
                    f"dropped pipeline {outcome['pipeline']!r} needs a reason")
            dropped.append(outcome)
        else:
            used.append(outcome)

    by_name = lambda entry: entry["pipeline"]
    return {
        "schema": 1,
        "n_pipelines": len(outcomes),
        "n_used": len(used),
        "n_dropped": len(dropped),
        "n_items": sum(entry["n_items"] for entry in used),
        "used": sorted(used, key=by_name),
        "dropped": sorted(dropped, key=by_name),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_build.py -q`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/build.py tests/test_bench_build.py
git commit -m "feat(bench): manifest recording every excluded pipeline with a reason"
```

---

### Task 4: `mg bench build` CLI command

**Files:**
- Create: `src/methods_graph/bench/run.py`
- Modify: `src/methods_graph/connectors/nfcore_pipeline.py` — rename `_process_to_modid` → `process_to_modid` and `_module_paths_from_modules_json` → `module_paths_from_modules_json`, updating every in-module caller. These are reusable across the benchmark; importing them with a leading underscore would be a standing smell.
- Modify: `src/methods_graph/cli.py` (add subparser + dispatch alongside the existing `skills` / `explain` commands)
- Test: `tests/test_bench_run.py`

**Interfaces:**
- Consumes: `gold_sequence` (Task 1), `make_items` and `build_manifest` (Tasks 2–3), and the newly-public `process_to_modid(pipeline_dir: Path, path_to_modid: dict[str, str]) -> dict[str, str]` and `module_paths_from_modules_json(modules_json: dict) -> list[str]` from `methods_graph.connectors.nfcore_pipeline`
- Produces: `build_from_clones(pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str]) -> dict` — walks `<pipelines_dir>/<name>/`, reads `dag.mmd` where present, writes `<out_dir>/items/<pipeline>.json` and `<out_dir>/gold/manifest.json`, returns the manifest.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_run.py`:

```python
"""End-to-end gold build over a directory of pipeline clones."""
from __future__ import annotations

import json

from methods_graph.bench.run import build_from_clones

DAG = """flowchart TB
    v0(["TRIM"])
    v1["ch_reads"]
    v2(["ALIGN"])
    v0 --> v1
    v1 --> v2
"""

MODULES_JSON = {
    "repos": {"https://github.com/nf-core/modules.git": {"modules": {"nf-core": {
        "trimgalore": {"branch": "master", "git_sha": "abc"},
        "star": {"branch": "master", "git_sha": "def"},
    }}}}
}


def _clone(root, name, *, dag: str | None):
    directory = root / name
    (directory / "modules" / "nf-core").mkdir(parents=True)
    (directory / "modules.json").write_text(json.dumps(MODULES_JSON))
    if dag is not None:
        (directory / "dag.mmd").write_text(dag)
    return directory


def test_pipeline_without_a_dag_is_dropped_with_a_reason(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "sarek", dag=None)
    manifest = build_from_clones(clones, tmp_path / "bench", goals={"sarek": "Variant calling"})
    assert manifest["n_used"] == 0
    assert manifest["n_dropped"] == 1
    assert "dag.mmd" in manifest["dropped"][0]["reason"]


def test_manifest_and_items_are_written(tmp_path):
    clones = tmp_path / "pipelines"
    clones.mkdir()
    _clone(clones, "rnaseq", dag=DAG)
    out = tmp_path / "bench"
    build_from_clones(clones, out, goals={"rnaseq": "Bulk RNA-seq"})
    assert (out / "gold" / "manifest.json").exists()
    written = json.loads((out / "items" / "rnaseq.json").read_text())
    assert any(item["task"] == "whole_pipeline" for item in written)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'methods_graph.bench.run'`

- [ ] **Step 3a: Promote the two helpers to public names**

In `src/methods_graph/connectors/nfcore_pipeline.py`, rename `_process_to_modid` ->
`process_to_modid` and `_module_paths_from_modules_json` -> `module_paths_from_modules_json`,
updating every caller inside that file. Run `.venv/bin/python -m pytest tests/test_nfcore_pipeline.py -q`
to confirm nothing broke, then continue.

- [ ] **Step 3b: Write minimal implementation**

Create `src/methods_graph/bench/run.py`:

```python
"""Walk a directory of nf-core clones and emit the frozen benchmark item set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from methods_graph.bench.build import build_manifest, make_items
from methods_graph.bench.gold import gold_sequence
from methods_graph.connectors.nfcore_pipeline import (
    module_paths_from_modules_json, process_to_modid)


def _module_map(pipeline_dir: Path) -> dict[str, str]:
    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = module_paths_from_modules_json(modules_json)
    path_to_modid = {path: f"mod:{path.split('/')[-1]}" for path in rel_paths}
    return process_to_modid(pipeline_dir, path_to_modid)


def build_from_clones(
    pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str],
) -> dict[str, Any]:
    """Build items for every clone under *pipelines_dir*; write items + manifest."""
    items_dir, gold_dir = out_dir / "items", out_dir / "gold"
    items_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for pipeline_dir in sorted(p for p in pipelines_dir.iterdir() if p.is_dir()):
        name = pipeline_dir.name
        revision = "unknown"
        dag_path = pipeline_dir / "dag.mmd"
        if not dag_path.exists():
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": "no dag.mmd produced by nextflow -preview"})
            continue

        text = dag_path.read_text()
        sequence = gold_sequence(text, _module_map(pipeline_dir))
        if len(sequence) < 2:
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": f"gold sequence too short ({len(sequence)} steps)"})
            continue

        items = make_items(
            pipeline=name, revision=revision, nxf_ver="unknown",
            dag_sha256=hashlib.sha256(text.encode()).hexdigest(),
            goal=goals.get(name, name), sequence=sequence,
            derivation="nextflow_dsl2",
        )
        (items_dir / f"{name}.json").write_text(json.dumps(items, indent=2, sort_keys=True))
        outcomes.append({"pipeline": name, "revision": revision, "status": "used",
                         "reason": None, "n_items": len(items)})

    manifest = build_manifest(outcomes)
    (gold_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
```

Then in `src/methods_graph/cli.py`, add a subparser next to the existing ones:

```python
    p_bench = sub.add_parser("bench", help="build the method-sequencing benchmark item set")
    p_bench.add_argument("--pipelines", type=Path, default=Path("snapshots/pipelines"))
    p_bench.add_argument("--out", type=Path, default=Path("bench"))
```

and in the dispatch block:

```python
    if args.command == "bench":
        from methods_graph.bench.run import build_from_clones
        manifest = build_from_clones(args.pipelines, args.out, goals={})
        print(f"bench: {manifest['n_used']} pipelines used, "
              f"{manifest['n_dropped']} dropped, {manifest['n_items']} items")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -q && .venv/bin/python -m pytest -q`
Expected: PASS — new tests green, existing suite unchanged

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/run.py src/methods_graph/cli.py tests/test_bench_run.py
git commit -m "feat(bench): mg bench build emits items and a manifest from pipeline clones"
```

---

## Self-review notes

- **Spec coverage:** §1 (gold standard, derivation constraint, dropped-pipeline recording) → Tasks 1–4. §2 (item schema, both task types) → Task 2. §3/§3b/§4/§5 are Plans 2 and 3.
- **Deferred to Plan 2:** scoring, equivalence classes, model adapters.
- **Deferred to Plan 3:** live cuts, bioRxiv fetch.
- **Known gap:** `revision` and `nxf_ver` are `"unknown"` in Task 4 because clones do not carry them. Plan 2 threads the real values through from `fetch_nfcore_pipeline`'s returned manifest (`{repo, commit, revision, nxf_ver, path, dag, fetched_at}`). Items remain re-derivable via `dag_sha256` in the meantime.
