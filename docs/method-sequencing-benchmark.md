# Method-sequencing benchmark

**What this is:** the method-sequencing benchmark as built: what it measures, where gold comes from, the code, the one pilot run, and what blocks the next run.

**Status (2026-09-22):** code is complete through Plan 2 (merge `59d5111`, 2026-07-31). There are 0 items in git and one untracked 156-item pilot (2026-08-08). The pilot's only contestant (Sonnet, two runs) was not closed-book. Plan 3 (live cuts) is unwritten.

**Read next:** [BACKLOG.md](BACKLOG.md) for priorities, [methods-graph.md](methods-graph.md) for the graph the oracle reads, and [biolean/benchmark.md](biolean/benchmark.md) for the other benchmark.

> `mg` in this doc means `alias mg='.venv/bin/python -m methods_graph.cli'` (or
> `.venv/bin/methods-graph`). A bare `mg` on macOS runs `/usr/bin/mg`, an unrelated text
> editor. Run every command from the repo root.

## Summary

- **What it asks:** a model gets no methods-graph context and must name which tools a
  goal needs and in what order. Gold comes from nf-core's own Nextflow DAGs. The graph
  is only the scoring **oracle**, never a contestant.
- **What is built:** 10 files and 1,676 lines in `src/methods_graph/bench/`, plus 183
  tests in 8 files. `mg bench build|coverage|run|score` works end to end.
- **What is not built:** live cuts (Plan 3, spec §3b), a goals map, and any item set in
  git.
- **Only data:** `bench-runs/2026-08-08-pilot/` (untracked). It has 156 items from 10 of
  12 pipelines. The scores re-derive byte-identically with today's code. The items
  cannot be rebuilt offline, and the one contestant (Sonnet, two runs) was **not closed-book**.
- **Before quoting any number:** read the [five pilot caveats](#read-these-five-caveats-first).
  To restart the work, use the [to-resume checklist](#to-resume).

Top-level `opus.jsonl`, `modal.jsonl` and `opus.partial.jsonl` hold **Biolean**
prove-track results, not results from this benchmark. See
[biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md).

## What it measures

### Two task types

Source: `render.py:13-25`, `build.py:9-75`.

| Task | Prompt (verbatim template) | Answer | Items per pipeline |
|---|---|---|---|
| `whole_pipeline` | `Goal: {goal}` / `Return a JSON array of tool names, in execution order.` / `Return only the JSON array, with no commentary.` | ordered tool list | 1 |
| `next_step` | `Goal: {goal}` / `Completed so far: {given}` / `Return a JSON array of up to 3 candidate tool names for the NEXT step, best first.` / `Return only the JSON array, with no commentary.` | up to 3 ranked names | one per gold module step, minus the withheld ones (below) |

- `{given}` is rendered as method names (`fastqc, trimgalore`), never as `mod:` ids, so
  the prompt does not reveal which registry the answer key came from (`render.py:30-40`).
- The prompt includes no candidate list (`render.py:1-6`).
- `{goal}` comes from `--goals`. When no goal is given, the goal is the **bare pipeline
  name** (`run.py:173`). No goals file exists anywhere in the repo.
- Some next-step items are **withheld** because the prompt would print its own answer
  (for example, `star_genomegenerate` then `star_align` both project to `star`). The
  build drops these when it is given an oracle (`build.py:78-92`). In the pilot this
  withheld 104 of 250 positions (42%).

### Four axes, reported separately and never pooled

Source: `score.py`, `run.py:351-408`. An axis with nothing to score reports `null`,
never `0.0`. The exception is selection: an empty answer, including an unparsed reply,
scores `0.0` (`score.py:8-9`, `score.py:141-147`), and on next-step an unparsed reply
counts as a miss.

| Axis | Question | As built | Denominator |
|---|---|---|---|
| Selection | Right tools? | Step-set F1 (with precision and recall) after projecting gold to `m:` ids. Uses a maximum one-to-one matching (Kuhn's algorithm) with identity-first candidates, credited through equivalence classes (`score.py:87-152`) | gold and predicted method sets |
| Sequencing | Right order? | Fraction of **gold DAG edges** whose two endpoints were both matched and whose order the answer keeps. Never adjacent pairs of the sequence (`score.py:155-186`) | scorable edges only, so it depends on what each contestant matched |
| Validity | Would it run? | Checked **per step by reachability**. VALID means an earlier step outputs the step's input. BROKEN means only a later step *net*-produces it. UNKNOWN means neither. UNKNOWN never counts as valid (`score.py:189-254`) | VALID + BROKEN; `coverage` = classified / steps |
| Next-step | Right next tool? | Top-1 and top-3, with equivalence, bucketed by prefix length `0`, `1-2`, `3-5`, `6+`. The headline is the macro-mean over buckets other than `0`; the pooled figure is also reported (`score.py:257-322`) | scored next-step rows |

`summarize` accounts for every row: `n_rows == n_errors + whole_pipeline.n + next_step.n + n_gold_unresolved` (`run.py:351-362`).

### Owner decisions this rests on

These come from spec [2026-07-30](superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md), status "approved through §3, §4–§5 folded in". Spec line numbers in this doc are as of HEAD `6b28222`. The decision log records the scoring and gold decisions as F-13 to F-16, with status "fixed: merged" ([decisions/README.md](decisions/README.md)); the goal-derivation and live-cut decisions below are designed but not built.

- **Owner decision:** the baseline is models answering with no methods-graph in context.
  The graph is the oracle, not a contestant (spec lines 13-14). Selection and sequencing are reported as separate numbers (spec line 8).
- **Owner decision:** gold comes only from real Nextflow DAGs (`derivation:
  nextflow_dsl2`). The `io_inferred` fallback is rejected because it uses the same
  reasoning the benchmark scores (spec §1; enforced at `build.py:42-44`).
- **Owner decision:** dropped pipelines are counted with a reason (spec §1; enforced at
  `build.py:95-113`).
- **Owner decision:** goal text is "derived from the pipeline description" because
  "hand-writing goals leaks the expected answer into the prompt" (spec §2, line 77).
  **Not built.** The code accepts only an optional hand-written `--goals` map, and
  without one it falls back to the bare name.
- **Owner decision:** the main nf-core set is assumed contaminated. The designed
  contamination control is live cuts from new preprints (spec §3b). **Not built.**

## Where gold comes from

1. `mg ingest` clones each pipeline at a release tag. It then runs
   `nextflow run <clone> -profile test --outdir … -preview -with-dag dag.mmd`
   (`fetch.py:437-438`). The default v2 parser runs first and the legacy v1 parser is
   the fallback (`fetch.py:439-450`). The preview runs zero tasks and pulls no
   containers and no data (spec §1).
2. `parse_dag_process_edges` collapses channels to producer→consumer process edges.
3. Each process maps to `mod:<meta.yml name>` through the pipeline's `modules.json`
   (`run.py:29-41`, `nfcore_pipeline.py:77-96`). **Processes with no nf-core module
   mapping are dropped, and nothing counts them** (`gold.py:46-60`).
4. `break_cycles` runs, then a Kahn topological sort with every tie broken
   alphabetically gives the gold sequence (`gold.py:23-43`, `gold.py:63-76`). The
   bookkeeping modules `multiqc`, `versions`, `dumpsoftwareversions` and
   `custom_dumpsoftwareversions` are removed (`gold.py:13-15`).
5. The precedence edges are frozen next to the sequence as `gold.edges`
   (`gold.py:79-96`). Linearizing loses the DAG, so the edges are what sequencing scores.
6. A pipeline is dropped with a reason if it has no `dag.mmd`, if its metadata is
   unreadable, or if it has fewer than 2 **module** steps (`run.py:138-168`).
7. Each item records `source` (`nf-core/<pipeline>@<tag>`, or the clone's commit when no
   lock records a tag, `run.py:134-137`), `nxf_ver`, `dag_sha256` and `derivation`
   (`build.py:48-53`).

Gold therefore reflects **the `-profile test` configuration's DAG**, not every branch
the pipeline has. Whether that is intended is an open question (see [below](#open-questions)).

## The graph as oracle

- `oracle.py` is the only file that opens the database. It opens `data/methods.kuzu`
  with `read_only=True` (`oracle.py:96`). The scorer sees an `Oracle` protocol of 7
  queries (`oracle.py:18-27`). Tests use `StaticOracle`, and `--oracle-json` loads one
  from JSON (`oracle.py:178-196`).
- **Moving from `mod:` to `m:`:** `Module -WRAPS-> Method` covers 1,921 of 2,038
  modules (94%). 45 modules wrap more than one method; `method_for_module` returns the
  lexicographically first and `multi_wrapped()` lists the rest (`oracle.py:66-72`).
  Measured with `KuzuOracle`, 2026-09-22.
- **Coverage of the 905 methods** (measured with `KuzuOracle`, 2026-09-22):

  | Carries | Methods | Share |
  |---|---|---|
  | a `PERFORMS` edge to an EDAM Operation | 415 / 905 | 46% |
  | input `Data` | 49 / 905 | 5.4% |
  | output `Data` | 39 / 905 | 4.3% |

- **Equivalence** is identity, or a shared *non-bridging* EDAM operation together with
  a shared input Data type (`score.py:47-67`). Two operations are denylisted as
  bridging: `op:operation_0236` joined fastqc↔salmon and `op:operation_2495` joined
  affy↔gsea (`score.py:29-37`). On the real graph that leaves exactly 7 non-identity
  pairs (`mg bench coverage`, 2026-09-22):
  `bwa–bwamem2`, `bwa–strobealign`, `deseq2–limma`, `fastp–fastqc`, `hisat2–star`,
  `kraken2–metabuli`, `rsem–salmon`. The test pinning them
  (`tests/test_bench_score.py:573`) is **DB-gated, so it skips in CI**.
- **Normalizing a model's answer** is an exact lookup of `m:<lowercased name>` plus
  punctuation variants and a 10-entry alias table (`normalize.py:26-65`). It never uses
  the fuzzy `resolve_method_ids()`. Names that don't resolve are returned and counted,
  never dropped (`normalize.py:68-86`).

## Code map

`src/methods_graph/bench/`, 10 files, 1,676 lines (`wc -l`, 2026-09-22).

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 0 | package marker |
| `gold.py` | 96 | DAG text → ordered `mod:` sequence plus precedence edges |
| `build.py` | 124 | sequence → frozen items; enforces `nextflow_dsl2`; withholds leaking next-step items; builds the manifest |
| `oracle.py` | 196 | the only DB-aware file: `Oracle` protocol, `StaticOracle`, `KuzuOracle`, `coverage()`, `load_oracle()` |
| `normalize.py` | 138 | free text and `mod:` ids → `m:` space; `project_sequence`, `project_edges` (counts dropped cyclic edges) |
| `score.py` | 322 | equivalence, matching, the four axes, bucketing |
| `render.py` | 106 | item → prompt; reply → `list[str]` or `None` (unparseable) |
| `adapters.py` | 158 | contestants `claude:`, `openai:`, `static:`; a contestant is just `(prompt: str) -> str` |
| `baselines.py` | 128 | `gold:` (ceiling), `modal:`, `random:<seed>[:<k>]` (floor) |
| `run.py` | 408 | build from clones, `load_items`, `score_item`, `run_items`, `rescore`, `summarize` |

The CLI dispatch is `cmd_bench` at `cli.py:1607` and the parser is at `cli.py:1900-1936`.
Plan 1 (gold build) was merged in `529ffc5` and Plan 2 (scorer, adapters, runner) in
`59d5111`, both on 2026-07-31. Since the last push (`86ce425`, 2026-08-01) the only
change to this benchmark's code is in `adapters.py` (`git diff --stat 86ce425 HEAD -- src/methods_graph/bench/`).
It is the closed-book fix: `fcac341` (in merge `b0f80c4`) and `128a8c6` (merge
`894072d`), both on 2026-09-22 and **both unpushed**. `origin/main` still carries the
adapter that is not closed-book.

### Contestant adapters

| Spec | What runs | Needs | Cost |
|---|---|---|---|
| `claude:<model>` (default `claude-opus-5`) | `claude -p <prompt> --model <m> --tools "" --safe-mode --strict-mcp-config` in an empty temp dir (`adapters.py:55-88`) | logged-in `claude` CLI, network | paid (plan usage) |
| `openai:<model>` (default `gpt-4o`) | chat completions at temperature 0 over `urllib` (`adapters.py:103-131`) | `OPENAI_API_KEY`, network | paid |
| `static:<path>` | replays canned replies | a JSON file | free |
| `gold:` / `modal:` / `random:<seed>[:<k>]` | baselines built from the item set (`baselines.py`) | items + oracle | free |

The `claude:` adapter sets no temperature. The method benchmark has **no `--workers` and
no `--resume`**; those exist only on `mg biolean bench run`. Rows stream to disk one at
a time, so an interrupted run keeps what it wrote, but there is no command to resume
or merge.

## CLI

| Command | Needs | Cost |
|---|---|---|
| `mg bench coverage --items bench-runs/2026-08-08-pilot/items --db data/methods.kuzu` | DB, pilot dir | free |
| `mg bench score --results bench-runs/2026-08-08-pilot/results/r12-sonnet-merged.jsonl --db data/methods.kuzu --out /tmp/rescored.jsonl` | DB, pilot dir | free |
| `mg bench run --items bench-runs/2026-08-08-pilot/items --db data/methods.kuzu --model gold: --out /tmp/gold.jsonl` (also `modal:`, `random:42`) | DB, pilot dir | free |
| `mg bench run --items <items> --db data/methods.kuzu --model claude:<full-model-id> --out <results.jsonl> [--task whole_pipeline\|next_step] [--limit N]` | DB, network, `claude` CLI | **paid** |
| `mg ingest --manifest <bench>.ingest.yaml --dest <workdir> --db <workdir>/scale.kuzu` | network, Nextflow + Java, `snapshots/` | free, but slow, and it can hang: there is no preview timeout (the pilot's sarek preview hung for about 55 minutes) |
| `mg bench build --pipelines <workdir>/pipelines --out <outdir> --db data/methods.kuzu --goals goals.json` | clones that contain `dag.mmd` | free |
| `env -u OPENAI_API_KEY .venv/bin/python -m pytest -q tests/test_bench_*.py` | nothing; 2 tests need the DB | free |

- The defaults point at paths that do not exist: `--items bench/items`,
  `--pipelines snapshots/pipelines`, `--out bench` (`cli.py:1904-1921`). Pass explicit
  paths.
- `bench build` reads provenance from `<pipelines>/../ingest.lock.json` and
  `<pipelines>/../snapshot.json` (`run.py:75-97`). Without an oracle (`--db` or
  `--oracle-json`) it does not withhold leaking next-step items, and it records the skip
  count as `null`.
- A missing `--pipelines` or `--items` directory exits 1 with a Python traceback, not a
  usage error (checked 2026-09-22).
- `bench score` prints the summary. It writes rescored rows only when `--out` is given.

## Tests and CI

| Fact | Evidence |
|---|---|
| 183 tests in 8 files `tests/test_bench_*.py`; about 1 s | `pytest -q tests/test_bench_*.py` → `183 passed` (2026-09-22, DB present) |
| 2 of the 183 are DB-gated and **skip in CI** (CI has no `data/methods.kuzu`): the equivalence-set pin and the alias-table check | `tests/test_bench_score.py:573`, `tests/test_bench_normalize.py:103` |
| The CI ceiling gate (`gold:` scores 1.0 on selection, sequencing and validity) runs on **1 hand-written whole-pipeline item**, not on real items | `tests/test_bench_score.py:413-426`; `tests/fixtures/bench/rnaseq.json` has 3 items, 1 of them whole-pipeline |
| On the real pilot items, `gold:` scores **0.505** on validity | see caveat 4 |

Whole-suite numbers are in [STATUS.md](STATUS.md).

## State of items

| Where | State (2026-09-22) |
|---|---|
| git | **No items tracked.** `git ls-files snapshots` → 0 |
| `snapshots/pipelines/` | **Does not exist** (it is not merely empty). `snapshots/` is gitignored (`.gitignore:11`) |
| `bench/` (default `--out`) | Gitignored (`.gitignore:16`) and absent. The ignore comment says items are "committed separately once frozen". No such commit exists |
| `bench-runs/2026-08-08-pilot/` | **Untracked and not ignored**, 1.5 MB. Holds `README.md`, `scale.ingest.yaml`, `ingest.lock.json`, 12 `dags/*.dag.mmd`, `gold/manifest.json`, 10 `items/*.json` (156 items) and 6 `results/*.jsonl`. Nothing in git or the docs says why it is untracked |
| Rebuilding the pilot items offline | **Not possible.** The clones lived in another session's scratchpad, which has since been deleted (`ingest.lock.json` `pipelines[].path`). The lock does record `repo` and `commit` per pipeline, so a networked re-clone could re-derive them. A different Nextflow version may produce a different DAG. The retained DAGs' sha256 values match the items' `dag_sha256` |
| Re-scoring the pilot | **Byte-identical.** On 2026-09-22 `mg bench score --out` on all 6 results files gave `cmp`-identical output, and re-running `mg bench run` with `gold:`, `modal:` and `random:42` on the pilot items reproduced `r12-{gold,modal,random42}.jsonl` byte for byte |

## The 2026-08-08 pilot

Twelve nf-core pipelines were previewed with brew Nextflow 26.04.3 and **no `NXF_VER`
pin**. Ten were used. ampliseq@2.18.0 and scrnaseq@4.1.0 were dropped with the reason
"gold sequence too short (0 steps)". That gave 156 items: 10 `whole_pipeline` and 146
`next_step`, of which 145 were scored (1 gold module, `mod:METAMDBG_ASM` in mag, maps to
no method). Source: `bench-runs/2026-08-08-pilot/gold/manifest.json` and `bench coverage`.

### Read these five caveats first

1. **Sonnet was not closed-book.** The adapter at pilot time (`d7c8036`) ran
   `claude -p <prompt> --model sonnet` in the caller's working directory with default
   tools, `CLAUDE.md` and MCP servers. Its replies show the leakage. For
   `mag/next/000` it answered `["Bash", "Agent", "Read"]`, and for `mag/next/001`
   `["Grep", "Bash", "Read"]`. For `mag/whole/001` it asked whether "mag" meant
   `methods_graph`/`mg`, "the CLI in this repo" (`results/r12-sonnet2.jsonl`). The
   closed-book fix landed on 2026-09-22 (`fcac341`, `128a8c6`). The rows record only
   the alias `claude:sonnet`, not a resolved model version. The pilot README's
   "temperature 0" is wrong: the `claude:` adapter sets no temperature.
2. **Prompts were bare pipeline names.** No goals map existed, so every prompt was
   `Goal: <pipeline>` (all items have `goal == pipeline`). Selection partly measures
   whether the model recognizes an nf-core pipeline's name.
3. **"Modal" is not a mode.** All 10 gold sequences are distinct, so every count is 1.
   The tie-break (`baselines.py:62`, lexicographic minimum) makes `modal:` answer
   **viralrecon's gold** for every item. It scores F1 1.0 on viralrecon. Over the other
   9 items its mean F1 is 0.203; Sonnet's over the same 9 is 0.344 (computed from the
   `r12-*.jsonl` whole-pipeline rows).
4. **Validity fails its own ceiling.** Feeding nf-core's own gold back gives validity
   **0.505** over 8 scored items, with coverage 0.128. The false BROKEN verdicts come
   from method-level I/O unions. `m:samtools` is curated as outputting reads
   (`data_1234`), so trimgalore, fastqc or fastp placed before samtools counts as
   BROKEN (atacseq, chipseq, methylseq, taxprofiler, viralrecon). They also come from
   first-occurrence projection: in rnaseq, samtools's first occurrence (the faidx
   branch) comes before star, which produces `data_0863`. Until this is fixed or
   decided, a validity score on real items cannot be read as answer quality, because
   gold itself scores 0.505.
5. **Gold loses steps and counts plumbing.** Processes that don't map to an nf-core
   module are dropped with no counter. nanoseq@3.1.0's DAG has MINIMAP2_ALIGN,
   NANOPLOT, FASTQC and QCAT, yet its whole-pipeline gold is just `[m:samtools]`
   (5 samtools modules projected). The per-process cause can't be checked because the
   clone is deleted. Separately, **20 of 145** gold method steps, and 20 of 146
   next-step answers, are `cat`/`gunzip`/`untar`/`custom` plumbing.

Smaller caveats:

- Sequencing only scores each contestant's own matched steps. Sonnet's 0.583 covers
  6 items; modal's 0.881 covers 8.
- "Top-1" in the pilot README is the macro-mean headline. Pooled top-1 is lower
  (Sonnet 0.097).
- Sonnet run 1 failed on a contiguous block of 97 of 156 rows (indices 59-155), all
  `claude CLI exited 1:` with empty stderr. Run 2 had 0 errors. `r12-sonnet-merged.jsonl`
  is byte-identical to `r12-sonnet2.jsonl`. No merge tool exists in the repo.
- 50 module-level gold edges were discarded as cyclic after projection into method
  space (`n_cyclic_edges_dropped`, summed over the 10 whole-pipeline items). 175
  method-level edges remain, summed per item (154 distinct across the 10 items).
- nanoseq passes the "≥ 2 module steps" rule but projects to 1 method, so its ordering
  cannot be tested.
- **Open:** whether the Sonnet numbers should be discarded. Until that is decided, quote
  them only with caveats 1-5.

### Results, re-scored 2026-09-22 with current code and `data/methods.kuzu`

10 whole-pipeline items and 146 next-step items (145 scored). Command: `mg bench score --results bench-runs/2026-08-08-pilot/results/r12-<run>.jsonl --db data/methods.kuzu`.

| Run | Selection F1 (P / R) | Sequencing (items scored) | Validity (items scored, coverage) | Next-step top-1 headline / pooled | Top-3 headline | First-step top-1 (n=10) | Errors | Unparsed |
|---|---|---|---|---|---|---|---|---|
| `gold:` | 1.000 (1.000 / 1.000) | 1.000 (9) | **0.505** (8, 0.128) | 1.000 / 1.000 | 1.000 | 1.000 | 0 | 0 |
| `modal:` (= viralrecon's gold) | 0.283 (0.248 / 0.469) | 0.881 (8) | 0.500 (10, 0.080) | 0.003 / 0.014 | 0.049 | 0.100 | 0 | 0 |
| `random:42` | 0.000 (0.000 / 0.000) | null (0) | null (0, 0.000) | 0.000 / 0.000 | 0.000 | 0.000 | 0 | 0 |
| `claude:sonnet` run 1 | 0.366 (0.442 / 0.333), n=4 | 1.000 (2) | 0.000 (2, 0.122) | 0.157 / 0.148, n=54 | 0.303 | 0.000 (n=5) | 97 | 3 |
| `claude:sonnet` merged (= run 2) | 0.368 (0.488 / 0.400) | 0.583 (6) | 0.333 (6, 0.139) | 0.120 / 0.097 | 0.239 | 0.000 | 0 | 1 |

### Per pipeline (gold and Sonnet merged, whole-pipeline item)

| Pipeline@tag | Gold module steps | Gold method steps | Gold module edges | Items | Next-step withheld | Sonnet F1 | Sonnet sequencing (edges scored) | Sonnet validity (coverage) |
|---|---|---|---|---|---|---|---|---|
| atacseq@2.1.2 | 23 | 12 | 43 | 13 | 11 | 0.636 | 1.0 (8) | 0.0 (0.20) |
| chipseq@2.1.0 | 22 | 12 | 36 | 13 | 10 | 0.480 | 0.75 (4) | 0.0 (0.15) |
| differentialabundance@1.5.0 | 10 | 6 | 10 | 7 | 4 | 0.400 | 1.0 (1) | 1.0 (0.25) |
| mag@5.4.2 | 24 | 19 (+1 unresolved) | 38 | 21 | 4 | 0.0 (unparsed reply) | null | null |
| methylseq@4.2.0 | 11 | 6 | 15 | 7 | 5 | 0.500 | null (0) | null (0.0) |
| nanoseq@3.1.0 | 5 | 1 (`m:samtools` only) | 7 | 2 | 4 | 0.167 | null (0) | 0.0 (0.09) |
| rnaseq@3.26.0 | 40 | 23 | 93 | 24 | 17 | 0.286 | 0.0 (1) | 1.0 (0.40) |
| sarek@3.8.1 | 25 | 13 | 40 | 14 | 12 | 0.118 | null (0) | null (0.0) |
| taxprofiler@2.0.1 | 47 | 28 | 52 | 29 | 19 | 0.512 | 0.0 (1) | null (0.0) |
| viralrecon@3.0.0 | 43 | 25 | 62 | 26 | 18 | 0.579 | 0.75 (4) | 0.0 (0.15) |
| ampliseq@2.18.0 | dropped: 0-step gold | | | 0 | | | | |
| scrnaseq@4.1.0 | dropped: 0-step gold | | | 0 | | | | |
| **Total** | **250** | **145** | **396** | **156** | **104** | | | |

Sources: `items/*.json`, `gold/manifest.json`, `results/r12-{gold,sonnet-merged}.jsonl`
under `bench-runs/2026-08-08-pilot/`. Method steps come from `project_sequence` with
`KuzuOracle`. Oracle coverage of the pilot (`mg bench coverage`): 175 distinct gold
modules, 174 resolved. They cover 93 methods: 74 with operations, 18 with input Data,
18 with output Data. One module wraps more than one method (`mod:megahit` → megahit,
pigz).

## Blockers to building items at scale

The target is about 142 active nf-core pipelines (spec §3b, counted 2026-07-30, not
re-checked).

| Blocker | Evidence | Kind |
|---|---|---|
| **Network** is needed to clone pipelines and for any Nextflow self-download | `ingest` / `fetch_nfcore_pipeline` | environment |
| **Nextflow and Java.** Present on this Mac: brew Nextflow 26.04.3 and OpenJDK 26.0.1. `/usr/bin/java` is the macOS stub; the `nextflow` wrapper sets `JAVA_HOME` itself | `/opt/homebrew/bin/nextflow` line 2; checked 2026-09-22 | environment (met locally) |
| **The preview has no timeout.** sarek hung for about 55 minutes in the pilot until it was killed | `fetch.py:446` `runner(cmd, check=True, cwd=…, env=…)`; no `timeout` anywhere in `fetch.py`; pilot README infra issue 1 | code fix |
| **`NXF_VER` policy is undecided.** The pilot items record `nxf_ver: "unknown"`, which falls short of spec §1 provenance. `CLAUDE.md:109` and `README.md:184` (at HEAD `6b28222`) say to pin per release. A note from the 2026-06-16 differentialabundance ingest, kept outside the repo and not re-verified, says pinning `23.10.0` breaks Nextflow 26.04.3's launcher on this Mac and silently degrades the DAG to `io_inferred`. Yet `ingest.example.yaml:29` pins exactly that. The pilot README suggests "latest release at cut date" | items; `ingest.lock.json` `nxf_ver: null` | **open decision** |
| **No goals.** The spec decided goals are derived from the pipeline description; that derivation was never built, and the code accepts only a hand-written `--goals` map, which the spec's rationale argues against | `find . -name 'goals*.json'` → none; `run.py:173`; spec line 77 | work, or revisit the decision |
| 2 of 12 pilot pipelines produced 0-step gold. Their DAGs are not empty: ampliseq parses to 166 process edges and scrnaseq to 7 (including STAR_GENOMEGENERATE→STAR_ALIGN), so the loss is in process→module mapping. The pilot README's "empty DAGs" is wrong. Cause unverified (clones deleted) | `parse_dag_process_edges` on `dags/*.mmd` | investigation |
| Unmapped processes are not counted in the manifest | `gold.py:46-60`; `run.py:170-183` records no such field | code fix |
| `bench build` uses any `dag.mmd` on disk and ignores the ingest lock: sarek's lock says `dag: null`, yet 14 sarek items were built | `run.py:138-139`; `ingest.lock.json` | minor code fix |
| The pilot's `mg ingest` audit failed: 25 of 26 invariants passed and 1 failed. The lock does not name the failing invariant | `ingest.lock.json` `audit` | investigation |
| There is no ingest manifest for the scale-up. `catalog.ingest.yaml` lists 96 release-pinned pipelines but sets `wiring: false` (no DAGs). The pilot's `scale.ingest.yaml` is the template, but its `snapshot_dir` is an absolute local path | `catalog.ingest.yaml:12`; `grep -c '^  - {name:'` → 96 | work |

## Four defects parked at the `59d5111` merge

These are listed under "Known open items" in the `59d5111` commit message
(`git log -1 --format=%B 59d5111`). All four are still open at HEAD `6b28222`.

| # | Defect | Where (HEAD) | Consequence | Fix | Mutation check to require |
|---|---|---|---|---|---|
| 1 | The modal-baseline test does not pin the modal property | `tests/test_bench_score.py:447-464` (`_SEQ_A` is both the 2-of-3 majority and the lexicographic minimum) | A mutant that drops the count filter still passes | Make `_SEQ_B` the majority while it stays lexicographically larger (the commit message calls this a two-line fixture change) | Change `baselines.py:62` to `min(counts)`; the test must fail |
| 2 | `score_item` runs outside `run_items`' per-item guard | `run.py:313-320` (only `adapter(prompt)` sits inside `try … except AdapterError`) | A scoring exception aborts the run. Earlier rows survive on disk because rows stream | Guard `score_item` and emit a counted failure row | Inject an oracle that raises during scoring; the run must finish and count that row as an error |
| 3 | `summarize` omits `n_broken`, "the one number saying whether the validity axis fired" | `run.py:381-401` (per-item `n_broken` exists at `score.py:248`) | A reader can't tell a clean validity score from a vacuous one | Add a summed `validity_n_broken` | Hard-code it to 0; a test must fail |
| 4 | The fixture still contains `rnaseq/next/003`, the answer-leak shape that `bench build` now refuses to emit | `tests/fixtures/bench/rnaseq.json:32-39` | Tests exercise an item shape that real builds never produce | Remove or replace it. `tests/test_bench_run.py:436-460` depends on 3 fixture items in sorted order and must be updated with it | Re-run `tests/test_bench_*.py` |

## Not done, not enforced

- **Live cuts (Plan 3) are unwritten.** No code under `src/methods_graph/bench/`
  implements cohorts, `first_seen` or `bench/cuts/`. Nothing controls contamination.
  Only Biolean has a live cut (`src/methods_graph/biolean/bench/items.py`, `apply_since`).
- **No goals.** Every prompt built so far is a bare pipeline name.
- **No item set is committed or reproducible offline.**
- **No closed-book contestant run exists.** The only model runs (Sonnet, two) predate the fix.
- **CI does not enforce** the 7-pair equivalence set or the alias table (both DB-gated),
  and its ceiling gate never sees real items.
- **Validity is not ceiling-clean** on real items (gold 0.505).
- **Gold drops unmapped processes without counting them.** This breaks the repo's
  "nothing dropped silently" invariant.
- **The Biolean work is unpushed**, and that includes this benchmark's closed-book
  adapter. `origin/main` (`86ce425`) still runs `claude -p` in the caller's cwd.

## Open questions

All of these are **open**. None has an owner decision. Record decisions in
[decisions/README.md](decisions/README.md).

1. Discard the pilot's Sonnet numbers and re-run closed-book before quoting anything?
2. Goals: how do we derive them from the pipeline description (the spec's decision)
   without naming tools? Or should that decision be revised to allow the hand-written
   `--goals` map the code accepts? If so, what rule keeps a goal from leaking its
   answer?
3. Validity: fix the curation (`m:samtools` output reads) and first-occurrence
   projection, report it only with `n_broken` on gold, or drop the axis until
   curation improves?
4. Gold's unmapped processes: add a counted `n_unmapped_processes` per pipeline and a
   minimum mapped fraction below which a pipeline is dropped?
5. Plumbing (`cat`, `gunzip`, `untar`, `custom`, perhaps `fq`/`ucsc`/`tabix`): strip it
   like `BOOKKEEPING`? It is 14% of pilot gold method steps (20 / 145).
6. Is the `-profile test` DAG the right definition of "the pipeline"? For example,
   taxprofiler's test-profile gold runs 14 profilers side by side, bracken to sylph
   (`items/taxprofiler.json`).
7. `NXF_VER`: pin per release, pin "latest at cut date", or leave unpinned?
8. Is `fastp ↔ fastqc` a fair equivalence? fastp trims as well as running QC. It is in
   the pinned 7-pair set.
9. `bench-runs/2026-08-08-pilot/`: commit it as a frozen record, gitignore it, or delete
   it? Where should frozen item sets live, given that `/bench/` is ignored?
10. Should contestant rows record a resolved model id, not an alias like `sonnet`?
11. Should `bench build` cross-check the ingest lock's `dag` field, and should missing
    inputs give a usage error instead of a traceback?

## To resume

In order. Each code step follows the repo's mutation discipline (see
[CLAUDE.md](../CLAUDE.md#testing-standards-this-repo-enforces)).

1. **Decide** open questions 1, 2, 3, 7 and 9 above. Each one changes what gets built.
2. **Fix the four parked defects** (no network, free). Use the table above.
3. **Add a timeout to the Nextflow preview** (`fetch.py:446`). Pass it through the
   existing `runner` seam and test it without spawning a process.
4. **Count unmapped processes** per pipeline in `gold/manifest.json`. Optionally
   cross-check the lock's `dag` field.
5. **Apply the validity decision.** Then re-run the ceiling on the pilot items and
   record the new value:
   `mg bench run --items bench-runs/2026-08-08-pilot/items --db data/methods.kuzu --model gold: --out /tmp/gold.jsonl`
   (DB, free).
6. **Produce goals** as decided in step 1: derived from each pipeline's description
   (spec line 77), or a reviewed `goals.json` (`{pipeline: goal}`) if that decision is
   revised. Goals only take effect when items are rebuilt, and rebuilding needs the
   clones (step 8).
7. **Closed-book re-run on the pilot items** (DB, network, **paid**). Pass a full model
   id, not an alias:
   `mg bench run --items bench-runs/2026-08-08-pilot/items --db data/methods.kuzu --model claude:<full-model-id> --out bench-runs/<date>-<model>.jsonl`.
   There is no `--resume`; split the run with `--task` or `--limit` if usage windows are
   a risk.
8. **Scale-up** (network, Nextflow + Java, hours). Write a bench ingest manifest (wiring
   on, release-pinned, `NXF_VER` per the decision), then run
   `mg ingest --manifest <m>.yaml --dest <workdir> --db <workdir>/scale.kuzu`, then
   `mg bench build --pipelines <workdir>/pipelines --out <outdir> --db data/methods.kuzu --goals goals.json`,
   then `mg bench coverage --items <outdir>/items` **before any score**, then the
   `gold:`, `modal:` and `random:<seed>` baselines, then contestants.
9. **Write Plan 3 (live cuts)** through the repo's process: brainstorming → spec update →
   `superpowers:writing-plans`.

## Where the build departs from the spec

The code differs from these spec lines. When describing behaviour, go by the code. The
scoring rows were deliberate changes made during Plan 2: sequencing over DAG edges in
`3bc6c5a`, validity by reachability in `67a65de` (explained in the `59d5111` message). The
goal row is different: it is an owner decision that was never built, not a deliberate change.

| Spec (2026-07-30) says | As built |
|---|---|
| Gold example `[m:fastqc, m:trimgalore, …]` (line 66) | Gold is `mod:` ids, projected to `m:` through WRAPS |
| Goal "derived from the pipeline description" (line 77) | Optional `--goals` JSON; the default is the bare name (`run.py:173`) |
| Prompt has an `Input: <data type>` line (line 84) | No Input line (`render.py:13-17`) |
| Next-step asks for "the single next tool" (line 88) | Up to 3 ranked candidates (`render.py:19-25`) |
| Sequencing = gold adjacent pairs preserved (line 96) | Gold DAG edges (`score.py:155-186`) |
| Validity = consecutive pairs via `classify_handoff` (lines 97, 106) | Per-step reachability; `classify_handoff` is not called (`score.py:189-254`) |
| Ceiling scores 1.0 on all metrics, in CI (lines 124, 202) | True only on the fixture; real-item validity is 0.505 |
| `bench/items/` "generated, committed" (line 185) | `/bench/` is gitignored; nothing is committed |

## Sources

- Spec: [superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md](superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md)
- Plans: [Plan 1, gold build](superpowers/plans/2026-07-30-benchmark-gold-build.md) and
  [Plan 2, scorer and runner](superpowers/plans/2026-07-31-benchmark-scorer-and-runner.md)
  (merged; checkboxes never ticked)
- Commits: `529ffc5`, `59d5111` (message lists the parked items), `d7c8036` (the
  adapter at pilot time), `fcac341`, `128a8c6`
- Pilot (untracked): `bench-runs/2026-08-08-pilot/README.md`
- Related: [STATUS.md](STATUS.md), [ARCHITECTURE.md](ARCHITECTURE.md),
  [HISTORY.md](HISTORY.md), [GLOSSARY.md](GLOSSARY.md), [README.md](README.md)
