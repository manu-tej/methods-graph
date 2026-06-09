# Methods Master Graph — Design Spec

**Date:** 2026-06-08
**Status:** Approved (design phase)
**Owner:** manuarrojwala

## Summary

A standalone Python package, `methods_graph`, that builds a heterogeneous knowledge
graph of bioinformatics **methods/tools** from three structured sources — the EDAM
ontology, nf-core pipelines, and BioContainers — and stores it in an embedded Kùzu
graph database. It exposes a seed-subgraph extraction API (k-hop traversal + typed
templates) with adapters to NetworkX and to RAG-grounding text, terminating in a
`MethodsGraphProvider` that speaks the `quration` Method Broker's existing Pydantic
types.

The graph is the data backbone that replaces quration's 5 hardcoded methods. It is
developed, versioned, and embedded independently; quration imports the provider and
injects it at the broker, falling back to its hardcoded registry when the provider is
absent.

## Goals

- One comprehensive "master" methods graph from which **seed subgraphs** can be
  extracted for analysis.
- Two primary downstream uses: **RAG grounding** (subgraph → LLM context) and
  **embeddings/GNN** (subgraph → NetworkX/PyG). Embeddings are Phase 2.
- Clean integration into `quration` via a thin, single-file provider that maps graph
  nodes to quration's `AnalysisMethod` / `ParsedRequest` types.
- Rebuildable end-to-end from cached source snapshots; deterministic and testable
  offline.

## Non-Goals (this spec / MVP)

- ToolUniverse ingestion — Phase 2.
- Embedding/LLM-assisted entity resolution — Phase 2 (MVP is deterministic only).
- PyG/GNN export and link-prediction — Phase 2.
- A server/triplestore — explicitly out; storage is embedded Kùzu, single-user, local.
- Conflation with quration's `hypothesis/` CausalGraph — that is a separate biological
  causal-claims graph and is not modified by this work.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Domain | Heterogeneous methods/tools graph (methods as spine) | User: "all the above" — biomedical methods, stat/ML methods, papers, SOPs unified |
| Sources (MVP) | EDAM + nf-core + BioContainers | nf-core supplies composition (pipeline DAG), EDAM links, and the container/package join key in one source |
| Storage | Kùzu (embedded, Cypher, native NetworkX/PyG export) | Local single-user, no server, ~10k–500k nodes, embedding-export friendly |
| Architecture | A — Staging → Resolve → Load with a canonical entity layer | Clean nodes for RAG/embedding, testable connectors, rebuildable, curation queue built in |
| Entity resolution (MVP) | Deterministic keys only; fuzzy matches → reviewable `SAME_AS` candidates | Never silently merge; transparency for curation |
| Integration shape | Standalone pip package + injected `MethodsGraphProvider` | Independent versioning; quration works with or without it |

## Architecture

### Data flow

```
connectors → data/staging/*.parquet → resolver → data/canonical/*.parquet
           → loader → data/methods.kuzu → extract/ → provider/ → quration broker
```

Rebuildable end-to-end from cached source snapshots. Each stage is deterministic and
idempotent.

### Repo layout (package `methods_graph`)

```
methods_graph/
  connectors/      edam.py · nfcore.py · biocontainers.py   # fetch + normalize → staging Parquet
  resolve/         resolver.py                              # deterministic merge → canonical Parquet
  graph/           schema.py · loader.py                    # idempotent Kùzu build from canonical tables
  extract/         seed.py · adapters.py                    # k-hop/typed traversal; to_networkx, to_rag_text
  provider/        quration_provider.py                     # MethodsGraphProvider → AnalysisMethod mapping
  cli.py                                                    # build · resolve · load · query
data/   staging/*.parquet · canonical/*.parquet · methods.kuzu
tests/                                                      # per-connector + resolver + extract + integration
```

**Module boundaries**

- **connectors/** — pure functions: source input → normalized staging Parquet. Fully
  testable offline against recorded fixtures; no other module depends on their internals.
- **resolve/** — staging records → canonical node/edge tables + `SAME_AS` candidates.
  Deterministic; golden-table tested.
- **graph/** — schema definition + idempotent loader that rebuilds the Kùzu DB from
  canonical tables.
- **extract/** — seed-subgraph traversal over Kùzu + output adapters. Knows nothing of
  quration.
- **provider/** — the *only* quration-aware module. Maps graph results to
  `AnalysisMethod` / consumes `ParsedRequest`. Keeps coupling in one file.

## Graph schema

### Node types

`Method` (canonical join hub) · `Pipeline` (nf-core) · `Module` · `Container`
(BioContainer) · `Package` (bioconda) · `Operation` · `Topic` · `Data` · `Format`
(EDAM) · `Paper`.

Every node carries `provenance { source, source_url, ingested_at }`.

### Edge types

- `Pipeline -[:HAS_MODULE]→ Module`
- `Module -[:WRAPS]→ Method`
- `Module -[:DOWNSTREAM_OF]→ Module`  (pipeline DAG = method composition)
- `Method -[:PACKAGED_AS]→ Container -[:FROM_PACKAGE]→ Package`
- `Method -[:PERFORMS]→ Operation`
- `Method -[:HAS_TOPIC]→ Topic`
- `Operation -[:INPUT]→ Data`, `Operation -[:OUTPUT]→ Data`
- `Data -[:HAS_FORMAT]→ Format`
- `Operation -[:IS_A]→ Operation`  (EDAM hierarchy)
- `Method -[:CITES]→ Paper`
- `Method -[:SAME_AS]→ Method`  (resolution candidates; carries `confidence`, `source`)

Edges carry provenance as above.

### Mapping a `Method` neighborhood → quration `AnalysisMethod`

A `Method` node plus its 1-hop neighborhood materializes one
`quration.broker.models.AnalysisMethod`:

| AnalysisMethod field | Graph source |
|---|---|
| `id`, `name`, `description` | `Method` node |
| `category`, `implementation_type`, `version` | `Method` / `Pipeline` / `Container` |
| `repository_url`, `documentation_url` | nf-core / BioContainers metadata |
| `inputs`, `outputs` (`MethodInputSpec`/`OutputSpec`) | `Operation -INPUT/OUTPUT→ Data -HAS_FORMAT→ Format` |
| `tags` | `Operation` / `Topic` labels |
| `supported_modalities` | derived from `Topic` |
| `compute_requirements.container_image` | `Container` URI |
| `publications` | `Paper` (DOI/PMID) |
| `quality_metrics` (reproducibility, citations, peer-review, rating) | `Paper` citations, nf-core signals |
| `status` | `Method` status (active/deprecated/experimental) |

## Entity resolution (MVP — deterministic only)

Hard-merge staging records into one canonical `Method` when join keys agree:

- **bioconda package name** — nf-core `environment.yml` ↔ BioContainers (strong, reliable).
- **bio.tools ID** — nf-core `meta.yml` ↔ EDAM/bio.tools.
- name-normalization as a tiebreak only.

Anything uncertain becomes a `SAME_AS` candidate edge (with `confidence` + `source`),
surfaced for human review — **never silently merged**. Embedding/LLM-assisted resolution
and ToolUniverse linkage are Phase 2.

## Seed-subgraph extraction & provider contract

### Extraction

- `seed(node_ids, k_hops, edge_types, direction) -> Subgraph` — Cypher-templated k-hop
  traversal over Kùzu.
- A typed **"method neighborhood"** template returning the exact 1–2 hop slice needed to
  build an `AnalysisMethod`.

### Adapters

- `to_rag_text(subgraph) -> str` — structured markdown/JSON-LD context block for LLM
  grounding.
- `to_networkx(subgraph) -> nx.Graph` — for analytics / embedding prep.
- `to_pyg(...)` — Phase 2.

### Provider (the quration seam)

```python
class MethodsGraphProvider(Protocol):
    def get_methods(self) -> list[AnalysisMethod]: ...                       # hydrate registry
    def retrieve_context(self, req: ParsedRequest) -> str: ...               # seed subgraph → RAG text
    def score_method(self, method_id: str, req: ParsedRequest) -> float: ... # graph score (Phase 2)
```

## Integration with quration (slot-ins)

Build the graph standalone; quration injects the provider. Ranked seams:

| # | Seam | File | Integration |
|---|---|---|---|
| 1 | Registry hydration ⭐ | `broker/method_registry.py:30-46` | Replace 5 hardcoded methods with `get_methods()` output |
| 2 | Broker DI seam ⭐ | `broker/method_broker.py:33-48` | Inject `methods_graph` provider once; registry/parser/matcher read from it |
| 3 | Matcher scoring | `broker/matching_engine.py:68-135` | Add graph/EDAM-overlap score component (uses `score_method`, Phase 2) |
| 4 | Parser grounding | `broker/request_parser.py:49-95` | `retrieve_context()` as RAG context before LLM parse |
| 5 | Plan generator | `analysis/plan_generator.py:~64` | Replace hardcoded pipeline list with graph query |
| 6 | EDAM in ontologies | `data_sources/ontologies.py:13-307` | They query OLS for EFO/MONDO but not EDAM; graph fills it |
| 7 | Benchmark metric | `benchmarks/harness.py` | Add method-recommendation accuracy so integration is measurable |

Quration must continue to function when the provider is absent (falls back to hardcoded
registry). Coupling lives only in `provider/quration_provider.py`.

## Testing strategy

- **Connectors:** recorded source fixtures (EDAM TSV slice, a few nf-core module
  `meta.yml`/`environment.yml`, a BioContainers API sample). No network in tests.
- **Resolver:** golden canonical tables from fixture staging inputs; assert hard-merges
  and `SAME_AS` candidates.
- **Extract/provider:** a tiny fixture Kùzu graph; assert k-hop results, `to_rag_text`
  shape, and `AnalysisMethod` materialization.
- **Integration:** one test builds the full mini-graph end-to-end and runs the provider
  against a sample `ParsedRequest`.

## Phasing

**MVP (this spec)**
- EDAM + nf-core + BioContainers connectors.
- Deterministic entity resolution.
- Kùzu loader; k-hop + method-neighborhood extraction.
- `to_rag_text` + `to_networkx` adapters.
- Provider with `get_methods` + `retrieve_context`.

**Phase 2**
- ToolUniverse connector.
- Embedding/LLM-assisted entity resolution (resolve `SAME_AS` candidates).
- `score_method` + matcher integration.
- `to_pyg` + GNN / link-prediction (suggest missing edges/candidate methods).
- Method-recommendation accuracy benchmark inside quration.

## Open questions / risks

- **Source snapshotting:** nf-core and BioContainers are live; MVP pins cached snapshots
  for reproducibility. Refresh cadence is a Phase 2 concern.
- **EDAM coverage gaps:** not every tool has clean EDAM annotations; unannotated methods
  still load but with thinner `tags`/`inputs`/`outputs`.
- **Kùzu API churn:** pin a version; confirm `COPY FROM` Parquet + NetworkX export against
  the pinned release during implementation (via context7).
