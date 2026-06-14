# nf-core Pipeline Graph — Design Spec (Sub-project A)

- **Date:** 2026-06-13
- **Status:** Draft (awaiting review)
- **Scope:** Sub-project A — the data layer. The planner that consumes this graph is **Sub-project B** and gets its own spec.

## Summary

Today methods-graph ingests nf-core **modules** (one tool at a time) plus EDAM, BioContainers, bio.tools, and STATO/OBI. It has no notion of a **pipeline** — the ordered DAG of modules that constitutes a real, standard analysis protocol. The `Pipeline` node kind and the `HAS_MODULE` / `DOWNSTREAM_OF` edge kinds are already declared in [`types.py`](../../../src/methods_graph/types.py) but have **no emitter**.

This sub-project builds that emitter. It **decomposes nf-core pipelines into their modules, joins each step to the `mod:`/`m:` nodes already in the graph, and overlays every pipeline's step-ordering onto those shared nodes** — fusing the pipelines into one connected master graph. Because modules are deduplicated, an ordering like `fastqc → trim_galore` attested by both nf-core/rnaseq and nf-core/sarek lands on the *same* edge, accumulating an attestation count. That connected, typed, attested graph is the foundation the planner (Sub-project B) will traverse.

The result delivers three things at once: **protocol templates** (filter edges by one pipeline), the **planner substrate** (the union of all wiring), and the **ranking signal** (attestation count — counted from the corpus, not hand-tuned).

## Goals

1. Add a `parse_pipeline` connector that turns one nf-core pipeline checkout into `Pipeline` + `HAS_MODULE` + `DOWNSTREAM_OF` records, joined to existing module/method nodes.
2. Enrich the **plumbing layer** — per-module typed `INPUT`/`OUTPUT` contracts from multiple sources (EDAM ontologies already parsed + meta.yml `input:`/`output:` `type`/`pattern`), so connection inference and validation work even where EDAM URIs are absent.
3. **Wiring (`DOWNSTREAM_OF`)** between steps, MVP-derived by plumbing inference within a pipeline's module set (Option 2), with the Nextflow channel-parse path (Option 3) as a documented upgrade behind the same edge contract.
4. **Attestation merge:** the same `(A, B)` ordering seen in N pipelines becomes one edge carrying `pipelines: [...]` and `attestations: N`.
5. Wire the connector into `fetch` (acquire pipeline checkouts), `build` (`--nfcore-pipelines`), and `audit` (new invariants), preserving the project's offline/deterministic/fixture-driven contract.
6. Stay backward compatible: no DDL migration, no change to existing module/EDAM/container ingestion, all existing tests still green.

## Non-Goals (this spec)

- **The planner itself** (seed / expand / scoring / executor selection) — that is Sub-project B.
- **Quration integration** — B's concern.
- **Full Nextflow DSL2 parsing** (Option 3) — designed-for but not implemented in the MVP; the MVP uses plumbing inference (Option 2).
- **A learned/GNN ranker** — attestation count is the MVP ranking signal; learn-to-rank is deferred to B/Phase 3.
- **Parameter inference** for steps (default params, resource configs).
- **Pipelines outside nf-core** (Snakemake, WDL, Galaxy) — future sources.

## Decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | The graph is built by **decomposing pipelines into shared modules + overlaying their connections**, not storing isolated per-pipeline DAGs. | Shared nodes connect the pipelines into one traversable master graph; this is the project's core thesis. |
| D2 | Three layers: **plumbing** (module I/O contracts), **membership** (`HAS_MODULE`), **wiring** (`DOWNSTREAM_OF`). | Plumbing = "what *can* connect"; wiring = "what experts *do* connect". They validate each other. |
| D3 | **Attestation count = the ranking signal.** Edge multiplicity across pipelines, not invented weights. | A scoring function must be measured, not asserted; the corpus supplies it directly. |
| D4 | Wiring MVP = **plumbing inference (Option 2)**; **Nextflow parse (Option 3)** is the precision upgrade behind the same `DOWNSTREAM_OF` contract. | Get the connected graph standing end-to-end without the risky DSL2 parser; swap the derivation later with no rework. |
| D5 | **No DDL change.** New `kind` values flow through the generic `Entity`/`Rel` tables; per-edge metadata lives in `properties` JSON. | The schema was built generic for exactly this. |
| D6 | Pipeline steps join to existing nodes via `mod:<meta.yml name>` / `m:<tool>`. **The join key is the module's meta.yml `name`, not its directory path** ([nfcore.py:182,188](../../../src/methods_graph/connectors/nfcore.py#L182-L188)). | nf-core pipelines vendor modules under `modules/nf-core/<tool>/<sub>/`, but ids line up *only* when meta.yml `name` == directory leaf — `parse_pipeline` must map each `modules.json` entry to its meta.yml `name`, and the audit must report dropped (dangling) `HAS_MODULE` edges. |

## Architecture

### Where it sits in the build pipeline

```
connectors (edam, nfcore module, biocontainers, …)
        │
        ├── NEW (greenfield): nfcore_pipeline.parse_pipeline(pipeline_dir)
        │        → Pipeline node + HAS_MODULE edges + per-pipeline DOWNSTREAM_OF edges
        │          (each tagged pipelines=[this], attestations=1)
        ▼
  cmd_build accumulates all nodes/edges
        ▼
  resolve(method_nodes, other_nodes, edges)     ← Pipeline nodes pass through as "other";
        │                                          remaps method ids THEN dedupes
        │                                          (from_id,to_id,kind)  [resolver.py:271-279]
        ├── NEW (greenfield): merge_downstream_of(resolved_edges)
        │        → attestation accumulation ONLY (union pipelines[], attestations=len,
        │          confidence=max). NOT dedup — resolve already deduped.
        ▼
  build_graph(...)  → Kùzu (dangling edges dropped & counted)
        ▼
  audit(...)        ← NEW invariants (type-sound wiring, HAS_MODULE endpoints, …)
```

### Repo additions

> **All symbols below are greenfield** — none of `parse_pipeline`, `merge_downstream_of`, `pipeline_merge.py`, `nfcore_pipeline.py`, `fetch_nfcore_pipeline`, or `--nfcore-pipelines` exist yet (verified by repo-wide grep).

```
src/methods_graph/connectors/nfcore_pipeline.py   # parse_pipeline
src/methods_graph/connectors/nfcore.py            # extend I/O extraction (plumbing fallback)
src/methods_graph/pipeline_merge.py               # merge_downstream_of (attestation accumulation)
src/methods_graph/cli.py                          # --nfcore-pipelines arg + discovery loop
src/methods_graph/fetch.py                         # fetch_nfcore_pipeline(s)
src/methods_graph/audit.py                         # pipeline invariants
tests/fixtures/nfcore_pipeline/<sample>/          # vendored mini-pipeline fixture(s)
tests/test_nfcore_pipeline.py
tests/test_pipeline_merge.py
```

## Graph schema (additions — no DDL change)

### Nodes

| kind | id scheme | name | properties |
|------|-----------|------|------------|
| `Pipeline` | `pipe:<name>` (e.g. `pipe:rnaseq`) | pipeline name | `{version, revision, url, n_modules}` |

Provenance: `source="nfcore_pipeline"`, `source_url=<repo URL>`, `ingested_at` (injected).

### Edges

| kind | from → to | properties | derivation |
|------|-----------|------------|------------|
| `HAS_MODULE` | `Pipeline` → `Module` (`mod:`) | `{}` | from `modules.json` (membership) |
| `DOWNSTREAM_OF` | `Method`/`Module` → `Method`/`Module` | `{pipelines: [..], attestations: N, derivation: "io_inferred"\|"channel_parsed", confidence: float}` | Option 2 / Option 3 |

> **Direction convention:** `DOWNSTREAM_OF` goes **producer → consumer** (data-flow direction): `salmon -DOWNSTREAM_OF-> tximport` means tximport runs after / downstream of salmon. *(Open question Q1 — confirm vs. the reverse reading of the verb.)*

`INPUT` / `OUTPUT` edges (plumbing) already exist (`Method → Data|Format`); this sub-project only **improves their coverage** (Goal 2), it does not add a new edge kind.

## The three layers

### 1. Plumbing — typed module I/O (improve coverage)

Today [`parse_module`](../../../src/methods_graph/connectors/nfcore.py)'s `_io_edam_ids` (≈237-250, via `_collect_ontology_edam_uris`) reads **only** the meta.yml `ontologies` key — it never inspects `type`/`pattern`, and **no `pattern→EDAM` map exists anywhere in `src/`**. Consequence today: the `salmon_quant` fixture (`type: file`, `pattern: "*.fastq.gz"`, no `ontologies`) produces **zero** `INPUT`/`OUTPUT` edges — a good motivating case to cite in tests. **Net-new work** (all greenfield): add a helper analogous to `_collect_ontology_edam_uris` that walks the `input:`/`output:` channel entries, extracts `pattern`, and applies a **3-tier lookup** — (1) EDAM ontology URI > (2) a new `pattern→EDAM-format` map constant (e.g. `*.bam` → the BAM `fmt:` id) > (3) a raw-pattern `Format` node keyed by the pattern. This makes the "can A feed B?" test answerable for far more module pairs.

### 2. Membership — `HAS_MODULE`

`modules.json` lists every nf-core module a pipeline vendors **by directory path** (`nf-core/<tool>/<sub>`). The catch ([nfcore.py:182,188](../../../src/methods_graph/connectors/nfcore.py#L182-L188)): module node ids are minted from the meta.yml **`name`** field (`mod:<name>`), **not** the directory path — they coincide only when `name` == directory leaf. So `parse_pipeline` **must resolve each `modules.json` path to its module's meta.yml `name`** (by reading the vendored module's `meta.yml`) before forming `mod:<name>` and emitting `Pipeline -HAS_MODULE-> Module`. **This is the riskiest join in the design:** if it keys on the path instead, every `HAS_MODULE` edge silently becomes **dangling** and is dropped by the loader. Mitigations: (a) read each vendored module's `meta.yml` `name` during parse; (b) the audit's `pipeline_has_modules` / membership-coverage check reports dropped edges so silent loss is caught; (c) validate `modules.json` keys against discovered module names at build time.

### 3. Wiring — `DOWNSTREAM_OF`

**Option 2 (MVP) — plumbing inference within the pipeline's module set.** For pipeline P with module set M(P): emit `A -DOWNSTREAM_OF-> B` (for A, B ∈ M(P), A ≠ B) when `OUTPUT(A) ∩ INPUT(B) ≠ ∅`. Tag `derivation="io_inferred"`. Known limitations, stated honestly:
- **Ambiguity:** if A and C both output BAM and B inputs BAM, both `A→B` and `C→B` are inferred; one may be spurious.
- **Cycles:** self-compatible types (BAM→sort→BAM) can create cycles; the connector forbids self-loops and the planner (B) carries the depth guard.
- These are *acceptable for a first connected graph* and are exactly what Option 3 fixes.

**Option 3 (upgrade) — Nextflow channel parse.** Parse `workflows/`, `subworkflows/`, `main.nf` channel wiring to emit the *actual* `A→B` edges (`derivation="channel_parsed"`). Same edge contract; the merge step and audit are unchanged. Deferred (DSL2 parsing is hard); the schema, merge, and consumers are designed so it drops in without rework.

### Attestation merge

`parse_pipeline` emits per-pipeline `DOWNSTREAM_OF` edges, each with `pipelines=[<this pipeline>]`, `attestations=1`. A new pure reducer `merge_downstream_of(edges)` runs in `cmd_build` **after `resolve`, on the resolved edge list** — *not* before. **Ordering matters:** `resolve` remaps method ids and *then* dedupes `(from_id, to_id, kind)` ([resolver.py:271-279](../../../src/methods_graph/resolve/resolver.py#L271-L279)), so edges that become identical only *after* a method-id merge (e.g. `(m:foo_v1, bar)` and `(m:foo_v2, bar)` → `(m:foo, bar)`) are collapsed only post-resolve. The reducer's job is therefore **attestation accumulation only** — union `pipelines` (sorted/deduped), set `attestations=len(pipelines)`, `confidence=max` — **not** deduplication, which `resolve` already guarantees and the loader does not do ([loader.py:54-62](../../../src/methods_graph/graph/loader.py#L54-L62) only drops dangling edges). Deterministic; no clock/randomness.

## Acquisition & fixtures

- **`fetch`:** add `fetch_nfcore_pipeline(name, dest, *, revision, fetched_at, runner=subprocess.run)` — shallow-clone `https://github.com/nf-core/<name>` at a pinned `revision` into `<dest>/pipelines/<name>`; return `{repo, commit, revision, path, fetched_at}`. It **reuses `fetch_nfcore`'s *pattern*** (injectable runner, re-use-existing-clone, `rev-parse HEAD`) but **does not mirror its return shape**: `fetch_nfcore` returns `{repo, commit, modules_path, fetched_at}` ([fetch.py:329-379](../../../src/methods_graph/fetch.py#L329-L379)) — no `revision`, and a `modules_path` key; the pipeline version *adds* `revision` and uses `path`.
- **`write_manifest` must be extended:** it currently hardcodes exactly six source keys (`edam, nfcore_modules, biocontainers, biotools, stato, obi`) with no parameter for pipelines ([fetch.py:186-243](../../../src/methods_graph/fetch.py#L186-L243)). Add a `nfcore_pipelines` parameter + a `nfcore_pipelines` entry in `manifest['sources']` (and update the docstring schema/Args), then thread it through `cmd_fetch`.
- **Offline tests:** a vendored **mini-pipeline fixture** under `tests/fixtures/nfcore_pipeline/<sample>/` containing a `modules.json` and a handful of module dirs (reuse existing module fixtures), shaped so the inferred wiring is a known small DAG (e.g. `fastqc → salmon → tximport`). No network in any test.

## Entity resolution / the join

`Pipeline` nodes have unique strong ids (`pipe:<name>`) and pass through `resolve` as non-method "other" nodes ([cli.py:152-153](../../../src/methods_graph/cli.py#L152-L153); no merging needed). `HAS_MODULE`/`DOWNSTREAM_OF` edges reference `mod:`/`m:` ids — but see **§Membership**: `mod:` ids derive from the meta.yml `name`, so `parse_pipeline` must resolve to that name, not the path, or edges go dangling. Because `resolve` remaps method ids and dedupes edges, the attestation merge runs **after** resolve (see **§Attestation merge**). Edges to ids absent after resolution are dropped as dangling by the loader (existing behavior, counted) and surfaced by the audit's coverage check.

## Audit invariants (additions to `audit.py`)

1. **`pipeline_has_modules`** — every `Pipeline` has ≥1 `HAS_MODULE` edge (else the checkout/parse failed).
2. **`has_module_endpoints`** — every `HAS_MODULE` points `Pipeline → Module`.
3. **`downstream_type_sound`** — for every `DOWNSTREAM_OF` `A→B`, `OUTPUT(A) ∩ INPUT(B) ≠ ∅` *when both contracts are non-empty*. (Trivially true for `io_inferred`; the real value is catching `channel_parsed` mismatches — a wiring whose types don't line up means the parse is wrong.)
4. **`downstream_attestation_consistent`** — `attestations == len(pipelines)` and `pipelines` is non-empty/sorted/deduped.
5. **`no_downstream_self_loops`** — no `A -DOWNSTREAM_OF-> A`.

**Registration mechanics:** [`audit.py`](../../../src/methods_graph/audit.py) registers invariants as `(name, cypher)` tuples in `_invariant_specs` (looped ≈333-335), with a parallel Python-computed path (≈337-368) for checks that introspect the JSON `properties` column. Mapping: `pipeline_has_modules`, `has_module_endpoints`, the endpoint-kind portion of `downstream_type_sound`, and `no_downstream_self_loops` fit the **Cypher-tuple** pattern; **`downstream_attestation_consistent` needs the Python pattern** because `attestations`/`pipelines` live inside the `properties` JSON blob, which Cypher cannot introspect.

Consistent with the existing audit's "absence of a contract is not a violation" philosophy (opt-in checks).

## Testing strategy (TDD)

Pure-function-first, offline, deterministic — mirroring the existing connector tests.

- `test_nfcore_pipeline.py`:
  - `parse_pipeline` emits one `Pipeline` node with the right id/props.
  - `HAS_MODULE` edges match `modules.json` membership; ids are `mod:<name>`.
  - Option-2 wiring on the fixture yields the expected `fastqc→salmon→tximport` edges and **no** spurious/self edges.
  - I/O plumbing fallback: a module with `pattern: "*.bam"` but no EDAM URI still gets an `OUTPUT`/`INPUT` edge.
  - Determinism: two runs produce identical sorted records.
- `test_pipeline_merge.py`:
  - same `(A,B)` from two pipelines → one edge, `attestations==2`, `pipelines` sorted+deduped.
  - distinct edges untouched; properties merged not overwritten.
- Integration (`test_integration.py` extension): build a graph from module fixtures **+** a pipeline fixture; assert `Pipeline` node present, `DOWNSTREAM_OF` edges loaded, audit passes.
- All existing tests remain green (no regressions to module/EDAM/container paths).

## Phasing

- **Phase A1 (this MVP):** schema-value usage (no DDL), `parse_pipeline`, plumbing-coverage improvement, Option-2 wiring, `merge_downstream_of`, CLI `--nfcore-pipelines`, `fetch_nfcore_pipeline`, audit invariants, fixtures + tests.
- **Phase A2:** Option-3 Nextflow channel parsing behind the same `DOWNSTREAM_OF` contract.
- **Phase A3:** expand the pipeline corpus (more nf-core pipelines) and broaden the pattern→EDAM map.
- **Then Sub-project B:** the planner (seed/expand) over this graph.

## Open questions / risks

**Resolved for the MVP (recommended defaults, accepted 2026-06-13 — override any before implementation):** Q1 → **producer→consumer**; Q2 → start with **`rnaseq` + `sarek` + `scrnaseq`**; Q3 → **ship plain Option 2** (let Option 3 supersede); Q4 → **seed ~15 common genomics formats**, raw-pattern fallback otherwise. Rationale below.

- **Q1 — `DOWNSTREAM_OF` direction:** confirm producer→consumer (this spec's convention) vs. the literal "B is downstream_of A ⇒ B→A" reading. The edge has **no emitter yet** ([types.py:35](../../../src/methods_graph/types.py#L35)), so direction is genuinely unconstrained by any existing data or check — free to choose, but pick one, encode it once, and assert it in the audit.
- **Q2 — Pipeline corpus for the MVP:** start with how many / which? Recommendation: 2–3 well-known pipelines (`rnaseq`, `sarek`, maybe `scrnaseq`) to exercise shared-node overlap, plus the synthetic fixture for tests.
- **Q3 — Option 2 spurious edges:** acceptable for the MVP given attestation + audit type-soundness, or gate Option-2 edges by additional heuristics (e.g. only adjacent-in-`modules.json`)? Recommendation: ship plain Option 2, let Option 3 supersede.
- **Q4 — pattern→EDAM-format map:** how much to seed initially (BAM/SAM/CRAM/VCF/FASTQ/BED/GTF…) vs. fall back to raw-pattern `Format` nodes. Recommendation: seed the ~15 common genomics formats; raw-pattern fallback for the rest.
- **Risk — meta.yml `input:`/`output:` irregularity:** the shape is famously inconsistent (already noted in `nfcore.py`). The plumbing fallback must be structural/tolerant like `_collect_ontology_edam_uris`.
```
