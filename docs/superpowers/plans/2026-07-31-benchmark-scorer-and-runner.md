# Benchmark Scorer, Adapters and Runner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the frozen gold item set into measured numbers — score a model's free-text answer for method *selection*, *sequencing* and *validity*, and run any LLM against the set through a uniform adapter.

**Architecture:** A narrow `Oracle` interface stands between the graph and the scorer, so every metric is a pure function over sets and lists and is unit-testable with a dict-backed double. Model answers are normalized to `m:` method ids; gold `mod:` module ids are *projected* onto the same space through `Module -WRAPS-> Method`. Scoring is edge-based, not linearization-based. The runner is a thin loop: render prompt → call adapter → parse → score → append JSONL, retaining raw output so any score can be re-derived.

**Tech Stack:** Python 3.10+, stdlib only for new code (`urllib.request`, `subprocess`, `json`, `re`), existing `kuzu==0.11.3` for the oracle, `pytest` for tests. **No new dependencies.**

## Reconnaissance — measured facts this plan is built on

These were verified against `data/methods.kuzu` (905 methods) and the merged Plan 1 code before this plan was written. They override anything in the spec that contradicts them.

| Fact | Value | Consequence |
|---|---|---|
| Gold sequences use **`mod:` ids**, not `m:` | `gold.py` maps processes via `iter_module_metas` | Spec §2's `m:fastqc` example is wrong. A **projection layer is required** and is Task 2. |
| `Module -WRAPS-> Method` edges | 1,981 edges covering 1,921 of 2,038 modules (94%) | ~6% of gold steps are unresolvable and must be **counted, never dropped silently**. |
| Modules wrapping >1 method | exists (`mod:custom_orfnormalise` → 6) | Projection must pick deterministically and report the count. |
| `m:<lower(name)>` | **exact and total**: 0 mismatches / 905, names unique | Normalization is an exact lookup. |
| `provider.resolve_method_ids(["STAR"])` | returns `m:ea-utils, m:find, m:gedi, …` — **not** `m:star` | The fuzzy resolver **must not** be used for normalization. |
| Methods with ≥1 `PERFORMS` Operation | **415 / 905 (46%)** | Equivalence classes only exist for covered methods. |
| Methods with ≥1 `INPUT` **Data** node | **49 / 905 (5.4%)** | Equivalence degenerates to exact identity for ~95% of methods. |
| Methods with ≥1 `OUTPUT` **Data** node | **39 / 905 (4.3%)** | The validity axis will be mostly `UNKNOWN`. |
| `INPUT`/`OUTPUT` totals (3,945 / 3,935) | dominated by **Format**, not Data | `classify_handoff` excludes Format joins by design; the "7,880 typed I/O edges" figure does not translate into validity coverage. |
| Equivalence rule on real data | `m:star` and `m:hisat2` share op `op:operation_0292` **and** input Data `{data_1234, data_1255, data_2977}`; `m:bwa` shares the op but its input Data `{data_2044, data_3210}` is **disjoint** | Spec test 1 (**reject bwa for spliced alignment**) passes on real data with class = operation ∩ input-Data. |
| `m:bowtie2` | has ops but **zero** input Data nodes | Identity must be an explicit disjunct or such a method matches nothing, not even itself. |
| `snapshots/pipelines/` | **empty**; no items have ever been built | This plan is developed and tested against fixtures. Acquiring pipelines is an operational prerequisite, out of scope — see "Out of scope". |

**The load-bearing consequence:** thin Data coverage makes the metrics *conservative* — they under-credit legitimate substitutions rather than over-credit wrong answers. That is the correct failure direction for a benchmark, but the numbers are only interpretable next to a coverage report. **Task 1 therefore builds the coverage report before any metric exists**, so no metric is ever read without its denominator.

## Global Constraints

- **No new runtime dependencies.** `pyproject.toml` dependencies stay `kuzu==0.11.3`, `polars`, `pyyaml`, `networkx`. HTTP is `urllib.request`; subprocess is stdlib.
- **The scorer never imports `kuzu`.** All graph access goes through the `Oracle` protocol in `bench/oracle.py`. Metric functions are pure.
- **Determinism.** Every iteration over a set is `sorted()`. Every RNG is a seeded `random.Random`. Two runs on the same inputs produce byte-identical output.
- **`UNKNOWN` is never counted as valid.** It is reported as its own count with an explicit coverage denominator.
- **Undefined is `None`, never `0.0`.** A metric with an empty denominator returns `None`. Conflating "ordered nothing correctly" with "there was nothing to order" is the exact reporting failure this project already paid for once.
- **Nothing is dropped silently.** Unresolvable names, unparseable responses, cyclic projected edges, adapter failures — each gets a counted field in the output row.
- **Free-text output only.** Prompts never present the answer set. No methods-graph context in any prompt.
- **Temperature 0** on every adapter that exposes it.
- Test files for this module are named `tests/test_bench_*.py`. **`tests/test_adapters.py` already exists** for `extract/adapters.py` — the new adapter tests go in `tests/test_bench_adapters.py`.
- CLI entry point is `methods-graph` (the user's shell alias is `mg`).

## Out of scope

- **Acquiring the real item set.** `snapshots/pipelines/` is empty; populating it needs Nextflow, Java, network and per-release `NXF_VER` pinning across 142 pipelines. That is an operations task run after this plan lands, via `fetch_nfcore_pipeline` + `methods-graph bench build`.
- Live cuts / bioRxiv sourcing — Plan 3.
- Leaderboard hosting, fine-tuning, held-out submission server.

## File Structure

```
src/methods_graph/bench/
  oracle.py      NEW  Oracle protocol, StaticOracle (dicts), KuzuOracle (eager load), coverage report
  normalize.py   NEW  free text -> m: id; mod: -> m: projection for sequences and edges
  score.py       NEW  selection / sequencing / validity / next-step metrics + aggregation
  render.py      NEW  item -> prompt; model response -> list[str]
  adapters.py    NEW  static / claude_cli / openai; get_adapter(spec)
  run.py         MOD  add run_items(), score_rows(), summarize(); thread revision+nxf_ver
  build.py       —    unchanged
  gold.py        —    unchanged
src/methods_graph/cli.py           MOD  `bench` gains subcommands: build | coverage | run | score
tests/
  test_bench_oracle.py     NEW
  test_bench_normalize.py  NEW
  test_bench_score.py      NEW
  test_bench_render.py     NEW
  test_bench_adapters.py   NEW
  test_bench_run.py        MOD  CLI moved under `bench build`
  fixtures/bench/          NEW  two hand-written items used by the ceiling test
```

Responsibility split: `oracle.py` is the only file that knows the graph exists; `score.py` is the only file that knows what a metric is; `render.py` is the only file that knows what a prompt looks like; `run.py` wires them and owns I/O.

---

### Task 1: Oracle and coverage report

**Files:**
- Create: `src/methods_graph/bench/oracle.py`
- Test: `tests/test_bench_oracle.py`

**Interfaces:**
- Consumes: `data/methods.kuzu` (via `kuzu`), gold items from `bench/items/*.json`
- Produces:
  - `class StaticOracle` with methods `has_method(id) -> bool`, `method_for_module(id) -> str | None`, `operations(id) -> frozenset[str]`, `inputs(id) -> frozenset[str]`, `outputs(id) -> frozenset[str]`, `multi_wrapped() -> dict[str, list[str]]`
  - `class KuzuOracle(StaticOracle)` — `KuzuOracle(db_path: Path)`
  - `def coverage(oracle, module_ids: list[str]) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_oracle.py`:

```python
from methods_graph.bench.oracle import StaticOracle, coverage


def _oracle():
    return StaticOracle(
        methods=["m:star", "m:hisat2", "m:bwa", "m:bowtie2"],
        modules={
            "mod:star_align": "m:star",
            "mod:star_genomegenerate": "m:star",
            "mod:hisat2_align": "m:hisat2",
            "mod:custom_orfnormalise": "m:bwa",
        },
        operations={
            "m:star": ["op:operation_0292"],
            "m:hisat2": ["op:operation_0292"],
            "m:bwa": ["op:operation_0292", "op:operation_3198"],
            "m:bowtie2": ["op:operation_3198"],
        },
        inputs={
            "m:star": ["data:data_1234", "data:data_2977"],
            "m:hisat2": ["data:data_1234", "data:data_2977"],
            "m:bwa": ["data:data_2044"],
        },
        outputs={"m:star": ["data:data_0863"], "m:hisat2": ["data:data_0863"]},
    )


def test_module_resolves_to_method():
    assert _oracle().method_for_module("mod:star_align") == "m:star"


def test_unknown_module_is_none_not_a_guess():
    assert _oracle().method_for_module("mod:nowhere") is None


def test_missing_method_has_empty_sets_not_a_keyerror():
    oracle = _oracle()
    assert oracle.operations("m:nowhere") == frozenset()
    assert oracle.inputs("m:bowtie2") == frozenset()


def test_coverage_reports_each_denominator_separately():
    report = coverage(_oracle(), [
        "mod:star_align", "mod:hisat2_align", "mod:custom_orfnormalise", "mod:nowhere",
    ])
    assert report["n_modules"] == 4
    assert report["n_resolved"] == 3
    assert report["unresolved"] == ["mod:nowhere"]
    # m:star, m:hisat2, m:bwa all have operations; only star+hisat2 have output Data.
    assert report["n_methods"] == 3
    assert report["n_with_operations"] == 3
    assert report["n_with_input_data"] == 3
    assert report["n_with_output_data"] == 2


def test_coverage_of_empty_input_is_zero_not_a_crash():
    report = coverage(_oracle(), [])
    assert report["n_modules"] == 0
    assert report["resolved_fraction"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_oracle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.oracle'`

- [ ] **Step 3: Write the implementation**

Create `src/methods_graph/bench/oracle.py`:

```python
"""The graph, reduced to the five questions the scorer asks it.

Every metric in :mod:`methods_graph.bench.score` is a pure function over sets, and this
is the only place that knows a database exists. The scorer's tests therefore run against
:class:`StaticOracle` — no Kuzu, no fixtures on disk, no N+1 queries.

Coverage is reported, never assumed. Measured over the 905-method graph: 415 methods
carry a PERFORMS edge, 49 carry an input Data node, 39 carry an output Data node. A
metric read without its denominator is a metric misread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol


class Oracle(Protocol):
    """What the scorer needs from the graph, and nothing more."""

    def has_method(self, method_id: str) -> bool: ...
    def method_for_module(self, module_id: str) -> str | None: ...
    def operations(self, method_id: str) -> frozenset[str]: ...
    def inputs(self, method_id: str) -> frozenset[str]: ...
    def outputs(self, method_id: str) -> frozenset[str]: ...


class StaticOracle:
    """Dict-backed oracle. Holds the whole logic; :class:`KuzuOracle` only fills it."""

    def __init__(
        self,
        *,
        methods: Iterable[str],
        modules: dict[str, str] | None = None,
        operations: dict[str, Iterable[str]] | None = None,
        inputs: dict[str, Iterable[str]] | None = None,
        outputs: dict[str, Iterable[str]] | None = None,
        multi_wrapped: dict[str, list[str]] | None = None,
    ) -> None:
        self._methods = frozenset(methods)
        self._modules = dict(modules or {})
        self._operations = {k: frozenset(v) for k, v in (operations or {}).items()}
        self._inputs = {k: frozenset(v) for k, v in (inputs or {}).items()}
        self._outputs = {k: frozenset(v) for k, v in (outputs or {}).items()}
        self._multi_wrapped = dict(multi_wrapped or {})

    def has_method(self, method_id: str) -> bool:
        return method_id in self._methods

    def method_for_module(self, module_id: str) -> str | None:
        """The method a module wraps, or ``None`` — never a guess."""
        return self._modules.get(module_id)

    def operations(self, method_id: str) -> frozenset[str]:
        return self._operations.get(method_id, frozenset())

    def inputs(self, method_id: str) -> frozenset[str]:
        return self._inputs.get(method_id, frozenset())

    def outputs(self, method_id: str) -> frozenset[str]:
        return self._outputs.get(method_id, frozenset())

    def multi_wrapped(self) -> dict[str, list[str]]:
        """Modules wrapping more than one method, with every candidate.

        ``mod:custom_orfnormalise`` wraps six. :meth:`method_for_module` returns the
        lexicographically first so the answer key is deterministic; this exposes what
        that choice discarded rather than hiding it behind the determinism.
        """
        return dict(self._multi_wrapped)


class KuzuOracle(StaticOracle):
    """Load the whole oracle in five queries, then answer from memory.

    Eager, not lazy: the scorer touches most of the graph anyway, and the per-method
    N+1 pattern in ``KuzuMethodsGraphProvider.get_methods`` is exactly what a scoring
    loop over thousands of items must not repeat.
    """

    def __init__(self, db_path: Path) -> None:
        import kuzu

        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        try:
            methods = [r[0] for r in conn.execute(
                "MATCH (m:Entity {kind:'Method'}) RETURN m.id ORDER BY m.id")]

            modules: dict[str, str] = {}
            candidates: dict[str, list[str]] = {}
            for module_id, method_id in conn.execute(
                    "MATCH (mo:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->"
                    "(me:Entity {kind:'Method'}) "
                    "RETURN mo.id, me.id ORDER BY mo.id, me.id"):
                modules.setdefault(module_id, method_id)
                candidates.setdefault(module_id, []).append(method_id)

            operations: dict[str, list[str]] = {}
            for method_id, op_id in conn.execute(
                    "MATCH (m:Entity {kind:'Method'})-[:Rel {kind:'PERFORMS'}]->(o:Entity) "
                    "RETURN m.id, o.id ORDER BY m.id, o.id"):
                operations.setdefault(method_id, []).append(op_id)

            io: dict[str, dict[str, list[str]]] = {"INPUT": {}, "OUTPUT": {}}
            for edge_kind in ("INPUT", "OUTPUT"):
                for method_id, data_id in conn.execute(
                        "MATCH (m:Entity {kind:'Method'})-[:Rel {kind: $k}]->"
                        "(d:Entity {kind:'Data'}) "
                        "RETURN m.id, d.id ORDER BY m.id, d.id",
                        {"k": edge_kind}):
                    io[edge_kind].setdefault(method_id, []).append(data_id)
        finally:
            conn.close()
            db.close()

        super().__init__(
            methods=methods,
            modules=modules,
            operations=operations,
            inputs=io["INPUT"],
            outputs=io["OUTPUT"],
            multi_wrapped={k: v for k, v in candidates.items() if len(v) > 1},
        )


def coverage(oracle: Oracle, module_ids: list[str]) -> dict[str, Any]:
    """How much of the graph's oracle actually backs *module_ids*.

    Both halves matter and neither substitutes for the other: how many gold steps reach
    a method at all, and how many of those methods carry the edges the metrics read.
    """
    unique_modules = sorted(set(module_ids))
    resolved = {m: oracle.method_for_module(m) for m in unique_modules}
    unresolved = sorted(m for m, method in resolved.items() if method is None)
    methods = sorted({method for method in resolved.values() if method})

    return {
        "n_modules": len(unique_modules),
        "n_resolved": len(unique_modules) - len(unresolved),
        "resolved_fraction": (
            None if not unique_modules
            else (len(unique_modules) - len(unresolved)) / len(unique_modules)),
        "unresolved": unresolved,
        "n_methods": len(methods),
        "n_with_operations": sum(1 for m in methods if oracle.operations(m)),
        "n_with_input_data": sum(1 for m in methods if oracle.inputs(m)),
        "n_with_output_data": sum(1 for m in methods if oracle.outputs(m)),
        "methods": methods,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_oracle.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/oracle.py tests/test_bench_oracle.py
git commit -m "feat(bench): oracle seam over the graph, with a coverage report"
```

---

### Task 2: Normalization and mod→m projection

**Files:**
- Create: `src/methods_graph/bench/normalize.py`
- Test: `tests/test_bench_normalize.py`

**Interfaces:**
- Consumes: `Oracle` from Task 1
- Produces:
  - `def normalize_name(text: str, oracle) -> str | None`
  - `def normalize_answer(names: list[str], oracle) -> tuple[list[str], list[str]]` → `(method_ids, unresolved_names)`
  - `def project_sequence(module_ids: list[str], oracle) -> tuple[list[str], list[str]]` → `(method_ids, unresolved_modules)`
  - `def project_edges(edges, module_ids, oracle) -> tuple[list[tuple[str, str]], int]` → `(method_edges, n_dropped_cyclic)`

**Why projection exists:** gold sequences are `mod:` ids; the oracle keys on `m:` ids; models answer with tool names. Method space is the only space all three can meet in. Collapsing `mod:star_genomegenerate` and `mod:star_align` onto `m:star` is not a loss — a model should not have to know nf-core splits STAR into index and align.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_normalize.py`:

```python
import pytest

from methods_graph.bench.normalize import (
    normalize_answer, normalize_name, project_edges, project_sequence)
from methods_graph.bench.oracle import StaticOracle


def _oracle():
    return StaticOracle(
        methods=["m:star", "m:trimgalore", "m:bwamem2", "m:bwa", "m:deseq2",
                 "m:ea-utils", "m:salmon", "m:samtools"],
        modules={
            "mod:star_genomegenerate": "m:star",
            "mod:star_align": "m:star",
            "mod:samtools_sort": "m:samtools",
            "mod:salmon_quant": "m:salmon",
            "mod:deseq2_differential": "m:deseq2",
        },
    )


@pytest.mark.parametrize("text,expected", [
    ("star", "m:star"),
    ("STAR", "m:star"),
    ("  DESeq2  ", "m:deseq2"),
    ("Trim Galore", "m:trimgalore"),      # punctuation+space compaction
    ("Trim Galore!", "m:trimgalore"),
    ("BWA-MEM2", "m:bwamem2"),
    ("ea utils", "m:ea-utils"),           # hyphen reconstruction
    ("m:star", "m:star"),                 # already an id
    ("bwa mem", "m:bwa"),                 # curated alias
])
def test_names_resolve_exactly(text, expected):
    assert normalize_name(text, _oracle()) == expected


@pytest.mark.parametrize("text", ["", "   ", "some tool I invented", "aligner"])
def test_unresolvable_names_return_none(text):
    assert normalize_name(text, _oracle()) is None


def test_answer_keeps_order_dedupes_and_reports_unresolved():
    ids, unresolved = normalize_answer(
        ["STAR", "salmon", "STAR", "MyAligner", "DESeq2"], _oracle())
    assert ids == ["m:star", "m:salmon", "m:deseq2"]
    assert unresolved == ["MyAligner"]


def test_projection_collapses_two_modules_of_one_tool():
    seq, unresolved = project_sequence(
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant"], _oracle())
    assert seq == ["m:star", "m:salmon"]
    assert unresolved == []


def test_projection_reports_unresolvable_modules_rather_than_dropping_them_quietly():
    seq, unresolved = project_sequence(
        ["mod:star_align", "mod:some_local_process"], _oracle())
    assert seq == ["m:star"]
    assert unresolved == ["mod:some_local_process"]


def test_projected_edges_drop_self_loops_from_the_collapse():
    edges, n_cyclic = project_edges(
        [("mod:star_genomegenerate", "mod:star_align"),
         ("mod:star_align", "mod:salmon_quant")],
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant"],
        _oracle())
    assert edges == [("m:star", "m:salmon")]
    assert n_cyclic == 0


def test_projected_edges_drop_contradictions_the_collapse_created_and_count_them():
    # star -> salmon -> star in module space becomes a 2-cycle once collapsed.
    edges, n_cyclic = project_edges(
        [("mod:star_genomegenerate", "mod:salmon_quant"),
         ("mod:salmon_quant", "mod:star_align")],
        ["mod:star_genomegenerate", "mod:salmon_quant", "mod:star_align"],
        _oracle())
    assert edges == [("m:star", "m:salmon")]
    assert n_cyclic == 1


def test_projected_edges_are_sorted_and_deduped():
    edges, _ = project_edges(
        [("mod:star_align", "mod:salmon_quant"),
         ("mod:star_genomegenerate", "mod:salmon_quant"),
         ("mod:salmon_quant", "mod:deseq2_differential")],
        ["mod:star_genomegenerate", "mod:star_align", "mod:salmon_quant",
         "mod:deseq2_differential"],
        _oracle())
    assert edges == [("m:salmon", "m:deseq2"), ("m:star", "m:salmon")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.normalize'`

- [ ] **Step 3: Write the implementation**

Create `src/methods_graph/bench/normalize.py`:

```python
"""Three vocabularies, one comparison space.

Gold speaks ``mod:`` module ids, the oracle speaks ``m:`` method ids, and models speak
English. Everything is resolved into method space here so the metrics never have to
know which vocabulary a name arrived in.

Resolution is EXACT, deliberately. ``m:<lowercased name>`` holds for all 905 methods
with no exceptions and no collisions, so an exact lookup is both sufficient and safe.
The graph's fuzzy resolver is not used: ``resolve_method_ids(["STAR"])`` returns
``m:ea-utils``, ``m:find`` and ``m:gedi`` before it returns ``m:star``, and a normalizer
that guesses would score models on the guess.
"""
from __future__ import annotations

import re

from methods_graph.bench.oracle import Oracle

# Names whose canonical form is not recoverable by punctuation stripping alone. Every
# entry must name a method the graph actually carries; ``normalize_name`` re-checks
# against the oracle, so a stale alias degrades to "unresolved" rather than to a wrong id.
_ALIASES = {
    "bwa mem": "bwa",
    "bwa aln": "bwa",
    "bwa-mem": "bwa",
    "trim galore": "trimgalore",
    "cut adapt": "cutadapt",
    "star aligner": "star",
    "samtools sort": "samtools",
    "samtools index": "samtools",
    "picard markduplicates": "picard",
    "gatk haplotypecaller": "gatk4",
    "deseq": "deseq2",
}


def _candidates(text: str) -> list[str]:
    """Canonical-form candidates for a free-text tool name, most literal first."""
    stripped = text.strip().lower()
    if stripped.startswith("m:"):
        stripped = stripped[2:]
    if not stripped:
        return []

    spaced = re.sub(r"[^a-z0-9]+", " ", stripped).strip()
    out = [stripped]
    if spaced in _ALIASES:
        out.append(_ALIASES[spaced])
    # "Trim Galore!" -> "trimgalore"; "BWA-MEM2" -> "bwamem2"
    out.append(spaced.replace(" ", ""))
    # "ea utils" -> "ea-utils"
    out.append(spaced.replace(" ", "-"))
    return [c for c in out if c]


def normalize_name(text: str, oracle: Oracle) -> str | None:
    """A free-text tool name as an ``m:`` id, or ``None`` if the graph has no such tool."""
    for candidate in _candidates(text):
        method_id = f"m:{candidate}"
        if oracle.has_method(method_id):
            return method_id
    return None


def normalize_answer(
    names: list[str], oracle: Oracle,
) -> tuple[list[str], list[str]]:
    """A model's answer as ordered, deduped method ids plus the names that did not resolve.

    Unresolved names are RETURNED, not dropped: silently discarding them would let a
    model that names five imaginary tools and one real one score like a model that
    named one tool.
    """
    ids: list[str] = []
    unresolved: list[str] = []
    for name in names:
        method_id = normalize_name(name, oracle)
        if method_id is None:
            if name not in unresolved:
                unresolved.append(name)
        elif method_id not in ids:
            ids.append(method_id)
    return ids, unresolved


def project_sequence(
    module_ids: list[str], oracle: Oracle,
) -> tuple[list[str], list[str]]:
    """Gold ``mod:`` ids as ordered, deduped ``m:`` ids, plus the modules with no method.

    Deduping is the point, not a side effect: ``star_genomegenerate`` then ``star_align``
    is one tool choice, and asking a model to name it twice measures nf-core familiarity.
    """
    sequence: list[str] = []
    unresolved: list[str] = []
    for module_id in module_ids:
        method_id = oracle.method_for_module(module_id)
        if method_id is None:
            if module_id not in unresolved:
                unresolved.append(module_id)
        elif method_id not in sequence:
            sequence.append(method_id)
    return sequence, unresolved


def project_edges(
    edges: list[tuple[str, str]] | list[list[str]],
    module_ids: list[str],
    oracle: Oracle,
) -> tuple[list[tuple[str, str]], int]:
    """Gold precedence edges projected into method space, kept acyclic.

    Collapsing can manufacture a contradiction the DAG never contained: if A precedes B
    precedes C and A and C are the same tool, method space gets ``X -> Y`` and
    ``Y -> X``. Those edges are resolved against the projected sequence's order — which
    came from a topological sort of the uncollapsed DAG — and the discarded count is
    returned so the loss is visible rather than inferred.
    """
    sequence, _ = project_sequence(module_ids, oracle)
    position = {method_id: index for index, method_id in enumerate(sequence)}

    kept: set[tuple[str, str]] = set()
    dropped_cyclic = 0
    for source, target in edges:
        from_id = oracle.method_for_module(source)
        to_id = oracle.method_for_module(target)
        if from_id is None or to_id is None or from_id == to_id:
            continue
        if from_id not in position or to_id not in position:
            continue
        if position[from_id] < position[to_id]:
            kept.add((from_id, to_id))
        else:
            dropped_cyclic += 1
    return sorted(kept), dropped_cyclic
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_normalize.py -v`
Expected: PASS (all parametrized cases)

- [ ] **Step 5: Add the alias-integrity test**

Append to `tests/test_bench_normalize.py`:

```python
from pathlib import Path

from methods_graph.bench.normalize import _ALIASES
from methods_graph.bench.oracle import KuzuOracle

_DB = Path("data/methods.kuzu")


@pytest.mark.skipif(not _DB.exists(), reason="built graph not present")
def test_every_alias_names_a_method_the_graph_actually_has():
    oracle = KuzuOracle(_DB)
    missing = sorted(t for t in set(_ALIASES.values()) if not oracle.has_method(f"m:{t}"))
    assert missing == [], f"aliases pointing at non-existent methods: {missing}"
```

- [ ] **Step 6: Run it and remove any alias that fails**

Run: `.venv/bin/python -m pytest tests/test_bench_normalize.py -v`
Expected: PASS. If `cutadapt`, `picard` or `gatk4` are absent from the graph, **delete those alias rows** — do not invent a substitute id.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/bench/normalize.py tests/test_bench_normalize.py
git commit -m "feat(bench): normalize free-text names and project gold onto method space"
```

---

### Task 3: Selection metric

**Files:**
- Create: `src/methods_graph/bench/score.py`
- Test: `tests/test_bench_score.py`

**Interfaces:**
- Consumes: `Oracle` (Task 1)
- Produces:
  - `def same_class(a: str, b: str, oracle) -> bool`
  - `def match_steps(gold: list[str], pred: list[str], oracle) -> dict[str, str]` (gold id → matched pred id)
  - `def score_selection(gold, pred, oracle) -> dict[str, Any]`

**Equivalence class = operation ∩ input Data, with identity as an explicit disjunct.** Operation alone is too coarse (it credits `bwa` for spliced RNA alignment). Identity must be separate because 856 of 905 methods carry no input Data at all — without it, `m:bowtie2` would fail to match itself.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_score.py`:

```python
from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.score import match_steps, same_class, score_selection


def _oracle():
    """Mirrors the real graph: star/hisat2 share op AND input Data; bwa shares only op."""
    return StaticOracle(
        methods=["m:star", "m:hisat2", "m:bwa", "m:bowtie2", "m:salmon", "m:deseq2",
                 "m:fastqc"],
        operations={
            "m:star": ["op:operation_0292"],
            "m:hisat2": ["op:operation_0292"],
            "m:bwa": ["op:operation_0292", "op:operation_3198"],
            "m:bowtie2": ["op:operation_3198"],
            "m:salmon": ["op:operation_3800"],
            "m:deseq2": ["op:operation_3223"],
            "m:fastqc": ["op:operation_3218"],
        },
        inputs={
            "m:star": ["data:data_1234", "data:data_2977"],
            "m:hisat2": ["data:data_1234", "data:data_2977"],
            "m:bwa": ["data:data_2044", "data:data_3210"],
            "m:salmon": ["data:data_1234"],
            "m:deseq2": ["data:data_3917"],
            "m:fastqc": ["data:data_1234"],
        },
    )


def test_hisat2_is_credited_for_star():
    assert same_class("m:star", "m:hisat2", _oracle()) is True


def test_bwa_is_not_credited_for_spliced_alignment():
    oracle = _oracle()
    # The two DO share an operation — this is what an operation-only class would credit.
    assert oracle.operations("m:star") & oracle.operations("m:bwa")
    # Adding the input-data requirement is what rejects it.
    assert same_class("m:star", "m:bwa", oracle) is False


def test_a_method_with_no_curated_input_data_still_matches_itself():
    assert same_class("m:bowtie2", "m:bowtie2", _oracle()) is True


def test_a_method_with_no_curated_input_data_matches_nothing_else():
    assert same_class("m:bowtie2", "m:bwa", _oracle()) is False


def test_unrelated_tools_do_not_match():
    assert same_class("m:deseq2", "m:fastqc", _oracle()) is False


def test_perfect_answer_scores_one():
    gold = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    result = score_selection(gold, list(gold), _oracle())
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_equivalent_substitution_scores_one():
    result = score_selection(["m:star"], ["m:hisat2"], _oracle())
    assert result["f1"] == 1.0
    assert result["matched"] == {"m:star": "m:hisat2"}


def test_one_predicted_tool_cannot_satisfy_two_gold_steps():
    # Matching is one-to-one: hisat2 covers star, but nothing covers salmon.
    result = score_selection(["m:star", "m:salmon"], ["m:hisat2"], _oracle())
    assert result["recall"] == 0.5
    assert result["precision"] == 1.0


def test_matching_is_maximum_not_greedy():
    # Greedy left-to-right would bind hisat2 to star, leaving nothing for hisat2's own
    # gold slot. A maximum matching finds both.
    gold = ["m:star", "m:hisat2"]
    pred = ["m:hisat2", "m:star"]
    assert len(match_steps(gold, pred, _oracle())) == 2


def test_extra_predictions_cost_precision_not_recall():
    result = score_selection(["m:star"], ["m:star", "m:deseq2", "m:fastqc"], _oracle())
    assert result["recall"] == 1.0
    assert result["precision"] == 1.0 / 3


def test_empty_prediction_scores_zero_without_dividing_by_zero():
    result = score_selection(["m:star"], [], _oracle())
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.score'`

- [ ] **Step 3: Write the implementation**

Create `src/methods_graph/bench/score.py`:

```python
"""Three numbers, deliberately separate: did it pick, did it order, does it run.

A single accuracy figure hides both interesting failures — a model that knows every
tool and orders them wrongly, and a model that names the right tools in an unrunnable
order. Each metric returns ``None`` when its denominator is empty; ``0.0`` would claim a
measurement that was never made.
"""
from __future__ import annotations

from typing import Any

from methods_graph.bench.oracle import Oracle


def same_class(a: str, b: str, oracle: Oracle) -> bool:
    """Are these two methods interchangeable for the benchmark's purposes?

    Class = shared EDAM operation AND shared input data type. Operation alone is too
    coarse: ``bwa`` and ``STAR`` both perform *Sequence alignment*, but ``bwa`` accepts
    ``Sequence``/``Genome index`` while ``STAR`` accepts ``Sequence set (nucleic acid)``,
    so operation-only equivalence would credit an unspliced aligner for spliced RNA
    alignment.

    Identity is a separate disjunct because input Data is curated for only 49 of 905
    methods — without it a method with no curated inputs would fail to match itself.
    """
    if a == b:
        return True
    if not (oracle.operations(a) & oracle.operations(b)):
        return False
    return bool(oracle.inputs(a) & oracle.inputs(b))


def match_steps(
    gold: list[str], pred: list[str], oracle: Oracle,
) -> dict[str, str]:
    """Maximum one-to-one matching of gold steps to predicted steps.

    Maximum, not greedy: equivalence is not transitive and not a partition, so a greedy
    left-to-right pass can bind a predicted tool to the first gold step it fits and
    strand a later gold step that only that tool could have covered. Kuhn's augmenting
    path, with both sides iterated in their given order, is deterministic.
    """
    adjacency = {g: [p for p in pred if same_class(g, p, oracle)] for g in gold}
    owner: dict[str, str] = {}  # predicted id -> gold id currently holding it

    def _augment(g: str, seen: set[str]) -> bool:
        for p in adjacency[g]:
            if p in seen:
                continue
            seen.add(p)
            if p not in owner or _augment(owner[p], seen):
                owner[p] = g
                return True
        return False

    for g in gold:
        _augment(g, set())
    return {g: p for p, g in owner.items()}


def score_selection(
    gold: list[str], pred: list[str], oracle: Oracle,
) -> dict[str, Any]:
    """Which methods — step-set F1, order ignored, equivalence classes applied."""
    matched = match_steps(gold, pred, oracle)
    true_positives = len(matched)
    precision = true_positives / len(pred) if pred else 0.0
    recall = true_positives / len(gold) if gold else 0.0
    denominator = precision + recall
    return {
        "precision": precision,
        "recall": recall,
        "f1": 0.0 if denominator == 0 else 2 * precision * recall / denominator,
        "n_gold": len(gold),
        "n_pred": len(pred),
        "n_matched": true_positives,
        "matched": matched,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/score.py tests/test_bench_score.py
git commit -m "feat(bench): selection metric with operation+input-type equivalence classes"
```

---

### Task 4: Sequencing metric

**Files:**
- Modify: `src/methods_graph/bench/score.py`
- Test: `tests/test_bench_score.py`

**Interfaces:**
- Consumes: `match_steps` (Task 3), projected gold edges (Task 2)
- Produces: `def score_sequencing(gold_edges, matched, pred) -> dict[str, Any]`

Takes no oracle: equivalence was already resolved into `matched` by Task 3, so this is
pure list-and-set arithmetic.

**Scores edges, not adjacent pairs.** Two steps on parallel branches land adjacent in any linearization though nothing orders them; scoring the linearization marks a correct answer wrong. `gold["edges"]` was frozen in Plan 1 for exactly this.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_score.py`:

```python
from methods_graph.bench.score import score_sequencing


def test_correct_order_scores_one():
    gold_edges = [("m:fastqc", "m:star"), ("m:star", "m:salmon"),
                  ("m:salmon", "m:deseq2")]
    pred = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    matched = match_steps(["m:fastqc", "m:star", "m:salmon", "m:deseq2"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_reversed_order_scores_zero():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:salmon", "m:star"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 0.0


def test_parallel_branches_are_not_penalized():
    # fastqc and star are both required before salmon, but nothing orders them relative
    # to each other. Either interleaving must score 1.0.
    gold_edges = [("m:fastqc", "m:salmon"), ("m:star", "m:salmon")]
    gold = ["m:fastqc", "m:star", "m:salmon"]
    for pred in (["m:fastqc", "m:star", "m:salmon"], ["m:star", "m:fastqc", "m:salmon"]):
        matched = match_steps(gold, pred, _oracle())
        assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_order_metric_is_independent_of_naming_errors():
    # Two of four steps are wrong; the ordering of the two correct ones is perfect.
    gold_edges = [("m:fastqc", "m:star"), ("m:star", "m:salmon"),
                  ("m:salmon", "m:deseq2")]
    gold = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    pred = ["m:star", "m:salmon"]
    matched = match_steps(gold, pred, _oracle())
    result = score_sequencing(gold_edges, matched, pred)
    assert result["n_scorable"] == 1        # only star->salmon has both ends matched
    assert result["score"] == 1.0


def test_equivalent_substitution_keeps_its_position():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:hisat2", "m:salmon"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    assert score_sequencing(gold_edges, matched, pred)["score"] == 1.0


def test_no_scorable_edges_is_none_not_zero():
    gold_edges = [("m:star", "m:salmon")]
    pred = ["m:deseq2"]
    matched = match_steps(["m:star", "m:salmon"], pred, _oracle())
    result = score_sequencing(gold_edges, matched, pred)
    assert result["score"] is None
    assert result["n_scorable"] == 0


def test_one_prediction_covering_both_ends_of_an_edge_is_not_credited():
    # Nothing can precede itself; a single predicted tool matched to both endpoints
    # supplies no ordering evidence.
    gold_edges = [("m:star", "m:hisat2")]
    matched = {"m:star": "m:star", "m:hisat2": "m:star"}
    result = score_sequencing(gold_edges, matched, ["m:star"])
    assert result["score"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -k sequencing -v`
Expected: FAIL with `ImportError: cannot import name 'score_sequencing'`

- [ ] **Step 3: Write the implementation**

Append to `src/methods_graph/bench/score.py`:

```python
def score_sequencing(
    gold_edges: list[tuple[str, str]] | list[list[str]],
    matched: dict[str, str],
    pred: list[str],
) -> dict[str, Any]:
    """What order — the fraction of REQUIRED precedences the answer respects.

    Scores the DAG's edges, never the gold sequence's adjacent pairs. Linearizing a DAG
    puts parallel branches next to each other though nothing orders them, so an
    adjacency metric marks a correct interleaving wrong. Only edges whose BOTH endpoints
    were selected are scorable, which is what makes this independent of the selection
    score rather than a second copy of it.
    """
    position = {method_id: index for index, method_id in enumerate(pred)}
    scorable = [
        (source, target) for source, target in gold_edges
        if source in matched and target in matched
    ]
    if not scorable:
        return {"score": None, "n_scorable": 0, "n_respected": 0,
                "n_gold_edges": len(gold_edges)}

    respected = sum(
        1 for source, target in scorable
        if position[matched[source]] < position[matched[target]]
    )
    return {
        "score": respected / len(scorable),
        "n_scorable": len(scorable),
        "n_respected": respected,
        "n_gold_edges": len(gold_edges),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/score.py tests/test_bench_score.py
git commit -m "feat(bench): sequencing metric over gold DAG edges, not the linearization"
```

---

### Task 5: Validity metric

**Files:**
- Modify: `src/methods_graph/bench/score.py`
- Test: `tests/test_bench_score.py`

**Interfaces:**
- Consumes: `classify_handoff` from `methods_graph.guardrail`
- Produces: `def score_validity(pred: list[str], oracle) -> dict[str, Any]`

**Coverage is thin and must be reported.** Only 39 methods carry output Data and 49 carry input Data, so most consecutive pairs will be `UNKNOWN`. The metric therefore ships with an explicit `coverage` field; a validity score read without it is meaningless.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_score.py`:

```python
from methods_graph.bench.score import score_validity


def _io_oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:salmon", "m:deseq2", "m:bowtie2"],
        outputs={
            "m:fastqc": ["data:data_2955"],
            "m:star": ["data:data_0863"],       # Sequence alignment
            "m:salmon": ["data:data_3917"],     # Count matrix
        },
        inputs={
            "m:star": ["data:data_1234"],
            "m:salmon": ["data:data_0863"],     # consumes an alignment
            "m:deseq2": ["data:data_3917"],     # consumes a count matrix
        },
    )


def test_typechecking_handoffs_score_one():
    result = score_validity(["m:star", "m:salmon", "m:deseq2"], _io_oracle())
    assert result["score"] == 1.0
    assert result["n_valid"] == 2
    assert result["n_broken"] == 0


def test_disjoint_handoff_is_broken():
    result = score_validity(["m:star", "m:deseq2"], _io_oracle())
    assert result["n_broken"] == 1
    assert result["score"] == 0.0


def test_unknown_is_never_counted_as_valid():
    # bowtie2 has no curated I/O at all — both its pairs are unverifiable.
    result = score_validity(["m:star", "m:bowtie2", "m:deseq2"], _io_oracle())
    assert result["n_unknown"] == 2
    assert result["n_valid"] == 0
    assert result["score"] is None


def test_coverage_reports_how_much_of_the_answer_was_checkable():
    result = score_validity(["m:star", "m:salmon", "m:bowtie2"], _io_oracle())
    assert result["n_pairs"] == 2
    assert result["n_unknown"] == 1
    assert result["coverage"] == 0.5
    assert result["score"] == 1.0     # the one checkable pair was valid


def test_single_step_answer_has_no_pairs():
    result = score_validity(["m:star"], _io_oracle())
    assert result["n_pairs"] == 0
    assert result["score"] is None
    assert result["coverage"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -k validity -v`
Expected: FAIL with `ImportError: cannot import name 'score_validity'`

- [ ] **Step 3: Write the implementation**

Append to `src/methods_graph/bench/score.py` (and add the import at the top of the file):

```python
from methods_graph.guardrail import (
    HANDOFF_BROKEN, HANDOFF_UNKNOWN, HANDOFF_VALID, classify_handoff)


def score_validity(pred: list[str], oracle: Oracle) -> dict[str, Any]:
    """Does it run — the share of consecutive handoffs whose data types meet.

    ``UNKNOWN`` (a step with no curated Data I/O) is excluded from the score's
    denominator and reported as its own count. Folding it into "valid" would inflate the
    number with ignorance, and folding it into "invalid" would punish a correct answer
    for a curation gap. ``coverage`` says how much of the answer was checkable at all —
    with output Data curated for 39 of 905 methods, that caveat is the headline, not a
    footnote.
    """
    pairs: list[dict[str, Any]] = []
    counts = {HANDOFF_VALID: 0, HANDOFF_BROKEN: 0, HANDOFF_UNKNOWN: 0}
    for producer, consumer in zip(pred, pred[1:]):
        result, shared = classify_handoff(
            set(oracle.outputs(producer)), set(oracle.inputs(consumer)))
        counts[result] += 1
        pairs.append({"from": producer, "to": consumer,
                      "result": result, "shared": shared})

    classified = counts[HANDOFF_VALID] + counts[HANDOFF_BROKEN]
    return {
        "score": counts[HANDOFF_VALID] / classified if classified else None,
        "n_pairs": len(pairs),
        "n_valid": counts[HANDOFF_VALID],
        "n_broken": counts[HANDOFF_BROKEN],
        "n_unknown": counts[HANDOFF_UNKNOWN],
        "coverage": classified / len(pairs) if pairs else None,
        "pairs": pairs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/score.py tests/test_bench_score.py
git commit -m "feat(bench): validity metric with UNKNOWN reported separately from valid"
```

---

### Task 6: Next-step scoring, stratified by position

**Files:**
- Modify: `src/methods_graph/bench/score.py`
- Test: `tests/test_bench_score.py`

**Interfaces:**
- Consumes: `same_class` (Task 3)
- Produces:
  - `def score_next_step(gold_next: str, ranked: list[str], oracle, k: int = 3) -> dict[str, Any]`
  - `def position_bucket(n_given: int) -> str`
  - `def aggregate_next_step(rows: list[dict[str, Any]]) -> dict[str, Any]`

**Why stratify:** index 0 (`given == []`) is "name the first step of a bioinformatics pipeline" — nearly always a QC tool, and by far the easiest item in the set. Pooling it with the rest inflates the headline. It gets its own bucket and is excluded from the headline average.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_score.py`:

```python
from methods_graph.bench.score import (
    aggregate_next_step, position_bucket, score_next_step)


def test_exact_next_step_is_top1():
    result = score_next_step("m:salmon", ["m:salmon", "m:deseq2"], _oracle())
    assert result["top1"] is True
    assert result["topk"] is True


def test_equivalent_next_step_is_top1():
    result = score_next_step("m:star", ["m:hisat2"], _oracle())
    assert result["top1"] is True


def test_right_answer_ranked_second_is_topk_not_top1():
    result = score_next_step("m:deseq2", ["m:salmon", "m:deseq2"], _oracle())
    assert result["top1"] is False
    assert result["topk"] is True


def test_right_answer_ranked_fourth_is_outside_k():
    ranked = ["m:fastqc", "m:star", "m:salmon", "m:deseq2"]
    assert score_next_step("m:deseq2", ranked, _oracle(), k=3)["topk"] is False


def test_empty_answer_scores_false_not_an_error():
    result = score_next_step("m:star", [], _oracle())
    assert result["top1"] is False
    assert result["topk"] is False


def test_position_buckets():
    assert position_bucket(0) == "0"
    assert position_bucket(1) == "1-2"
    assert position_bucket(2) == "1-2"
    assert position_bucket(3) == "3-5"
    assert position_bucket(5) == "3-5"
    assert position_bucket(6) == "6+"
    assert position_bucket(40) == "6+"


def test_headline_excludes_the_first_step_bucket():
    rows = [
        {"n_given": 0, "top1": True, "topk": True},    # trivially easy
        {"n_given": 0, "top1": True, "topk": True},
        {"n_given": 1, "top1": False, "topk": True},
        {"n_given": 4, "top1": True, "topk": True},
    ]
    result = aggregate_next_step(rows)
    assert result["by_bucket"]["0"]["top1"] == 1.0
    assert result["by_bucket"]["1-2"]["top1"] == 0.0
    assert result["by_bucket"]["3-5"]["top1"] == 1.0
    # Macro-mean over non-zero buckets: (0.0 + 1.0) / 2 — NOT the pooled 0.75.
    assert result["headline_top1"] == 0.5
    assert result["pooled_top1"] == 0.75


def test_headline_is_none_when_only_first_step_items_exist():
    result = aggregate_next_step([{"n_given": 0, "top1": True, "topk": True}])
    assert result["headline_top1"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -k next_step -v`
Expected: FAIL with `ImportError: cannot import name 'score_next_step'`

- [ ] **Step 3: Write the implementation**

Append to `src/methods_graph/bench/score.py`:

```python
# Position buckets for next-step items, by how many steps were already given. "0" is
# broken out because "name the first step" is nearly always a QC tool and is the easiest
# item in the set; pooling it with the rest inflates the headline.
_BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (0, 0, "0"), (1, 2, "1-2"), (3, 5, "3-5"), (6, None, "6+"),
)
_FIRST_STEP_BUCKET = "0"


def score_next_step(
    gold_next: str, ranked: list[str], oracle: Oracle, k: int = 3,
) -> dict[str, Any]:
    """One next-step item: is the gold step (or its equivalent) ranked first, or in top-k?"""
    return {
        "top1": bool(ranked) and same_class(gold_next, ranked[0], oracle),
        "topk": any(same_class(gold_next, candidate, oracle) for candidate in ranked[:k]),
        "k": k,
    }


def position_bucket(n_given: int) -> str:
    """Which difficulty bucket a next-step item falls in, by prefix length."""
    for low, high, label in _BUCKETS:
        if n_given >= low and (high is None or n_given <= high):
            return label
    raise ValueError(f"no bucket for n_given={n_given}")  # pragma: no cover - total


def aggregate_next_step(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Next-step accuracy by position bucket, plus a headline that skips the free one.

    The headline is a macro-mean over the non-trivial buckets: pooling weights the
    benchmark by pipeline length, so long pipelines would quietly dominate, and the
    first-step bucket would lift every model's number by the same free amount.
    """
    by_bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_bucket.setdefault(
            position_bucket(row["n_given"]), {"n": 0, "top1": 0, "topk": 0})
        bucket["n"] += 1
        bucket["top1"] += int(row["top1"])
        bucket["topk"] += int(row["topk"])

    for bucket in by_bucket.values():
        bucket["top1"] = bucket["top1"] / bucket["n"]
        bucket["topk"] = bucket["topk"] / bucket["n"]

    scored = [v for label, v in sorted(by_bucket.items()) if label != _FIRST_STEP_BUCKET]
    return {
        "n": len(rows),
        "by_bucket": by_bucket,
        "headline_top1": (
            None if not scored else sum(b["top1"] for b in scored) / len(scored)),
        "headline_topk": (
            None if not scored else sum(b["topk"] for b in scored) / len(scored)),
        "pooled_top1": (
            None if not rows else sum(int(r["top1"]) for r in rows) / len(rows)),
        "pooled_topk": (
            None if not rows else sum(int(r["topk"]) for r in rows) / len(rows)),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/score.py tests/test_bench_score.py
git commit -m "feat(bench): next-step scoring stratified by prefix length"
```

---

### Task 7: Prompt rendering and response parsing

**Files:**
- Create: `src/methods_graph/bench/render.py`
- Test: `tests/test_bench_render.py`

**Interfaces:**
- Consumes: items from Task 1 of the previous plan (`bench/items/*.json`), `Oracle`
- Produces:
  - `def render_prompt(item: dict, oracle) -> str`
  - `def parse_tool_list(raw: str) -> list[str]`

**Two deliberate deviations from the spec's §2 prompt text, both forced by the scoring design:**
1. Spec says next-step returns "the single next tool". Top-3 scoring needs a ranked list, so the prompt asks for **up to 3, best first**. Top-1 still reads element 0.
2. `given` is stored as `mod:` ids. Rendering `mod:star_align` into a prompt leaks nf-core naming into the question. `given` is rendered as **method names** (`star`), falling back to the bare module name only when the module resolves to no method.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_render.py`:

```python
import pytest

from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.render import parse_tool_list, render_prompt


def _oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:salmon"],
        modules={"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                 "mod:salmon_quant": "m:salmon"},
    )


def _whole_item():
    return {
        "id": "rnaseq/whole/001", "task": "whole_pipeline",
        "goal": "Bulk RNA-seq differential expression from paired-end human FASTQ",
        "given": [],
        "gold": {"sequence": ["mod:fastqc", "mod:star_align", "mod:salmon_quant"]},
    }


def _next_item(given):
    return {"id": "rnaseq/next/002", "task": "next_step", "goal": "Bulk RNA-seq",
            "given": given, "gold": {"next": "mod:salmon_quant"}}


def test_whole_pipeline_prompt_states_the_goal_and_asks_for_a_json_array():
    prompt = render_prompt(_whole_item(), _oracle())
    assert "Bulk RNA-seq differential expression" in prompt
    assert "JSON array" in prompt


def test_prompt_never_leaks_the_answer():
    prompt = render_prompt(_whole_item(), _oracle())
    for leaked in ("star", "salmon", "fastqc", "mod:"):
        assert leaked not in prompt.lower()


def test_next_step_prompt_renders_given_as_tool_names_not_module_ids():
    prompt = render_prompt(_next_item(["mod:fastqc", "mod:star_align"]), _oracle())
    assert "fastqc" in prompt
    assert "star" in prompt
    assert "mod:" not in prompt
    assert "star_align" not in prompt


def test_next_step_prompt_falls_back_to_the_bare_module_name_when_unresolvable():
    prompt = render_prompt(_next_item(["mod:some_local_process"]), _oracle())
    assert "some_local_process" in prompt
    assert "mod:" not in prompt


def test_next_step_prompt_asks_for_a_ranked_shortlist():
    prompt = render_prompt(_next_item(["mod:fastqc"]), _oracle())
    assert "3" in prompt
    assert "best first" in prompt.lower()


def test_unknown_task_type_raises_rather_than_rendering_something_wrong():
    with pytest.raises(ValueError, match="unknown task"):
        render_prompt({"id": "x", "task": "freeform", "goal": "g", "given": [],
                       "gold": {}}, _oracle())


@pytest.mark.parametrize("raw,expected", [
    ('["fastqc", "STAR", "salmon"]', ["fastqc", "STAR", "salmon"]),
    ('Here you go:\n["fastqc", "STAR"]\nHope that helps!', ["fastqc", "STAR"]),
    ('```json\n["fastqc", "STAR"]\n```', ["fastqc", "STAR"]),
    ('["fastqc"]', ["fastqc"]),
    ('[]', []),
])
def test_parses_the_json_array_out_of_a_chatty_response(raw, expected):
    assert parse_tool_list(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "I cannot help with that.", "fastqc, STAR, salmon", "[unclosed",
])
def test_unparseable_responses_return_empty_rather_than_guessing(raw):
    assert parse_tool_list(raw) == []


def test_non_string_elements_are_discarded_not_stringified():
    assert parse_tool_list('["fastqc", 42, null, {"tool": "star"}, "salmon"]') == [
        "fastqc", "salmon"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.render'`

- [ ] **Step 3: Write the implementation**

Create `src/methods_graph/bench/render.py`:

```python
"""Item to prompt, and model response back to a list of tool names.

Prompts are identical across models and carry no methods-graph context: the baseline
being measured is what the model knows unaided. They present no candidate list either —
a closed multiple choice would hand over the answer set.
"""
from __future__ import annotations

import json
import re

from methods_graph.bench.oracle import Oracle

_WHOLE_PIPELINE = (
    "Goal: {goal}\n"
    "Return a JSON array of tool names, in execution order.\n"
    "Return only the JSON array, with no commentary."
)

_NEXT_STEP = (
    "Goal: {goal}\n"
    "Completed so far: {given}\n"
    "Return a JSON array of up to 3 candidate tool names for the NEXT step, "
    "best first.\n"
    "Return only the JSON array, with no commentary."
)

_NOTHING_YET = "nothing yet"


def _display_name(module_id: str, oracle: Oracle) -> str:
    """A completed step as a human would name it.

    ``mod:star_align`` is nf-core's vocabulary, not the field's; putting it in the prompt
    would tell the model which registry the answer key came from. Unresolvable modules
    fall back to their bare name — honest, and rare (94% of modules reach a method).
    """
    method_id = oracle.method_for_module(module_id)
    if method_id:
        return method_id.split(":", 1)[1]
    return module_id.split(":", 1)[1] if ":" in module_id else module_id


def render_prompt(item: dict, oracle: Oracle) -> str:
    """The exact text sent to every model for one item."""
    task = item.get("task")
    if task == "whole_pipeline":
        return _WHOLE_PIPELINE.format(goal=item["goal"])
    if task == "next_step":
        names = [_display_name(m, oracle) for m in item.get("given") or []]
        return _NEXT_STEP.format(
            goal=item["goal"], given=", ".join(names) if names else _NOTHING_YET)
    raise ValueError(f"unknown task type: {task!r}")


def _first_json_array(text: str) -> str | None:
    """The first balanced ``[...]`` span, so a chatty preamble does not break parsing."""
    start = text.find("[")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        start = text.find("[", start + 1)
    return None


def parse_tool_list(raw: str) -> list[str]:
    """Tool names from a model response, or ``[]`` if none can be read.

    Never falls back to splitting prose on commas. A guessed parse would be scored as
    though the model had answered, turning a formatting failure into a knowledge result.
    The caller counts empty parses so refusals stay visible.
    """
    if not raw:
        return []
    fenced = re.sub(r"```(?:json)?", "", raw)
    span = _first_json_array(fenced)
    if span is None:
        return []
    try:
        parsed = json.loads(span)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [element for element in parsed if isinstance(element, str) and element.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/render.py tests/test_bench_render.py
git commit -m "feat(bench): prompt rendering and strict response parsing"
```

---

### Task 8: Model adapters

**Files:**
- Create: `src/methods_graph/bench/adapters.py`
- Test: `tests/test_bench_adapters.py`

**Interfaces:**
- Produces:
  - `def static(responses: dict[str, str] | list[str]) -> Callable[[str], str]`
  - `def claude_cli(*, model: str, timeout: int = 300, runner=subprocess.run) -> Callable[[str], str]`
  - `def openai(*, model: str, api_key: str | None = None, timeout: int = 120, http_post=None) -> Callable[[str], str]`
  - `def get_adapter(spec: str) -> Callable[[str], str]`
  - `class AdapterError(RuntimeError)`

A contestant is exactly `(prompt: str) -> str`. Nothing model-specific reaches the scorer. Network and subprocess calls take injectable seams, matching `fetch.py`'s `runner=subprocess.run` pattern, so tests never touch the network.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_adapters.py`:

```python
import json
import subprocess

import pytest

from methods_graph.bench.adapters import (
    AdapterError, claude_cli, get_adapter, openai, static)


def test_static_replays_by_prompt():
    adapter = static({"Goal: A": '["fastqc"]', "Goal: B": '["star"]'})
    assert adapter("Goal: B") == '["star"]'


def test_static_replays_a_list_in_order():
    adapter = static(['["a"]', '["b"]'])
    assert adapter("anything") == '["a"]'
    assert adapter("anything else") == '["b"]'


def test_static_raises_when_it_runs_out_rather_than_repeating():
    adapter = static(['["a"]'])
    adapter("one")
    with pytest.raises(AdapterError, match="exhausted"):
        adapter("two")


def test_claude_cli_sends_the_prompt_and_returns_stdout():
    seen = {}

    def _runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='["fastqc"]\n', stderr="")

    adapter = claude_cli(model="claude-opus-5", runner=_runner)
    assert adapter("Goal: X") == '["fastqc"]'
    assert "-p" in seen["cmd"]
    assert "Goal: X" in seen["cmd"]
    assert "claude-opus-5" in seen["cmd"]


def test_claude_cli_nonzero_exit_raises_with_stderr():
    def _runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="quota exceeded")

    with pytest.raises(AdapterError, match="quota exceeded"):
        claude_cli(model="claude-opus-5", runner=_runner)("Goal: X")


def test_claude_cli_timeout_raises_adapter_error():
    def _runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 300)

    with pytest.raises(AdapterError, match="timed out"):
        claude_cli(model="claude-opus-5", runner=_runner)("Goal: X")


def test_openai_posts_temperature_zero_and_returns_the_message():
    seen = {}

    def _post(url, payload, headers, timeout):
        seen.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": '["fastqc"]'}}]}

    adapter = openai(model="gpt-4o", api_key="sk-test", http_post=_post)
    assert adapter("Goal: X") == '["fastqc"]'
    assert seen["payload"]["temperature"] == 0
    assert seen["payload"]["model"] == "gpt-4o"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_without_a_key_raises_before_any_request():
    with pytest.raises(AdapterError, match="OPENAI_API_KEY"):
        openai(model="gpt-4o", api_key=None, http_post=None, _env={})


def test_openai_malformed_response_raises_rather_than_returning_empty():
    with pytest.raises(AdapterError, match="unexpected response"):
        openai(model="gpt-4o", api_key="sk-test",
               http_post=lambda *a, **k: {"error": "boom"})("Goal: X")


def test_get_adapter_parses_provider_and_model():
    assert callable(get_adapter("claude:claude-opus-5"))
    assert callable(get_adapter("openai:gpt-4o"))


def test_get_adapter_rejects_an_unknown_provider():
    with pytest.raises(AdapterError, match="unknown adapter"):
        get_adapter("mystery:model-x")


def test_get_adapter_loads_a_static_file(tmp_path):
    path = tmp_path / "canned.json"
    path.write_text(json.dumps({"Goal: A": '["fastqc"]'}))
    assert get_adapter(f"static:{path}")("Goal: A") == '["fastqc"]'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.adapters'`

- [ ] **Step 3: Write the implementation**

Create `src/methods_graph/bench/adapters.py`:

```python
"""A contestant is a callable ``(prompt: str) -> str``. That is the whole contract.

Nothing model-specific reaches the scorer, so adding a model is adding a function here
and nothing else. Network and subprocess calls take injectable seams — the same pattern
``fetch.py`` uses — so the test suite never makes a request.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class AdapterError(RuntimeError):
    """A contestant could not be reached or answered unusably.

    Distinct from an empty answer: the runner records this against the item and keeps
    going, so one rate limit does not discard a whole run, and a failed call is never
    scored as if the model had declined to answer.
    """


def static(responses: dict[str, str] | list[str]) -> Callable[[str], str]:
    """Replay canned responses — by prompt if a dict, in order if a list."""
    if isinstance(responses, dict):
        table = dict(responses)

        def _by_prompt(prompt: str) -> str:
            if prompt not in table:
                raise AdapterError(f"static adapter has no response for: {prompt!r}")
            return table[prompt]

        return _by_prompt

    queue = list(responses)
    index = {"n": 0}

    def _in_order(_prompt: str) -> str:
        if index["n"] >= len(queue):
            raise AdapterError("static adapter exhausted")
        value = queue[index["n"]]
        index["n"] += 1
        return value

    return _in_order


def claude_cli(
    *, model: str, timeout: int = 300, runner: Callable[..., Any] = subprocess.run,
) -> Callable[[str], str]:
    """Headless ``claude -p`` — no API key needed, uses the local CLI's auth."""

    def _call(prompt: str) -> str:
        cmd = ["claude", "-p", prompt, "--model", model]
        try:
            completed = runner(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdapterError(f"claude CLI timed out after {timeout}s") from None
        except OSError as exc:
            raise AdapterError(f"claude CLI could not be run: {exc}") from exc
        if completed.returncode != 0:
            raise AdapterError(
                f"claude CLI exited {completed.returncode}: {completed.stderr.strip()}")
        return completed.stdout.strip()

    return _call


def _urllib_post(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int,
) -> Any:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AdapterError(f"OpenAI request failed: {exc}") from exc


def openai(
    *,
    model: str,
    api_key: str | None = None,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
    _env: dict[str, str] | None = None,
) -> Callable[[str], str]:
    """OpenAI chat completions at temperature 0, over stdlib urllib."""
    env = os.environ if _env is None else _env
    key = api_key or env.get("OPENAI_API_KEY")
    if not key:
        raise AdapterError("OPENAI_API_KEY is not set and no api_key was passed")
    post = http_post or _urllib_post

    def _call(prompt: str) -> str:
        body = post(
            _OPENAI_URL,
            {"model": model, "temperature": 0,
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout,
        )
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AdapterError(f"unexpected response shape: {body!r}") from None

    return _call


def get_adapter(spec: str) -> Callable[[str], str]:
    """``claude:<model>`` / ``openai:<model>`` / ``static:<path-to-json>``."""
    provider, _, argument = spec.partition(":")
    if provider == "claude":
        return claude_cli(model=argument or "claude-opus-5")
    if provider == "openai":
        return openai(model=argument or "gpt-4o")
    if provider == "static":
        return static(json.loads(Path(argument).read_text()))
    raise AdapterError(f"unknown adapter {spec!r} (expected claude:, openai: or static:)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_adapters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/adapters.py tests/test_bench_adapters.py
git commit -m "feat(bench): static, claude-cli and openai contestant adapters"
```

---

### Task 9: Runner, re-scorer and CLI subcommands

**Files:**
- Modify: `src/methods_graph/bench/run.py`
- Modify: `src/methods_graph/cli.py:1442-1445` (parser) and `:1533` (dispatch)
- Modify: `tests/test_bench_run.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8
- Produces:
  - `def load_items(items_dir: Path) -> list[dict]`
  - `def score_item(item: dict, raw: str, oracle) -> dict[str, Any]`
  - `def run_items(items, adapter, oracle, *, model: str) -> list[dict]`
  - `def rescore(rows, oracle) -> list[dict]`
  - `def summarize(rows) -> dict[str, Any]`
  - CLI: `methods-graph bench build | coverage | run | score`

**Breaking CLI change:** `mg bench --pipelines X --out Y` becomes `mg bench build --pipelines X --out Y`. Nothing is released; update `tests/test_bench_run.py` accordingly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_run.py`:

```python
import json

from methods_graph.bench.oracle import StaticOracle
from methods_graph.bench.run import rescore, run_items, score_item, summarize
from methods_graph.cli import main


def _oracle():
    return StaticOracle(
        methods=["m:fastqc", "m:star", "m:hisat2", "m:salmon", "m:deseq2"],
        modules={"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                 "mod:salmon_quant": "m:salmon",
                 "mod:deseq2_differential": "m:deseq2"},
        operations={"m:star": ["op:0292"], "m:hisat2": ["op:0292"]},
        inputs={"m:star": ["data:1234"], "m:hisat2": ["data:1234"],
                "m:salmon": ["data:0863"], "m:deseq2": ["data:3917"]},
        outputs={"m:star": ["data:0863"], "m:salmon": ["data:3917"]},
    )


def _whole_item():
    return {
        "id": "rnaseq/whole/001", "task": "whole_pipeline", "goal": "Bulk RNA-seq",
        "given": [],
        "gold": {
            "sequence": ["mod:fastqc", "mod:star_align", "mod:salmon_quant",
                         "mod:deseq2_differential"],
            "edges": [["mod:fastqc", "mod:star_align"],
                      ["mod:star_align", "mod:salmon_quant"],
                      ["mod:salmon_quant", "mod:deseq2_differential"]],
        },
    }


def test_ceiling_feeding_the_gold_answer_back_scores_one():
    row = score_item(_whole_item(), '["fastqc","star","salmon","deseq2"]', _oracle())
    assert row["selection"]["f1"] == 1.0
    assert row["sequencing"]["score"] == 1.0
    assert row["unresolved"] == []


def test_row_retains_the_raw_output_so_scores_can_be_rederived():
    raw = 'Sure!\n["fastqc","star"]'
    assert score_item(_whole_item(), raw, _oracle())["raw"] == raw


def test_unparseable_response_is_recorded_not_silently_zeroed():
    row = score_item(_whole_item(), "I cannot help with that.", _oracle())
    assert row["parsed"] is False
    assert row["pred"] == []
    assert row["selection"]["f1"] == 0.0


def test_next_step_row_carries_its_bucket():
    item = {"id": "rnaseq/next/002", "task": "next_step", "goal": "Bulk RNA-seq",
            "given": ["mod:fastqc", "mod:star_align"],
            "gold": {"next": "mod:salmon_quant"}}
    row = score_item(item, '["salmon","kallisto"]', _oracle())
    assert row["n_given"] == 2
    assert row["next"]["top1"] is True


def test_adapter_failure_is_recorded_against_the_item_and_the_run_continues():
    from methods_graph.bench.adapters import AdapterError

    def _flaky(prompt):
        if "Bulk" in prompt:
            raise AdapterError("rate limited")
        return '["fastqc"]'

    items = [_whole_item(), {**_whole_item(), "id": "other/whole/001", "goal": "Other"}]
    rows = run_items(items, _flaky, _oracle(), model="test")
    assert rows[0]["error"] == "rate limited"
    assert rows[0]["selection"] is None
    assert rows[1]["error"] is None


def test_rescore_reproduces_the_original_scores_from_raw_alone():
    rows = run_items([_whole_item()], lambda p: '["fastqc","star","salmon","deseq2"]',
                     _oracle(), model="test")
    stripped = [{k: v for k, v in r.items()
                 if k in ("item", "task", "raw", "model", "gold_raw", "given")}
                for r in rows]
    assert rescore(stripped, _oracle())[0]["selection"]["f1"] == 1.0


def test_summary_separates_the_two_task_types():
    rows = run_items([_whole_item()], lambda p: '["fastqc","star","salmon","deseq2"]',
                     _oracle(), model="test")
    summary = summarize(rows)
    assert summary["whole_pipeline"]["n"] == 1
    assert summary["whole_pipeline"]["selection_f1"] == 1.0
    assert summary["next_step"]["n"] == 0


def test_cli_run_writes_one_jsonl_row_per_item(tmp_path):
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    (items_dir / "rnaseq.json").write_text(json.dumps([_whole_item()]))
    canned = tmp_path / "canned.json"
    canned.write_text(json.dumps(['["fastqc","star","salmon","deseq2"]']))
    out = tmp_path / "results.jsonl"

    code = main(["bench", "run", "--items", str(items_dir),
                 "--model", f"static:{canned}", "--out", str(out),
                 "--oracle-json", str(_write_oracle_json(tmp_path))])
    assert code == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["selection"]["f1"] == 1.0


def _write_oracle_json(tmp_path):
    """A serialized StaticOracle, so the CLI test needs no Kuzu database."""
    path = tmp_path / "oracle.json"
    path.write_text(json.dumps({
        "methods": ["m:fastqc", "m:star", "m:salmon", "m:deseq2"],
        "modules": {"mod:fastqc": "m:fastqc", "mod:star_align": "m:star",
                    "mod:salmon_quant": "m:salmon",
                    "mod:deseq2_differential": "m:deseq2"},
        "operations": {}, "inputs": {}, "outputs": {},
    }))
    return path
```

Also update the existing CLI test in `tests/test_bench_run.py` that invokes `main(["bench", "--pipelines", ...])` to `main(["bench", "build", "--pipelines", ...])`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_items'`

- [ ] **Step 3: Add the oracle's JSON round-trip**

Append to `src/methods_graph/bench/oracle.py`:

```python
def load_oracle(*, db_path: Path | None = None, json_path: Path | None = None) -> Oracle:
    """A :class:`KuzuOracle` from the graph, or a :class:`StaticOracle` from JSON.

    The JSON form exists so the CLI is testable without a built database — the same
    reason the scorer takes an ``Oracle`` rather than a connection.
    """
    if json_path is not None:
        blob = json.loads(json_path.read_text())
        return StaticOracle(
            methods=blob.get("methods", []),
            modules=blob.get("modules", {}),
            operations=blob.get("operations", {}),
            inputs=blob.get("inputs", {}),
            outputs=blob.get("outputs", {}),
        )
    if db_path is None:
        raise ValueError("one of db_path or json_path is required")
    return KuzuOracle(db_path)
```

Add `import json` to the top of `oracle.py`.

- [ ] **Step 4: Write the runner**

Append to `src/methods_graph/bench/run.py`:

```python
from methods_graph.bench.adapters import AdapterError
from methods_graph.bench.normalize import (
    normalize_answer, project_edges, project_sequence)
from methods_graph.bench.oracle import Oracle
from methods_graph.bench.render import parse_tool_list, render_prompt
from methods_graph.bench.score import (
    aggregate_next_step, match_steps, position_bucket, score_next_step,
    score_selection, score_sequencing, score_validity)


def load_items(items_dir: Path) -> list[dict[str, Any]]:
    """Every item under *items_dir*, ordered by id so runs are comparable."""
    items: list[dict[str, Any]] = []
    for path in sorted(items_dir.glob("*.json")):
        items.extend(json.loads(path.read_text()))
    return sorted(items, key=lambda item: item["id"])


def score_item(item: dict[str, Any], raw: str, oracle: Oracle) -> dict[str, Any]:
    """One model answer, scored on every axis its task type supports.

    ``raw`` is kept on the row: every score here is a pure function of it, so a metric
    can be redefined and the whole run re-scored without spending another API call.
    """
    names = parse_tool_list(raw)
    pred, unresolved = normalize_answer(names, oracle)
    row: dict[str, Any] = {
        "item": item["id"], "task": item["task"], "raw": raw,
        "parsed": bool(names), "pred": pred, "unresolved": unresolved, "error": None,
        # The item's own gold and prefix, verbatim. Together with `raw` these are
        # everything `rescore` needs, so a redefined metric can be applied to a finished
        # run without re-reading the item set — or paying for the API calls again.
        "gold_raw": item["gold"], "given": list(item.get("given") or []),
    }

    if item["task"] == "whole_pipeline":
        gold_modules = item["gold"]["sequence"]
        gold, gold_unresolved = project_sequence(gold_modules, oracle)
        edges, n_cyclic = project_edges(
            item["gold"].get("edges") or [], gold_modules, oracle)
        selection = score_selection(gold, pred, oracle)
        row.update({
            "gold": gold,
            "gold_unresolved": gold_unresolved,
            "n_cyclic_edges_dropped": n_cyclic,
            "selection": selection,
            "sequencing": score_sequencing(edges, selection["matched"], pred),
            "validity": score_validity(pred, oracle),
        })
        return row

    if item["task"] == "next_step":
        gold_next = oracle.method_for_module(item["gold"]["next"])
        n_given = len(item.get("given") or [])
        row.update({"gold": gold_next, "n_given": n_given,
                    "bucket": position_bucket(n_given)})
        # An unresolvable gold answer cannot be scored against; it is reported, not zeroed.
        row["next"] = (None if gold_next is None
                       else score_next_step(gold_next, pred, oracle))
        return row

    raise ValueError(f"unknown task type: {item['task']!r}")


def run_items(
    items: list[dict[str, Any]], adapter: Callable[[str], str], oracle: Oracle,
    *, model: str,
) -> list[dict[str, Any]]:
    """Render, call, score — one row per item, in item order.

    An adapter failure is recorded against its item and the run continues: a rate limit
    partway through a 500-item set must not discard the 300 answers already paid for.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        prompt = render_prompt(item, oracle)
        try:
            raw = adapter(prompt)
        except AdapterError as exc:
            rows.append({"item": item["id"], "task": item["task"], "model": model,
                         "raw": None, "parsed": False, "pred": [], "unresolved": [],
                         "error": str(exc), "selection": None, "sequencing": None,
                         "validity": None, "next": None})
            continue
        rows.append({**score_item(item, raw, oracle), "model": model})
    return rows


def rescore(rows: list[dict[str, Any]], oracle: Oracle) -> list[dict[str, Any]]:
    """Re-derive every score from the retained raw output, leaving failures untouched."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("raw") is None:
            out.append(dict(row))
            continue
        item = {"id": row["item"], "task": row["task"], "goal": "",
                "given": row.get("given") or [], "gold": row["gold_raw"]}
        out.append({**score_item(item, row["raw"], oracle), "model": row.get("model")})
    return out


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline table: two task types, never pooled into one accuracy figure."""
    whole = [r for r in rows if r["task"] == "whole_pipeline" and not r["error"]]
    nxt = [r for r in rows if r["task"] == "next_step" and not r["error"] and r["next"]]

    return {
        "n_rows": len(rows),
        "n_errors": sum(1 for r in rows if r["error"]),
        "n_unparsed": sum(1 for r in rows if not r["parsed"] and not r["error"]),
        "whole_pipeline": {
            "n": len(whole),
            "selection_f1": _mean([r["selection"]["f1"] for r in whole]),
            "selection_precision": _mean([r["selection"]["precision"] for r in whole]),
            "selection_recall": _mean([r["selection"]["recall"] for r in whole]),
            "sequencing": _mean([r["sequencing"]["score"] for r in whole]),
            "sequencing_n_scored": sum(
                1 for r in whole if r["sequencing"]["score"] is not None),
            "validity": _mean([r["validity"]["score"] for r in whole]),
            "validity_coverage": _mean([r["validity"]["coverage"] for r in whole]),
        },
        "next_step": {
            "n": len(nxt),
            **aggregate_next_step([
                {"n_given": r["n_given"], "top1": r["next"]["top1"],
                 "topk": r["next"]["topk"]} for r in nxt]),
        },
    }
```

Add to the top of `run.py`: `from typing import Any, Callable`.

- [ ] **Step 5: Restructure the CLI**

Replace `src/methods_graph/cli.py:1442-1445` with:

```python
    p_bench = sub.add_parser("bench", help="method-sequencing benchmark")
    bench_sub = p_bench.add_subparsers(dest="bench_cmd", required=True)

    b_build = bench_sub.add_parser("build", help="nf-core clones -> frozen item set")
    b_build.add_argument("--pipelines", type=Path, default=Path("snapshots/pipelines"))
    b_build.add_argument("--out", type=Path, default=Path("bench"))

    b_cov = bench_sub.add_parser(
        "coverage", help="how much graph oracle backs the item set")
    b_cov.add_argument("--items", type=Path, default=Path("bench/items"))
    b_cov.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))
    b_cov.add_argument("--oracle-json", type=Path, default=None)

    b_run = bench_sub.add_parser("run", help="run a model over the item set")
    b_run.add_argument("--items", type=Path, default=Path("bench/items"))
    b_run.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))
    b_run.add_argument("--oracle-json", type=Path, default=None)
    b_run.add_argument("--model", required=True,
                       help="claude:<model> | openai:<model> | static:<path>")
    b_run.add_argument("--out", type=Path, required=True)
    b_run.add_argument("--limit", type=int, default=None)
    b_run.add_argument("--task", choices=["whole_pipeline", "next_step"], default=None)

    b_score = bench_sub.add_parser(
        "score", help="re-derive scores from a results file's retained raw output")
    b_score.add_argument("--results", type=Path, required=True)
    b_score.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))
    b_score.add_argument("--oracle-json", type=Path, default=None)
    b_score.add_argument("--out", type=Path, default=None)
```

Replace the `elif args.cmd == "bench":` dispatch branch at `:1533` with a call to a new `cmd_bench(args)` helper defined next to the other `cmd_*` functions:

```python
def cmd_bench(args) -> int:
    """Dispatch the bench subcommands. Returns a process exit code."""
    from methods_graph.bench.oracle import coverage, load_oracle
    from methods_graph.bench.run import (
        build_from_clones, load_items, rescore, run_items, summarize)

    if args.bench_cmd == "build":
        manifest = build_from_clones(args.pipelines, args.out, goals={})
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    oracle = load_oracle(db_path=args.db, json_path=args.oracle_json)

    if args.bench_cmd == "coverage":
        module_ids = [
            module_id
            for item in load_items(args.items) if item["task"] == "whole_pipeline"
            for module_id in item["gold"]["sequence"]
        ]
        print(json.dumps(coverage(oracle, module_ids), indent=2, sort_keys=True))
        return 0

    if args.bench_cmd == "run":
        from methods_graph.bench.adapters import get_adapter

        items = load_items(args.items)
        if args.task:
            items = [i for i in items if i["task"] == args.task]
        if args.limit:
            items = items[:args.limit]
        rows = run_items(items, get_adapter(args.model), oracle, model=args.model)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        print(json.dumps(summarize(rows), indent=2, sort_keys=True))
        return 0

    if args.bench_cmd == "score":
        rows = [json.loads(line) for line in
                args.results.read_text().splitlines() if line.strip()]
        rescored = rescore(rows, oracle)
        if args.out:
            args.out.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rescored))
        print(json.dumps(summarize(rescored), indent=2, sort_keys=True))
        return 0

    raise ValueError(f"unknown bench subcommand: {args.bench_cmd!r}")
```

and in `main`:

```python
    elif args.cmd == "bench":
        return cmd_bench(args)
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, no regressions against the 619 tests already on `main`.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/bench/run.py src/methods_graph/bench/oracle.py \
        src/methods_graph/cli.py tests/test_bench_run.py
git commit -m "feat(bench): runner, re-scorer and bench build|coverage|run|score CLI"
```

---

### Task 10: Baselines and the CI ceiling gate

**Files:**
- Create: `src/methods_graph/bench/baselines.py`
- Modify: `tests/test_bench_score.py`
- Create: `tests/fixtures/bench/rnaseq.json`
- Modify: `.github/workflows/*.yml` (whichever runs pytest)

**Interfaces:**
- Produces:
  - `def gold_adapter(items, oracle) -> Callable[[str], str]` — the ceiling
  - `def modal_adapter(items, oracle) -> Callable[[str], str]` — answer the most common gold sequence, ignoring the goal
  - `def random_adapter(oracle, *, k: int, seed: int) -> Callable[[str], str]` — the floor

**Why these three:** without a floor, a mediocre score reads as a result. The modal baseline is the important one — if "always answer the median RNA-seq pipeline" scores near a model, the benchmark is measuring pipeline-shape priors, not method knowledge.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_score.py`:

```python
import json
from pathlib import Path

from methods_graph.bench.baselines import gold_adapter, modal_adapter, random_adapter
from methods_graph.bench.oracle import load_oracle
from methods_graph.bench.run import run_items, summarize

_FIXTURES = Path(__file__).parent / "fixtures" / "bench"


def _fixture_items():
    return json.loads((_FIXTURES / "rnaseq.json").read_text())


def _fixture_oracle():
    return load_oracle(json_path=_FIXTURES / "oracle.json")


def test_ceiling_gold_fed_back_scores_one_on_every_metric():
    items = [i for i in _fixture_items() if i["task"] == "whole_pipeline"]
    oracle = _fixture_oracle()
    rows = run_items(items, gold_adapter(items, oracle), oracle, model="gold")
    summary = summarize(rows)
    assert summary["whole_pipeline"]["selection_f1"] == 1.0
    assert summary["whole_pipeline"]["sequencing"] == 1.0
    assert summary["n_errors"] == 0


def test_random_baseline_is_deterministic_for_a_seed():
    oracle = _fixture_oracle()
    first = random_adapter(oracle, k=4, seed=7)("any prompt")
    second = random_adapter(oracle, k=4, seed=7)("any prompt")
    assert first == second


def test_random_baseline_differs_across_seeds():
    oracle = _fixture_oracle()
    assert (random_adapter(oracle, k=4, seed=7)("p")
            != random_adapter(oracle, k=4, seed=8)("p"))


def test_modal_baseline_ignores_the_goal():
    items = [i for i in _fixture_items() if i["task"] == "whole_pipeline"]
    adapter = modal_adapter(items, _fixture_oracle())
    assert adapter("Goal: A") == adapter("Goal: something completely different")
```

- [ ] **Step 2: Create the fixture**

Create `tests/fixtures/bench/rnaseq.json` — two whole-pipeline items and three next-step items, using **nested module paths** (`mod:star_align`, not `mod:align`) so the fixture cannot mask the id-scheme bug that survived four reviews in Plan 1:

```json
[
  {
    "id": "rnaseq/whole/001",
    "task": "whole_pipeline",
    "goal": "Bulk RNA-seq differential expression from paired-end human FASTQ",
    "given": [],
    "gold": {
      "sequence": ["mod:fastqc", "mod:trimgalore", "mod:star_genomegenerate",
                   "mod:star_align", "mod:salmon_quant", "mod:deseq2_differential"],
      "edges": [["mod:fastqc", "mod:trimgalore"],
                ["mod:trimgalore", "mod:star_align"],
                ["mod:star_genomegenerate", "mod:star_align"],
                ["mod:star_align", "mod:salmon_quant"],
                ["mod:salmon_quant", "mod:deseq2_differential"]],
      "source": "nf-core/rnaseq@3.14.0",
      "nxf_ver": "23.04.0",
      "dag_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "derivation": "nextflow_dsl2"
    }
  },
  {
    "id": "rnaseq/next/000",
    "task": "next_step",
    "goal": "Bulk RNA-seq differential expression from paired-end human FASTQ",
    "given": [],
    "gold": {"next": "mod:fastqc", "source": "nf-core/rnaseq@3.14.0",
             "nxf_ver": "23.04.0",
             "dag_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
             "derivation": "nextflow_dsl2"}
  },
  {
    "id": "rnaseq/next/003",
    "task": "next_step",
    "goal": "Bulk RNA-seq differential expression from paired-end human FASTQ",
    "given": ["mod:fastqc", "mod:trimgalore", "mod:star_genomegenerate"],
    "gold": {"next": "mod:star_align", "source": "nf-core/rnaseq@3.14.0",
             "nxf_ver": "23.04.0",
             "dag_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
             "derivation": "nextflow_dsl2"}
  }
]
```

Create `tests/fixtures/bench/oracle.json` with the matching module→method map, operations, inputs and outputs (mirroring the real graph's values for `m:star`, `m:hisat2`, `m:salmon`, `m:deseq2`, `m:fastqc`, `m:trimgalore` as recorded in this plan's Reconnaissance table).

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -k baseline -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.bench.baselines'`

- [ ] **Step 4: Write the implementation**

Create `src/methods_graph/bench/baselines.py`:

```python
"""Floor, ceiling and the one baseline that can embarrass the benchmark.

A model score means nothing without them. The modal baseline is the sharp one: if
"always answer the most common gold pipeline, ignoring the question" scores close to a
model, the benchmark is measuring pipeline-shape priors rather than method knowledge.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from typing import Any, Callable

from methods_graph.bench.normalize import project_sequence
from methods_graph.bench.oracle import Oracle
from methods_graph.bench.render import render_prompt


def _bare(method_id: str) -> str:
    return method_id.split(":", 1)[1] if ":" in method_id else method_id


def _as_answer(method_ids: list[str]) -> str:
    return json.dumps([_bare(m) for m in method_ids])


def gold_adapter(
    items: list[dict[str, Any]], oracle: Oracle,
) -> Callable[[str], str]:
    """The ceiling: answer each item with its own gold. Must score 1.0, and is a CI gate.

    Keyed by rendered prompt rather than item id because an adapter only ever sees the
    prompt — which also means this quietly asserts that prompts are unique per item.
    """
    table: dict[str, str] = {}
    for item in items:
        if item["task"] == "whole_pipeline":
            sequence, _ = project_sequence(item["gold"]["sequence"], oracle)
            table[render_prompt(item, oracle)] = _as_answer(sequence)
        else:
            gold_next = oracle.method_for_module(item["gold"]["next"])
            table[render_prompt(item, oracle)] = _as_answer(
                [gold_next] if gold_next else [])
    return lambda prompt: table.get(prompt, "[]")


def modal_adapter(
    items: list[dict[str, Any]], oracle: Oracle,
) -> Callable[[str], str]:
    """Always answer the single most common gold sequence, ignoring the goal entirely."""
    counts: Counter[tuple[str, ...]] = Counter()
    for item in items:
        if item["task"] == "whole_pipeline":
            sequence, _ = project_sequence(item["gold"]["sequence"], oracle)
            counts[tuple(sequence)] += 1
    # Ties break on the lexicographically smallest sequence, so the baseline is stable
    # across item-set revisions rather than shifting with dict ordering.
    best = min(seq for seq, n in counts.items() if n == max(counts.values())) if counts else ()
    answer = _as_answer(list(best))
    return lambda _prompt: answer


def random_adapter(
    oracle: Oracle, *, k: int, seed: int,
) -> Callable[[str], str]:
    """The floor: *k* methods drawn uniformly from the catalog, seeded for determinism."""
    catalog = oracle.method_ids()
    if not catalog:
        raise ValueError("oracle exposes no methods to sample from")
    rng = random.Random(seed)
    answer = _as_answer(rng.sample(catalog, min(k, len(catalog))))
    return lambda _prompt: answer
```

This uses `oracle.method_ids()`, which Task 1 does not yet define. Add it to `StaticOracle` and to the `Oracle` protocol in `src/methods_graph/bench/oracle.py`:

```python
    def method_ids(self) -> list[str]:
        """Every method the oracle knows, sorted — the random baseline's sample space."""
        return sorted(self._methods)
```

and change `baselines.py`'s first line of `random_adapter` to `catalog = oracle.method_ids()`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_bench_score.py -v`
Expected: PASS

- [ ] **Step 6: Confirm the ceiling test runs in CI**

Run: `grep -rn "pytest" .github/workflows/`
The ceiling test lives in `tests/test_bench_score.py` and is collected by the existing `pytest tests/` invocation. Confirm that is the case; if CI selects specific test files, add `tests/test_bench_score.py`.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/bench/baselines.py tests/fixtures/bench/ tests/test_bench_score.py
git commit -m "feat(bench): random, modal and gold baselines with a CI ceiling gate"
```

---

### Task 11: Thread real revision and NXF_VER into items

**Files:**
- Modify: `src/methods_graph/bench/run.py:50-106` (`build_from_clones`)
- Modify: `tests/test_bench_run.py`

**Interfaces:**
- Consumes: `snapshots/snapshot.json` → `sources.nfcore_pipelines` → `{name: fetch_nfcore_pipeline manifest}`
- Produces: `build_from_clones(..., manifests: dict[str, dict] | None = None)`

`build_from_clones` currently hardcodes `nxf_ver="unknown"` and re-derives the revision with `git rev-parse`. `fetch_nfcore_pipeline` already returns `{repo, commit, revision, nxf_ver, path, dag, fetched_at}`, and `write_snapshot_manifest` stores it under `sources.nfcore_pipelines`. Spec §1 requires `pipeline@release` and `NXF_VER` per item so a disputed item can be re-derived — `@unknown` does not satisfy that.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_run.py`:

```python
def test_manifest_revision_and_nxf_ver_reach_the_item(tmp_path, monkeypatch):
    pipelines = tmp_path / "pipelines" / "rnaseq"
    pipelines.mkdir(parents=True)
    _write_minimal_clone(pipelines)     # existing fixture helper in this file

    out = tmp_path / "bench"
    build_from_clones(
        tmp_path / "pipelines", out,
        goals={"rnaseq": "Bulk RNA-seq"},
        manifests={"rnaseq": {"revision": "3.14.0", "nxf_ver": "23.04.0",
                              "commit": "abc123"}})
    items = json.loads((out / "items" / "rnaseq.json").read_text())
    assert items[0]["gold"]["source"] == "nf-core/rnaseq@3.14.0"
    assert items[0]["gold"]["nxf_ver"] == "23.04.0"


def test_missing_manifest_still_builds_with_honest_unknowns(tmp_path):
    pipelines = tmp_path / "pipelines" / "rnaseq"
    pipelines.mkdir(parents=True)
    _write_minimal_clone(pipelines)

    out = tmp_path / "bench"
    build_from_clones(tmp_path / "pipelines", out, goals={}, manifests=None)
    items = json.loads((out / "items" / "rnaseq.json").read_text())
    assert items[0]["gold"]["nxf_ver"] == "unknown"


def test_load_pipeline_manifests_reads_the_snapshot(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "created_at": "2026-07-31",
        "sources": {"nfcore_pipelines": {"rnaseq": {"revision": "3.14.0",
                                                    "nxf_ver": "23.04.0"}}},
    }))
    assert load_pipeline_manifests(snapshot)["rnaseq"]["nxf_ver"] == "23.04.0"


def test_load_pipeline_manifests_of_a_snapshot_without_pipelines_is_empty(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"sources": {"nfcore_pipelines": None}}))
    assert load_pipeline_manifests(snapshot) == {}


def test_load_pipeline_manifests_of_a_missing_file_is_empty(tmp_path):
    assert load_pipeline_manifests(tmp_path / "absent.json") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bench_run.py -k manifest -v`
Expected: FAIL with `TypeError: build_from_clones() got an unexpected keyword argument 'manifests'`

- [ ] **Step 3: Write the implementation**

In `src/methods_graph/bench/run.py`, add:

```python
def load_pipeline_manifests(snapshot_path: Path) -> dict[str, dict[str, Any]]:
    """Per-pipeline fetch manifests from a snapshot.json, or ``{}`` if absent.

    Missing is not an error: an offline build from a plain directory of clones is a
    supported path, and it degrades to "unknown" provenance rather than failing.
    """
    if not snapshot_path.exists():
        return {}
    try:
        blob = json.loads(snapshot_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return (blob.get("sources") or {}).get("nfcore_pipelines") or {}
```

Change the signature and the two provenance lines in `build_from_clones`:

```python
def build_from_clones(
    pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str],
    manifests: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build items for every clone under *pipelines_dir*; write items + manifest.

    *manifests* carries the ``fetch_nfcore_pipeline`` record per pipeline. It supplies
    the RELEASE tag and the NXF_VER the DAG was previewed under — provenance a bare
    clone cannot report, and which spec §1 requires so a disputed item can be re-derived.
    """
    manifests = manifests or {}
```

Inside the loop, replace `revision = _revision(pipeline_dir)` with:

```python
        manifest_entry = manifests.get(name) or {}
        # The release tag names what a reader can check out; the commit is the fallback
        # when no manifest recorded a tag.
        revision = manifest_entry.get("revision") or _revision(pipeline_dir)
        nxf_ver = manifest_entry.get("nxf_ver") or "unknown"
```

and pass `nxf_ver=nxf_ver` to `make_items` instead of the hardcoded `"unknown"`.

Finally, in `cmd_bench`'s `build` branch, load them:

```python
    if args.bench_cmd == "build":
        manifests = load_pipeline_manifests(args.pipelines.parent / "snapshot.json")
        manifest = build_from_clones(
            args.pipelines, args.out, goals={}, manifests=manifests)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/bench/run.py tests/test_bench_run.py src/methods_graph/cli.py
git commit -m "fix(bench): carry real release tag and NXF_VER into item provenance"
```

---

## After the plan

Once merged, the code is complete but **no numbers exist yet** — `snapshots/pipelines/` is empty. The operational sequence to get the first baseline:

1. Fetch pipelines with DAG preview (needs Nextflow + Java + network), writing `sources.nfcore_pipelines` into `snapshots/snapshot.json`.
2. `methods-graph bench build --pipelines snapshots/pipelines --out bench`
3. `methods-graph bench coverage --items bench/items` — **read this before any model score.** If `n_with_input_data` is a small fraction of `n_methods`, the selection metric is effectively exact-match and the sequencing/validity numbers carry large `UNKNOWN` denominators. Report it alongside every result.
4. `methods-graph bench run --model openai:gpt-4o --out results/gpt-4o.jsonl`, repeated per contestant, plus the three baselines.

## Self-review

**Spec coverage** — every requirement in §3–§5 maps to a task:

| Spec requirement | Task |
|---|---|
| Selection = step-set F1, order ignored, equivalence classes | 3 |
| Sequencing = fraction of gold precedences preserved | 4 |
| Validity via `classify_handoff`, `UNKNOWN` never valid | 5 |
| Class = operation + input data type, rejects bwa for spliced | 1 (oracle), 3 (test) |
| Next-step top-1 and top-3 | 6 |
| `adapters.openai` / `adapters.claude_cli` / `adapters.static` | 8 |
| `mg bench run --model <adapter>` → `results.jsonl`, raw retained | 9 |
| Baselines: random, most-common-gold; ceiling = 1.0 in CI | 10 |
| Test 1 equivalence, 2 order-independence, 3 UNKNOWN, 4 ceiling | 3, 4, 5, 10 |
| Tests 5 (`io_inferred`) and 6 (dropped manifest) | already merged in Plan 1 |
| Provenance `pipeline@release` + `NXF_VER` | 11 |
| `render.py`, `normalize.py`, `score.py`, `adapters.py`, `run.py` layout | 2, 3–6, 7, 8, 9 |

**Additions beyond the spec, each with cause:** `oracle.py` and the coverage report (§3 assumes graph coverage that measurement shows is 5.4% for input Data); `normalize.project_*` (spec §2 shows `m:` gold ids but Plan 1 emits `mod:`); next-step position stratification (flagged by Plan 1's final review); the modal baseline promoted from a line in §3 to its own tested function.

**Deliberate spec deviations, both in Task 7:** next-step prompts request up to 3 ranked candidates (spec §2 says one — but §3 requires top-3); `given` renders as method names rather than `mod:` ids (rendering module ids would leak nf-core vocabulary into the question).

**Type consistency:** `Oracle` methods (`has_method`, `method_for_module`, `operations`, `inputs`, `outputs`, `method_ids`) are used under those exact names in Tasks 2, 3, 5, 7, 10. `match_steps` returns gold→pred and is consumed that way by `score_sequencing`. `score_selection` returns the key `matched`, which Task 9 passes to `score_sequencing` as its `matched` argument.
