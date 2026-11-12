# methods-graph

`methods-graph` is the separately versioned method-validity and guardrail substrate for
[Dogma](https://github.com/manu-tej/dogma), an AI scientist platform that is currently paused. It is a local
knowledge graph over bioinformatics **methods**, pipeline modules, containers, ontology
terms, statistical assumptions, diagnostics, and executable workflow context — built on
[Kùzu](https://kuzudb.com/).

> **Status: paused since October 2026.** This repo holds three sub-projects. The methods
> graph and guardrail are frozen. The method-sequencing benchmark is blocked. Biolean was
> the active one when work stopped. Details are in [`docs/STATUS.md`](docs/STATUS.md), which
> is a snapshot dated 2026-09-22 with a short note on what has changed since. The other docs
> carry the same date and have not been updated.

> **About this repository.** This is a single-commit snapshot, taken on 2026-11-11, of a
> private development repository. Commit hashes cited in the docs refer to that history and
> do not resolve here. On that date a fresh install (`uv sync --extra dev`) ran the suite
> without the local database or GO snapshots: 1218 passed, 33 skipped.

Within Dogma, it acts as a **methodological leash**: not a substitute for scientific
judgment, but a guardrail that asks an agent's proposed analysis to resolve to documented
methods, expose its prerequisites and diagnostics, and retain provenance so gaps remain
visible before execution or interpretation. As of 2026-09-22 the leash is narrow: only one
method (`m:deseq2`) can be blocked, and 806 of 905 methods are `NOT_EVALUABLE` (see
[What you can run against it](#what-you-can-run-against-it)).

It answers a practical question: given a biological analysis goal, *what methods are
available, what do they depend on, and what assumptions or diagnostics make their use
trustworthy?* Every method is linked to the operations it performs, the statistical
methods and assumptions it relies on, and the evidence (citations / ontology terms) that
grounds those links — so a workflow can be checked for evaluability rather than taken on
faith.

## Documentation

- [`docs/README.md`](docs/README.md) — the docs index: reading order, one line per doc.
- [`docs/STATUS.md`](docs/STATUS.md) — what was built, measured and broken as of 2026-09-22, with a 2026-11-09 note on what has changed since.
- [`docs/decisions/2026-09-22-biolean-transitive-edges.md`](docs/decisions/2026-09-22-biolean-transitive-edges.md)
  — the open Biolean decision: keep direct-edge steps strict, or admit a transitive step.

Commands here are written `mg ...`, but no `mg` is installed: the console script is
`methods-graph` (`.venv/bin/methods-graph`), and on macOS a bare `mg` runs `/usr/bin/mg`, an
unrelated text editor. From the repo root, define it once:
`alias mg='.venv/bin/python -m methods_graph.cli'`.

## What it does

- **Graph model.** A Kùzu-backed schema for methods and related entities (operations,
  data types/formats, statistical methods, assumptions, diagnostics, assays, containers).
- **Connectors** for public sources: EDAM, nf-core modules, BioContainers, bio.tools, and
  ontology terms (STATO statistical methods; OBI assays, protocols, study designs,
  instruments, materials). Assumptions and diagnostics are not ontology-derived: they come
  from the curated crosslink YAML below.
- **Curated crosslinks** tying methods to their statistical methods, assumptions,
  diagnostics, and pipeline context, each carrying provenance.
- **Explain / audit utilities** that surface *why* a method has a given evaluability chain,
  and a workflow validator that rejects hallucinated methods and forged evidence.

See [`examples/causal_evaluability_demo.py`](examples/causal_evaluability_demo.py) for a
self-contained walkthrough that turns a biological hypothesis into an *evaluable* causal
DAG (identify → estimate → refute), grounding each estimator against the graph and
flagging coverage gaps instead of inventing tools.

## Role in Dogma

Dogma is the product; `methods-graph` is a focused component kept in its own repository so
its sources, curation, tests, and rebuild process can be inspected independently of the
application. The boundary is deliberate: the graph can surface method candidates,
assumptions, diagnostics, provenance, and honest coverage gaps. It does not decide whether
a biological claim is true or replace expert review.

The original Dogma implementation used `quration` as its package and API namespace. That
name survives only at the compatibility boundary; it does not refer to a second product.

## Data sources

The graph is assembled from public bioinformatics metadata. Upstream licenses and
attribution requirements are tracked in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md):

| Source | Use | License |
|---|---|---|
| EDAM Ontology | operations, data types, formats (the Topic layer is not ingested) | CC BY-SA 4.0 |
| nf-core | pipeline/module metadata, workflow context | MIT |
| BioContainers | container / tool metadata | Apache-2.0 |
| bio.tools | tool registry metadata | CC BY 4.0 |
| STATO | statistical-method ontology terms | CC BY 3.0 |
| OBI | assay / protocol ontology terms | CC BY 3.0 |
| BioClaw skill library | `Skill` nodes (28 parsed of 39 `SKILL.md`) | not recorded; verify |
| Gene Ontology (`go-basic.obo`) | Biolean only, not the graph | CC BY 4.0 |
| GOA human GAF | Biolean only, not the graph | CC BY 4.0 (verify) |
| ECO `gaf-eco-mapping.txt` | Biolean only, not the graph | verify |

Full source ontologies and build artifacts are fetched or regenerated, not vendored: the
repo commits provenance metadata (`data/methods.lock.json`) and small reduced fixtures
rather than upstream dumps.

## Quickstart

```bash
uv sync --extra dev
uv run pytest -q                                  # 1,014 tests; see below for the expected split
uv run python examples/causal_evaluability_demo.py
```

The demo is self-contained: it builds a compact, faithfully-grounded graph from the
shipped curated maps, so no external fetch or database is required.

The suite collects 1,014 tests in 71 files. With `data/methods.kuzu` and `snapshots/go/`
present: 1013 passed, 1 skipped (the optional `quration` package). Without them, as in CI:
981 passed, 33 skipped (30 need the DB, 2 need `snapshots/go/`, 1 needs `quration`).
Measured 2026-09-22 with `env -u OPENAI_API_KEY .venv/bin/python -m pytest -q`, the second
split in a `git archive HEAD` checkout that has neither.

Contributing? [`CLAUDE.md`](CLAUDE.md) documents the conventions, identifier schemes, and
the traps that have actually cost time here.

## The graph at a glance

Built artifact (`data/methods.kuzu`, regenerated — not committed): **905 methods**, 19,425
nodes, 32,757 edges. Curation depth is uneven by design, and every query surface reports
its own denominator rather than implying uniform coverage:

| Attribute | Methods carrying it |
|---|---|
| EDAM operation (`PERFORMS`) | 415 / 905 (46%) |
| bioconda package | 745 (82%) |
| container | 646 (71%) |
| bio.tools id | 450 (50%) |
| typed input `Data` node | 49 (5.4%) |
| typed output `Data` node | 39 (4.3%) |

Semantic `Data` typing is the thin layer, and deliberately so — it is hand-curated where
a handoff needs to be checkable, not inferred. Treat any I/O-derived result as scoped to
those 49/39, which is why the tooling prints coverage next to every number.

## What you can run against it

All of these need the built `data/methods.kuzu` (gitignored; `make rebuild` makes it from
`snapshots/`).

```bash
mg guardrail --method m:deseq2 --fact replicates_per_group=2   # one step's preconditions
mg explain --method m:deseq2                                   # why it has that verdict
mg audit --db data/methods.kuzu                                # graph invariant checks

# a proposed pipeline: per-step verdicts plus the data handoffs between consecutive steps
mg guardrail-chain --step m:salmon --step m:tximeta --step m:deseq2 --fact replicates_per_group=3
```

`guardrail` returns `EVALUABLE` / `BLOCKED` / `NOT_EVALUABLE` / `FACTS_REQUIRED` (exit 0 / 3 /
4 / 5), e.g. (excerpt):

```text
BLOCKED  (m:deseq2)
  [FAIL] asymptotic (large-sample) normality — replicates_per_group supplied=2 >= 3?
  [REQUIRES_REVIEW] independence of observations — manual check
  [POST-RUN] normality — run: diag:qq_plot, diag:shapiro_wilk
```

The chain above returns `CHAIN: EVALUABLE` with both handoffs `VALID via data:data_3917`.
Most chains do not: `m:fastqc → m:star → m:subread → m:deseq2` (featureCounts ships in
subread; `m:featurecounts` is not a method id) is `NOT_EVALUABLE` (exit 4), because the
first three steps have no evaluability coverage. Write chain steps as `m:` ids; a bare
keyword resolves by fuzzy search and can pick the wrong tool (`salmon` → `m:biohansel`).

`NOT_EVALUABLE` is a first-class answer: an uncovered method is reported as a coverage
gap, never silently approved. Coverage is narrow. Over all 905 methods with no facts
supplied, 806 are `NOT_EVALUABLE`, 98 `EVALUABLE` and 1 `FACTS_REQUIRED`. Only `m:deseq2`
can ever return `BLOCKED` or `FACTS_REQUIRED`, and `replicates_per_group >= 3` is the only
numeric gate. This was re-measured on 2026-09-22 by calling `guardrail.evaluate` on every
`Method` node. The guardrail code has not changed since 2026-07-31 (`430300a`).

## Reproducibility

`data/methods.lock.json` records graph counts, the content hash of a graph rebuilt from
local snapshots, and partial source pins. Only EDAM, STATO and OBI carry a sha256 and
nf-core/modules a commit. The `biocontainers` and `biotools` entries are empty (`{}`), and
the skill library is not recorded at all. CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

- **Every push to `main` / every PR** — `pytest -q` on Python 3.12, nothing else. Tests
  needing the built database or `snapshots/go/` skip automatically (both are gitignored),
  so anything gated that way is enforced locally, not in CI. The Biolean commits were pushed
  on 2026-09-23 and 2026-09-26, and CI has run on them since.
- **Weekly / on demand** — two separate questions:
  - *Is the build deterministic given identical snapshots?* **Hard gate.** Two rebuilds
    must produce the same graph hash. The latest scheduled result was not re-checked on
    2026-09-22. The hash function itself trusts Kùzu's `ORDER BY`, which occasionally
    returns edges out of order, so one red run can be a false alarm; rerun before
    treating it as non-determinism ([`docs/BACKLOG.md`](docs/BACKLOG.md) M21).
  - *Has upstream drifted from the lock?* **Informational.** `fetch` does not replay the
    lock. It shallow-clones nf-core/modules at the default branch, and reuses an existing
    clone without updating it. It queries the BioContainers and bio.tools APIs live. EDAM,
    STATO and OBI come from unversioned "latest" URLs. It never fetches
    `snapshots/skills/bioclaw`, which `rebuild` reads without an existence check: a
    missing skills directory builds 0 `Skill` nodes and fails `--check` on the hash even
    with no upstream drift. Closing the gap means threading the pins into `fetch` and
    pinning a skills source. Until then drift is reported, not treated as a regression.

## Biolean

A proof assistant for biological claims. An agent emits a derivation of a GO claim (axiom,
`is_a`, `part_of`, `sorry`); `mg biolean check` accepts or rejects it against GO and human GOA
with typed errors and suggestions. `mg biolean prove` is the mechanical prover, `mg biolean
goals` lists what is derivable for a gene product. Guide: [`docs/biolean/README.md`](docs/biolean/README.md);
benchmark: [`docs/biolean/benchmark.md`](docs/biolean/benchmark.md). Design: `docs/superpowers/specs/2026-09-21-biolean-design.md`.

Its benchmark has two tracks. **prove** hides every row of one annotation and asks for a
closed-book re-derivation from a more specific term; a hit is an ACCEPTED derivation of the
item's claim with no `sorry`. **hypothesize** hides the whole subtree so nothing can be
derived, and measures format compliance only (a `sorry` root with provenance) until Phase B
can discharge the computation. Every rate ships with its denominator; the `modal:` baseline
(most common descendant for the goal term, gene-blind) is the number to beat, `gold:` must
score 1.0, and `template:` saturates the hypothesize track by construction.

```bash
mg biolean fetch --out snapshots/go                                  # NETWORK, ~47 MB: GAF, the GO release it names, ECO
mg biolean bench build --out biolean-bench [--since 2026-01-01]       # frozen items, manifest, modal prior
mg biolean bench coverage --items biolean-bench                       # denominators; read before any score
mg biolean bench run --model gold: --track prove --out gold.jsonl     # then modal:, random:<seed>, claude:...
mg biolean bench run --model template: --track hypothesize --out t.jsonl
mg biolean bench run --model claude:claude-opus-5 --track prove --workers 8 --resume --out claude-run.jsonl   # PAID; a NEW file; --resume keeps finished rows on restart
mg biolean bench score --results gold.jsonl                           # re-derive from retained raw output
```

`check`, `prove`, `goals` and `bench build|run|score` need `snapshots/go/`, and every call
re-parses it (about 13 s); `bench coverage` reads only the item directory.
`claude:` and `openai:` contestants cost money. `bench run` without `--resume` truncates an
existing `--out` file (`cli.py:1416`), so a mistyped restart discards a paid run.

`run` and `score` refuse a store whose GO/GOA release differs from the one the items were
built from. No items ship in the repo; `snapshots/go/` is gitignored. The local
`snapshots/go/` was not made by `mg biolean fetch`. It has no `snapshot.json`, and its OBO
(`releases/2026-07-26`) is a later release than the GAF names (`2026-04-27`). The frozen
items in `biolean-bench/` and both result files depend on that exact pair. A re-fetch would
make `run`/`score` refuse them, so whether to re-fetch is an open decision, not a routine
step. `claude:` runs the CLI with built-in tools removed (`--tools ""`), every customization and MCP
server disabled (`--safe-mode --strict-mcp-config`), in an empty temporary directory, so the
contestant cannot read the item files, query the store, or receive your CLAUDE.md or hooks.
It still runs under Claude Code's default system prompt with no temperature control, while
`openai:` is a raw chat completion at temperature 0. Cross-provider numbers are not
like for like.

**Result, 2026-09-22 (prove track, 500 items, strict kernel):** gold 500 (1.000), modal 264
(0.528), `claude:claude-opus-5` 205 (0.410), `random:0` 26 (0.052). Opus is below the
gene-blind modal prior (exact McNemar p = 1.7e-5). Many of its rejections are exact-edge
errors: the kernel accepts only a direct, asserted `is_a`/`part_of` edge, the prompt never
says so, and 106 of Opus's cited edges point to a true ancestor rather than a direct
parent. If a relation-aware transitive step were admitted, Opus would score 269 (0.538,
p = 0.76 vs modal); gold, modal and random would not change. Whether to admit it is an **open decision**:
[`docs/decisions/2026-09-22-biolean-transitive-edges.md`](docs/decisions/2026-09-22-biolean-transitive-edges.md).
Full numbers: [`docs/biolean/results-2026-09-22-opus-5.md`](docs/biolean/results-2026-09-22-opus-5.md).
The result files (`opus.jsonl`, `modal.jsonl`) are untracked in the repo root.

## Method-sequencing benchmark (`bench`)

A LiveBench-style benchmark asking whether a model knows which methods a bioinformatics
goal needs and in what order. Gold answers are derived from real nf-core pipeline DAGs
(`nextflow -preview`); the graph is the scoring oracle, supplying method equivalence,
data-type I/O and the module→method projection.

```bash
mg bench build --pipelines snapshots/pipelines --goals goals.json  # clones -> frozen items
mg bench coverage --items bench/items                              # how much oracle backs them
mg bench run --items bench/items --model claude:claude-opus-5 --out results.jsonl   # PAID
mg bench score --results results.jsonl --out rescored.jsonl        # re-derive from retained raw
```

`coverage`, `run` and `score` need an oracle: `data/methods.kuzu` (the default `--db`) or an
`--oracle-json` file. `claude:` and `openai:` contestants cost money.

**No items ship in the repo.** `snapshots/pipelines/` does not exist and must be populated
first. That needs Nextflow, Java and network access, via `mg ingest` or
`fetch_nfcore_pipeline`; `bench build` accepts any directory of clones with a `dag.mmd`
each. The `NXF_VER` pinning policy is an **open question**. The one pilot ran unpinned on
Nextflow 26.04.3, and an old pin (23.10.0) is reported to break that launcher and silently
degrade the DAG to `io_inferred`. `bench build` on a missing directory and `bench run` on
missing items both fail (today with a Python traceback, exit 1) rather than report a null
result as success.

**Pilot, 2026-08-08 (untracked, `bench-runs/2026-08-08-pilot/`):** 156 items (10
whole_pipeline, 146 next_step) from 10 of 12 pipelines. Its Sonnet contestant was **not**
closed-book: it ran before the adapter fix, with default tools, CLAUDE.md and MCP. Its
scores are not a model measurement. The pilot also showed that `gold:` scores 1.0 on
selection, sequencing and next-step but only 0.505 on validity (coverage 0.128), so the
validity axis is not ceiling-clean on real items. See
[`docs/method-sequencing-benchmark.md`](docs/method-sequencing-benchmark.md).

- `--model` accepts `claude:<model>`, `openai:<model>`, `static:<path>`, and the three
  baselines `gold:` (ceiling: 1.0 on the one fixture item CI checks, but not on validity
  over real items), `modal:` (answer the most common gold pipeline regardless of the question; when
  every gold sequence is unique it degenerates to the lexicographically smallest) and
  `random:<seed>[:<k>]` (floor).
- `--goals` maps pipeline name → the goal text that becomes the prompt. Without it a
  pipeline is asked only by its bare name. No goals file exists in the repo yet.
- Four axes are reported separately, never pooled: selection (F1 over the method set),
  sequencing (fraction of required DAG precedences respected), validity (does each
  step's input reach it from something earlier), and next-step accuracy by prefix
  length. Undefined is `null`, never `0.0`, and every axis prints its denominator.

Note: `mg bench --pipelines X` is now `mg bench build --pipelines X`.

## Contribution model

The graph design direction, curation choices, and public interpretation are mine. Claude
Code and Codex helped implement connectors, tests, and review-driven fixes — implementation
acceleration, not ownership of the curation or scientific framing.

## Limitations

This is research / tooling code, not a clinical or production recommendation system. Graph
coverage depends on the public sources and curated crosslinks included here; broad coverage
claims should wait until source coverage and attribution are fully reviewed.

## Setup notes

The compatibility adapter remains at
[`src/methods_graph/provider/quration_provider.py`](src/methods_graph/provider/quration_provider.py)
because the original Dogma package/API namespace was `quration`. The provider emits plain
dictionaries without that legacy package installed. Install `quration` in the same
environment only when validating those dictionaries against the legacy `AnalysisMethod`
model.

## License

MIT. See [`LICENSE`](LICENSE).
