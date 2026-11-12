# Biolean prove track: Opus 5 results, 2026-09-22

**What this is:** the results of the only paid Biolean run: `claude:claude-opus-5` on the 500 frozen prove items, scored by the strict kernel next to the `gold:`, `modal:` and `random:0` baselines.

**Status as of 2026-09-22:** the run is complete and every row reproduces on rescoring. The result files are untracked and not committed. Whether the headline holds depends on an open decision about the kernel's direct-edge rule.

**Read next:** [transitive-edge decision memo](../decisions/2026-09-22-biolean-transitive-edges.md) · [the benchmark as built](benchmark.md) · [Biolean guide](README.md) · [BACKLOG](../BACKLOG.md) · [GLOSSARY](../GLOSSARY.md)

## The answer

- **Under the strict kernel (the benchmark as built), Opus 5 scores 205/500 (41.0%). The gene-blind `modal:` baseline scores 264/500 (52.8%).** Opus is below the baseline (exact McNemar p = 1.7e-5).
- **One kernel rule accounts for most of the gap.** A propagation step must cite a *direct* GO edge ([kernel.py:304-313](../../src/methods_graph/biolean/kernel.py)), and the prompt never says so. Of Opus's 187 EDGE_NOT_FOUND citations, 106 name a true ancestor and skip the intermediate terms. With a transitive step Opus would score 269 (53.8%, relation-aware, p = 0.76 vs modal) or 287 (57.4%, relation-blind, p = 0.077). **Open decision:** which rule the benchmark should use.
- **Opus collapses past depth 1 under the strict rule:** 54.0% at gold depth 1, 20.2% at 2, 21.3% at 3, 0/14 at 4+.
- **The files pass every integrity check.** Each of the 500 items appears exactly once, with 0 adapter errors and 3 unparsed replies. Rescoring on main reproduces all 500 rows byte for byte.
- **What limits these results:**
  - 3 replies tried to call QuickGO, which raises a closed-book question.
  - The GO and GOA files come from different releases.
  - The rows do not record the flags, the worker count or the commit.
  - There is one sample per item.

## Setup

| | |
|---|---|
| Contestant | `claude:claude-opus-5` runs `claude -p <prompt> --model claude-opus-5 --tools "" --safe-mode --strict-mcp-config` in a fresh empty temporary directory, with a 300 s timeout ([adapters.py:55-88](../../src/methods_graph/bench/adapters.py)). The adapter has been closed-book since 128a8c6 (merged at 894072d). Claude Code's own system prompt is still sent: 128a8c6 measured 4,265 prompt tokens with these flags and 8,806 without `--safe-mode`. There is no temperature control, and each item is sampled once. |
| Items | 500 prove items in `biolean-bench/items/prove.json`: seed 0, `per_track` 500, `since` null (no live cut). They are sampled from 32,298 eligible triples. Another 99,535 of the 131,833 triples could not be re-derived once hidden (`biolean-bench/manifest.json`). |
| Task | For each item, every non-NOT GAF row at the exact (subject, qualifier, term, taxon) is hidden ([items.py:100-103](../../src/methods_graph/biolean/bench/items.py)). The model must derive the claim from a more specific annotation with `axiom` / `is_a` / `part_of` / `sorry` steps. The prompt is `PROVE_TEMPLATE` + `FORMAT_BLOCK` ([render.py:13-32](../../src/methods_graph/biolean/bench/render.py)). |
| Judge | `elaborate`, then `kernel.check`, over `MaskedFactStore` ([score.py:67-74](../../src/methods_graph/biolean/bench/score.py)). hit = accepted, the root concludes the goal, and no `sorry` is used ([score.py:97-98](../../src/methods_graph/biolean/bench/score.py)). |
| Release | `go-basic.obo` is `releases/2026-07-26`. `goa_human.gaf.gz` was generated 2026-05-21T08:10 against GO `releases/2026-04-27`. The OBO is three months newer than the GO release the GAF was built on (**release skew**). |
| Snapshot origin | `snapshots/go` has no `snapshot.json`, so `mg biolean fetch` did not produce it (`mg` here means `.venv/bin/python -m methods_graph.cli`; see [Reproduce](#reproduce)). That command writes one and pins the OBO to the GAF's release ([fetch.py:828-839](../../src/methods_graph/fetch.py)). |
| Baselines | On the same 500 items: `gold:` (the prover, the ceiling), `modal:` (the gene-blind prior, the bar to beat) and `random:0` (the floor). |

### Files

| File | Git state | Size | sha256 (first 12) | Contents |
|---|---|---|---|---|
| `opus.jsonl` | untracked, repo root | 1,058,083 B | `f94066ca626c` | 500 rows, the only copy of the paid run |
| `modal.jsonl` | untracked, repo root | 929,184 B | `db33e281b7e3` | 500 rows, byte-identical to a fresh `modal:` run |
| `opus.partial.jsonl` | untracked, repo root | 386,009 B | — | a backup of the first 180 rows, a byte-identical prefix of `opus.jsonl` (redundant) |
| `biolean-bench/` | gitignored (`.gitignore:19`) | — | `items/prove.json` `c188887b2a28` | frozen items; a fresh `bench build` reproduced all four files byte for byte in 38.7 s on 2026-09-22 |
| `snapshots/go/` | gitignored (`.gitignore:11`) | — | — | the store; `score` and `run` refuse any other release pair |

**Open:** whether to commit or archive `opus.jsonl`. Deleting it loses a paid run that cannot be reproduced. See [BACKLOG](../BACKLOG.md).

### What is not recorded

Each row carries the item id, the adapter spec string, `items_manifest` (only `release` and `since`), the raw reply and the scores. The rows and the repo do **not** record:

- the CLI flags, the worker count or the git commit
- the `claude` CLI version, or the model id the CLI resolved `claude-opus-5` to
- per-row timestamps, token counts or cost
- the system prompt text

At 6b28222 the repo mentions the run only as the example command at README.md:160. The uncommitted 2026-09-22 working tree adds a short result paragraph to the root README's Biolean section, plus this doc set.

The log of the session that launched the run gives a partial reconstruction. It is local to the machine and not in the repo, so treat it as secondary evidence:

| Segment | Rows | How it ran | Code |
|---|---|---|---|
| 1 | first 180 items in id order | sequential (`--workers` did not exist yet). Started about 19:32 PDT (UTC-7) and stopped with Ctrl-C at about 20:16 PDT | main at 894072d (the closed-book adapter, merged 19:23:37) |
| 2 | the other 320 | `--resume --workers 8`: 8 concurrent `claude -p` processes were observed from about 20:24 PDT. `opus.jsonl` was last written at 20:32:57 | the unmerged `feat/bench-workers` worktree through `PYTHONPATH`, at or near 4c2e3b9 (20:07:19). The review fixes ad992e8..948ba7d landed after the run |

**Why the missing commit does not change the numbers:** `git diff --stat 894072d 6b28222` touches only `run.py`, `cli.py`, `README.md` and tests. `adapters.py`, `render.py`, `score.py` and `kernel.py` are identical across that window. So both segments sent the same prompts through the same adapter, and rescoring on main reproduces every row. The same session log shows a one-off check after the run: the CLI's init and billing records reported `claude-opus-5`.

## Integrity

| Check | opus.jsonl | modal.jsonl |
|---|---|---|
| rows / unique items | 500 / 500 | 500 / 500 |
| item set == the 500 prove items | yes | yes |
| rows in item-id order | yes | yes |
| model | claude:claude-opus-5 | modal: |
| distinct `items_manifest` / equals biolean-bench's | 1 / yes | 1 / yes |
| rows whose goal/hidden/hidden_classes/gold_depth differ from the items | 0 | 0 |
| rows that differ after rescoring on main | 0 (byte-identical file) | 0 |
| n_errors / n_unparsed / n_checked | 0 / 3 / 497 | 0 / 0 / 500 |
| release mismatch (items vs store) | none | none |
| other | `opus.partial.jsonl` (180 lines) is a byte-identical prefix | equals a fresh `modal:` run, 0/500 rows differ |

`items_manifest` holds only `release` and `since`, so matching it is a weak check. The strong checks are item-set equality and the per-row match of goal and hidden rows against the item file.

## Headline (strict kernel, same 500 prove items)

| Contestant | n | Hits | Hit rate | 95% Wilson | Accepted | hit_with_sorry | Unparsed | Mean depth of hits |
|---|---|---|---|---|---|---|---|---|
| gold: | 500 | 500 | 1.000 | 0.992-1.000 | 500 | 0 | 0 | 1.528 |
| modal: | 500 | 264 | 0.528 | 0.484-0.571 | 264 | 0 | 0 | 1.443 |
| **opus (claude:claude-opus-5)** | 500 | **205** | **0.410** | **0.368-0.454** | 217 | 12 | 3 | 1.351 |
| random:0 | 500 | 26 | 0.052 | 0.036-0.075 | 26 | 0 | 0 | 1.615 |

- Accepted 217 = 205 hits + 12 hit_with_sorry. No accepted row missed the goal, and `n_goal_rewritten` is 0.
- The modal, gold and random:0 figures match the spec's stated measurement: 52.8% / 100% / 5.2% (`docs/superpowers/specs/2026-09-21-biolean-design.md:652-654`; lines 629-631 at 6b28222).

## Head-to-head: Opus vs modal (strict)

| Both hit | Opus only | Modal only | Neither | Exact McNemar p |
|---|---|---|---|---|
| 142 | 63 | 122 | 173 | 1.7e-5 |

The p-value is a two-sided exact binomial test on the 185 discordant items (63 vs 122).

## By gold depth (strict; hits in parentheses)

| Gold depth | n | gold | modal | opus | random:0 |
|---|---|---|---|---|---|
| 1 | 315 | 1.000 | 0.622 (196) | 0.540 (170) | 0.057 (18) |
| 2 | 124 | 1.000 | 0.468 (58) | 0.202 (25) | 0.040 (5) |
| 3 | 47 | 1.000 | 0.128 (6) | 0.213 (10) | 0.021 (1) |
| 4+ | 14 | 1.000 | 0.286 (4) | 0.000 (0) | 0.143 (2) |

- The gold_depth histogram is 1: 315, 2: 124, 3: 47, 4: 10, 5: 4. The 4+ bucket holds only 14 items.
- No Opus hit is shorter than gold, which is the prover's shortest derivation. 183 hits have the same depth and 22 are longer.

## By evidence class of the hidden rows (strict)

| Class | n | modal | opus | random:0 |
|---|---|---|---|---|
| experimental | 480 | 0.525 | 0.408 | 0.052 |
| electronic | 224 | 0.612 | 0.415 | 0.040 |
| author_statement | 61 | 0.607 | 0.328 | 0.033 |
| phylogenetic | 43 | 0.488 | 0.465 | 0.116 |
| high_throughput | 34 | 0.529 | 0.294 | 0.059 |
| computational | 29 | 0.655 | 0.483 | 0.034 |
| curatorial | 1 | 0.000 | 0.000 | 0.000 |

- gold scores 1.000 in every class.
- An item counts under every class among its hidden rows, so the buckets overlap: n sums to 872 over 500 items.
- Classes outside the population (such as electronic) appear because hiding covers every row at the triple, whatever its evidence code.

## error_items

Error items are the items whose error codes contain the code, out of 500. Error occurrences count every error record, and a step can carry several. Their denominator is the total number of records, 388 for Opus ([score.py:180-194](../../src/methods_graph/biolean/bench/score.py)).

| Code | Opus items | Opus occurrences | Modal items |
|---|---|---|---|
| EDGE_NOT_FOUND | 172 | 187 | 0 |
| AXIOM_NOT_FOUND | 153 | 153 | 236 |
| OBSOLETE_TERM | 15 | 40 | 0 |
| UNPARSED | 3 | 3 | 0 |
| CONCLUSION_MISMATCH | 2 | 2 | 0 |
| UNKNOWN_TERM | 1 | 2 | 0 |
| SORRY_MALFORMED | 1 | 1 | 0 |

- Modal can only fail with AXIOM_NOT_FOUND. It computes its path from the store, so it cannot make a structure error.
- random:0 fails only with ROOT_MISMATCH (474 items).

## Where Opus's 295 strict misses come from

| Bucket | Items |
|---|---|
| rejected, edge errors only | 114 |
| rejected, axiom errors only | 93 |
| rejected, axiom + edge | 54 |
| rejected, other codes only (9 OBSOLETE_TERM, 1 CONCLUSION_MISMATCH, 1 UNKNOWN_TERM) | 11 |
| rejected, axiom + other | 4 |
| rejected, axiom + edge + other | 2 |
| rejected, edge + other | 2 |
| accepted, but a `sorry` sits on the chain (hit_with_sorry) | 12 |
| unparsed (attempted QuickGO tool calls) | 3 |
| **total misses** | **295** |

Kernel rejections total 280: every row above except the hit_with_sorry and unparsed rows.

## EDGE_NOT_FOUND sub-kinds (occurrences)

| Sub-kind | Opus | Modal |
|---|---|---|
| shortcut: true ancestor, and the cited relation matches the composed path | 105 | 0 |
| not an ancestor at all | 49 | 0 |
| relation swapped on a real direct edge (19 cite is_a where GO has part_of, 5 the reverse) | 24 | 0 |
| self edge `[X, X]` after elaboration: the cited child is an alt_id of the cited parent | 7 | 0 |
| reversed (the cited parent is a direct child) | 1 | 0 |
| shortcut: true ancestor, but cites is_a where only a part_of-composed path exists | 1 | 0 |
| **total** | **187** | **0** |

- **The 106 shortcut steps skip few terms.** By shortest-path length: 2 edges 98, 3 edges 5, 4 edges 2, 5 edges 1. By cited rule over the path's label: is_a over is_a 60, part_of over part_of 45, is_a over part_of 1.
- **Example:** IPO5 (UniProtKB:O00410) located_in membrane. Opus cites `is_a GO:0031965 nuclear membrane -> GO:0016020 membrane`. GO has nuclear membrane is_a organelle membrane (GO:0031090) is_a membrane.
- **No shortcut crosses an obsolete term.** None of the 10,248 obsolete terms has any edge.
- **Self edges are not in the replies.** No reply cites `[X, X]`. Each of the 7 cites an edge from a GO id that this OBO lists as an alt_id of the parent, for example `is_a [GO:0017137, GO:0031267]`. The elaborator rewrites the alt_id to its primary (`ALT_ID_RESOLVED`), both ends become `GO:0031267`, and the step fails `EDGE_NOT_FOUND`. 5 of the 7 end at GO:0031267, in protein-binding goals, and in 3 of the 7 rows this is the only error. **Inference, not verified:** the model cites an edge from a GO release in which the child was still a separate term, so this is release drift. Open as [BACKLOG](../BACKLOG.md) B15.
- **Composition used:** is_a∘is_a = is_a, and any path with a part_of = part_of.

## AXIOM_NOT_FOUND sub-kinds (occurrences)

| Sub-kind | Opus | Modal |
|---|---|---|
| below the goal; the gene has no visible annotation at or around the term | 78 | 184 |
| below the goal; the gene is annotated at a MORE specific term under it (cited too general) | 26 | 31 |
| below the goal; the gene is annotated only at a LESS specific term between it and the goal | 23 | 4 |
| right term, other qualifier | 13 | 3 |
| term not below the goal | 8 | 0 |
| cited the hidden goal fact itself | 5 | 14 |
| **total** | **153** | **236** |

- **How a citation is classified:** the first test that matches, in this order:
  1. A code or reference filter on the step excluded a real annotation.
  2. It is the goal itself.
  3. It is another hidden row.
  4. It is negated, or has a different subject or taxon.
  5. The gene has the same term under another qualifier.
  6. The term is not below the goal (above it, or unrelated).
  7. The term is below the goal and the gene has a same-qualifier annotation more specific than the term.
  8. The term is below the goal and the gene has such an annotation only between the term and the goal.
  9. None of the above.
- **Buckets with no rows:** tests 1, 3 and 4 matched no citation for either contestant, and no citation was above the goal.
- **Open (same question at the axiom end):** the 26 Opus and 31 modal "cited too general" axioms are true, derivable facts. The axiom rule still demands the exact recorded term.

## What this does and does not show

**It shows (fact):** closed-book Opus 5 falls below the gene-blind modal prior on the benchmark as built: 205 vs 264, p = 1.7e-5. "As built" means the strict kernel and the direct asserted edges of go-basic 2026-07-26.

**It does not show that Opus knows less gene biology than a frequency table.** The spec reads a score below modal as "knows GO's shape, not the gene" (`docs/superpowers/specs/2026-09-21-biolean-design.md:654-655, :932-933`; lines 631-632 and 909-910 at 6b28222). That reading does not fit this run.

- **The direct-edge rule:**
  - The kernel accepts an is_a/part_of step only when the store holds that exact direct edge ([kernel.py:304-313](../../src/methods_graph/biolean/kernel.py)). The prompt never says the edge must be direct or asserted. It says a step "lifts the premise along an is_a edge" ([render.py:20](../../src/methods_graph/biolean/bench/render.py)).
  - The table below rescores the same rows under two counterfactual rules. They were computed with a wrapper store outside the repo's tracked code; the scripts are under [Reproduce](#reproduce).

  | Regime | Opus | Modal | Opus vs modal (both / Opus only / modal only / neither) | Exact McNemar p |
  |---|---|---|---|---|
  | strict (current kernel) | 205 (0.410) | 264 (0.528) | 142 / 63 / 122 / 173 | 1.7e-5 |
  | relation-aware transitive step | 269 (0.538) | 264 (0.528) | 184 / 85 / 80 / 151 | 0.76 |
  | relation-blind transitive step | 287 (0.574) | 264 (0.528) | 198 / 89 / 66 / 147 | 0.077 |
  | biology only (see below) | 305 (0.610) | 264 (0.528) | 204 / 101 / 60 / 135 | 0.0015 |

  - Under both transitive rules, gold (500), modal (264) and random:0 (26) do not change, and no Opus row goes from hit to miss. The relation-aware rule turns 64 Opus misses into hits and the relation-blind rule turns 82.
  - "Biology only" ignores structure. It counts a row when the bottom axiom of the used chain is a visible annotation of the gene, with the goal's qualifier and taxon, strictly below the goal. It is an upper bound, not a score: random:0 reaches 178 on it because it draws its start from the gene's real annotations. 100 of Opus's strict misses pass it.
  - On this measure Opus beats modal. **Inference:** Opus's deficit is GO-structure recall. The fact behind it: 172 items carry EDGE_NOT_FOUND, against 0 for modal.
  - **Open:** strict, relation-aware, relation-blind, or keep the kernel strict and report an expanded rate beside the strict one. The [decision memo](../decisions/2026-09-22-biolean-transitive-edges.md) sets out the options, their cost, and the 3 tests that pin the strict rule.
- **The depth collapse is mostly the same rule.**
  - Under the relation-aware rule, Opus scores 184/315 (0.584) at depth 1, 58/124 (0.468) at 2, 24/47 (0.511) at 3 and 3/14 (0.214) at 4+. The strict figures are 0.540 / 0.202 / 0.213 / 0.000.
  - Depth 4+ has 14 items, too few to read.
  - **Open:** if a transitive rule is adopted, the per-row `depth` ([score.py:103](../../src/methods_graph/biolean/bench/score.py)) stops being comparable to `gold_depth`.
- **The closed-book question is not settled.**
  - The 3 unparsed replies are Bash/curl calls to EBI QuickGO, written into the reply text. They are rows 84, 354 and 494, so segment 1 produced one and segment 2 produced two:
    - `prove/UniProtKB:P05026/located_in/GO:0031090`
    - `prove/UniProtKB:Q92466/involved_in/GO:0034644`
    - `prove/UniProtKB:Q9Y619/enables/GO:0015297`
  - Two of the replies end with "Failed to run command: ETIMEDOUT" and "Command running in background (ID: 2b6df5), check status with BashOutput." All 3 score as UNPARSED misses.
  - **Facts:** `--tools ""` removes Bash, and 128a8c6 verified live that tools and MCP servers were both empty (`tools []`, `mcp_servers []`). No parsed row contains "curl" or "http".
  - **Inference, not verified:** with no tools available, the model wrote tool-call markup as text, and the "output" lines are its own.
  - **Open:** a row keeps only the final text, so the data cannot rule out silent retrieval in other rows.
- **Release skew is a confound for obsolete-term and not-an-ancestor errors.**
  - The OBO (2026-07-26) is newer than the GO release the GAF used (2026-04-27), and the model's training data is older than both.
  - Opus cited obsolete terms 40 times in 15 items, and 9 items fail on OBSOLETE_TERM alone. 10 distinct terms are involved; the most cited are:
    - GO:0031226 obsolete intrinsic component of plasma membrane (9)
    - GO:0005615 obsolete extracellular space, replaced by GO:0005576 (8)
    - GO:0016458 obsolete gene silencing (6)
  - Rewriting each obsolete id to its single `replaced_by` gains 0 hits under the strict and relation-aware rules (12 rows rewritten). So the obsolete ids are not what stands between those rows and a hit.
  - Some of the 49 not-an-ancestor edges may be valid in an older GO release. This cannot be checked offline, because no older OBO is on disk.
  - **Open:** should the benchmark be rebuilt on the pinned pair that `mg biolean fetch` would produce (network needed)? That invalidates the frozen items and both result files through the release check.
- **hit_with_sorry: 12 rows (2.4%).**
  - Each one reaches the goal from a `sorry` as its bottom premise. In 10 of the 12, the provenance `method` string says the annotation was not verified, for example "GAF annotation lookup (unverified in this session; no GO/GOA data source available)". The other 2 are bare labels (`annotation_lookup`, `curated-annotation-lookup`).
  - These rows are not hits by definition ([score.py:97](../../src/methods_graph/biolean/bench/score.py)). Counting them gives 217/500 (43.4%), still below modal.
  - **Open:** whether to show `hit_with_sorry_rate` (0.024, already in the summary) next to the headline.
- **Other limits:**
  - One sample per item and no temperature control, so run-to-run variance is unmeasured.
  - The contestant is Opus 5 inside Claude Code's headless CLI with that CLI's system prompt, not a raw API call.
  - `since` is null, so there is no live cut and contamination is not controlled: GOA is in training data (spec, Risks). Only 44 of the 500 items have `cut_date` >= 2026-01-01.

## Reproduce

None of the commands below needs the network or costs money. Run them from the repo root.

```bash
alias mg='.venv/bin/python -m methods_graph.cli'   # a bare `mg` on macOS is /usr/bin/mg, an unrelated editor
export OUT=/tmp/biolean-repro && mkdir -p "$OUT"
```

| Numbers | Command | Needs |
|---|---|---|
| hit rate, acceptance, hit_with_sorry rate, mean depth, rates by depth and by class, error_items / error_occurrences | `mg biolean bench score --results opus.jsonl 2>/dev/null \| jq .prove` (and the same for `modal.jsonl`) | the result file and `snapshots/go` with the exact release pair; about 20 s |
| rows reproduce | `mg biolean bench score --results opus.jsonl --out "$OUT/opus.rescored.jsonl" >/dev/null && cmp "$OUT/opus.rescored.jsonl" opus.jsonl` | same |
| baselines | `mg biolean bench run --model gold: --track prove --out "$OUT/gold.jsonl"`, then `mg biolean bench run --model random:0 --track prove --out "$OUT/random0.jsonl"`, then `mg biolean bench run --model modal: --track prove --out "$OUT/modal.jsonl" && cmp "$OUT/modal.jsonl" modal.jsonl`. Without `--track prove` a baseline refuses to run ([baselines.py:174-177](../../src/methods_graph/biolean/bench/baselines.py)) | `biolean-bench/` and `snapshots/go`; about 15-30 s each |
| items rebuild | `mg biolean bench build --out "$OUT/bb"`, then `cmp` each of the four files against `biolean-bench/` | `snapshots/go`; about 40 s |
| partial prefix | `head -n 180 opus.jsonl \| cmp - opus.partial.jsonl` | the files |
| the 3 unparsed replies | `jq -r 'select(.parsed == false) \| .item, .raw' opus.jsonl` | the file |
| integrity, Wilson CIs, head-to-head and McNemar, hits by depth, hit depth vs gold, miss buckets | script A below (stdlib only) | the result files, the baseline runs in `$OUT`, `biolean-bench/items/prove.json` |
| EDGE_NOT_FOUND sub-kinds, relation-aware and relation-blind rescoring, biology-only measure | script B below | the above plus `snapshots/go`; about 20 s |
| AXIOM_NOT_FOUND sub-kinds, obsolete-term counts and the `replaced_by` what-if, the finer EDGE_NOT_FOUND splits (swap direction, shortcut path lengths, cited rule by path label, self-edge terms, the IPO5 example), relation-aware hits by depth, the 3 tests that pin the strict rule | custom analysis; its scripts are not in the repo. On 2026-09-22 a separate script re-derived every one of these numbers, and re-running the survey's in-memory transitive patch over `tests/test_biolean_kernel.py` and `tests/test_biolean_render.py` failed exactly those 3 tests. The definitions are above and in the [decision memo](../decisions/2026-09-22-biolean-transitive-edges.md) | `snapshots/go` |

- `score` opens `data/methods.kuzu` when it exists, although prove rows never use it. Pass `--db /nonexistent` to skip it.
- `score` prints its `load_report` line to stderr ([cli.py:1354](../../src/methods_graph/cli.py)), which is why `2>/dev/null` leaves clean JSON for `jq`.

**The paid command** is `mg biolean bench run --model claude:claude-opus-5 --track prove --workers 8 --resume --out opus.jsonl`. It needs the network and an authenticated `claude` CLI. On the complete `opus.jsonl`, `--resume` keeps all 500 error-free rows and makes no calls ([cli.py:1388-1398](../../src/methods_graph/cli.py)). **Never run it without `--resume` against `opus.jsonl`:** it then opens `--out` with `"w"`, truncates the only copy ([cli.py:1416](../../src/methods_graph/cli.py)), and pays for 500 new calls.

<details>
<summary>Script A: integrity, Wilson CIs, head-to-head, depth, miss buckets (stdlib only)</summary>

```bash
.venv/bin/python - <<'EOF'
# Integrity, Wilson CIs, head-to-head + exact McNemar, hits by gold depth, miss buckets. Stdlib only.
import json, math, os
from collections import Counter
from math import comb
OUT = os.environ["OUT"]
def load(p): return {r["item"]: r for r in map(json.loads, open(p))}
R = {"gold": load(f"{OUT}/gold.jsonl"), "modal": load("modal.jsonl"),
     "opus": load("opus.jsonl"), "random:0": load(f"{OUT}/random0.jsonl")}
items = {i["id"]: i for i in json.load(open("biolean-bench/items/prove.json"))}
for k in ("opus", "modal"):
    lines = [json.loads(line) for line in open(f"{k}.jsonl")]
    ids = [r["item"] for r in lines]
    print(k, "rows", len(lines), "unique", len(set(ids)), "== prove items", set(ids) == set(items),
          "in id order", ids == sorted(ids), "models", sorted({r["model"] for r in lines}),
          "items_manifest values", len({json.dumps(r["items_manifest"], sort_keys=True) for r in lines}),
          "rows differing from items", sum(any(r[f] != items[r["item"]][f] for f in
              ("goal", "hidden", "hidden_classes", "gold_depth")) for r in lines),
          "errors", sum(r["error"] is not None for r in lines))
def wilson(k, n, z=1.959963984540054):
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{c - h:.3f}-{c + h:.3f}"
def mcnemar(b, c):  # exact two-sided binomial test on the discordant pairs
    return min(1.0, 2 * sum(comb(b + c, i) for i in range(min(b, c) + 1)) / 2 ** (b + c))
def hit(r): return r["hit"] is True
for k, rows in R.items():
    n, h = len(rows), sum(map(hit, rows.values()))
    print(k, f"hits {h}/{n}", "wilson", wilson(h, n),
          "accepted", sum(r["accepted"] is True for r in rows.values()),
          "hit_with_sorry", sum(r["hit_with_sorry"] is True for r in rows.values()),
          "unparsed", sum(r["parsed"] is False for r in rows.values()))
o, m = R["opus"], R["modal"]
both = sum(hit(o[i]) and hit(m[i]) for i in o)
b = sum(hit(o[i]) and not hit(m[i]) for i in o)
c = sum(hit(m[i]) and not hit(o[i]) for i in o)
print("opus vs modal: both", both, "opus only", b, "modal only", c,
      "neither", len(o) - both - b - c, "exact McNemar p", f"{mcnemar(b, c):.2g}")
def bucket(d): return str(d) if d < 4 else "4+"
for k, rows in R.items():
    n, h = Counter(), Counter()
    for r in rows.values():
        n[bucket(r["gold_depth"])] += 1
        h[bucket(r["gold_depth"])] += hit(r)
    print(k, "hits/n by gold depth:", {d: f"{h[d]}/{n[d]}" for d in sorted(n)})
print("opus hit depth vs gold_depth:", dict(Counter(
    "equal" if r["depth"] == r["gold_depth"] else "longer" if r["depth"] > r["gold_depth"]
    else "shorter" for r in o.values() if hit(r))))
def family(codes):
    return "+".join(sorted({"edge" if x == "EDGE_NOT_FOUND" else "axiom" if x == "AXIOM_NOT_FOUND"
                            else "other" for x in codes}))
misses = Counter("unparsed" if not r["parsed"] else "hit_with_sorry" if r["hit_with_sorry"]
                 else "rejected: " + family(r["error_codes"]) for r in o.values() if not hit(r))
print("opus misses", sum(misses.values()), dict(sorted(misses.items())))
print("opus rejected rows by exact code set:", dict(Counter(
    ",".join(sorted(set(r["error_codes"]))) for r in o.values() if r["parsed"] and not r["accepted"])))
EOF
```

</details>

<details>
<summary>Script B: EDGE_NOT_FOUND sub-kinds, transitive-rule rescoring, biology-only measure</summary>

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'EOF'
# EDGE_NOT_FOUND sub-kinds, the two transitive-rule rescorings, the biology-only measure.
# Needs snapshots/go and biolean-bench/. Uses score.py's private _checked(). About 20 s.
import json, os
from collections import Counter, deque
from math import comb
from pathlib import Path
from methods_graph.biolean.bench.items import load_items
from methods_graph.biolean.bench.render import parse_reply
from methods_graph.biolean.bench.score import _checked, score_prove
from methods_graph.biolean.elaborate import elaborate
from methods_graph.biolean.kernel import ancestors, descendants, propagating_parents
from methods_graph.biolean.props import Edge, Prop
from methods_graph.biolean.store import MaskedFactStore, load_store
OUT = os.environ["OUT"]
store, _ = load_store(Path("snapshots/go"))
items = {i["id"]: i for i in load_items(Path("biolean-bench"))[0] if i["track"] == "prove"}
paths = {"opus": "opus.jsonl", "modal": "modal.jsonl",
         "gold": f"{OUT}/gold.jsonl", "random:0": f"{OUT}/random0.jsonl"}
rows = {k: [json.loads(line) for line in open(p)] for k, p in paths.items()}
def p_exact(b, c): return min(1.0, 2 * sum(comb(b + c, i) for i in range(min(b, c) + 1)) / 2 ** (b + c))
def h2h(o, m):
    b = sum(o[i] and not m[i] for i in o); c = sum(m[i] and not o[i] for i in o)
    return dict(both=sum(o[i] and m[i] for i in o), opus_only=b, modal_only=c, p=f"{p_exact(b, c):.2g}")

_labels = {}
def labels(child):  # ancestor -> composed path labels: is_a.is_a = is_a, any part_of = part_of
    if child not in _labels:
        out, seen, q = {}, {(child, "is_a")}, deque([(child, "is_a")])
        while q:
            cur, lab = q.popleft()
            for par, rel in propagating_parents(cur, store):
                nl = "part_of" if "part_of" in (lab, rel) else "is_a"
                out.setdefault(par, set()).add(nl)
                if (par, nl) not in seen:
                    seen.add((par, nl)); q.append((par, nl))
        _labels[child] = out
    return _labels[child]

kinds = Counter()
for r in rows["opus"]:
    if not r["parsed"] or r["accepted"]:
        continue
    _canon, verdict, _root, _goal = _checked(items[r["item"]], parse_reply(r["raw"]), store)
    for e in verdict["errors"]:
        if e["code"] != "EDGE_NOT_FOUND":
            continue
        c, rel, p = (e["expected"][k] for k in ("child", "relation", "parent"))
        if c == p: k = "self edge"
        elif any(pp == p for pp, _ in propagating_parents(c, store)): k = "relation swapped"
        elif any(pp == c for pp, _ in propagating_parents(p, store)): k = "reversed"
        elif p in ancestors(c, store):
            k = "shortcut, label matches" if rel in labels(c)[p] else "shortcut, label mismatch"
        else: k = "not an ancestor"
        kinds[k] += 1
print("opus EDGE_NOT_FOUND sub-kinds:", dict(kinds), "total", sum(kinds.values()))

class Transitive:  # parents() also returns every ancestor, labelled (aware) or both labels (blind)
    def __init__(self, base, blind): self.base, self.blind, self.cache = base, blind, {}
    def __getattr__(self, name): return getattr(self.base, name)
    def parents(self, t):
        if t not in self.cache:
            direct = tuple(self.base.parents(t)); have = {(e.relation, e.parent) for e in direct}
            extra = [Edge(t, lab, anc) for anc, labs in sorted(labels(t).items())
                     for lab in (("is_a", "part_of") if self.blind else sorted(labs))
                     if (lab, anc) not in have] if self.base.term(t) else []
            self.cache[t] = direct + tuple(extra)
        return self.cache[t]

strict = {k: {r["item"]: r["hit"] is True for r in v} for k, v in rows.items()}
print("strict", {k: sum(v.values()) for k, v in strict.items()}, h2h(strict["opus"], strict["modal"]))
for name, blind in (("relation-aware", False), ("relation-blind", True)):
    st = Transitive(store, blind)
    hits = {k: {r["item"]: score_prove(items[r["item"]], r["raw"], st)["hit"] is True for r in v}
            for k, v in rows.items()}
    o = hits["opus"]
    print(name, {k: sum(v.values()) for k, v in hits.items()}, h2h(o, hits["modal"]),
          "opus miss->hit", sum(o[i] and not strict["opus"][i] for i in o),
          "hit->miss", sum(strict["opus"][i] and not o[i] for i in o))

def biology_ok(r):  # the used chain's bottom axiom is a visible annotation strictly below the goal
    if r["error"] is not None or not r["parsed"]: return False
    item = items[r["item"]]; goal = Prop.from_dict(item["goal"])
    masked = MaskedFactStore(store, frozenset(item["hidden"]))
    canon, _ = elaborate(parse_reply(r["raw"]), masked)
    steps = canon.get("steps") if isinstance(canon, dict) else None
    if not isinstance(steps, list): return False
    by_id = {s.get("id"): s for s in steps if isinstance(s, dict)}
    cur, seen = by_id.get(canon.get("root")), set()
    while cur is not None and cur.get("premises") and cur.get("id") not in seen:
        seen.add(cur.get("id")); prem = cur["premises"]
        cur = by_id.get(prem[0]) if isinstance(prem, list) and prem else None
    if cur is None or cur.get("rule") != "axiom": return False
    a = Prop.from_dict(cur.get("conclusion"))
    if a is None or a.negated or (a.subject, a.qualifier, a.taxon) != (goal.subject, goal.qualifier, goal.taxon):
        return False
    return bool(masked.matching(a)) and a.term in set(descendants(goal.term, store))
bio = {k: {r["item"]: biology_ok(r) for r in v} for k, v in rows.items()}
print("biology-only", {k: sum(v.values()) for k, v in bio.items()}, h2h(bio["opus"], bio["modal"]),
      "opus strict misses that pass it", sum(bio["opus"][i] and not strict["opus"][i] for i in bio["opus"]))
EOF
```

</details>

Both scripts were run verbatim on 2026-09-22 against the files above. Every number they print matches this document. They do not print the numbers that the table above assigns to custom analysis. They are not tracked code, so if you want them kept and tested, move them into the repo; that is a [BACKLOG](../BACKLOG.md) item.
