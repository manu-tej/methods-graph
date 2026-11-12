# Biolean benchmark (`mg biolean bench`)

**What this is:** the two-track Biolean benchmark as built on `main` at `6b28222`: how items are made, the exact prompt, every row and summary key, the baselines, the refusals, and how to run a paid model without losing or contaminating the run.
**Status, 2026-09-22:** merged and runnable. One real item set exists (500 prove + 500 hypothesize, in `biolean-bench/`, gitignored), and one paid run (Opus 5, prove track, `opus.jsonl`, untracked). The prove headline depends on an **open** kernel decision. The hypothesize track measures format compliance only.
**Read next:** [Opus 5 results](results-2026-09-22-opus-5.md), then the [transitive-edge decision memo](../decisions/2026-09-22-biolean-transitive-edges.md). Kernel rules, error codes and the derivation format are in the [Biolean guide](README.md).

Source citations are at `6b28222`. That includes `spec:N` (`docs/superpowers/specs/2026-09-21-biolean-design.md`), the Plan 2 file and `README.md:160`: the 2026-09-22 docs pass adds status banners to the spec and plan and rewrites `README.md`, which shifts those line numbers in the working tree, so read them with `git show 6b28222:<path>`. `items.py`, `render.py`, `score.py`, `baselines.py` and `run.py` live in `src/methods_graph/biolean/bench/`. `cli.py` is `src/methods_graph/cli.py`. `adapters.py` is `src/methods_graph/bench/adapters.py`, which is shared with the [method-sequencing benchmark](../method-sequencing-benchmark.md).

```bash
alias mg='.venv/bin/python -m methods_graph.cli'   # or .venv/bin/methods-graph; on macOS /usr/bin/mg is an unrelated text editor
```

---

## 1. At a glance

| | prove | hypothesize |
|---|---|---|
| Hider | `hide_exact`: every non-NOT row at the exact (subject, qualifier, term, taxon) | `hide_subtree`: the same, at the term and at every term below it |
| Question to the model | Re-derive the hidden fact closed-book, from a more specific annotation, over `is_a`/`part_of` | Propose the computation that would establish the fact, as a `sorry` step with provenance |
| Gold | The mechanical prover's shortest derivation, stored on each item | None (`"hypothesize_gold": null` in the manifest) |
| Headline metric | `hit_rate` | `format_ok`, `goal_match`, `inputs_nonempty`, `method_resolves` (**format only**) |
| Eligible / sampled, real set | 32,298 / 500 | 131,833 / 500 |
| Baselines, real set | gold 500/500 (1.000), modal 264/500 (0.528), random:0 26/500 (0.052) | template: all four rates 500/500 (1.0) |
| Paid runs | `claude:claude-opus-5`: 205/500 (0.410) under the strict kernel | none |

Sources: `biolean-bench/manifest.json`. `gold:`, `modal:`, `random:0` and `template:` were all re-run for this doc on 2026-09-22 (§11). `opus.jsonl` was summarized read-only. Opus under the other candidate edge rules scores 269/500 (0.538, relation-aware) and 287/500 (0.574, relation-blind). See the [results doc](results-2026-09-22-opus-5.md).

---

## 2. Why two tracks

**Design decision, recorded in spec §0 next to the owner-fixed decisions** (`docs/superpowers/specs/2026-09-21-biolean-design.md:33-40`). Hiding a gene's annotations at a term *and its whole subtree* makes re-derivation impossible by construction. Propagation only moves upward, and the subtree is exactly the set of terms from which the goal is reachable. So a subtree-hidden item cannot measure proving. It became the **hypothesize** track, where the only admissible proof is a `sorry`. The **prove** track hides only the exact fact, so a derivation through a visible, more specific annotation exists, and the model has to find it without looking anything up.

### prove: why `hide_exact` must hide every row of the triple

**Fact, measured.** GOA often records the same fact more than once (several evidence codes and references). If only one row is masked, the fact almost always comes back through a sibling row. That is a one-step axiom, not a derivation.

| Single-row masking: 1,000 experimental/HTP rows, from the first 31 of the test's 118 subjects | rows |
|---|---|
| Still derivable after masking one row | 815 |
| of which re-derived by an axiom at a sibling row of the **same** triple (no propagation) | **785** (96% of 815) |
| of which re-derived by real propagation | 30 |
| Not re-derivable | 185 |

Source: the comment at `tests/test_biolean_scale.py:58-63` (commit `39d0263`, 2026-09-21). Reproduced exactly on 2026-09-22 by re-running that test's loop over the same `snapshots/go`.

That is why `hide_exact` (`items.py:100-103`) hides **every** non-negated row at `(subject, qualifier, term, taxon)`, whatever its evidence code, IEA included. It has these consequences, measured on the 500 sampled prove items:

- 365/500 items hide more than one row; 4,077 rows are hidden in total.
- `hidden_classes` includes classes outside the population. 224/500 items hide an `electronic` row and 480/500 an `experimental` one. So the `by_evidence_class` buckets overlap: their `n` values sum to 872 over 500 items.

### hypothesize: format compliance only, until Phase B

**Owner decision** (spec §0 item 1 and non-goals, `spec:14-16, 59-60`): Phase A now, Phase B later. A GAF row records PMIDs and evidence codes, never datasets or method ids, so there is no data-derived gold for a `sorry`'s provenance. The constant `template:` reply scores 1.0 on every rate (§7). The track's knowledge measure waits on Phase B's `discharge(sorry, provider)` (`spec:720-724`), which **has not been started**. The summary says so in its `note` string (`score.py:33-36`).

---

## 3. How items are built

`mg biolean bench build` → `build_items` (`items.py:293-329`). The order is fixed:

```
population → prove_items (hide_exact) → fit_modal(all prove-eligible) → hypothesize_items (hide_subtree)
           → apply_since per track → sample per track → write items/, modal.json, manifest.json
```

### Step 1: population (`items.py:38-79`)

Every loaded annotation row is tested against these filters in order: 906,422 rows, which is the GAF's 906,445 data rows minus 23 duplicate rows collapsed at load (`load_report`). A row is counted only under the **first** filter it fails (`DROP_REASONS`, `items.py:27-28`). The visible store is always the whole GAF; the filters decide only which facts may be *hidden*.

| # | Drop reason | A row passes if | Dropped, real set |
|---|---|---|---|
| 1 | `negated` | it is not a NOT row | 1,501 |
| 2 | `qualifier_out_of_scope` | qualifier ∈ {involved_in, enables, located_in, part_of, is_active_in} | 6,837 |
| 3 | `evidence_class` | experimental (EXP IDA IPI IMP IGI IEP) or high_throughput (HTP HDA HMP HGI HEP) (`props.py:37-45`) | 436,190 |
| 4 | `object_type` | `protein` | 8,717 |
| 5 | `term_not_in_ontology` | the term id is known | 0 |
| 6 | `term_alt_id` | the term id is primary, not an alt_id | 0 |
| 7 | `term_obsolete` | the term is live | 60 |
| | **eligible rows** | | **453,117** of 906,422 (453,117 + 453,305 dropped = 906,422) |

Eligible rows collapse to **131,833** unique (subject, qualifier, term, taxon) triples. All of them are `UniProtKB:` subjects under `NCBITaxon:9606`. The manifest's `n_subjects` is 38,924: every subject in the GAF was *enumerated*. Only 16,836 subjects have at least one eligible triple (counted from `population()` on 2026-09-22; this number is not in the manifest).

### Step 2a: prove items (`items.py:191-207`)

For each triple, hide it with `hide_exact`, then run the mechanical prover over `MaskedFactStore(store, hidden)`. The prover is a shortest multi-source BFS from every visible annotation of the subject under the same qualifier and taxon, with ties broken by sorted term id.

- It finds a derivation → an item. `gold` is that derivation, and `gold_depth = len(steps) - 1` (the number of propagation steps).
- It finds none → counted under `not_rederivable`. Real set: 99,535 of 131,833.

### Step 2b: hypothesize items (`items.py:216-244`)

For each triple, hide it with `hide_subtree` (`items.py:106-119`). That removes the exact rows at the term and at every propagation descendant (the closure of is_a ∪ part_of, same namespace, live terms). NOT rows are never hidden. Then two checks run:

1. The prover over the masked store **must fail**. If it succeeds, the build raises `BuildError` and exits 1, because a wrong hider is a build defect, not a dropped item (`items.py:161-169`; `spec:715-716`).
2. A single placeholder `sorry` at the goal **must be ACCEPTED**. If it is not, the triple is counted once under the alphabetically first error code in `goal_not_statable` and dropped. Real set: 0 dropped, so all 131,833 triples are eligible.

### Step 3: modal fit (`items.py:267-282`)

`modal.json` maps qualifier → goal term → proper descendant → count. The count is the number of prove-eligible items whose subject is visibly annotated at that descendant (over that item's masked store). The fit runs over **all 32,298 prove-eligible items, before the live cut and before sampling**. At answer time the modal baseline subtracts the item's own subject (leave-subject-out, `baselines.py:126-128`). Real file: 2,802 (qualifier, term) keys: enables 736, involved_in 1,699, is_active_in 47, located_in 190, part_of 130.

### Step 4: live cut, `--since YYYY-MM-DD` (`items.py:251-257`)

The cut keeps an item iff `cut_date >= since`. `cut_date` is the **minimum** date over every hidden row of every evidence code. IEA rows carry the date of the pipeline run, so a max-or-exists rule would let a fact curated decades ago pass as recent. Removed items are counted in `excluded_by_since`. **Not done:** no item set has been built with `--since` (the real set has `since: null`). In the current samples, only 44/500 prove and 30/500 hypothesize items have `cut_date >= 2026-01-01`.

### Step 5: sampling (`items.py:260-264`)

Sort by item id. If `--per-track` ≥ the number eligible, keep all of them and don't call the RNG. Otherwise take `random.Random(seed).sample(ordered, n)` and re-sort by id. Defaults: `--per-track 500`, `--seed 0`. On the shipped pair, id order equals (subject, qualifier, term) order, and item ids do not collide.

### Step 6: freeze

`biolean-bench/` holds `items/prove.json`, `items/hypothesize.json`, `modal.json` and `manifest.json`, all written with `sort_keys=True`. A fresh build is byte-identical to the existing set (all four files, checked with `cmp` on 2026-09-22). It takes ~38–41 s on this machine: 41.2 s in the survey, 37.9 s re-timed on 2026-09-22.

**Item keys** (`items.py:172-188, 205-206`):

| Key | Meaning |
|---|---|
| `id` | `<track>/<subject>/<qualifier>/<term>` (no taxon) |
| `track` | `prove` or `hypothesize` |
| `goal` | the hidden fact as a `Prop`: `{subject, qualifier, term, taxon, negated: false}` |
| `symbol` | the minimum gene symbol across the subject's rows (used in the prompt) |
| `term_name` | the GO term name (used in the prompt) |
| `hidden` | sorted annotation ids masked for this item |
| `hidden_dates` | sorted dates of the hidden rows |
| `cut_date` | `min(hidden_dates)` |
| `hidden_classes` | evidence class of each hidden row, sorted, repeats kept |
| `gold`, `gold_depth` | **prove only**: the prover's derivation and its propagation-step count |

### The real item set (`mg biolean bench coverage --items biolean-bench`)

| Manifest field | Value |
|---|---|
| `release.go_basic_data_version` | `releases/2026-07-26` |
| `release.goa_date_generated` | `2026-05-21T08:10` |
| `release.goa_go_version` | `…/releases/2026-04-27/extensions/go-plus.ofn` |
| `seed` / `per_track` / `since` / `schema` | 0 / 500 / null / 1 |
| `population.rows` / `eligible_rows` / `triples` / `n_subjects` | 906,422 / 453,117 / 131,833 / 38,924 |
| `prove.eligible` / `not_rederivable` / `excluded_by_since` / `sampled` | 32,298 / 99,535 / 0 / 500 |
| `hypothesize.eligible` / `goal_not_statable_total` / `excluded_by_since` / `sampled` | 131,833 / 0 / 0 / 500 |
| `hypothesize_gold` | null |

The 500 sampled prove items (from `biolean-bench/items/prove.json`):

| Property | Value |
|---|---|
| `gold_depth` | 1: 315 · 2: 124 · 3: 47 · 4: 10 · 5: 4 (the `4+` bucket = 14) |
| Gold steps | 500 axiom, 524 `is_a`, 240 `part_of` (mean depth 1.528) |
| Qualifiers | enables 184 · located_in 180 · involved_in 109 · part_of 19 · is_active_in 8 |
| Distinct subjects | 488 |
| `cut_date` | 2001-08-29 … 2026-04-25 (the two middle values of 500 are 2014-12-09 and 2015-01-22) |

**Open: release skew.** The OBO (2026-07-26) is newer than the GO release the GAF was built against (2026-04-27). `snapshots/go/` has no `snapshot.json`, so it was not produced by `mg biolean fetch`, which pins the OBO to the GAF's release. Re-fetching would change the release identity, and `run`, `score` and `--resume` would then refuse the frozen items and both result files (§8). See [BACKLOG](../BACKLOG.md).

---

## 4. The prompt, and how a reply is parsed

### Prompt (`render.py:13-59`)

Single shot and closed book. Kernel error suggestions are never fed back (spec non-goals). This is the real prompt for `prove/UniProtKB:A0A087X1C5/located_in/GO:0005737`, verbatim. The `Format:` paragraph is one line:

```
Prove the following claim as a Biolean derivation.
Claim: CYP2D7 (UniProtKB:A0A087X1C5) located_in cytoplasm (GO:0005737), human.
The direct annotation of this gene product to this term is not available to you. Derive
it from an annotation to a more specific term using the rules is_a and part_of.
Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only.
Format: {"biolean": "0.1", "goal": P, "root": "<id of the final step>", "steps": [...]}, where P is {"subject": "<UniProtKB accession, e.g. UniProtKB:P04637>", "qualifier": "<GAF qualifier, e.g. involved_in>", "term": "<GO id>", "taxon": "<NCBITaxon:id>", "negated": false}. Steps: {"id": "s1", "rule": "axiom", "conclusion": P} cites a recorded annotation; {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["<GO child>", "<GO parent>"], "conclusion": P} lifts the premise along an is_a edge, and rule "part_of" does the same along a part_of edge; {"id": "s1", "rule": "sorry", "conclusion": P, "provenance": {"method": "<method>", "inputs": ["<dataset>"], "parameters": {}, "claim": "<what the computation shows>"}} admits a computed result. Every step id is unique and a premise must come earlier.
```

The hypothesize prompt replaces the first five lines with:

```
No recorded annotation supports the following claim.
Claim: <same claim format>
Propose the computation that would establish it: a Biolean derivation whose root is a
sorry step with provenance naming the method, the input datasets, and parameters.
Answer with the JSON document only.
```

- The claim is `<symbol> (<subject>) <qualifier> <term_name> (<term>), <organism>.` `organism()` maps only `NCBITaxon:9606` to `human`; any other taxon is printed verbatim.
- The `Format:` block is identical for every item and both tracks, so it adds no per-item information (plan deviation 2, §10).
- **Open:** the prompt never says an `is_a`/`part_of` edge must be a *direct, asserted* edge of this GO release, but the kernel accepts only such edges (`kernel.py:304-313`). This is the subject of the [transitive-edge decision](../decisions/2026-09-22-biolean-transitive-edges.md).

### `parse_reply` (`render.py:65-92`)

It scans every `{` from left to right and JSON-decodes from there. It returns the **first** decoded dict that has at least one of the keys `steps`, `root` or `biolean`. Anything else is `None`, which is scored `UNPARSED`: a miss that stays in the denominator. It is never turned into an empty derivation. Probed 2026-09-22:

| Reply | Result |
|---|---|
| Blank, or not a string | `None` |
| A JSON document inside a fenced code block, with prose around it | parsed |
| Document inside a list, or under another key (`{"answer": {...}}`) | the inner document is found |
| A dict without `steps`/`root`/`biolean` (a bare `Prop`, or a tool-call JSON `{"name": "Bash", …}`) | skipped; `None` if nothing else matches |
| Trailing comma, or Python `False`/`True`/`None` | `None` |
| `NaN` literal | parsed (JSON's decoder accepts it). The kernel then rejects it as `MALFORMED`; the scorer does not crash |
| An example object in prose **before** the real answer | **the example wins**. Not tested; 3/500 Opus replies were UNPARSED, none for this reason |

---

## 5. Rows: one per item, streamed to `--out`

`score.py:25-31` defines the vocabulary: 13 common keys, 8 prove-only and 5 hypothesize-only, with no overlap between the two track sets. A real prove row has 21 keys and a hypothesize row 18 (checked against `modal.jsonl` and a fresh `template:` run).

| Key | Track | Meaning | Unparsed row | Error row |
|---|---|---|---|---|
| `item` | both | item id | id | id |
| `track` | both | `prove` / `hypothesize` | set | set |
| `model` | both | the `--model` string (stamped by `run.py`) | set | set |
| `items_manifest` | both | `{release, since}` copied from `manifest.json`; lets `score` and `--resume` refuse a mismatch using only the rows | set | set |
| `goal`, `hidden`, `hidden_classes` | both | copied from the item, so `rescore` needs only the row and the store | set | set |
| `raw` | both | the adapter's reply, verbatim | the reply | `null` |
| `parsed` | both | `parse_reply` found a document | `false` | `false` |
| `error` | both | string when the adapter raised `AdapterError`, rendering failed, or a call failed during a parallel abort; else `null` | `null` | string |
| `render_error` | both | `ExcType: msg` when `render_prompt` failed | `null` | string or `null` |
| `error_codes` | both | sorted kernel error codes, repeats kept; `[]` when accepted | `["UNPARSED"]` | `null` |
| `goal_match` | both | the elaborated conclusion of the step named by `root` equals the item's `Prop`; `null` if `root` names no step | `null` | `null` |
| `gold_depth` | prove | copied from the item | set | copied |
| `accepted` | prove | the kernel verdict is ACCEPTED over `MaskedFactStore(store, hidden)` | `false` | `null` |
| `goal_rewritten` | prove | the reply's own `goal`, elaborated, differs from the item's `Prop`. **Also `true` when the goal is missing or malformed**, so it counts omissions as well as rewrites | `null` | `null` |
| `hit` | prove | `accepted and goal_match is True and sorry_count == 0` | `false` | `null` |
| `hit_with_sorry` | prove | the same, with `sorry_count > 0` | `false` | `null` |
| `sorry_count` | prove | `sorry` steps **on the used chain** | `null` | `null` |
| `unused_sorries` | prove | `sorry` steps off the used chain | `null` | `null` |
| `depth` | prove | propagation steps on the used chain (`steps_checked − unused_steps − 1`) when accepted, else `null`; comparable with `gold_depth` | `null` | `null` |
| `format_ok` | hypothesize | accepted and the root rule is `sorry` | `false` | `null` |
| `inputs_nonempty` | hypothesize | `provenance.inputs` is a non-empty list; `null` if the root is not a `sorry` | `null` | `null` |
| `method` | hypothesize | `provenance.method`, verbatim (string or `null`) | `null` | `null` |
| `method_normalized` | hypothesize | exact `m:` lookup through `bench/normalize.py::normalize_name`, never `resolve_method_ids` | `null` | `null` |
| `method_resolves` | hypothesize | `method_normalized is not null`; `null` when there is no graph or no method string (never `false` by default) | `null` | `null` |

The scorer never trusts the reply's own `goal`. It elaborates and checks the reply, then compares the **root step's** conclusion to the item's `Prop` (`score.py:61-64, 81-106`). A model that rewrites the claim and proves the rewrite is accepted, but it is not a hit.

---

## 6. The summary (stdout of `run` and `score`)

`summarize` (`score.py:248-266`). The two tracks are **never pooled**, and both blocks are always present. A one-track run has `n: 0` and null rates in the other block.

| Top-level key | Meaning |
|---|---|
| `n_rows` | every row, both tracks |
| `n_errors` | rows with `error` set. **Excluded from every per-track denominator** |
| `n_render_errors` | a subset of `n_errors` |
| `n_unparsed` | error-free rows with `parsed: false`. **Kept in the denominators as misses** |
| `n_checked` | error-free rows that were parsed and checked |
| `release`, `since` | from `items_manifest`; `null` unless every row carries the same one |
| `prove`, `hypothesize` | per-track blocks, below |

**Reconciliation identity:** `n_rows == n_errors + n_unparsed + n_checked`, exactly. Test: `tests/test_biolean_bench_run.py:46` (`test_rows_reconcile`). For `opus.jsonl`: 500 = 0 + 3 + 497.

| `prove` key | Meaning |
|---|---|
| `n`, `n_hits`, `hit_rate` | `hit_rate = n_hits / n`, where `n` = the **error-free prove rows**. The spec's `hits / (n_rows − n_errors)` (`spec:559`) is exact only for a prove-only file |
| `hit_with_sorry_rate`, `acceptance_rate` | over the same `n` |
| `n_goal_rewritten` | count (includes missing or malformed goals, see §5) |
| `mean_depth` | mean `depth` over hits, `null` if there are none |
| `by_evidence_class` | `{class: {n, hit_rate}}`. An item counts under **every** class among its hidden rows, so the `n` values overlap (sum 872 over 500) |
| `by_gold_depth` | `{"1","2","3","4+": {n, hit_rate}}` |
| `error_items` + `error_items_denominator` | rows whose `error_codes` contain the code, over `n`. **This is the headline histogram**, because it does not depend on derivation length |
| `error_occurrences` + `error_occurrences_denominator` | total occurrences of each code, over the sum of all occurrences |

| `hypothesize` key | Meaning |
|---|---|
| `note` | `"format compliance only: …"`. The spec says this is a printed heading (`spec:599`); in the code it is this JSON string |
| `n` | error-free hypothesize rows |
| `format_ok`, `goal_match`, `inputs_nonempty`, `method_resolves` | each `{n, rate}`, over the rows where the field is not `null` |
| `n_method_resolves_none`, `method_unresolved` | rows with `method_resolves` null; `[[name, count], …]` for the names that did not resolve |
| `error_items`, `error_occurrences` (+ denominators) | as for prove |

`score` re-derives every row from the retained `raw` plus the row's own `goal`/`hidden` and the store (`run.py:172-186`); it never reads the item files. Checked 2026-09-22: rescoring `modal.jsonl` and `opus.jsonl` reproduces every row. `score` uses the **current** `--db`, so `method_resolves` can change if the graph has changed.

---

## 7. Baselines (`baselines.py`)

Each baseline is a `(prompt) -> str` table built in item order over the whole selection (`baselines.py:151-163`), so a seeded baseline is deterministic, including after `--resume`.

| Spec | Track | What it answers | Real set | Fails only by | What it shows |
|---|---|---|---|---|---|
| `gold:` | prove | The prover's derivation over the item's masked store (`:94-98`) | 500/500 = **1.000**, mean depth 1.528 | — | That the full scoring path (render → parse → elaborate → check → goal_match) credits a correct answer on every item, and that no item is unwinnable. It does **not** test the prover, since items are defined by the prover succeeding. **It must be 1.0**; anything less is a scorer or release bug |
| `modal:` | prove | The most-counted descendant for (qualifier, goal term) after leave-subject-out, ties broken by sorted term id, plus the shortest path up. An empty counter emits the hidden axiom, which is a counted miss (`:121-134`) | 264/500 = **0.528**. Depth 1: 0.622 · 2: 0.468 · 3: 0.128 · 4+: 0.286 | `AXIOM_NOT_FOUND` (236) | The gene-blind prior: what GO's shape and population frequencies give without knowing the gene. It is accepted exactly when it hits, and it never makes a structure error because its path comes from the store. **The number to beat.** It matches the spec's 52.8% (`spec:629-631`) |
| `random:<seed>` | prove | A seeded random *visible* start for the gene under the item's qualifier, then 1–4 random upward hops; the root is wherever the walk ends (`:101-118`) | random:0 26/500 = **0.052** | `ROOT_MISMATCH` (474) | The floor. It is store-informed by design: it starts from real evidence and hits only when the walk lands on the goal |
| `template:` | hypothesize | A constant `sorry` root: method `m:deseq2`, inputs `["GEO:GSE0"]`, empty parameters, the item's claim (`:137-144`) | 1.0 on all four rates (n 500) | — | That the hypothesize track **saturates**: it measures format, not knowledge. `method_resolves` is 1.0 only when `data/methods.kuzu` is present. Without it the rate is `{n: 0, rate: null}` and `n_method_resolves_none` is 500 |

- **Open:** the spec reads a model below modal as "reporting GO's shape, not the gene" (`spec:631, 909-910`). For Opus under the strict kernel, that reading is inverted. On a biology-only measure Opus beats modal, 305 vs 264 (p = 0.0015). Its deficit is exact-edge recall. See the [results doc](results-2026-09-22-opus-5.md).
- A baseline on the wrong track, a non-integer random seed, a missing `modal.json`, or two items with the same prompt raises `AdapterError`, which exits 2 (`baselines.py:151-191`).

---

## 8. Release identity and refusals

**Release identity** is read from the file headers, not from `snapshot.json` (`items.py:138-154`): the OBO `data-version:` line (reading stops at the first `[Term]`), and the GAF `!date-generated` and `!go-version` (via `fetch.gaf_header`). `build` records it in `manifest.json`, and every row carries it in `items_manifest`.

Every refusal below except `BuildError` exits **2** through `parser.error` and names what differs. Checks marked "before the store load" cost nothing. Every refusal in `run` happens before `--out` is opened, so it never touches an existing results file.

| Subcommand | Refuses when | Where |
|---|---|---|
| `build` | `--per-track < 1` (before the load) | `cli.py:1343-1344` |
| `build` | `--since` is not `YYYY-MM-DD`. **This check runs after the ~13–16 s store load**, although the comment at `cli.py:1341` says validation comes first | `cli.py:1357-1359` |
| `build`, `run`, `score` | `--store` lacks `go-basic.obo`, the GAF or `gaf-eco-mapping.txt` | `cli.py:1179-1188` |
| `build` | the hypothesize prover still succeeds after hiding → `BuildError`, **exit 1** (by design; 1 is reserved for uncaught exceptions) | `items.py:233-234` |
| `coverage`, `run` | `--items` has no `manifest.json`, or no items | `items.py:338-348` |
| `run` | `--limit < 0`, `--workers < 1`, or `--workers > 1` with any `static:` adapter (before the load) | `cli.py:1345-1351` |
| `run` | the store's release differs from the items' (each differing key is named) | `cli.py:1378-1380` |
| `run` | an adapter cannot be built: unknown spec, baseline on the wrong track, bad seed, missing `modal.json`, `OPENAI_API_KEY` unset for `openai:`, unreadable `static:` file | `cli.py:1399-1405` |
| `run --resume` | see §9.3 | `cli.py:1255-1300` |
| `score` | the file is unreadable or has zero rows; rows mix more than one `items_manifest` or more than one `model`; the recorded release differs from the store's | `cli.py:1440-1462` |

`score` does **not** refuse a file that mixes tracks; the summary keeps them apart anyway.

---

## 9. Running a paid model safely

`claude:<model>` and `openai:<model>` **cost money and need network**. Everything else here is free and offline (it needs `snapshots/go`). No cost is recorded anywhere for the one paid run.

### 9.1 The closed-book `claude:` adapter (`adapters.py:55-88`)

Each item runs:

```
claude -p <prompt> --model <model> --tools "" --safe-mode --strict-mcp-config
```

The working directory is a **fresh, empty temporary directory**, and the call times out after 300 s. A non-zero exit, a timeout or an `OSError` becomes `AdapterError`, which is an error row, and the run continues. The default model is `claude-opus-5`. Commit `128a8c6` (merged at `894072d`) added the layers after `--tools ""` alone was found to leave MCP servers, hooks and `CLAUDE.md` in every contestant's prompt.

| Layer | Blocks | Does not block |
|---|---|---|
| `--tools ""` | every built-in tool: shell, file read/write, web fetch/search | MCP tools |
| `--safe-mode` | `CLAUDE.md` at every level, hooks, skills, plugins, MCP servers, custom commands and agents | admin-managed policy; Claude Code's own default system prompt |
| `--strict-mcp-config` (no `--mcp-config`) | every MCP server, even if safe mode's scope ever narrows | — |
| empty temp cwd | reading the item files (which hold `gold` and `hidden`), the store, the repo | — |

Commit `128a8c6` records a live check: `tools []`, `mcp_servers []`, 0 SessionStart hooks (3 without safe mode), and a 4,265-token prompt with the flags (8,806 without). `tests/test_bench_adapters.py:29` pins the exact command and the empty cwd. The installed CLI here is 2.1.280, which supports all three flags.

**Not controlled (open, see [BACKLOG](../BACKLOG.md)):**

- No `--system-prompt` is passed, so the contestant runs under Claude Code's default system prompt.
- There is no temperature control. `openai:` is a raw chat completion at temperature 0 with a 120 s timeout (`adapters.py:103-131`), so cross-provider comparisons are not like for like.
- The rows do not record the CLI version, the flags, `--workers`, or the commit.

**Open: closed-book integrity.** 3 of 500 Opus replies were not answers but attempted tool calls to EBI QuickGO (`curl …/QuickGO/services/annotation/search?geneProductId=…`):

- two as `<invoke name="Bash">` text followed by `Failed to run command: ETIMEDOUT`, or by `Command running in background (ID: 2b6df5), check status with BashOutput.`;
- one as a JSON `{"name": "Bash", …}`.

All 3 score `UNPARSED` (misses, kept in the denominator). The file's mtime (2026-09-22 20:32:57 -0700) is after the closed-book merge. Whether the trailing tool-result text came from a real tool runtime or was generated by the model is **unknown**. Because `raw` is the only record, silent retrieval in other rows cannot be ruled out from the data. See the [results doc](results-2026-09-22-opus-5.md).

### 9.2 `--workers N` (`run.py:83-169`, `cli.py:1406-1437`)

- Adapter calls run in a thread pool of size N. Rendering and scoring stay in the calling thread.
- Rows are written **in completion order**, each flushed as soon as it is scored. A row therefore never waits in memory behind a slower item, and SIGKILL or SIGTERM loses nothing that was already answered.
- When the run completes, `--out` is rewritten **once, atomically, in item order**: a temp file beside it, fsync, `os.replace`, file mode kept (`cli.py:1303-1324`). A fresh parallel file is therefore **byte-identical** to a `--workers 1` file for a deterministic adapter (`tests/test_biolean_bench_cli.py:251`). The rewrite follows a symlink and skips a non-regular `--out` such as `/dev/null`. If the rewrite fails with `OSError`, a warning is printed, the file stays complete in completion order, and the summary is still printed.
- `static:` is refused with `--workers > 1`: a list-backed `static:` replays answers in call order, which parallel calls scramble. The dict-backed form would be safe but is refused too.
- Opus took 12–27 s per call sequentially, 2–3 h for 500 items (commit `4c2e3b9`); that is why this flag exists. `README.md:160` shows `--workers 8`. Nobody has measured rate limits or the best N.

### 9.3 `--resume` (`cli.py:1255-1300, 1381-1411`)

It applies only when `--out` already exists; otherwise the run is a normal fresh run. So **always passing `--resume` is safe.**

- **Keeps:** the first error-free row per item.
- **Drops:** error rows (so those items are retried) and duplicate rows.
- **Runs:** the current `--track`/`--limit` selection minus the kept ids.
- **Prints to stderr:** `{"resume": {rows_read, kept, dropped_error_rows, dropped_duplicate_rows, kept_outside_selection, to_run}}`. On a complete gold file it printed `kept 500, to_run 0` and left the file byte-identical (checked 2026-09-22).
- **Writes:** `--out` is rewritten atomically with the kept rows, then new rows are appended. The summary covers kept + new rows, **including kept rows outside the current selection**.
- **Refuses (exit 2):**
  - an unreadable line;
  - a row that is not a dict with a string `item` and an `error` key;
  - any row from another `--model`;
  - any row with another `items_manifest`;
  - any item id outside the **full** `--items` set, taken before `--track`/`--limit`. This catches a sample drawn with another `--seed` or `--per-track`, which the manifest check cannot see.
- **Row order:** a resumed file holds kept rows first, then new rows, so it is **not** in item order unless the kept rows were an item-order prefix. Summaries do not depend on order, but a byte diff against a fresh run fails. The `--workers` help text (`cli.py:1977`) says "item order" without this caveat.

**Hazard:** `run` **without** `--resume` opens `--out` with `"w"` (`cli.py:1416`) and **truncates an existing paid file**.

### 9.4 Interrupts and failures

| Event | Rows on disk | Calls in flight | Summary | Recover with |
|---|---|---|---|---|
| `AdapterError`: `claude -p` exits non-zero or times out; `openai:` URL error, timeout or bad JSON | an error row; the run continues | — | printed; counted in `n_errors`, excluded from denominators | `--resume` (retries error rows) |
| Ctrl-C, `--workers 1` | every row before it | the current call is lost (the `claude -p` child gets the same Ctrl-C) | not printed (traceback) | `--resume` |
| Ctrl-C or another abort, `--workers N` | queued calls are **cancelled first**; finished calls are written in item order; then the notice `biolean bench: stopping; waiting for N call(s) still in flight, each written as it finishes (Ctrl-C discards the rest)`, and each in-flight call is written as it lands | a terminal Ctrl-C also reaches the `claude -p` children, so they usually finish as `AdapterError` rows: paid for, not kept | not printed; the exception re-raises | `--resume` |
| A second Ctrl-C during that drain | rows written so far are kept | calls still running are discarded (the interpreter still waits for their threads at exit) | not printed | `--resume` |
| A call raises something other than `AdapterError`, e.g. a connection reset the adapter does not wrap | `--workers 1`: the run stops, and earlier rows are kept. `--workers N`: the abort path above; other drained calls that fail the same way become error rows; only the call whose exception is re-raised gets no row | as above | not printed | `--resume` |
| Writing a row fails (e.g. disk full) | `--workers 1`: the run stops. `--workers N`: the abort path; the cancel runs first, so queued paid calls never start | drained (`--workers N`) | not printed | free space, then `--resume` |
| SIGKILL, SIGTERM, SIGHUP, crash | every row already scored (in completion order with `--workers N`) | lost | none | `--resume` reads a file in completion order |

Sources: `run.py:26-58` (docstring) and `:141-167`; commits `ad992e8`, `09986ab`, `26c09dd`, `948ba7d`; their bodies record 29 `mutation checked:` lines (11 + 7 + 7 + 4), on top of the 12 in `4c2e3b9`. The interrupt paths are tested with injected callables (`tests/test_biolean_bench_run.py:204-587`), never with a real `claude` process.

### 9.5 Checklist for a paid run

1. Free: `mg biolean bench run --model gold: --track prove --out /tmp/biolean/gold.jsonl`. This proves the store, items and release agree. Expect `prove.hit_rate` 1.0.
2. Paid, small: add `--limit 3` to the real command and read the three `raw` fields.
3. Paid, full: **always pass `--track prove` and `--resume`.** Without `--track`, a model adapter runs both tracks, which is 1,000 calls on the real set. Use an `--out` path you will keep; results have no agreed home (open, see [BACKLOG](../BACKLOG.md)).
4. After the run: `mg biolean bench score --results <file>` must reproduce the summary. Write down the commit, `claude --version`, the flags and `--workers`, because the rows do not carry them.

---

## 10. Seven deliberate spec deviations

**Plan decisions, merged at `b0f80c4`.** They are listed in Plan 2's Global Constraints (`docs/superpowers/plans/2026-09-22-biolean-plan-2-benchmark.md:25-32`) and were written into the spec by Task 1.

| # | Deviation | Why |
|---|---|---|
| 1 | `FactStore` gains `subjects() -> tuple[str, ...]` | the population must enumerate subjects; the protocol had no way to |
| 2 | Both prompts end with the fixed `Format:` block | a closed-book model cannot emit a format it has never seen, and an all-`UNPARSED` benchmark measures nothing |
| 3 | Release identity is read from the file headers, not `snapshots/go/snapshot.json` | the local snapshot was fetched by hand and has no `snapshot.json`; the headers are what that manifest copies anyway |
| 4 | `depth` (row) and `gold_depth` (item) both count **propagation steps** (used steps minus the axiom) | makes `mean_depth` comparable with the `1/2/3/4+` buckets and with `goals`' `depth: 0` for a direct annotation |
| 5 | Layout: `biolean/bench/render.py` holds `render_prompt` and `parse_reply`; `--items DIR` is the `build --out` directory; `--per-track` defaults to 500 | mirrors `bench/render.py` |
| 6 | Every row carries `items_manifest: {release, since}` | `score` can refuse a mismatched store and echo `since` from the rows alone |
| 7 | `goal_not_statable` counts each dropped triple once, under the alphabetically first error code, and ships `goal_not_statable_total` | one count per triple; nothing double-counted |

### Where the spec or help text still disagrees with the code (facts; the code wins)

| Location | Says | Code does |
|---|---|---|
| `spec:118-121` | "the shipped pair is consistent" | the local pair is skewed (OBO 2026-07-26 vs GAF on 2026-04-27); see §3 |
| `spec:491-492` | sample triples sorted by (subject, qualifier, term) with `min(N, len)` | cuts by `--since` first, sorts by id, skips the RNG when N ≥ len, re-sorts by id |
| `spec:559` | `hit_rate = hits / (n_rows − n_errors)` | per track: hits / error-free prove rows |
| `spec:563` | denominator `n_errors_total` | key is `error_occurrences_denominator` |
| `spec:599` | prints a heading `format compliance only` | a `note` string in the JSON |
| `spec:704` | `run` flags end at `--limit` | `run` also takes `--workers`, `--resume`, `--db`, `--oracle-json`; no spec or plan covers `--workers`/`--resume` |
| `spec:879, 883, 884` | test names `test_hypothesize_rows_carry_no_hit_keys`, `test_modal_is_fit_before_sampling_and_leaves_the_subject_out`, `test_random_baseline_is_structurally_valid` | renamed or split: `test_hypothesize_rows_and_summary_carry_no_hit_keys` (`tests/test_biolean_bench_score.py:207`); `test_modal_is_fit_on_the_full_eligible_set_before_sampling` (`tests/test_biolean_bench_items.py:257`) + `test_modal_leaves_the_subject_out_and_breaks_ties_by_sorted_term_id` (`tests/test_biolean_bench_baselines.py:81`); `test_random_baseline_is_structurally_valid_and_seeded` (`tests/test_biolean_bench_baselines.py:43`) |
| `cli.py:1977` | `--workers` puts rows "in item order when the run completes" | not after `--resume` (§9.3) |
| `adapters.py:156-158` | unknown-adapter message lists `gold:, modal: or random:<seed>` | the Biolean bench also accepts `template:` |

---

## 11. Commands and expected output

All commands run from the repo root. `snapshots/go` is required by everything except `coverage`. stdout is the JSON result; stderr gets the `load_report` line (and the `resume` line).

| Command | Needs | Expected | Time here |
|---|---|---|---|
| `mg biolean bench build --out /tmp/biolean/bench` | `snapshots/go` | prints the manifest. All four files are byte-identical to `biolean-bench/` (check with `cmp`). Building into `biolean-bench` itself overwrites the frozen set | ~38–41 s |
| `mg biolean bench coverage --items biolean-bench` | the items only | prints `manifest.json` (§3) | < 1 s |
| `mg biolean bench run --model gold: --track prove --out /tmp/biolean/gold.jsonl` | `snapshots/go` | `prove.n` 500, `n_hits` 500, `hit_rate` **1.0**, `mean_depth` 1.528, `error_items` `{}` | ~13 s (2026-09-22) |
| `mg biolean bench run --model modal: --track prove --out /tmp/biolean/modal.jsonl` | `snapshots/go`, `biolean-bench/modal.json` | 264/500 = 0.528; `error_items` `{"AXIOM_NOT_FOUND": 236}`; byte-identical to the repo-root `modal.jsonl` | ~15–30 s |
| `mg biolean bench run --model random:0 --track prove --out /tmp/biolean/random.jsonl` | `snapshots/go` | 26/500 = 0.052; `{"ROOT_MISMATCH": 474}` | ~15–30 s |
| `mg biolean bench run --model template: --track hypothesize --out /tmp/biolean/template.jsonl` | `snapshots/go`; `data/methods.kuzu` for `method_resolves` | all four rates `{n: 500, rate: 1.0}` | ~15–30 s |
| `mg biolean bench score --results /tmp/biolean/modal.jsonl` | `snapshots/go` | the same summary as the run; `--out FILE` writes rows byte-identical to the input | ~15–30 s |
| `mg biolean bench run --model claude:claude-opus-5 --track prove --workers 8 --resume --out opus.jsonl` | `snapshots/go`, network, `claude` CLI auth. **Costs money** | 500 prove rows. The existing run scored 205/500 = 0.410 (strict). Pointed at the complete existing `opus.jsonl`, `--resume` finds `to_run 0` and makes no calls, but it still rewrites the file atomically; copy the file first | ~2–3 h sequential (`4c2e3b9`); parallel not timed |

Read one number from a run:

```bash
mg biolean bench run --model gold: --track prove --out /tmp/biolean/gold.jsonl 2>/dev/null \
  | .venv/bin/python -c 'import json,sys; p=json.load(sys.stdin)["prove"]; print(p["n_hits"], p["n"], p["hit_rate"])'
# 500 500 1.0
```

`run` opens `data/methods.kuzu` read-only even for a prove-only run, where `method_resolves` is unused (`cli.py:1365-1368`). Passing `--db /nonexistent` skips it and changes nothing on prove.

---

## 12. Tests, and what CI enforces

| Suite | Count | CI |
|---|---|---|
| `tests/test_biolean_bench_{render,items,score,baselines,run,cli,scale}.py` | 97 tests, 7 modules (`pytest --co`) | 96 run in CI. `tests/test_biolean_bench_scale.py` needs `snapshots/go` and **skips in CI** |
| Gold ceiling on the 6 fixture items | `tests/test_biolean_bench_baselines.py:37` (+ CLI tests) | **enforced** |
| Gold 1.0 on real data | only the scale test (a subject slice capped at 300, which is 118 subjects on this pair; `--per-track 100`) and manual runs | **not enforced** |
| Reconciliation identity | `tests/test_biolean_bench_run.py:46` | enforced |
| Closed-book command and empty cwd | `tests/test_bench_adapters.py:29` (mutation: drop `--safe-mode` → fails, per `128a8c6`) | enforced. No test runs a real `claude` |
| Parallel abort paths and `--resume` | `tests/test_biolean_bench_run.py:133-587`, `tests/test_biolean_bench_cli.py:251-459` | enforced, with injected callables |

```bash
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q tests/test_biolean_bench_*.py   # 97 tests; the scale test runs only when snapshots/go exists
```

---

## 13. Not done / open

Each item is tracked in [BACKLOG](../BACKLOG.md). Decisions go in the [decision log](../decisions/README.md).

- **Open decision:** strict direct-edge rule vs a transitive rule vs a strict kernel plus an untrusted expander. The Opus headline swings from 0.410 to 0.574 depending on it. See [the memo](../decisions/2026-09-22-biolean-transitive-edges.md).
- **Open:** whether the prompt should state the edge rule; changing `FORMAT_BLOCK` changes every prompt.
- **Open:** release skew (§3), and whether to rebuild on a pair made by `mg biolean fetch`.
- **Open:** closed-book integrity (3 QuickGO replies, §9.1); the `claude:` system prompt and temperature; run provenance is not in the rows.
- **Not done:** Phase B `discharge`, so hypothesize stays format-only.
- **Not done:** a `--since` item set; no other models run.
- **Not done:** `--workers`/`--resume` has no spec or plan (commit messages, `README.md` and `--help` only).
- **Not done:** Plan 2's checkboxes were never ticked.
- **Not done:** `opus.jsonl`, `opus.partial.jsonl` and `modal.jsonl` are untracked and not gitignored, and `biolean-bench/` is gitignored. Deleting them loses the only copy of the paid run.
- **Wart:** `run` without `--resume` truncates `--out`; `--since` is validated after the store load; `n_goal_rewritten` counts omissions; `parse_reply` takes the first document-like object.
