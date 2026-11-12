# Decision log

**What this is:** every decision the owner has fixed (Part 1, do not reopen without a new spec) and every decision still open (Part 2, one line each with a link).
**Status as of 2026-09-22:** 23 fixed entries and 25 open. The most urgent open item is **O-01, the Biolean edge rule**: its answer flips the only Biolean headline.
**Read next:** [2026-09-22-biolean-transitive-edges.md](2026-09-22-biolean-transitive-edges.md) (the memo for O-01), then [../STATUS.md](../STATUS.md) §2 for the ranked queue.

## How to read and maintain this log

- **Format.** Every entry has the same six fields: ID, date, status, decision, rationale, source.
- **Dates** are when the decision was made (Part 1) or when the question was first raised (Part 2). Where a decision was recorded later than it was made, both dates are given.
- **Status values:**

| Status | Meaning |
|---|---|
| fixed: owner | Settled explicitly with the owner. Recorded in a spec §0, or in the owner's notes. |
| fixed: merged | A design decision in a spec, plan or commit that the owner merged to `main`. Plans require the owner for every merge (`docs/superpowers/plans/2026-09-22-biolean-plan-2-benchmark.md:24`). Reopening one needs a new spec, not a code change. |
| open | Nobody has decided. Nothing in these docs settles it. |

- **Line numbers** in specs and plans are at commit `6b28222`. `spec:N` means the Biolean spec (`docs/superpowers/specs/2026-09-21-biolean-design.md`), "seq spec" means `docs/superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md`, and `plan-2:N` means `docs/superpowers/plans/2026-09-22-biolean-plan-2-benchmark.md`. A status banner was added to the top of each spec and plan on 2026-09-22, so in the working tree those lines sit lower. Read the cited lines with `git show 6b28222:<path> | sed -n <from>,<to>p`. Code and test line numbers are unaffected.
- **"Owner's notes"** are the owner's working notes, kept outside the repo. Nothing in the repo reproduces them. [../HISTORY.md](../HISTORY.md) uses the same label.
- **"Not enforced in CI"** means the test that pins the decision is skipped in CI. It is gated on `data/methods.kuzu` or `snapshots/go/`, and CI has neither. That makes 33 skips in CI (30 need the DB, 2 need the GO snapshot, 1 needs the `quration` package).
- **When an open decision is settled:** move it to Part 1 and keep its ID. Add the date and the source (commit, spec line, or "owner, <date>"), and link the memo if there is one. Never delete an entry. Superseding one means a new entry that names the ID it replaces.

## Part 1: fixed decisions (do not reopen)

### Biolean: spec §0 (owner, 2026-09-20; recorded 2026-09-21)

The spec says: "These were settled with the owner and are not reopened by this document" (`docs/superpowers/specs/2026-09-21-biolean-design.md:10-12`, commit 86fe1ee). The owner's notes date the decisions to 2026-09-20, the day Biolean started.

| ID | Date | Status | Decision | Rationale | Source |
|---|---|---|---|---|---|
| F-01 | 2026-09-20 | fixed: owner | **Phase A now, Phase B later.** A is a typed checker for claims over existing ontologies. B verifies analyses (a pipeline run as a proof that its result is valid given the method's assumptions), with the proof discharged through the methods graph. | A needs only GO and GOA, which exist. B needs `sorry` discharge against method preconditions. | spec:14-16 |
| F-02 | 2026-09-20 | fixed: owner | **The kernel guarantees structural soundness only.** A checked claim means every step traces to a recorded fact through a declared rule, with the rule's side conditions met. It says nothing about truth: no scores, no probabilities, no belief. | Keeps the trusted guarantee small and checkable. Note: options B and C of the open O-01 would change the `is_a`/`part_of` side condition; none of the four options changes this guarantee (memo §5.1). | spec:17-19 |
| F-03 | 2026-09-20 | fixed: owner | **The library is existing ontologies, not curated here.** The v1 slice is GO (`go-basic.obo`) plus human GOA (GAF 2.2). Evidence codes are types, never weights. | Curation cost goes to zero, and the facts are external and citable. The owner's notes name slice 2 (gene to disease) sources as MONDO, HPO, Open Targets and Monarch. The spec does not. | spec:20-21 |
| F-04 | 2026-09-20 | fixed: owner | **The prover is an LLM agent.** Biolean is a checker with a JSON derivation format and errors written for a model to act on. There is no human surface syntax in v1, but there is a prose rendering of any derivation for review. | The consumer is an agent. Caveat: `render_derivation` exists but has no CLI surface (`src/methods_graph/biolean/render.py`; only tests call it). | spec:22-24 |
| F-05 | 2026-09-20 | fixed: owner | **Computed evidence is admitted as `sorry`.** v1 accepts the step structurally, records its provenance, and reports the count. Phase B discharges it. | Lets a derivation cite an analysis before Phase B exists. Caveat: an ACCEPTED verdict with a used `sorry` still exits 0, so callers must check `sorry_count`. | spec:25-27 |
| F-06 | 2026-09-20 | fixed: owner | **Success criteria.** (a) Kernel soundness proven by tests under the repo's mutation discipline, as the CI gate. (b) A leave-one-out benchmark on the same footing as the method-sequencing benchmark: gold comes from the data, and every number ships with its coverage. | Same evidence standard as the rest of the repo. Caveat: the two snapshot-gated scale tests (`tests/test_biolean_scale.py`, `tests/test_biolean_bench_scale.py`) are not enforced in CI. | spec:28-30 |
| F-07 | 2026-09-20 | fixed: owner | **Biolean lives in this repo** as `src/methods_graph/biolean/`. | Phase B needs the methods graph. | spec:31 |
| F-08 | 2026-09-21 | fixed: owner | **Two tracks.** *prove* hides only the direct annotation, so a derivation through a visible descendant exists. *hypothesize* hides the whole subtree, which makes re-derivation impossible by construction. In v1, hypothesize measures format compliance only. | This is the spec's one correction to what was agreed in conversation: subtree hiding cannot measure proving, because propagation only moves upward. | spec:33-40 |

### Methods graph and guardrail

| ID | Date | Status | Decision | Rationale | Source |
|---|---|---|---|---|---|
| F-09 | 2026-07-31 | fixed: owner | **Do not invoke the kill criterion. Redirect the graph from guardrail substrate to benchmark scoring oracle.** The criterion was "stop if recall < 10% and no real catch is logged". Guardrail recall measured exactly 0%, so the criterion was formally met, and it was deliberately not invoked. | The 905-method catalog caused every false positive as a gate. It is a better oracle than a gate. Recall was 0% on the enrichment-analysis corpus (`markziemann/SurveyEnrichmentMethods`, 1,761 rows, 1,628 after exclusions): its failure kinds (background gene set, FDR correction) cannot be written as `min_x >= n`. | Owner's notes only. Indirect repo traces: `tests/test_guardrail.py:346-351` (background-set failures in 1,364/1,628 rows) and 8477b28, which added the benchmark spec. See [../HISTORY.md](../HISTORY.md). |
| F-10 | 2026-07-30 | fixed: merged | **Operation-mediated (`AMENABLE_TO`) assumptions never gate.** Only `source=used` assumptions gate, and a diagnostic's threshold attaches only to its `applies_to_assumption`. | `AMENABLE_TO` means "a statistic runnable downstream of this tool's output", so gating the tool on it is a category error. Blockable methods went from 23 to 1 (`m:deseq2`). | 8477b28, merged in 529ffc5; `src/methods_graph/guardrail.py:96-100`; `src/methods_graph/extract/seed.py:338-353`; pinned by `tests/test_guardrail_precision.py`, which is DB-gated and **not enforced in CI** |
| F-11 | 2026-07-30 | fixed: merged | **Fail closed.** A used-path gate whose fact was not supplied returns `FACTS_REQUIRED` (exit 5), not `EVALUABLE`. Chain precedence is BLOCKED > NOT_EVALUABLE > FACTS_REQUIRED > EVALUABLE. | Not measuring must not be the cheapest route to approval. | 8477b28; `src/methods_graph/cli.py:1164-1165`; `src/methods_graph/guardrail.py:276-321` |
| F-12 | 2026-06-19 | fixed: merged | **Skills: only declared tools gate.** Only a skill's `primary_tool` and frontmatter dependencies create `Skill-WRAPS->Method` edges. Tools mined from prose are stored as `context_tools` and never gate. | A tool mentioned only in prose must not hand its gates to the skill. Before this fix, `skill:bioclaw/cell-annotation` inherited `m:scanpy`'s replicate gate from a prose mention and could BLOCK a legitimate run. | 1db3a13 "prose over-wiring" (on local `master` only; the code reached `main` in the b791d69 squash); `src/methods_graph/connectors/skills.py:24-32,151-159` |

### Method-sequencing benchmark

| ID | Date | Status | Decision | Rationale | Source |
|---|---|---|---|---|---|
| F-13 | 2026-07-30 | fixed: merged | **Two separate numbers, closed-book, graph as oracle.** Selection and sequencing are reported separately. Models answer with no methods graph in context, and the graph scores; it is not a contestant. | Measures what the model knows, not what the graph supplies. | `docs/superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md:6-14` (spec status: "approved through §3") |
| F-14 | 2026-07-30 | fixed: merged | **Gold is nf-core DAGs from `nextflow -preview -with-dag`.** `derivation: nextflow_dsl2` is required, and `io_inferred` is rejected, not downweighted. Dropped pipelines are counted with reasons. | `io_inferred` guesses order from typed I/O, which is the very reasoning being scored. | seq spec:23-49 |
| F-15 | 2026-07-31 | fixed: merged | **Sequencing is scored over gold DAG edges, never adjacent pairs. Validity uses per-step reachability.** `UNKNOWN` never counts as valid, and undefined is `None`, never `0.0`. | Parallel branches sit adjacent in any linearization, so an adjacency metric marks correct answers wrong. | 59d5111; `src/methods_graph/bench/score.py:155-254`; [../../CLAUDE.md](../../CLAUDE.md) "The benchmark". The spec's lines 96-97 still describe the old metric (stale). |
| F-16 | 2026-07-31 | fixed: merged | **Equivalence is (operation ∩ input data type) plus identity.** `op:operation_0236` and `op:operation_2495` are denylisted. The graph yields exactly 7 non-identity pairs. | Operation alone credits `bwa` for spliced alignment. The two denylisted operations bridged unrelated tools. | `src/methods_graph/bench/score.py:29-37`; the 7-pair pin `tests/test_bench_score.py:573` is DB-gated and **not enforced in CI** |

### Repo-wide

| ID | Date | Status | Decision | Rationale | Source |
|---|---|---|---|---|---|
| F-17 | 2026-07-31 (recorded 2026-08-01) | fixed: merged | **Identifier schemes.** `m:` is `m:` + the lowercased method name. `mod:` comes from `meta.yml` `name`, never the directory leaf. Never normalize a tool name with `resolve_method_ids()`, which is a fuzzy search. | Mixing the schemes silently produces ids that reference nothing. | [../../CLAUDE.md](../../CLAUDE.md) "Identifier schemes"; `src/methods_graph/bench/normalize.py` |
| F-18 | 2026-08-01 | fixed: merged | **Invariants.** No new runtime dependencies. `kuzu==0.11.3` is pinned. Output is deterministic (sorted iteration, seeded RNG, `ORDER BY`, `sort_keys=True`). Nothing is dropped silently. Tests pass with `OPENAI_API_KEY` unset and never touch the network. | Byte-identical re-runs and counted drops are what make every number here checkable. Known violations are listed in [../BACKLOG.md](../BACKLOG.md): Cypher without `ORDER BY` in `extract/seed.py` (G7), 45 dangling edges that are logged but not stored (M7), and a graph hash that trusts Kuzu's `ORDER BY`, which is occasionally out of order (M21). | [../../CLAUDE.md](../../CLAUDE.md) "Invariants" (fbb1844) |
| F-19 | 2026-08-01 | fixed: merged | **Process and test discipline.** Work goes brainstorm → spec → plan → execution. Every test names the mutation it catches, and that mutation was applied to see it fail. Nothing lands on `main` without the owner. | One plan once shipped 8 tests that passed against the bug they claimed to catch. | [../../CLAUDE.md](../../CLAUDE.md) "Process", "Testing standards"; plan-2:21,24 |

### Biolean benchmark (Plan 2 and after)

| ID | Date | Status | Decision | Rationale | Source |
|---|---|---|---|---|---|
| F-20 | 2026-09-22 | fixed: merged | **The kernel is the only trusted code in the benchmark.** The scorer never reimplements a rule: it calls `elaborate` + `check` over `MaskedFactStore(store, item.hidden)` and reads the verdict. | One judge. Option D of O-01 adds an untrusted rewriter before `check`, so choosing D means recording it as a deliberate deviation from this constraint. | plan-2:18 |
| F-21 | 2026-09-22 | fixed: merged | **Seven deliberate spec deviations.** (1) `FactStore.subjects()`. (2) A fixed `FORMAT_BLOCK` at the end of both prompts. (3) Release identity is read from the file headers. (4) `depth` counts propagation steps and is comparable with `gold_depth`. (5) Layout. (6) Rows carry `items_manifest`. (7) `goal_not_statable` is counted under the first error code. | Each is justified in the plan. (2) is the prompt that O-01 asks to reword. (4) is what a transitive kernel rule would break. | plan-2:25-32 |
| F-22 | 2026-09-22 | fixed: merged | **Contestants run closed-book.** `claude:` runs `claude -p` with `--tools "" --safe-mode --strict-mcp-config` in an empty temporary directory. | `--tools ""` alone removed only the built-in tools. MCP servers (PubMed, Open Targets, Playwright), user hooks and `CLAUDE.md` still reached every contestant. Commit 128a8c6 records a live check: `tools []`, `mcp_servers []`, 0 SessionStart hooks (3 without safe mode), and a 4,265-token prompt (8,806 without). | 128a8c6, merged in 894072d; `src/methods_graph/bench/adapters.py:55-88` |
| F-23 | 2026-09-21 | fixed: merged | **`hide_exact` hides every evidence row of the goal triple,** not just one row. | About 96% of single-row-masked GOA facts (785/815) re-derive through a sibling evidence row, so masking one row measures nothing. | spec:500-501 defines it. The 785/815 measurement is recorded in the repo: the comment at `tests/test_biolean_scale.py:58-63` and the body of commit 39d0263 (2026-09-21). |

## Part 2: open decisions

**"Raised"** is the date the question first surfaced. Each "Where" link gives the full evidence.

### Biolean

| ID | Raised | Status | Decision needed | Why it matters | Where |
|---|---|---|---|---|---|
| **O-01** | 2026-09-22 | **open, blocks the Biolean headline** | Edge rule: (A) strict; (B) a relation-aware transitive step in the kernel; (C) a relation-blind step; or (D) a strict kernel plus an untrusted expander, reporting both rates. | Opus 5 scores 41.0% strict (below modal's 52.8%, p = 1.7e-5), 53.8% relation-aware (a tie, p = 0.76), and 61.0% on biology alone (beats modal, p = 0.0015). | [the memo](2026-09-22-biolean-transitive-edges.md) |
| O-02 | 2026-09-22 | open | Keep the release-skewed `snapshots/go` pair (OBO 2026-07-26; GAF built on GO 2026-04-27; no `snapshot.json`), or re-fetch a pinned pair [net], rebuild the items and re-run [paid]. | A re-fetch changes release identity, and `bench run`/`score` then refuse the frozen items and `opus.jsonl`. Combine it with any O-01 re-run so the re-run is paid for once. | [../biolean/benchmark.md](../biolean/benchmark.md), memo §6 |
| O-03 | 2026-09-22 | open | Axiom end: should a citation of a true but less specific term count? That is 26 Opus and 31 modal `AXIOM_NOT_FOUND` citations (exclusive buckets; 27 and 32 counted non-exclusively, memo §6.1). | It is the same strict-versus-entailed question as O-01. Claude's analysis: an unrestricted rule would let a constant "axiom at the goal" reply hit every prove item. | memo §6 |
| O-04 | 2026-09-22 | open | Where results live: `opus.jsonl` and `modal.jsonl` (repo root, untracked, not ignored), `opus.partial.jsonl` (a redundant 180-row prefix), and `bench-runs/2026-08-08-pilot/`. Commit them as frozen records, or ignore them and back them up. Also record run provenance (flags, commit). | `opus.jsonl` is paid output that cannot be reproduced, and it is the only complete copy. `bench run` without `--resume` truncates `--out` (`cli.py:1416`). | [../STATUS.md](../STATUS.md) §3, [../biolean/results-2026-09-22-opus-5.md](../biolean/results-2026-09-22-opus-5.md) |
| O-05 | 2026-09-22 | open | The `claude:` contestant runs under Claude Code's default system prompt with no temperature control. `openai:` is a raw call at temperature 0. Accept this, or pin a system prompt? | Cross-provider comparisons are not like for like. | [../biolean/benchmark.md](../biolean/benchmark.md) |
| O-06 | 2026-09-22 | open | 3 Opus replies are Bash/curl calls to QuickGO. 2 of them end in tool-output text: `Failed to run command: ETIMEDOUT` and a background-job notice. Did a real tool runtime run them, or did the model write that text? | If a runtime ran them, silent retrieval in other rows cannot be ruled out from the data. All 3 scored as UNPARSED. | [../biolean/results-2026-09-22-opus-5.md](../biolean/results-2026-09-22-opus-5.md) |
| O-07 | 2026-09-22 | open | The trust boundary. `kernel.py` imports `store`, which imports `obo`, `gaf` and `eco` at module level. Restate "the only trusted file", or add a test that pins the kernel's import set. | The claim is stated but not enforced. | [../biolean/README.md](../biolean/README.md) |
| O-08 | 2026-09-22 | open | Contradictions. "X" and "NOT X" are both ACCEPTED (for example KCNK1 GO:0005249), and only `conflicts` shows the tension. Should consumers gate on conflicts until the defeasibility milestone exists? | Exit 0 does not mean "uncontested". | [../biolean/README.md](../biolean/README.md) |
| O-09 | 2026-09-21 | open | When to start Phase B (`sorry` discharge), which gives the hypothesize track its only knowledge measure. | Until then, the `template:` baseline saturates hypothesize at 1.0 on all four rates. | spec §8; [../biolean/benchmark.md](../biolean/benchmark.md) |

### Repository and housekeeping

| ID | Raised | Status | Decision needed | Why it matters | Where |
|---|---|---|---|---|---|
| O-10 | 2026-09-22 | open | Push the 56 local commits on `main` to `origin/main` (86ce425). | None of the Biolean work (7bc79ef, b0f80c4, 894072d, 6b28222) is pushed. CI has never run on it, and this disk holds the only copy. | [../STATUS.md](../STATUS.md) §2 |
| O-11 | 2026-09-22 | open | Archive local `master` (1b9399b, 165 commits, upstream gone), or restore its 15 June specs and plans into `docs/`. Were they dropped on purpose by the 2026-07-10 public-release squash (b791d69)? | That branch holds the only copy of the guardrail, chain, skills, planner and reproducible-pipeline designs. | [../HISTORY.md](../HISTORY.md) |
| O-12 | 2026-09-22 | open | `site/`: a nested git repo (1 commit, no remote, 764 MB, mostly `node_modules`). Move it out, or add `/site/` to `.gitignore`. | `git add -A` would embed it as a gitlink. Its numbers are stale, and it predates Biolean. | [../STATUS.md](../STATUS.md) §2 |
| O-13 | 2026-09-22 | open | Delete the branch `codex/align-dogma-method-layer` (local and on `origin`, both at e143522). | Its tree is identical to 849a071, which is already on `main`. | [../STATUS.md](../STATUS.md) §2 |
| O-14 | 2026-09-22 | open | Commit a small fixture graph so the DB-gated invariants run in CI (the precision pin, the 7-pair pin, the rules-versus-graph parity test). | 33 tests skip in CI, including those three pins. | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| O-15 | 2026-09-22 | open | The `mg` name. On macOS it runs `/usr/bin/mg`, a text editor. Install an `mg` console script, or keep the docs' alias convention? | Every doc and `data/methods.lock.json` (`"command": "mg rebuild"`) say `mg`. | [../README.md](../README.md#running-the-cli) |

### Methods graph and guardrail

| ID | Raised | Status | Decision needed | Why it matters | Where |
|---|---|---|---|---|---|
| O-16 | 2026-07-31 | open | Guardrail: keep it, fix it, or retire it. "Fix" could mean curated used-path replicate floors for limma and edgeR (both EVALUABLE at n=1), curated presence predicates (`requires`), and an exact `m:` lookup in place of fuzzy `--analysis` resolution (`salmon` resolves to `m:biohansel`). | It gates 1 of 905 methods (`m:deseq2`), yet the root README still calls the repo a "guardrail substrate". The code has been frozen since 430300a (2026-07-31). | [../methods-graph.md](../methods-graph.md) |
| O-17 | 2026-07-31 | open | Record the F-09 evidence in the repo: the recall-evaluation script and a pin of the corpus, if either can be recovered. | The project's biggest change of direction cannot be re-checked from the checkout. | [../HISTORY.md](../HISTORY.md) |
| O-18 | 2026-09-22 | open | Which graph is canonical? The `rebuild` graph whose hash is committed in `data/methods.lock.json` (the DB itself is gitignored; 19,425 nodes, 0 Pipeline/DOWNSTREAM_OF/ExecutionSpec/Modality), or an `ingest` graph (`catalog.ingest.yaml`, 96 pipelines; `data/catalog.kuzu` does not exist)? Is `quration`/Dogma still a live consumer? | `suggest` and the modality layer get nothing from the committed graph. | [../methods-graph.md](../methods-graph.md) |
| O-19 | 2026-09-22 | open | Skill library: add a pinned fetch plus an existence guard, or drop skills from `rebuild`. | `rebuild` reads `snapshots/skills/bioclaw`, which `fetch` never creates. A fresh fetch then yields 0 Skill nodes and a hash mismatch, so the weekly drift check cannot pass even with no upstream change. | [../methods-graph.md](../methods-graph.md) |
| O-20 | 2026-06-16 | open | Should the nf-core connector default `biotools_id` to the tool name when `meta.yml` has none? | Newer modules arrive semantically blank. Name collisions (`gprofiler2` vs `gprofiler`) need TDD and sign-off (owner's notes). | [../BACKLOG.md](../BACKLOG.md) |
| O-21 | 2026-06-18 | open | Are the executor (running tools from `ExecutionSpec` recipes) and the domain roadmap (phylogenetics, then epigenomics) still wanted after the pivot to benchmarks? | The owner's notes ranked the executor the most valuable unbuilt capability. No code runs a tool. | [../HISTORY.md](../HISTORY.md), [../BACKLOG.md](../BACKLOG.md) |

### Method-sequencing benchmark

| ID | Raised | Status | Decision needed | Why it matters | Where |
|---|---|---|---|---|---|
| O-22 | 2026-06-16 | open | `NXF_VER` policy. README and `CLAUDE.md` say to pin per release (`ingest.example.yaml:29` pins 23.10.0). The owner's notes say an old pin breaks this machine's Nextflow 26.04.3 and silently degrades the DAG to `io_inferred`. | The pilot ran unpinned, and its items record `nxf_ver: "unknown"`, which violates seq spec §1 provenance. Settling it needs a real Nextflow run [net]. | [../method-sequencing-benchmark.md](../method-sequencing-benchmark.md) |
| O-23 | 2026-08-08 | open | Goals: who writes the goal text, and how to keep it from leaking the answer. No goals file exists; the pilot prompts were bare pipeline names. | Given the bare name "mag", Sonnet refused or hallucinated. | [../method-sequencing-benchmark.md](../method-sequencing-benchmark.md) |
| O-24 | 2026-08-08 | open | The validity axis. On the pilot, gold scores 0.505 validity (coverage 0.128). Fix the method-level I/O unions and first-occurrence projection, report `n_broken` beside it, or drop the axis until curation improves. | The ceiling baseline fails its own ceiling. | [../method-sequencing-benchmark.md](../method-sequencing-benchmark.md) |
| O-25 | 2026-09-22 | open | Pilot scope before scaling to about 142 pipelines. Discard the pilot's Sonnet numbers, which were not closed-book? Count local-module processes that gold drops? Strip plumbing modules (20 of 145 gold method steps)? Write Plan 3 (live cuts), or drop contamination control? | These decide whether a scaled run means anything. | [../method-sequencing-benchmark.md](../method-sequencing-benchmark.md) |

Loose ends that are defects rather than decisions are in [../BACKLOG.md](../BACKLOG.md): the four items parked in 59d5111, the missing timeout on the nextflow preview call (`fetch.py:446`), and the Format audit mismatch.
