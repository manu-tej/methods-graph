# Working in this repo

Orientation for coding agents. The [README](README.md) says what this project *is*; this
file says what will bite you. Everything here was learned by getting it wrong first.

Before changing anything, read [`docs/STATUS.md`](docs/STATUS.md) (what was built, measured
and open as of 2026-09-22) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (the whole-repo map,
data flows, CLI surface, and which tests CI actually gates).

## Run things this way

```bash
.venv/bin/python -m pytest -q          # 1,234 tests; ~1.5-2.5 min locally (see skips below)
.venv/bin/python -m methods_graph.cli  # the CLI; docs write it `mg`
make help                              # rebuild / verify / explain / audit / test (no bench/biolean targets)
```

**There is no `python` on PATH.** Bare `python` fails; `.venv/bin/python` works. The
`Makefile` auto-selects the venv, so `make test` is safe either way.

**There is no `mg` either.** Every doc writes the CLI as `mg`, but the installed console
script is `methods-graph` (`.venv/bin/methods-graph`), and on macOS a bare `mg` is
`/usr/bin/mg`, an unrelated emacs-like text editor. Define it first:
`alias mg='.venv/bin/python -m methods_graph.cli'`. `data/methods.lock.json`
(`"command": "mg rebuild"`), `catalog.ingest.yaml` and `ingest.example.yaml` use the same
shorthand.

The suite must pass with `OPENAI_API_KEY` unset — a test that reads the real environment
is a defect, and one shipped here before. Check both:

```bash
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q
```

```bash
.venv/bin/python -m methods_graph.cli biolean fetch --out snapshots/go   # NETWORK, ~47MB; pins GO to the GAF's release
.venv/bin/python -m methods_graph.cli biolean prove "UniProtKB:P04637 involved_in GO:0006915"
.venv/bin/python -m methods_graph.cli biolean bench build --out biolean-bench   # frozen items + manifest.json + modal.json
.venv/bin/python -m methods_graph.cli biolean bench run --model gold: --track prove --out gold.jsonl   # ceiling, must be 1.0
```

**Do not re-fetch `snapshots/go/` casually.** The copy on disk was not made by `biolean
fetch`: it has no `snapshot.json`, and its OBO (`releases/2026-07-26`) is newer than the
release the GAF names (`2026-04-27`). The frozen `biolean-bench/` items and the only paid
Biolean result (`opus.jsonl`) were built on that exact pair, and `run`/`score`/`--resume` refuse a
store whose release headers differ. Replacing it is an open owner decision, not cleanup.

**`biolean bench run` without `--resume` truncates `--out`** (`cli.py:1416`). A mistyped
restart of a `claude:`/`openai:` run throws away paid output. Every Biolean call that reads
the store re-parses `snapshots/go/` (about 13 s); there is no cached store.

```bash
.venv/bin/python -m methods_graph.cli biolean ledger verify --ledger <dir> --store snapshots/go --no-cache
.venv/bin/python tests/fixtures/biolean/ledger/make_fixtures.py   # regenerates every signed fixture (signed/, signed-variants/, sigs/) with the real ssh-keygen; never run by the suite
```

**Ledger fixtures are content-addressed signatures.** Changing the entry envelope, `methods_graph.__version__`, the ledger fixture base or a test scenario makes `fake_runner` fail naming a missing `sigs/*.sig`; re-run `make_fixtures.py` and commit.

## Layout

| Path | What lives there |
|---|---|
| `src/methods_graph/connectors/` | source parsers (EDAM, nf-core modules + pipelines, BioContainers, bio.tools, ontologies) |
| `src/methods_graph/crosslinks/` | hand-curated YAML tying methods to statistics, assumptions, diagnostics |
| `src/methods_graph/extract/` | queries over the built graph (`seed.py` holds `method_neighborhood`) |
| `src/methods_graph/provider/` | the quration-facing provider (`KuzuMethodsGraphProvider`) |
| `src/methods_graph/guardrail.py` | EVALUABLE / BLOCKED / NOT_EVALUABLE / FACTS_REQUIRED verdicts (exit 0 / 3 / 4 / 5) |
| `src/methods_graph/rules.py`, `hook.py`, `planner.py`, `explain.py` | DB-free YAML rule engine; Claude Code PreToolUse hook (not wired into any settings file); `suggest`; `explain` |
| `src/methods_graph/fetch.py`, `audit.py`, `ingest.py`, `pipeline.py` | source downloads (incl. Biolean's GO/GOA/ECO); graph invariant audit; `mg ingest` manifests; `mg rebuild` helpers (graph hash, lock, coverage diff) |
| `src/methods_graph/connectors/skills.py` | BioClaw `Skill` nodes; only *declared* tools mint gating `WRAPS` edges |
| `src/methods_graph/bench/` | the method-sequencing benchmark (see below) |
| `src/methods_graph/biolean/` | Biolean: a structural proof checker for GO claims (`kernel.py` is the trusted core, but it imports `store.py`, which pulls in the `obo`/`gaf`/`eco` parsers, and its verdict depends on `StaticFactStore`'s indexes, so the real trusted base is `kernel` plus `props`, `errors`, `store`, `obo`, `gaf` and `eco`, and the ledger adds `ed25519.py`, `sshsig.py` and `ledger/` to it because they decide what enters the store); `bench/` is its two-track benchmark; `mg biolean fetch|check|prove|goals|bench`; `ledger/` is the signed fact ledger (`mg biolean ledger init|append|verify|show`), with `ed25519.py` and `sshsig.py` the verify-only crypto beside it |
| `src/methods_graph/cli.py` | every subcommand; large, follow its `cmd_*` pattern |
| `docs/` | start at `docs/README.md`; `STATUS.md`, `ARCHITECTURE.md`, `BACKLOG.md`, `decisions/` |
| `docs/superpowers/specs/`, `plans/` | design specs and implementation plans; each opens with a status banner saying where the code diverged. None has ticked checkboxes, though all four plans are merged |

The rest (`kgx.py`, `pipeline_merge.py`, `workflow/`, `resolve/`, `graph/`, `schema/`, `types.py`) is mapped in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The graph, in numbers that matter

Query `data/methods.kuzu` read-only before assuming anything. Measured 2026-07-31 and
unchanged on 2026-09-22 (the DB was built 2026-06-19; its hash matches `data/methods.lock.json`):

- **905 methods**, 19,425 nodes, 32,757 edges
- **415** methods carry a `PERFORMS` edge to an EDAM Operation (46%)
- **49** carry an input `Data` node (5.4%); **39** carry an output `Data` node (4.3%)
- `INPUT`/`OUTPUT` total ~7,880 edges, but they are **dominated by `Format`, not `Data`**
  (7,744 target Format, 136 target Data) — and `classify_handoff` deliberately excludes
  Format joins because they produce false handoffs. Do not read the 7,880 figure as I/O
  coverage.
- The `mg rebuild` graph has **0 `Pipeline` nodes and 0 `DOWNSTREAM_OF` edges**. Only
  `mg ingest` builds those layers, and no ingest-built DB exists here, so `suggest` has no
  pipeline signal: `--have mod:star_align` returns `[]`, and `--have fmt:format_1930` lists
  entry modules all at count 0, in alphabetical order.

Coverage this thin is the single most common source of wrong conclusions here. Any metric
computed over the graph needs its denominator reported alongside it.

## Identifier schemes — the trap that has cost the most

Three vocabularies, and mixing them silently produces ids that reference nothing:

| Prefix | Example | Source of truth |
|---|---|---|
| `m:` | `m:star` | **`m:` + the method node's lowercased name.** Exact and total across all 905, no collisions. |
| `mod:` | `mod:star_align` | **`mod:` + the module's `meta.yml` `name` field.** Never the directory leaf. |
| `op:` / `data:` / `fmt:` | `op:operation_0292` | EDAM term ids |

Two specific rules:

1. **Module ids come from `meta.yml`, never the path's last segment.** `star/align` is
   `mod:star_align`; `mod:align` is an id no node carries. 80% of modules differ from
   their leaf, and 141 leaves collide (`index` ×32, `align` ×28). `iter_module_metas()`
   in `connectors/nfcore_pipeline.py` is the one definition — use it. **Test fixtures must
   use nested paths** like `star/align`; a fixture built only from single-segment paths
   cannot see this bug, which is how it survived four reviews once.

2. **Never use `resolve_method_ids()` to normalize a tool name.** It is a fuzzy keyword
   search: `resolve_method_ids(["STAR"])` returns `m:ea-utils`, `m:find`, `m:gedi` before
   `m:star`. Because `m:<lower(name)>` is exact, normalization is a lookup — see
   `bench/normalize.py`.

`mod:` → `m:` goes through `Module -WRAPS-> Method` (1,921 of 2,038 modules, 94%). The
other 6% resolve to nothing and must be **counted, never dropped silently.** All 117 of them
are nf-core *subworkflows*, because `rebuild` ingests the `subworkflows/` tree as `Module`
nodes too. Every real module wraps at least one Method (re-checked 2026-09-22 against
`snapshots/modules`: 117 unwrapped, 117 subworkflow names, 0 module names).

## The benchmark (`src/methods_graph/bench/`)

Measures whether an LLM knows which method to use and can sequence methods. Gold comes
from nf-core pipeline DAGs; the graph is the scoring **oracle**, not a contestant.

```
oracle.py     the ONLY file that knows a database exists; everything else takes an `Oracle`
normalize.py  free text and mod: ids -> m: method space
score.py      selection (step-set F1) / sequencing (over DAG edges) / validity / next-step
render.py     item -> prompt, and model reply -> list[str]
adapters.py   a contestant is exactly `(prompt: str) -> str`
baselines.py  gold (ceiling; the CI gate checks one hand-written fixture item) / modal / random
run.py        build items, run a model, score, re-score from retained raw output
```

```bash
mg bench build --pipelines snapshots/pipelines --out bench
mg bench coverage --items bench/items      # READ THIS BEFORE ANY SCORE
mg bench run --model openai:gpt-4o --out results.jsonl   # PAID; needs OPENAI_API_KEY
mg bench score --results results.jsonl     # re-derive from retained raw output
```

**No benchmark items are tracked in this repo.** `snapshots/pipelines/` does not exist, and
`/bench/` is gitignored. Building items needs Nextflow, Java and network. The only items
anywhere are the untracked 2026-08-08 pilot in `bench-runs/2026-08-08-pilot/`: 156 items
(10 whole_pipeline, 146 next_step) from 10 of 12 pipelines, built with **no** `NXF_VER` pin
(items record `nxf_ver: "unknown"`). Its clones are deleted, so it cannot be rebuilt
offline; its scores do re-derive byte-identically. Its Sonnet run was **not closed-book**
(it predates the `claude:` adapter fix), so do not quote those numbers as a model
measurement. The pinning policy is open: an old pin (23.10.0) reportedly broke the
installed Nextflow 26.04.3 and silently degraded the DAG to `io_inferred`. The preview
subprocess has no timeout (`fetch.py:446`; sarek hung about 55 min in the pilot).

On real items `gold:` scores 1.0 on selection, sequencing and next-step, but **0.505 on
validity** (coverage 0.128). Curated method-level I/O unions (e.g. `m:samtools` outputs
reads) and projecting each tool to its first occurrence produce false `BROKEN`s. The ceiling test (`tests/test_bench_score.py:413`) passes
because it scores the one whole_pipeline item in `tests/fixtures/bench/rnaseq.json`
against a dict-backed fixture oracle, not real items.

Design points that are load-bearing, not stylistic:

- **Sequencing scores `gold["edges"]`, never adjacent pairs of the sequence.** Parallel
  branches land adjacent in any linearization though nothing orders them, so an adjacency
  metric marks correct answers wrong.
- **Validity uses reachability, not consecutive pairs**, for the same reason — an answer is
  a linearization of a DAG, not a pipe. `BROKEN` means the input is only *net-produced*
  later (consumed before produced). A step that consumes and re-emits a type is not a net
  producer of it.
- **Equivalence classes are `operation ∩ input data type`, plus identity.** Operation alone
  credits `bwa` for spliced alignment. Identity must be a separate disjunct because 856 of
  905 methods have no curated input Data and would otherwise fail to match themselves.
  The relation is **exactly 7 non-identity pairs** across the whole graph and is pinned by
  a test that enumerates all of them — if a re-curation adds an eighth, that test fails.
  That test (`tests/test_bench_score.py:573`) is DB-gated, so it fails **locally only**;
  CI skips it.
  Two bridging EDAM operations are denylisted in `score.py` because they joined unrelated
  tools (`operation_0236` bridged fastqc/salmon; `operation_2495` bridged affy/gsea).
- **`match_steps` orders candidates identity-first.** Kuhn's returns *a* maximum matching;
  without identity preference two mutually-equivalent tools get swapped and a verbatim-
  correct answer scores 0.5 on ordering.
- **Undefined is `None`, never `0.0`.** "Ordered nothing correctly" and "there was nothing
  to order" are different facts.
- **`UNKNOWN` is never counted as valid**, and always ships with a coverage denominator.

## Testing standards this repo enforces

One plan here produced **eight tests that passed against the bug they claimed to catch.**
Every one was caught by review, none by the author. The recurring shapes:

- a symmetric fixture where the buggy and correct algorithms agree (greedy vs maximum
  matching on a K2,2 case)
- singleton buckets where two aggregation schemes coincide
- a test asserting over a code path that never reaches the thing it names
- assertions guaranteed by a closure's *shape* rather than its logic
- ambient environment making a test green locally and red in CI

**The discipline that works is mutation.** Before accepting a test, break the
implementation in the specific way the test's name claims to detect, and require the test
to fail. If it still passes, the test is decoration. State the check in your PR/report.

Other conventions:

- Benchmark tests are `tests/test_bench_*.py`. Note `tests/test_adapters.py` already exists
  for `extract/adapters.py` — the benchmark's is `tests/test_bench_adapters.py`.
- **DB-gated tests skip when `data/methods.kuzu` is absent**, which it is in CI (`data/*.kuzu`
  is gitignored). Anything guarded that way is **not** enforced by CI — don't claim it is.
  The local `1 skipped` is **not** the DB: it is `tests/test_provider.py:174`,
  `importorskip("quration")`. 1201 passed / 33 skipped in a CI-like checkout (30 DB-gated,
  2 snapshot-gated, 1 quration); the main checkout with `data/methods.kuzu` and
  `snapshots/go/` present skips 1. CI runs Python 3.12; the local venv is 3.14.6.
- **Snapshot-gated tests** (`tests/test_biolean_scale.py`, `tests/test_biolean_bench_scale.py`)
  skip when `snapshots/go/` is absent, which it is in CI. Same rule: not enforced by CI.
- Network and subprocess calls take injectable seams (`runner=subprocess.run`,
  `http_post=`), following `fetch.py`. No test may hit the network or spawn a real process.

## Invariants

- **No new runtime dependencies.** `pyproject.toml` stays `kuzu==0.11.3`, `polars`, `pyyaml`,
  `networkx`. Use `urllib.request` over `requests`; stdlib over a package.
- **`kuzu` is pinned deliberately** — 0.11.x has schema/COPY/Cypher behaviour the loader and
  extract layers were verified against. Do not float it.
- **Determinism.** Sort every set iteration; seed every RNG; two runs produce byte-identical
  output. Cypher queries carry `ORDER BY`; JSON is written `sort_keys=True`. This is the
  rule, not yet the state everywhere. `extract/seed.py:48-79` and
  `provider/quration_provider.py:128-129` issue Cypher without `ORDER BY`. `cli.py:67, 1158,
  1576, 1603` (`suggest`, `skills --coverage`, `guardrail`/`guardrail-chain --json`) dump JSON
  without `sort_keys`. Fix them when you touch them; don't copy them.
- **Nothing is dropped silently.** Unresolvable ids, unparseable replies, dropped edges,
  adapter failures — each gets a counted field in the output.
- After touching connectors, crosslinks, or the loader, **rebuild first**, then audit:
  `make rebuild` (or build into a scratch path), then `mg audit --db <that db>`. `audit`
  only reads an existing DB, so auditing the old `data/methods.kuzu` checks the old graph.
  Also note 9 of its 26 invariants pass vacuously on the rebuild graph: it has no
  `Pipeline`, `ExecutionSpec` or `Modality` nodes and no `DOWNSTREAM_OF`, `HAS_MODULE`,
  `RUNS_AS` or `HAS_MODALITY` edges for them to check.

## CI reality

`.github/workflows/ci.yml` has two jobs:

- **`test`** — runs on every push to `main` and every PR. `pytest -q`, nothing else. This is
  the real gate. (The workflow's comment says "tests + lock-schema validity"; there is no
  separate lock step. Lock validity is `tests/test_pipeline.py:120`, which returns silently
  when the CWD-relative lock path is missing.)
- **`rebuild-verify`** — weekly/dispatch only. Reports upstream drift *informationally* and
  hard-fails only on genuine non-determinism. The lock records source pins that `fetch`
  does not replay: `fetch_nfcore` takes no ref and reuses an existing clone without
  updating it; the BioContainers and bio.tools APIs are not pinned at all (`{}` in the
  lock); EDAM, STATO and OBI come from unversioned "latest" URLs; and the skill library
  (`snapshots/skills/bioclaw`) is never fetched, although `rebuild` reads it and silently
  builds 0 `Skill` nodes without it. Drift is expected until that gap is closed. The
  comment block in the workflow explains the first two. Also, `compute_graph_hash`
  (`pipeline.py:24-28`) trusts Kuzu's `ORDER BY`, which occasionally returns the same edges
  out of order, so a single hash MISMATCH (here, in `rebuild --check`, or in a one-off
  re-hash) needs a rerun before it counts ([`docs/BACKLOG.md`](docs/BACKLOG.md) M21).
- **The Biolean commits are on `origin/main`.** They were pushed on 2026-09-23 and
  2026-09-26, and the `test` job has run on them. Docs dated 2026-09-22 that call them
  unpushed predate that.

## Process

Design work goes through `superpowers:brainstorming` → spec in `docs/superpowers/specs/` →
`superpowers:writing-plans` → plan in `docs/superpowers/plans/` → execution. Plans carry
complete code and per-task tests; read the plan's Global Constraints before starting a task.
