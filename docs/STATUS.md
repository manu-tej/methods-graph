# Status

> **What this is:** the state of the repo on one page: the three projects, the decisions waiting on the owner, what is on disk, how to resume, and the traps.
> **Status:** as of 2026-09-22 (local `main` at `6b28222`).
> **Read next:** [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md), then the doc for the project you are resuming (the order is in [README.md](README.md)).

> **Note added 2026-11-09.** Work on this repo has been paused since October 2026. Everything below is the 2026-09-22 snapshot and has not been rewritten. Checked against `origin/main` (`8c6f56f`, 141 commits, last commit 2026-09-25), these snapshot statements no longer hold:
>
> - **"Unpushed" and "CI has never run on it".** `6b28222` and the four Biolean merges (`7bc79ef`, `b0f80c4`, `894072d`, `6b28222`) are on `origin/main`. The `test` job has run on pushes to `main` since 2026-09-23, including on `8c6f56f`. This also closes §2 #2 and the last line of the first CI trap in §5.
> - **"This doc set is uncommitted".** The docs were committed in `0c25cd1` and merged in `f97c516`.
> - **Biolean ledger "not yet merged".** The `worktree-biolean-ledger` commits are on `origin/main`.
> - **`master` "upstream gone" (§2 #3).** The branch was pushed to `origin/master` at `1b9399b`. It is still not merged into `main`.
>
> Still true of `origin/main`: `opus.jsonl`, `modal.jsonl`, `bench-runs/2026-08-08-pilot/` and `site/` are not tracked on `main`. The project states in §1 and the open decisions in §2 other than #2 were not re-checked for this note. The same "unpushed" wording appears in other docs dated 2026-09-22 ([README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), [HISTORY.md](HISTORY.md), [BACKLOG.md](BACKLOG.md), [method-sequencing-benchmark.md](method-sequencing-benchmark.md)); it is out of date there too.

`mg` means `alias mg='.venv/bin/python -m methods_graph.cli'`, run from the repo root. In a script or a non-interactive agent shell the alias does not expand; use the function form in [README.md](README.md#running-the-cli). The tags [DB], [GO], [items], [net] and [paid] are defined in [README.md](README.md#running-the-cli).

| Repo fact | Value | Source |
|---|---|---|
| HEAD | `6b28222`, the merge of `--workers/--resume`, 2026-09-22 | `git log -1` |
| Commits on `main` | 99, dated 2026-07-10 to 2026-09-22 | `git rev-list --count main` |
| Unpushed | 56 commits ahead of `origin/main` (`86ce425`, 2026-08-01) and 0 behind, as of the last fetch on 2026-09-22 (`.git/FETCH_HEAD`). **No Biolean work is pushed, and CI has never run on it.** | `git rev-list --left-right --count origin/main...main` |
| Working tree | Before this doc set was written: nothing staged or modified, only untracked or ignored artifacts (§3). This doc set is uncommitted: the new `docs/*.md` files, plus edits to `README.md`, `CLAUDE.md`, `docs/DATA_SOURCES.md` and `docs/superpowers/`. | `git status --porcelain --ignored`; `git diff --stat` |
| Tests | With the Biolean ledger (branch `worktree-biolean-ledger`, 2026-09-25): 1,234 tests in 79 files; 1201 passed / 33 skipped in a CI-like checkout (no DB, no `snapshots/go`); the main checkout with `data/methods.kuzu` and `snapshots/go/` present skips 1. Before the ledger (2026-09-22): 1,014 tests in 71 files, locally 1013 passed, 1 skipped; CI-like 981 passed, 33 skipped. CI runs Python 3.12; the local venv is 3.14.6. | `pytest -q`; `.github/workflows/ci.yml:20` |

## 1. The three projects

| Project | State | Single next step |
|---|---|---|
| Methods graph + guardrail | **frozen** (works, narrow) | Owner decides: keep, fix or retire the guardrail (§2 #6) |
| Method-sequencing benchmark | **blocked** | Add a timeout to the nextflow preview call (`src/methods_graph/fetch.py:446`) |
| Biolean | **active** | Owner decides the transitive-edge rule (§2 #1) |

### 1.1 Methods graph + guardrail: frozen

- **State [fact]:** frozen. No commit has touched guardrail-area files since `430300a` (2026-07-31). The crosslink YAMLs have not changed since `b791d69` (2026-07-10).
- **Why work stopped [owner decision]:** a corpus evaluation measured the guardrail's recall at 0%. The owner redirected the graph to serve as a benchmark scoring oracle rather than a gate. The corpus and the script are not in the repo, so this cannot be re-checked from the checkout. See [HISTORY.md](HISTORY.md).
- **Works [fact]:**
  - An offline `mg rebuild` from `snapshots/` reproduces the committed lock hash `sha256:c6940e39…`. Re-checked on 2026-09-22; it takes about 12 s.
  - Caveat: the hash computation itself is occasionally unstable, because it trusts Kuzu's `ORDER BY`. On the unchanged DB it gave a different hash in a few percent of reads, so a single MISMATCH from `rebuild --check` or CI's determinism step needs a rerun before it means anything ([BACKLOG.md](BACKLOG.md) M21; [methods-graph.md](methods-graph.md#5-reproducibility) R11).
  - `mg audit` passes.
  - `guardrail`, `guardrail-chain`, `explain` and `skills --coverage` run.

| Metric | Value | Denominator | Source |
|---|---|---|---|
| Nodes / edges | 19,425 / 32,757 | – | `data/methods.lock.json`; `mg audit` |
| Methods | 905 | – | `mg audit` (`methods_total`) |
| Methods with an EDAM operation (`PERFORMS`) | 415 (45.9%) | 905 | `mg audit` |
| Methods with an input / output `Data` node | 49 / 39 (5.4% / 4.3%) | 905 | [../CLAUDE.md](../CLAUDE.md), "The graph, in numbers that matter" |
| Methods with a complete assumption → diagnostic chain | 99 (10.9%). 94 of them reach it through operation-mediated `AMENABLE_TO`, which never gates; for 87 that is the only route (the other 7 also have a tool-internal chain). | 905 | `mg audit` (`with_checked_assumption`, `with_checked_via_operation`) |
| Methods the guardrail can BLOCK | 1 (`m:deseq2`, `replicates_per_group >= 3`) | 905 | `tests/test_guardrail_precision.py:60` (DB-gated, so CI does not run it) |

- **Not done or not true of the committed graph [fact]:**
  - The graph has 0 Pipeline, DOWNSTREAM_OF, ExecutionSpec and Modality entries, because `rebuild` never passes `--nfcore-pipelines`. As a result `suggest` has nothing to rank on: `--have fmt:format_1930` returns entries whose rank count is 0 ("0 pipeline(s) start with …"), and `--have mod:fastqc` returns `[]`.
  - limma and edgeR are EVALUABLE at n=1. They have no replicate floor on the path the guardrail enforces, which is a curation gap.
  - `mg fetch` replays none of the lock's source pins and never fetches `snapshots/skills/`.
- Details: [methods-graph.md](methods-graph.md).

### 1.2 Method-sequencing benchmark: blocked

- **State [fact]:** two of three plans are merged, both on 2026-07-31:
  - Plan 1 (gold build) in `529ffc5`.
  - Plan 2 (scorer, adapters, runner) in `59d5111`.
  - Plan 3 (live cuts, for contamination control) was never written, and no live-cut code exists.
  - No items are in git: `/bench/` is gitignored and `snapshots/pipelines/` does not exist.
- **Works [fact]:** `mg bench build|coverage|run|score`. The 183 tests in 8 files pass in under 2 s. Re-scoring the pilot reproduces its README table exactly.
- **Blocked by [fact]:**
  - Building items needs network access, Nextflow and Java.
  - The nextflow preview call has no timeout (`fetch.py:446`). sarek hung for about 55 min during the pilot.
  - There is no goals map, so every prompt is a bare pipeline name.
  - The NXF_VER pinning policy is undecided [open question].
- **Pilot:** untracked `bench-runs/2026-08-08-pilot/`, run 2026-08-08/09. It has 156 items (10 whole_pipeline, 146 next_step) from 10 of 12 pipelines. ampliseq and scrnaseq gave 0-step gold and were dropped.

| Axis (denominator) | gold: | claude:sonnet (merged) | modal: | random:42 |
|---|---|---|---|---|
| Selection F1 (10 whole-pipeline items) | 1.000 | 0.368 | 0.283 | 0.000 |
| Next-step top-1, headline (145 scored next-step items) | 1.000 | 0.120 | 0.003 | 0.000 |
| Validity (coverage) | 0.505 (0.128) | 0.333 (0.139) | 0.500 (0.080) | null |

Validity is scored only on whole-pipeline items where it is defined: 8, 6, 10 and 0 of the 10 for gold, Sonnet, modal and random (`validity_n_scored`).

Source: `mg bench score --results bench-runs/2026-08-08-pilot/results/r12-<run>.jsonl` [DB].

- **Read before quoting [fact]:**
  - Sonnet was **not** closed-book. It ran on the adapter as last changed in `d7c8036` (2026-07-31; unchanged through `86ce425`): `claude -p <prompt> --model sonnet`, in the caller's working directory, with tools and repo context available. `--tools ""` and an empty working directory came in `fcac341` (2026-09-22); safe mode and no MCP servers came in `128a8c6`.
  - `modal:` answers viralrecon's gold for every item, because all 10 gold sequences are unique.
  - Validity fails its own ceiling: gold scores 0.505.
  - Whether to discard the Sonnet numbers is an open question.
- **Next step:** add a subprocess timeout at `fetch.py:446`. It is offline and small, and it must come before any new item build. After that: write a goals map, rebuild the items [net], and re-run the models closed-book [paid]. Details: [method-sequencing-benchmark.md](method-sequencing-benchmark.md).

### 1.3 Biolean: active

- **State [fact]:** built on 2026-09-21/22 and merged locally in four merges:
  - `7bc79ef`, Plan 1: kernel, elaborator, tactics, fetch, CLI.
  - `b0f80c4`, Plan 2: the two-track benchmark.
  - `894072d`: the closed-book `claude:` adapter.
  - `6b28222`: `--workers N --resume`.
  - None of them is pushed, so CI has never run on them.
- **Works [fact]:**
  - `mg biolean check|prove|goals|fetch|bench`, with 249 tests in 19 files (242 before the ledger branch added 7 to the store, kernel, GAF and bench-item tests).
  - `mg biolean ledger init|append|verify|show` and `--ledger` on `prove|check|goals`; 213 tests in `tests/test_biolean_ledger_*.py`, `test_biolean_ed25519.py`, `test_biolean_sshsig.py`; no ledger repo exists yet (the base pair cannot be re-fetched: O-02). Built on branch `worktree-biolean-ledger`, not yet merged; see [biolean/ledger.md](biolean/ledger.md).
  - The gold ceiling scored 500/500 when re-run on 2026-09-22.
  - `bench build` reproduced `biolean-bench/` byte-for-byte on 2026-09-22 in about 40 s, from the current `snapshots/go/` only.
- **Headline, prove track, 500 items (seed 0), strict kernel [fact]:**

| Contestant | Hits / 500 | Rate | Where |
|---|---|---|---|
| gold: | 500 | 1.000 | ceiling, re-run 2026-09-22 |
| modal: (gene-blind prior) | 264 | 0.528 | `modal.jsonl` |
| claude:claude-opus-5 | 205 | 0.410 | `opus.jsonl` |
| random:0 | 26 | 0.052 | [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md) |

Opus against modal, item by item: both hit 142, only Opus 63, only modal 122, neither 173. Exact McNemar p = 1.7e-5. Sources: `mg biolean bench score --results opus.jsonl` [GO], and the rows' `hit` field.

- **The edge rule decides who wins [fact; which rule to adopt is an open question].** Across the three kernel rules only Opus's score changes: gold 500, modal 264 and random:0 26 under each. The biology-only row is a measure, not a kernel rule. It is an upper bound: modal stays at 264 and gold at 500, but random:0 rises to 178.

| Kernel rule for `is_a` / `part_of` steps | Opus hits / 500 | Opus vs modal (264): exact McNemar p |
|---|---|---|
| strict: exact direct edge (current `kernel.py`) | 205 (0.410) | 1.7e-5, modal ahead |
| relation-aware transitive | 269 (0.538) | 0.76, no significant difference |
| relation-blind transitive | 287 (0.574) | 0.077 |
| biology only (a measure, not a rule: no structure check) | 305 (0.610) | 0.0015, Opus ahead |

Source: [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md).

- **Not done [fact]:**
  - The hypothesize track measures format compliance only: `template:` saturates it at 1.0. That stays true until Phase B `discharge` exists.
  - The store is release-skewed and cannot be reproduced from upstream (§5).
  - `mg biolean fetch` is covered only by seam tests. It was not used to make the current `snapshots/go/`.
  - `--workers/--resume` has no spec or plan.
  - `claude:` runs under Claude Code's default system prompt, with no temperature control.
- Details: [biolean/README.md](biolean/README.md), [biolean/benchmark.md](biolean/benchmark.md).

## 2. Decisions waiting on the owner, ranked

All six are open. Nothing in these docs settles them.

| # | Decision | Why it ranks here | Doc |
|---|---|---|---|
| 1 | **Biolean edge rule.** Keep strict; add a relation-aware or a relation-blind transitive step; or keep `kernel.py` strict and report an untrusted-expander rate next to the strict one. | It flips the only Biolean headline (§1.3). If the prompt has to change to state the rule, the paid Opus run no longer matches the prompts. | [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md) |
| 2 | **Push the 56 local commits** to `origin/main`. | This disk holds the only copy of all Biolean work. CI has never run on it, and the GitHub README has no Biolean section. | [decisions/README.md](decisions/README.md) |
| 3 | **Archive local `master`** (`1b9399b`: 165 commits, 2026-06-08 to 2026-06-19, upstream gone, no history shared with `main`). | It holds the only copy of 15 June design docs: 9 specs and 6 plans covering the master graph, nf-core pipeline graph, planner, guardrail CLI, pipeline-chain evaluator, proteomics-MS, reproducible pipeline, single-cell and skill library. Deleting the branch loses them. | [decisions/README.md](decisions/README.md) |
| 4 | **Where results files live**: `opus.jsonl` and `modal.jsonl` (repo root, untracked, not ignored) and `bench-runs/2026-08-08-pilot/` (untracked, no ignore rule). Commit them as frozen records, or ignore them and back them up. | `opus.jsonl` is paid output that cannot be reproduced, and it is not backed up anywhere. | [decisions/README.md](decisions/README.md) |
| 5 | **`site/`**, a nested git repo inside the checkout (1 commit, no remote). Move it out, or add `/site/` to `.gitignore`. | `git add -A` would embed it as a gitlink. Its content is stale: hardcoded graph numbers, "134 benchmark checks passing", no Biolean. | [decisions/README.md](decisions/README.md) |
| 6 | **The guardrail**: keep it, fix it (for example, curate replicate floors for limma and edgeR), or retire it. | It gates 1 of 905 methods, while the root README still presents the repo as a guardrail substrate. | [decisions/README.md](decisions/README.md), [methods-graph.md](methods-graph.md) |

Smaller calls, also the owner's:
- Delete `opus.partial.jsonl`, which is redundant (§3).
- Delete the branch `codex/align-dogma-method-layer`. Its tree is identical to `849a071`, which is already on `main`.
- Everything else is in [BACKLOG.md](BACKLOG.md).

## 3. The checkout itself

Measured on 2026-09-22 with `git status --porcelain --ignored` and `du -sh`.

| Artifact | Git state | Size | What it is | Reproducible? | Losing it costs |
|---|---|---|---|---|---|
| `opus.jsonl` | untracked, not ignored | 1.0 MB (1,058,083 bytes), 500 rows | Biolean prove run by `claude:claude-opus-5`, written 2026-09-22 20:32: 205/500 hits | **No.** Paid model output. It can be re-scored from its `raw` field [GO]. | The only record of the Opus result. A re-run costs money and will not return the same replies. |
| `modal.jsonl` | untracked, not ignored | 908 KB, 500 rows | The `modal:` baseline on the same items: 264/500 | Yes, it is deterministic: `mg biolean bench run --model modal: --track prove --out <new-file>` [GO][items] gave a byte-identical file (`cmp`) on 2026-09-22 | About 13 s of rerun, as long as `biolean-bench/` and `snapshots/go/` survive. |
| `opus.partial.jsonl` | untracked, not ignored | 380 KB, 180 rows | A byte-identical 180-row prefix of `opus.jsonl`, saved mid-run | Redundant | Nothing. |
| `biolean-bench/` | ignored (`.gitignore:19`) | 1.8 MB | The frozen Biolean items (prove and hypothesize, 500 each), plus `manifest.json` and `modal.json`. Built 2026-09-22 18:29. | Yes, byte-identical: `mg biolean bench build --out biolean-bench` (about 40 s), but **only from the current `snapshots/go/`**. | Nothing while `snapshots/go/` survives. Without both, the two result files cannot be scored. |
| `bench-runs/2026-08-08-pilot/` | untracked, no ignore rule | 1.5 MB | The sequencing-benchmark pilot: 12 captured DAGs, 156 items, 6 results files, an ingest lock and a README | Partly. Scores re-derive exactly [DB]. The items do not: the pipeline clones were in a scratch dir that has been deleted, and rebuilding needs [net], Nextflow and Java. The Sonnet rows cannot be reproduced. | The only empirical run of the sequencing benchmark. |
| `site/` | untracked; a separate git repo | 764 MB (757 MB of it `node_modules`) | A Next.js (vinext) landing page, `methods-graph-story`. 1 commit, `e81508a` (2026-07-31), no remote. Predates Biolean. | The source cannot be reproduced. It has no remote, and no other copy is known. `node_modules` comes back with `npm install` [net]. | The site source, about 7 MB without `node_modules`. |
| `snapshots/` | ignored (`.gitignore:11`) | 129 MB in total: `modules` 64 MB, `go` 45 MB, `obi.owl` 9.5 MB, `biocontainers` 3.8 MB, `biotools` 2.6 MB, `stato.owl` 2.1 MB, `EDAM.tsv` 1.9 MB, `skills` 508 KB | Source snapshots, fetched 2026-06-18 (graph sources) and 2026-09-21 (GO) | Partly. `mg fetch --dest snapshots` [net] fetches today's upstream, not the 2026-06-18 pins, and never fetches `skills/`. `go/` cannot be re-fetched to the same release pair (§5). | The costliest loss in the checkout: the graph could no longer be rebuilt to the committed lock hash, the Biolean items could not be rebuilt, and no Biolean result file could be scored again. |
| `data/methods.kuzu` (+ `data/methods.kuzu.staging/`) | ignored (`.gitignore:6-7`) | 11 MB (+ 716 KB) | The built graph, dated 2026-06-19. Its hash equals `data/methods.lock.json`. | Yes: `mg rebuild` (about 12 s), as long as `snapshots/` (including `skills/`) is intact | 30 tests skip, and guardrail, explain, audit and the sequencing oracle stop working until it is rebuilt. |

Also ignored and local only: `.venv/`, `.superpowers/` (344 KB of agent scratch), `.claude/` and `.pytest_cache/`.

## 4. How to resume each thread

Run everything from the repo root.

**Biolean**
```bash
mg biolean bench coverage --items biolean-bench              # denominators and drop reasons; no store load
mg biolean bench score --results opus.jsonl                  # [GO] re-derive Opus from raw (~13 s); prints JSON, writes nothing
mg biolean bench score --results modal.jsonl                 # [GO]
mg biolean prove "UniProtKB:P04637 involved_in GO:0006915"   # [GO] ~12 s
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q tests/test_biolean_*.py   # 242 tests
```
A paid model run is tagged [net][paid][GO][items] and needs the `claude` CLI logged in. Always write to a **new** file, and pass `--resume` on every restart: without it, `--out` is truncated.
```bash
mg biolean bench run --model claude:<model> --track prove --workers 8 --resume --out <new-results-file>.jsonl
```

**Methods graph + guardrail**
```bash
mg audit --db data/methods.kuzu                                # [DB] ALL CHECKS PASSED
mg guardrail --method m:deseq2 --fact replicates_per_group=2   # [DB] BLOCKED, exit 3
mg explain --method m:deseq2                                   # [DB]
make verify                                                    # working-tree lock vs HEAD's lock; no rebuild
```
After editing the crosslink YAML, run `make rebuild` and commit the lock. `make rebuild` overwrites both `data/methods.kuzu` and `data/methods.lock.json`.

**Method-sequencing benchmark**
```bash
mg bench score --results bench-runs/2026-08-08-pilot/results/r12-sonnet-merged.jsonl        # [DB] selection_f1 0.3677
mg bench run --items bench-runs/2026-08-08-pilot/items --model gold: --out /tmp/seq-gold.jsonl # [DB] ceiling 1.0
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q tests/test_bench_*.py                     # 183 tests, under 2 s
```
`mg bench run` has no `--workers` or `--resume`. Building new items needs [net], Nextflow and Java, and `fetch.py:446` must be fixed first.

## 5. Traps

- **`mg` is a text editor.** On macOS a bare `mg` runs `/usr/bin/mg`. Define the alias (in scripts, the function in [README.md](README.md#running-the-cli)) or use `.venv/bin/methods-graph`. Committed files still say `mg`; for example, `data/methods.lock.json` records `"command": "mg rebuild"`.
- **There is no `python` on PATH.** Use `.venv/bin/python`. The `python3` on PATH is Homebrew's, not the venv.
- **CI does not enforce the DB-gated or snapshot-gated tests.** CI has neither `data/methods.kuzu` nor `snapshots/go/`, so 33 tests skip there: 30 need the DB, 2 need `snapshots/go`, 1 needs `quration`. The skipped tests include:
  - the gate-precision pin (`GATEABLE = {"m:deseq2"}`)
  - the exact 7-pair equivalence pin (`tests/test_bench_score.py:573`)
  - the rules-vs-graph parity test
  - both Biolean scale tests

  Biolean has also never run in CI at all, because it is unpushed.
- **The Biolean store cannot be reproduced from upstream.**
  - `snapshots/go/` has no `snapshot.json`.
  - Its OBO is `releases/2026-07-26`, but its GAF was built against GO 2026-04-27 (generated 2026-05-21).
  - The files predate the release-pinning fetch (`3398050`, 2026-09-21 15:49): the OBO and the GAF are from 2026-09-21 00:09, and the ECO mapping is from 10:23.
  - `mg biolean fetch` always downloads the current `goa_human.gaf.gz` (`fetch.py:738`) and by default overwrites the files in `snapshots/go/`. That changes the release identity. `bench run`, `bench score` and `--resume` then refuse the frozen items and every result file, with exit 2.
  - **Back up `snapshots/go/` before any fetch.**
- **`mg biolean bench run` without `--resume` truncates `--out`.** A mistyped restart throws away a paid run.
- **`mg audit --snapshot snapshots` exits 1** on a known Format mismatch (612 vs 2,100). It is not a regression. The gate is plain `mg audit --db data/methods.kuzu`.
- **`make rebuild` and `make rebuild-check` overwrite `data/methods.kuzu`.** Without `snapshots/skills/bioclaw`, which `fetch` never downloads, a rebuild quietly produces 0 Skill nodes and a hash mismatch.
- **Keyword resolution is fuzzy.** `mg guardrail --analysis salmon` resolves to `m:biohansel` and reports EVALUABLE with exit 0. Pass `m:` ids instead.
