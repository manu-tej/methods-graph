# Working in this repo

Orientation for coding agents. The [README](README.md) says what this project *is*; this
file says what will bite you. Everything here was learned by getting it wrong first.

## Run things this way

```bash
.venv/bin/python -m pytest -q          # the suite (~772 tests, ~75s)
.venv/bin/python -m methods_graph.cli  # the CLI, aka `mg`
make help                              # rebuild / verify / explain / audit / test
```

**There is no `python` on PATH.** Bare `python` fails; `.venv/bin/python` works. The
`Makefile` auto-selects the venv, so `make test` is safe either way.

The suite must pass with `OPENAI_API_KEY` unset — a test that reads the real environment
is a defect, and one shipped here before. Check both:

```bash
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q
```

## Layout

| Path | What lives there |
|---|---|
| `src/methods_graph/connectors/` | source parsers (EDAM, nf-core modules + pipelines, BioContainers, bio.tools, ontologies) |
| `src/methods_graph/crosslinks/` | hand-curated YAML tying methods to statistics, assumptions, diagnostics |
| `src/methods_graph/extract/` | queries over the built graph (`seed.py` holds `method_neighborhood`) |
| `src/methods_graph/provider/` | the quration-facing provider (`KuzuMethodsGraphProvider`) |
| `src/methods_graph/guardrail.py` | EVALUABLE / BLOCKED / NOT_EVALUABLE / FACTS_REQUIRED verdicts |
| `src/methods_graph/bench/` | the method-sequencing benchmark (see below) |
| `src/methods_graph/cli.py` | every subcommand; large, follow its `cmd_*` pattern |
| `docs/superpowers/specs/`, `plans/` | design specs and implementation plans |

## The graph, in numbers that matter

Query `data/methods.kuzu` read-only before assuming anything. Measured 2026-07-31:

- **905 methods**, 19,425 nodes, 32,757 edges
- **415** methods carry a `PERFORMS` edge to an EDAM Operation (46%)
- **49** carry an input `Data` node (5.4%); **39** carry an output `Data` node (4.3%)
- `INPUT`/`OUTPUT` total ~7,880 edges, but they are **dominated by `Format`, not `Data`** —
  and `classify_handoff` deliberately excludes Format joins because they produce false
  handoffs. Do not read the 7,880 figure as I/O coverage.

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
other 6% resolve to nothing and must be **counted, never dropped silently.**

## The benchmark (`src/methods_graph/bench/`)

Measures whether an LLM knows which method to use and can sequence methods. Gold comes
from nf-core pipeline DAGs; the graph is the scoring **oracle**, not a contestant.

```
oracle.py     the ONLY file that knows a database exists; everything else takes an `Oracle`
normalize.py  free text and mod: ids -> m: method space
score.py      selection (step-set F1) / sequencing (over DAG edges) / validity / next-step
render.py     item -> prompt, and model reply -> list[str]
adapters.py   a contestant is exactly `(prompt: str) -> str`
baselines.py  gold (ceiling, a CI gate) / modal / random
run.py        build items, run a model, score, re-score from retained raw output
```

```bash
mg bench build --pipelines snapshots/pipelines --out bench
mg bench coverage --items bench/items      # READ THIS BEFORE ANY SCORE
mg bench run --model openai:gpt-4o --out results.jsonl
mg bench score --results results.jsonl     # re-derive from retained raw output
```

**No benchmark items ship in this repo.** `snapshots/pipelines/` is empty; populating it
needs Nextflow, Java, network, and per-release `NXF_VER` pinning across ~142 pipelines.

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
  is gitignored). That is the `1 skipped` in every run. Anything guarded that way is **not**
  enforced by CI — don't claim it is.
- Network and subprocess calls take injectable seams (`runner=subprocess.run`,
  `http_post=`), following `fetch.py`. No test may hit the network or spawn a real process.

## Invariants

- **No new runtime dependencies.** `pyproject.toml` stays `kuzu==0.11.3`, `polars`, `pyyaml`,
  `networkx`. Use `urllib.request` over `requests`; stdlib over a package.
- **`kuzu` is pinned deliberately** — 0.11.x has schema/COPY/Cypher behaviour the loader and
  extract layers were verified against. Do not float it.
- **Determinism.** Sort every set iteration; seed every RNG; two runs produce byte-identical
  output. Cypher queries carry `ORDER BY`; JSON is written `sort_keys=True`.
- **Nothing is dropped silently.** Unresolvable ids, unparseable replies, dropped edges,
  adapter failures — each gets a counted field in the output.
- Run `mg audit --db data/methods.kuzu` after touching connectors, crosslinks, or the loader.

## CI reality

`.github/workflows/ci.yml` has two jobs:

- **`test`** — runs on every push to `main` and every PR. `pytest -q`, nothing else. This is
  the real gate.
- **`rebuild-verify`** — weekly/dispatch only. Reports upstream drift *informationally* and
  hard-fails only on genuine non-determinism. The lock records source pins that `fetch`
  does not replay (`fetch_nfcore` takes no ref; the BioContainers and bio.tools APIs are
  not pinned at all), so drift is expected until that gap is closed. The comment block in
  the workflow explains it.

## Process

Design work goes through `superpowers:brainstorming` → spec in `docs/superpowers/specs/` →
`superpowers:writing-plans` → plan in `docs/superpowers/plans/` → execution. Plans carry
complete code and per-task tests; read the plan's Global Constraints before starting a task.
