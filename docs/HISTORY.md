# History

**What this is:** the dated timeline of methods-graph from its first commit (2026-06-08) to 2026-09-22, and why the direction changed twice: guardrail, then benchmark, then Biolean.
**Status as of 2026-09-22:** `main` is at 6b28222 with 99 commits (2026-07-10..2026-09-22). It is 56 commits ahead of `origin/main` (86ce425), and none of those 56 are pushed. The June 2026 history exists only on the local `master` branch (165 commits).
**Read next:** [STATUS.md](STATUS.md) for where things stand on 2026-09-22, and [decisions/README.md](decisions/README.md) for what is fixed and what is still open.

## How to read this page

Each claim carries one of these labels:

| Label | Meaning |
|---|---|
| **git** | Checked against `git log` on `main`, or on `master` where marked. The hash is given. |
| **untracked** | Comes from files in the checkout that git does not track. Dates come from the file's own README or its mtime. |
| **owner's notes** | Comes from the owner's working notes, which are kept outside the repo. Nothing in the repo reproduces it. |
| **open** | Not settled. Listed in [BACKLOG.md](BACKLOG.md) or [decisions/README.md](decisions/README.md). |

To check the git facts yourself (run from the repo root; no network, DB or snapshots needed):

```bash
git log --format='%h %ad %s' --date=short main     # 99 commits
git log --format='%h %ad %s' --date=short master   # 165 commits, local only, no shared history with main
git diff --stat master b791d69                     # what the public-release squash dropped
git show -s --format=%B <hash>                     # the reasoning recorded in a commit body
```

## The short version

1. **June 2026 (git, `master` only).** A knowledge graph of 905 bioinformatics methods was built, then a guardrail on top of it that returns EVALUABLE / BLOCKED / NOT_EVALUABLE.
2. **2026-07-10 (git).** The public release squashed that history into one commit, b791d69. All 15 June design documents were dropped from `main`.
3. **2026-07-30/31 (git).** The guardrail's false blocks were fixed: the number of methods it could block went from 23 to 1. **The owner's notes add** that a corpus evaluation then measured the guardrail's recall at 0%, and the owner decided to redirect the project to a benchmark. No script or data for that evaluation is in the repo.
4. **2026-07-30..2026-08-09.** The method-sequencing benchmark was built (git) and piloted on 156 items (untracked).
5. **2026-09-20..2026-09-22.** Biolean was built: a proof checker for Gene Ontology (GO) claims with its own benchmark (git). On its prove track, Opus 5 scored 205/500 against the gene-blind modal baseline's 264/500 (untracked results). Under a looser rule for ontology edges, Opus ties modal (269/500, p = 0.76); on a biology-only score it beats it (305/500, p = 0.0015). Which rule to adopt is **open**.

## Timeline at a glance

| Date | Commit | Event | Source |
|---|---|---|---|
| 2026-06-08 | a3a2499 | First commit: design spec for the methods master graph | git (`master`) |
| 2026-06-09..06-11 | 3d2a02f..b3b0415 | MVP: EDAM, nf-core, BioContainers and bio.tools connectors, resolver, Kùzu loader, provider, STATO/OBI, statistical-method links, causal demo | git (`master`) |
| 2026-06-13 | c1d6672 | nf-core pipeline graph ("Sub-project A") | git (`master`) |
| 2026-06-14 | 7751803, b4f47bb | Planner and `suggest` ("Sub-project B") | git (`master`) |
| 2026-06-15 | 11d24fa | AMENABLE_TO layer: statistics that can run on an operation's output | git (`master`) |
| 2026-06-16 | eb3ee50, 78b67cb | DOWNSTREAM_OF edges from Nextflow preview DAGs; the `ingest` backbone | git (`master`) |
| 2026-06-17 | a6d4e67, 2ea6621 | Execution-spec layer; assumption→diagnostic layer | git (`master`) |
| 2026-06-17 | — | Bake-off: a frontier LLM matched the graph at recommending canonical workflows | owner's notes |
| 2026-06-18 | a528346 | Operation-mediated AMENABLE_TO: complete-chain methods went from 26 to 97 | git (`master`) |
| 2026-06-19 | 64a207e, 8678b57 | `guardrail` CLI; `guardrail-chain` | git (`master`) |
| 2026-06-19 | a84afa8..1db3a13 | Skill layer (BioClaw snapshot, K-Dense adapter) | git (`master`) |
| 2026-06-19 | 47ac306 | Single-cell evaluability; scanpy's leaked bulk replicate gate removed | git (`master`) |
| 2026-06-19 | 10329c4, 067f7e9, bc3b7bb, 1b9399b | `rebuild`, `explain`, Makefile and CI; 1b9399b is the last `master` commit | git (`master`) |
| 2026-07-10 | b791d69 | Public release, squashed; this is the root of `main` | git |
| 2026-07-12 | 849a071 | PR #2: README repositions the repo as Dogma's method-validity layer | git |
| 2026-07-30 | 8477b28 | Guardrail precision fix (23 → 1 blockable methods); FACTS_REQUIRED; `rules.py`; `hook.py`; benchmark spec and Plan 1 | git |
| 2026-07-30/31 | — | Corpus evaluation: guardrail recall 0%. The kill criterion was met but not invoked, and the owner redirected work to the benchmark | owner's notes |
| 2026-07-31 | 529ffc5 | Merge: guardrail hardening + benchmark gold build (Plan 1) | git |
| 2026-07-31 | 59d5111 | Merge: benchmark scorer, adapters and runner (Plan 2) | git |
| 2026-07-31 | 5bdd587 | CI starts running on pushes to `main` | git |
| 2026-08-01 | fbb1844, 86ce425 | CLAUDE.md; the weekly `rebuild-verify` job split into an informational drift step and a hard determinism step (still one job); README fixes. 86ce425 is `origin/main` as of the 2026-09-22 fetch | git |
| 2026-08-08/09 | — | Sequencing-benchmark pilot: 156 items, Sonnet against three baselines | untracked (`bench-runs/2026-08-08-pilot/`) |
| 2026-08-02..09-20 | — | No commits | git |
| 2026-09-20 | — | Biolean started. The seven fixed design decisions are first recorded in 86fe1ee §0 (2026-09-21); the day they were fixed is not recorded | owner's notes (start date); git (86fe1ee) |
| 2026-09-21 | 86fe1ee, 7bc79ef | Biolean spec; Plan 1 merged (kernel, elaborator, tactics, fetch, CLI) | git |
| 2026-09-22 | b0f80c4 | Biolean Plan 2 merged: the two-track benchmark | git |
| 2026-09-22 | 894072d | Closed-book `claude:` adapter merged | git |
| 2026-09-22 | — | Opus 5 prove-track run: 205/500 strict, against modal's 264/500 | untracked (`opus.jsonl`, `modal.jsonl`) |
| 2026-09-22 | 6b28222 | `biolean bench run --workers N --resume` merged; this is HEAD | git |

## Phase 1 — June 2026: the graph and the guardrail (local `master`)

All of this is on local `master` (1b9399b). Its upstream `origin/master` is gone: the last fetch on 2026-09-22 (`.git/FETCH_HEAD`) lists only `main` and `codex/align-dogma-method-layer` on origin. As far as git can tell, this checkout holds the only copy. The code itself did reach `main` through the squash (Phase 2); the reasoning in its commit messages and specs did not.

What was built (git, `master`):

- **2026-06-09..06-11:** the graph itself. Connectors, a union-find resolver keyed on `m:<lower(name)>`, the Kùzu loader, `KuzuMethodsGraphProvider`, STATO/OBI ingestion, and curated statistical-method/assumption links (f31c056).
- **2026-06-13..06-16:** pipeline structure. The nf-core pipeline graph (c1d6672), then real DOWNSTREAM_OF edges from `nextflow -preview -with-dag` (eb3ee50). Per its commit message, that cut the rnaseq edges from 434 noisy I/O-inferred edges to 98 real ones.
- **2026-06-14:** the planner and `suggest` (b4f47bb).
- **2026-06-15..06-18:** the evaluability layers: AMENABLE_TO (11d24fa), data types (8cdd702), execution specs (a6d4e67), assumption→diagnostic (2ea6621), modality (42eebe8) and the full nf-core catalog import (1203204).
- **2026-06-19:** proteomics-MS (b3003e7..8702cb3), the guardrail CLI (64a207e, exit codes 0/3/4), the linear chain evaluator (8678b57), the skill layer (a84afa8..1db3a13), single-cell (47ac306), the reproducible `rebuild` with its lock (10329c4), `explain` (067f7e9), and Makefile + CI (bc3b7bb).

Why it went this way:

- **Goal at the time (owner's notes).** The graph was to be the substrate that quration calls. quration is the legacy namespace of Dogma's package. For each edge of a causal graph, the graph would say whether the data can evaluate it now, what it needs first, or that it cannot be evaluated.
- **2026-06-17 bake-off (owner's notes).** A frontier LLM matched or beat the graph at recommending canonical workflows such as DESeq2. The owner concluded that the graph's value lies in determinism, per-claim provenance and correctly refusing edges it cannot evaluate, not in knowing more than a model does. The repo holds no bake-off code or data.
- **2026-06-18 scope (owner's notes).** Scope widened to all of computational biology, taken one domain at a time with the cheapest-to-ground domains first. By 2026-06-19, five domains had curated evaluability: variant/GWAS, bulk RNA-seq DE, GSEA, proteomics-MS and single-cell (git, among others: a528346 (variant/GWAS and expression/DE operations), 39112cf (a GSEA-specific stat node), b3003e7..8702cb3 (proteomics), 47ac306 (single-cell)).
- **The scaling lever (git, a528346, 2026-06-18).** Assumptions are curated once per EDAM operation, and every tool that PERFORMS that operation inherits the chain. This took complete-chain methods from 26 to 97 and AMENABLE_TO edges from 7 to 43. The same mechanism later produced the guardrail's false blocks (Phase 4).
- **First sign of the leak (git, 47ac306, 2026-06-19).** scanpy picked up a bulk-DE replicate floor through a bio.tools EDAM tag. The fix was curation for scanpy alone; the mechanism stayed.
- **CI (git, bc3b7bb).** The workflow filtered on `branches: [master]`. That filter mattered after the squash (Phase 2).

## Phase 2 — 2026-07-10: the public-release squash (b791d69)

Facts (git):

- b791d69 is the root of `main`: 145 files, +25,194 lines. `git merge-base master main` exits 1, so the two branches share no history.
- Outside `docs/`, the release tree differs from `master`'s tip only in README.md, LICENSE, .gitignore, pyproject.toml, uv.lock, `examples/causal_evaluability_demo.py` and `provider/quration_provider.py`. In total, `git diff --stat master b791d69` shows 25 files changed, +2,400/−6,596. The code that shipped is the June code.
- **What the squash dropped from `main`:**
  - 9 specs: 2026-06-08 methods-master-graph; 2026-06-13 nfcore-pipeline-graph; 2026-06-14 methods-graph-planner; and from 2026-06-19 guardrail-cli, pipeline-chain-evaluator, proteomics-ms-evaluability, reproducible-pipeline, single-cell-evaluability and skill-library-integration.
  - 6 plans: 2026-06-08 methods-master-graph-mvp; 2026-06-13 nfcore-pipeline-graph; 2026-06-14 methods-graph-planner; and from 2026-06-19 proteomics-ms-evaluability, reproducible-pipeline and skill-library-integration.
  - `docs/arXiv-2606.04494v1.tar.gz`.
  - The 165 commit messages that recorded why each piece was built.

  To read any of them: `git show master:docs/superpowers/specs/2026-06-19-guardrail-cli-design.md`.
- Consequences (git):
  - CI's `branches: [master]` filter matched nothing on `main`. 5bdd587 (2026-07-31) records that "no push to main has ever triggered CI" until that commit. Pull requests were still tested.
  - `src/methods_graph/connectors/skills.py:3` still points at a spec that is not on `main`.
- **Open** (O-11 in [decisions/README.md](decisions/README.md)): whether leaving the June docs out was deliberate. Local `master` is the only copy git knows of, so archive it (tag, push, or copy the docs into `docs/`) before deleting anything.

## Phase 3 — 2026-07-12: Dogma repositioning (849a071)

- PR #2 changed only README.md (+29/−8) (git). It frames the repo as "the separately versioned method-validity and guardrail substrate for Dogma" and a "methodological leash". It also says `quration` survives only as Dogma's legacy package namespace.
- The branch `codex/align-dogma-method-layer` (e143522, still present locally and on origin) has a tree identical to 849a071, so it is fully merged (git: `git diff --stat e143522 849a071` is empty).
- The framing is still in the README. It no longer matches what the guardrail does: after Phase 4 it can block 1 of 905 methods, and no guardrail-area file has changed since 430300a (2026-07-31). See [methods-graph.md](methods-graph.md).

## Phase 4 — 2026-07-30/31: guardrail hardening and the precision fix

Facts (git):

- **8477b28, 2026-07-30: blockable methods went from 23 to 1.** Before this commit, 23 of 905 methods could BLOCK on a replicate count. They included bbmap (the one read aligner among them), antismash, cellbender, salmon and kallisto. The commit names two causes:
  1. **Gating on `source=amenable`.** AMENABLE_TO describes statistics that can run on a tool's output, not statistics the tool performs. Now only `source=used` assumptions gate (`guardrail.py:96-100`).
  2. **Ignoring `applies_to_assumption`.** A diagnostic's threshold leaked onto every tool that uses maximum-likelihood estimation. Now the threshold attaches only to the assumption the diagnostic names (`extract/seed.py`).

  The only gateable method left is `m:deseq2` (replicates_per_group ≥ 3), pinned by `tests/test_guardrail_precision.py::test_the_gateable_set_is_pinned`. That test is DB-gated, so CI skips it. The 23 → 1 figure was re-derived for these docs by running 849a071's `seed.py` and `guardrail.py` against `data/methods.kuzu`. That was a scratch script, not a repo command.
- **The same commit made the guardrail fail closed.** A new FACTS_REQUIRED verdict (exit 5) means a hard pre-run gate whose fact was never supplied is uncertified rather than EVALUABLE. Chain precedence became BLOCKED > NOT_EVALUABLE > FACTS_REQUIRED > EVALUABLE.
- **It added a `requires: {fact: true}` presence-predicate shape.** The engine supports it, but no curated data emits it.
- **It added two new files.** `rules.py` evaluates the rules from the curated YAML with no DB. `hook.py` is a Claude Code PreToolUse adapter; it is not wired into any settings file.
- **The same commit also added the method-sequencing benchmark spec and the Plan 1 (gold build) plan.** Tests went from 552 to 578, per the commit message.
- **430300a, 2026-07-31.**
  - Fixed the gold answer key's module ids. 1,541 of 1,920 modules had received an id no node carries (see Lessons).
  - Fixed four hook/rules enforcement defects. One of the four dropped the hook patterns for edgeR/limma/kallisto, which have no `source=used` precondition that can fire.
- **529ffc5, 2026-07-31 07:25: the merge.** Tests went from 552 to 619.
- No commit since 430300a touches `guardrail.py`, `rules.py`, `hook.py`, `planner.py`, `provider/`, `extract/`, `explain.py` or `connectors/skills.py`. `crosslinks/` has not changed since b791d69.

## Phase 5 — The corpus evaluation, the kill criterion and the redirect

This is the project's biggest change of direction, and **the repo holds almost none of it**. Each row says where its claim comes from.

| Claim | Source | Can the repo reproduce it? |
|---|---|---|
| Guardrail recall was measured at exactly 0% against `markziemann/SurveyEnrichmentMethods` `data/PMC_2019-analysis.tsv`: 1,761 rows, 1,628 after dropping EXCLUDE, about 1,465 expert-labelled violations | owner's notes | **No.** No script and no corpus file. No commit message mentions Ziemann, SurveyEnrichmentMethods or a kill criterion (`git log --all -i --grep=<term>` finds nothing); the one commit that says "recall" (d7c8036) means the random baseline's. |
| The 0% is deductive, not sampled. The labelled failure kinds (background gene set, FDR correction, inference without a test) cannot be written as `min_x >= n`, and 8 of the corpus's top 10 tools are absent from the graph | owner's notes | **Partly.** A comment at `tests/test_guardrail.py:346-351` cites background-set failures in 1,364/1,628 labelled rows and multiple-testing correction in about 760 rows, attributed to "Wijesooriya et al.", and says neither can be expressed as `min_<dim> >= n`. The `requires` presence predicate (8477b28) is the gate shape that could express them; nothing curates it. The "8 of 10 tools" claim is unverified. |
| The kill criterion (stop if recall < 10% and no real catch has been logged) was formally met | owner's notes | **No.** |
| **Owner decision:** do not invoke the kill criterion; continue, and redirect to a benchmark. The reasoning: the 905-method catalog makes a poor guardrail substrate (it caused every false positive) but a good benchmark scoring oracle | owner's notes | **No.** Indirect trace only: the benchmark spec (`docs/superpowers/specs/2026-07-30-method-sequencing-benchmark-design.md`) landed in 8477b28, in the same commit as the precision fix. The spec states its purpose but not why the project turned to it. |

What git cannot establish:

- **Ordering.** The spec is dated 2026-07-30 and the owner's notes were last modified on 2026-07-31, but no timestamp places the recall evaluation before or after the benchmark spec.
- **A caveat on the oracle rationale.** The owner's notes cite "7,880 typed I/O edges" as the substrate for validity checks. In `data/methods.kuzu`, 7,744 of those 7,880 INPUT/OUTPUT edges point to Format nodes and only 136 to Data nodes, and the benchmark oracle reads Data only (`bench/oracle.py:116-122`). The pilot later measured validity coverage at 0.128 (Phase 6).

The decision itself is now logged as F-09 in [decisions/README.md](decisions/README.md), sourced to the owner's notes. **Open** (O-17 there): recover and commit the evaluation script and a pin of the corpus, so the result can be re-checked.

## Phase 6 — 2026-07-30..2026-08-09: the method-sequencing benchmark

What was built (git):

| Date | Commit | What |
|---|---|---|
| 2026-07-30 | 8477b28, 825c086, 8e82d9e | Spec and Plan 1; gold sequences extracted from Nextflow DAGs |
| 2026-07-31 | 529ffc5 (merge, 10 commits) | Plan 1: `bench build` emits frozen items and a manifest. Gold requires `derivation=nextflow_dsl2`; the `io_inferred` fallback is rejected |
| 2026-07-31 | 3224732 → 59d5111 (merge, 25 commits) | Plan 2: oracle, normalizer, scorer, renderer, adapters, baselines, runner. Tests went from 619 to 771 |
| 2026-07-31 | 5bdd587 | CI now runs on pushes to `main` |
| 2026-08-01 | fbb1844 | CLAUDE.md. The weekly rebuild job was split: upstream drift is informational, determinism is a hard gate. Per the commit message, the old combined job "stayed red for six weeks" |
| 2026-08-01 | 86ce425 | README corrections. **This is the last pushed commit** (`origin/main`) |

Defects caught in review before the Plan 2 merge (per the 59d5111 commit body; each is now a lesson below):

- validity scored adjacent pairs;
- next-step items printed their own answer;
- the runner buffered rows in memory;
- `match_steps` could swap equivalent tools;
- a test read the ambient `OPENAI_API_KEY`;
- the equivalence relation had 9 pairs, 2 of them wrong, so it now has 7.

Four items were parked in that same commit body and **are still open at HEAD**:

- the modal-baseline test does not pin the mode property;
- `score_item` runs outside the per-item guard;
- `summarize` omits `n_broken`;
- the fixture still contains the answer-leak item `rnaseq/next/003`.

Plan 3 (live cuts from bioRxiv, for contamination control) was never written, and no live-cut code exists under `src/methods_graph/bench/`.

**The pilot, 2026-08-08/09 (untracked, `bench-runs/2026-08-08-pilot/`).** This is the only empirical run of this benchmark. The directory has never been committed and has no ignore rule.

- 12 nf-core pipelines were previewed with Nextflow 26.04.3 and no `NXF_VER` pin. 10 were used; ampliseq and scrnaseq were dropped with 0-step gold.
- The 10 pipelines gave 156 items: 10 whole_pipeline and 146 next_step. Another 104 of 250 next-step positions were withheld as answer leaks.
- Contestants were gold, modal, random:42 and `claude:sonnet` (two runs, merged; run 1 hit a usage window at row 59, and `r12-sonnet-merged.jsonl` is byte-identical to run 2's `r12-sonnet2.jsonl`).

Re-scoring the retained rows with current code reproduces the pilot README exactly (`mg bench score --results bench-runs/2026-08-08-pilot/results/r12-<run>.jsonl` [DB]; no network, no paid calls). Two headline figures: selection F1 is 1.000 for gold, 0.368 for Sonnet, 0.283 for modal and 0.000 for random:42; validity is 0.505 for gold itself (coverage 0.128).

Why none of it is a model measurement (details, the full table and the five caveats are in [method-sequencing-benchmark.md](method-sequencing-benchmark.md#read-these-five-caveats-first)):

- **Sonnet was not closed-book.** The adapter at the time (d7c8036) ran `claude -p` in the caller's working directory with default tools, CLAUDE.md and MCP loaded, and some replies name Claude Code tools. This is why the closed-book adapter (Phase 7) exists.
- **Prompts were bare pipeline names**, `modal:` answers viralrecon's gold for every item, gold fails its own validity ceiling, and gold drops processes from local modules without a count.
- **Infra.** `fetch.py:446` runs the Nextflow preview with no timeout; sarek hung for about 55 minutes.

After 86ce425 (2026-08-01), the next commit is 86fe1ee on 2026-09-21. That makes a seven-week gap, and the pilot falls inside it. Also untracked: `site/`, a separate landing-page repo nested in the checkout, with one commit (e81508a, 2026-07-31, in that repo's own history) and no remote. It predates Biolean.

## Phase 7 — 2026-09-20..2026-09-22: Biolean

**Why Biolean exists (owner's notes only).** The guardrail's 0% recall showed that advice-shaped gates fail. The alternative is a checker the agent must satisfy. The spec (86fe1ee) states what Biolean is but not why it was started.

**By 2026-09-21 the owner had fixed seven decisions.** The spec records them as §0 "Fixed decisions" (git, 86fe1ee, 2026-09-21 11:14). The owner's notes date Biolean's start to 2026-09-20 but not the decisions themselves:

1. Phase A (a typed checker over existing ontologies) comes first; Phase B (verifying analyses) comes later.
2. The kernel guarantees structural soundness only.
3. The library is existing ontologies: GO + human GOA in v1.
4. The prover is an LLM agent.
5. Computed evidence is admitted as `sorry`.
6. Success means kernel soundness under the repo's mutation discipline, plus a two-track leave-one-out benchmark.
7. It lives in this repo.

See [decisions/README.md](decisions/README.md).

| Date/time | Commit | What (git) |
|---|---|---|
| 2026-09-21 11:14 | 86fe1ee | Spec, revised against a 31-finding adversarial review. The latest OBO (the PURL) leaves 162 GOA rows at obsolete terms, so the fetcher pins the OBO to the release the GAF names |
| 2026-09-21 11:39 | 8c9b9cf | Plan 1: 14 TDD tasks, with a named mutation per test |
| 2026-09-21 15:49 | 3398050 | `biolean fetch`: GOA, GO at the GAF's release, ECO mapping |
| 2026-09-21 17:20 | 7bc79ef (merge, 32 commits) | Plan 1: kernel (axiom, is_a, part_of, sorry), elaborator, breadth-first prover, `biolean fetch\|check\|prove\|goals`. The commit message says 883 tests; 914 are collected at that commit |
| 2026-09-22 15:22 | 5199bd3 | Plan 2 |
| 2026-09-22 17:35 | abb5ba9 | The spec's modal estimate of "about 61%" is replaced by the measured 52.8% |
| 2026-09-22 18:07 | fcac341 | Final-review fixes F1–F7. F2 runs `claude:` with `--tools ""` in an empty temp directory |
| 2026-09-22 18:21 | b0f80c4 (merge, 14 commits) | Plan 2: prove and hypothesize tracks. Gold scores 1.000, modal 0.528, random 0.052. The message notes: "claude: adapter still loads MCP servers" |
| 2026-09-22 19:06 | 128a8c6 → 894072d (merge) | Adds `--safe-mode --strict-mcp-config`. Verified live: tools [], mcp_servers [], 0 SessionStart hooks (3 without safe mode), and a 4,265-token prompt (8,806 without) |
| 2026-09-22 20:07 | 4c2e3b9 | `--workers N --resume`. Sequential Opus took 12–27 s per call, or 2–3 h for 500 items |
| 2026-09-22 20:42..21:38 | ad992e8, 09986ab, 26c09dd, 948ba7d | Four review rounds on the abort path, one fix commit each. Each round found a real defect: the first three could lose answers already paid for (for example, SIGINT with 4 calls in flight wrote 0 rows before ad992e8); the fourth found that a drained call failing with a non-`AdapterError` left no row |
| 2026-09-22 21:40 | 6b28222 (merge, 5 commits) | The merge message says 18 mutations were applied and each one killed; the five commit bodies actually hold 41 `mutation checked:` lines (39 distinct). This is HEAD |

One fact bears on every Biolean result (git plus file mtimes). In `snapshots/go/`, `go-basic.obo` and `goa_human.gaf.gz` are dated 2026-09-21 00:09 and `gaf-eco-mapping.txt` 10:23, all before the pinning fetcher existed (3398050, 15:49). There is no `snapshot.json`. The OBO is `releases/2026-07-26`, while the GAF was built against GO 2026-04-27 (`biolean-bench/manifest.json` release block). The frozen items and every result below were built on that skewed pair.

## Phase 8 — 2026-09-22: the Opus 5 prove-track run

Timing (untracked; file mtimes compared with git):

- `modal.jsonl` was written at 18:29.
- `opus.partial.jsonl` (180 rows) was written at 20:17, and `opus.jsonl` (500 rows) at 20:32.
- The rows carry no timestamps and no commit, so the code version is inferred from mtimes, not recorded. The last 320 rows landed in the 15 minutes after the 180-row prefix, a rate only a parallel run reaches (sequential calls took 12–27 s each, per 4c2e3b9). That fits the `--workers` code of 4c2e3b9 (20:07). Every write predates the abort-path fix wave and the final merge (6b28222, 21:40). Nothing in the repo records when the first 180 rows were produced. The log of the session that launched the run (outside the repo, so secondary evidence) puts their start at about 19:32, after the closed-book merge (894072d, 19:23); see [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md#what-is-not-recorded).
- The exact command line is not recorded in the rows.

Results on the same 500 frozen prove items (seed 0). A hit is an ACCEPTED derivation of the item's goal with no `sorry` on the used chain. The Opus and modal rows were re-derived for these docs with the command below (swap in `modal.jsonl`), which needs `snapshots/go/` and the untracked result files and makes no paid calls. Gold and random:0 have no results file: the docs survey re-ran them in process on the frozen items, and the b0f80c4 merge message gives the same rates (1.000, 0.052).

```bash
mg biolean bench score --results opus.jsonl
```

| Contestant | Hits / 500 (strict kernel) | Rate |
|---|---|---|
| gold: | 500 | 1.000 |
| modal: | 264 | 0.528 |
| claude:claude-opus-5 | 205 | 0.410 |
| random:0 | 26 | 0.052 |

What happened (from the docs survey of `opus.jsonl`; details in [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md)):

- Opus loses to modal head to head (exact McNemar p = 1.7e-5).
- 3 of its 500 replies are unparsed. All three are attempted tool calls, written as text, that `curl` EBI QuickGO. Even with no tools available, the model tried to go open-book.
- The kernel accepts an `is_a`/`part_of` step only when the store holds that exact direct edge (`kernel.py:304-313`), and the prompt never says so. Opus often cites a true ancestor that skips an intermediate term.
- Other rules were scored outside the repo for the decision memo; no repo command produces these numbers. Under a relation-aware transitive step Opus scores 269/500 (p = 0.76 against modal), under a relation-blind one 287/500 (p = 0.077), and on a biology-only measure 305/500 (p = 0.0015). gold, modal and random:0 do not change under the two transitive rules, and modal stays at 264. The full table, with head-to-head counts, is in [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md#what-this-does-and-does-not-show).

**Open:** the rule choice flips the headline. The options are strict, relation-aware in the kernel, relation-blind, or a strict kernel plus an untrusted expander that reports both. The owner has not decided. See [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md).

The result files are untracked. Before this doc set, the results were recorded nowhere in the repo.

## Test count over time

Every figure below is quoted from the commit message or command named in the Source column.

| Date | Commit | Tests | Source |
|---|---|---|---|
| 2026-06-15 | 11d24fa (`master`) | 333 passed | commit message |
| 2026-06-19 | 47ac306 (`master`) | 535 passed, 1 skipped | commit message |
| 2026-07-30 | 8477b28 | 552 → 578 | commit message |
| 2026-07-31 | 529ffc5 | 552 → 619 | merge message |
| 2026-07-31 | 59d5111 | 619 → 771 | merge message |
| 2026-09-21 | 7bc79ef | Merge message: "883 tests". Re-counted: 914 collected; 882 passed, 32 skipped CI-like. The owner's notes say 913, which fits 914 minus the `quration` skip | merge message; `git archive 7bc79ef` into a scratch dir, then `pytest --collect-only -q` and `pytest -q` there |
| 2026-09-22 | 4c2e3b9 | 966 passed, 33 skipped (`OPENAI_API_KEY` unset) | commit message |
| 2026-09-22 | 6b28222 (HEAD) | 1,014 collected in 71 files. 1013 passed, 1 skipped locally (with DB and `snapshots/go`); 981 passed, 33 skipped CI-like (30 need the DB, 2 need `snapshots/go`, 1 needs `quration`) | `env -u OPENAI_API_KEY .venv/bin/python -m pytest -q` (CI-like: the same command in a `git archive HEAD` export with `PYTHONPATH=<export>/src`) |

CI runs `pytest -q` on Python 3.12; the local venv is Python 3.14.6. **CI has never run any commit after 86ce425**, because nothing after it is pushed.

## Lessons that shaped the code

Each lesson was learned by getting it wrong first. The "In CI?" column uses three values:

- **yes:** the test is on `origin/main` and needs neither the DB nor `snapshots/go`. CI results on GitHub were not checked, because these docs were written offline.
- **no, DB-gated:** the test skips without `data/methods.kuzu`, which CI does not have.
- **not yet, unpushed:** the test is in the 56 unpushed commits.

| # | Lesson | What went wrong first | Encoded in | Test | In CI? |
|---|---|---|---|---|---|
| 1 | Module ids come from the `meta.yml` `name`, never the path's last segment | The gold key minted `mod:align` for `star/align`: 1,541 of 1,920 modules got an id no node carries, and 141 leaves collide across 582 modules. The bug survived four reviews because fixtures used single-segment paths | 430300a (`iter_module_metas()`) | `tests/test_bench_run.py::test_module_ids_use_the_meta_yml_name_not_the_directory_leaf` | yes |
| 2 | Normalize names by exact `m:<lower(name)>` lookup; never use the fuzzy resolver | `resolve_method_ids(["STAR"])` returns `m:ea-utils`, `m:find` and `m:gedi` before `m:star` | df7ce92 (`bench/normalize.py`) | `tests/test_bench_normalize.py::test_names_resolve_exactly` | yes. **Not applied to the guardrail:** `guardrail --analysis salmon` still resolves to `m:biohansel` (open) |
| 3 | Score sequencing over the gold DAG's edges, not adjacent pairs | Parallel branches sit next to each other in any linearization, so the spec's adjacent-pair metric marks correct answers wrong | 430300a (gold edges frozen with the item), 3bc6c5a | `tests/test_bench_score.py::test_parallel_branches_are_not_penalized`; `tests/test_bench_gold.py::test_edges_are_the_dag_not_a_linearization` | yes |
| 4 | Validity uses reachability, not consecutive pairs | A verified-correct nf-core/rnaseq chain scored 0.5 at coverage 1.0 | 67a65de | `tests/test_bench_score.py::test_a_type_preserving_step_downstream_does_not_break_an_upstream_consumer` | yes. `guardrail-chain` still checks consecutive pairs (open) |
| 5 | Undefined is `None`, never `0.0` | "Ordered nothing correctly" and "there was nothing to order" were reported as the same number | 3bc6c5a | `tests/test_bench_score.py::test_no_scorable_edges_is_none_not_zero` | yes |
| 6 | `match_steps` prefers identity pairs | Feeding gold back scored 1.0 selection but 0.5 sequencing when two equivalent tools appeared | df9316d | `tests/test_bench_score.py::test_match_steps_returns_identity_pairing_when_gold_contains_a_mutual_equivalence` | yes |
| 7 | Audit the equivalence relation; don't assume it | 2 of 9 pairs were wrong (fastqc↔salmon, affy↔gsea), each bridged by an over-coarse EDAM operation | 67a65de (denylist in `score.py`) | `tests/test_bench_score.py::test_bridging_operations_do_not_make_a_qc_tool_a_quantifier` (yes); `::test_equivalence_relation_over_the_real_graph_is_exactly_the_expected_set` | first: yes; second: no, DB-gated |
| 8 | A next-step prompt must not contain its own answer | `star_genomegenerate` → `star_align` both render as "star", so 30–50% of real items would have scored free | 612cc82 | `tests/test_bench_build.py::test_a_next_step_item_is_not_built_when_the_prompt_would_contain_its_own_answer` | yes. The fixture still holds `rnaseq/next/003` (open) |
| 9 | AMENABLE_TO never gates, and a threshold attaches only to its `applies_to_assumption` | 23 methods could BLOCK on a replicate count, including a read aligner (bbmap). scanpy had already hit this in June (47ac306) | 8477b28 | `tests/test_guardrail_precision.py::test_the_gateable_set_is_pinned` | no, DB-gated |
| 10 | An unmeasured fact is not an approval (fail closed) | A gate whose fact was never supplied returned EVALUABLE, so not measuring was the cheapest route to approval | 8477b28 (FACTS_REQUIRED, exit 5) | `tests/test_guardrail.py::test_missing_fact_neither_blocks_nor_certifies` | yes |
| 11 | Only declared skill tools create gating WRAPS edges | A tool merely mentioned in a skill's prose gave `cell-annotation` scanpy's replicate gate | 1db3a13 (`master`; carried into b791d69) | `tests/test_skills_connector.py::test_prose_mined_tool_does_not_mint_wraps_edge` | yes |
| 12 | Tests never read the ambient environment | A test read `OPENAI_API_KEY`: green locally, red in CI | 3d5b886 | `tests/test_bench_adapters.py::test_get_adapter_parses_openai_provider` | yes |
| 13 | Paid runs stream rows to disk; an abort keeps every answer already paid for | The runner buffered rows in memory, so Ctrl-C lost the whole run. The later parallel runner lost in-flight answers on abort | d26587f (sequencing bench), 89d24ba (Biolean runner), ad992e8..948ba7d (parallel abort path), 4c2e3b9 (`--resume`) | `tests/test_bench_run.py::test_a_run_interrupted_by_a_non_adapter_exception_keeps_what_it_paid_for` (yes); `tests/test_biolean_bench_run.py::test_parallel_sink_gets_each_row_as_soon_as_its_call_finishes`; `tests/test_biolean_bench_cli.py::test_resume_keeps_paid_rows_and_retries_errors` | first: yes; Biolean tests: not yet, unpushed. **Not guarded:** without `--resume`, `--out` is opened with `"w"` and an existing results file is truncated (`cli.py:1416`) |
| 14 | Contestants run closed-book | The pilot's Sonnet ran in the repo with tools, CLAUDE.md and MCP loaded; its replies named Claude Code tools. After `--tools ""`, MCP servers, hooks and CLAUDE.md still leaked | fcac341 (`--tools ""`, empty temp cwd), 128a8c6 (`--safe-mode --strict-mcp-config`) | `tests/test_bench_adapters.py::test_claude_cli_sends_the_prompt_and_returns_stdout` | not yet, unpushed. The test exists on `origin/main`, but only in its pre-closed-book form; the flag and empty-cwd assertions came in fcac341 and 128a8c6. The contestant still gets Claude Code's default system prompt, and temperature is not controlled |
| 15 | The prove track hides every evidence row of the target triple (`hide_exact`), not a single row | With one row masked at a time, 815 of 1,000 GOA facts re-derived, and about 785 of those 815 went through a sibling evidence row at the same tuple rather than an ontology edge (measured on the 2026-09-21 snapshot; recorded in `tests/test_biolean_scale.py:58-63`, 39d0263). The owner's notes give the same 785/815 | d0d5f11 (`biolean/bench/items.py:100`) | `tests/test_biolean_bench_items.py::test_prove_item_hides_only_the_exact_rows` ("every evidence class at the tuple") | not yet, unpushed |
| 16 | Pin the GO OBO to the release the GAF names | The PURL OBO left 162 GAF rows at obsolete terms | 86fe1ee, 3398050 | `tests/test_biolean_fetch.py::test_fetch_biolean_downloads_the_obo_at_the_gaf_release_and_writes_the_manifest` | not yet, unpushed. The local `snapshots/go/` predates this fix and is still skewed |
| 17 | Quote measured figures, not estimates | The spec's modal figure of "about 61%" was an estimate (abb5ba9); the owner's notes say it came from a probe without leave-subject-out. The measured figure is 52.8% | abb5ba9 | — | — |
| 18 | Check that CI actually runs | `branches: [master]` matched nothing on `main`, so pushes went untested from 2026-07-10 to 2026-07-31 | 5bdd587 | — | As of 2026-09-22, 56 commits have never been in CI because they are unpushed |
| 19 | Keep upstream drift separate from non-determinism | The combined rebuild job stayed red for six weeks | fbb1844 | CI job `rebuild-verify` (weekly or dispatch) | weekly only |
| 20 | Accept a test only after it fails against a deliberate mutation | One plan produced eight tests that passed against the very bug they named; review caught all eight, the author none (CLAUDE.md; the owner's notes file it under the sequencing benchmark, and its examples are Plan 2 defects) | CLAUDE.md (fbb1844); `mutation checked:` lines in commit bodies (41 in the five commits merged at 6b28222) | — | Enforced by review, not by tooling |

## What this history cannot tell you

- **The 0% recall evaluation and the redirect.** They rest only on the owner's notes (Phase 5).
- **The 2026-06-17 bake-off.** It rests only on the owner's notes.
- **The pilot's exact build commands and clones.** They lived in a scratch directory that has since been deleted, so the pilot items cannot be rebuilt offline. The retained rows still re-score exactly.
- **The command line of the Opus run.** It is not recorded in the rows.
- **The design reasoning for June work.** It is on local `master` only, and only while that branch exists.
