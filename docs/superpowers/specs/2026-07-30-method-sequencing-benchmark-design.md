# Method Selection & Sequencing Benchmark — design

**Date:** 2026-07-30
**Status:** approved through §3, §4–§5 folded in

## Purpose

Measure LLMs on two questions, reported as two separate numbers:

1. **Selection** — does the model know which method to use?
2. **Sequencing** — can it order those methods the standard way?

Baseline first: models answer with **no methods-graph in context**. The graph is the
*scoring oracle*, not a contestant.

## Non-goals

- Not an admissibility benchmark (is this method valid for this design?). That is a later
  track; the `UNDERSPECIFIED` class design is retained but out of scope here.
- Not a capability benchmark for executing analyses (BixBench, StatABench cover that).
- No fine-tuning, no leaderboard hosting, no held-out submission server in v1.

## §1 — Gold standard

Source: **nf-core pipeline DAGs**, machine-generated.

```
nextflow run <pipeline> -preview -with-dag dag.mmd   # zero tasks, no containers, no data
  -> parse_dag_process_edges()                       # channels collapsed to producer->consumer
  -> break_cycles()                                  # alias-quotient cycles resolved by rank
  -> topological order = gold sequence
```

Existing code: `fetch.py:417` generates, `connectors/nextflow_dag.py` parses,
`connectors/nfcore_pipeline.py` maps processes to module ids.

**Why this is gold:** not an opinion and not documentation. It is the released pipeline's own
channel wiring, from a peer-reviewed community-maintained project.

### Hard constraints

1. **`derivation: nextflow_dsl2` required.** `nfcore_pipeline.py:119` falls back to
   `io_inferred` — guessing order from typed I/O overlap — when `dag.mmd` is absent.
   That is the same reasoning the benchmark scores, so accepting it would make the answer
   key an artifact of the method under test. Rejected, not downweighted.
2. **Dropped pipelines are counted, with reasons,** in `bench/gold/manifest.json`. Preview
   fails on some releases (Nextflow version pinning). Today `fetch.py:448` only emits a
   `_log.warning` — a build task is to record failures structurally. A benchmark that
   silently drops what it could not parse misreports the population it covers.

### Provenance per item

`pipeline@release`, `NXF_VER`, `dag_sha256` — any disputed item can be re-derived.

## §2 — Items

One gold DAG yields both task types: whole-pipeline is the full sequence; next-step is N
slices of it.

```yaml
id: rnaseq/whole/001
task: whole_pipeline          # or: next_step
goal: "Bulk RNA-seq differential expression from paired-end human FASTQ"
given: []                     # next_step: completed steps
gold:
  sequence: [m:fastqc, m:trimgalore, m:star, m:salmon, m:deseq2]
  source: nf-core/rnaseq@3.14.0
  nxf_ver: "23.04.0"
  dag_sha256: 9f2c...
  derivation: nextflow_dsl2
```

| Decision | Choice | Rationale |
|---|---|---|
| Output format | free-text tool names, normalized to `m:` ids | closed multiple-choice leaks the answer set |
| Accumulator steps | strip `multiqc` / `versions` | bookkeeping, not method choice; DAG parser already excludes them |
| Goal text | derived from the pipeline description | hand-writing goals leaks the expected answer into the prompt |

### Prompts

Identical across models. No methods-graph context.

```
whole_pipeline:  Goal: <goal>. Input: <data type>.
                 Return a JSON array of tool names, in execution order.

next_step:       Goal: <goal>. Completed: [<given>].
                 Return the single next tool as JSON.
```

## §3 — Scoring

| Metric | Answers | Definition |
|---|---|---|
| **Selection** | which method? | step-set F1, order ignored, equivalence classes applied |
| **Sequencing** | what order? | of correctly-named steps, fraction of gold adjacent pairs preserved |
| **Validity** | does it run? | share of consecutive pairs whose handoff type-checks |

**Equivalence classes** — `PERFORMS -> Operation`. STAR and HISAT2 both perform *Sequence
alignment*, so either scores.

EDAM operations are coarse: "Sequence alignment" would also credit `bwa` for spliced RNA
alignment. A class is therefore **operation + accepted input data type**, never operation
alone.

**Validity** uses the existing `classify_handoff`. Results are `VALID` / `BROKEN` /
`UNKNOWN`. **`UNKNOWN` is reported separately and never counted as valid** — many methods
carry no I/O edges, and folding those into "valid" would inflate the score with ignorance.

**The 2×2 is the headline output:**

| | Valid | Invalid |
|---|---|---|
| **Conformant** | matched nf-core, runs | oracle bug — investigate |
| **Non-conformant** | legitimate alternative | wrong |

Bottom-left is why the design has two axes. Single-gold scoring marks it wrong.

**Next-step:** top-1 and top-3 against gold-next ∪ its equivalence class.

**Baselines:**
- Floor — (a) random tools from the catalog; (b) always answer the single most common gold
  sequence in the item set, ignoring the goal
- Ceiling — nf-core itself must score 1.0 (a scorer sanity check, run in CI)
- Contestants — several LLMs, temperature 0

## §3b — Live cuts (contamination control)

Follows LiveBench / LiveCodeBench: items carry a release date, and a model is scored only on
cuts postdating its training cutoff. Contamination stops being a caveat and becomes a
measurement.

| Set | Source | Role |
|---|---|---|
| **Main** | nf-core DAGs (155 pipelines, 142 active) | clean machine gold; assumed contaminated |
| **Live** | fresh preprints with a public workflow file | uncontaminated; refreshed monthly |

### Live item sourcing — measured, not assumed

April 2026 (fully-indexed month), open-access papers using DESeq2:

| Filter | Count | Share |
|---|---|---|
| baseline | 1,502 | — |
| + `github.com` link | 291 | 19% |
| + Nextflow / Snakemake / WDL | **31** | **2%** |

**~31/month is sufficient.** LiveBench replaces ~1/6 of its items per month; it does not
rebuild the set. At that cadence a Tier A yield of 20–30 usable items/month sustains the
live set indefinitely.

**Therefore no LLM extraction is required.** Gold comes from committed workflow files, parsed
the same way as nf-core. LiveBench's no-LLM-judge standard is preserved. Prose extraction
(previously "Tier B") is dropped from v1.

Reserve, if repo yield disappoints: papers with a GitHub repo but no workflow manager
(291/month) — order is often literal in a driver shell script. Semi-structured, still no
model judgment.

### Mechanics

- `bench/cuts/<YYYY-MM>/` — frozen, tagged, never re-released; every item carries `first_seen`
- Full-text indexing lags 2–3 months on Europe PMC (July 2026 returned 5 papers vs a ~1,500
  steady state), so bioRxiv is the fetch source; Europe PMC is the lagging cross-check
- **Headline result:** score plotted against cut date. The drop at a model's cutoff *is* the
  contamination estimate — the same signal LiveCodeBench used to expose DeepSeek's LeetCode
  gap.

## §4 — Runner and adapters

A contestant is a callable `(prompt: str) -> str`. Nothing model-specific leaks into
scoring.

- `adapters.openai` — `OPENAI_API_KEY` is present in this environment
- `adapters.claude_cli` — headless `claude -p`, no API key needed
- `adapters.static` — fixed responses, for scorer tests

Runner writes `results.jsonl` with one row per item: raw model output, normalized ids, all
three scores. Raw output is retained so any score can be re-derived without re-running.

## §5 — Layout and tests

```
bench/
  items/                    generated, committed
  gold/manifest.json        pipelines used + dropped, with reasons
src/methods_graph/bench/
  build.py       nf-core DAG -> items
  render.py      item -> prompt
  normalize.py   free text -> m: ids
  score.py       selection / sequencing / validity
  adapters.py    model adapters
  run.py         CLI: mg bench run --model <adapter>
tests/test_bench_score.py, test_bench_normalize.py, test_bench_build.py
```

Tests, written first:

1. Scorer: equivalence class credits HISAT2 for STAR; **rejects bwa for spliced alignment**
2. Scorer: order metric independent of naming errors
3. Validity: `UNKNOWN` never counted as valid
4. Ceiling: feeding the gold sequence back scores 1.0 on all three metrics
5. Build: an `io_inferred` pipeline never produces an item
6. Manifest: dropped pipelines are present with a reason

## Risks

| Risk | Mitigation |
|---|---|
| **Training contamination** — nf-core pipelines are public and likely memorized | Addressed by §3b live cuts: fresh preprint-derived items postdating model cutoffs, scored by cohort. The main set stays contaminated by assumption; the delta between main and live *is* the measurement. |
| **Live yield falls below ~20 items/month** | Fall back to Tier A− (repo with driver scripts, 291/month in the April sample). Do **not** fall back to prose extraction — that reintroduces an LLM judge. |
| Preview failures shrink coverage | Counted in the manifest, not hidden |
| EDAM coarseness makes equivalence too permissive | Class = operation + input data type; test 1 pins it |
| One pipeline per goal understates valid alternatives | Validity axis exists precisely for this |

## Open

Pipeline count is an empirical result of the build, not a design parameter. No number is
promised until `-preview` has been run across the catalogue.
