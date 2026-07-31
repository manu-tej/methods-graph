# methods-graph

`methods-graph` is the separately versioned method-validity and guardrail substrate for
[Dogma](https://github.com/manu-tej/dogma), the in-progress AI scientist platform. It is a local
knowledge graph over bioinformatics **methods**, pipeline modules, containers, ontology
terms, statistical assumptions, diagnostics, and executable workflow context — built on
[Kùzu](https://kuzudb.com/).

Within Dogma, it acts as a **methodological leash**: not a substitute for scientific
judgment, but a guardrail that asks an agent's proposed analysis to resolve to documented
methods, expose its prerequisites and diagnostics, and retain provenance so gaps remain
visible before execution or interpretation.

It answers a practical question: given a biological analysis goal, *what methods are
available, what do they depend on, and what assumptions or diagnostics make their use
trustworthy?* Every method is linked to the operations it performs, the statistical
methods and assumptions it relies on, and the evidence (citations / ontology terms) that
grounds those links — so a workflow can be checked for evaluability rather than taken on
faith.

## What it does

- **Graph model.** A Kùzu-backed schema for methods and related entities (operations,
  data types/formats, statistical methods, assumptions, diagnostics, assays, containers).
- **Connectors** for public sources: EDAM, nf-core modules, BioContainers, bio.tools, and
  ontology-derived method/assumption records (STATO, OBI).
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
| EDAM Ontology | operations, data types, formats, topics | CC BY-SA 4.0 |
| nf-core | pipeline/module metadata, workflow context | MIT |
| BioContainers | container / tool metadata | Apache-2.0 |
| bio.tools | tool registry metadata | CC BY 4.0 |
| STATO | statistical-method ontology terms | CC BY 3.0 |
| OBI | assay / protocol ontology terms | CC BY 3.0 |

Full source ontologies and build artifacts are fetched or regenerated, not vendored: the
repo commits provenance metadata (`data/methods.lock.json`) and small reduced fixtures
rather than upstream dumps.

## Quickstart

```bash
uv sync --extra dev
uv run pytest -q                                  # 552 passed, 1 skipped
uv run python examples/causal_evaluability_demo.py
```

The demo is self-contained: it builds a compact, faithfully-grounded graph from the
shipped curated maps, so no external fetch or database is required.

## Reproducibility

`data/methods.lock.json` pins source snapshots and records the hash of a graph rebuilt
from them. CI runs two gates ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

- **On every push / PR** — the full test suite plus lock-schema validity.
- **Weekly / on demand** — a reproducibility gate that fetches the pinned sources,
  rebuilds the graph, and asserts the rebuild reproduces the committed lock's graph hash
  (`python -m methods_graph.cli rebuild --check`).

## Method-sequencing benchmark (`bench`)

A LiveBench-style benchmark asking whether a model knows which methods a bioinformatics
goal needs and in what order. Gold answers are derived from real nf-core pipeline DAGs
(`nextflow -preview`); the graph is the scoring oracle, supplying method equivalence,
data-type I/O and the module→method projection.

```bash
mg bench build --pipelines snapshots/pipelines --goals goals.json  # clones -> frozen items
mg bench coverage --items bench/items                              # how much oracle backs them
mg bench run --items bench/items --model claude:claude-opus-5 --out results.jsonl
mg bench score --results results.jsonl --out rescored.jsonl        # re-derive from retained raw
```

**No items ship in the repo.** `snapshots/pipelines/` must be populated first — that
needs Nextflow, Java, network access and a per-release `NXF_VER` pin, via
`mg ingest` or `fetch_nfcore_pipeline`. `bench build` refuses a missing directory and
`bench run` refuses an empty item set rather than reporting a null result as success.

- `--model` accepts `claude:<model>`, `openai:<model>`, `static:<path>`, and the three
  baselines `gold:` (ceiling, must score 1.0), `modal:` (answer the most common gold
  pipeline regardless of the question) and `random:<seed>[:<k>]` (floor).
- `--goals` maps pipeline name → the goal text that becomes the prompt. Without it a
  pipeline is asked only by its bare name.
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
