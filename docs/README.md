# methods-graph docs

> **What this is:** the entry point to the docs: a reading order, one line per doc, how to run the CLI, and three checks that the checkout is healthy.
> **Status:** as of 2026-09-22 (local `main` at `6b28222`, 56 commits ahead of `origin/main`). Those commits have since been pushed, and work has been paused since October 2026; see the 2026-11-09 note at the top of [STATUS.md](STATUS.md).
> **Read next:** [STATUS.md](STATUS.md).

## Four questions, four places to look

| If you need to know | Read |
|---|---|
| What state everything is in | [STATUS.md](STATUS.md) |
| What is waiting for a decision | [STATUS.md](STATUS.md) §2 (the ranked six), then [decisions/README.md](decisions/README.md) Part 2 (25 logged open decisions); 18 smaller ones are marked "not yet in the log" in [BACKLOG.md](BACKLOG.md) |
| How to run everything | [Running the CLI](#running-the-cli) below; then [STATUS.md](STATUS.md) §4 (how to resume each thread) and [ARCHITECTURE.md](ARCHITECTURE.md) §7 (every subcommand and flag) |
| Why the project looks the way it does | [HISTORY.md](HISTORY.md) (guardrail, then sequencing benchmark, then Biolean, and why), then [decisions/README.md](decisions/README.md) Part 1 (what the owner fixed and why) |

## Coming back fresh: reading order

1. [STATUS.md](STATUS.md): the state of the three projects, the owner's decision queue, what is on disk, and how to resume. One page.
2. [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md): the open decision that blocks the Biolean headline. Read it before quoting any Biolean number.
3. [decisions/README.md](decisions/README.md): the other owner decisions, both the fixed ones and the open ones.
4. The docs for the project you are resuming:
   - Methods graph and guardrail: [methods-graph.md](methods-graph.md)
   - Method-sequencing benchmark: [method-sequencing-benchmark.md](method-sequencing-benchmark.md)
   - Biolean: [biolean/README.md](biolean/README.md), then [biolean/benchmark.md](biolean/benchmark.md), then [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md)
5. Background, as needed: [ARCHITECTURE.md](ARCHITECTURE.md), [HISTORY.md](HISTORY.md), [BACKLOG.md](BACKLOG.md), [GLOSSARY.md](GLOSSARY.md).

Coding agents should read [../CLAUDE.md](../CLAUDE.md) (the traps) first, then [ARCHITECTURE.md](ARCHITECTURE.md).

## Every doc, one line each

| Doc | What it answers |
|---|---|
| [README.md](README.md) | This index: reading order, the `mg` definition, health checks. |
| [STATUS.md](STATUS.md) | Where everything stands on 2026-09-22, on one page. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The whole-repo map, data flows, CLI surface, tests, and what CI actually gates. |
| [HISTORY.md](HISTORY.md) | A dated timeline, and why the direction changed (guardrail, then sequencing benchmark, then Biolean). |
| [methods-graph.md](methods-graph.md) | The Kuzu graph and the guardrail as built: what they cover, what they gate, what they don't. |
| [method-sequencing-benchmark.md](method-sequencing-benchmark.md) | The nf-core sequencing benchmark as built, the 2026-08-08 pilot, and its blockers. |
| [biolean/README.md](biolean/README.md) | The Biolean guide: kernel, rules, error codes, derivation format, CLI. |
| [biolean/benchmark.md](biolean/benchmark.md) | The two-track Biolean benchmark as built, and how to run a paid model safely. |
| [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md) | The Opus 5 prove-track results (500 items), under the strict and the alternative edge rules. |
| [biolean/ledger.md](biolean/ledger.md) | The ledger as built: format, CLI contract, error table, what verify proves. |
| [decisions/README.md](decisions/README.md) | The decision log: decisions the owner has fixed, and decisions still open. |
| [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md) | The open memo on whether the Biolean kernel should accept transitive `is_a`/`part_of` steps. |
| [BACKLOG.md](BACKLOG.md) | Every open question and loose end, grouped and prioritized. |
| [GLOSSARY.md](GLOSSARY.md) | Terms and acronyms. |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Upstream data sources, attribution and licences. |
| [REFERENCES.md](REFERENCES.md) | External papers the project cites (arXiv:2606.04494), and the rule against committing paper bundles. |
| [superpowers/specs/](superpowers/specs/) | Design specs on `main`: the sequencing benchmark (2026-07-30) and Biolean (2026-09-21); and the Biolean ledger spec (2026-09-25), tracked on branch `worktree-biolean-ledger`, whose banner lists where the code follows the plan instead. The June specs are not here; see [STATUS.md](STATUS.md) §2. |
| [superpowers/plans/](superpowers/plans/) | The four earlier implementation plans, all merged, and the Biolean ledger plan (2026-09-25), implemented on branch `worktree-biolean-ledger`; its banner records the commits. Their checkboxes were never ticked, so read the merge commits, not the boxes. |
| [../README.md](../README.md) | The public project README. |
| [../CLAUDE.md](../CLAUDE.md) | Orientation for coding agents: traps, invariants, testing discipline. |

## Running the CLI

- **There is no `python` on PATH.** Use `.venv/bin/python`. The `python3` on PATH is Homebrew's, not the project venv.
- **The installed console script is `methods-graph`** (`.venv/bin/methods-graph`, pyproject.toml:25). There is no `mg` binary.
- **On macOS, a bare `mg` runs `/usr/bin/mg`, an emacs-like text editor.** Every doc still writes `mg` as shorthand. Define it once per shell, from the repo root:

```bash
alias mg='.venv/bin/python -m methods_graph.cli'   # the path is relative: run from the repo root
# or, the same thing:  alias mg='.venv/bin/methods-graph'
```

- The alias works only in an interactive shell. In `bash -c` or `zsh -c`, which is how scripts and coding agents run commands, it does not expand, and `mg` silently runs `/usr/bin/mg` instead (checked on 2026-09-22). Use a function there:

```bash
mg() { .venv/bin/python -m methods_graph.cli "$@"; }
```

- A fresh clone with no venv: `uv sync --extra dev`, taken from the root README's Quickstart. It was not re-run on 2026-09-22.
- Every subcommand and flag, with what each needs and writes: [ARCHITECTURE.md](ARCHITECTURE.md) §7. Exit codes are in the same section.
- Tags used for commands in these docs:

| Tag | Needs | In a fresh clone? |
|---|---|---|
| [DB] | `data/methods.kuzu` (gitignored; build it with `mg rebuild` from `snapshots/`) | no |
| [GO] | `snapshots/go/` (gitignored; three files, about 47 MB, which `du -sh` shows as 45M; see the traps in [STATUS.md](STATUS.md) §5) | no |
| [items] | `biolean-bench/` (gitignored; `mg biolean bench build`, needs [GO]) | no |
| [net] | network access | n/a |
| [paid] | paid model calls (`claude:` or `openai:` contestants) | n/a |

## Is the checkout healthy? Three commands

Run all three from the repo root, with the `mg` alias defined. Expected output was measured on 2026-09-22 at `6b28222`.

### 1. Full test suite

```bash
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q
```

| Environment | Expected last line | Skips |
|---|---|---|
| This checkout (DB and `snapshots/go` present) | `1013 passed, 1 skipped` | 1: `tests/test_provider.py:174`, because the optional `quration` package is not installed |
| No DB, no `snapshots/go` (what CI sees) | `981 passed, 33 skipped` | 30 need the DB, 2 need `snapshots/go`, 1 needs `quration` |

- 1,014 tests are collected from 71 files. Runtime was 88.57 s, 95.95 s and 133.30 s in three runs on 2026-09-22.
- Any other count means something changed. Add `-rs` to list the skip reasons.
- `OPENAI_API_KEY` is unset on purpose. The suite must pass without it ([../CLAUDE.md](../CLAUDE.md)).
- pytest may print `PytestWarning: (rm_rf) error removing ...` for directories under the shared pytest temp dir. That is noise, not a failure.

### 2. Biolean gold ceiling [GO] [items]

```bash
mg biolean bench run --model gold: --track prove --out /tmp/mg-gold.jsonl
```

- Exit 0, about 13 s. Most of that time is loading the store.
- The JSON summary on stdout must show `"n_rows": 500`, `"n_errors": 0`, `"n_unparsed": 0`, and under `"prove"` both `"hit_rate": 1.0` and `"n_hits": 500`. `release.go_basic_data_version` must be `"releases/2026-07-26"`.
- stderr prints a `load_report` line. `"term_obsolete": 162` is expected, because the store is release-skewed (see [STATUS.md](STATUS.md) §5).
- Anything below 1.0 means the kernel, the store or the items changed.
- `--out` points at `/tmp` so the run does not leave a new untracked file in the repo. **Never point `--out` at an existing results file.** Without `--resume`, `bench run` truncates it.

### 3. Graph audit [DB]

```bash
mg audit --db data/methods.kuzu          # same as: make audit
```

- Exit 0, under 1 s. The final block reads `AUDIT RESULT: ALL CHECKS PASSED`. The output also includes `node ids unique (19425 nodes / 19425 distinct ids)` and `methods_total: 905`.
- Do **not** add `--snapshot snapshots`. That form exits 1 on a known Format mismatch (612 Format terms in EDAM vs 2,100 Format nodes in the graph). This is a known issue, not a regression. See [methods-graph.md](methods-graph.md).
- Stronger, optional: rebuild into a scratch directory and compare the hash with the committed lock. It needs `snapshots/`, including `snapshots/skills/bioclaw`, and takes about 12 s. It leaves the repo untouched:

```bash
rm -rf /tmp/mg-rebuild && mkdir -p /tmp/mg-rebuild && cp data/methods.lock.json /tmp/mg-rebuild/ \
  && mg rebuild --db /tmp/mg-rebuild/methods.kuzu --check
# expected: --check: graph hash matches committed lock (sha256:c6940e39883fb7aa...)
```

- If it prints `MISMATCH`, run it once more before concluding anything. The hash computation trusts Kuzu's `ORDER BY` and occasionally reads the same edges in a different order ([BACKLOG.md](BACKLOG.md) M21).
