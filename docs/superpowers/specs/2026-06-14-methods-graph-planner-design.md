# Methods-Graph Planner — Design Spec (Sub-project B)

- **Date:** 2026-06-14
- **Status:** Draft (awaiting review)
- **Scope:** Sub-project B — the **planner** that consumes the attested master graph built by Sub-project A. MVP only: a minimal, advisory *expand* recommender. Quration/Canvas wiring and execution-grade plans are explicitly out of scope (see Non-Goals).

## Summary

Sub-project A fused nf-core pipelines into one connected master graph: `Module` nodes are DAG vertices, wired by `DOWNSTREAM_OF` edges that each carry an **attestation count** — how many real pipelines sequence step A→B. That count is a *measured* ranking signal, not a hand-tuned weight.

This sub-project adds the first consumer of that signal: a **method-layer planner**. Given the steps and/or data a user currently has on their canvas, it returns the **attestation-ranked next analysis steps**, each resolved to a concrete executor (the tool that runs the step), with its container and inherited statistical assumptions surfaced for free.

The deliverable is intentionally tiny: **one pure primitive** (`expand`), a thin causal-edge adapter (`seed_from_edge`), a CLI subcommand for inspection (`mg suggest`), and deterministic tests. It is **advisory only** — it suggests; it does not emit a runnable, type-sound DAG and does not drive any runner.

## Context: how this serves quration ("both, layered")

Quration presents a **Canvas** with two layers. The **causal layer** (biological entities + signed causal edges) is seeded and grounded by quration's own hypothesis engine (SIGNOR / optimusKG / LLM seeding) — **we do not build or touch it**. The **method/execution layer** is where each causal edge expands into the analysis sub-DAG that would test or compute it. This planner serves *that* layer, anchored to a causal edge:

> given a causal edge (source→target entities, signed relation) plus an available dataset, suggest the attestation-ranked execution steps that compute/test it.

The anchoring is a thin mapping (`seed_from_edge`): a causal edge + dataset format becomes a *frontier*, and the generic `expand` primitive does the rest. The planner never reasons about biology; it reasons about *which analysis step typically follows which*, learned from the pipeline corpus.

## Goals

1. Add a pure module `src/methods_graph/planner.py` exposing **`expand(conn, frontier_ids, *, limit=10, exclude=None) -> list[Suggestion]`** — the whole MVP.
2. Unify two candidate sources behind that one primitive: **continue** (step→step via `DOWNSTREAM_OF`, ranked by attestation) and **start** (data→step via `INPUT`→`WRAPS`, ranked by `HAS_MODULE` popularity).
3. Resolve each suggested `Module` to a concrete **executor** (`Method`) via `WRAPS`, enriched with container + inherited assumptions through the existing `method_neighborhood`.
4. Add a thin **`seed_from_edge(conn, edge, *, dataset_format=None) -> list[str]`** adapter mapping a quration causal edge + dataset to a frontier seed.
5. Add a `mg suggest` CLI subcommand for demo/inspection.
6. Keep everything **pure / deterministic / offline** (sorted output, no clock/random) — same contract as the connectors — with fixture-driven tests.
7. No DDL change, no change to existing ingestion, all existing tests still green.

## Non-Goals (this spec)

- **Quration provider/Canvas wiring.** No `MethodsGraphProvider.expand` seam, no Canvas payload schema. There is *no confirmed plan-ingestion contract on either side* (verified: quration's provider intake is the flat `get_methods()` list). Building a plan contract against an unconfirmed consumer is premature; this MVP ships the planner logic + CLI and defers the seam.
- **Runnable / execution-grade DAG.** Output is advisory. No type-soundness guarantee, no parameter inference, no resource configs. (Matches quration's current "advisory, never drives runner" posture.)
- **Multi-hop path synthesis.** `expand` returns **one hop** of ranked next steps. Iterating hops (and therefore topological sort / cycle-breaking on the bidirectional candidate graph) is the caller's / a later phase's job — see D4.
- **A runnable-ready `ExecutionPlan` schema.** The user chose the *minimal* option over the forward-compatible one. We emit `Suggestion`s, not a plan envelope.
- **Learned / GNN ranking.** Attestation count (and `HAS_MODULE` popularity for cold starts) is the only ranker. `confidence` (flat `0.5` today) is carried but **not** used as a discriminator.
- **Recall@k corpus evaluation.** A good validation idea, deferred; MVP correctness is proven by deterministic unit tests over a fixture graph.
- **SAME_AS alternative-tool selection.** When a module wraps multiple methods we list alternatives deterministically; we do not resolve cross-tool equivalents.

## Decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Both, layered.** Quration owns the causal layer; this planner serves the method/execution layer, anchored to a causal edge it receives. | The causal graph is the user's canvas; each edge expands into a method sub-DAG. We never rebuild quration's seeding/grounding. |
| D2 | **Advisory + minimal.** Emit ranked next-step `Suggestion`s + chosen executor. No runnable-ready schema, no execution-grade typing. | User explicitly chose the smallest scope. Advisory matches quration's current posture; Option-2 wiring is sufficient. YAGNI on the plan envelope. |
| D3 | **One frontier primitive.** `expand(frontier)` where `frontier` is "the nodes you currently have" — data-nodes (cold start) and/or step-nodes (continue). | One function places the first step and every next step. Leanest unification; no separate entry-point path. |
| D4 | **One hop, no topo-sort.** `expand` suggests the next step only; already-placed/excluded nodes are dropped. | One-hop-forward sidesteps the bidirectional-candidate-graph / cycle problem entirely. Keeps the MVP minimal and correct. |
| D5 | **Attestation is the ranker.** `attestations` for continue, `HAS_MODULE` popularity for start. Tie-break deterministic by id. | The corpus supplies the score (D3 of Sub-project A). `confidence` is flat 0.5 → carried, not ranked on. |
| D6 | **Schema-altitude payoff.** Suggested step = `Module` node; executor = `Method` via `WRAPS`. | The Module/Method split (recorded 2026-06-13) exists precisely so a step has one DAG identity and a separate concrete executor. |
| D7 | **Pure / deterministic / offline**, fixture-tested. | Same ethos as the connectors; reproducible suggestions, testable without network. |

## Verified substrate facts (the design rests on these)

Confirmed against `feat/methods-graph-mvp` source on 2026-06-14:

- `EdgeKind` includes `DOWNSTREAM_OF`, `WRAPS`, `HAS_MODULE`, `INPUT`, `OUTPUT`, `PERFORMS`, `USES_STATISTICAL_METHOD`, `REQUIRES_ASSUMPTION`, `PACKAGED_AS` ([types.py:32-55](../../../src/methods_graph/types.py#L32-L55)).
- `WRAPS` is emitted **Module → Method** (`mod:<name>` → `m:<tool>`) ([nfcore.py:396](../../../src/methods_graph/connectors/nfcore.py#L396)).
- **`INPUT`/`OUTPUT` edges attach to `Method` nodes, not `Module` nodes** ([nfcore.py:405-407](../../../src/methods_graph/connectors/nfcore.py#L405-L407)). *Module-level I/O exists only in-memory for DOWNSTREAM_OF inference and is never emitted as a queryable edge.* → **the cold-start lookup is data → Method (via `INPUT`) → Module (via `WRAPS`), a 2-hop traversal.**
- `DOWNSTREAM_OF` edges carry `{pipelines: list, attestations: int, derivation: str, confidence: float}` ([nfcore_pipeline.py:95-98](../../../src/methods_graph/connectors/nfcore_pipeline.py#L95-L98), merged in [pipeline_merge.py:35-49](../../../src/methods_graph/pipeline_merge.py#L35-L49)).
- `HAS_MODULE` is emitted **Pipeline → Module** ([nfcore_pipeline.py:78](../../../src/methods_graph/connectors/nfcore_pipeline.py#L78)) → counting `HAS_MODULE` into a Module = "how many pipelines include it".
- `method_neighborhood(conn, method_id) -> dict` ([extract/seed.py:86](../../../src/methods_graph/extract/seed.py#L86)) returns the typed 1-hop slice **including containers (via `PACKAGED_AS` → `Container.image_name`) and inherited assumptions** (Method→StatisticalMethod→Assumption, each with a `via` list) ([extract/seed.py:152-174](../../../src/methods_graph/extract/seed.py#L152-L174)). → executor enrichment is **one existing call**; no new traversal, **no `container` attribute** is needed on Method/Module (there isn't one).
- `seed(conn, seed_ids, *, k_hops=1) -> Subgraph` ([extract/seed.py:29](../../../src/methods_graph/extract/seed.py#L29)).
- Keyword resolver currently exists only as a **private method** `KuzuMethodsGraphProvider._method_ids_matching(keywords) -> list[str]` ([provider/quration_provider.py:219](../../../src/methods_graph/provider/quration_provider.py#L219)). → **small refactor: lift it to a pure free function in `extract/seed.py`**, reused by both the provider and `seed_from_edge` (no logic duplication).
- CLI uses argparse subparsers (`sub = parser.add_subparsers(dest="cmd", required=True)`; `elif args.cmd == "<name>":` dispatch); existing subcommands: `query, methods, build, audit, fetch, export-kgx` ([cli.py:591-730](../../../src/methods_graph/cli.py#L591-L730)).

## Architecture

### Where it sits

```
Sub-project A master graph (Kùzu)  ──►  planner.expand(conn, frontier)  ──►  [Suggestion, ...]
        (DOWNSTREAM_OF / WRAPS               │  (pure, read-only)
         HAS_MODULE / INPUT / ...)           ├── continue: Module ─DOWNSTREAM_OF─► Module   (rank: attestations)
                                             ├── start:    Format ◄─INPUT─ Method ◄─WRAPS─ Module (rank: HAS_MODULE count)
                                             └── enrich:   Module ─WRAPS─► Method ─► method_neighborhood
                                                            → chosen_executor + container? + assumptions

quration causal Edge + dataset ──► planner.seed_from_edge(...) ──► frontier_ids ──► expand(...)
mg suggest --db ... --have <id>... ──► expand(...) ──► printed table
```

### Repo additions

- **Create** `src/methods_graph/planner.py` — `expand`, `seed_from_edge`, the `Suggestion` dataclass (and small private query helpers). Pure; takes a live `kuzu.Connection`; returns plain dataclasses / JSON-serializable dicts.
- **Modify** `src/methods_graph/extract/seed.py` — lift keyword resolution into a pure free function (e.g. `method_ids_matching(conn, keywords) -> list[str]`); have the provider's private method delegate to it (behavior-preserving).
- **Modify** `src/methods_graph/cli.py` — add the `suggest` subparser + `cmd_suggest` dispatch.
- **Create** `tests/test_planner.py` — deterministic unit tests over a fixture graph (built via the existing loader, as other graph tests do).
- **Create** `tests/test_seed_from_edge.py` (or fold into `test_planner.py`) — adapter + lifted-helper tests.

## API

### `expand`

```python
def expand(
    conn: kuzu.Connection,
    frontier_ids: list[str],
    *,
    limit: int = 10,
    exclude: set[str] | None = None,
) -> list[Suggestion]:
    """Suggest the attestation-ranked next analysis steps from the current frontier.

    frontier_ids: the nodes the user "has" — Module step ids (e.g. 'mod:star_align')
        and/or EDAM Format/Data ids (e.g. 'fmt:format_1930'). Order-insensitive.
    Returns up to `limit` Suggestions, sorted by (rank_signal.count desc, module_id asc).
    Candidate modules already present in frontier_ids or `exclude` are dropped.
    Read-only; deterministic; no network.
    """
```

Candidate gathering:

- **continue** — for each frontier id that is a `Module`: `MATCH (a:Entity{kind:'Module'})-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b:Entity{kind:'Module'})` where `a.id ∈ frontier`. Candidate = `b`; signal = `attestations` (parsed from `r.properties`); evidence = `pipelines`.
- **start** — for each frontier id that is a `Format`/`Data`: `MATCH (mod:Entity{kind:'Module'})-[:Rel{kind:'WRAPS'}]->(m:Entity{kind:'Method'})-[:Rel{kind:'INPUT'}]->(f:Entity)` where `f.id ∈ frontier`. Candidate = `mod`; signal = `count{ (p:Pipeline)-[:HAS_MODULE]->(mod) }`; evidence = those pipeline names.
- A candidate reachable both ways keeps its **higher** signal; `rank_signal.kind` reflects which produced it (`"downstream"` wins ties over `"entry"` for label stability).
- Drop candidates in `frontier_ids ∪ exclude`. Sort, truncate to `limit`, then enrich each survivor.

Enrichment (per surviving Module candidate):

- `MATCH (mod)-[:Rel{kind:'WRAPS'}]->(m:Method)` → wrapped methods. `chosen_executor` = method with id min (deterministic; all wrapped methods of one module are equivalent executors of that step). Remaining → `alternatives`.
- Call `method_neighborhood(conn, chosen_executor.id)` once → fill `container` (if any `PACKAGED_AS`) and `assumptions` (inherited, with `via`).

### `Suggestion` (dataclass; `to_dict()` → JSON-serializable)

```python
@dataclass(frozen=True)
class Executor:
    method_id: str
    name: str
    container: str | None = None          # Container.image_name via PACKAGED_AS, else None

@dataclass(frozen=True)
class Suggestion:
    module_id: str
    module_name: str
    chosen_executor: Executor
    alternatives: list[Executor]          # other methods this module wraps (sorted by id)
    rank_signal: dict                     # {"kind": "downstream"|"entry", "count": int}
    evidence: list[str]                   # pipeline names attesting this step (sorted)
    assumptions: list[dict]               # [{"id","name","via":[...]}] from method_neighborhood; [] if none
    why: str                              # human string, e.g. "after star_align, 3 pipelines run samtools_sort next"
```

### `seed_from_edge`

```python
def seed_from_edge(
    conn: kuzu.Connection,
    edge: dict,                           # quration causal Edge: {source_label, target_label, relation, ...}
    *,
    dataset_format: str | None = None,    # an EDAM Format id the user has, e.g. 'fmt:format_1930'
) -> list[str]:
    """Map a causal edge + dataset to a frontier seed for expand().

    Resolves keywords from the edge's entity labels + relation via the lifted
    method_ids_matching(); appends dataset_format if given. Returns frontier ids.
    Deliberately thin — quration owns the causal layer.
    """
```

## Testing strategy

All tests build a **small fixture graph** with the existing loader (no network), then call the planner against a live connection. Cases:

1. **continue ranks by attestation** — frontier `{mod:A}`; B (attestations 3) ranks above C (attestations 1).
2. **start from data (2-hop)** — frontier `{fmt:X}`; modules whose wrapped method has `INPUT fmt:X` are returned, ranked by `HAS_MODULE` count. *Guards Correction 1: a Module with no `INPUT` edge of its own is still found via its Method.*
3. **executor resolution** — suggested module → `chosen_executor` is the min-id wrapped method; multi-wrap module lists `alternatives`.
4. **enrichment** — `container` populated when `PACKAGED_AS` exists, `None` when absent; `assumptions` populated (with `via`) for a method that inherits one, `[]` otherwise. *Guards Correction 2: no `container` attribute is assumed.*
5. **frontier/exclude dedup** — a candidate already in `frontier_ids` (or `exclude`) is never suggested.
6. **determinism** — identical inputs → identical ordered output (run twice, assert equal); ties broken by id.
7. **limit** — `limit=k` truncates after sorting.
8. **empty** — empty frontier, or frontier with no outgoing candidates → `[]` (no error).
9. **`seed_from_edge`** — a causal edge resolves to a non-empty frontier; `dataset_format` is appended; unknown labels → empty/seeded-only, no crash.
10. **lifted helper** — `method_ids_matching` returns the same results as the old private method (behavior-preserving refactor); provider delegates to it.
11. **CLI** — `mg suggest --db <fixture> --have <id>` prints the ranked suggestions; exits 0.

## Design notes / risks

- **Correction 1 (folded in):** module-level `INPUT`/`OUTPUT` edges do not exist; cold-start is data→Method→Module. Test 2 guards it.
- **Correction 2 (folded in):** no `container` attribute on Method/Module; containers come via `method_neighborhood`'s `PACKAGED_AS` lookup. Test 4 guards it.
- **Refactor risk:** lifting `_method_ids_matching` must be behavior-preserving — covered by Test 10; the provider keeps a thin delegating wrapper so its public behavior is unchanged.
- **Sparse cold-start signal:** `HAS_MODULE` popularity is a weaker signal than attestation and, on a single-pipeline graph, is near-uniform. Acceptable for MVP (advisory); noted so we don't over-trust entry-step ranks.
- **`confidence` is inert:** flat `0.5` today; carried in case Option-3 later differentiates it, but never ranked on. Stated so reviewers don't expect it to discriminate.
- **One-hop only:** multi-step plans require the caller to call `expand` repeatedly, feeding accepted steps back into the frontier. This is the intended advisory loop ("expand the DAG and curate") and keeps cycle-handling out of the MVP (D4).
- **No quration seam yet:** when a Canvas plan-ingestion contract is confirmed, a `MethodsGraphProvider.expand`/payload adapter is an additive follow-up — the pure `expand` already returns JSON-serializable suggestions.
