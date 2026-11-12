# Architecture

**What this is:** the whole-repo map. Package layout, the three subsystems and how they connect, each data flow, the Kuzu schema, the Biolean trust boundary, the full CLI, tests and CI gating, Makefile targets, dependencies and invariants.
**Status:** as of 2026-09-22. Local `main` is at `6b28222`, 56 commits ahead of `origin/main` (`86ce425`). None of the Biolean work is pushed, so CI has never run on it.
**Read next:** [STATUS.md](STATUS.md) for what works as of 2026-09-22. Then the subsystem you are touching: [methods-graph.md](methods-graph.md), [method-sequencing-benchmark.md](method-sequencing-benchmark.md) or [biolean/README.md](biolean/README.md). For the identifier traps, read [CLAUDE.md](../CLAUDE.md#identifier-schemes--the-trap-that-has-cost-the-most).

---

## Conventions used in this doc

- **`mg` is shorthand. It is not an installed command.** The console script is `methods-graph` (`pyproject.toml:25`, installed as `.venv/bin/methods-graph`). On this Mac a bare `mg` runs `/usr/bin/mg`, which is an unrelated text editor. Define the shorthand once per shell, from the repo root:

  ```bash
  alias mg='.venv/bin/python -m methods_graph.cli'   # or: alias mg='.venv/bin/methods-graph'
  ```

- There is no `python` on PATH. Always use `.venv/bin/python`.
- Every command below runs from the repo root. Each is tagged with what it needs:

  | Tag | Meaning |
  |---|---|
  | **DB** | needs `data/methods.kuzu`, which is gitignored. Rebuild it with `make rebuild` |
  | **snap** | needs `snapshots/` (graph sources, gitignored) |
  | **go** | needs `snapshots/go/` (GO + GOA + ECO files, gitignored) |
  | **net** | makes network calls |
  | **nf** | needs Nextflow + Java (installed via brew on this machine) |
  | **$** | paid or usage-metered model calls (`claude:` via the `claude` CLI, `openai:` via `OPENAI_API_KEY`) |

---

## 1. The three subsystems

| Subsystem | What it is | Its data | State as of 2026-09-22 |
|---|---|---|---|
| **Methods graph + guardrail** | A Kuzu knowledge graph of bioinformatics methods, modules, containers, EDAM terms, STATO/OBI terms and curated statistics. The guardrail and provider read it. | `data/methods.kuzu`, built from `snapshots/` | Built 2026-06-19. Its hash matches `data/methods.lock.json`. Guardrail code is unchanged since `430300a` (2026-07-31). See [methods-graph.md](methods-graph.md). |
| **Method-sequencing benchmark** (`bench/`) | Asks whether an LLM knows which tools a goal needs and in what order. Gold comes from nf-core Nextflow DAGs. | Pipeline clones + `dag.mmd`, produced by `mg ingest`. The graph is the scoring oracle. | Plans 1 and 2 merged (`529ffc5`, `59d5111`). No items are tracked. The only run is the untracked pilot in `bench-runs/2026-08-08-pilot/`. See [method-sequencing-benchmark.md](method-sequencing-benchmark.md). |
| **Biolean** (`biolean/`) | A structural proof checker for GO annotation claims, plus a two-track benchmark. | `snapshots/go/`, loaded into an in-memory `FactStore`. **No Kuzu** in the checker (one optional read-only use in `biolean bench`, see below). | Merged in `7bc79ef`, `b0f80c4`, `894072d` and `6b28222`, all unpushed. See [biolean/README.md](biolean/README.md) and [biolean/benchmark.md](biolean/benchmark.md). |

### How they relate

```
 upstream: EDAM, nf-core/modules, BioContainers, bio.tools, STATO, OBI      BioClaw skills (manual copy)
                 | mg fetch  [net]                                                        |
                 v                                                                        v
            snapshots/  --------------------- mg rebuild [snap] --------------------------+
                                                            |
                                                            v
                                      data/methods.kuzu  +  data/methods.lock.json
                                                            |  (opened read-only)
      +-----------------------------------------------------+-------------------------------+
      v                                                     v                               v
 provider/ + extract/  <-- guardrail.py, explain.py      bench/oracle.py = scoring       audit.py, kgx.py,
 (query, methods)          (guardrail, guardrail-chain,  oracle for the sequencing       planner.py (suggest)
                           explain, skills --coverage)   benchmark

 nf-core pipeline clones + dag.mmd (mg ingest [net, nf]) --> bench/gold.py --> sequencing-benchmark gold

 GOA + GO + ECO (mg biolean fetch [net]) --> snapshots/go --> biolean/store.py (FactStore, in memory)
                                                                  --> biolean/kernel.py  <-- elaborate, tactics, biolean/bench
```

Facts about the joins:

- **The graph is the oracle, not a contestant.** Of the sequencing-benchmark code, only `bench/oracle.py` opens the DB. It reads Method ids, `Module-WRAPS->Method`, `PERFORMS`, and `INPUT`/`OUTPUT` to **Data** nodes only (`bench/oracle.py:88-138`). `bench/score.py:15` imports only the `HANDOFF_*` vocabulary from `guardrail.py`. It computes validity by reachability itself and does not call `classify_handoff`.
- **The guardrail reads the graph through a provider.** `guardrail.py` imports nothing from the package. It takes any provider object and calls `resolve_method_ids`, `method_preconditions` and `skill_wraps_method_ids` on it (`guardrail.py:342-363`), plus `neighborhood` for chains (`guardrail.py:296`). Its docstring (`guardrail.py:334-336`) also lists `skill_preconditions`, which the guardrail never calls; `explain.py:49` and `skills --coverage` (`cli.py:1156`) do. The CLI passes `KuzuMethodsGraphProvider`. `rules.py` is the DB-free alternative: it reads the curated YAML directly, and only `hook.py` uses it.
- **Biolean does not use Kuzu.** `kernel.py`, `store.py`, `tactics.py`, `elaborate.py` and the parsers import no Kuzu. The only graph contact in any Biolean path is optional. `biolean bench run` and `biolean bench score` build an `m:` resolver for the hypothesize track's `method_resolves` field through `bench/normalize.py` and `bench/oracle.py`. That resolver opens `data/methods.kuzu` read-only whenever the file exists, even on a prove-only run (`cli.py:1243-1252`, `1365-1368`). Without the DB the field is `null`.
- **Shared code across the two benchmarks:** `bench/adapters.py` supplies the contestants (`claude:`, `openai:`, `static:`) to both. `biolean/bench/items.py` imports `read_release` from `biolean/store.py` (not `fetch.gaf_header`) to read the release identity; `fetch.py` imports `gaf_header` from there too.

---

## 2. Repository layout

| Path | Tracked? | What |
|---|---|---|
| `src/methods_graph/` | yes | the package (section 3) |
| `tests/` | yes | 71 test files, 1,014 tests, plus `fixtures/` and `biolean_fixture.py` (section 8) |
| `docs/` | yes | this doc set; `DATA_SOURCES.md`, `REFERENCES.md`; `superpowers/specs/` (2 specs) and `superpowers/plans/` (4 plans) |
| `examples/` | yes | `causal_evaluability_demo.py` and `workflow_demo.py` (self-contained); `merge_audit.py` (needs `snapshots/modules`) |
| `data/methods.lock.json` | yes | graph hash, counts, coverage and source pins from the last `rebuild` |
| `data/methods.kuzu`, `data/methods.kuzu.staging/` | no (`.gitignore:6-7`) | the built graph: a single 11.6 MB file under kuzu 0.11.3, plus the Parquet of the last build |
| `snapshots/` | no (`.gitignore:11`) | graph sources (`EDAM.tsv`, `modules/`, `biocontainers/`, `biotools/`, `stato.owl`, `obi.owl`, `skills/bioclaw/`, `snapshot.json`) and Biolean's `go/` |
| `ingest.example.yaml`, `catalog.ingest.yaml` | yes | `mg ingest` manifests. The catalog pins 96 pipelines with `wiring: false`. |
| `Makefile`, `pyproject.toml`, `uv.lock` | yes | section 9 and section 10 |
| `.github/workflows/ci.yml` | yes | the `test` and `rebuild-verify` jobs (section 8) |
| `/bench/`, `/biolean-bench/` | no (`.gitignore:16`, `:19`) | default `--out` for the two `bench build` commands |
| `bench-runs/`, `opus.jsonl`, `modal.jsonl`, `opus.partial.jsonl` | untracked, not ignored | run artifacts. See [STATUS.md](STATUS.md). |
| `site/` | untracked nested git repo | a separate landing-page project. It is not part of the package and reads no repo data. |

---

## 3. Package map (`src/methods_graph/`)

Verified against the tree on 2026-09-22. The line counts come from `wc -l`. Each row gives the module's job in one line.

### Top-level modules

| Module | Lines | Job |
|---|---|---|
| `__init__.py` | 2 | package marker |
| `cli.py` | 2,087 | every subcommand. `main()` is the `methods-graph` script. The parsers are at `cli.py:1701-1990`, and each `cmd_*` function implements one subcommand. |
| `types.py` | 155 | `NodeKind` (21 kinds) and `EdgeKind` (20 kinds) enums, plus the `NodeRecord`/`MethodRecord`/`EdgeRecord`/`Provenance` staging records |
| `fetch.py` | 839 | every network fetcher behind injectable seams. For the graph: EDAM, the nf-core/modules clone, BioContainers, bio.tools, STATO, OBI. For `ingest`: an nf-core pipeline clone plus the `nextflow -preview -with-dag` DAG. For Biolean: GOA, GO and ECO. |
| `pipeline.py` | 184 | reproducible-build helpers: `compute_graph_hash`, snapshot verification, lock read/write, coverage diff |
| `pipeline_merge.py` | 50 | rolls up `DOWNSTREAM_OF` attestations across pipelines before resolve (it has effect on the ingest path only) |
| `ingest.py` | 127 | ingest-manifest loader and shared-source resolution for `mg ingest` |
| `audit.py` | 866 | 26 schema invariants, plus provenance, id-uniqueness and coverage checks, plus optional source reconciliation (`--snapshot`) |
| `explain.py` | 87 | `mg explain`: traces assumption → via → evidence → source YAML |
| `guardrail.py` | 367 | verdict engine returning EVALUABLE / BLOCKED / NOT_EVALUABLE / FACTS_REQUIRED for a method, a keyword, a skill or a chain. It takes a provider and has no DB import. |
| `rules.py` | 196 | DB-free rule engine over three crosslink YAMLs. It knows 12 methods. Only `hook.py` and tests use it. |
| `hook.py` | 186 | Claude Code PreToolUse hook that gates DESeq2 runs on the samplesheet. It is not wired into any settings file. |
| `planner.py` | 215 | `mg suggest`: attestation-ranked next steps. It is inert on the committed DB, which has 0 `DOWNSTREAM_OF` edges. |
| `kgx.py` | 114 | `mg export-kgx`: `nodes.tsv` and `edges.tsv`. Categories are the raw `kind` strings, and properties are dropped. |

### Graph build and read

| Module | Lines | Job |
|---|---|---|
| `connectors/edam.py` | 87 | EDAM TSV → Operation / Data / Format nodes + `IS_A` |
| `connectors/nfcore.py` | 480 | module `meta.yml` → Module + Method + `WRAPS` + `INPUT`/`OUTPUT`. Includes the synthetic `fmt:pat:<ext>` Format nodes. |
| `connectors/nfcore_pipeline.py` | 188 | pipeline checkout → Pipeline + `HAS_MODULE` + `DOWNSTREAM_OF`. `iter_module_metas()` is the single definition of `mod:` ids. |
| `connectors/nextflow_dag.py` | 129 | Nextflow mermaid `dag.mmd` → process edges, with cycle breaking |
| `connectors/module_execution.py` | 231 | module `main.nf` / `environment.yml` → ExecutionSpec + `RUNS_AS` (ingest path only) |
| `connectors/biocontainers.py` | 29 | BioContainers record → Package + Container |
| `connectors/biotools.py` | 114 | bio.tools JSON → EDAM operation map, used to enrich `PERFORMS` |
| `connectors/ontology.py` | 315 | STATO and OBI OWL → StatisticalMethod / Assay / Protocol / StudyDesign / Instrument / Material + `IS_A`. Needs `rdflib`. |
| `connectors/skills.py` + `skill_aliases.yaml` | 164 | BioClaw `SKILL.md` → Skill + `WRAPS`. Only declared tools create edges. |
| `crosslinks/__init__.py` ← `method_statistical_methods.yaml` | 233 | curated `USES_STATISTICAL_METHOD` |
| `crosslinks/amenable.py` ← `operation_amenable_statistics.yaml` | 185 | curated `AMENABLE_TO` (Operation → StatisticalMethod) |
| `crosslinks/assumptions.py` ← `statistical_method_assumptions.yaml` | 269 | Assumption nodes, curated `stat:` nodes, `REQUIRES_ASSUMPTION` |
| `crosslinks/assumption_diagnostics.py` ← `assumption_diagnostics.yaml` | 206 | Diagnostic nodes and `CHECKED_BY` |
| `crosslinks/assay_methods.py` ← `assay_methods.yaml` | 181 | `ANALYZED_BY` (Assay → Method) |
| `crosslinks/data_handoffs.py` ← `data_types.yaml` | 171 | curated Method → Data `INPUT`/`OUTPUT` |
| `crosslinks/method_operations.py` ← `method_operations.yaml` | 147 | adds and removes curated `PERFORMS` edges |
| `crosslinks/modalities.py` ← `modalities.yaml` | 127 | Modality + `HAS_MODALITY`. Needs Pipeline nodes, so it only takes effect on the ingest path. |
| `resolve/resolver.py` | 317 | union-find merge on the `m:` id, plus `SAME_AS` candidates |
| `graph/schema.py` | 31 | Kuzu DDL (section 5) |
| `graph/loader.py` | 88 | writes Parquet into `<db>.staging/`, then COPYs it into Kuzu. Dangling edges are dropped and logged. |
| `schema/` (`__init__.py` + `methods_graph.yaml`) | 13 + 444 | LinkML schema. It lags `types.py` and is **not** the source of the DDL. |
| `extract/seed.py` | 379 | `seed()`, `method_ids_matching()` (fuzzy), `method_neighborhood()`, `method_preconditions()` (the guardrail contract) |
| `extract/adapters.py` | 31 | Subgraph → NetworkX or RAG text. The benchmark's adapters are `bench/adapters.py`. |
| `provider/quration_provider.py` | 260 | `KuzuMethodsGraphProvider`: the read API behind `query`, `methods`, `guardrail*`, `explain` and `skills`, and the shape Dogma's quration consumes. quration is not installed here. |
| `workflow/ir.py`, `ledger.py`, `validator.py` | 73 / 98 / 285 | WorkflowIR, an append-only provenance ledger, and validation against the graph. Only `examples/` and tests use them; there is no CLI surface. |

### Method-sequencing benchmark (`bench/`)

| Module | Lines | Job |
|---|---|---|
| `oracle.py` | 196 | **the only file that opens the DB.** Contains the `Oracle` protocol, `StaticOracle`, `KuzuOracle` (read-only), the JSON-oracle loader and `coverage()`. |
| `normalize.py` | 138 | free text and `mod:` ids → `m:` ids by exact lookup plus a 10-entry alias table. It never uses the fuzzy resolver. |
| `gold.py` | 96 | Nextflow DAG → ordered, deterministic `mod:` gold sequence and edges |
| `build.py` | 124 | gold → frozen items (`whole_pipeline`, `next_step`) and the build manifest |
| `run.py` | 408 | walks clones into items (`build_from_clones`); `run_items`; `rescore`; `summarize` |
| `render.py` | 106 | item → prompt; reply → list of tool names |
| `score.py` | 322 | selection F1, sequencing over gold DAG edges, validity by reachability, next-step top-1/top-k. Equivalence is `operation ∩ input Data`, plus identity. |
| `adapters.py` | 158 | contestants, each `(prompt) -> str`: `claude:` (closed-book CLI), `openai:` (temperature 0), `static:`. Biolean shares them. |
| `baselines.py` | 128 | `gold:`, `modal:`, `random:<seed>[:<k>]` |

### Biolean (`biolean/`)

The ledger rows, and the four modules the ledger branch changed (`kernel.py`, `store.py`, `gaf.py`, `bench/items.py`), are counted at `edd9d4c`; the other rows are as of 2026-09-22.

| Module | Lines | Job |
|---|---|---|
| `props.py` | 138 | `Prop`/`Annotation`/`Term`/`Edge`, the 13 GAF qualifiers, the qualifier→aspect table, `PROPAGATING_RELATIONS = (is_a, part_of)`. Pure data. |
| `errors.py` | 52 | the 21 error codes and the 6-key error record |
| `kernel.py` | 529 | **the checker.** `check(derivation, store)` applies 4 rules (`axiom`, `is_a`, `part_of`, `sorry`) and returns a 12-key verdict dict. It also exports `propagating_parents`/`propagating_children`, and `check_term`/`check_qualifier_aspect` for the ledger's append check. |
| `elaborate.py` | 95 | identifier rewrites before the kernel (symbol → subject, alt_id → primary, taxon spelling), each one reported. Also `elaborate_and_check`. |
| `store.py` | 269 | `FactStore` protocol, `StaticFactStore` (dict indexes), `MaskedFactStore` (hides annotation ids), the release identity (`gaf_header`, `read_release`), `base_digests`, `load_base`, and `load_store(dir, ledger_dir=None, ...)` |
| `obo.py` | 85 | `go-basic.obo` parser (`[Term]` stanzas only) |
| `gaf.py` | 126 | GAF 2.2 reader with ordered, counted filters, and `GAF_COLUMNS`. The annotation id is `gaf:` plus a 16-hex-character sha256 prefix. |
| `eco.py` | 29 | `gaf-eco-mapping.txt` reader |
| `tactics.py` | 154 | untrusted helpers: `goals_for`, `applicable`, and `prove` (BFS shortest derivation) |
| `render.py` | 88 | `render_verdict` (used by `check --render`) and `render_derivation` (called only from tests) |
| `ed25519.py` | 107 | verify-only Ed25519 (RFC 8032 §5.1.7, `S < L`), stdlib ints. **Trusted.** |
| `sshsig.py` | 462 | the OpenSSH `sshsig` blob, `allowed_signers` reader and writer, key digests (`key16`, `fingerprint`), the fixture-key refusal list. **Trusted.** |
| `ledger/errors.py` | 97 | the ledger's error codes and the 7-key `LedgerError`; `LedgerIntegrityError` (exit 2) |
| `ledger/format.py` | 392 | canonical bytes, entry hash, the field schema (`shape_errors`), the character rules, RFC 6901 pointers |
| `ledger/check.py` | 538 | the append check for `axiom`, `derived` and `computed` bodies, with `fix`/`options` per error |
| `ledger/integrity.py` | 409 | per-file integrity (signature, chain, signer), `--extends`, the verification cache |
| `ledger/load.py` | 197 | base binding (admitted / stale / superseded), the `ledger` report block, `load_with_ledger`, `--recheck` |
| `ledger/append.py` | 357 | `init`, signing through the `runner` seam, self-verify, the append write |
| `bench/items.py` | 325 | population filters, `hide_exact`/`hide_subtree`, item build, modal fit, `--since` cut, seeded sample |
| `bench/render.py` | 92 | closed-book prompt; `parse_reply` takes the first JSON object with a `steps`, `root` or `biolean` key |
| `bench/baselines.py` | 191 | `gold:`, `random:<seed>`, `modal:` (prove track); `template:` (hypothesize track) |
| `bench/run.py` | 197 | render → adapter → score, one streamed row per item; thread-pool runner for `--workers`; `rescore` |
| `bench/score.py` | 266 | scores each row over `MaskedFactStore`; per-track summary with denominators |

---

## 4. Data flows

### 4a. Graph: fetch → snapshots → rebuild → DB + lock (the committed path)

```
mg fetch --dest snapshots                                                    [net]
  EDAM.tsv            unversioned "latest" URL; sha256 recorded
  modules/            git clone --depth 1 nf-core/modules at HEAD (an existing clone is reused as-is)
  biocontainers/      live API, for the bioconda packages found in modules/   (not pinned)
  biotools/           live API, for the bio.tools ids found in modules/       (not pinned)
  stato.owl, obi.owl  unversioned URLs; sha256 + versionIRI recorded
  snapshot.json       rewritten wholesale on every run
snapshots/skills/bioclaw/   a manual copy: nothing in the repo fetches or pins it
        |
        v
mg rebuild  (= make rebuild)                        [snap; offline; needs rdflib]
  1 verify  pipeline.verify_snapshots: EDAM/STATO/OBI sha256 + the nf-core commit vs snapshot.json
  2 build   cmd_build: connectors -> merge_downstream_of -> resolver -> bio.tools PERFORMS
            -> curated PERFORMS add/remove -> curated Data I/O -> skills
            -> curated statistics layer (USES, REQUIRES_ASSUMPTION, AMENABLE_TO, CHECKED_BY, ANALYZED_BY)
            (modalities and execution specs are skipped: rebuild passes no --nfcore-pipelines)
  3 load    graph/loader.py: Parquet into <db>.staging/, then COPY into Kuzu (dangling edges dropped + logged)
  4 audit   audit.audit_graph, 26 invariants: a hard gate, and no lock is written on failure
  5 lock    compute_graph_hash -> methods.lock.json written NEXT TO --db (cli.py:782)
  6 diff    coverage delta against the lock at git HEAD
```

- **Fact:** the on-disk DB was built on 2026-06-19 from snapshots fetched on 2026-06-18 (nf-core/modules `d13eeb9f`). It has 905 methods, 19,425 nodes and 32,757 edges. Its hash `sha256:c6940e39…` equals `data/methods.lock.json:70`. Rebuilding into a scratch dir with `rebuild --check` reproduced that hash in 5 of 7 runs on 2026-09-22 (12–22 s each).
- **Fact: the hash computation is unstable.** The other 2 of those 7 runs printed MISMATCH (`sha256:e303b738…`, `sha256:a59566a2…`), yet the DB one of them wrote re-hashes to `c6940e39…`. `compute_graph_hash` relies on Kuzu's `ORDER BY` (`pipeline.py:24-28`), which sometimes returns the same 32,757 edge rows out of order, even on the unchanged `data/methods.kuzu`. The one-liner below, `rebuild --check` and CI's determinism step can all report a false mismatch; rerun before concluding a DB differs from the lock. The measured rates are in R11 of [methods-graph.md](methods-graph.md#5-reproducibility); the fix is [BACKLOG.md](BACKLOG.md) M21.
- **Fact:** `rebuild` always passes `snapshots/skills/bioclaw` with no existence check (`cli.py:833`). A missing directory silently yields 0 Skill nodes and a hash mismatch. So the weekly CI drift step, which starts from a fresh `mg fetch`, cannot match the lock even when no upstream source has moved.
- **Fact:** the hash covers node id, name, kind, properties, `bioconda_pkg` and `biotools_id`, plus every edge's endpoints, kind and properties. It excludes `source`, `source_url` and `ingested_at` (`pipeline.py:16-55`).

Useful read-only checks:

```bash
.venv/bin/python -m methods_graph.cli audit --db data/methods.kuzu     # [DB] <1 s; exit 1 if any check fails
.venv/bin/python -c "import kuzu; from methods_graph.pipeline import compute_graph_hash; \
c=kuzu.Connection(kuzu.Database('data/methods.kuzu', read_only=True)); print(compute_graph_hash(c))"   # [DB] compare to data/methods.lock.json:70; rerun if it differs (see above)
rm -rf /tmp/mg-rebuild && mkdir -p /tmp/mg-rebuild && cp data/methods.lock.json /tmp/mg-rebuild/ && \
  .venv/bin/python -m methods_graph.cli rebuild --db /tmp/mg-rebuild/methods.kuzu --check          # [snap] 12-22 s; the repo is untouched
```

`make rebuild-check` is **not** read-only. It rebuilds over `data/methods.kuzu` and leaves only the lock alone.

### 4b. Graph: `mg ingest` (a separate path that builds a different graph)

```
manifest YAML: shared sources + pipelines as name@revision [+ nxf_ver]  (ingest.example.yaml, catalog.ingest.yaml)
        |
mg ingest --manifest M --dest W --db W/graph.kuzu                        [net, nf, snap]
  1 resolve the declared shared sources from the snapshot layout (fails loudly if one is missing)
  2 fetch_nfcore_pipeline per pipeline -> W/pipelines/<name>/ (+ dag.mmd from
      `nextflow run <clone> -profile test -preview -with-dag`, unless wiring: false)
  3 cmd_build with nfcore_modules = nfcore_pipelines = W/pipelines        (no skills)
      adds Pipeline, HAS_MODULE, DOWNSTREAM_OF, ExecutionSpec/RUNS_AS, Modality/HAS_MODALITY
  4 audit gate: raises AFTER writing the lock
  5 W/ingest.lock.json          (never data/methods.lock.json)
```

- **Fact:** no ingest-built DB exists in this checkout. Pipeline, `DOWNSTREAM_OF`, ExecutionSpec and Modality therefore have 0 rows in the committed graph, and `suggest` returns nothing useful.
- **Caution:** the header of `ingest.example.yaml` suggests `--db data/methods.kuzu`. Doing that replaces the rebuild graph with a different one that no longer matches `data/methods.lock.json`. Pass a separate `--db`.
- **Open question:** which DB is canonical, the rebuild graph or an ingest graph? See [BACKLOG.md](BACKLOG.md).

### 4c. Sequencing benchmark: build → items → run → rows → score

```
mg ingest ... --dest W                        [net, nf]   -> W/pipelines/<name>/{clone, dag.mmd}, W/ingest.lock.json
        |
mg bench build --pipelines W/pipelines --out bench [--goals goals.json] [--db data/methods.kuzu]
  gold.py:  dag.mmd -> process edges (connectors/nextflow_dag.py) -> mod: ids (connectors/nfcore_pipeline.py)
  build.py: gold -> whole_pipeline + next_step items; next-step items that would print their own answer
            are dropped (this needs the oracle)
  -> bench/items/<pipeline>.json, bench/gold/manifest.json   (provenance read from W/ingest.lock.json)
        |
mg bench coverage --items bench/items         [DB or --oracle-json]   read this before any score
mg bench run --items bench/items --model M --out rows.jsonl   [DB or --oracle-json; $ for claude:/openai:]
  render.render_prompt -> adapter(prompt) -> raw -> render.parse_tool_list -> normalize.py (-> m:) -> score.py
  -> one row per item, streamed and flushed; summary JSON to stdout
mg bench score --results rows.jsonl [--out rescored.jsonl]    re-derives every score from the retained raw output
```

- **Fact:** the default `--pipelines snapshots/pipelines` does not exist, and `bench build` on a missing directory exits 1 with a traceback. The pilot was built from an `ingest --dest` scratch directory. Its clones are gone, but its DAGs and results are kept in `bench-runs/2026-08-08-pilot/`, and they re-score byte-identically with current code.

### 4d. Biolean: fetch → snapshots/go → store → check / prove

```
mg biolean fetch --out snapshots/go                                          [net]
  goa_human.gaf.gz (current GOA) -> the GAF header's go-version -> go-basic.obo at THAT release
  -> gaf-eco-mapping.txt -> snapshot.json
        |
snapshots/go --store.load_store--> obo.py + gaf.py + eco.py --> StaticFactStore   (13-16 s per CLI call, no cache)
        |
mg biolean check D.json [--render]    elaborate.py (reported rewrites) -> kernel.check -> verdict JSON
mg biolean prove "SUBJECT QUALIFIER TERM" [--taxon]    tactics.prove -> derivation (it is not re-checked here)
mg biolean goals SUBJECT [--aspect F|P|C]              tactics.goals_for -> derivable propositions
```

The ledger ([biolean/ledger.md](biolean/ledger.md)) adds two flows:

```
mg biolean ledger append --fact ...  ->  check.py (§2)  ->  ssh-keygen -Y sign (runner seam)  ->  self-verify  ->  ledger/<key16>.jsonl
load_store(ledger_dir)  ->  integrity.py  ->  load.py (base binding)  ->  StaticFactStore(base + admitted)
```

`append` first loads the ledger the same way (`load.load_with_ledger`, which `load_store(ledger_dir=...)` delegates to), so an entry is checked against the base plus the admitted facts; `prove|check|goals --ledger` run over the second flow's store.

- **Fact:** the on-disk `snapshots/go` was **not** made by `biolean fetch`. It has no `snapshot.json`, and it is a release-skewed pair: the OBO is `releases/2026-07-26`, while the GAF was built against GO `2026-04-27`. `biolean fetch` always downloads the current GOA, so the frozen items can be rebuilt only while this directory is kept. See [biolean/README.md](biolean/README.md).

### 4e. Biolean benchmark: build → items → run → rows → score

```
mg biolean bench build --out biolean-bench [--store snapshots/go --per-track 500 --seed 0 --since YYYY-MM-DD]   [go]
  population (7 ordered drop filters) -> prove items (hide_exact; tactics.prove must still derive -> gold)
  -> fit_modal (on every prove-eligible item) -> hypothesize items (hide_subtree; prove must fail; a sorry must be ACCEPTED)
  -> --since cut -> seeded sample -> write
  -> biolean-bench/items/{prove,hypothesize}.json, manifest.json, modal.json      (41-60 s; rebuilt byte-identical to biolean-bench/ on 2026-09-22)
        |
mg biolean bench coverage --items biolean-bench      prints manifest.json; does not load the store
mg biolean bench run --model M --track prove --out rows.jsonl [--workers N] [--resume]   [go; $ for claude:/openai:]
  release check (OBO/GAF headers vs manifest; exit 2 on mismatch) -> render prompt -> adapter
  -> parse_reply -> elaborate + kernel.check over MaskedFactStore(store, item.hidden) -> row, streamed and flushed
mg biolean bench score --results rows.jsonl [--out ...]   [go]  re-derives from each row's raw, goal and hidden
```

- **Caution (fact):** `biolean bench run` without `--resume` opens `--out` with `'w'` (`cli.py:1416`). A mistyped restart truncates a paid results file. Rerunning with `--resume` is the safe restart. [biolean/benchmark.md](biolean/benchmark.md) covers running a paid model safely.

---

## 5. Kuzu schema

One node table and one rel table. The type of a node or edge is a `kind` string column, not a separate table (`graph/schema.py:3-30`). `CALL show_tables()` on the DB lists only `Entity` (NODE) and `Rel` (REL).

```sql
CREATE NODE TABLE Entity(id STRING PRIMARY KEY, name STRING, kind STRING, properties STRING,
                         bioconda_pkg STRING, biotools_id STRING, source STRING, source_url STRING, ingested_at STRING)
CREATE REL TABLE Rel(FROM Entity TO Entity, kind STRING, properties STRING,
                     source STRING, source_url STRING, ingested_at STRING)
```

`properties` is a JSON string. Queries filter on `kind`, for example `MATCH (m:Entity {kind:'Method'})-[:Rel {kind:'PERFORMS'}]->(o)`.

**Node kinds in `data/methods.kuzu`:** 16 of the 21 declared. Counts come from `MATCH (n:Entity) RETURN n.kind, count(*)`, run on 2026-09-22.

| kind | count | id prefix | source |
|---|---|---|---|
| Container | 9,139 | `ctr:` | biocontainers |
| Format | 2,100 | `fmt:` (612) / `fmt:pat:` (1,488, synthetic, from nf-core globs) | edam / nfcore |
| Module | 2,038 | `mod:` | nfcore (modules plus nf-core subworkflows; all 117 Module nodes without `WRAPS` are subworkflows) |
| Assay | 1,795 | `obo:` | obi |
| Data | 949 | `data:` | edam |
| Method | 905 | `m:` | nfcore |
| Package | 804 | `pkg:` | biocontainers |
| Instrument | 607 | `obo:` | obi |
| Operation | 537 | `op:` | edam |
| StatisticalMethod | 207 | `obo:` (203) / `stat:` (4) | stato / curated |
| Material | 157 | `obo:` | obi |
| StudyDesign | 101 | `obo:` | obi |
| Assumption | 29 | `assum:` | curated |
| Skill | 28 | `skill:` | skills |
| Diagnostic | 23 | `diag:` | curated |
| Protocol | 6 | `obo:` | obi |
| **total** | **19,425** | | |

**Edge kinds in `data/methods.kuzu`:** 13 of the 20 declared.

| kind | count | kind | count |
|---|---|---|---|
| FROM_PACKAGE | 9,139 | PERFORMS | 920 |
| PACKAGED_AS | 7,684 | REQUIRES_ASSUMPTION | 52 |
| IS_A | 4,988 | AMENABLE_TO | 49 |
| INPUT | 3,945 | CHECKED_BY | 33 |
| OUTPUT | 3,935 | USES_STATISTICAL_METHOD | 18 |
| WRAPS | 1,987 | SAME_AS | 5 |
| | | ANALYZED_BY | 2 |
| **total** | | | **32,757** |

**Declared in `types.py` but absent from the committed DB:**

| Kind | Why it is absent |
|---|---|
| Pipeline, ExecutionSpec, Modality; `HAS_MODULE`, `DOWNSTREAM_OF`, `RUNS_AS`, `HAS_MODALITY` | these are emitted only on the ingest path (`--nfcore-pipelines`), which `rebuild` never passes |
| Topic, Paper; `HAS_TOPIC`, `HAS_FORMAT`, `CITES` | no code emits them (`grep` finds no emitter outside `types.py`) |

The `INPUT`/`OUTPUT` edges total 7,880, but 7,744 of them point to Format and only 136 point to Data. Every coverage figure needs its denominator. [methods-graph.md](methods-graph.md) has the coverage tables. Identifier schemes (`m:`, `mod:`, `op:`/`data:`/`fmt:`) and their traps are in [CLAUDE.md](../CLAUDE.md#identifier-schemes--the-trap-that-has-cost-the-most). Do not restate them elsewhere.

---

## 6. Biolean trust boundary

```
derivation JSON (from an agent or model: untrusted)
   |
   v
elaborate.py      identifier rewrites by lookup: symbol -> subject, alt_id -> primary, 9606/taxon:9606 -> NCBITaxon:9606
   |              every rewrite is reported in verdict["elaboration"]; obsolete terms are never rewritten
   v
kernel.check(derivation, store) -> verdict dict      <- the checker; no I/O
   ^
   |  store: StaticFactStore / MaskedFactStore built by obo.py + gaf.py + eco.py
   |
tactics.py (goals_for, applicable, prove), render.py, biolean/bench/*   <- untrusted helpers; only a kernel verdict counts
```

| Claim | Status |
|---|---|
| "`kernel.py` is the only trusted file" (spec §3, `docs/superpowers/specs/2026-09-21-biolean-design.md:206` in the working tree, `:183` at `6b28222`; `kernel.py:1-4`; `CLAUDE.md` as committed at `6b28222`) | **Fact: true only of the direct imports.** `kernel.py` imports `errors`, `props` and `store.FactStore`. `store.py` imports `eco`, `gaf` and `obo` at module level (`store.py:12-14`), so importing the kernel loads six package modules. The verdict also depends on `StaticFactStore`'s indexes. No test pins the kernel's import surface. |
| The kernel resolves no identifiers itself | **Fact.** An alt_id that reaches it is `ALT_ID_IN_KERNEL`. From the CLI this cannot happen, because the elaborator rewrites alt_ids first. |
| The verdict is about the raw input | **Fact: no.** It is about the *elaborated* derivation. The rewrites are reported, not checked. |
| `ACCEPTED` means "proved from facts" | **Fact: no.** A derivation whose root is a `sorry` is ACCEPTED with exit 0 and `sorry_count` 1. Contradictions can be ACCEPTED both ways, and the tension shows only in `conflicts`. Callers must check `sorry_count == 0` and `conflicts`. |
| `mg biolean prove` output is kernel-checked | **Fact: no.** The CLI prints the prover's derivation without checking it (`cli.py:1505-1518`). Pipe it through `check` to verify it. The benchmark scores every reply, the `gold:` baseline's included, through `elaborate` + `check`, and `gold:` scores 500/500 on the real prove set. |
| Should "only trusted file" be restated? | **Open question.** See [decisions/README.md](decisions/README.md) and [BACKLOG.md](BACKLOG.md). |
| The ledger's verifier modules are trusted | **Fact.** `ed25519.py`, `sshsig.py` and `ledger/` join the trusted set: the ledger decides what enters the store, so it is inside the boundary. None of them imports a network or bench module (`test_ledger_and_verifier_modules_import_no_network_or_bench_module`, `tests/test_biolean_ledger_format.py`). Signing is the contributor's `ssh-keygen`; the repo has no signing code. See [biolean/ledger.md](biolean/ledger.md) §6. |

The rules, error codes and derivation format are in [biolean/README.md](biolean/README.md).

---

## 7. CLI surface

`.venv/bin/python -m methods_graph.cli --help` lists 15 top-level subcommands, 29 leaf commands in all (25 before the ledger added `biolean ledger init|append|verify|show`). Every flag below was taken from `--help` on 2026-09-22, except the ledger rows and the `--ledger` flags, taken on 2026-09-25.

### Graph build and maintenance

| Command | What it does | Needs | Writes |
|---|---|---|---|
| `mg fetch --dest DIR [--no-edam --no-nfcore --no-biocontainers --no-biotools --no-stato --no-obi]` | download graph sources and write `snapshot.json`. Does not fetch skills or pipelines. | net | `DIR/` |
| `mg build --db PATH [--edam --nfcore-modules --nfcore-pipelines --biocontainers --biotools --stato --obi --skills --staging --ingested-at --no-wiring]` | raw build from explicit source paths (`rebuild` wraps this). `--ingested-at` defaults to the date of the run. | source paths; `rdflib` for `--stato`/`--obi` | `PATH`, `PATH.staging/` |
| `mg rebuild [--db --snapshots --ingested-at --no-verify --check --diff-only]` | verify → build → audit gate → lock → coverage diff | snap | `--db` (default `data/methods.kuzu`) and `methods.lock.json` beside it. `--check` skips the lock write; `--diff-only` writes nothing. |
| `mg ingest --manifest M --dest W --db PATH [--staging --ingested-at]` | clone pinned pipelines, build with the pipeline layers, audit gate, write the lock | net, nf, snap | `W/pipelines/`, `W/ingest.lock.json`, `PATH` |
| `mg audit --db PATH [--snapshot DIR] [--json]` | 26 invariants plus provenance, id and coverage checks. With `--snapshot` it also reconciles sources; that currently exits 1 on a known Format count mismatch (612 vs 2,100). | DB | nothing |
| `mg export-kgx --db PATH --out DIR` | KGX `nodes.tsv` + `edges.tsv` | DB | `DIR/` |

### Graph queries

| Command | What it does | Needs |
|---|---|---|
| `mg query --keyword K [--keyword ...] [--hops N] [--db]` | keyword-seeded subgraph printed as RAG text | DB |
| `mg methods [--db]` | all 905 methods as AnalysisMethod-shaped JSON | DB |
| `mg suggest --have ID [--have ...] [--limit N] [--db]` | attestation-ranked next steps. Degenerate on the committed DB (0 `DOWNSTREAM_OF`). | DB |

### Guardrail

| Command | What it does | Needs |
|---|---|---|
| `mg guardrail (--method m:X \| --analysis KW \| --skill skill:Y) [--fact k=v ...] [--json] [--db]` | verdict for one step. `--analysis` takes the first fuzzy hit silently (`salmon` → `m:biohansel`). | DB |
| `mg guardrail-chain --step S [--step ...] [--fact k=v ...] [--json] [--db]` | a verdict per step plus the consecutive Data handoffs. Use `m:` ids, not keywords. | DB |
| `mg explain (--method m:X \| --skill skill:Y) [--json] [--db]` | assumption → via → evidence → source YAML | DB |
| `mg skills --coverage [--db]` | skill counts: skills / wired / evaluable / gaps. Errors without `--coverage`. | DB |

The hook has no subcommand. It runs as `.venv/bin/python -m methods_graph.hook`, reading a PreToolUse JSON payload on stdin. It is not wired into any settings file.

### Method-sequencing benchmark

| Command | What it does | Needs |
|---|---|---|
| `mg bench build [--pipelines DIR] [--out DIR] [--goals JSON] [--db \| --oracle-json]` | pipeline clones → frozen items. Defaults: `snapshots/pipelines` → `bench`. | clones with `dag.mmd`; DB optional (answer-leak filter) |
| `mg bench coverage [--items DIR] [--db \| --oracle-json]` | how much graph oracle backs the item set, plus the equivalence pairs | DB or oracle JSON |
| `mg bench run --model M --out F [--items DIR] [--limit N] [--task whole_pipeline\|next_step] [--db \| --oracle-json]` | run a contestant or baseline. `M` is one of `claude:<m>`, `openai:<m>`, `static:<path>`, `gold:`, `modal:`, `random:<seed>[:<k>]`. There is no `--workers` or `--resume` here. | DB or oracle JSON; **$** for `claude:`/`openai:` |
| `mg bench score --results F [--out F2] [--db \| --oracle-json]` | re-derive scores from retained raw output | DB or oracle JSON |

### Biolean

| Command | What it does | Needs |
|---|---|---|
| `mg biolean fetch [--out snapshots/go]` | GOA, then GO at the release the GAF names, then ECO, then `snapshot.json` | net |
| `mg biolean check DERIVATION.json [--store DIR] [--render] [--ledger DIR] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]` | elaborate + kernel check → verdict JSON, or prose with `--render`. With `--ledger`, over the base plus the admitted ledger facts | go |
| `mg biolean prove "SUBJECT QUALIFIER TERM" [--store] [--taxon] [--ledger DIR] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]` | mechanical shortest derivation; with `--ledger`, when every row matching the axiom step is a ledger row, the step carries a reference (DOI, else PMID, else GO_REF) from the row with the smallest annotation id | go |
| `mg biolean goals SUBJECT [--store] [--taxon] [--aspect F\|P\|C] [--ledger DIR] [--signers-sha256 HEX] [--no-cache] [--cache-dir DIR]` | derivable propositions for a subject | go |
| `mg biolean ledger init --ledger DIR --key KEY.pub [--store] [--principal NAME]` | create a ledger: `allowed_signers`, `base.json`, `ledger.json`, `ledger/`. Refuses non-ed25519 keys and the fixture keys | go |
| `mg biolean ledger append --ledger DIR --key KEY (--fact \| --derivation \| --computed) JSON\|@FILE [--store] [--no-cache] [--cache-dir]` | check, sign (`ssh-keygen -Y sign`), self-verify and append one entry. `--computed` is schema-checked, then refused | go; `ssh-keygen` |
| `mg biolean ledger verify --ledger DIR [--store] [--recheck] [--extends DIR\|heads.json] [--signers-sha256 HEX] [--no-cache] [--cache-dir]` | integrity; with `--store` also base binding (stale, superseded, contested); `--recheck` re-proves derived entries. Never reads the cache | go only with `--store` |
| `mg biolean ledger show --ledger DIR [--store] [--by KEY16] [--kind axiom\|derived\|computed] [--contested] [--stale] [--recheck] [--signers-sha256 HEX] [--no-cache] [--cache-dir]` | entries as JSON lines with status and the signer's fingerprint | go only with `--store` |
| `mg biolean bench build [--out biolean-bench] [--store] [--per-track 500] [--seed 0] [--since YYYY-MM-DD]` | store → frozen items, `manifest.json`, `modal.json` | go |
| `mg biolean bench coverage [--items biolean-bench]` | print the build manifest | items |
| `mg biolean bench run --model M --out F [--items] [--store] [--track prove\|hypothesize] [--limit] [--workers N] [--resume] [--db] [--oracle-json]` | run a model or baseline. `M` is `claude:<m>`, `openai:<m>`, `static:<path>`, `gold:`, `modal:`, `random:<seed>` (no `:<k>` here) or `template:`. `gold:`/`modal:`/`random:` need `--track prove`, and `template:` needs `--track hypothesize`, unless the item set holds only that track. | go; DB optional; **$** for `claude:`/`openai:` |
| `mg biolean bench score --results F [--store] [--out] [--db] [--oracle-json]` | re-derive scores from retained raw output | go; DB optional |

### Exit codes

| Commands | Codes | Source |
|---|---|---|
| `guardrail`, `guardrail-chain` | 0 EVALUABLE, 3 BLOCKED, 4 NOT_EVALUABLE, 5 FACTS_REQUIRED, 2 usage. The `--help` text still names only three verdicts. | `cli.py:1164-1165` |
| `explain` | 4 for an unknown method | `cli.py:883-902` |
| `audit`, `rebuild` | 1 on any failed check, snapshot drift or `--check` mismatch | `cli.py:712-880` |
| `biolean check`/`prove`/`goals` | 0 ACCEPTED or found, 3 REJECTED or no proof, 2 usage (missing store file, bad claim, ambiguous symbol). With `--ledger`, also 2 with `{"errors": [...]}` on stdout when the ledger or store cannot be loaded | `cli.py:1168-1188`, `1473-1528` |
| `biolean ledger *` | 0 ok or ACCEPTED, 3 REJECTED (the body is wrong and fixable), 2 usage (argparse, stderr) or integrity / base / signers / rollback / signing failure (`{"errors": [...]}` on stdout). Exit 2 never means the body is wrong | [biolean/ledger.md](biolean/ledger.md) §3 |
| `biolean bench *` | 2 on every refusal (release mismatch, wrong-track baseline, mixed model or manifest, `--resume` mismatch, `--workers` misuse). `BuildError` in build exits 1. | `cli.py:1327-1468` |
| `bench build`/`run` on a missing input directory | 1, with a traceback rather than a usage error | seq-bench survey |

---

## 8. Tests and CI gating

### Layout

`pytest --collect-only -q` → **1,014 tests in 71 files** (verified 2026-09-22).

| File prefix | Files | Tests | Covers |
|---|---|---|---|
| `tests/test_bench_*.py` | 8 | 183 | sequencing benchmark |
| `tests/test_biolean_bench_*.py` | 7 | 97 | Biolean benchmark |
| `tests/test_biolean_*.py` (excluding `bench_`) | 12 | 145 | Biolean kernel, parsers, store, elaborator, tactics, fetch, CLI |
| everything else | 44 | 589 | connectors (`test_edam`, `test_nfcore*`, `test_nextflow_dag`, `test_ontology`, `test_skills_connector`, …), crosslinks, build/load/resolve/audit/fetch/ingest/lock, guardrail/provider/rules/hook/explain/planner, workflow, `test_cli` |

- `tests/test_adapters.py` tests `extract/adapters.py`. The benchmark's adapter tests are in `tests/test_bench_adapters.py`.
- Fixtures: `tests/fixtures/` holds `bench/` (a 3-item `rnaseq.json`: 1 whole-pipeline and 2 next-step items; plus `oracle.json`), `biolean/` (`go-mini.obo`, `goa-mini.gaf`, `eco-mini.txt`, `golden_verdict.json`), `nfcore*/` (only `nfcore_nested/salmon/quant` and `nfcore_tool_id/bcftools/{sort,view}` use the nested `tool/subcommand` paths [CLAUDE.md](../CLAUDE.md#identifier-schemes--the-trap-that-has-cost-the-most) asks for; `nfcore/*` and `nfcore_pipeline/mini` are single-segment), `ontology/` mini OWL files, and EDAM/BioContainers/bio.tools samples. `tests/biolean_fixture.py` builds the mini store.

### Gated tests: these skip when their input is absent, so CI does not enforce them

| Gate | Tests | Where |
|---|---|---|
| `data/methods.kuzu` present | 30 | `test_cli_guardrail` 10, `test_provider` 7, `test_guardrail_precision` 4, `test_explain` 3, `test_rules` 3 (rules-vs-graph parity), `test_bench_normalize` 1 (alias table, `:103`), `test_bench_score` 1 (the 7 equivalence pairs, `:573`), `test_skills_connector` 1 |
| `snapshots/go/` present | 2 | `test_biolean_scale.py`, `test_biolean_bench_scale.py` |
| `quration` importable | 1 | `test_provider.py:174` |

| Environment | Result | Source |
|---|---|---|
| This checkout (DB + `snapshots/go` present, Python 3.14.6) | 1013 passed, 1 skipped (quration), in 89-133 s across runs | re-run 2026-09-22: `env -u OPENAI_API_KEY .venv/bin/python -m pytest -q -rs` |
| CI-like (a `git archive HEAD` export with no DB and no snapshots) | 981 passed, 33 skipped, in 53-76 s across runs | re-run 2026-09-22 with the commands below |

### What CI enforces and what it does not

- **Enforced (fact):** the `test` job in `.github/workflows/ci.yml:20-32` runs on every trigger (push to `main`, PRs, dispatch, and the weekly schedule). It uses Python 3.12 and installs exactly what `uv.lock` pins (`uv sync --locked --extra dev`, with uv itself and `setup-uv` pinned), then runs `python -m pytest -q`. That means the 981 ungated tests.
- **Enforced weekly only (fact):** `rebuild-verify` (`ci.yml:46-93`) runs `mg fetch`, then `rebuild --check` (informational, `continue-on-error`), then two rebuilds whose `graph_hash` must match. Apart from a fetch or build error, only a hash difference between the two rebuilds fails it, and the unstable hash (section 4a) can cause one without any real non-determinism in the build.
- **Not enforced (fact):**
  - The 33 gated tests above. That includes the gate-precision pin, the rules-vs-graph parity test, the 7-pair equivalence pin and both Biolean scale tests.
  - Anything on the 56 unpushed commits. CI has never run on the Biolean code.
  - Python 3.10 and 3.11, even though `requires-python >=3.10`.
  - An end-to-end `rebuild` test. `tests/test_cli_rebuild.py` has only two `--diff-only` tests.
  - A lock-schema step. The `ci.yml:12` comment claims one; none exists. Lock validity is a test (`tests/test_pipeline.py:120-127`) that returns silently if the CWD-relative lock path is missing.
  - Linting.
- **Rule (from CLAUDE.md):** the suite must pass with `OPENAI_API_KEY` unset. Check with `env -u OPENAI_API_KEY .venv/bin/python -m pytest -q`. `make test` does **not** unset it.

To reproduce the CI result locally without the DB or snapshots (verified 2026-09-22):

```bash
repo=$PWD; tmp=$(mktemp -d); git archive HEAD | tar -x -C "$tmp"
cd "$tmp" && env -u OPENAI_API_KEY PYTHONPATH="$tmp/src" "$repo/.venv/bin/python" -m pytest -q -rs; cd "$repo"
```

---

## 9. Makefile targets

`PY` auto-selects `.venv/bin/python` when it exists, and falls back to `python` otherwise (`Makefile:3`). CI does not call `make`; it runs `python -m pytest -q` directly. There are no bench or Biolean targets.

| Target | Runs | Notes |
|---|---|---|
| `make help` | lists the targets | |
| `make rebuild` | `mg rebuild` | [snap]. Overwrites `data/methods.kuzu` **and** `data/methods.lock.json`. |
| `make rebuild-check` | `mg rebuild --check` | [snap]. Overwrites `data/methods.kuzu`; leaves the lock. Use the scratch-path form in section 4a to keep the DB. |
| `make verify` | `mg rebuild --diff-only` | diffs the working-tree lock against git HEAD's lock. No rebuild. |
| `make explain ARGS='--method m:scanpy'` | `mg explain $(ARGS)` | [DB] |
| `make audit` | `mg audit --db data/methods.kuzu` | [DB]. Audits the DB **as it is on disk**. After changing connectors, crosslinks or the loader, rebuild first, or you audit the old graph. |
| `make test` | `$(PY) -m pytest -q` | does not unset `OPENAI_API_KEY`. Use `env -u OPENAI_API_KEY make test`. |

---

## 10. Dependencies and invariants

### Dependencies (`pyproject.toml`)

| Kind | Package | Used by |
|---|---|---|
| runtime | `kuzu==0.11.3` (pinned on purpose; do not float) | loader, extract, provider, planner, kgx, workflow validator, `bench/oracle.py`, `cli.py` (audit, rebuild, ingest, suggest) |
| runtime | `polars>=1.0` | `graph/loader.py` (Parquet staging) |
| runtime | `pyyaml>=6.0` | crosslinks, connectors, ingest, rules, audit, `fetch.py`, `bench/run.py` |
| runtime | `networkx>=3.0` | `extract/adapters.py` |
| extra `ontology` | `rdflib>=7` | `connectors/ontology.py`. **`rebuild` needs it**, because STATO and OBI are always loaded. |
| extra `schema` | `linkml>=1.7` | LinkML validation in tests |
| extra `dev` | `pytest>=8.0`, `linkml`, `rdflib` | CI installs `.[dev]` |

Biolean's own modules import nothing outside the stdlib (`json`, `gzip`, `hashlib`, `random`, `concurrent.futures`, …). The benchmark does pull in `pyyaml` indirectly: `biolean/bench/items.py:19` imports `methods_graph.fetch`, which imports `yaml` at module level (`fetch.py:43`). HTTP calls go through `urllib.request`. `git`, `nextflow` and `claude` run as subprocesses behind a `runner=` seam, except three local `git` reads that call `subprocess.run` directly (`pipeline.py:101`, `cli.py:749`, `bench/run.py:52`). `uv.lock` matches `pyproject.toml` (`uv lock --check --offline`, repo-state survey). The local venv is Python 3.14.6; CI uses 3.12.

### Invariants (the rules are in [CLAUDE.md](../CLAUDE.md#invariants); this table records where the code falls short)

| Invariant | Known exceptions in the code (facts) |
|---|---|
| **No new runtime dependencies.** Prefer stdlib. | none found |
| **`kuzu` pinned** at 0.11.3 | none. `pyproject.toml:10`. |
| **Determinism:** sorted iteration, seeded RNG, Cypher `ORDER BY`, JSON `sort_keys=True` | Cypher without `ORDER BY`: `extract/seed.py:48-79` and `provider/quration_provider.py:128-129`. Cypher *with* `ORDER BY` that Kuzu 0.11.3 does not always honour: the graph-hash edge query (`pipeline.py:24-28`; section 4a). JSON dumped without `sort_keys`: `cli.py:49` (`methods`), `:67` (`suggest`), `:1158` (`skills`), `:1576` (`guardrail --json`), `:1603` (`guardrail-chain --json`). |
| **Nothing dropped silently.** Each drop gets a counted field in the output. | `graph/loader.py:59-67` drops 45 dangling edges per rebuild; the count is printed (a log warning and the `Built graph: … (45 dangling dropped)` stdout line) but not recorded in the lock or the audit. `connectors/skills.py:66-68` skips 11 of 39 `SKILL.md` files with no count. Sequencing-benchmark gold drops processes from local (non-nf-core) modules with no counted field (`bench/gold.py:51-58`). |
| **Injectable seams for network and subprocess calls** (`runner=`, `http_get=`, `http_post=`); no test hits the network | followed in `fetch.py`, `cmd_ingest`, `bench/adapters.py`. The Nextflow preview call has no timeout (`fetch.py:446`). |
| **Run `mg audit` after touching connectors, crosslinks or the loader** | the audit reads the existing DB, so rebuild first (see section 9) |

The identifier-scheme rules (`m:` = `m:` + the lowercased name; `mod:` comes from `meta.yml` `name`, never the directory leaf; never normalize with `resolve_method_ids()`) are in [CLAUDE.md](../CLAUDE.md#identifier-schemes--the-trap-that-has-cost-the-most).

---

## 11. Where to change what

| Change | Touch | Then |
|---|---|---|
| add or fix a curated link | `crosslinks/*.yaml` | `make rebuild`, `make audit`, commit the new lock |
| add a graph source | `connectors/`, `fetch.py`, `cli.cmd_build`, `audit.py` | rebuild. For the source to be verified, `pipeline.verify_snapshots` must check its pin; as of 2026-09-22 it checks only EDAM, STATO, OBI and the nf-core commit. |
| add a contestant for either benchmark | `bench/adapters.py` | keep it `(prompt) -> str` behind an injectable seam; no network in tests |
| change a sequencing metric | `bench/score.py` only (`oracle.py` stays the only DB reader) | mutation-check the test, per [CLAUDE.md](../CLAUDE.md#testing-standards-this-repo-enforces) |
| change a proof rule or error | `biolean/kernel.py`, `errors.py`, the spec in `docs/superpowers/specs/2026-09-21-biolean-design.md` | design work goes spec → plan → execution ([CLAUDE.md](../CLAUDE.md#process)). The transitive-edge rule is an open decision: see [decisions/README.md](decisions/README.md). |
| add a CLI subcommand | `cli.py`: a `cmd_*` function plus its parser at `cli.py:1701+` | update section 7 of this doc |

See also: [README.md](README.md) (docs index), [HISTORY.md](HISTORY.md), [BACKLOG.md](BACKLOG.md), [GLOSSARY.md](GLOSSARY.md), [DATA_SOURCES.md](DATA_SOURCES.md).
