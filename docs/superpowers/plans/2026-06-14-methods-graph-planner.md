# Methods-Graph Planner (Sub-project B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal, advisory, attestation-ranked *expand* recommender over the master graph: given the Module steps and/or EDAM Format/Data a user has, return the ranked next analysis steps, each resolved to a concrete executor.

**Architecture:** One pure module `src/methods_graph/planner.py` exposing `expand(conn, frontier_ids, ...)` (the whole MVP) plus a thin `seed_from_edge` adapter. A small behavior-preserving refactor lifts the keyword resolver out of the provider into a shared pure helper in `extract/seed.py`. A `mg suggest` CLI subcommand exposes it. All read-only, deterministic, offline; fixture-driven tests via the existing loader.

**Tech Stack:** Python 3.13, Kùzu 0.11.3 (`conn.execute(..., parameters=...)`, `list_contains`), polars (loader), pytest. Test runner is `.venv/bin/pytest` (NOT `uv run`, which fails on the `[quration]` extra).

**Spec:** [docs/superpowers/specs/2026-06-14-methods-graph-planner-design.md](../specs/2026-06-14-methods-graph-planner-design.md)

---

## File Structure

- **Modify** `src/methods_graph/extract/seed.py` — add pure free function `method_ids_matching(conn, keywords) -> list[str]` (lifted from the provider).
- **Modify** `src/methods_graph/provider/quration_provider.py` — `_method_ids_matching` delegates to the lifted helper (behavior preserved).
- **Create** `src/methods_graph/planner.py` — `Executor`, `Suggestion`, `_candidates`, `_enrich`, `expand`, `seed_from_edge`.
- **Modify** `src/methods_graph/cli.py` — `cmd_suggest` + `suggest` subparser + dispatch.
- **Modify** `tests/test_seed.py` (or create if absent) — tests for `method_ids_matching` + provider delegation.
- **Create** `tests/test_planner.py` — shared fixture graph + tests for dataclasses, `_candidates`, `_enrich`, `expand`, `seed_from_edge`, CLI.

Key verified facts the code relies on (see spec "Verified substrate facts"): `INPUT` edges attach to **Method** nodes (cold start is data→Method→Module, a 2-hop); there is **no** `container` attribute (containers come via `method_neighborhood`'s `PACKAGED_AS` bucket); `WRAPS` is Module→Method; `DOWNSTREAM_OF.properties` carries `pipelines`/`attestations`; `HAS_MODULE` is Pipeline→Module.

---

## Task 1: Lift the keyword resolver into a shared pure helper

**Files:**
- Modify: `src/methods_graph/extract/seed.py`
- Modify: `src/methods_graph/provider/quration_provider.py:219-275`
- Test: `tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seed.py` (create the file with these imports if it does not exist):

```python
import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.extract.seed import method_ids_matching

P = Provenance("test", "x", "2026-06-14")


def _kw_graph(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"description": "rna quant"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:quant", "Expression quantification", NodeKind.OPERATION, {}, P),
    ]
    edges = [EdgeRecord("m:salmon", "op:quant", EdgeKind.PERFORMS, {}, P)]
    db = tmp_path / "kw.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_method_ids_matching_direct_name_hit(tmp_path):
    conn = _kw_graph(tmp_path)
    assert method_ids_matching(conn, ["salmon"]) == ["m:salmon"]


def test_method_ids_matching_transitive_via_operation(tmp_path):
    conn = _kw_graph(tmp_path)
    # "quantification" hits the Operation node; the method that PERFORMS it resolves.
    assert "m:salmon" in method_ids_matching(conn, ["quantification"])


def test_provider_delegates_to_helper(tmp_path):
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    db = tmp_path / "kw.kuzu"
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {}, P,
                          bioconda_pkg="salmon", biotools_id="salmon")]
    build_graph(nodes, [], db, staging_dir=tmp_path / "stg")
    with KuzuMethodsGraphProvider(db) as prov:
        assert prov._method_ids_matching(["salmon"]) == method_ids_matching(prov._conn, ["salmon"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_seed.py -x -q`
Expected: FAIL with `ImportError: cannot import name 'method_ids_matching'`.

- [ ] **Step 3: Add the pure helper to `extract/seed.py`**

Append to `src/methods_graph/extract/seed.py` (this is the body of the provider's `_method_ids_matching`, with `self._conn` → `conn`):

```python
def method_ids_matching(conn: kuzu.Connection, keywords: list[str]) -> list[str]:
    """Resolve keywords to Method ids: direct name/property substring hits, plus
    methods that reach a matched non-method entity within 1-2 outward hops
    (asymmetric — covers Method-PERFORMS->ChildOp-IS_A->ParentOp), plus matched
    Assumption nodes seeded directly. Deduped, order-preserving. Read-only."""
    ids: list[str] = []
    for kw in keywords:
        all_rows = conn.execute(
            "MATCH (n:Entity) "
            "WHERE contains(lower(n.name), lower($kw)) "
            "   OR contains(lower(n.properties), lower($kw)) "
            "RETURN n.id, n.kind ORDER BY n.id",
            parameters={"kw": kw},
        )
        direct_method_ids: list[str] = []
        non_method_ids: list[str] = []
        matched_assumption_ids: list[str] = []
        for row in all_rows:
            nid, kind = row[0], row[1]
            if kind == "Method":
                direct_method_ids.append(nid)
            else:
                non_method_ids.append(nid)
                if kind == "Assumption":
                    matched_assumption_ids.append(nid)
        ids.extend(direct_method_ids)
        if non_method_ids:
            resolved = conn.execute(
                "MATCH (meth:Entity {kind:'Method'})-[r:Rel*1..2]->(x:Entity) "
                "WHERE list_contains($matched, x.id) "
                "RETURN DISTINCT meth.id ORDER BY meth.id",
                parameters={"matched": non_method_ids},
            )
            ids.extend(row[0] for row in resolved)
        ids.extend(matched_assumption_ids)
    return list(dict.fromkeys(ids))
```

- [ ] **Step 4: Make the provider delegate (behavior-preserving)**

In `src/methods_graph/provider/quration_provider.py`, add to the imports near the top (where `seed`/`to_rag_text`/`method_neighborhood` are imported from `methods_graph.extract.seed`):

```python
from methods_graph.extract.seed import method_ids_matching
```

Replace the entire body of `_method_ids_matching` (lines 219-275) with:

```python
    def _method_ids_matching(self, keywords: list[str]) -> list[str]:
        return method_ids_matching(self._conn, keywords)
```

- [ ] **Step 5: Run tests to verify they pass (and no regression)**

Run: `.venv/bin/pytest tests/test_seed.py tests/test_provider.py -q`
Expected: PASS (new tests green; existing provider tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/extract/seed.py src/methods_graph/provider/quration_provider.py tests/test_seed.py
git commit -m "refactor(seed): lift keyword resolver to pure method_ids_matching helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `Executor` and `Suggestion` dataclasses

**Files:**
- Create: `src/methods_graph/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_planner.py` with:

```python
import json
from methods_graph.planner import Executor, Suggestion


def test_executor_to_dict_is_json_serializable():
    e = Executor("m:star", "star", container="quay.io/biocontainers/star:2.7")
    d = e.to_dict()
    assert d == {"method_id": "m:star", "name": "star", "container": "quay.io/biocontainers/star:2.7"}
    json.dumps(d)  # must not raise


def test_suggestion_to_dict_round_trips():
    s = Suggestion(
        module_id="mod:sort", module_name="samtools sort",
        chosen_executor=Executor("m:samtools", "samtools"),
        alternatives=[Executor("m:alt", "alt")],
        rank_signal={"kind": "downstream", "count": 2},
        evidence=["rnaseq", "sarek"],
        assumptions=[{"id": "assum:x", "name": "normality", "via": []}],
        why="after star_align, 2 pipeline(s) run samtools sort next",
    )
    d = s.to_dict()
    assert d["chosen_executor"]["container"] is None
    assert d["alternatives"][0]["method_id"] == "m:alt"
    assert d["rank_signal"]["count"] == 2
    json.dumps(d)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_planner.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.planner'`.

- [ ] **Step 3: Create `planner.py` with the dataclasses**

Create `src/methods_graph/planner.py`:

```python
"""Method-layer planner: advisory, attestation-ranked next-step suggestions.

Pure / deterministic / read-only over a built Kùzu methods graph. Given a frontier
(the Module step-nodes and/or EDAM Format/Data nodes the user currently has),
expand() returns the attestation-ranked next analysis steps, each resolved to a
concrete executor (the wrapped Method) with its container and inherited assumptions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import kuzu

from methods_graph.extract.seed import method_ids_matching, method_neighborhood


@dataclass(frozen=True)
class Executor:
    method_id: str
    name: str
    container: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"method_id": self.method_id, "name": self.name, "container": self.container}


@dataclass(frozen=True)
class Suggestion:
    module_id: str
    module_name: str
    chosen_executor: Executor
    alternatives: list[Executor] = field(default_factory=list)
    rank_signal: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "chosen_executor": self.chosen_executor.to_dict(),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "rank_signal": self.rank_signal,
            "evidence": self.evidence,
            "assumptions": self.assumptions,
            "why": self.why,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_planner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/planner.py tests/test_planner.py
git commit -m "feat(planner): Executor + Suggestion dataclasses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Candidate gathering (`_candidates`) — continue + start, ranked

**Files:**
- Modify: `src/methods_graph/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test (introduces the shared fixture)**

Add to `tests/test_planner.py`:

```python
import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.planner import _candidates

P = Provenance("test", "x", "2026-06-14")


def _ds(pipelines, attestations):
    return {"pipelines": pipelines, "attestations": attestations,
            "derivation": "io_inferred", "confidence": 0.5}


def build_fixture(tmp_path):
    """A small but representative master-graph slice.

    Modules: align, sort, index, fastqc, multiqc, multi(wraps 2 methods).
    Wiring:  align -> sort (att 2), align -> index (att 1), sort -> multiqc (att 1).
    Cold start: m:star and m:fastqc both INPUT fmt:fastq.
    Popularity: HAS_MODULE so fastqc=2, align=2 pipelines.
    Executors: m:samtools has a container; m:multiqc has an inherited assumption.
    """
    nodes = [
        NodeRecord("mod:align", "STAR align", NodeKind.MODULE, {}, P),
        NodeRecord("mod:sort", "samtools sort", NodeKind.MODULE, {}, P),
        NodeRecord("mod:index", "samtools index", NodeKind.MODULE, {}, P),
        NodeRecord("mod:fastqc", "fastqc", NodeKind.MODULE, {}, P),
        NodeRecord("mod:multiqc", "multiqc", NodeKind.MODULE, {}, P),
        NodeRecord("mod:multi", "multi-wrap", NodeKind.MODULE, {}, P),
        MethodRecord("m:star", "star", NodeKind.METHOD, {}, P, bioconda_pkg="star"),
        MethodRecord("m:samtools", "samtools", NodeKind.METHOD, {}, P, bioconda_pkg="samtools"),
        MethodRecord("m:fastqc", "fastqc", NodeKind.METHOD, {}, P, bioconda_pkg="fastqc"),
        MethodRecord("m:multiqc", "multiqc", NodeKind.METHOD, {}, P, bioconda_pkg="multiqc"),
        MethodRecord("m:aaa", "aaa", NodeKind.METHOD, {}, P, bioconda_pkg="aaa"),
        MethodRecord("m:bbb", "bbb", NodeKind.METHOD, {}, P, bioconda_pkg="bbb"),
        NodeRecord("fmt:fastq", "FASTQ", NodeKind.FORMAT, {}, P),
        NodeRecord("pipe:rnaseq", "rnaseq", NodeKind.PIPELINE, {}, P),
        NodeRecord("pipe:sarek", "sarek", NodeKind.PIPELINE, {}, P),
        NodeRecord("cont:samtools", "samtools-container", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/samtools:1.17"}, P),
        NodeRecord("sm:rank", "rank test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:norm", "normality", NodeKind.ASSUMPTION, {}, P),
    ]
    edges = [
        EdgeRecord("mod:align", "m:star", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:sort", "m:samtools", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:index", "m:samtools", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:fastqc", "m:fastqc", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multiqc", "m:multiqc", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multi", "m:aaa", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multi", "m:bbb", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:align", "mod:sort", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq", "sarek"], 2), P),
        EdgeRecord("mod:align", "mod:index", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq"], 1), P),
        EdgeRecord("mod:sort", "mod:multiqc", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq"], 1), P),
        EdgeRecord("m:star", "fmt:fastq", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:fastqc", "fmt:fastq", EdgeKind.INPUT, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:fastqc", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:align", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:sort", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:fastqc", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:align", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:index", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("m:samtools", "cont:samtools", EdgeKind.PACKAGED_AS, {}, P),
        EdgeRecord("m:multiqc", "sm:rank", EdgeKind.USES_STATISTICAL_METHOD, {"evidence": "doi:10.x"}, P),
        EdgeRecord("sm:rank", "assum:norm", EdgeKind.REQUIRES_ASSUMPTION, {"evidence": "doi:10.y"}, P),
    ]
    db = tmp_path / "mg.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_candidates_continue_ranks_by_attestation(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["mod:align"], set())
    ids = [c.module_id for c in cands]
    assert ids == ["mod:sort", "mod:index"]            # 2 attestations before 1
    assert cands[0].kind == "downstream"
    assert cands[0].count == 2
    assert cands[0].evidence == ["rnaseq", "sarek"]


def test_candidates_start_from_data_two_hop_ranks_by_popularity(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["fmt:fastq"], set())
    ids = [c.module_id for c in cands]
    # m:star->mod:align and m:fastqc->mod:fastqc both accept fmt:fastq (Method-level
    # INPUT, reached via WRAPS). Both have popularity 2 -> tie broken by id asc.
    assert ids == ["mod:align", "mod:fastqc"]
    assert all(c.kind == "entry" and c.count == 2 for c in cands)


def test_candidates_excludes_frontier_and_exclude(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["mod:align"], {"mod:sort"})
    assert [c.module_id for c in cands] == ["mod:index"]   # sort excluded


def test_candidates_deterministic(tmp_path):
    conn = build_fixture(tmp_path)
    a = [c.module_id for c in _candidates(conn, ["mod:align", "fmt:fastq"], set())]
    b = [c.module_id for c in _candidates(conn, ["mod:align", "fmt:fastq"], set())]
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_planner.py -k candidates -x -q`
Expected: FAIL with `ImportError: cannot import name '_candidates'`.

- [ ] **Step 3: Implement `_Candidate` + `_candidates` in `planner.py`**

Add to `src/methods_graph/planner.py`:

```python
@dataclass(frozen=True)
class _Candidate:
    module_id: str
    module_name: str
    kind: str            # "downstream" | "entry"
    count: int
    evidence: list[str]
    source_label: str    # the frontier step name (for the "why" string); "" for entry


def _candidates(conn: kuzu.Connection, frontier_ids: list[str],
                exclude: set[str]) -> list[_Candidate]:
    """Gather + rank next-step candidates from a frontier. Continue (step->step via
    DOWNSTREAM_OF, ranked by attestation count) and start (data->Method INPUT->Module
    WRAPS, ranked by HAS_MODULE popularity) are unified. When a module is reachable
    both ways the downstream (sequencing-evidence) candidate is preferred. Candidates
    in the frontier or `exclude` are dropped. Sorted by (count desc, module_id asc)."""
    blocked = set(frontier_ids) | exclude
    best: dict[str, _Candidate] = {}

    # Continue: frontier Module -DOWNSTREAM_OF-> next Module
    for a_name, b_id, b_name, props in conn.execute(
        "MATCH (a:Entity {kind:'Module'})-[r:Rel {kind:'DOWNSTREAM_OF'}]->(b:Entity {kind:'Module'}) "
        "WHERE list_contains($frontier, a.id) "
        "RETURN a.name, b.id, b.name, r.properties",
        parameters={"frontier": frontier_ids},
    ):
        if b_id in blocked:
            continue
        p = json.loads(props or "{}")
        count = int(p.get("attestations") or len(p.get("pipelines", [])))
        cand = _Candidate(b_id, b_name, "downstream", count,
                          sorted(p.get("pipelines", [])), a_name)
        cur = best.get(b_id)
        if cur is None or count > cur.count:
            best[b_id] = cand

    # Start: frontier Format/Data <-INPUT- Method <-WRAPS- Module
    entry_mods = list(conn.execute(
        "MATCH (mod:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->"
        "(m:Entity {kind:'Method'})-[:Rel {kind:'INPUT'}]->(f:Entity) "
        "WHERE list_contains($frontier, f.id) "
        "RETURN DISTINCT mod.id, mod.name",
        parameters={"frontier": frontier_ids},
    ))
    for mod_id, mod_name in entry_mods:
        if mod_id in blocked or (mod_id in best and best[mod_id].kind == "downstream"):
            continue
        pipes = [r[0] for r in conn.execute(
            "MATCH (p:Entity {kind:'Pipeline'})-[:Rel {kind:'HAS_MODULE'}]->(mod:Entity {id:$mid}) "
            "RETURN p.name ORDER BY p.name",
            parameters={"mid": mod_id},
        )]
        cand = _Candidate(mod_id, mod_name, "entry", len(pipes), pipes, "")
        cur = best.get(mod_id)
        if cur is None or cand.count > cur.count:
            best[mod_id] = cand

    return sorted(best.values(), key=lambda c: (-c.count, c.module_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner.py -k candidates -q`
Expected: PASS (all 4 candidate tests).

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/planner.py tests/test_planner.py
git commit -m "feat(planner): _candidates — continue + start, attestation-ranked

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Executor resolution + enrichment (`_enrich`)

**Files:**
- Modify: `src/methods_graph/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_planner.py` (reuses `build_fixture`):

```python
from methods_graph.planner import _enrich


def test_enrich_picks_min_id_executor_and_lists_alternatives(tmp_path):
    conn = build_fixture(tmp_path)
    chosen, alts, _assum = _enrich(conn, "mod:multi")
    assert chosen.method_id == "m:aaa"               # min id
    assert [a.method_id for a in alts] == ["m:bbb"]


def test_enrich_resolves_container_when_present(tmp_path):
    conn = build_fixture(tmp_path)
    chosen, _alts, _assum = _enrich(conn, "mod:sort")
    assert chosen.method_id == "m:samtools"
    assert chosen.container == "quay.io/biocontainers/samtools:1.17"


def test_enrich_container_none_when_absent(tmp_path):
    conn = build_fixture(tmp_path)
    chosen, _alts, _assum = _enrich(conn, "mod:align")
    assert chosen.container is None                   # m:star has no PACKAGED_AS


def test_enrich_surfaces_inherited_assumptions(tmp_path):
    conn = build_fixture(tmp_path)
    _chosen, _alts, assumptions = _enrich(conn, "mod:multiqc")
    assert [a["id"] for a in assumptions] == ["assum:norm"]
    assert assumptions[0]["via"][0]["statistical_method"] == "rank test"


def test_enrich_returns_none_when_module_wraps_no_method(tmp_path):
    conn = build_fixture(tmp_path)
    # fmt:fastq is not a module and wraps nothing -> defensive None.
    chosen, alts, assumptions = _enrich(conn, "fmt:fastq")
    assert chosen is None and alts == [] and assumptions == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_planner.py -k enrich -x -q`
Expected: FAIL with `ImportError: cannot import name '_enrich'`.

- [ ] **Step 3: Implement `_enrich` in `planner.py`**

Add to `src/methods_graph/planner.py`:

```python
def _enrich(conn: kuzu.Connection, module_id: str):
    """Resolve a Module to its executor(s) via WRAPS and enrich the chosen one.

    Returns (chosen: Executor | None, alternatives: list[Executor],
    assumptions: list[dict]). chosen is the min-id wrapped Method (deterministic);
    its container (via PACKAGED_AS) and inherited assumptions come from one
    method_neighborhood call. Returns (None, [], []) if the module wraps no method."""
    rows = list(conn.execute(
        "MATCH (mod:Entity {id:$mid})-[:Rel {kind:'WRAPS'}]->(m:Entity {kind:'Method'}) "
        "RETURN m.id, m.name ORDER BY m.id",
        parameters={"mid": module_id},
    ))
    if not rows:
        return None, [], []
    execs = [Executor(r[0], r[1]) for r in rows]
    base, alternatives = execs[0], execs[1:]

    nb = method_neighborhood(conn, base.method_id)
    containers = nb.get("containers", [])
    container = None
    if containers:
        c0 = containers[0]
        container = c0["properties"].get("image_name", c0["name"])
    chosen = Executor(base.method_id, base.name, container)
    assumptions = [
        {"id": a["id"], "name": a["name"], "via": a.get("via", [])}
        for a in nb.get("assumptions", [])
    ]
    return chosen, alternatives, assumptions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner.py -k enrich -q`
Expected: PASS (all 5 enrich tests).

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/planner.py tests/test_planner.py
git commit -m "feat(planner): _enrich — WRAPS executor pick + container/assumptions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: The `expand` public API

**Files:**
- Modify: `src/methods_graph/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_planner.py`:

```python
from methods_graph.planner import expand, Suggestion


def test_expand_continue_returns_ranked_suggestions(tmp_path):
    conn = build_fixture(tmp_path)
    out = expand(conn, ["mod:align"])
    assert [s.module_id for s in out] == ["mod:sort", "mod:index"]
    assert all(isinstance(s, Suggestion) for s in out)
    top = out[0]
    assert top.chosen_executor.method_id == "m:samtools"
    assert top.chosen_executor.container == "quay.io/biocontainers/samtools:1.17"
    assert top.rank_signal == {"kind": "downstream", "count": 2}
    assert top.evidence == ["rnaseq", "sarek"]
    assert "samtools sort" in top.why and "mod:align" not in top.why  # uses names, not ids


def test_expand_surfaces_assumptions_on_executor(tmp_path):
    conn = build_fixture(tmp_path)
    out = expand(conn, ["mod:sort"])
    assert [s.module_id for s in out] == ["mod:multiqc"]
    assert [a["id"] for a in out[0].assumptions] == ["assum:norm"]


def test_expand_respects_limit(tmp_path):
    conn = build_fixture(tmp_path)
    out = expand(conn, ["mod:align"], limit=1)
    assert [s.module_id for s in out] == ["mod:sort"]


def test_expand_empty_frontier_returns_empty(tmp_path):
    conn = build_fixture(tmp_path)
    assert expand(conn, []) == []


def test_expand_no_outgoing_returns_empty(tmp_path):
    conn = build_fixture(tmp_path)
    assert expand(conn, ["mod:index"]) == []   # index has no DOWNSTREAM_OF out


def test_expand_skips_executorless_candidate_but_keeps_limit(tmp_path):
    conn = build_fixture(tmp_path)
    # mod:align is excluded; from fmt:fastq the entry candidates both have executors.
    out = expand(conn, ["fmt:fastq"], limit=10)
    assert [s.module_id for s in out] == ["mod:align", "mod:fastqc"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_planner.py -k expand -x -q`
Expected: FAIL with `ImportError: cannot import name 'expand'`.

- [ ] **Step 3: Implement `expand` in `planner.py`**

Add to `src/methods_graph/planner.py`:

```python
def expand(conn: kuzu.Connection, frontier_ids: list[str], *,
           limit: int = 10, exclude: set[str] | None = None) -> list[Suggestion]:
    """Suggest the attestation-ranked next analysis steps from the current frontier.

    frontier_ids: the nodes the user "has" — Module step ids and/or EDAM Format/Data
        ids, order-insensitive. Returns up to `limit` Suggestions sorted by
        (rank_signal.count desc, module_id asc); candidates already in frontier_ids
        or `exclude` are dropped. Read-only, deterministic, no network.
    """
    cands = _candidates(conn, list(frontier_ids), exclude or set())
    out: list[Suggestion] = []
    for c in cands:
        if len(out) >= limit:
            break
        chosen, alternatives, assumptions = _enrich(conn, c.module_id)
        if chosen is None:
            continue  # module wraps no executable method; skip
        if c.kind == "downstream":
            why = f"after {c.source_label}, {c.count} pipeline(s) run {c.module_name} next"
        else:
            why = f"{c.count} pipeline(s) start with {c.module_name}"
        out.append(Suggestion(
            module_id=c.module_id, module_name=c.module_name,
            chosen_executor=chosen, alternatives=alternatives,
            rank_signal={"kind": c.kind, "count": c.count},
            evidence=c.evidence, assumptions=assumptions, why=why,
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner.py -q`
Expected: PASS (entire planner test file green).

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/planner.py tests/test_planner.py
git commit -m "feat(planner): expand() — assemble ranked Suggestions with why

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `seed_from_edge` causal-edge adapter

**Files:**
- Modify: `src/methods_graph/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_planner.py`:

```python
from methods_graph.planner import seed_from_edge


def test_seed_from_edge_includes_dataset_format_and_maps_keywords_to_modules(tmp_path):
    conn = build_fixture(tmp_path)
    edge = {"source_label": "STAR", "target_label": "aligned reads", "relation": "aligns"}
    frontier = seed_from_edge(conn, edge, dataset_format="fmt:fastq")
    assert "fmt:fastq" in frontier            # dataset always seeded
    assert "mod:align" in frontier            # "star" -> m:star -> mod:align (via WRAPS)


def test_seed_from_edge_dataset_only_when_no_keyword_hits(tmp_path):
    conn = build_fixture(tmp_path)
    edge = {"source_label": "zzzznomatch", "target_label": "", "relation": ""}
    assert seed_from_edge(conn, edge, dataset_format="fmt:fastq") == ["fmt:fastq"]


def test_seed_from_edge_empty_when_nothing_resolves(tmp_path):
    conn = build_fixture(tmp_path)
    assert seed_from_edge(conn, {"source_label": "zzzznomatch"}) == []


def test_seed_from_edge_accepts_object_edge(tmp_path):
    conn = build_fixture(tmp_path)
    class E:
        source_label = "STAR"; target_label = ""; relation = ""
    frontier = seed_from_edge(conn, E(), dataset_format="fmt:fastq")
    assert "fmt:fastq" in frontier and "mod:align" in frontier
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_planner.py -k seed_from_edge -x -q`
Expected: FAIL with `ImportError: cannot import name 'seed_from_edge'`.

- [ ] **Step 3: Implement `seed_from_edge` in `planner.py`**

Add to `src/methods_graph/planner.py`:

```python
def seed_from_edge(conn: kuzu.Connection, edge: Any, *,
                   dataset_format: str | None = None) -> list[str]:
    """Map a quration causal edge (+ optional dataset format) to an expand() frontier.

    Reads `source_label`, `target_label`, `relation` (dict keys or attributes),
    resolves their words to Method ids via method_ids_matching, maps those to their
    Modules (via WRAPS), and prepends the dataset Format id. Deduped, order-preserving.
    Deliberately thin — quration owns the causal layer; biological entity labels often
    don't match method vocabulary, so the dataset_format is the reliable seed."""
    def _get(key: str):
        return edge.get(key) if isinstance(edge, dict) else getattr(edge, key, None)

    labels = [str(_get(k)) for k in ("source_label", "target_label", "relation") if _get(k)]
    keywords = [w for label in labels for w in label.replace("-", " ").replace("_", " ").split()]

    frontier: list[str] = []
    if dataset_format:
        frontier.append(dataset_format)
    method_ids = method_ids_matching(conn, keywords) if keywords else []
    if method_ids:
        for row in conn.execute(
            "MATCH (mod:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->(m:Entity) "
            "WHERE list_contains($mids, m.id) "
            "RETURN DISTINCT mod.id ORDER BY mod.id",
            parameters={"mids": method_ids},
        ):
            frontier.append(row[0])
    return list(dict.fromkeys(frontier))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_planner.py -k seed_from_edge -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/planner.py tests/test_planner.py
git commit -m "feat(planner): seed_from_edge — thin causal-edge -> frontier adapter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `mg suggest` CLI subcommand

**Files:**
- Modify: `src/methods_graph/cli.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_planner.py`:

```python
import json as _json
from methods_graph.cli import main


def test_cli_suggest_prints_ranked_json(tmp_path, capsys):
    conn = build_fixture(tmp_path)
    conn.close()                                   # release; CLI reopens read-only
    rc = main(["suggest", "--db", str(tmp_path / "mg.kuzu"),
               "--have", "mod:align", "--limit", "5"])
    assert rc == 0
    out = _json.loads(capsys.readouterr().out)
    assert [s["module_id"] for s in out] == ["mod:sort", "mod:index"]
    assert out[0]["chosen_executor"]["method_id"] == "m:samtools"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_planner.py -k cli_suggest -x -q`
Expected: FAIL — argparse exits non-zero on the unknown `suggest` subcommand (SystemExit), so the test errors/fails.

- [ ] **Step 3: Add `cmd_suggest` to `cli.py`**

Add this function next to `cmd_methods` in `src/methods_graph/cli.py`:

```python
def cmd_suggest(*, db_path: Path, have: list[str], limit: int) -> None:
    """Print attestation-ranked next-step suggestions for the given frontier as JSON."""
    import kuzu
    from methods_graph.planner import expand

    db = kuzu.Database(str(db_path), read_only=True)
    conn = kuzu.Connection(db)
    try:
        suggestions = expand(conn, have, limit=limit)
    finally:
        conn.close()
        db.close()
    print(json.dumps([s.to_dict() for s in suggestions], indent=2))
```

- [ ] **Step 4: Register the subparser**

In `main()`, after the `methods` subparser block (around line 609), add:

```python
    sg = sub.add_parser("suggest",
                        help="suggest attestation-ranked next analysis steps from a frontier")
    sg.add_argument("--db", type=Path, default=Path("data/methods.kuzu"),
                    help="path to the Kùzu database directory")
    sg.add_argument("--have", action="append", dest="have", required=True, metavar="ID",
                    help="a node id you have: a Module step id or EDAM Format/Data id (repeatable)")
    sg.add_argument("--limit", type=int, default=10, help="max suggestions (default: 10)")
```

In the dispatch chain (after the `methods` branch), add:

```python
    elif args.cmd == "suggest":
        cmd_suggest(db_path=args.db, have=args.have, limit=args.limit)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_planner.py -k cli_suggest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/cli.py tests/test_planner.py
git commit -m "feat(cli): mg suggest — print ranked next-step suggestions as JSON

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Final verification + whole-implementation review

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all green (prior 297 passed/1 skipped + the new planner/seed tests), no regressions.

- [ ] **Step 2: Smoke-test the CLI against the real graph (if a built DB exists)**

If a real DB is available (e.g. `/private/tmp/mgreal/rnaseq.kuzu` from prior sessions), run:

```bash
.venv/bin/python -m methods_graph.cli suggest --db /private/tmp/mgreal/rnaseq.kuzu \
  --have mod:star_align --limit 5
```

Expected: a JSON array of suggestions (or `[]` if that exact id isn't present — pick a real `mod:` id via `mg query`/inspection first). This is a sanity check, not a gating test (no network, no fixture).

- [ ] **Step 3: Dispatch a whole-implementation code review**

Per subagent-driven-development, dispatch a final reviewer over the full diff (`git diff <branch-point>..HEAD -- src/methods_graph/planner.py src/methods_graph/extract/seed.py src/methods_graph/provider/quration_provider.py src/methods_graph/cli.py tests/`). Focus: determinism (no clock/random; sorted outputs), read-only safety, the dual-reachable "downstream preferred" tie rule, executor-less skip honoring `limit`, behavior-preserving helper lift. Fix any findings and re-run the suite.

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to present completion options.

---

## Self-Review (checklist run against the spec)

**Spec coverage:** Goal 1 `expand` → Tasks 3-5. Goal 2 two unified sources → Task 3. Goal 3 executor + enrichment → Task 4. Goal 4 `seed_from_edge` → Task 6. Goal 5 CLI → Task 7. Goal 6 pure/deterministic/fixture-tested → every task's tests + Task 8 review. Goal 7 no DDL / no regression → Task 8 full suite. The refactor (lift `_method_ids_matching`) → Task 1.

**Placeholder scan:** none — every code step shows complete code; every run step gives the command + expected outcome.

**Type/name consistency:** `Executor(method_id, name, container)`, `Suggestion(module_id, module_name, chosen_executor, alternatives, rank_signal, evidence, assumptions, why)`, `_Candidate(module_id, module_name, kind, count, evidence, source_label)`, `_candidates(conn, frontier_ids, exclude)`, `_enrich(conn, module_id) -> (chosen|None, alternatives, assumptions)`, `expand(conn, frontier_ids, *, limit, exclude)`, `seed_from_edge(conn, edge, *, dataset_format)`, `method_ids_matching(conn, keywords)` — names are identical across definition, tests, and call sites.

**Verified-fact alignment:** cold start uses Method-level `INPUT` then `WRAPS` (Correction 1 → Task 3 query + `test_candidates_start_from_data_two_hop_ranks_by_popularity`); container via `method_neighborhood` `PACKAGED_AS`, no attribute (Correction 2 → Task 4 `test_enrich_container_*`); helper lift behavior-preserving (Task 1 `test_provider_delegates_to_helper`).
