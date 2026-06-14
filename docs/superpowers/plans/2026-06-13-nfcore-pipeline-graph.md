# nf-core Pipeline Graph (Sub-project A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose nf-core pipelines into the existing KG's shared module nodes and overlay their step-ordering into one connected, typed, attested master graph (`Pipeline` + `HAS_MODULE` + `DOWNSTREAM_OF`).

**Architecture:** A new offline connector `parse_pipeline` reads a pipeline checkout's `modules.json` + vendored module `meta.yml`s, emits a `Pipeline` node, `HAS_MODULE` membership edges (joined via each module's meta.yml `name`), and per-pipeline `DOWNSTREAM_OF` wiring inferred from module I/O type-overlap (Option 2). A separate post-`resolve` reducer accumulates attestation counts. Module I/O coverage is first improved so the inference has data to work with. No DDL change — new `kind` values flow through the generic `Entity`/`Rel` tables; metadata lives in the JSON `properties`.

**Tech Stack:** Python 3, `pyyaml`, `polars`, `kuzu`, `pytest`. Determinism rules: no `datetime.now()`/`random` in pure code (timestamps injected as `ingested_at`); sorted iteration.

**Spec:** [docs/superpowers/specs/2026-06-13-nfcore-pipeline-graph-design.md](../specs/2026-06-13-nfcore-pipeline-graph-design.md)

**Locked decisions:** Q1 `DOWNSTREAM_OF` = producer→consumer; Q2 corpus starts with `rnaseq`+`sarek`+`scrnaseq` (real builds) + a synthetic fixture (tests); Q3 ship plain Option 2; Q4 seed the format map below, raw-pattern `Format` fallback otherwise. MVP `DOWNSTREAM_OF` is **module-level** (`mod:` → `mod:`); the planner (Sub-project B) hops module→method via `WRAPS`.

---

## File Structure

- `src/methods_graph/connectors/nfcore.py` — **modify**: add a pattern→EDAM-format map + I/O-pattern fallback so modules with only `type`/`pattern` (no `ontologies`) still get `INPUT`/`OUTPUT` edges and any needed synthetic `Format` nodes.
- `src/methods_graph/connectors/nfcore_pipeline.py` — **create**: `parse_pipeline(pipeline_dir, *, ingested_at)` → `Pipeline` node + `HAS_MODULE` + per-pipeline `DOWNSTREAM_OF`.
- `src/methods_graph/pipeline_merge.py` — **create**: `merge_downstream_of(edges)` pure reducer (attestation accumulation; runs AFTER `resolve`).
- `src/methods_graph/fetch.py` — **modify**: `fetch_nfcore_pipeline(...)`; extend `write_manifest` with a `nfcore_pipelines` source key.
- `src/methods_graph/cli.py` — **modify**: `--nfcore-pipelines` arg + discovery loop in `cmd_build`; call `merge_downstream_of` after `resolve`; thread pipeline fetch into `cmd_fetch`.
- `src/methods_graph/audit.py` — **modify**: 5 pipeline invariants (4 Cypher tuples + 1 Python attestation check).
- `tests/fixtures/nfcore_pipeline/mini/` — **create**: `modules.json` + vendored `modules/nf-core/<tool>/meta.yml` shaped as a known small DAG.
- `tests/test_nfcore_pipeline.py`, `tests/test_pipeline_merge.py` — **create**.
- `tests/test_nfcore.py`, `tests/test_integration.py`, `tests/test_audit.py`, `tests/test_fetch.py` — **modify**: extend with new behavior.

Run all tests with: `.venv/bin/pytest -q` (from repo root).

---

## Task 1: Plumbing — I/O fallback from `type`/`pattern` in the module connector

**Why:** `parse_module` today reads I/O EDAM ids **only** from the meta.yml `ontologies` key ([nfcore.py:237-250](../../../src/methods_graph/connectors/nfcore.py#L237-L250)), so the `salmon_quant` fixture (`pattern: "*.fastq.gz"` / `"*.sf"`, no `ontologies`) produces **zero** `INPUT`/`OUTPUT` edges. The wiring inference in Task 2 needs these, so add a pattern fallback.

**Files:**
- Modify: `src/methods_graph/connectors/nfcore.py`
- Test: `tests/test_nfcore.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_nfcore.py`:

```python
def test_parse_module_io_from_pattern_when_no_ontologies():
    """salmon_quant has type/pattern but no ontologies; pattern fallback must
    still emit INPUT (FASTQ→known EDAM fmt) and OUTPUT (*.sf→synthetic Format)."""
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)

    inputs = {e.to_id for e in edges if e.kind == EdgeKind.INPUT and e.from_id == method.id}
    outputs = {e.to_id for e in edges if e.kind == EdgeKind.OUTPUT and e.from_id == method.id}

    # *.fastq.gz maps to a known EDAM format id (node provided by EDAM ingestion).
    assert "fmt:format_1930" in inputs
    # *.sf has no EDAM mapping → synthetic Format node, which MUST also be emitted.
    assert "fmt:pat:.sf" in outputs
    fmt_node = next(n for n in nodes if n.id == "fmt:pat:.sf")
    assert fmt_node.kind == NodeKind.FORMAT

def test_parse_module_ontology_io_still_wins():
    """fastp_io declares EDAM ontology URIs; those must still be emitted
    (the pattern fallback must not regress ontology-based extraction)."""
    nodes, edges = parse_module(FASTP_IO_MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    inputs = {e.to_id for e in edges if e.kind == EdgeKind.INPUT and e.from_id == method.id}
    outputs = {e.to_id for e in edges if e.kind == EdgeKind.OUTPUT and e.from_id == method.id}
    assert "fmt:format_1930" in inputs   # from ontologies
    assert "fmt:format_3464" in outputs  # from ontologies
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_nfcore.py::test_parse_module_io_from_pattern_when_no_ontologies -v`
Expected: FAIL — `assert "fmt:format_1930" in inputs` fails (inputs is empty for salmon_quant today).

- [ ] **Step 3: Add the pattern→EDAM map and helpers in `nfcore.py`**

After the `_EDAM_PREFIX_MAP` definition (≈line 48) add:

```python
# Glob-suffix → EDAM format id.  Seeded with the common genomics formats
# (spec Q4); anything not here falls back to a synthetic Format node so the
# I/O contract is still expressed.  Keys are lowercased extensions WITHOUT the
# leading '*'.
_PATTERN_TO_FMT: dict[str, str] = {
    ".fastq.gz": "fmt:format_1930", ".fq.gz": "fmt:format_1930",
    ".fastq": "fmt:format_1930", ".fq": "fmt:format_1930",
    ".fasta": "fmt:format_1929", ".fa": "fmt:format_1929", ".fna": "fmt:format_1929",
    ".bam": "fmt:format_2572", ".sam": "fmt:format_2573", ".cram": "fmt:format_3462",
    ".vcf.gz": "fmt:format_3016", ".vcf": "fmt:format_3016", ".bcf": "fmt:format_3020",
    ".bed": "fmt:format_3003", ".gtf": "fmt:format_2306",
    ".gff3": "fmt:format_2305", ".gff": "fmt:format_2305",
    ".bw": "fmt:format_3006", ".bigwig": "fmt:format_3006",
}


def _normalize_pattern_ext(pattern: str) -> str:
    """'*.fastq.gz' → '.fastq.gz' (lowercased, leading glob stripped)."""
    p = pattern.strip().lower()
    star = p.rfind("*")
    if star != -1:
        p = p[star + 1:]
    if not p.startswith("."):
        p = "." + p.lstrip(".")
    return p


def _pattern_to_fmt_id(pattern: str) -> str:
    """Map a glob to a known EDAM fmt: id, else a synthetic 'fmt:pat:<ext>' id.

    Longest matching suffix wins so '.vcf.gz' beats '.gz' (when present).
    """
    ext = _normalize_pattern_ext(pattern)
    for known in sorted(_PATTERN_TO_FMT, key=len, reverse=True):
        if ext.endswith(known):
            return _PATTERN_TO_FMT[known]
    return f"fmt:pat:{ext}"


def _collect_io_patterns(section: Any) -> list[str]:
    """Recursively collect every 'pattern' string in an input/output section.

    Tolerates the same irregular shapes as _collect_ontology_edam_uris
    (list, list-of-lists, channel-dicts).
    """
    patterns: list[str] = []
    if isinstance(section, list):
        for item in section:
            patterns.extend(_collect_io_patterns(item))
    elif isinstance(section, dict):
        pat = section.get("pattern")
        if isinstance(pat, str) and pat:
            patterns.append(pat)
        for k, v in section.items():
            if k != "pattern" and isinstance(v, (dict, list)):
                patterns.extend(_collect_io_patterns(v))
    return patterns
```

- [ ] **Step 4: Wire the fallback into `_io_edam_ids` and emit synthetic Format nodes**

Inside `parse_module`, the nested `_io_edam_ids` helper (≈237-247) currently returns only ontology ids. Replace its body and the two call sites so each section yields `(ids, synthetic_format_nodes)`:

```python
    def _io_targets(section_key: str) -> tuple[list[str], list[NodeRecord]]:
        # 1. EDAM ontology URIs (existing behaviour — these nodes already exist
        #    in the graph from EDAM ingestion, so no synthetic node is needed).
        raw_uris = _collect_ontology_edam_uris(meta.get(section_key))
        onto_ids = {
            nid for uri in raw_uris
            if (nid := _edam_uri_to_node_id(uri)) is not None
            and (nid.startswith("data:") or nid.startswith("fmt:"))
        }
        # 2. type/pattern fallback for channels that declare no ontologies.
        synth: list[NodeRecord] = []
        pat_ids: set[str] = set()
        for pat in _collect_io_patterns(meta.get(section_key)):
            fid = _pattern_to_fmt_id(pat)
            pat_ids.add(fid)
            if fid.startswith("fmt:pat:"):
                # Synthetic Format node so the INPUT/OUTPUT edge is not dangling.
                synth.append(NodeRecord(fid, fid.split(":", 2)[-1], NodeKind.FORMAT,
                                        {"pattern": pat}, prov))
        return sorted(onto_ids | pat_ids), synth

    input_edam_ids, input_synth = _io_targets("input")
    output_edam_ids, output_synth = _io_targets("output")
    # Synthetic Format nodes are deduped downstream by the resolver (by id).
    nodes.extend(input_synth)
    nodes.extend(output_synth)
```

Delete the old `_io_edam_ids` function and its two assignments (`input_edam_ids = _io_edam_ids("input")` / `output_edam_ids = _io_edam_ids("output")`). The existing per-tool edge-emission loop that consumes `input_edam_ids`/`output_edam_ids` (≈318-321) is unchanged.

- [ ] **Step 5: Run the new and existing nfcore tests**

Run: `.venv/bin/pytest tests/test_nfcore.py -v`
Expected: PASS — both new tests pass and all pre-existing `test_nfcore.py` tests still pass (ontology extraction unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/connectors/nfcore.py tests/test_nfcore.py
git commit -m "feat(nfcore): I/O plumbing fallback from type/pattern (+ synthetic Format nodes)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Mini-pipeline fixture

**Why:** Tasks 3-4 and the integration test need an offline pipeline checkout whose inferred wiring is a known small DAG. Reuse the meta.yml shapes the module connector already understands.

**Files:**
- Create: `tests/fixtures/nfcore_pipeline/mini/modules.json`
- Create: `tests/fixtures/nfcore_pipeline/mini/modules/nf-core/fastqc/meta.yml`
- Create: `tests/fixtures/nfcore_pipeline/mini/modules/nf-core/salmon/meta.yml`
- Create: `tests/fixtures/nfcore_pipeline/mini/modules/nf-core/tximport/meta.yml`

- [ ] **Step 1: Create `modules.json`**

`tests/fixtures/nfcore_pipeline/mini/modules.json` — note the keys are **directory paths**, and `installed_by` is what nf-core records:

```json
{
  "name": "nf-core/mini",
  "homePage": "https://github.com/nf-core/mini",
  "repos": {
    "https://github.com/nf-core/modules.git": {
      "modules": {
        "nf-core": {
          "fastqc": { "branch": "master", "git_sha": "aaa", "installed_by": ["fastqc"] },
          "salmon": { "branch": "master", "git_sha": "bbb", "installed_by": ["salmon"] },
          "tximport": { "branch": "master", "git_sha": "ccc", "installed_by": ["tximport"] }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Create the three vendored module `meta.yml` files**

The DAG we want is `fastqc → salmon → tximport`. Note the module `name` fields **deliberately differ from the directory leaf** (`salmon_pe` vs dir `salmon`) to exercise the path→meta.yml-name join.

`tests/fixtures/nfcore_pipeline/mini/modules/nf-core/fastqc/meta.yml`:

```yaml
name: fastqc_qc
description: Quality control
tools:
  - fastqc:
      description: FastQC
      identifier: biotools:fastqc
input:
  - reads:
      type: file
      pattern: "*.fastq.gz"
output:
  - html:
      type: file
      pattern: "*.html"
```

`tests/fixtures/nfcore_pipeline/mini/modules/nf-core/salmon/meta.yml`:

```yaml
name: salmon_pe
description: Quantify expression with Salmon
tools:
  - salmon:
      description: Selective alignment
      identifier: biotools:salmon
input:
  - reads:
      type: file
      pattern: "*.fastq.gz"
output:
  - quant:
      type: file
      pattern: "*.sf"
```

`tests/fixtures/nfcore_pipeline/mini/modules/nf-core/tximport/meta.yml`:

```yaml
name: tximport_agg
description: Aggregate transcript counts to gene level
tools:
  - tximport:
      description: tximport
      identifier: biotools:tximport
input:
  - quant:
      type: file
      pattern: "*.sf"
output:
  - counts:
      type: file
      pattern: "*.tsv"
```

This yields: `fastqc_qc` OUTPUT `{*.html→fmt:pat:.html}`, `salmon_pe` IN `{fastq→fmt:format_1930}` OUT `{*.sf→fmt:pat:.sf}`, `tximport_agg` IN `{*.sf→fmt:pat:.sf}` OUT `{*.tsv→fmt:pat:.tsv}`. So Option-2 inference will find exactly **`salmon_pe → tximport_agg`** (`.sf` overlap) and **`fastqc_qc → salmon_pe`** only if fastqc OUTPUT overlaps salmon INPUT — it does **not** here (`.html` vs `.fastq.gz`), so the one inferred edge is `salmon_pe → tximport_agg`. (This is the honest Option-2 limitation; the test asserts exactly that.)

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/nfcore_pipeline/
git commit -m "test(fixtures): mini nf-core pipeline checkout for pipeline-graph tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `parse_pipeline` — Pipeline node + HAS_MODULE (membership)

**Files:**
- Create: `src/methods_graph/connectors/nfcore_pipeline.py`
- Test: `tests/test_nfcore_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_nfcore_pipeline.py`:

```python
from pathlib import Path

from methods_graph.connectors.nfcore_pipeline import parse_pipeline
from methods_graph.types import NodeKind, EdgeKind

PIPE = Path(__file__).parent / "fixtures" / "nfcore_pipeline" / "mini"


def test_parse_pipeline_emits_pipeline_node():
    nodes, _ = parse_pipeline(PIPE, ingested_at="2026-06-13")
    pipe = next(n for n in nodes if n.kind == NodeKind.PIPELINE)
    assert pipe.id == "pipe:mini"
    assert pipe.properties["n_modules"] == 3


def test_parse_pipeline_has_module_uses_meta_yml_name():
    """HAS_MODULE must target mod:<meta.yml name>, NOT mod:<dir leaf>.
    salmon dir → name 'salmon_pe' → mod:salmon_pe (the riskiest join)."""
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    has_mod = {e.to_id for e in edges if e.kind == EdgeKind.HAS_MODULE}
    assert has_mod == {"mod:fastqc_qc", "mod:salmon_pe", "mod:tximport_agg"}
    assert all(e.from_id == "pipe:mini" for e in edges if e.kind == EdgeKind.HAS_MODULE)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_nfcore_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'methods_graph.connectors.nfcore_pipeline'`.

- [ ] **Step 3: Implement membership in `nfcore_pipeline.py`**

```python
"""Parse an nf-core PIPELINE checkout into Pipeline + HAS_MODULE + DOWNSTREAM_OF.

Reads ``modules.json`` (membership) and each vendored module's ``meta.yml``
(for the canonical ``name`` join key and the I/O contract used to infer
DOWNSTREAM_OF ordering — Option 2, see ``_infer_downstream``).

Offline + deterministic: no network, no clock; ``ingested_at`` is injected.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from methods_graph.connectors.nfcore import _io_module_targets
from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)


def _module_paths_from_modules_json(modules_json: dict[str, Any]) -> list[str]:
    """Return sorted 'nf-core/<path>' module keys from a modules.json."""
    paths: list[str] = []
    for _repo, repo_body in (modules_json.get("repos") or {}).items():
        nfcore = ((repo_body.get("modules") or {}).get("nf-core") or {})
        paths.extend(nfcore.keys())
    return sorted(set(paths))


def _module_name(pipeline_dir: Path, rel_path: str) -> str | None:
    """Read the vendored module's meta.yml `name` (the mod: join key)."""
    meta_path = pipeline_dir / "modules" / "nf-core" / rel_path / "meta.yml"
    if not meta_path.exists():
        return None
    meta = yaml.safe_load(meta_path.read_text()) or {}
    if not isinstance(meta, dict):
        return None
    return meta.get("name", Path(rel_path).name)


def parse_pipeline(
    pipeline_dir: Path,
    *,
    ingested_at: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    pipeline_dir = Path(pipeline_dir)
    name = pipeline_dir.name
    pipe_id = f"pipe:{name}"
    prov = Provenance("nfcore_pipeline",
                      f"https://github.com/nf-core/{name}", ingested_at)

    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = _module_paths_from_modules_json(modules_json)

    # path → mod:<meta.yml name>; drop any path whose meta.yml is missing.
    path_to_modid: dict[str, str] = {}
    for rel in rel_paths:
        mname = _module_name(pipeline_dir, rel)
        if mname:
            path_to_modid[rel] = f"mod:{mname}"

    nodes: list[NodeRecord] = [NodeRecord(
        pipe_id, name, NodeKind.PIPELINE,
        {"url": prov.source_url, "n_modules": len(path_to_modid)}, prov,
    )]
    edges: list[EdgeRecord] = [
        EdgeRecord(pipe_id, mod_id, EdgeKind.HAS_MODULE, {}, prov)
        for mod_id in sorted(path_to_modid.values())
    ]
    return nodes, edges
```

- [ ] **Step 4: Extract a reusable module-I/O helper in `nfcore.py`**

`parse_pipeline` needs each module's I/O sets to infer wiring (Task 4). Factor the Task-1 `_io_targets` logic into a module-level function in `nfcore.py` so both callers share it. Add near the other helpers:

```python
def _io_module_targets(meta: dict[str, Any], section_key: str) -> set[str]:
    """Return the set of EDAM/synthetic-format target ids for a meta.yml
    section ('input' or 'output').  Pure: returns ids only (no node creation).
    Used by the pipeline connector to infer DOWNSTREAM_OF."""
    raw_uris = _collect_ontology_edam_uris(meta.get(section_key))
    ids = {
        nid for uri in raw_uris
        if (nid := _edam_uri_to_node_id(uri)) is not None
        and (nid.startswith("data:") or nid.startswith("fmt:"))
    }
    for pat in _collect_io_patterns(meta.get(section_key)):
        ids.add(_pattern_to_fmt_id(pat))
    return ids
```

(The Task-1 `_io_targets` inside `parse_module` can call `_io_module_targets` for the id set and keep its own synthetic-node creation. Refactor `_io_targets` to: `ids = _io_module_targets(meta, section_key)`, then build `synth` from the `fmt:pat:` ids. This keeps one source of truth for the id logic.)

- [ ] **Step 5: Run to verify membership tests pass**

Run: `.venv/bin/pytest tests/test_nfcore_pipeline.py tests/test_nfcore.py -v`
Expected: PASS — both membership tests pass; Task-1 tests still pass after the refactor.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/connectors/nfcore_pipeline.py src/methods_graph/connectors/nfcore.py tests/test_nfcore_pipeline.py
git commit -m "feat(nfcore-pipeline): Pipeline node + HAS_MODULE membership (meta.yml-name join)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `parse_pipeline` — DOWNSTREAM_OF wiring (Option 2 inference)

**Files:**
- Modify: `src/methods_graph/connectors/nfcore_pipeline.py`
- Test: `tests/test_nfcore_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_nfcore_pipeline.py`:

```python
def test_parse_pipeline_infers_downstream_of_by_io_overlap():
    """salmon_pe OUTPUT *.sf feeds tximport_agg INPUT *.sf → one DOWNSTREAM_OF.
    fastqc_qc OUTPUT *.html does NOT match salmon INPUT → no edge (honest Option-2)."""
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    dse = [e for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF]
    pairs = {(e.from_id, e.to_id) for e in dse}
    assert ("mod:salmon_pe", "mod:tximport_agg") in pairs
    assert ("mod:fastqc_qc", "mod:salmon_pe") not in pairs  # no I/O overlap

    edge = next(e for e in dse if e.from_id == "mod:salmon_pe")
    assert edge.properties["derivation"] == "io_inferred"
    assert edge.properties["pipelines"] == ["mini"]
    assert edge.properties["attestations"] == 1


def test_parse_pipeline_no_self_loops():
    _, edges = parse_pipeline(PIPE, ingested_at="2026-06-13")
    assert all(e.from_id != e.to_id
               for e in edges if e.kind == EdgeKind.DOWNSTREAM_OF)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_nfcore_pipeline.py::test_parse_pipeline_infers_downstream_of_by_io_overlap -v`
Expected: FAIL — no `DOWNSTREAM_OF` edges emitted yet.

- [ ] **Step 3: Add the inference to `parse_pipeline`**

In `nfcore_pipeline.py`, add a helper and extend `parse_pipeline` before `return nodes, edges`:

```python
def _module_io(pipeline_dir: Path, rel_path: str) -> tuple[set[str], set[str]]:
    """(inputs, outputs) EDAM/synthetic-format id sets for a vendored module."""
    meta_path = pipeline_dir / "modules" / "nf-core" / rel_path / "meta.yml"
    meta = yaml.safe_load(meta_path.read_text()) or {}
    if not isinstance(meta, dict):
        return set(), set()
    return _io_module_targets(meta, "input"), _io_module_targets(meta, "output")
```

Then, inside `parse_pipeline`, after building `path_to_modid`:

```python
    # Option-2 wiring: A -DOWNSTREAM_OF-> B when OUTPUT(A) ∩ INPUT(B) ≠ ∅.
    io: dict[str, tuple[set[str], set[str]]] = {
        rel: _module_io(pipeline_dir, rel) for rel in path_to_modid
    }
    seen_pairs: set[tuple[str, str]] = set()
    for a_rel, (_a_in, a_out) in sorted(io.items()):
        for b_rel, (b_in, _b_out) in sorted(io.items()):
            a_id, b_id = path_to_modid[a_rel], path_to_modid[b_rel]
            if a_id == b_id:           # no self-loops (incl. name collisions)
                continue
            if a_out & b_in and (a_id, b_id) not in seen_pairs:
                seen_pairs.add((a_id, b_id))
                edges.append(EdgeRecord(
                    a_id, b_id, EdgeKind.DOWNSTREAM_OF,
                    {"pipelines": [name], "attestations": 1,
                     "derivation": "io_inferred", "confidence": 0.5},
                    prov,
                ))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_nfcore_pipeline.py -v`
Expected: PASS — exactly the `salmon_pe → tximport_agg` edge, no self-loops, correct properties.

- [ ] **Step 5: Determinism test + commit**

Add:

```python
def test_parse_pipeline_deterministic():
    a = parse_pipeline(PIPE, ingested_at="2026-06-13")
    b = parse_pipeline(PIPE, ingested_at="2026-06-13")
    assert [(n.id, n.kind) for n in a[0]] == [(n.id, n.kind) for n in b[0]]
    assert [(e.from_id, e.to_id, e.kind) for e in a[1]] == \
           [(e.from_id, e.to_id, e.kind) for e in b[1]]
```

Run: `.venv/bin/pytest tests/test_nfcore_pipeline.py -v` → PASS, then:

```bash
git add src/methods_graph/connectors/nfcore_pipeline.py tests/test_nfcore_pipeline.py
git commit -m "feat(nfcore-pipeline): Option-2 DOWNSTREAM_OF inference from module I/O overlap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `merge_downstream_of` — attestation accumulation (runs AFTER resolve)

**Why:** The same `(A,B)` ordering can appear in multiple pipelines. After `resolve` has remapped ids and deduped `(from,to,kind)`, this reducer rolls up the per-pipeline metadata. **It does not dedupe** — `resolve` already did (see spec §Attestation merge).

**Files:**
- Create: `src/methods_graph/pipeline_merge.py`
- Test: `tests/test_pipeline_merge.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_merge.py`:

```python
from methods_graph.pipeline_merge import merge_downstream_of
from methods_graph.types import EdgeKind, EdgeRecord, Provenance

P = Provenance("nfcore_pipeline", "u", "2026-06-13")


def _dse(a, b, pipelines, conf=0.5):
    return EdgeRecord(a, b, EdgeKind.DOWNSTREAM_OF,
                      {"pipelines": pipelines, "attestations": len(pipelines),
                       "derivation": "io_inferred", "confidence": conf}, P)


def test_merge_accumulates_attestations():
    edges = [_dse("mod:a", "mod:b", ["rnaseq"], 0.5),
             _dse("mod:a", "mod:b", ["sarek"], 0.7)]
    out = merge_downstream_of(edges)
    merged = [e for e in out if e.kind == EdgeKind.DOWNSTREAM_OF]
    assert len(merged) == 1
    assert merged[0].properties["pipelines"] == ["rnaseq", "sarek"]  # sorted+deduped
    assert merged[0].properties["attestations"] == 2
    assert merged[0].properties["confidence"] == 0.7  # max


def test_merge_leaves_distinct_edges_and_non_downstream_untouched():
    other = EdgeRecord("mod:a", "m:x", EdgeKind.WRAPS, {}, P)
    edges = [_dse("mod:a", "mod:b", ["rnaseq"]),
             _dse("mod:a", "mod:c", ["rnaseq"]), other]
    out = merge_downstream_of(edges)
    dse = {(e.from_id, e.to_id) for e in out if e.kind == EdgeKind.DOWNSTREAM_OF}
    assert dse == {("mod:a", "mod:b"), ("mod:a", "mod:c")}
    assert other in out  # non-DOWNSTREAM_OF edges pass through unchanged
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'methods_graph.pipeline_merge'`.

- [ ] **Step 3: Implement the reducer**

`src/methods_graph/pipeline_merge.py`:

```python
"""Roll up DOWNSTREAM_OF attestation metadata after resolution.

Runs AFTER resolve() (which already remaps ids and dedupes (from,to,kind)).
This step is metadata accumulation ONLY, not deduplication.
"""
from __future__ import annotations

from methods_graph.types import EdgeKind, EdgeRecord


def merge_downstream_of(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    """Return a new edge list with DOWNSTREAM_OF edges sharing (from,to)
    collapsed into one whose ``pipelines`` is the sorted/deduped union,
    ``attestations`` is its length, and ``confidence`` is the max. All other
    edges pass through unchanged and in their original order."""
    out: list[EdgeRecord] = []
    by_pair: dict[tuple[str, str], EdgeRecord] = {}
    for e in edges:
        if e.kind != EdgeKind.DOWNSTREAM_OF:
            out.append(e)
            continue
        key = (e.from_id, e.to_id)
        if key not in by_pair:
            # Copy so the input list is never mutated.
            merged = EdgeRecord(e.from_id, e.to_id, e.kind,
                                dict(e.properties), e.provenance)
            merged.properties.setdefault("pipelines", [])
            merged.properties["pipelines"] = sorted(set(merged.properties["pipelines"]))
            merged.properties["attestations"] = len(merged.properties["pipelines"])
            by_pair[key] = merged
            out.append(merged)
        else:
            merged = by_pair[key]
            pipes = set(merged.properties.get("pipelines", [])) | \
                set(e.properties.get("pipelines", []))
            merged.properties["pipelines"] = sorted(pipes)
            merged.properties["attestations"] = len(pipes)
            merged.properties["confidence"] = max(
                merged.properties.get("confidence", 0.0),
                e.properties.get("confidence", 0.0),
            )
            merged.properties.setdefault("derivation", e.properties.get("derivation"))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_merge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/pipeline_merge.py tests/test_pipeline_merge.py
git commit -m "feat(pipeline-merge): DOWNSTREAM_OF attestation accumulation reducer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Wire pipelines into `cmd_build` (CLI + merge after resolve)

**Files:**
- Modify: `src/methods_graph/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (which already calls `cmd_build` directly — cf. `test_cmd_build_end_to_end`):

```python
from pathlib import Path
from methods_graph.cli import cmd_build
import kuzu

FIX = Path(__file__).parent / "fixtures"


def test_cmd_build_loads_pipeline_graph(tmp_path):
    db = tmp_path / "m.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=FIX / "nfcore_pipeline" / "mini" / "modules" / "nf-core",
        biocontainers=None,
        nfcore_pipelines=FIX / "nfcore_pipeline",
        db_path=db,
        staging_dir=tmp_path / "stage",
        ingested_at="2026-06-13",
    )
    conn = kuzu.Connection(kuzu.Database(str(db), read_only=True))
    pipes = [r[0] for r in conn.execute(
        "MATCH (n:Entity {kind:'Pipeline'}) RETURN n.id")]
    assert "pipe:mini" in pipes
    dse = [r[0] for r in conn.execute(
        "MATCH ()-[r:Rel {kind:'DOWNSTREAM_OF'}]->() RETURN r.kind")]
    assert len(dse) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py::test_cmd_build_loads_pipeline_graph -v`
Expected: FAIL — `cmd_build() got an unexpected keyword argument 'nfcore_pipelines'`.

- [ ] **Step 3: Add the `nfcore_pipelines` parameter + discovery loop**

In `cmd_build`'s signature ([cli.py:46-57](../../../src/methods_graph/cli.py#L46-L57)) add `nfcore_pipelines: Path | None = None,`. Add the path guard alongside the others (≈81-92):

```python
    if nfcore_pipelines is not None and not Path(nfcore_pipelines).exists():
        raise FileNotFoundError(f"--nfcore-pipelines path does not exist: {nfcore_pipelines}")
```

Add the import in the grouped block (≈68-75): `from methods_graph.connectors.nfcore_pipeline import parse_pipeline`. After the biocontainers block (≈137), add the discovery loop — a pipeline dir is any dir directly containing a `modules.json`:

```python
    # --- nf-core pipelines ---
    if nfcore_pipelines is not None:
        for mj in sorted(Path(nfcore_pipelines).rglob("modules.json")):
            nodes, edges = parse_pipeline(mj.parent, ingested_at=ingested_at)
            all_nodes.extend(nodes)
            all_edges.extend(edges)
```

- [ ] **Step 4: Call `merge_downstream_of` AFTER resolve**

Import at the top of the grouped block: `from methods_graph.pipeline_merge import merge_downstream_of`. Immediately after the `resolved_nodes, resolved_edges = resolve(...)` call ([cli.py:160-165](../../../src/methods_graph/cli.py#L160-L165)) and before the bio.tools enrichment block, add:

```python
    # Roll up DOWNSTREAM_OF attestation metadata (after resolve's id-remap+dedup).
    resolved_edges = merge_downstream_of(resolved_edges)
```

- [ ] **Step 5: Add the CLI argument**

In `main()`, in the `build` subparser block (≈588-605), add:

```python
    b.add_argument("--nfcore-pipelines", type=Path, default=None, dest="nfcore_pipelines",
                   help="path to a directory tree of nf-core pipeline checkouts (optional)")
```

And pass it through in the `args.cmd == "build"` dispatch (≈675-685): add `nfcore_pipelines=args.nfcore_pipelines,` to the `cmd_build(...)` call.

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS — pipeline node + ≥1 DOWNSTREAM_OF edge loaded; existing CLI tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/cli.py tests/test_cli.py
git commit -m "feat(cli): --nfcore-pipelines build wiring + post-resolve attestation merge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Audit invariants for the pipeline graph

**Files:**
- Modify: `src/methods_graph/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit.py` (existing tests build a graph then call `audit_graph(conn)`; `AuditResult` has `.invariants: list[Invariant]` and `.ok`, verified against the source):

```python
def test_audit_passes_with_pipeline_graph(tmp_path):
    from methods_graph.cli import cmd_build
    from methods_graph.audit import audit_graph
    import kuzu
    from pathlib import Path

    fix = Path(__file__).parent / "fixtures"
    db = tmp_path / "m.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=fix / "nfcore_pipeline" / "mini" / "modules" / "nf-core",
        biocontainers=None,
        nfcore_pipelines=fix / "nfcore_pipeline",
        db_path=db, staging_dir=tmp_path / "s", ingested_at="2026-06-13",
    )
    conn = kuzu.Connection(kuzu.Database(str(db), read_only=True))
    result = audit_graph(conn)
    names = {i.name for i in result.invariants}
    assert any("HAS_MODULE" in n for n in names)
    assert any("DOWNSTREAM_OF" in n for n in names)
    assert result.ok  # all invariants pass on a well-formed build
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_audit.py::test_audit_passes_with_pipeline_graph -v`
Expected: FAIL — no invariant name contains "HAS_MODULE"/"DOWNSTREAM_OF".

- [ ] **Step 3: Add the four Cypher-tuple invariants**

In `audit.py`, append to the `_invariant_specs` list ([audit.py:259-330](../../../src/methods_graph/audit.py#L259-L330)), before the closing `]`:

```python
        (
            "HAS_MODULE: Pipeline→Module",
            "MATCH (a)-[r:Rel{kind:'HAS_MODULE'}]->(b) "
            "WHERE NOT (a.kind='Pipeline' AND b.kind='Module') RETURN count(*)",
        ),
        (
            "DOWNSTREAM_OF: no self-loops",
            "MATCH (a)-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b) "
            "WHERE a.id = b.id RETURN count(*)",
        ),
        (
            "Pipeline: has >=1 HAS_MODULE",
            "MATCH (p:Entity{kind:'Pipeline'}) "
            "WHERE NOT EXISTS { MATCH (p)-[:Rel{kind:'HAS_MODULE'}]->() } "
            "RETURN count(*)",
        ),
        (
            # Endpoint-kind soundness only. The full I/O-overlap soundness check
            # (OUTPUT(A) ∩ INPUT(B) ≠ ∅) is trivially true under Option-2 inference,
            # so it is deferred to Option 3 (see Deferred).
            "DOWNSTREAM_OF: endpoints are Method/Module",
            "MATCH (a)-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b) "
            "WHERE NOT (a.kind IN ['Method','Module'] AND b.kind IN ['Method','Module']) "
            "RETURN count(*)",
        ),
```

- [ ] **Step 4: Add the Python attestation-consistency check**

After the existing `_bad_evidence_count` registration loop ([audit.py:361-368](../../../src/methods_graph/audit.py#L361-L368)), add:

```python
    # DOWNSTREAM_OF attestation consistency — JSON properties, so computed in
    # Python (Cypher can't introspect the blob).  attestations must equal the
    # length of a non-empty, sorted, deduped pipelines list.
    def _bad_attestation_count() -> int:
        rows = _qall("MATCH ()-[r:Rel{kind:'DOWNSTREAM_OF'}]->() RETURN r.properties")
        n = 0
        for row in rows:
            try:
                props = json.loads(row[0] or "{}")
            except (json.JSONDecodeError, TypeError):
                props = {}
            pipes = props.get("pipelines", [])
            if (not isinstance(pipes, list) or not pipes
                    or pipes != sorted(set(pipes))
                    or props.get("attestations") != len(pipes)):
                n += 1
        return n

    _att_bad = _bad_attestation_count()
    invariants.append(Invariant(
        name="DOWNSTREAM_OF: attestation consistent (attestations==len(pipelines))",
        violations=_att_bad, ok=(_att_bad == 0)))
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_audit.py -v`
Expected: PASS — new invariants present and green; existing audit tests unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/audit.py tests/test_audit.py
git commit -m "feat(audit): pipeline-graph invariants (HAS_MODULE, DOWNSTREAM_OF, attestation)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `fetch_nfcore_pipeline` + `write_manifest` extension

**Files:**
- Modify: `src/methods_graph/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fetch.py` (mirror the existing `fetch_nfcore` test that injects a fake `runner`):

```python
def test_fetch_nfcore_pipeline_clones_and_returns_manifest(tmp_path):
    from methods_graph.fetch import fetch_nfcore_pipeline

    calls = []
    def fake_runner(cmd, **kw):
        calls.append(cmd)
        class R:  # mimic subprocess.CompletedProcess
            stdout = "deadbeef\n"
        # create the clone dir so the "reuse existing" branch is exercised next time
        if cmd[:2] == ["git", "clone"]:
            (tmp_path / "pipelines" / "rnaseq").mkdir(parents=True, exist_ok=True)
        return R()

    m = fetch_nfcore_pipeline("rnaseq", tmp_path, revision="3.14.0",
                              fetched_at="2026-06-13T00:00:00Z", runner=fake_runner)
    assert m["revision"] == "3.14.0"
    assert m["commit"] == "deadbeef"
    assert m["path"].endswith("pipelines/rnaseq")


def test_write_manifest_includes_nfcore_pipelines(tmp_path):
    from methods_graph.fetch import write_manifest
    import json
    p = write_manifest(tmp_path, edam=None, nfcore=None, biocontainers=None,
                       nfcore_pipelines={"rnaseq": {"commit": "x"}},
                       created_at="2026-06-13T00:00:00Z")
    data = json.loads(p.read_text())
    assert data["sources"]["nfcore_pipelines"] == {"rnaseq": {"commit": "x"}}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_fetch.py -k "nfcore_pipeline or nfcore_pipelines" -v`
Expected: FAIL — `cannot import name 'fetch_nfcore_pipeline'` / `write_manifest() got an unexpected keyword argument 'nfcore_pipelines'`.

- [ ] **Step 3: Add `fetch_nfcore_pipeline`**

In `fetch.py`, after `fetch_nfcore` (≈379), add:

```python
def fetch_nfcore_pipeline(
    name: str,
    dest_dir: Path,
    *,
    revision: str,
    fetched_at: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Shallow-clone nf-core/<name> at *revision* into <dest>/pipelines/<name>.

    Reuses fetch_nfcore's pattern (injectable runner, reuse-existing-clone,
    rev-parse HEAD) but returns a {repo, commit, revision, path, fetched_at}
    manifest — note `revision` and `path` (vs fetch_nfcore's `modules_path`)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    clone_dir = dest_dir / "pipelines" / name
    repo = f"https://github.com/nf-core/{name}.git"
    if not clone_dir.exists():
        runner(["git", "clone", "--depth", "1", "--branch", revision, repo,
                str(clone_dir)], check=True)
    result = runner(["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
                    capture_output=True, text=True, check=True)
    return {
        "repo": repo,
        "commit": result.stdout.strip(),
        "revision": revision,
        "path": str(clone_dir),
        "fetched_at": fetched_at,
    }
```

- [ ] **Step 4: Extend `write_manifest`**

In `write_manifest` ([fetch.py:186-243](../../../src/methods_graph/fetch.py#L186-L243)): add `nfcore_pipelines: dict[str, Any] | None = None,` to the keyword params, and add `"nfcore_pipelines": nfcore_pipelines,` to the `manifest["sources"]` dict. Update the docstring schema block to list the new key.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: PASS — both new tests pass; existing fetch tests unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/fetch.py tests/test_fetch.py
git commit -m "feat(fetch): fetch_nfcore_pipeline + write_manifest nfcore_pipelines key

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: End-to-end integration test

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

Add to `tests/test_integration.py` (drives the full `cmd_build` path, then queries Kùzu via `list(conn.execute(...))`):

```python
def test_build_connects_pipeline_to_shared_module_nodes(tmp_path):
    from methods_graph.cli import cmd_build
    from methods_graph.audit import audit_graph
    import kuzu
    from pathlib import Path

    fix = Path(__file__).parent / "fixtures"
    db = tmp_path / "m.kuzu"
    cmd_build(
        edam=None,
        nfcore_modules=fix / "nfcore_pipeline" / "mini" / "modules" / "nf-core",
        biocontainers=None,
        nfcore_pipelines=fix / "nfcore_pipeline",
        db_path=db, staging_dir=tmp_path / "s", ingested_at="2026-06-13",
    )
    conn = kuzu.Connection(kuzu.Database(str(db), read_only=True))

    # HAS_MODULE edges connect the Pipeline to module nodes that the MODULE
    # connector minted (shared-node join) — i.e. they are NOT dangling.
    n_has_mod = list(conn.execute(
        "MATCH (:Entity{kind:'Pipeline'})-[r:Rel{kind:'HAS_MODULE'}]->"
        "(:Entity{kind:'Module'}) RETURN count(r)"))[0][0]
    assert n_has_mod == 3

    # The inferred salmon→tximport ordering survived load.
    n_dse = list(conn.execute(
        "MATCH (:Entity{id:'mod:salmon_pe'})-[r:Rel{kind:'DOWNSTREAM_OF'}]->"
        "(:Entity{id:'mod:tximport_agg'}) RETURN count(r)"))[0][0]
    assert n_dse == 1

    assert audit_graph(conn).ok
```

- [ ] **Step 2: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_integration.py -v`
Expected: PASS — `n_has_mod == 3` proves the meta.yml-name join is correct (no dangling), the DOWNSTREAM_OF edge survived, and the audit is green.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pre-existing tests + the new ones PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test(integration): pipeline graph connects to shared module nodes + audits clean

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Done criteria

- `.venv/bin/pytest -q` green (existing + new).
- A build with `--nfcore-pipelines` produces `Pipeline` nodes, non-dangling `HAS_MODULE` edges (meta.yml-name join verified by `n_has_mod == 3`), attestation-tagged `DOWNSTREAM_OF` edges, and a clean `audit`.
- `salmon_quant`-style modules (pattern, no ontologies) now carry `INPUT`/`OUTPUT` edges.
- No DDL change; determinism preserved (injected `ingested_at`, sorted iteration).

## Deferred (out of scope — later phases / Sub-project B)

- Option-3 Nextflow channel parsing (real wiring; replaces Option-2 inference behind the same edge contract).
- Method-level `DOWNSTREAM_OF` (MVP is module-level).
- The planner (seed/expand), scoring beyond attestation, recall@k eval harness.
- Broadening the `pattern→EDAM` map and the pipeline corpus.
- Full `DOWNSTREAM_OF` I/O-overlap type-soundness audit (trivially true under Option-2 inference; meaningful only once Option-3 channel parsing can produce real mismatches).
