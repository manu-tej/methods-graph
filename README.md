# methods-graph

A local knowledge graph over bioinformatics **methods**, pipeline modules, containers,
ontology terms, statistical assumptions, diagnostics, and executable workflow context —
built on [Kùzu](https://kuzudb.com/).

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

## Contribution model

The graph design direction, curation choices, and public interpretation are mine. Coding
agents helped implement connectors, tests, and review-driven fixes — implementation
acceleration, not ownership of the curation or scientific framing.

## Limitations

This is research / tooling code, not a clinical or production recommendation system. Graph
coverage depends on the public sources and curated crosslinks included here; broad coverage
claims should wait until source coverage and attribution are fully reviewed.

## Setup notes

The `quration` provider emits plain dictionaries without a `quration` install. Install
`quration` in the same environment only when validating those dictionaries against
`quration`'s `AnalysisMethod` model.

## License

MIT. See [`LICENSE`](LICENSE).
