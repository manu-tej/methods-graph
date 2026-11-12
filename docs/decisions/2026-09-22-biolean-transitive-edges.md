# Decision memo: transitive `is_a`/`part_of` steps in Biolean (O-01)

**What this is:** the memo for open decision O-01. Should Biolean accept a propagation step that skips intermediate GO terms? It gives the evidence, four options, a non-binding recommendation, and a checklist for each option.
**Status as of 2026-09-22:** **OPEN. The owner has not decided.** The kernel is strict today. Nothing in the repo implements options B, C or D, and no repo command produces the non-strict numbers below; the [appendix](#appendix-reproducing-the-numbers) has a read-only snippet that does.
**Read next:** [the Opus 5 results](../biolean/results-2026-09-22-opus-5.md), then [the kernel rules](../biolean/README.md). Related decisions are in [the decision log](README.md).

Labels used below: **[fact]** means checked against code or data, with the source given. **[analysis]** means Claude's reasoning. **[open]** means not decided. Commands use `mg`, which here means `alias mg='.venv/bin/python -m methods_graph.cli'` (see [../README.md](../README.md#running-the-cli); on macOS a bare `mg` is an unrelated editor). Tags: [GO] needs `snapshots/go/`, [items] needs `biolean-bench/`, and [paid] costs model calls.

**Line numbers** are at commit `6b28222`. `spec:N` means `docs/superpowers/specs/2026-09-21-biolean-design.md` line N, and `plan-2:N` means `docs/superpowers/plans/2026-09-22-biolean-plan-2-benchmark.md` line N. A status banner was added to the top of each spec and plan on 2026-09-22, so in the working tree those lines sit lower. To read the cited lines: `git show 6b28222:docs/superpowers/specs/2026-09-21-biolean-design.md | sed -n 269,270p`. Code and test line numbers are unaffected.

## 1. The question

The kernel accepts an `is_a` or `part_of` step only when `go-basic.obo` asserts that exact direct edge. A step from a term to a true ancestor two or more edges up is therefore rejected, even when every edge in between exists. Should that step count, and if it does, must the cited relation match the composed path (relation-aware) or not (relation-blind)?

## 2. Why it matters now: the rule choice flips the headline

One paid run exists: `claude:claude-opus-5`, 500 prove items, seed 0, written 2026-09-22 to the untracked `opus.jsonl`. The same 500 items were rescored under each rule. Denominator: 500 items in every row.

| Rule for an `is_a`/`part_of` step | Opus 5 hits | Rate (95% Wilson) | Opus vs modal: both / Opus only / modal only / neither | Exact McNemar p | Reading |
|---|---|---|---|---|---|
| **Strict** (kernel today) | 205 | 41.0% (36.8–45.4) | 142 / 63 / 122 / 173 | 1.7e-5 | Opus **loses** to the gene-blind baseline |
| **Relation-aware** transitive step | 269 | 53.8% (49.4–58.1) | 184 / 85 / 80 / 151 | 0.76 | **tie** |
| **Relation-blind** transitive step | 287 | 57.4% (53.0–61.7) | 198 / 89 / 66 / 147 | 0.077 | Opus ahead, not significant at 0.05 |
| *Biology only* (not a proposed rule; an upper reference) | 305 | 61.0% (56.7–65.2) | 204 / 101 / 60 / 135 | 0.0015 | Opus **wins** |

- **[fact]** Under every rule, modal scores 264/500 = 52.8% (48.4–57.1), gold 500/500 and random:0 26/500. No Opus item goes from hit to miss under either transitive rule.
- **[fact, from the 2026-09-22 analysis; re-derived the same day by an independent read-only script that is not in the repo]** "Biology only" ignores structure. It asks whether the bottom axiom of the used chain is a visible annotation of the gene, under the goal's qualifier and taxon, at a proper descendant of the goal. It bounds what any edge rule could give Opus. 100 of Opus's 295 strict misses pass it.
- **[fact]** The spec reads a score below modal as "knows GO's shape, not the gene" (`docs/superpowers/specs/2026-09-21-biolean-design.md:631`, `:909-910`). **[analysis]** This run shows the reverse. Opus's deficit is GO-structure recall: 172 of 500 Opus items carry `EDGE_NOT_FOUND`, against 0 for modal. On the gene-level part, Opus beats modal.
- Sources: for the strict row, `mg biolean bench score --results opus.jsonl` [GO] (it reads only the rows and the store, not `biolean-bench/`). For the other rows, the [appendix](#appendix-reproducing-the-numbers) snippet. The strict, relation-aware and relation-blind rows were each computed twice, by independent scripts, with identical results.

## 3. What the kernel, the spec and the prompt say today

**The kernel [fact].** `src/methods_graph/biolean/kernel.py:304-313` accepts only a direct edge of exactly the named relation:

```python
edges = store.parents(child)
if not any(e.relation == relation and e.parent == parent for e in edges):
    ... st.err(Code.EDGE_NOT_FOUND, f"no {relation} edge {child} -> {parent}", ...)
```

- The conclusion is `Prop(pp.subject, pp.qualifier, parent, pp.taxon, False)` (`kernel.py:328`). **It does not depend on the relation.**
- A trusted ancestor closure already exists. `propagating_parents` (`kernel.py:63-82`) keeps an edge only when its relation is `is_a` or `part_of` and the parent is known, live and in the same namespace. `_closure` (`kernel.py:101-110`) is a BFS over it, and `ancestors` (`kernel.py:113-115`) is that closure. Trusted code already uses it, for axiom suggestions (`kernel.py:271`) and conflicts (`kernel.py:371-374`).

**The spec [fact]** is explicit. The rules table requires "`Edge(t1, is_a, t2)` in the store" (`spec:269-270`). It also warns: "Cosmetic rejections. The kernel is exact … Watch `error_items` for a code that dominates for spelling reasons" (`spec:913-915`). `EDGE_NOT_FOUND` is Opus's most common error code.

**The prompt [fact]** never states the rule. `FORMAT_BLOCK` (`src/methods_graph/biolean/bench/render.py:19-21`) says a step "lifts the premise along an is_a edge, and rule "part_of" does the same along a part_of edge". The prove template (`render.py:29-30`) says "Derive it from an annotation to a more specific term using the rules is_a and part_of." Nothing says the edge must be direct, must be asserted, or must come from release 2026-07-26.

**Who is exposed [fact].** The gold and modal derivations are built from direct store edges (tactics `prove`; `baselines.py:94-144`), so the baselines never cite a shortcut. All 236 modal rejections are `AXIOM_NOT_FOUND`. Only a model contestant can lose points to the unstated rule.

## 4. Evidence

All counts are Opus's, on the 500-item run, unless marked otherwise.

### 4.1 What Opus's `EDGE_NOT_FOUND` errors are (187 occurrences in 172 items; modal has 0)

Composition used, the standard OBO composition for GO's propagating relations: `is_a ∘ is_a = is_a`, and any path containing a `part_of` composes to `part_of`.

| Sub-kind | Occurrences | Relation-aware | Relation-blind |
|---|---|---|---|
| Shortcut to a true ancestor; the cited relation matches the composed path | 105 | accepted | accepted |
| Shortcut to a true ancestor; cites `is_a`, but only a `part_of`-composed path exists | 1 | rejected | accepted |
| Relation swapped on a real direct edge (19 cite `is_a` where GO has `part_of`; 5 the reverse) | 24 | rejected | accepted |
| Not an ancestor at all | 49 | rejected | rejected |
| Self edge `[X, X]` after elaboration: the cited child is an alt_id of the cited parent, so `ALT_ID_RESOLVED` makes both ends equal (5 of the 7 on GO:0031267; [BACKLOG](../BACKLOG.md) B15) | 7 | rejected | rejected |
| Reversed (the cited parent is a direct child) | 1 | rejected | rejected |
| **Total** | **187** | | |

### 4.2 Shortcuts are short

| Shortest path from the cited child to the cited parent | Shortcut steps |
|---|---|
| 2 edges (one intermediate term skipped) | 98 |
| 3 edges | 5 |
| 4 edges | 2 |
| 5 edges | 1 |
| **Total** | **106** |

By cited rule and path label: `is_a` over an `is_a` path 60, `part_of` over a `part_of` path 45, `is_a` over a `part_of` path 1.

### 4.3 From steps to items

| Set | Items |
|---|---|
| Rejected items whose only errors are shortcuts (relation-blind test) | 66 |
| … of which every shortcut is relation-aware-valid | 65 |
| Relation-aware: miss becomes hit | **64**. The 65th, `prove/UniProtKB:O96006/located_in/GO:0005654`, has a `sorry` at the bottom of its chain and becomes `hit_with_sorry`. |
| Relation-blind: miss becomes hit | **82** = 64 + 16 relation-swap-only items + 1 swap-plus-shortcut + 1 `is_a`-over-`part_of` |
| Hit becomes miss, either rule | **0** |
| Shortcut steps with an obsolete endpoint | **0**. None of the 10,248 obsolete terms has any edge. |

### 4.4 Examples

These are real Opus steps, rejected today. The 2026-09-22 analysis found that, for the first three items, every error is a relation-aware-valid shortcut.

| Item (gold depth) | Goal | Cited step | Skipped terms (composed label) | Aware | Blind |
|---|---|---|---|---|---|
| IPO5, UniProtKB:O00410 (2) | located_in GO:0016020 membrane | `is_a` GO:0031965 nuclear membrane → GO:0016020 membrane | GO:0031090 organelle membrane (is_a, is_a → is_a) | accept | accept |
| PRODH, UniProtKB:O43272 (1) | located_in GO:0005739 mitochondrion | `part_of` GO:0005743 mitochondrial inner membrane → GO:0005740 mitochondrial envelope | GO:0031966 mitochondrial membrane (is_a, then part_of → part_of) | accept | accept |
| THSD4, UniProtKB:Q6ZMP0 (3) | located_in GO:0031012 extracellular matrix | `part_of` GO:0001527 microfibril → GO:0031012 extracellular matrix | GO:0071953 elastic fiber, GO:0140149, GO:0140151, GO:0005614 interstitial matrix (4 × part_of, then is_a → part_of) | accept | accept |
| **Label mismatch**: CEACAM5, UniProtKB:P06731 (1) | located_in GO:0016020 membrane | `is_a` GO:0016324 apical plasma membrane → GO:0005886 plasma membrane | only path: `is_a` GO:0098590, then `part_of` → composes to part_of | **reject** | accept |

### 4.5 Hit rate by gold depth under each rule (hits / n)

| Gold depth | n | Opus strict | Opus aware | Opus blind | Modal (every rule) | random:0 (every rule) |
|---|---|---|---|---|---|---|
| 1 | 315 | 170 (54.0%) | 184 (58.4%) | 190 (60.3%) | 196 (62.2%) | 18 (5.7%) |
| 2 | 124 | 25 (20.2%) | 58 (46.8%) | 68 (54.8%) | 58 (46.8%) | 5 (4.0%) |
| 3 | 47 | 10 (21.3%) | 24 (51.1%) | 26 (55.3%) | 6 (12.8%) | 1 (2.1%) |
| 4+ | 14 | 0 (0.0%) | 3 (21.4%) | 3 (21.4%) | 4 (28.6%) | 2 (14.3%) |

Gold is 100% in every bucket. **[analysis]** Under the strict rule Opus looks like a one-hop model. Under the relation-aware rule it beats modal at depth 3 (24 vs 6 of 47) and trails it at depth 1 (184 vs 196 of 315). The 4+ bucket (n = 14) is too small to read.

### 4.6 Tests that pin the strict rule

| Test | Location | Asserts | Fails if the kernel accepts aware shortcuts | … blind shortcuts |
|---|---|---|---|---|
| `test_edge_not_found_suggests_the_other_propagating_relation` | `tests/test_biolean_kernel.py:374` | `is_a A→C` is `EDGE_NOT_FOUND`; the fixture has `A is_a B is_a C` (and `A part_of C`) | yes | yes |
| `test_dependent_step_is_still_checked_when_premise_failed` | `tests/test_biolean_kernel.py:428` | `is_a X→T` is `EDGE_NOT_FOUND`; the fixture has `X is_a Y is_a T` | yes | yes |
| `test_render_verdict_shows_the_first_suggestion_and_elaboration` | `tests/test_biolean_render.py:35` | the `part_of` suggestion from the same `A→C` rejection | yes | yes |

- **[fact]** The other 239 of the 242 Biolean tests pass under both in-memory patches, and all 242 pass unpatched. Claude re-ran the mutation on 2026-09-22 over the kernel, render, tactics and elaborate test files (88 tests): exactly these 3 failed under each patch.
- **[fact] No existing test tells relation-aware from relation-blind:** both patches fail the same 3 tests. Adopting B needs a new test that does, for example `is_a C2→T0` over the spec fixture's mixed chain `C2 is_a C1 part_of T0` (`spec:758`), which must be rejected. The mutant for that test is the relation-blind patch.

## 5. The options

### 5.1 Soundness: all four options keep the set of provable propositions unchanged

**[fact + analysis]** Every transitive variant is *admissible*: it proves nothing new, only shorter proofs (B, C) or filled-in ones (D).

1. A propagation step's conclusion depends only on the premise and `edge[1]` (`kernel.py:328`), not on the relation named.
2. `ancestors()` walks exactly the edges a direct step accepts (`kernel.py:63-82`): relation `is_a` or `part_of`, parent known and live, same namespace.
3. So if `parent ∈ ancestors(child)`, there is a chain of direct edges from child to parent. The current kernel accepts each edge as a step with its own relation, and each concludes the same subject, qualifier and taxon at the next term. A transitive step expands into that chain. Conversely, a direct edge is a path of length 1.
4. Data check on the shipped snapshot: 0 of 10,248 obsolete terms has any edge, and 0 `is_a`/`part_of` edges cross a namespace. On all 106 shortcut pairs, the kernel's filtered closure and an unfiltered closure agree.

Consequences:
- **The relation label is a knowledge check, not a soundness condition**, because of point 1. That is why even C is sound.
- The kernel guarantee in spec §0.2 ([F-02](README.md)) holds under every option: every accepted conclusion still traces to recorded annotations and asserted edges.
- What changes between options is which *derivations* are accepted, and so what the benchmark measures. For B and C, the size of the trusted code also changes.
- `NEGATED_PREMISE` and `NAMESPACE_CROSSED` apply unchanged under every option.

### 5.2 Side by side

| | **A. Strict** (status quo, rule stated in the prompt) | **B. Relation-aware step in the kernel** | **C. Relation-blind step in the kernel** | **D. Strict kernel + untrusted expander, both rates reported** |
|---|---|---|---|---|
| Opus on the 2026-09-22 run | 205 (41.0%) | 269 (53.8%) | 287 (57.4%) | strict 205 (41.0%) and expanded 269 (53.8%), side by side. The 269 is expected, not measured: no expander exists yet. |
| Versus modal, 264 (52.8%) | loses, p = 1.7e-5 | tie, p = 0.76 | ahead, p = 0.077 | headline: tie; strict: loses |
| What the benchmark measures | biology + recall of the exact direct edges asserted in go-basic 2026-07-26 | biology + GO ancestry with the right relation type (subsumption vs parthood), however many terms are skipped | biology + knowing the target is an ancestor; the `rule` name carries no information | headline as B; strict reported as a separate GO-structure-recall metric |
| Change to `kernel.py` (518 lines today) | none | about 15 trusted lines: a labelled closure plus the edge test | a few lines: accept when `parent in ancestors(child)` | none |
| Other code | one `FORMAT_BLOCK` sentence | the same, plus kernel tests | the same, plus kernel tests | an expander module (untrusted), new row and summary fields, and tests. Size not measured. |
| Existing 242 Biolean tests | unchanged | 3 rewritten; new mutation-checked tests | 3 rewritten; new tests | unchanged; new expander tests |
| Soundness (§5.1) | unchanged | unchanged (admissible) | unchanged (admissible; label unchecked) | unchanged (the kernel is untouched and checks the expanded derivation) |
| `depth` and `mean_depth` | GO hops; comparable with `gold_depth` | cited steps, which can be fewer than hops. Plan 2 deviation 4 ([F-21](README.md)) breaks. | as B | hops of the expanded derivation; comparable |
| Errors still counted | all | swaps, non-ancestors, self, reversed | non-ancestors, self, reversed only (the 24 swapped steps are accepted) | all in the strict rate; as B in the expanded rate |
| Fits plan constraint [F-20](README.md) (the scorer only calls `elaborate` + `check`) | yes | yes | yes | **no**; record it as a deliberate deviation. The relation-label policy lives in untrusted code. |
| Prompt change | required (that is the whole option) | recommended | recommended | recommended |
| Paid re-run [paid] | yes, to get a number under the stated rule. The 41.0% stays valid as "strict, rule unstated". | not to rescore existing replies (free once implemented); yes for numbers under a reworded prompt | as B | as B |
| Spec text to change | prompt text `spec:517-531`; framing at `spec:631`, `:909-910` | rules table `spec:269-270`; `depth` at `spec:556`; the §9 kernel test table (`spec:782-815`); framing lines | as B, plus: the `rule` label is informational | scoring section §6 (`spec:536-562`); record the F-20 deviation; framing lines |

### 5.3 A: strict, with the rule stated

- **Prompt wording (proposal):** "Each is_a or part_of step must cite one edge asserted in go-basic.obo (release 2026-07-26), from a term to its direct parent. Do not skip intermediate terms."
- **[analysis]** This measures memorisation of one GO release's asserted graph on top of the biology. Release skew sharpens that ([§6.2](#62-release-skew)): the model's GO knowledge predates both files on disk.
- The existing 41.0% cannot be relabelled as an A result. It was produced under a prompt that did not state the rule.

### 5.4 B: relation-aware transitive step in the kernel

- **Implementation sketch [analysis]:** a BFS over `(term, composed label)` pairs on `propagating_parents`. Accept when the direct edge exists, or when `(parent, relation)` is in the child's labelled closure. The analysis prototype was about 15 lines. It lived in a scratchpad and is not in the repo.
- **Variant:** add new rule names (for example `is_a_path`) rather than widening `is_a`. That keeps the 3 tests, but the existing replies use `is_a`/`part_of`, so rescoring them still needs the widened meaning.
- `EDGE_NOT_FOUND` then means "not an ancestor under this composed relation". Its suggestions should offer the composed label that does hold. Today they list only direct edges (`kernel.py:307-309`).
- Trusted code grows more than under C, but the change in meaning is smaller: the relation label stays checked.

### 5.5 C: relation-blind transitive step in the kernel

- Reuses the trusted `ancestors()` closure, so the kernel change is the smallest of B and C.
- **[analysis]** The `rule` field becomes decoration. A reply that says `is_a` over a parthood path is accepted, and prose renderings of accepted derivations would repeat the wrong relation. It credits 18 more Opus items than B: the 16 swap-only items, 1 swap plus shortcut, and 1 `is_a` over a `part_of` path. In each, the model named the wrong relation.

### 5.6 D: strict kernel plus an untrusted expander

- **Where:** in `score.py`'s `_checked` (`src/methods_graph/biolean/bench/score.py:67-74`), between `elaborate` and `check`.
- **What it does:** for each `is_a`/`part_of` step whose edge is not direct but whose parent is an ancestor with a matching composed label, replace the step with the shortest such chain of direct steps. Ties break deterministically by sorted term id. New steps get fresh ids, and the last keeps the original id so later premises still resolve. Then run the unchanged kernel on the result.
- **Reporting:** report every expansion the way the elaborator reports rewrites, as a counted field in the row. Nothing is silent (invariant [F-18](README.md)).
- **Rows and summary [open]:** keep `hit` strict, so existing rows stay valid, and add expanded fields (for example `hit_expanded`, `accepted_expanded`, `depth_expanded`, `n_expanded_steps`), or do the reverse. The summary prints both rates over the same denominators and depth buckets.
- **Failure mode [analysis]:** a buggy expander can inflate the expanded rate, crediting a reply for something it did not say. It cannot produce an ACCEPTED verdict for a derivation the kernel would reject, because the kernel checks the expanded derivation.

## 6. Related decisions this one drags in

### 6.1 The same question at the axiom end (O-03)

- **[fact]** 26 Opus and 31 modal `AXIOM_NOT_FOUND` citations name a term above one the gene is really annotated at. These are exclusive buckets; a non-exclusive recount gives 27 and 32. The fact is true and derivable, but the axiom rule demands the exact recorded row (`kernel.py:281-297`).
- **[analysis]** It is not symmetric with edges. Every prove item is re-derivable from a visible annotation by construction (`src/methods_graph/biolean/bench/items.py:191-207`). An axiom rule that accepted any entailed proposition would therefore accept a constant one-step "axiom at the goal" reply on all 500 items. Any relaxation at the axiom end needs a restriction, or should only be reported as a diagnostic. It would also help modal (31) about as much as Opus (26).

### 6.2 Release skew

- **[fact]** The benchmark was built on `go-basic.obo` `releases/2026-07-26` and a GAF built against GO `releases/2026-04-27`. `snapshots/go` has no `snapshot.json`, so `mg biolean fetch` did not produce it: fetch writes that file (`src/methods_graph/fetch.py:823`) and downloads the OBO at the GAF's release (`fetch.py:832-835`).
- **[open]** Part of the 49 "not an ancestor" edges and the 40 `OBSOLETE_TERM` citations may be release drift rather than ignorance. For example, GO:0005615 "extracellular space" is obsolete in this OBO and was cited 8 times. This cannot be checked offline, because no older OBO is on disk.
- **[analysis]** A transitive rule absorbs re-parenting where the old parent is still an ancestor. The strict rule does not.
- **[fact]** Re-fetching a pinned pair changes the release identity. `bench run` and `score` then refuse the frozen items and `opus.jsonl` (exit 2). If the owner wants the pinned pair (O-02), do it before the same paid re-run, so the run is paid for once.

### 6.3 Changing `FORMAT_BLOCK` changes every prompt

- **[fact]** `FORMAT_BLOCK` ends both the prove and the hypothesize templates (`render.py:13-40`, `:59`).
- **[fact]** Rows carry no prompt version. `items_manifest` is `{release, since}` only (`src/methods_graph/biolean/bench/run.py:20-23`). `--resume` into `opus.jsonl` after a prompt change would silently mix two prompts, and `score` could not tell.
- **Before any re-run:** add a prompt version (for example a hash of the templates) to the rows, and write to a new `--out` file.

### 6.4 Depth

Under B or C, the row's `depth` (`score.py:103`, used steps minus 1) counts cited steps, not GO hops. It stops being comparable with `gold_depth`, which is what Plan 2 deviation 4 ([F-21](README.md)) promised. **[open]** Either count hops by expanding for the count only, or rename the field. The per-bucket tables keyed on the item's `gold_depth` are unaffected.

### 6.5 Smaller items

- The spec framing at `spec:631` and `spec:909-910` needs rewording under every option (see §2).
- `hit_with_sorry`: 12 Opus rows (2.4%) under the strict rule and 13 under either transitive rule. The 12 stay; the 13th is the §4.3 item with a `sorry` on its chain. Should they be shown beside the headline? **[open]**, minor.

## 7. Claude's recommendation (non-binding)

> This section is Claude's analysis. It is **not** an owner decision. O-01 stays open until the owner decides.

**Recommendation: option D, with a relation-aware expander.**
- **Headline:** the expanded relation-aware rate. For the 2026-09-22 run that is an expected 269/500 (53.8%), against modal's 264/500 (52.8%): a tie, p = 0.76.
- **Reported beside it:** the strict rate, 205/500 (41.0%), labelled "GO-structure recall: exact asserted edges, go-basic 2026-07-26".

Why:
1. **The prompt never asked for direct edges** (`render.py:19-21`, `:29-30`). The strict score mixes knowledge with guessing an unstated rule. The relation-aware rate is the fairest reading of what the prompt actually asked.
2. **D leaves trusted code untouched.** `kernel.py` and the 242 Biolean tests stay as they are, and the trusted surface stays as small as §0.2 ([F-02](README.md)) intends. The expander is untrusted in the same way the elaborator is: every rewrite is reported, and the kernel re-checks the result.
3. **Relation-aware, not blind.** It keeps the subsumption/parthood distinction, so the 24 swapped-relation citations remain errors. Blind would add 18 hits for naming the wrong relation.
4. **The strict rate is a real signal, not noise.** Opus's deficit against modal is exactly GO-structure recall: 172 items with `EDGE_NOT_FOUND`, against 0 for modal. Reported separately, the two numbers say more than either one alone.
5. **Depth stays comparable** with `gold_depth`, because the expanded derivation counts GO hops.
6. **Both numbers for the existing run cost no model calls.** They are rescored from the retained `raw` field.

Also recommended:
- **State the rule explicitly in `FORMAT_BLOCK` for future runs.** Proposed wording for D (and B): *"A step may skip intermediate GO terms. With rule "is_a", every edge on the path from child to parent must be is_a; with rule "part_of", the path must contain at least one part_of edge."*
- **Treat a paid re-run as the price of that wording change.** Add a prompt version to the rows first (§6.3). If O-02 (re-fetch) is also wanted, do both before the one re-run.

The costs of this recommendation, stated plainly:
- the expander is new code, not yet written, and its size is unmeasured;
- it is a deviation from plan constraint F-20, which must be recorded;
- every report carries two numbers that need explaining;
- the 269 is an expectation until the expander exists and is run.

## 8. After deciding: checklists

**For any option:**
- [ ] Back up `opus.jsonl` first (O-04). It is untracked, it is paid output that cannot be reproduced, and it is the only complete copy (`opus.partial.jsonl` holds only its first 180 rows). (`modal.jsonl` can be regenerated with `mg biolean bench run --model modal: --track prove --out modal.jsonl` [GO] [items].) Never re-run into `opus.jsonl`: `bench run` without `--resume` truncates `--out` (`src/methods_graph/cli.py:1416`).
- [ ] Move O-01 to Part 1 of [README.md](README.md) with the date and source, and set this memo's status line to the decision.
- [ ] Update the headline in [../biolean/results-2026-09-22-opus-5.md](../biolean/results-2026-09-22-opus-5.md) and the rule description in [../biolean/README.md](../biolean/README.md).
- [ ] Reword the "GO's shape" framing at `spec:631` and `spec:909-910`.
- [ ] If `FORMAT_BLOCK` changes: add a prompt version to the rows (`run.py:20-23`) so `--resume` and `score` refuse mixed prompts, then re-run into a **new** file: `mg biolean bench run --model claude:claude-opus-5 --track prove --workers 8 --out opus-v2.jsonl` [GO] [items] [paid] (it also needs the network).

**A. Strict:**
- [ ] Add the §5.3 sentence to `FORMAT_BLOCK` (`render.py:13-24`) and to the spec's prompt text (`spec:517-531`). Add a render test that pins the sentence; its mutation is deleting the sentence.
- [ ] Re-run Opus [paid]. Report the old 41.0% as "strict, rule unstated (prompt v1)".
- [ ] No kernel change and no kernel test change.

**B. Relation-aware in the kernel:**
- [ ] Spec §3 rules table (`spec:269-270`): the side condition becomes "a path from t1 to t2 over live, same-namespace is_a/part_of edges whose composed relation equals the rule". State the composition.
- [ ] `kernel.py` `_apply_propagation` (`kernel.py:300-331`): add the labelled closure. Update the `EDGE_NOT_FOUND` message and suggestions.
- [ ] Rewrite the 3 pinned tests (§4.6) to target a non-ancestor. Add mutation-checked tests, each with its mutant: (1) `is_a` over a part_of-composed path is rejected (mutant: relation-blind); (2) a non-ancestor is rejected (mutant: accept any parent); (3) a path through an obsolete or cross-namespace term is never used (mutant: unfiltered closure).
- [ ] Decide what `depth` reports (§6.4). Update `spec:556` and the Plan 2 deviation 4 note.
- [ ] Rescore the existing files (free). Expected: Opus 269, modal 264, gold 500, random:0 26.
- [ ] Reword `FORMAT_BLOCK` and re-run [paid] for numbers under the stated rule.

**C. Relation-blind in the kernel:**
- [ ] As B, but the side condition is `parent ∈ ancestors(child)`. The spec states that the `rule` label is informational only.
- [ ] Rewrite the 3 pinned tests. Add mutation-checked tests: (1) a non-ancestor is rejected; (2) an obsolete or cross-namespace path is never used.
- [ ] Rescore (free). Expected: Opus 287, modal 264, gold 500, random:0 26.

**D. Strict kernel + expander (the recommendation):**
- [ ] Record the expander as a deliberate deviation from F-20 (`plan-2:18`) in spec §6.
- [ ] Write the expander as an untrusted module under `src/methods_graph/biolean/bench/` and call it in `score.py` `_checked` between `elaborate` and `check`. It is relation-aware, picks paths deterministically, and reports every expansion as a counted field.
- [ ] Decide the row and summary names (§5.6). Print both rates over the same denominators and `by_gold_depth` buckets. Update the spec's row table (`spec:548-557`).
- [ ] Mutation-checked tests, each with its mutant: (1) an expander that inserts a wrong intermediate produces a kernel rejection, not a hit; (2) an expander that ignores the label must not turn the `is_a`-over-`part_of` case into a hit; (3) with the expander disabled, expanded equals strict on every row; (4) the expansion counters reconcile.
- [ ] Rescore the existing files (free). Expected: Opus 269 expanded and 205 strict; modal 264 and 264. A mismatch with 269 means the expander and this memo's store-wrapper method disagree, and needs a look.
- [ ] Reword `FORMAT_BLOCK`, add the prompt version, and re-run [paid] for future numbers.

## Appendix: reproducing the numbers

All of these run from the repo root. None needs network access or makes a paid call, and none writes to the repo.

**Strict (a repo command)** [GO], plus the untracked `opus.jsonl`; `score` reads the rows and the store, not `biolean-bench/`. About 15-20 s, most of it the store load. The store's `load_report` JSON goes to stderr, and stdout is the summary JSON alone.

```bash
mg biolean bench score --results opus.jsonl     # prove.n_hits 205, prove.hit_rate 0.41
mg biolean bench score --results modal.jsonl    # prove.n_hits 264, prove.hit_rate 0.528
```

**Relation-aware and relation-blind (not a repo command).** The snippet wraps the store so that `parents()` also returns composed edges to every propagating ancestor, then reuses the repo's own `score_prove`. The strict mode reproduces the stored rows. It needs [GO] [items] plus the untracked `opus.jsonl` and `modal.jsonl`, takes about 20 s, and is read-only.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'EOF'
import json, math
from collections import deque
from methods_graph.biolean.kernel import propagating_parents
from methods_graph.biolean.props import Edge
from methods_graph.biolean.store import load_store
from methods_graph.biolean.bench.score import score_prove

class Rule:  # parents() also returns composed edges to every propagating ancestor
    def __init__(self, base, mode): self.base, self.mode, self.memo = base, mode, {}
    def __getattr__(self, name): return getattr(self.base, name)
    def parents(self, t):
        direct = self.base.parents(t)
        if self.mode == "strict": return direct
        if t not in self.memo:
            seen, q = set(), deque(propagating_parents(t, self.base))
            while q:  # label: is_a.is_a = is_a; any part_of on the path = part_of
                node, lab = q.popleft()
                if (node, lab) in seen: continue
                seen.add((node, lab))
                for p, r in propagating_parents(node, self.base):
                    q.append((p, "is_a" if lab == r == "is_a" else "part_of"))
            labs = lambda lab: ("is_a", "part_of") if self.mode == "blind" else (lab,)
            extra = {Edge(t, l, a) for a, lab in seen for l in labs(lab)} - set(direct)
            self.memo[t] = tuple(direct) + tuple(sorted(extra, key=lambda e: (e.parent, e.relation)))
        return self.memo[t]

store, _ = load_store("snapshots/go")
items = {i["id"]: i for i in json.load(open("biolean-bench/items/prove.json"))}
rows = {n: [json.loads(l) for l in open(f"{n}.jsonl")] for n in ("opus", "modal")}
for mode in ("strict", "aware", "blind"):
    s = Rule(store, mode)
    hit = {n: {r["item"]: score_prove(items[r["item"]], r["raw"], s)["hit"] for r in rs} for n, rs in rows.items()}
    b = sum(hit["opus"][i] and not hit["modal"][i] for i in items)
    c = sum(hit["modal"][i] and not hit["opus"][i] for i in items)
    p = min(1.0, 2 * sum(math.comb(b + c, k) for k in range(min(b, c) + 1)) / 2 ** (b + c))
    print(mode, {n: sum(h.values()) for n, h in hit.items()}, "opus-only", b, "modal-only", c, f"McNemar p={p:.2g}")
EOF
```

Expected output (checked 2026-09-22):

```
strict {'opus': 205, 'modal': 264} opus-only 63 modal-only 122 McNemar p=1.7e-05
aware {'opus': 269, 'modal': 264} opus-only 85 modal-only 80 McNemar p=0.76
blind {'opus': 287, 'modal': 264} opus-only 89 modal-only 66 McNemar p=0.077
```

**Where every other number comes from:**
- **Re-verified by Claude on 2026-09-22** with independent scripts: the by-depth table (§4.5); 0 hit-to-miss; the 64 and 82 flips; the 187 `EDGE_NOT_FOUND` occurrences, split into 106 shortcuts (skip lengths 98/5/2/1), 24 swaps and 57 others; 0 obsolete endpoints; the three examples and the label-mismatch case; the 3 pinned tests.
- **From the 2026-09-22 analysis run, then re-derived by a separate fact-check the same day** (read-only scripts outside the repo): the 66/65 item reconciliation; the biology-only counts (305, 264, 178 for random:0), their 204/101/60/135 head-to-head and exact McNemar p = 0.0015, and the 100 strict misses that pass; the axiom-end split (27 and 32 non-exclusive, 26 and 31 once the one citation each that is also "right term, other qualifier" is removed).
- **Wilson intervals** were computed from the hit counts with z = 1.96.
- **The mutation check (§4.6)** is a monkeypatch of `kernel._apply_propagation` that also accepts a parent in the child's ancestor set. Run `tests/test_biolean_kernel.py` and `tests/test_biolean_render.py` under it, and exactly the 3 listed tests fail.
