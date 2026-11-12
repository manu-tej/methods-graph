# Biolean Plan 2 — Two-track Benchmark (`mg biolean bench`)

> **Status as of 2026-09-22: implemented and merged in `b0f80c4` (2026-09-22).** None of the 49 step checkboxes was ticked, but every task landed. Later changes outside this plan: the closed-book `claude:` adapter (`128a8c6`, merged `894072d`) and `bench run --workers N --resume` (`4c2e3b9` plus four fixes, merged `6b28222`). Neither has a spec or plan.
>
> As-built references: [`docs/biolean/benchmark.md`](../../biolean/benchmark.md) and the first paid run, [`docs/biolean/results-2026-09-22-opus-5.md`](../../biolean/results-2026-09-22-opus-5.md). Spec-level divergences are listed in the banner of [`specs/2026-09-21-biolean-design.md`](../specs/2026-09-21-biolean-design.md). Plan-specific ones:
>
> - Deviation 3 is load-bearing. The frozen items were built on a `snapshots/go/` with no manifest and a release-skewed pair (OBO `2026-07-26`, GAF built against `2026-04-27`). Re-fetching would make `run`/`score` refuse them.
> - The `--workers` help says rows are put in item order when the run completes. That holds for a fresh run; after `--resume` the file holds kept rows first, then new rows.
> - `bench run` without `--resume` truncates an existing `--out` (`cli.py:1416`).
> - `--since` is validated after the store load (`cli.py:1357-1359`), not before it.
> - The `claude:` contestant runs under Claude Code's default system prompt with no temperature control; `openai:` is temperature 0. Cross-provider comparisons are not like for like.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A frozen, re-scorable benchmark over GO + human GOA with two tracks — *prove* (hide the exact annotation rows, ask for a closed-book re-derivation) and *hypothesize* (hide the whole subtree, measure format compliance only) — with gold / random / modal / template baselines and `mg biolean bench build|coverage|run|score`.

**Architecture:** `biolean/bench/items.py` enumerates the population from a `FactStore`, applies an injectable hider per track, builds items over `MaskedFactStore`, fits the modal prior, samples, applies the live cut, and freezes everything to disk with every count in `manifest.json`. `biolean/bench/render.py` turns an item into the closed-book prompt and a model reply into a JSON object. `biolean/bench/score.py` scores one row by re-running the kernel over the item's masked store and aggregates with denominators. `biolean/bench/baselines.py` provides the four baselines as `(prompt) -> str` adapters. `biolean/bench/run.py` renders, calls, scores, streams rows, and rescores from rows alone. Adapters are reused verbatim from `methods_graph.bench.adapters`.

**Tech Stack:** Python 3.12+ stdlib only (`json`, `random`, `functools`, `pathlib`, `collections`). No new runtime dependencies. pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-biolean-design.md` §6 (benchmark), §7 (layout and CLI rows for `bench`), §9 "Benchmark" and "CLI" tables. Plan 1 (`docs/superpowers/plans/2026-09-21-biolean-plan-1-kernel.md`) is merged at `7bc79ef`; this plan builds on it and never edits `kernel.py` except in Task 1's prep refactor, which is guarded by the existing kernel tests and the committed golden verdict.

## Global Constraints

- No new runtime dependencies: `pyproject.toml` stays `kuzu==0.11.3`, `polars`, `pyyaml`, `networkx`. Everything here is stdlib.
- Determinism: sort every set iteration; every list written to disk is sorted by the key this plan names; JSON is written `sort_keys=True`; the only RNG is `random.Random(seed)` and its seed is recorded in `manifest.json`.
- Nothing dropped silently: every filter has a counter that ships even when zero; `hit_rate` and every other rate ships beside its denominator; undefined is `None`, never `0.0` or `False`.
- The kernel is the only trusted code. The scorer never reimplements a rule: it calls `elaborate` + `check` over `MaskedFactStore(store, item.hidden)` and reads the verdict.
- Identifier discipline: `method_resolves` goes through `methods_graph.bench.normalize.normalize_name` (an exact `m:` lookup), never `resolve_method_ids`.
- No test hits the network or spawns a process; adapters used in tests are plain callables. The suite passes with `OPENAI_API_KEY` unset: `env -u OPENAI_API_KEY $PYTEST -q`.
- Test discipline: before accepting a test, apply the mutation its step names and confirm the test fails; write "mutation checked: <what>" in the commit body. A rejection assertion names the `(step, code)` pair or the exact `error_codes` list, never the verdict string alone.
- Run tests as `$PYTEST` where, in the main checkout, `PYTEST=".venv/bin/python -m pytest"` and, in a worktree without its own venv, `PYTEST="env PYTHONPATH=src <main-checkout>/.venv/bin/python -m pytest"` (the editable install points at the main checkout's `src`; verify with `python -c "import methods_graph; print(methods_graph.__file__)"`).
- The worktree guard rejects compound Bash commands (`&&`, `;`, heredocs) and commands whose text names `git`/`github`; run one plain command per call and write helper scripts with the Write tool.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Nothing lands on `main` without the owner.
- Spec deviations this plan makes deliberately, each recorded in the spec by Task 1 so spec and code agree:
  1. `FactStore` gains `subjects() -> tuple[str, ...]` (the population needs to enumerate; the protocol had no enumeration).
  2. Both prompts end with a fixed `Format:` block describing the derivation JSON. The spec's prompt text is otherwise verbatim; a closed-book model cannot emit a format it has never seen, and a benchmark where every reply is `UNPARSED` measures nothing.
  3. The store's release identity is read from the files themselves (`data-version:` in the OBO header; `!date-generated:` and `!go-version:` in the GAF header), not from `snapshots/go/snapshot.json`: the shipped snapshot was fetched before the manifest existed and has none, and the headers are the ground truth the manifest copies anyway.
  4. `depth` on a prove row and `gold_depth` on a prove item both count **propagation steps** (used steps minus the axiom), so `mean_depth` over hits is comparable with `gold_depth` buckets `1, 2, 3, 4+` and with the `goals` CLI's `depth: 0` for a direct annotation.
  5. Layout: `biolean/bench/render.py` holds `render_prompt` and `parse_reply`, mirroring `bench/render.py`; `--items DIR` names the directory `bench build --out` wrote (it holds `items/`, `manifest.json`, `modal.json`); `--per-track` defaults to `500`.
  6. Every results row carries `items_manifest: {"release": ..., "since": ...}` so `score --results FILE --store DIR` can refuse a mismatched store and echo `since` with nothing but the rows.
  7. `goal_not_statable` counts each dropped triple once, under the alphabetically first error code of its rejected sorry, and ships `goal_not_statable_total`.

## File structure

| File | Responsibility |
|---|---|
| `src/methods_graph/biolean/kernel.py` (modify, Task 1) | `propagating_parents`, `propagating_children` — the one propagation predicate; `ancestors`/`descendants` rewritten over them |
| `src/methods_graph/biolean/tactics.py` (modify, Task 1) | `_live_parents` and `applicable` use the kernel predicate; `applicable` refuses an unknown/obsolete target |
| `src/methods_graph/biolean/store.py` (modify, Task 1) | `subjects()` on the protocol and both implementations |
| `src/methods_graph/biolean/bench/__init__.py` | package marker |
| `src/methods_graph/biolean/bench/render.py` | `claim_text`, `render_prompt`, `parse_reply`, `organism`, the two templates and `FORMAT_BLOCK` |
| `src/methods_graph/biolean/bench/items.py` | `population`, `hide_exact`, `hide_subtree`, `visible_descendants`, `prove_items`, `hypothesize_items`, `BuildError`, `apply_since`, `sample`, `fit_modal`, `build_items`, `load_items`, `read_release` |
| `src/methods_graph/biolean/bench/score.py` | `parse`-boundary constants, `score_prove`, `score_hypothesize`, `score_row`, `failure_row`, `summarize` |
| `src/methods_graph/biolean/bench/baselines.py` | `gold`, `random`, `modal`, `template`; `is_baseline_spec`, `baseline_adapter` |
| `src/methods_graph/biolean/bench/run.py` | `run_items`, `rescore`, `release_mismatch` |
| `src/methods_graph/cli.py` (modify) | `mg biolean bench build|coverage|run|score`, `_cmd_biolean_bench`, `_biolean_resolver` |
| `tests/biolean_fixture.py` (modify) | `copy_store(dest)`, `reversed_store()` |
| `tests/test_biolean_store.py`, `tests/test_biolean_tactics.py`, `tests/test_biolean_kernel.py` (modify, Task 1) | `subjects()`, predicate, `applicable` obsolete guard |
| `tests/test_biolean_bench_render.py`, `_items.py`, `_score.py`, `_baselines.py`, `_run.py`, `_cli.py`, `_scale.py` | one test module per source module, plus the snapshot-gated scale check |
| `CLAUDE.md`, `README.md` (modify, Task 9) | run lines, test count, layout row |
| `docs/superpowers/specs/2026-09-21-biolean-design.md` (modify, Task 1) | the seven deviations above |

## Fixture facts this plan relies on (from `tests/fixtures/biolean/`, unchanged)

Population over the fixture store (24 annotations): 15 eligible rows, **13 eligible triples**; drop counts `negated 2`, `qualifier_out_of_scope 1`, `evidence_class 4` (three IEA rows and the `XYZ` row), `object_type 0`, `term_not_in_ontology 1` (GO:0009999), `term_alt_id 0`, `term_obsolete 1` (P00005 at GO:0000110).

Prove-eligible after `hide_exact` (exactly 6, sorted by id), each with `gold_depth == 1`:

| Item id | hidden rows | gold |
|---|---|---|
| `prove/UniProtKB:P00001/involved_in/GO:0000005` | B IDA | axiom A, `is_a` A→B |
| `prove/UniProtKB:P00001/involved_in/GO:0000010` | C IDA (2019-01-01), C IEA (2026-03-01) | axiom B, `is_a` B→C |
| `prove/UniProtKB:P00001/involved_in/GO:0000020` | D IMP | axiom A, `part_of` A→D |
| `prove/UniProtKB:P00002/involved_in/GO:0000050` | Y IDA | axiom X, `is_a` X→Y |
| `prove/UniProtKB:P00002/involved_in/GO:0000060` | T IMP | axiom Y, `is_a` Y→T |
| `prove/UniProtKB:P00003/enables/GO:0000200` | MF1 IDA | axiom MF2, `is_a` MF2→MF1 |

`not_rederivable == 7`. Hypothesize-eligible: all 13 triples; `goal_not_statable` is empty on the fixture. Term constants used below come from `tests/test_biolean_kernel.py`: `A, B, C, D = GO:0000030, GO:0000005, GO:0000010, GO:0000020`; `X, Y, T = GO:0000040, GO:0000050, GO:0000060`; `MF1, MF2 = GO:0000200, GO:0000210`; `P1..P7 = UniProtKB:P00001..P00007`; `TAX = NCBITaxon:9606`.

---

### Task 1: Prep — one propagation predicate, `subjects()`, spec deviations

**Files:**
- Modify: `src/methods_graph/biolean/kernel.py` (closure helpers section)
- Modify: `src/methods_graph/biolean/tactics.py` (`_live_parents`, `applicable`)
- Modify: `src/methods_graph/biolean/store.py` (`FactStore`, `StaticFactStore`, `MaskedFactStore`)
- Modify: `docs/superpowers/specs/2026-09-21-biolean-design.md`
- Test: `tests/test_biolean_kernel.py`, `tests/test_biolean_tactics.py`, `tests/test_biolean_store.py`

**Interfaces:**
- Produces: `kernel.propagating_parents(term_id, store) -> tuple[tuple[str, str], ...]` — `(parent, relation)` pairs one propagation step above `term_id`: relation in `PROPAGATING_RELATIONS`, parent live and in the same namespace, sorted by `(parent, relation)`; empty for an unknown term. `kernel.propagating_children(term_id, store) -> tuple[tuple[str, str], ...]` — the exact dual, sorted by `(child, relation)`. `FactStore.subjects() -> tuple[str, ...]` — every subject with at least one annotation, sorted; `MaskedFactStore.subjects()` delegates unmasked.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_biolean_store.py`:

```python
def test_subjects_are_sorted_and_the_masked_universe_is_whole():
    s = mini_store()
    subjects = s.subjects()
    assert list(subjects) == sorted(subjects) and len(subjects) == 9
    assert subjects[0] == "UniProtKB:P00001" and subjects[-1] == "UniProtKB:P00009"
    m = MaskedFactStore(s, frozenset(a.id for a in s.annotations("UniProtKB:P00005")))
    assert m.subjects() == subjects                  # a fully hidden subject is still a subject
```

Append to `tests/test_biolean_kernel.py`:

```python
def test_propagating_parents_and_children_are_duals_over_the_fixture():
    from methods_graph.biolean.kernel import propagating_children, propagating_parents
    # A's parents: is_a B, part_of C, part_of D — sorted by parent id.
    assert propagating_parents(A, STORE) == ((B, "is_a"), (C, "part_of"), (D, "part_of"))
    # C's children exclude the regulates edge (R) and the cross-namespace part_of (MF2).
    assert propagating_children(C, STORE) == ((B, "is_a"), (D, "is_a"), (A, "part_of"))
    assert propagating_parents("GO:0009999", STORE) == ()
    for term in (A, B, C, D, X, Y, T, MF1, MF2):
        for parent, relation in propagating_parents(term, STORE):
            assert (term, relation) in propagating_children(parent, STORE)
```

Append to `tests/test_biolean_tactics.py`:

```python
def test_applicable_is_empty_at_an_obsolete_or_unknown_target_even_with_a_row():
    """P00005 has a real IDA row at the obsolete term GO:0000110; the kernel would still refuse
    an axiom there (OBSOLETE_TERM), so `applicable` must not offer it."""
    assert STORE.matching(_p("GO:0000110", subject=P5)) != ()
    assert applicable(_p("GO:0000110", subject=P5), STORE) == []
    assert applicable(_p("GO:0009999", subject=P7), STORE) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_store.py tests/test_biolean_kernel.py tests/test_biolean_tactics.py -q -k "subjects or propagating or obsolete_or_unknown_target"`
Expected: FAIL — `AttributeError: 'StaticFactStore' object has no attribute 'subjects'`, `ImportError: cannot import name 'propagating_children'`, and `applicable(...) == [{'rule': 'axiom', ...}]`.

- [ ] **Step 3: Add `subjects()` to the store**

In `src/methods_graph/biolean/store.py`, add to the `FactStore` protocol after `subject_exists`:

```python
    def subjects(self) -> tuple[str, ...]: ...
```

In `StaticFactStore.__init__`, after `self._by_symbol = ...`:

```python
        self._subjects: tuple[str, ...] = tuple(sorted(by_subject))
```

Add the method to `StaticFactStore` after `subject_exists`:

```python
    def subjects(self) -> tuple[str, ...]:
        """Every subject with at least one annotation, sorted. The population enumerates over it."""
        return self._subjects
```

Add to `MaskedFactStore` after `subject_exists`:

```python
    def subjects(self) -> tuple[str, ...]:
        return self._base.subjects()
```

- [ ] **Step 4: Replace the closure helpers in `kernel.py` with one predicate**

Replace the whole `ancestors` and `descendants` functions (the "closure helpers" section) with:

```python
def propagating_parents(term_id: str, store: FactStore) -> tuple[tuple[str, str], ...]:
    """``(parent, relation)`` one propagation step above ``term_id``.

    The one definition of "an annotation lifts over this edge": relation in
    ``PROPAGATING_RELATIONS``, parent known, live, and in the child's namespace. Sorted by
    ``(parent, relation)``. Empty for an unknown term. ``tactics`` and the benchmark import
    this rather than restating the filters.
    """
    start = store.term(term_id)
    if start is None:
        return ()
    out: list[tuple[str, str]] = []
    for e in store.parents(term_id):
        if e.relation not in PROPAGATING_RELATIONS:
            continue
        parent = store.term(e.parent)
        if parent is None or parent.obsolete or parent.namespace != start.namespace:
            continue
        out.append((e.parent, e.relation))
    return tuple(sorted(out))


def propagating_children(term_id: str, store: FactStore) -> tuple[tuple[str, str], ...]:
    """``(child, relation)`` one propagation step below ``term_id``: the exact dual."""
    start = store.term(term_id)
    if start is None:
        return ()
    out: list[tuple[str, str]] = []
    for e in store.children(term_id):
        if e.relation not in PROPAGATING_RELATIONS:
            continue
        child = store.term(e.child)
        if child is None or child.obsolete or child.namespace != start.namespace:
            continue
        out.append((e.child, e.relation))
    return tuple(sorted(out))


def _closure(term_id: str, store: FactStore, step) -> tuple[str, ...]:
    seen: set[str] = set()
    queue: deque[str] = deque([term_id])
    while queue:
        cur = queue.popleft()
        for nxt, _relation in step(cur, store):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return tuple(sorted(seen))


def ancestors(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict ancestors over is_a/part_of, same namespace, live terms only, sorted."""
    return _closure(term_id, store, propagating_parents)


def descendants(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict descendants: the exact dual of :func:`ancestors`, walked with children()."""
    return _closure(term_id, store, propagating_children)
```

Note that `propagating_parents` checks the namespace against the *current* node's namespace at every hop, exactly as the old loop did (the old loop compared against `start.namespace`; go-basic has no cross-namespace `is_a`/`part_of`, and a chain can only change namespace through an edge this predicate already refuses, so the two are equivalent — the golden verdict pins it).

- [ ] **Step 5: Use the predicate in `tactics.py`**

Replace the import line and `_live_parents`:

```python
from methods_graph.biolean.kernel import propagating_children, propagating_parents
from methods_graph.biolean.props import NAMESPACE_ASPECT, QUALIFIER_ASPECT, Prop
from methods_graph.biolean.store import FactStore
```

```python
def _live_parents(term_id: str, store: FactStore) -> list[tuple[str, str]]:
    """(parent, relation) over propagating relations within namespace, sorted by parent id."""
    return list(propagating_parents(term_id, store))
```

Replace the body of `applicable` from `target = store.term(prop.term)` to the end with:

```python
    target = store.term(prop.term)
    if target is None or target.obsolete:
        return []            # the kernel refuses every step concluding this (UNKNOWN_TERM / OBSOLETE_TERM)
    if not _aspect_legal(target.namespace, prop.qualifier):
        return []            # ... as QUALIFIER_ASPECT_MISMATCH
    frags: list[dict[str, Any]] = []
    if store.matching(prop):
        frags.append({"rule": "axiom", "conclusion": prop.to_dict()})
    derivable = {(g["prop"]["term"]) for g in goals_for(prop.subject, store)[0]
                 if g["prop"]["qualifier"] == prop.qualifier and g["prop"]["taxon"] == prop.taxon}
    for child, relation in propagating_children(prop.term, store):
        if child in derivable:
            frags.append({"rule": relation, "edge": [child, prop.term], "conclusion": prop.to_dict()})
    return sorted(frags, key=lambda f: (f["rule"], f.get("edge", [])))
```

Remove the now-unused `PROPAGATING_RELATIONS` import from `tactics.py` (the module-level import of `props` keeps `NAMESPACE_ASPECT`, `QUALIFIER_ASPECT`, `Prop`).

- [ ] **Step 6: Run the whole Biolean suite**

Run: `$PYTEST tests/test_biolean_store.py tests/test_biolean_kernel.py tests/test_biolean_tactics.py tests/test_biolean_elaborate.py tests/test_biolean_render.py tests/test_biolean_cli.py -q`
Expected: all PASS, including `test_verdict_matches_committed_golden` (byte-identical) and every existing tactics test. If the golden differs, the refactor changed behaviour: stop and diff `kernel.dumps` output against `tests/fixtures/biolean/golden_verdict.json` before touching anything else.

Mutation checks to run and record in the commit body: (a) in `propagating_children`, drop the namespace check — `test_propagating_parents_and_children_are_duals_over_the_fixture` fails (MF2 appears under C); (b) in `applicable`, remove `or target.obsolete` — `test_applicable_is_empty_at_an_obsolete_or_unknown_target_even_with_a_row` fails; (c) return `self._base.subjects()` filtered by `annotations()` in `MaskedFactStore` — the store test fails.

- [ ] **Step 7: Record the deviations in the spec**

In `docs/superpowers/specs/2026-09-21-biolean-design.md`:

(a) §4 protocol block — add after the `subject_exists` line:

```python
    def subjects(self) -> tuple[str, ...]: ...                       # every annotated subject, sorted
```

and append to the `MaskedFactStore` paragraph: "`subjects` also delegates unmasked."

(b) §6 "Prove track" — after the fenced prompt block, add the paragraph:

> Both prompts end with one fixed `Format:` paragraph (`biolean/bench/render.py::FORMAT_BLOCK`) that states the derivation JSON shape: the top-level keys, the five `Prop` keys, and one line each for an `axiom`, a propagation, and a `sorry` step. It is part of the prompt, identical for every item and both tracks, so a closed-book model is measured on the claim, not on guessing a private schema.

(c) §6 "Prove track" table — replace the `depth` row with:

| `depth` | propagation steps in the used chain (used steps minus the axiom), or `None` when rejected; comparable with `gold_depth`, which is the gold derivation's step count minus one |

(d) §6 "Prove track", the sentence "Rows also retain `item`, `track`, `model`, the item's `goal`, and `hidden`, so `rescore` needs nothing but the row and the store." — replace with:

> Rows also retain `item`, `track`, `model`, the item's `goal`, `hidden`, `hidden_classes`, `gold_depth` (prove rows), and `items_manifest` (`{"release", "since"}` copied from the items' `manifest.json`), so `rescore` and the release check need nothing but the row and the store.

(e) §6 "Hypothesize track" — replace "otherwise the triple is counted under `goal_not_statable:<CODE>` and dropped." with "otherwise the triple is counted once under `goal_not_statable[<CODE>]`, where `<CODE>` is the alphabetically first code among the rejection's errors, alongside `goal_not_statable_total`, and dropped."

(f) §7 layout block — add under `bench/`:

```
    render.py     item → prompt (claim text + the fixed FORMAT_BLOCK); reply → JSON object or None
```

(g) §7 "Fetch and manifest" — replace the final sentence "Every benchmark item names the release it was built from, and `bench run` and `bench score` refuse a store whose manifest release differs from the items'." with:

> The benchmark's `manifest.json` records the release it was built from as read from the files themselves — the OBO header's `data-version` and the GAF header's `date-generated` and `go-version` — because those headers are what `snapshot.json` copies and a snapshot fetched by hand has no manifest. `bench run` and `bench score` refuse a store whose file headers differ from the items' record.

(h) §7 CLI table — replace the four `bench` rows with:

| `bench build --out biolean-bench [--store DIR] [--per-track N] [--seed S] [--since DATE]` | frozen items under `items/`, `manifest.json` with every count, `modal.json`; `--per-track` defaults to 500 |
| `bench coverage --items DIR` | prints `manifest.json` — the denominators — read before any score; `DIR` is the `build --out` directory |
| `bench run --model SPEC --items DIR --store DIR --out results.jsonl [--track T] [--limit N]` | run an adapter or baseline, retain raw output; `--track` is required for a baseline when the item set mixes tracks |
| `bench score --results results.jsonl --store DIR [--out FILE]` | re-derive scores from retained output |

- [ ] **Step 8: Commit**

```
git add src/methods_graph/biolean/kernel.py src/methods_graph/biolean/tactics.py src/methods_graph/biolean/store.py tests/test_biolean_kernel.py tests/test_biolean_tactics.py tests/test_biolean_store.py docs/superpowers/specs/2026-09-21-biolean-design.md
git commit -m "refactor(biolean): one propagation predicate, FactStore.subjects(), Plan 2 spec deviations"
```

---
### Task 2: Prompt rendering and reply parsing (`biolean/bench/render.py`)

**Files:**
- Create: `src/methods_graph/biolean/bench/__init__.py`
- Create: `src/methods_graph/biolean/bench/render.py`
- Test: `tests/test_biolean_bench_render.py`

**Interfaces:**
- Produces: `FORMAT_BLOCK: str`, `PROVE_TEMPLATE: str`, `HYPOTHESIZE_TEMPLATE: str`, `organism(taxon: str) -> str`, `claim_text(item: dict) -> str`, `render_prompt(item: dict) -> str` (raises `KeyError` for a malformed item; the runner turns that into a `render_error` row), `parse_reply(raw: Any) -> dict | None` (the first balanced JSON object in the text, or `None`).
- Items consumed have at least `track`, `goal` (a `Prop` dict), `symbol`, `term_name`.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_bench_render.py`:

```python
from methods_graph.biolean.bench.render import (
    FORMAT_BLOCK, claim_text, organism, parse_reply, render_prompt)

GOAL = {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0006915",
        "taxon": "NCBITaxon:9606", "negated": False}
ITEM = {"id": "prove/UniProtKB:P04637/involved_in/GO:0006915", "track": "prove", "goal": GOAL,
        "symbol": "TP53", "term_name": "apoptotic process"}


def test_claim_text_names_symbol_accession_qualifier_term_and_organism():
    assert claim_text(ITEM) == ("TP53 (UniProtKB:P04637) involved_in apoptotic process "
                                "(GO:0006915), human.")
    assert organism("NCBITaxon:9606") == "human"
    assert organism("NCBITaxon:10090") == "NCBITaxon:10090"      # never guessed


def test_prove_prompt_is_the_spec_text_plus_the_format_block():
    prompt = render_prompt(ITEM)
    assert prompt.startswith("Prove the following claim as a Biolean derivation.\nClaim: TP53 ")
    assert "The direct annotation of this gene product to this term is not available to you." in prompt
    assert "Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only." in prompt
    assert prompt.endswith(FORMAT_BLOCK)
    assert '"rule": "sorry"' in FORMAT_BLOCK and '"edge"' in FORMAT_BLOCK and '"root"' in FORMAT_BLOCK


def test_hypothesize_prompt_differs_only_in_the_task_text():
    prove = render_prompt(ITEM)
    hyp = render_prompt({**ITEM, "track": "hypothesize"})
    assert hyp.startswith("No recorded annotation supports the following claim.\nClaim: TP53 ")
    assert "sorry step with provenance naming the method, the input datasets, and parameters" in hyp
    assert hyp != prove and hyp.endswith(FORMAT_BLOCK)
    assert claim_text(ITEM) in hyp


def test_render_prompt_raises_key_error_for_a_malformed_item():
    import pytest
    with pytest.raises(KeyError):
        render_prompt({"id": "x", "track": "prove", "goal": GOAL})       # no symbol / term_name
    with pytest.raises(KeyError):
        render_prompt({**ITEM, "track": "unknown"})


def test_parse_reply_finds_the_first_json_object_and_rejects_everything_else():
    doc = {"biolean": "0.1", "goal": GOAL, "steps": [], "root": "s1"}
    import json
    text = json.dumps(doc)
    assert parse_reply(text) == doc
    assert parse_reply("```json\n" + text + "\n```") == doc
    assert parse_reply("Sure, here is the derivation:\n" + text + "\nHope this helps.") == doc
    assert parse_reply("{not json} " + text) == doc                # skips the unbalanced span
    assert parse_reply('[{"a": 1}]') == {"a": 1}                   # the inner object is the only object
    assert parse_reply("[1, 2, 3]") is None
    assert parse_reply("I cannot help with that.") is None
    assert parse_reply("") is None
    assert parse_reply(None) is None
    assert parse_reply(42) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.bench'`.

- [ ] **Step 3: Write the module**

`src/methods_graph/biolean/bench/__init__.py`:

```python
"""The Biolean benchmark: frozen items, retained raw output, re-scorable rows (spec §6)."""
```

`src/methods_graph/biolean/bench/render.py`:

```python
"""Item → closed-book prompt, and model reply → JSON object. Mirrors ``bench/render.py``.

The prompt is the spec's text plus one fixed ``FORMAT_BLOCK``. A model that has never seen
Biolean cannot emit its JSON from the claim alone, and a benchmark where every reply is
``UNPARSED`` measures nothing; the block is identical for every item and both tracks, so
it adds no per-item information.
"""
from __future__ import annotations

import json
from typing import Any

FORMAT_BLOCK = (
    'Format: {"biolean": "0.1", "goal": P, "root": "<id of the final step>", "steps": [...]}, '
    'where P is {"subject": "<UniProtKB accession, e.g. UniProtKB:P04637>", '
    '"qualifier": "<GAF qualifier, e.g. involved_in>", "term": "<GO id>", '
    '"taxon": "<NCBITaxon:id>", "negated": false}. '
    'Steps: {"id": "s1", "rule": "axiom", "conclusion": P} cites a recorded annotation; '
    '{"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["<GO child>", "<GO parent>"], '
    '"conclusion": P} lifts the premise along an is_a edge, and rule "part_of" does the same '
    'along a part_of edge; '
    '{"id": "s1", "rule": "sorry", "conclusion": P, "provenance": {"method": "<method>", '
    '"inputs": ["<dataset>"], "parameters": {}, "claim": "<what the computation shows>"}} '
    'admits a computed result. Every step id is unique and a premise must come earlier.')

PROVE_TEMPLATE = (
    "Prove the following claim as a Biolean derivation.\n"
    "Claim: {claim}\n"
    "The direct annotation of this gene product to this term is not available to you. Derive\n"
    "it from an annotation to a more specific term using the rules is_a and part_of.\n"
    "Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only.\n"
    "{format}")

HYPOTHESIZE_TEMPLATE = (
    "No recorded annotation supports the following claim.\n"
    "Claim: {claim}\n"
    "Propose the computation that would establish it: a Biolean derivation whose root is a\n"
    "sorry step with provenance naming the method, the input datasets, and parameters.\n"
    "Answer with the JSON document only.\n"
    "{format}")

_TEMPLATES = {"prove": PROVE_TEMPLATE, "hypothesize": HYPOTHESIZE_TEMPLATE}
_ORGANISM = {"NCBITaxon:9606": "human"}


def organism(taxon: str) -> str:
    """A common name where one is known, else the taxon id verbatim — never a guess."""
    return _ORGANISM.get(taxon, taxon)


def claim_text(item: dict[str, Any]) -> str:
    goal = item["goal"]
    return (f"{item['symbol']} ({goal['subject']}) {goal['qualifier']} "
            f"{item['term_name']} ({goal['term']}), {organism(goal['taxon'])}.")


def render_prompt(item: dict[str, Any]) -> str:
    """The closed-book prompt for one item. Raises ``KeyError`` for a malformed item."""
    return _TEMPLATES[item["track"]].format(claim=claim_text(item), format=FORMAT_BLOCK)


def parse_reply(raw: Any) -> dict[str, Any] | None:
    """The first balanced JSON object in the reply, or ``None``.

    ``None`` is a FORMATTING failure — prose, a refusal, a bare list, a truncated document —
    and is scored as ``UNPARSED``; it is never turned into an empty derivation, because the
    kernel would then report the model's formatting as a knowledge failure. Fences and
    surrounding prose are skipped by decoding from each ``{`` left to right.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_render.py -q`
Expected: 5 passed.

Mutation checks: (a) return `json.loads(raw)` directly — the fenced and prose-wrapped cases fail; (b) in `_ORGANISM.get(taxon, taxon)` return `"human"` for any taxon — the organism test fails; (c) drop `{format}` from `PROVE_TEMPLATE` — `endswith(FORMAT_BLOCK)` fails.

- [ ] **Step 5: Commit**

```
git add src/methods_graph/biolean/bench/__init__.py src/methods_graph/biolean/bench/render.py tests/test_biolean_bench_render.py
git commit -m "feat(biolean-bench): prompt rendering with the fixed format block, reply parsing"
```

---

### Task 3: Population, hiders, release (`biolean/bench/items.py`, part A)

**Files:**
- Create: `src/methods_graph/biolean/bench/items.py`
- Modify: `tests/biolean_fixture.py`
- Test: `tests/test_biolean_bench_items.py`

**Interfaces:**
- Produces:
  - `Triple = tuple[str, str, str, str]` — `(subject, qualifier, term, taxon)`.
  - `population(store, *, subjects: Iterable[str] | None = None) -> tuple[list[Triple], dict[str, Any]]` — sorted eligible triples and `{"rows", "eligible_rows", "triples", "n_subjects", "dropped": {reason: n}}` with every reason in `DROP_REASONS` present.
  - `hide_exact(store, prop) -> frozenset[str]`; `hide_subtree(store, prop, *, cache: dict[str, frozenset[str]] | None = None) -> frozenset[str]`.
  - `below(term, store, cache=None) -> frozenset[str]` — the term plus its propagation descendants, memoized in `cache` when given.
  - `visible_descendants(store, prop, *, cache=None) -> list[str]` — sorted proper descendants of `prop.term` at which `prop.subject` has a visible, non-negated annotation under `(prop.qualifier, prop.taxon)`.
  - `read_release(store_dir: Path, *, obo="go-basic.obo", gaf="goa_human.gaf.gz") -> dict[str, str]` — `{"go_basic_data_version", "goa_date_generated", "goa_go_version"}`.
- Consumes: `kernel.descendants`, `props.evidence_class`, `fetch.gaf_header`.

- [ ] **Step 1: Extend the shared fixture module**

Replace `tests/biolean_fixture.py` with:

```python
"""The one fixture inventory, loaded from the three files under tests/fixtures/biolean."""
import shutil
from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.store import StaticFactStore, load_store

FIX = Path(__file__).parent / "fixtures" / "biolean"
RELEASE = {"go_basic_data_version": "releases/2026-01-01", "goa_date_generated": "2026-01-01",
           "goa_go_version": ""}


def mini_store() -> StaticFactStore:
    store, _ = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return store


def mini_report() -> dict:
    _, report = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return report


def reversed_store() -> StaticFactStore:
    """The same facts with the GAF rows fed in reverse order: for order-independence tests."""
    terms, edges, _ = parse_go_basic((FIX / "go-mini.obo").read_text())
    eco_map, _ = parse_eco_mapping((FIX / "eco-mini.txt").read_text())
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}
    lines = list(reversed((FIX / "goa-mini.gaf").read_text().splitlines()))
    annotations, _ = parse_gaf(lines, eco_map, lambda g: g if g in by_id else alt.get(g), by_id.get)
    return StaticFactStore(terms, edges, annotations)


def copy_store(dest: Path) -> Path:
    """The fixture files under the names `mg biolean --store` expects (plain GAF, not gz)."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "go-mini.obo", dest / "go-basic.obo")
    shutil.copy(FIX / "goa-mini.gaf", dest / "goa_human.gaf")
    shutil.copy(FIX / "eco-mini.txt", dest / "gaf-eco-mapping.txt")
    return dest
```

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_bench_items.py` (this file grows in Task 4; start it with these):

```python
"""Population, hiders, item construction, sampling, live cut, modal fit (spec §6)."""
import pytest

from methods_graph.biolean.bench.items import (
    DROP_REASONS, below, hide_exact, hide_subtree, population, read_release, visible_descendants)
from methods_graph.biolean.props import Annotation, Edge, Prop, Term
from methods_graph.biolean.store import MaskedFactStore, StaticFactStore
from tests.biolean_fixture import RELEASE, copy_store, mini_store, reversed_store
from tests.test_biolean_kernel import (
    A, B, C, D, MF1, MF2, P1, P2, P3, P5, P7, R, T, TAX, X, Y)

STORE = mini_store()
C1, C2, T0, CC2 = "GO:0000080", "GO:0000090", "GO:0000070", "GO:0000310"
P4, P6, P8, P9 = "UniProtKB:P00004", "UniProtKB:P00006", "UniProtKB:P00008", "UniProtKB:P00009"

EXPECTED_TRIPLES = sorted([
    (P1, "involved_in", A, TAX), (P1, "involved_in", B, TAX), (P1, "involved_in", C, TAX),
    (P1, "involved_in", D, TAX), (P2, "involved_in", X, TAX), (P2, "involved_in", Y, TAX),
    (P2, "involved_in", T, TAX), (P3, "enables", MF1, TAX), (P3, "enables", MF2, TAX),
    (P4, "located_in", CC2, TAX), (P6, "involved_in", C, TAX), (P7, "involved_in", R, TAX),
    (P7, "involved_in", C2, TAX),
])


def _p(term, subject=P1, qualifier="involved_in"):
    return Prop(subject, qualifier, term, TAX, False)


def _ann(i, subject, qualifier, term, *, code="IDA", negated=False, object_type="protein",
         date="2020-01-01"):
    return Annotation(i, subject, subject.split(":")[1], qualifier, negated, term, term, ("PMID:1",),
                      code, "ECO:0000314", (), "P", object_type, TAX, "", date, "UniProt", "", "")


def _term(i, ns="biological_process", obsolete=False):
    return Term(i, i, ns, obsolete, (), (), ())


# ---------- population ----------

def test_population_over_the_fixture_is_thirteen_triples_with_every_drop_counted():
    triples, report = population(STORE)
    assert triples == EXPECTED_TRIPLES
    assert report["rows"] == 24 and report["eligible_rows"] == 15 and report["triples"] == 13
    assert report["n_subjects"] == 9
    assert set(report["dropped"]) == set(DROP_REASONS)
    assert report["dropped"] == {
        "negated": 2, "qualifier_out_of_scope": 1, "evidence_class": 4, "object_type": 0,
        "term_not_in_ontology": 1, "term_alt_id": 0, "term_obsolete": 1}
    assert report["rows"] == report["eligible_rows"] + sum(report["dropped"].values())


def test_population_filters_count_the_first_failure_in_order():
    """A row failing several filters is counted once, under the first in spec order:
    negated, qualifier, evidence class, object type, term."""
    store = StaticFactStore([_term("GO:1")], [], [
        _ann("a1", "UniProtKB:S", "involved_in", "GO:9", code="IEA", negated=True),   # negated+IEA+unknown
        _ann("a2", "UniProtKB:S", "colocalizes_with", "GO:9", code="IEA"),           # qualifier+IEA+unknown
        _ann("a3", "UniProtKB:S", "involved_in", "GO:9", code="IEA"),                # IEA+unknown
        _ann("a4", "UniProtKB:S", "involved_in", "GO:9", object_type="gene"),         # object_type+unknown
        _ann("a5", "UniProtKB:S", "involved_in", "GO:9"),                            # unknown only
        _ann("a6", "UniProtKB:S", "involved_in", "GO:1"),                            # eligible
    ])
    triples, report = population(store)
    assert triples == [("UniProtKB:S", "involved_in", "GO:1", TAX)]
    assert report["dropped"] == {
        "negated": 1, "qualifier_out_of_scope": 1, "evidence_class": 1, "object_type": 1,
        "term_not_in_ontology": 1, "term_alt_id": 0, "term_obsolete": 0}


def test_population_excludes_obsolete_terms():
    """P00005's IDA row sits at the obsolete GO:0000110; it is counted, not eligible."""
    triples, report = population(STORE)
    assert (P5, "involved_in", "GO:0000110", TAX) not in triples
    assert report["dropped"]["term_obsolete"] == 1
    # The alt_id counter exists even though the loader canonicalizes alt ids before the
    # store is built (a StaticFactStore cannot hold one), so it is 0 by construction here.
    assert report["dropped"]["term_alt_id"] == 0


def test_population_can_be_restricted_to_named_subjects_and_says_so():
    triples, report = population(STORE, subjects=[P2, P1])
    assert {t[0] for t in triples} == {P1, P2} and report["n_subjects"] == 2
    assert report["rows"] == 12


def test_population_is_independent_of_row_order():
    assert population(reversed_store())[0] == population(STORE)[0]


# ---------- hiders ----------

def test_prove_item_hides_only_the_exact_rows():
    hidden = hide_exact(STORE, _p(C))
    codes = sorted(a.code for a in STORE.annotations(P1) if a.id in hidden)
    assert codes == ["IDA", "IEA"]                                  # every evidence class at the tuple
    masked = MaskedFactStore(STORE, hidden)
    remaining = {(a.qualifier, a.term, a.negated) for a in masked.annotations(P1)}
    assert ("acts_upstream_of_or_within", C, False) in remaining    # other qualifier stays
    assert ("involved_in", C, True) in remaining                    # the NOT row stays
    assert ("involved_in", B, False) in remaining                   # the descendant stays


def test_hypothesize_subtree_is_closure_of_the_union():
    """C2 is_a C1 part_of T0: is_a-closure(T0) ∪ part_of-closure(T0) is {C1}; the closure of
    the union is {C1, C2}. P00007's rows at C2 must be hidden for goal T0."""
    assert below(T0, STORE) == frozenset({T0, C1, C2})
    hidden = hide_subtree(STORE, _p(T0, subject=P7))
    hidden_terms = sorted(a.term for a in STORE.annotations(P7) if a.id in hidden)
    assert hidden_terms == [C2, C2]                                 # the IDA row and the XYZ row


def test_hypothesize_never_hides_not_rows():
    hidden = hide_subtree(STORE, _p(T, subject=P2))
    rows = [a for a in STORE.annotations(P2) if a.id in hidden]
    assert sorted(a.term for a in rows) == [X, Y, T]
    assert all(not a.negated for a in rows)
    not_row = next(a for a in STORE.annotations(P2) if a.negated)
    assert not_row.id not in hidden
    assert hide_subtree(STORE, _p(C)) == hide_subtree(STORE, _p(C), cache={})   # the cache is transparent


def test_subtree_stops_at_namespace_and_non_propagating_edges():
    hidden = hide_subtree(STORE, _p(C))
    assert sorted({a.term for a in STORE.annotations(P1) if a.id in hidden}) == [B, C, D, A]
    assert not any(a.id in hidden for a in STORE.annotations(P3))    # MF2 part_of C is cross-namespace
    assert not any(a.id in hidden for a in STORE.annotations(P7))    # R regulates C


def test_visible_descendants_are_the_subjects_visible_rows_strictly_below_the_term():
    masked = MaskedFactStore(STORE, hide_exact(STORE, _p(C)))
    assert visible_descendants(masked, _p(C)) == [B, D, A]          # sorted; C itself excluded
    assert visible_descendants(STORE, _p(C)) == [B, D, A]           # the direct row is not a descendant
    assert visible_descendants(STORE, _p(T, subject=P2)) == [X, Y]
    assert visible_descendants(STORE, _p(X, subject=P2)) == []
    # A NOT row below the term is never a visible descendant.
    assert visible_descendants(STORE, _p(Y, subject=P2)) == [X]


# ---------- release ----------

def test_read_release_comes_from_the_file_headers(tmp_path):
    store_dir = copy_store(tmp_path)
    assert read_release(store_dir, gaf="goa_human.gaf") == RELEASE
    obo = store_dir / "go-basic.obo"
    obo.write_text(obo.read_text().replace("releases/2026-01-01", "releases/2026-02-02"))
    assert read_release(store_dir, gaf="goa_human.gaf")["go_basic_data_version"] == "releases/2026-02-02"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_items.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.bench.items'`.

- [ ] **Step 4: Write the module (part A)**

`src/methods_graph/biolean/bench/items.py`:

```python
"""Population, hiders, item construction, sampling, the live cut, and the modal fit.

Everything here reads a ``FactStore`` and writes plain dicts. The kernel is called only to
confirm that a hypothesize goal is statable; the prover is called only to build gold and to
prove that a hidden fact really is hidden.
"""
from __future__ import annotations

import functools
import json
import random
from pathlib import Path
from typing import Any, Callable, Iterable

from methods_graph.biolean.kernel import check, descendants
from methods_graph.biolean.props import Prop, evidence_class
from methods_graph.biolean.store import FactStore, MaskedFactStore
from methods_graph.biolean.tactics import prove
from methods_graph.fetch import gaf_header

Triple = tuple[str, str, str, str]                      # (subject, qualifier, term, taxon)
Hider = Callable[[FactStore, Prop], frozenset[str]]

POPULATION_QUALIFIERS = frozenset({"involved_in", "enables", "located_in", "part_of", "is_active_in"})
POPULATION_CLASSES = frozenset({"experimental", "high_throughput"})
# Spec order. A row is counted under the FIRST filter it fails and under no other.
DROP_REASONS = ("negated", "qualifier_out_of_scope", "evidence_class", "object_type",
                "term_not_in_ontology", "term_alt_id", "term_obsolete")
TRACKS = ("prove", "hypothesize")
PLACEHOLDER_PROVENANCE = {"method": "m:placeholder", "inputs": ["placeholder"],
                          "parameters": {}, "claim": "placeholder"}


# ---------------------------------------------------------------------------
# population
# ---------------------------------------------------------------------------

def _drop_reason(a, store: FactStore) -> str | None:
    if a.negated:
        return "negated"
    if a.qualifier not in POPULATION_QUALIFIERS:
        return "qualifier_out_of_scope"
    if evidence_class(a.code) not in POPULATION_CLASSES:
        return "evidence_class"
    if a.object_type != "protein":
        return "object_type"
    term = store.term(a.term)
    if term is None:
        return "term_alt_id" if store.primary_id(a.term) is not None else "term_not_in_ontology"
    if term.obsolete:
        return "term_obsolete"
    return None


def population(
    store: FactStore, *, subjects: Iterable[str] | None = None,
) -> tuple[list[Triple], dict[str, Any]]:
    """Eligible ``(subject, qualifier, term, taxon)`` tuples, sorted, plus every count.

    Only the hidden fact must be in the population; the visible store stays whole. *subjects*
    restricts the enumeration (the scale test and debugging use it) and is reported as
    ``n_subjects`` so a restricted build cannot pass for a full one.
    """
    chosen = tuple(sorted(subjects)) if subjects is not None else store.subjects()
    dropped = {reason: 0 for reason in DROP_REASONS}
    rows = eligible_rows = 0
    triples: set[Triple] = set()
    for subject in chosen:
        for a in store.annotations(subject):
            rows += 1
            reason = _drop_reason(a, store)
            if reason is not None:
                dropped[reason] += 1
                continue
            eligible_rows += 1
            triples.add((a.subject, a.qualifier, a.term, a.taxon))
    out = sorted(triples)
    return out, {"rows": rows, "eligible_rows": eligible_rows, "triples": len(out),
                 "n_subjects": len(chosen), "dropped": dropped}


# ---------------------------------------------------------------------------
# hiders
# ---------------------------------------------------------------------------

def below(term: str, store: FactStore, cache: dict[str, frozenset[str]] | None = None) -> frozenset[str]:
    """``term`` plus every propagation descendant (is_a/part_of, same namespace, live).

    The closure of the union of the two relations — ``kernel.descendants`` — not the union
    of two closures: ``C2 is_a C1 part_of T0`` puts C2 below T0.
    """
    if cache is not None and term in cache:
        return cache[term]
    result = frozenset(descendants(term, store)) | {term}
    if cache is not None:
        cache[term] = result
    return result


def hide_exact(store: FactStore, prop: Prop) -> frozenset[str]:
    """Every row at ``(subject, qualifier, term, taxon, negated=False)``, all evidence codes."""
    return frozenset(a.id for a in store.matching(
        Prop(prop.subject, prop.qualifier, prop.term, prop.taxon, False)))


def hide_subtree(
    store: FactStore, prop: Prop, *, cache: dict[str, frozenset[str]] | None = None,
) -> frozenset[str]:
    """``hide_exact`` at the term and at every term below it. NOT rows are never hidden.

    Walks the subject's annotations and tests membership in the descendant set rather than
    calling ``matching`` once per descendant: cytoplasm has thousands of descendants and a
    subject has tens of rows.
    """
    terms = below(prop.term, store, cache)
    return frozenset(
        a.id for a in store.annotations(prop.subject)
        if not a.negated and a.qualifier == prop.qualifier and a.taxon == prop.taxon
        and a.term in terms)


def visible_descendants(
    store: FactStore, prop: Prop, *, cache: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """Proper descendants of ``prop.term`` where the subject has a visible positive row under
    ``(qualifier, taxon)``, sorted. The modal baseline's unit of evidence."""
    terms = below(prop.term, store, cache) - {prop.term}
    return sorted({
        a.term for a in store.annotations(prop.subject)
        if not a.negated and a.qualifier == prop.qualifier and a.taxon == prop.taxon
        and a.term in terms})


# ---------------------------------------------------------------------------
# release identity
# ---------------------------------------------------------------------------

def read_release(store_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz") -> dict[str, str]:
    """The pair's identity from the file headers: OBO ``data-version``, GAF ``date-generated``
    and ``go-version``. Read from the files, not ``snapshot.json``, which a hand-fetched
    snapshot lacks and which copies these same lines."""
    store_dir = Path(store_dir)
    data_version = ""
    with (store_dir / obo).open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("[Term]"):
                break
            if line.startswith("data-version:"):
                data_version = line.partition(":")[2].strip()
                break
    header = gaf_header((store_dir / gaf).read_bytes())
    return {"go_basic_data_version": data_version,
            "goa_date_generated": header["date_generated"],
            "goa_go_version": header["go_version"]}
```

(The imports `functools`, `json`, `random`, `check`, `prove`, `MaskedFactStore`, `TRACKS`, and `PLACEHOLDER_PROVENANCE` are used by part B in Task 4; leave them in place.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_items.py -q`
Expected: 11 passed.

Mutation checks: (a) reorder `_drop_reason` so the evidence check precedes `negated` — `..._first_failure_in_order` fails (`negated: 0`); (b) in `hide_exact`, match on `(subject, term)` by iterating `annotations` and comparing `a.term` only — `..._hides_only_the_exact_rows` fails (the NOT row and the other-qualifier row vanish); (c) in `below`, compute `is_a`-only and `part_of`-only closures over `store.children` and union them — `..._closure_of_the_union` fails (C2 not below T0); (d) in `hide_subtree`, drop `not a.negated` — `..._never_hides_not_rows` fails; (e) in `read_release`, return `""` for `data_version` — the release test fails.

- [ ] **Step 6: Commit**

```
git add src/methods_graph/biolean/bench/items.py tests/biolean_fixture.py tests/test_biolean_bench_items.py
git commit -m "feat(biolean-bench): population with ordered drop counts, exact and subtree hiders, release identity"
```

---
### Task 4: Items, sampling, live cut, modal fit, build and load (`items.py`, part B)

**Files:**
- Modify: `src/methods_graph/biolean/bench/items.py`
- Test: `tests/test_biolean_bench_items.py` (append)

**Interfaces:**
- Produces:
  - `BuildError(triple, derivation)` with attributes `.triple`, `.derivation`.
  - `prove_items(store, triples, *, hide: Hider = hide_exact) -> tuple[list[dict], dict[str, int]]` — report `{"eligible", "not_rederivable"}`; each item carries `gold` (the derivation) and `gold_depth = len(gold["steps"]) - 1`.
  - `hypothesize_items(store, triples, *, hide: Hider = hide_subtree) -> tuple[list[dict], dict[str, Any]]` — report `{"eligible", "goal_not_statable": {code: n}, "goal_not_statable_total"}`; raises `BuildError` when `prove` still succeeds over the masked store.
  - Item record (both tracks): `id` (`<track>/<subject>/<qualifier>/<term>`), `track`, `goal` (Prop dict), `symbol`, `term_name`, `hidden` (sorted ids), `hidden_dates` (sorted), `cut_date` (min), `hidden_classes` (sorted).
  - `apply_since(items, since: str | None) -> tuple[list[dict], int]`.
  - `sample(items, n: int | None, seed: int) -> list[dict]` — `random.Random(seed).sample` over the id-sorted list, result re-sorted by id; `None` or `n >= len` keeps all.
  - `fit_modal(store, items, *, cache=None) -> dict[str, dict[str, dict[str, int]]]` — `qualifier → goal term → descendant → count`.
  - `build_items(store, out_dir: Path, *, release: dict, per_track: int | None = 500, seed: int = 0, since: str | None = None, subjects=None) -> dict` — writes `items/prove.json`, `items/hypothesize.json`, `modal.json`, `manifest.json`; returns the manifest.
  - `load_items(root: Path) -> tuple[list[dict], dict]` — items sorted by id plus the manifest; `FileNotFoundError` without a manifest, `ValueError` on an empty item set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_biolean_bench_items.py`:

```python
import json

from methods_graph.biolean.bench.items import (
    BuildError, apply_since, build_items, fit_modal, hypothesize_items, load_items, prove_items,
    sample)
from methods_graph.biolean.kernel import check
from methods_graph.biolean.tactics import prove

PROVE_IDS = [f"prove/{P1}/involved_in/{B}", f"prove/{P1}/involved_in/{C}",
             f"prove/{P1}/involved_in/{D}", f"prove/{P2}/involved_in/{Y}",
             f"prove/{P2}/involved_in/{T}", f"prove/{P3}/enables/{MF1}"]


def _prove_items(store=STORE):
    return prove_items(store, population(store)[0])


# ---------- prove items ----------

def test_prove_items_are_the_six_rederivable_triples_with_accepted_gold():
    items, report = _prove_items()
    assert report == {"eligible": 6, "not_rederivable": 7}
    assert [i["id"] for i in items] == PROVE_IDS
    for item in items:
        masked = MaskedFactStore(STORE, frozenset(item["hidden"]))
        assert check(item["gold"], masked)["errors"] == [], item["id"]
        assert item["gold"]["goal"] == item["goal"]
        assert item["gold_depth"] == len(item["gold"]["steps"]) - 1 == 1
        assert item["track"] == "prove" and item["hidden"] == sorted(item["hidden"])
    c_item = items[1]
    assert c_item["symbol"] == "GA" and c_item["term_name"] == "C"
    assert c_item["hidden_dates"] == ["2019-01-01", "2026-03-01"]
    assert c_item["cut_date"] == "2019-01-01"
    assert c_item["hidden_classes"] == ["electronic", "experimental"]
    assert [s["rule"] for s in c_item["gold"]["steps"]] == ["axiom", "is_a"]
    assert c_item["gold"]["steps"][0]["conclusion"]["term"] == B        # sorted tie-break, not D or A


def test_not_rederivable_triples_are_counted_not_dropped_silently():
    triples, _ = population(STORE)
    items, report = _prove_items()
    assert report["eligible"] + report["not_rederivable"] == len(triples) == 13
    assert f"prove/{P1}/involved_in/{A}" not in {i["id"] for i in items}     # A is a leaf
    assert f"prove/{P3}/enables/{MF2}" not in {i["id"] for i in items}       # only the parent remains


# ---------- hypothesize items ----------

def test_hypothesize_items_hide_the_subtree_and_every_fixture_triple_is_statable():
    triples, _ = population(STORE)
    items, report = hypothesize_items(STORE, triples)
    assert report == {"eligible": 13, "goal_not_statable": {}, "goal_not_statable_total": 0}
    assert len(items) == 13 and all("gold" not in i and "gold_depth" not in i for i in items)
    t_item = next(i for i in items if i["id"] == f"hypothesize/{P2}/involved_in/{T}")
    assert sorted(a.term for a in STORE.annotations(P2) if a.id in t_item["hidden"]) == [X, Y, T]
    assert len(t_item["hidden_dates"]) == 3
    for item in items:
        masked = MaskedFactStore(STORE, frozenset(item["hidden"]))
        assert prove(Prop.from_dict(item["goal"]), masked) is None, item["id"]


def test_hypothesize_still_derivable_raises_build_error():
    """The hider is injectable and a wrong one is a defect, not a dropped item."""
    triples, _ = population(STORE)
    with pytest.raises(BuildError) as ex:
        hypothesize_items(STORE, triples, hide=hide_exact)
    assert ex.value.triple == (P1, "involved_in", B, TAX)                   # the first rederivable
    assert [s["rule"] for s in ex.value.derivation["steps"]] == ["axiom", "is_a"]
    assert "still derivable" in str(ex.value)


def test_hypothesize_goal_not_statable_is_counted_with_its_code():
    """A release-skewed row: located_in (C aspect) at a biological_process term passes the
    population filters but no sorry can state it — the kernel says QUALIFIER_ASPECT_MISMATCH."""
    store = StaticFactStore([_term("GO:1")], [], [
        _ann("a1", "UniProtKB:S", "located_in", "GO:1"),
        _ann("a2", "UniProtKB:S", "involved_in", "GO:1"),
    ])
    triples, _ = population(store)
    assert len(triples) == 2
    items, report = hypothesize_items(store, triples)
    assert report == {"eligible": 1, "goal_not_statable": {"QUALIFIER_ASPECT_MISMATCH": 1},
                      "goal_not_statable_total": 1}
    assert [i["goal"]["qualifier"] for i in items] == ["involved_in"]


# ---------- live cut, sampling, modal fit ----------

def test_live_cut_uses_min_hidden_date():
    items, _ = _prove_items()
    kept, excluded = apply_since(items, "2020-01-01")
    assert excluded == 1 and f"prove/{P1}/involved_in/{C}" not in {i["id"] for i in kept}
    assert apply_since(items, "2019-01-01") == (items, 0)
    assert apply_since(items, None) == (items, 0)
    # Under a max-or-any rule the C item (IEA row dated 2026-03-01) would survive this cut.
    assert apply_since(items, "2026-03-01") == ([], 6)


def test_sampling_is_seeded_and_sorted_first():
    forward, _ = _prove_items(STORE)
    backward, _ = _prove_items(reversed_store())
    assert forward == backward                                    # content ids, sorted collections
    s1 = [i["id"] for i in sample(forward, 3, seed=1)]
    assert s1 == [i["id"] for i in sample(backward, 3, seed=1)]
    assert len(s1) == 3 and s1 == sorted(s1) and set(s1) < set(PROVE_IDS)
    assert any([i["id"] for i in sample(forward, 3, seed=s)] != s1 for s in range(2, 8))
    assert sample(forward, None, 0) == forward and sample(forward, 10, 0) == forward


def test_modal_is_fit_on_the_full_eligible_set_before_sampling(tmp_path):
    items, _ = _prove_items()
    full = fit_modal(STORE, items)
    assert full == {"enables": {MF1: {MF2: 1}},
                    "involved_in": {B: {A: 1}, C: {B: 1, D: 1, A: 1}, D: {A: 1},
                                    Y: {X: 1}, T: {X: 1, Y: 1}}}
    build_items(STORE, tmp_path, release=RELEASE, per_track=1, seed=0)
    assert json.loads((tmp_path / "modal.json").read_text()) == full   # not the 1-item sample's fit


# ---------- build and load ----------

def test_build_writes_items_manifest_and_modal_and_is_byte_reproducible(tmp_path):
    manifest = build_items(STORE, tmp_path / "b", release=RELEASE, per_track=3, seed=0)
    items, loaded = load_items(tmp_path / "b")
    assert loaded == manifest
    assert [i["track"] for i in items] == ["hypothesize"] * 3 + ["prove"] * 3
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)
    assert manifest["prove"] == {"eligible": 6, "not_rederivable": 7, "excluded_by_since": 0, "sampled": 3}
    assert manifest["hypothesize"] == {"eligible": 13, "goal_not_statable": {}, "goal_not_statable_total": 0,
                                       "excluded_by_since": 0, "sampled": 3}
    assert manifest["population"]["triples"] == 13 and manifest["population"]["n_subjects"] == 9
    assert manifest["hypothesize_gold"] is None and manifest["since"] is None
    assert manifest["release"] == RELEASE and manifest["seed"] == 0 and manifest["per_track"] == 3
    for name in ("manifest.json", "modal.json", "items/prove.json", "items/hypothesize.json"):
        text = (tmp_path / "b" / name).read_text()
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    build_items(STORE, tmp_path / "c", release=RELEASE, per_track=3, seed=0)
    for name in ("manifest.json", "modal.json", "items/prove.json", "items/hypothesize.json"):
        assert (tmp_path / "b" / name).read_bytes() == (tmp_path / "c" / name).read_bytes()


def test_build_with_since_records_the_cut_on_both_tracks(tmp_path):
    manifest = build_items(STORE, tmp_path, release=RELEASE, since="2020-01-01")
    assert manifest["since"] == "2020-01-01"
    assert manifest["prove"]["excluded_by_since"] == 1 and manifest["prove"]["sampled"] == 5
    assert manifest["hypothesize"]["excluded_by_since"] == 1 and manifest["hypothesize"]["sampled"] == 12
    items, _ = load_items(tmp_path)
    assert all(i["cut_date"] >= "2020-01-01" for i in items)


def test_build_restricted_to_subjects_reports_the_restriction(tmp_path):
    manifest = build_items(STORE, tmp_path, release=RELEASE, subjects=[P2])
    assert manifest["population"]["n_subjects"] == 1
    assert manifest["prove"]["eligible"] == 2 and manifest["hypothesize"]["eligible"] == 3


def test_load_items_refuses_a_missing_or_empty_item_set(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_items(tmp_path / "nope")
    (tmp_path / "items").mkdir()
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="no benchmark items"):
        load_items(tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_items.py -q`
Expected: the eleven Task 3 tests pass; the new ones fail with `ImportError: cannot import name 'BuildError'`.

- [ ] **Step 3: Append part B to `items.py`**

Append after `read_release`:

```python
# ---------------------------------------------------------------------------
# items
# ---------------------------------------------------------------------------

class BuildError(RuntimeError):
    """A hypothesize triple is still derivable after hiding. The hider is injectable and a
    wrong hider is a defect in the build, not a dropped item, so this raises."""

    def __init__(self, triple: Triple, derivation: dict[str, Any]) -> None:
        super().__init__(f"hypothesize triple {triple} is still derivable after hiding: "
                         f"{len(derivation['steps'])}-step derivation from visible evidence")
        self.triple = triple
        self.derivation = derivation


def _item(store: FactStore, track: str, triple: Triple, hidden: frozenset[str]) -> dict[str, Any]:
    subject, qualifier, term, taxon = triple
    rows = [a for a in store.annotations(subject) if a.id in hidden]
    assert rows, triple                       # a population triple always has its own row
    anns = store.annotations(subject)
    term_rec = store.term(term)
    return {
        "id": f"{track}/{subject}/{qualifier}/{term}",
        "track": track,
        "goal": Prop(subject, qualifier, term, taxon, False).to_dict(),
        "symbol": min(a.symbol for a in anns),
        "term_name": term_rec.name if term_rec is not None else term,
        "hidden": sorted(hidden),
        "hidden_dates": sorted(a.date for a in rows),
        "cut_date": min(a.date for a in rows),
        "hidden_classes": sorted(evidence_class(a.code) for a in rows),
    }


def prove_items(
    store: FactStore, triples: Iterable[Triple], *, hide: Hider = hide_exact,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One item per triple that the mechanical prover still derives after hiding."""
    items: list[dict[str, Any]] = []
    report = {"eligible": 0, "not_rederivable": 0}
    for triple in triples:
        prop = Prop(*triple, False)
        hidden = hide(store, prop)
        gold = prove(prop, MaskedFactStore(store, hidden))
        if gold is None:
            report["not_rederivable"] += 1
            continue
        report["eligible"] += 1
        items.append({**_item(store, "prove", triple, hidden),
                      "gold": gold, "gold_depth": len(gold["steps"]) - 1})
    return items, report


def _sorry_at(prop: Prop) -> dict[str, Any]:
    return {"biolean": "0.1", "goal": prop.to_dict(), "root": "s1",
            "steps": [{"id": "s1", "rule": "sorry", "conclusion": prop.to_dict(),
                       "provenance": dict(PLACEHOLDER_PROVENANCE)}]}


def hypothesize_items(
    store: FactStore, triples: Iterable[Triple], *, hide: Hider = hide_subtree,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One item per triple whose whole subtree is hidden and whose goal a sorry can state.

    Two checks per triple: the prover must FAIL over the masked store (else ``BuildError``),
    and a single placeholder sorry at the goal must be ACCEPTED (else the triple is counted
    under the alphabetically first code of that rejection and dropped).
    """
    items: list[dict[str, Any]] = []
    not_statable: dict[str, int] = {}
    eligible = 0
    for triple in triples:
        prop = Prop(*triple, False)
        hidden = hide(store, prop)
        masked = MaskedFactStore(store, hidden)
        still = prove(prop, masked)
        if still is not None:
            raise BuildError(triple, still)
        verdict = check(_sorry_at(prop), masked)
        if verdict["errors"]:
            code = min(e["code"] for e in verdict["errors"])
            not_statable[code] = not_statable.get(code, 0) + 1
            continue
        eligible += 1
        items.append(_item(store, "hypothesize", triple, hidden))
    return items, {"eligible": eligible,
                   "goal_not_statable": dict(sorted(not_statable.items())),
                   "goal_not_statable_total": sum(not_statable.values())}


# ---------------------------------------------------------------------------
# live cut, sampling, modal fit
# ---------------------------------------------------------------------------

def apply_since(items: list[dict[str, Any]], since: str | None) -> tuple[list[dict[str, Any]], int]:
    """Keep an item iff ``cut_date >= since`` — the MIN over every hidden row, so an IEA row
    stamped with last month's pipeline run cannot make a decades-old fact 'recent'."""
    if since is None:
        return list(items), 0
    kept = [item for item in items if item["cut_date"] >= since]
    return kept, len(items) - len(kept)


def sample(items: list[dict[str, Any]], n: int | None, seed: int) -> list[dict[str, Any]]:
    """``random.Random(seed).sample`` over the id-sorted eligible list, re-sorted by id."""
    ordered = sorted(items, key=lambda item: item["id"])
    chosen = ordered if n is None or n >= len(ordered) else random.Random(seed).sample(ordered, n)
    return sorted(chosen, key=lambda item: item["id"])


def fit_modal(
    store: FactStore, items: Iterable[dict[str, Any]], *,
    cache: dict[str, frozenset[str]] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """``qualifier -> goal term -> descendant -> number of eligible prove items whose subject
    is visibly annotated at that descendant``. Fit over the FULL eligible enumeration, before
    sampling and before any live cut; the adapter subtracts the item's own subject."""
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for item in items:
        goal = Prop.from_dict(item["goal"])
        assert goal is not None, item["id"]
        masked = MaskedFactStore(store, frozenset(item["hidden"]))
        per_term = counts.setdefault(goal.qualifier, {}).setdefault(goal.term, {})
        for descendant in visible_descendants(masked, goal, cache=cache):
            per_term[descendant] = per_term.get(descendant, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# build and load
# ---------------------------------------------------------------------------

def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def build_items(
    store: FactStore, out_dir: Path, *, release: dict[str, str], per_track: int | None = 500,
    seed: int = 0, since: str | None = None, subjects: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Enumerate, build both tracks, fit the modal prior, cut, sample, freeze. Returns the manifest.

    Order matters and is fixed: the modal prior is fit on every prove-eligible item before
    the live cut and before sampling; the live cut precedes sampling so ``--per-track N``
    yields N live items rather than N minus the cut.
    """
    out_dir = Path(out_dir)
    triples, pop_report = population(store, subjects=subjects)
    cache: dict[str, frozenset[str]] = {}
    prove_all, prove_report = prove_items(store, triples)
    modal = fit_modal(store, prove_all, cache=cache)
    hyp_all, hyp_report = hypothesize_items(
        store, triples, hide=functools.partial(hide_subtree, cache=cache))
    prove_live, prove_cut = apply_since(prove_all, since)
    hyp_live, hyp_cut = apply_since(hyp_all, since)
    prove_sample = sample(prove_live, per_track, seed)
    hyp_sample = sample(hyp_live, per_track, seed)

    (out_dir / "items").mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "items" / "prove.json", prove_sample)
    _write_json(out_dir / "items" / "hypothesize.json", hyp_sample)
    _write_json(out_dir / "modal.json", modal)
    manifest = {
        "schema": 1, "release": dict(release), "seed": seed, "per_track": per_track, "since": since,
        "population": pop_report,
        "prove": {**prove_report, "excluded_by_since": prove_cut, "sampled": len(prove_sample)},
        "hypothesize": {**hyp_report, "excluded_by_since": hyp_cut, "sampled": len(hyp_sample)},
        # GAF records PMIDs and evidence codes, never datasets or method ids: no data-derived
        # gold exists for provenance, and the track is format compliance only (spec §6).
        "hypothesize_gold": None,
    }
    _write_json(out_dir / "manifest.json", manifest)
    return manifest


def load_items(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every item under ``<root>/items`` sorted by id, plus ``<root>/manifest.json``.

    Empty is an error, not a result, for the same reason as ``bench/run.py::load_items``: a
    typo'd ``--items`` must not print a null summary and exit 0.
    """
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"--items path has no manifest.json: {root} (run `mg biolean bench build` first)")
    manifest = json.loads(manifest_path.read_text())
    items: list[dict[str, Any]] = []
    for path in sorted((root / "items").glob("*.json")) if (root / "items").exists() else []:
        items.extend(json.loads(path.read_text()))
    if not items:
        raise ValueError(f"--items path contains no benchmark items: {root}")
    return sorted(items, key=lambda item: item["id"]), manifest
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_items.py -q`
Expected: 23 passed. If `test_sampling_is_seeded_and_sorted_first` finds every seed in `range(2, 8)` agreeing with seed 1 (probability under 1e-6 for 6-choose-3), widen the range and record it.

Mutation checks: (a) in `prove_items`, drop the `not_rederivable` increment — `..._counted_not_dropped_silently` fails; (b) in `hypothesize_items`, replace `raise BuildError` with `continue` — `..._raises_build_error` fails; (c) replace the `not_statable` bookkeeping with `continue` — `..._counted_with_its_code` fails; (d) in `apply_since`, use `max(item["hidden_dates"])` — `..._min_hidden_date` fails on the last assertion; (e) in `build_items`, fit the modal on `prove_sample` — `..._before_sampling` fails; (f) in `sample`, drop the initial sort — `..._sorted_first` still passes (both inputs already sorted), so additionally feed `list(reversed(forward))` and confirm the sample is unchanged, then restore; (g) in `_item`, build `hidden_classes` unsorted — the prove-items test fails.

- [ ] **Step 5: Commit**

```
git add src/methods_graph/biolean/bench/items.py tests/test_biolean_bench_items.py
git commit -m "feat(biolean-bench): prove and hypothesize items, live cut, seeded sampling, modal fit, build/load"
```

---
### Task 5: Scoring and aggregates (`biolean/bench/score.py`)

**Files:**
- Create: `src/methods_graph/biolean/bench/score.py`
- Test: `tests/test_biolean_bench_score.py`

**Interfaces:**
- Produces:
  - `UNPARSED = "UNPARSED"`, `Resolver = Callable[[str], str | None]`, `COMMON_KEYS`, `PROVE_KEYS`, `HYPOTHESIZE_KEYS`, `DEPTH_BUCKETS = ("1", "2", "3", "4+")`, `HYPOTHESIZE_NOTE`.
  - `score_prove(item, raw, store) -> dict`, `score_hypothesize(item, raw, store, resolve) -> dict`, `score_row(item, raw, store, *, resolve=None) -> dict` (dispatch on `item["track"]`, `ValueError` otherwise).
  - `failure_row(item, *, error: str, render_error: str | None) -> dict` — the track's full key set with `None` for every score field.
  - `summarize(rows) -> dict` with keys `n_rows, n_errors, n_render_errors, n_unparsed, n_checked, release, since, prove, hypothesize`.
- Row vocabulary (both tracks): `item, track, goal, hidden, hidden_classes, raw, parsed, error, render_error, error_codes, goal_match` (+ `model`, `items_manifest` attached by `run.py`). Prove adds `gold_depth, accepted, goal_rewritten, hit, hit_with_sorry, sorry_count, unused_sorries, depth`. Hypothesize adds `format_ok, inputs_nonempty, method, method_normalized, method_resolves`.
- Consumes: `render.parse_reply`, `elaborate.elaborate`, `kernel.check`, `MaskedFactStore`.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_bench_score.py`:

```python
"""Per-item scoring reads the kernel's verdict over the item's masked store (spec §6)."""
import json

import pytest

from methods_graph.bench.normalize import normalize_name
from methods_graph.bench.oracle import StaticOracle
from methods_graph.biolean.bench.items import hypothesize_items, population, prove_items
from methods_graph.biolean.bench.score import (
    COMMON_KEYS, DEPTH_BUCKETS, HYPOTHESIZE_KEYS, PROVE_KEYS, UNPARSED, failure_row, score_hypothesize,
    score_prove, score_row, summarize)
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, B, C, D, P1, TAX, axiom, deriv, prop, prop_step, sorry

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)
# score_row attaches no model/manifest; run.py does. The scorer's own key sets:
SCORED_COMMON = COMMON_KEYS - {"model", "items_manifest"}


def _item(track, term, subject=P1):
    pool = PROVE if track == "prove" else HYP
    return next(i for i in pool if i["goal"]["term"] == term and i["goal"]["subject"] == subject)


def _gold_rows():
    return [score_prove(i, json.dumps(i["gold"]), STORE) for i in PROVE]


C_ITEM = _item("prove", C)
GOAL_C = prop(C)


# ---------- prove ----------

def test_gold_derivations_score_as_hits_with_depth_equal_to_gold_depth():
    for item in PROVE:
        row = score_prove(item, json.dumps(item["gold"]), STORE)
        assert (row["accepted"], row["goal_match"], row["goal_rewritten"]) == (True, True, False), item["id"]
        assert row["hit"] is True and row["hit_with_sorry"] is False
        assert row["sorry_count"] == 0 and row["unused_sorries"] == 0
        assert row["depth"] == row["gold_depth"] == 1 and row["error_codes"] == []
        assert row["parsed"] is True and row["raw"] == json.dumps(item["gold"])
        assert set(row) == SCORED_COMMON | PROVE_KEYS


def test_scorer_uses_the_masked_store():
    """The direct row at C is hidden for this item; citing it is AXIOM_NOT_FOUND over the masked
    store though the unmasked store holds two rows there."""
    raw = json.dumps(deriv(GOAL_C, [axiom("s1", C)], "s1"))
    row = score_prove(C_ITEM, raw, STORE)
    assert row["accepted"] is False and row["hit"] is False
    assert row["error_codes"] == ["AXIOM_NOT_FOUND"]
    assert row["goal_match"] is True and row["goal_rewritten"] is False     # right claim, no proof
    assert row["depth"] is None


def test_hit_requires_goal_match_and_zero_used_sorries():
    # (a) an accepted sorry at the goal is hit_with_sorry, never hit
    row = score_prove(C_ITEM, json.dumps(deriv(GOAL_C, [sorry("s1", C)], "s1")), STORE)
    assert row["accepted"] is True and row["goal_match"] is True and row["sorry_count"] == 1
    assert row["hit"] is False and row["hit_with_sorry"] is True
    # (b) an accepted proof of a DIFFERENT (visible) claim: goal_match is judged against the
    # item, not the reply's own goal, so rewriting both consistently is not a hit
    rewritten = deriv(prop(D), [axiom("s1", D)], "s1")
    row = score_prove(C_ITEM, json.dumps(rewritten), STORE)
    assert row["accepted"] is True and row["error_codes"] == []
    assert row["goal_match"] is False and row["goal_rewritten"] is True
    assert row["hit"] is False and row["hit_with_sorry"] is False


def test_goal_rewritten_is_counted():
    rows = [
        score_prove(C_ITEM, json.dumps(C_ITEM["gold"]), STORE),                             # faithful
        score_prove(C_ITEM, json.dumps(deriv(prop(D), [axiom("s1", D)], "s1")), STORE),      # rewritten
        score_prove(C_ITEM, json.dumps({**C_ITEM["gold"], "goal": "C"}), STORE),             # malformed goal
    ]
    assert [r["goal_rewritten"] for r in rows] == [False, True, True]
    assert rows[2]["error_codes"] == ["MALFORMED"] and rows[2]["goal_match"] is True
    assert summarize(rows)["prove"]["n_goal_rewritten"] == 2


def test_depth_counts_propagation_steps_in_the_used_chain():
    two_hops = deriv(GOAL_C, [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B),
                              prop_step("s3", "is_a", "s2", B, C)], "s3")
    row = score_prove(C_ITEM, json.dumps(two_hops), STORE)
    assert row["hit"] is True and row["depth"] == 2
    with_unused = deriv(GOAL_C, [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B), axiom("s3", D),
                                 prop_step("s4", "is_a", "s2", B, C)], "s4")
    row = score_prove(C_ITEM, json.dumps(with_unused), STORE)
    assert row["hit"] is True and row["depth"] == 2                       # s3 is not on the chain


def test_unparsed_reply_is_a_miss_with_unparsed_code():
    row = score_prove(C_ITEM, "I do not know this gene.", STORE)
    assert row["parsed"] is False and row["hit"] is False and row["accepted"] is False
    assert row["error_codes"] == [UNPARSED]
    assert row["goal_match"] is None and row["goal_rewritten"] is None
    assert row["sorry_count"] is None and row["depth"] is None
    rows = _gold_rows()[:5] + [row]
    summary = summarize(rows)
    assert summary["n_unparsed"] == 1 and summary["n_checked"] == 5 and summary["n_errors"] == 0
    assert summary["prove"]["n"] == 6 and summary["prove"]["hit_rate"] == 5 / 6   # a miss, in the denominator
    assert summary["prove"]["error_items"] == {UNPARSED: 1}
    assert summary["prove"]["error_items_denominator"] == 6
    assert summary["prove"]["error_occurrences"] == {UNPARSED: 1}


def test_error_histograms_count_items_and_occurrences():
    two_and_one = deriv(GOAL_C, [axiom("s1", "GO:0009999"), axiom("s2", "GO:0009998"), axiom("s3", C)], "s3")
    row = score_prove(C_ITEM, json.dumps(two_and_one), STORE)
    assert row["error_codes"] == ["AXIOM_NOT_FOUND", "UNKNOWN_TERM", "UNKNOWN_TERM"]
    summary = summarize([row])["prove"]
    assert summary["error_items"] == {"AXIOM_NOT_FOUND": 1, "UNKNOWN_TERM": 1}
    assert summary["error_items_denominator"] == 1
    assert summary["error_occurrences"] == {"AXIOM_NOT_FOUND": 1, "UNKNOWN_TERM": 2}
    assert summary["error_occurrences_denominator"] == 3


def test_prove_aggregates_carry_denominators_and_every_depth_bucket():
    summary = summarize(_gold_rows())
    assert summary["n_rows"] == 6 and summary["n_checked"] == 6
    p = summary["prove"]
    assert p["n"] == 6 and p["n_hits"] == 6 and p["hit_rate"] == 1.0
    assert p["hit_with_sorry_rate"] == 0.0 and p["acceptance_rate"] == 1.0 and p["mean_depth"] == 1.0
    assert p["by_evidence_class"] == {"electronic": {"n": 1, "hit_rate": 1.0},
                                      "experimental": {"n": 6, "hit_rate": 1.0}}
    assert tuple(p["by_gold_depth"]) == DEPTH_BUCKETS
    assert p["by_gold_depth"]["1"] == {"n": 6, "hit_rate": 1.0}
    assert p["by_gold_depth"]["4+"] == {"n": 0, "hit_rate": None}       # None, never 0.0
    assert summarize([])["prove"]["hit_rate"] is None and summarize([])["prove"]["mean_depth"] is None


# ---------- hypothesize ----------

def _sorry_reply(item, **provenance):
    prov = {"method": "m:deseq2", "inputs": ["GEO:GSE0"], "parameters": {}, "claim": "computed",
            **provenance}
    goal = item["goal"]
    return json.dumps({"biolean": "0.1", "goal": goal, "root": "s1",
                       "steps": [{"id": "s1", "rule": "sorry", "conclusion": goal, "provenance": prov}]})


B_HYP = _item("hypothesize", B)


def test_format_ok_requires_an_accepted_sorry_root():
    ok = score_hypothesize(B_HYP, _sorry_reply(B_HYP), STORE, None)
    assert ok["format_ok"] is True and ok["goal_match"] is True and ok["inputs_nonempty"] is True
    assert ok["error_codes"] == [] and set(ok) == SCORED_COMMON | HYPOTHESIZE_KEYS
    # An ACCEPTED axiom derivation of a visible claim is not format-compliant for this track.
    visible = json.dumps(deriv(prop(D), [axiom("s1", D)], "s1"))
    row = score_hypothesize(B_HYP, visible, STORE, None)
    assert row["error_codes"] == [] and row["format_ok"] is False
    assert row["goal_match"] is False and row["inputs_nonempty"] is None and row["method"] is None
    # A sorry with empty inputs is SORRY_MALFORMED: rejected, inputs_nonempty False.
    row = score_hypothesize(B_HYP, _sorry_reply(B_HYP, inputs=[]), STORE, None)
    assert row["format_ok"] is False and row["inputs_nonempty"] is False
    assert row["error_codes"] == ["SORRY_MALFORMED"]
    # Unparsed.
    row = score_hypothesize(B_HYP, "no", STORE, None)
    assert row["format_ok"] is False and row["goal_match"] is None and row["error_codes"] == [UNPARSED]
    assert row["inputs_nonempty"] is None and row["method_resolves"] is None


def test_method_resolves_is_none_without_a_graph():
    row = score_hypothesize(B_HYP, _sorry_reply(B_HYP), STORE, None)
    assert row["method"] == "m:deseq2" and row["method_normalized"] is None
    assert row["method_resolves"] is None                                  # None, never False
    summary = summarize([row])["hypothesize"]
    assert summary["method_resolves"] == {"n": 0, "rate": None}
    assert summary["n_method_resolves_none"] == 1 and summary["method_unresolved"] == []


def test_method_is_resolved_by_exact_lookup_not_search():
    oracle = StaticOracle(methods=["m:deseq2", "m:star"], modules={}, operations={}, inputs={}, outputs={})
    resolve = lambda name: normalize_name(name, oracle)
    rows = [score_hypothesize(B_HYP, _sorry_reply(B_HYP, method=m), STORE, resolve)
            for m in ("DESeq2", "deseq", "m:star", "edgeR")]
    assert [r["method_normalized"] for r in rows] == ["m:deseq2", "m:deseq2", "m:star", None]
    assert [r["method_resolves"] for r in rows] == [True, True, True, False]
    assert [r["method"] for r in rows] == ["DESeq2", "deseq", "m:star", "edgeR"]        # verbatim
    summary = summarize(rows)["hypothesize"]
    assert summary["method_resolves"] == {"n": 4, "rate": 0.75}
    assert summary["method_unresolved"] == [["edgeR", 1]]


def test_hypothesize_rows_and_summary_carry_no_hit_keys():
    row = score_row(B_HYP, _sorry_reply(B_HYP), STORE)
    assert not {"hit", "hit_with_sorry", "accepted", "depth", "gold_depth"} & set(row)
    prove_row = score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)
    assert set(prove_row) & set(row) == SCORED_COMMON
    block = summarize([row])["hypothesize"]
    assert not {"hit", "hit_rate", "accepted", "acceptance_rate", "hit_with_sorry_rate"} & set(block)
    assert block["note"].startswith("format compliance only")
    assert block["format_ok"] == {"n": 1, "rate": 1.0} and block["n"] == 1


def test_score_row_dispatches_on_track_and_rejects_unknown_tracks():
    assert score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)["hit"] is True
    with pytest.raises(ValueError, match="unknown track"):
        score_row({**C_ITEM, "track": "guess"}, "{}", STORE)


def test_failure_row_has_exactly_the_tracks_key_set():
    scored = score_row(C_ITEM, json.dumps(C_ITEM["gold"]), STORE)
    failed = failure_row(C_ITEM, error="rate limited", render_error=None)
    assert set(failed) == set(scored)
    assert failed["error"] == "rate limited" and failed["raw"] is None and failed["parsed"] is False
    assert failed["hit"] is None and failed["error_codes"] is None and failed["gold_depth"] == 1
    assert set(failure_row(B_HYP, error="x", render_error=None)) == set(score_row(B_HYP, "{}", STORE))
    assert set(failure_row({"id": "?"}, error="render failed", render_error="KeyError")) \
        >= SCORED_COMMON | PROVE_KEYS | HYPOTHESIZE_KEYS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_score.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.bench.score'`.

- [ ] **Step 3: Write the module**

`src/methods_graph/biolean/bench/score.py`:

```python
"""Per-item scoring for both tracks, and the aggregates with their denominators.

The kernel is the only judge: every parsed reply is ``elaborate`` + ``check`` over
``MaskedFactStore(store, item.hidden)`` and this module reads the verdict. It never trusts
the reply's own ``goal``: ``goal_match`` compares the elaborated root conclusion to the
item's proposition, so a model that rewrites the claim and proves the rewrite is counted
as ``goal_rewritten``, not as a hit.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from methods_graph.biolean.bench.render import parse_reply
from methods_graph.biolean.elaborate import elaborate
from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import FactStore, MaskedFactStore

UNPARSED = "UNPARSED"
Resolver = Callable[[str], "str | None"]

# The row vocabulary every row carries, whatever its track. `model` and `items_manifest`
# are attached by run.py; score_row and failure_row emit the rest.
COMMON_KEYS = frozenset({
    "item", "track", "model", "items_manifest", "goal", "hidden", "hidden_classes",
    "raw", "parsed", "error", "render_error", "error_codes", "goal_match"})
PROVE_KEYS = frozenset({"gold_depth", "accepted", "goal_rewritten", "hit", "hit_with_sorry",
                        "sorry_count", "unused_sorries", "depth"})
HYPOTHESIZE_KEYS = frozenset({"format_ok", "inputs_nonempty", "method", "method_normalized",
                              "method_resolves"})
DEPTH_BUCKETS = ("1", "2", "3", "4+")
HYPOTHESIZE_NOTE = (
    "format compliance only: GAF records PMIDs and evidence codes, never datasets or method "
    "ids, so no data-grounded target exists for provenance and a constant reply saturates "
    "every rate; the track's knowledge measure arrives with Phase B")


# ---------------------------------------------------------------------------
# one row
# ---------------------------------------------------------------------------

def _base(item: dict[str, Any], raw: Any, parsed: bool) -> dict[str, Any]:
    return {"item": item["id"], "track": item["track"], "goal": item["goal"],
            "hidden": list(item["hidden"]),
            "hidden_classes": list(item.get("hidden_classes") or []),
            "raw": raw, "parsed": parsed, "error": None, "render_error": None}


def _root_step(canonical: dict[str, Any]) -> dict[str, Any] | None:
    """The step named by ``root``, or ``None`` when ``root`` names no step."""
    steps, root = canonical.get("steps"), canonical.get("root")
    if not isinstance(steps, list) or not isinstance(root, str):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("id") == root:
            return step
    return None


def _goal_match(root: dict[str, Any] | None, target: Prop) -> bool | None:
    if root is None:
        return None
    return Prop.from_dict(root.get("conclusion")) == target


def _checked(item: dict[str, Any], reply: dict[str, Any], store: FactStore):
    """``(canonical, verdict, root step, target)`` for a parsed reply over the item's masked store."""
    target = Prop.from_dict(item["goal"])
    assert target is not None, item["id"]
    masked = MaskedFactStore(store, frozenset(item["hidden"]))
    canonical, _report = elaborate(reply, masked)
    verdict = check(canonical, masked)
    return canonical, verdict, _root_step(canonical), target


def _codes(verdict: dict[str, Any]) -> list[str]:
    return sorted(e["code"] for e in verdict["errors"])


def score_prove(item: dict[str, Any], raw: Any, store: FactStore) -> dict[str, Any]:
    reply = parse_reply(raw)
    row = {**_base(item, raw, reply is not None), "gold_depth": item.get("gold_depth")}
    if reply is None:
        row.update(accepted=False, goal_match=None, goal_rewritten=None, hit=False,
                   hit_with_sorry=False, sorry_count=None, unused_sorries=None, depth=None,
                   error_codes=[UNPARSED])
        return row
    canonical, verdict, root, target = _checked(item, reply, store)
    accepted = verdict["verdict"] == "ACCEPTED"
    goal_match = _goal_match(root, target)
    sorry_count = verdict["sorry_count"]
    row.update(
        accepted=accepted,
        goal_match=goal_match,
        goal_rewritten=Prop.from_dict(canonical.get("goal")) != target,
        hit=accepted and goal_match is True and sorry_count == 0,
        hit_with_sorry=accepted and goal_match is True and sorry_count > 0,
        sorry_count=sorry_count,
        unused_sorries=verdict["unused_sorries"],
        # Propagation steps on the used chain: every step has an id when accepted, so the
        # used chain is steps_checked minus unused_steps; minus one for the axiom.
        depth=(verdict["steps_checked"] - len(verdict["unused_steps"]) - 1) if accepted else None,
        error_codes=_codes(verdict),
    )
    return row


def score_hypothesize(
    item: dict[str, Any], raw: Any, store: FactStore, resolve: Resolver | None,
) -> dict[str, Any]:
    reply = parse_reply(raw)
    row = _base(item, raw, reply is not None)
    if reply is None:
        row.update(format_ok=False, goal_match=None, inputs_nonempty=None, method=None,
                   method_normalized=None, method_resolves=None, error_codes=[UNPARSED])
        return row
    _canonical, verdict, root, target = _checked(item, reply, store)
    accepted = verdict["verdict"] == "ACCEPTED"
    is_sorry = root is not None and root.get("rule") == "sorry"
    prov = root.get("provenance") if is_sorry else None
    prov = prov if isinstance(prov, dict) else {}
    inputs = prov.get("inputs")
    method = prov.get("method") if isinstance(prov.get("method"), str) else None
    normalized = resolve(method) if resolve is not None and method is not None else None
    row.update(
        format_ok=accepted and is_sorry,
        goal_match=_goal_match(root, target),
        inputs_nonempty=(isinstance(inputs, list) and len(inputs) > 0) if is_sorry else None,
        method=method,
        method_normalized=normalized,
        # None (undefined) without a graph or without a method string; never False by default.
        method_resolves=None if resolve is None or method is None else normalized is not None,
        error_codes=_codes(verdict),
    )
    return row


def score_row(
    item: dict[str, Any], raw: Any, store: FactStore, *, resolve: Resolver | None = None,
) -> dict[str, Any]:
    track = item["track"]
    if track == "prove":
        return score_prove(item, raw, store)
    if track == "hypothesize":
        return score_hypothesize(item, raw, store, resolve)
    raise ValueError(f"unknown track: {track!r}")


def failure_row(item: dict[str, Any], *, error: str, render_error: str | None) -> dict[str, Any]:
    """A row for an item that never produced a scorable answer: the track's key set, ``None``
    where a score would be. ``.get`` throughout — a render failure can be a malformed item."""
    track = item.get("track")
    keys = (PROVE_KEYS if track == "prove" else HYPOTHESIZE_KEYS if track == "hypothesize"
            else PROVE_KEYS | HYPOTHESIZE_KEYS)
    row: dict[str, Any] = {
        "item": item.get("id"), "track": track, "goal": item.get("goal"),
        "hidden": list(item.get("hidden") or []),
        "hidden_classes": list(item.get("hidden_classes") or []),
        "raw": None, "parsed": False, "error": error, "render_error": render_error,
        "error_codes": None, "goal_match": None, **{key: None for key in keys}}
    if "gold_depth" in row:
        row["gold_depth"] = item.get("gold_depth")
    return row


# ---------------------------------------------------------------------------
# aggregates
# ---------------------------------------------------------------------------

def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: list[Any]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _histograms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``error_items`` (rows whose codes contain the code) and ``error_occurrences`` (error
    records carrying it), each with its denominator. Items is the headline: it is invariant
    to derivation length."""
    items: dict[str, int] = {}
    occurrences: dict[str, int] = {}
    for row in rows:
        codes = row["error_codes"] or []
        for code in set(codes):
            items[code] = items.get(code, 0) + 1
        for code in codes:
            occurrences[code] = occurrences.get(code, 0) + 1
    return {"error_items": dict(sorted(items.items())), "error_items_denominator": len(rows),
            "error_occurrences": dict(sorted(occurrences.items())),
            "error_occurrences_denominator": sum(occurrences.values())}


def _depth_bucket(gold_depth: Any) -> str | None:
    if not isinstance(gold_depth, int):
        return None
    return str(gold_depth) if gold_depth in (1, 2, 3) else "4+"


def _summarize_prove(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hits = [r for r in rows if r["hit"]]
    by_class: dict[str, Any] = {}
    for cls in sorted({c for r in rows for c in r["hidden_classes"]}):
        sub = [r for r in rows if cls in r["hidden_classes"]]
        by_class[cls] = {"n": len(sub), "hit_rate": _rate(sum(1 for r in sub if r["hit"]), len(sub))}
    by_depth: dict[str, Any] = {}
    for bucket in DEPTH_BUCKETS:
        sub = [r for r in rows if _depth_bucket(r.get("gold_depth")) == bucket]
        by_depth[bucket] = {"n": len(sub), "hit_rate": _rate(sum(1 for r in sub if r["hit"]), len(sub))}
    return {
        "n": len(rows), "n_hits": len(hits), "hit_rate": _rate(len(hits), len(rows)),
        "hit_with_sorry_rate": _rate(sum(1 for r in rows if r["hit_with_sorry"]), len(rows)),
        "acceptance_rate": _rate(sum(1 for r in rows if r["accepted"]), len(rows)),
        "n_goal_rewritten": sum(1 for r in rows if r["goal_rewritten"]),
        "mean_depth": _mean([r["depth"] for r in hits]),
        "by_evidence_class": by_class,
        "by_gold_depth": by_depth,
        **_histograms(rows),
    }


def _rate_over_defined(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    defined = [r for r in rows if r[key] is not None]
    return {"n": len(defined), "rate": _rate(sum(1 for r in defined if r[key]), len(defined))}


def _summarize_hypothesize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unresolved: dict[str, int] = {}
    for r in rows:
        if r["method_resolves"] is False:
            unresolved[r["method"]] = unresolved.get(r["method"], 0) + 1
    return {
        "note": HYPOTHESIZE_NOTE,
        "n": len(rows),
        "format_ok": _rate_over_defined(rows, "format_ok"),
        "goal_match": _rate_over_defined(rows, "goal_match"),
        "inputs_nonempty": _rate_over_defined(rows, "inputs_nonempty"),
        "method_resolves": _rate_over_defined(rows, "method_resolves"),
        "n_method_resolves_none": sum(1 for r in rows if r["method_resolves"] is None),
        "method_unresolved": [[name, n] for name, n in sorted(unresolved.items())],
        **_histograms(rows),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Two tracks, never pooled. ``n_rows == n_errors + n_unparsed + n_checked`` exactly."""
    errors = [r for r in rows if r["error"] is not None]
    scored = [r for r in rows if r["error"] is None]
    unparsed = [r for r in scored if not r["parsed"]]
    manifests = {json.dumps(r.get("items_manifest"), sort_keys=True) for r in rows}
    manifest = rows[0].get("items_manifest") if len(manifests) == 1 else None
    manifest = manifest if isinstance(manifest, dict) else {}
    return {
        "n_rows": len(rows),
        "n_errors": len(errors),
        "n_render_errors": sum(1 for r in rows if r.get("render_error")),
        "n_unparsed": len(unparsed),
        "n_checked": len(scored) - len(unparsed),
        "release": manifest.get("release"),
        "since": manifest.get("since"),
        "prove": _summarize_prove([r for r in scored if r["track"] == "prove"]),
        "hypothesize": _summarize_hypothesize([r for r in scored if r["track"] == "hypothesize"]),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_score.py -q`
Expected: 14 passed.

Mutation checks: (a) in `_checked`, pass `store` instead of `masked` to `check` — `test_scorer_uses_the_masked_store` fails (accepted); (b) `hit = accepted and goal_match is True` (drop the sorry condition) — `..._zero_used_sorries` (a) fails; (c) compute `goal_match` from `canonical["goal"]` instead of the root conclusion — (b) of the same test fails; (d) `goal_rewritten = False` — `..._is_counted` fails; (e) `depth = verdict["steps_checked"]` — `..._propagation_steps` fails; (f) in `summarize`, filter unparsed rows out of the prove list — `..._unparsed_code` fails (hit_rate 1.0); (g) in `_histograms`, count `codes` instead of `set(codes)` for items — `..._items_and_occurrences` fails; (h) drop zero-count buckets from `by_gold_depth` — `..._every_depth_bucket` fails; (i) `method_resolves = normalized is not None` unconditionally — `..._none_without_a_graph` fails; (j) `format_ok = accepted` — `..._accepted_sorry_root` fails on the visible-axiom case.

- [ ] **Step 5: Commit**

```
git add src/methods_graph/biolean/bench/score.py tests/test_biolean_bench_score.py
git commit -m "feat(biolean-bench): per-item scoring over the masked store, aggregates with denominators"
```

---
### Task 6: Baselines (`biolean/bench/baselines.py`)

**Files:**
- Create: `src/methods_graph/biolean/bench/baselines.py`
- Test: `tests/test_biolean_bench_baselines.py`

**Interfaces:**
- Produces: `BASELINE_TRACK = {"gold": "prove", "random": "prove", "modal": "prove", "template": "hypothesize"}`, `TEMPLATE_PROVENANCE`, `is_baseline_spec(spec) -> bool`, `gold_answer(item, store) -> dict`, `random_answer(item, store, rng) -> dict`, `modal_answer(item, store, modal) -> dict`, `template_answer(item) -> dict`, `baseline_adapter(spec, items, store, *, modal_path: Path | None = None) -> Callable[[str], str]` (raises `AdapterError` for an unknown spec, a wrong-track item set, a bad seed, or a missing `modal.json`).
- Consumes: `items.visible_descendants`, `render.render_prompt`, `render.claim_text`, `kernel.propagating_parents`, `tactics._starts`, `tactics.prove`, `bench.adapters.AdapterError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_bench_baselines.py`:

```python
"""gold (ceiling), random (floor), modal (gene-blind prior), template (hypothesize constant)."""
import json

import pytest

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.baselines import (
    BASELINE_TRACK, baseline_adapter, is_baseline_spec, modal_answer, template_answer)
from methods_graph.biolean.bench.items import build_items, fit_modal, hypothesize_items, population, prove_items
from methods_graph.biolean.bench.render import render_prompt
from methods_graph.biolean.bench.score import score_row, summarize
from methods_graph.biolean.props import Annotation, Edge, Term
from methods_graph.biolean.store import StaticFactStore
from tests.biolean_fixture import RELEASE, mini_store
from tests.test_biolean_kernel import TAX

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)


def _rows(items, adapter, resolve=None):
    return [score_row(item, adapter(render_prompt(item)), STORE, resolve=resolve) for item in items]


def _axiom_terms(rows):
    return [json.loads(r["raw"])["steps"][0]["conclusion"]["term"] for r in rows]


def test_baseline_specs_are_recognized():
    assert all(is_baseline_spec(s) for s in ("gold:", "random:3", "modal:", "template:"))
    assert not is_baseline_spec("claude:opus") and not is_baseline_spec("static:x.json")
    assert BASELINE_TRACK["template"] == "hypothesize"


def test_gold_hits_every_prove_item():
    rows = _rows(PROVE, baseline_adapter("gold:", PROVE, STORE))
    assert all(r["hit"] for r in rows) and summarize(rows)["prove"]["hit_rate"] == 1.0
    assert [r["depth"] for r in rows] == [1] * 6


def test_random_baseline_is_structurally_valid_and_seeded():
    rows = _rows(PROVE, baseline_adapter("random:0", PROVE, STORE))
    for r in rows:
        assert r["parsed"] and (r["hit"] or r["error_codes"] == ["ROOT_MISMATCH"]), r["error_codes"]
    again = _rows(PROVE, baseline_adapter("random:0", PROVE, STORE))
    assert [r["raw"] for r in again] == [r["raw"] for r in rows]
    others = [[r["raw"] for r in _rows(PROVE, baseline_adapter(f"random:{s}", PROVE, STORE))] for s in range(1, 6)]
    assert any(o != [r["raw"] for r in rows] for o in others)
    with pytest.raises(AdapterError, match="integer seed"):
        baseline_adapter("random:x", PROVE, STORE)


def test_modal_with_singleton_keys_emits_the_hidden_axiom_and_misses(tmp_path):
    """Every fixture key has one subject, so leaving it out empties the counter."""
    build_items(STORE, tmp_path, release=RELEASE)
    rows = _rows(PROVE, baseline_adapter("modal:", PROVE, STORE, modal_path=tmp_path / "modal.json"))
    assert [r["hit"] for r in rows] == [False] * 6
    assert all(r["error_codes"] == ["AXIOM_NOT_FOUND"] for r in rows)
    assert _axiom_terms(rows) == [r["goal"]["term"] for r in rows]
    with pytest.raises(AdapterError, match="modal.json"):
        baseline_adapter("modal:", PROVE, STORE, modal_path=None)


def _three_subject_store():
    """T with is_a children C1 < C2. S1 sits at T and C1; S2 and S3 at T and C2."""
    T, C1, C2 = "GO:0000001", "GO:0000002", "GO:0000003"
    terms = [Term(t, t, "biological_process", False, (), (), ()) for t in (T, C1, C2)]
    edges = [Edge(C1, "is_a", T), Edge(C2, "is_a", T)]

    def ann(i, subject, term):
        return Annotation(i, subject, subject[-2:], "involved_in", False, term, term, ("PMID:1",),
                          "IDA", "ECO:0000314", (), "P", "protein", TAX, "", "2020-01-01", "UniProt", "", "")
    anns = [ann("a1", "UniProtKB:S1", T), ann("a2", "UniProtKB:S1", C1),
            ann("a3", "UniProtKB:S2", T), ann("a4", "UniProtKB:S2", C2),
            ann("a5", "UniProtKB:S3", T), ann("a6", "UniProtKB:S3", C2)]
    return StaticFactStore(terms, edges, anns), T, C1, C2


def test_modal_leaves_the_subject_out_and_breaks_ties_by_sorted_term_id():
    store, T, C1, C2 = _three_subject_store()
    items, _ = prove_items(store, population(store)[0])
    t_items = [i for i in items if i["goal"]["term"] == T]
    assert [i["goal"]["subject"] for i in t_items] == ["UniProtKB:S1", "UniProtKB:S2", "UniProtKB:S3"]
    modal = fit_modal(store, items)
    assert modal == {"involved_in": {T: {C1: 1, C2: 2}}}
    answers = [modal_answer(i, store, modal) for i in t_items]
    # S1 left out: {C1: 0, C2: 2} -> C2 (S1 has no row there: a miss).
    # S2 / S3 left out: {C1: 1, C2: 1} -> tie -> C1 by sorted term id (a miss for both).
    assert [a["steps"][0]["conclusion"]["term"] for a in answers] == [C2, C1, C1]
    rows = [score_row(i, json.dumps(a), store) for i, a in zip(t_items, answers)]
    assert [r["hit"] for r in rows] == [False, False, False]
    assert all(r["error_codes"] == ["AXIOM_NOT_FOUND"] for r in rows)
    assert all([s["rule"] for s in a["steps"]] == ["axiom", "is_a"] for a in answers)


def test_template_baseline_scores_one_on_every_hypothesize_rate():
    resolve = lambda name: name if name == "m:deseq2" else None
    rows = _rows(HYP, baseline_adapter("template:", HYP, STORE), resolve=resolve)
    block = summarize(rows)["hypothesize"]
    assert block["n"] == 13
    for key in ("format_ok", "goal_match", "inputs_nonempty", "method_resolves"):
        assert block[key] == {"n": 13, "rate": 1.0}, key
    answer = template_answer(HYP[0])
    assert answer["steps"][0]["provenance"]["method"] == "m:deseq2"
    assert answer["steps"][0]["provenance"]["inputs"] == ["GEO:GSE0"]
    assert HYP[0]["symbol"] in answer["steps"][0]["provenance"]["claim"]


def test_baseline_on_the_wrong_track_is_a_usage_error():
    with pytest.raises(AdapterError, match="--track prove"):
        baseline_adapter("gold:", HYP, STORE)
    with pytest.raises(AdapterError, match="--track hypothesize"):
        baseline_adapter("template:", PROVE, STORE)
    with pytest.raises(AdapterError, match="--track prove"):
        baseline_adapter("random:1", PROVE + HYP, STORE)
    with pytest.raises(AdapterError, match="not a baseline"):
        baseline_adapter("static:x", PROVE, STORE)
    adapter = baseline_adapter("gold:", PROVE, STORE)
    with pytest.raises(AdapterError, match="no answer"):
        adapter("a prompt no item rendered")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_baselines.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.bench.baselines'`.

- [ ] **Step 3: Write the module**

`src/methods_graph/biolean/bench/baselines.py`:

```python
"""Ceiling, floor, the gene-blind prior, and the constant reply that saturates hypothesize.

Dispatched by item track; a baseline on the wrong track is a usage error raised as
``AdapterError`` so the CLI turns it into exit 2. Every answer is a derivation dict the
kernel will either accept or reject for a stated reason — no baseline emits malformed JSON.
"""
from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path
from typing import Any, Callable

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.items import visible_descendants
from methods_graph.biolean.bench.render import claim_text, render_prompt
from methods_graph.biolean.kernel import propagating_parents
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import FactStore, MaskedFactStore
from methods_graph.biolean.tactics import _starts, prove

BASELINE_TRACK = {"gold": "prove", "random": "prove", "modal": "prove", "template": "hypothesize"}
TEMPLATE_PROVENANCE = {"method": "m:deseq2", "inputs": ["GEO:GSE0"], "parameters": {}}
_MAX_RANDOM_LENGTH = 4


def is_baseline_spec(spec: str) -> bool:
    return spec.partition(":")[0] in BASELINE_TRACK


# ---------------------------------------------------------------------------
# derivation builders
# ---------------------------------------------------------------------------

def _derivation(goal: Prop, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"biolean": "0.1", "goal": goal.to_dict(), "steps": steps, "root": steps[-1]["id"]}


def _at(goal: Prop, term: str) -> dict[str, Any]:
    return Prop(goal.subject, goal.qualifier, term, goal.taxon, False).to_dict()


def _axiom_only(goal: Prop) -> dict[str, Any]:
    """An axiom at the goal term itself. The item hides that row, so this is a counted miss."""
    return _derivation(goal, [{"id": "s1", "rule": "axiom", "conclusion": goal.to_dict()}])


def _chain(goal: Prop, start: str, path: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Axiom at ``start`` then one propagation step per ``(child, relation, parent)`` hop."""
    steps: list[dict[str, Any]] = [{"id": "s1", "rule": "axiom", "conclusion": _at(goal, start)}]
    for i, (child, relation, parent) in enumerate(path, start=2):
        steps.append({"id": f"s{i}", "rule": relation, "premises": [f"s{i - 1}"],
                      "edge": [child, parent], "conclusion": _at(goal, parent)})
    return _derivation(goal, steps)


def _shortest_path(start: str, target: str, store: FactStore) -> list[tuple[str, str, str]] | None:
    """Hops from ``start`` up to ``target`` over propagating edges (sorted expansion), or ``None``."""
    if start == target:
        return []
    came_from: dict[str, tuple[str, str]] = {}
    seen = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        for parent, relation in propagating_parents(cur, store):
            if parent in seen:
                continue
            seen.add(parent)
            came_from[parent] = (cur, relation)
            if parent == target:
                path: list[tuple[str, str, str]] = []
                node = target
                while node != start:
                    child, rel = came_from[node]
                    path.append((child, rel, node))
                    node = child
                return list(reversed(path))
            queue.append(parent)
    return None


def _masked(item: dict[str, Any], store: FactStore) -> tuple[Prop, MaskedFactStore]:
    goal = Prop.from_dict(item["goal"])
    assert goal is not None, item["id"]
    return goal, MaskedFactStore(store, frozenset(item["hidden"]))


# ---------------------------------------------------------------------------
# the four baselines
# ---------------------------------------------------------------------------

def gold_answer(item: dict[str, Any], store: FactStore) -> dict[str, Any]:
    """The mechanical prover over the item's masked store: the ceiling, a CI gate at 1.0."""
    goal, masked = _masked(item, store)
    derivation = prove(goal, masked)
    return derivation if derivation is not None else _axiom_only(goal)


def random_answer(item: dict[str, Any], store: FactStore, rng: random.Random) -> dict[str, Any]:
    """A seeded random visible start under the item's qualifier, a seeded random upward walk of
    seeded random length, root at its end. Structurally valid, so accepted exactly when the
    walk ends at the target. The floor."""
    goal, masked = _masked(item, store)
    starts = _starts(goal.subject, goal.qualifier, goal.taxon, masked)
    if not starts:
        return _axiom_only(goal)
    start = cur = rng.choice(starts)
    path: list[tuple[str, str, str]] = []
    for _ in range(rng.randint(1, _MAX_RANDOM_LENGTH)):
        parents = propagating_parents(cur, masked)
        if not parents:
            break
        parent, relation = rng.choice(parents)
        path.append((cur, relation, parent))
        cur = parent
    return _chain(goal, start, path)


def modal_answer(item: dict[str, Any], store: FactStore, modal: dict[str, Any]) -> dict[str, Any]:
    """The gene-blind prior: the descendant most often annotated across other eligible items
    with the same ``(qualifier, goal term)``, the item's own subject subtracted, ties by sorted
    term id, plus the shortest path up. An empty counter emits the hidden axiom (a miss)."""
    goal, masked = _masked(item, store)
    counts = dict(modal.get(goal.qualifier, {}).get(goal.term, {}))
    for descendant in visible_descendants(masked, goal):
        counts[descendant] = counts.get(descendant, 0) - 1        # leave this subject out
    ranked = sorted((-n, term) for term, n in counts.items() if n > 0)
    if not ranked:
        return _axiom_only(goal)
    best = ranked[0][1]
    path = _shortest_path(best, goal.term, masked)
    return _chain(goal, best, path) if path is not None else _axiom_only(goal)


def template_answer(item: dict[str, Any]) -> dict[str, Any]:
    """A constant sorry-root reply carrying the item's claim. Saturates every hypothesize rate;
    printed beside every model so the ceiling is visible."""
    goal = Prop.from_dict(item["goal"])
    assert goal is not None, item["id"]
    step = {"id": "s1", "rule": "sorry", "conclusion": goal.to_dict(),
            "provenance": {**TEMPLATE_PROVENANCE, "claim": claim_text(item)}}
    return _derivation(goal, [step])


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------

def _table(items: list[dict[str, Any]], answer: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[str], str]:
    """Answers keyed by rendered prompt, computed in item order so a seeded RNG is deterministic.
    An adapter only ever sees the prompt, which also asserts prompts are unique per item."""
    table = {render_prompt(item): json.dumps(answer(item), sort_keys=True) for item in items}

    def _adapter(prompt: str) -> str:
        if prompt not in table:
            raise AdapterError("baseline has no answer for this prompt")
        return table[prompt]
    return _adapter


def baseline_adapter(
    spec: str, items: list[dict[str, Any]], store: FactStore, *, modal_path: Path | None = None,
) -> Callable[[str], str]:
    """``gold:`` / ``random:<seed>`` / ``modal:`` / ``template:`` over a specific item set."""
    provider, _, argument = spec.partition(":")
    if provider not in BASELINE_TRACK:
        raise AdapterError(f"{spec!r} is not a baseline spec (gold:, random:<seed>, modal:, template:)")
    track = BASELINE_TRACK[provider]
    wrong = sorted({item["track"] for item in items} - {track})
    if wrong:
        raise AdapterError(f"{provider}: is a {track}-track baseline but the item set also holds "
                           f"{', '.join(wrong)} items; pass --track {track}")
    if provider == "gold":
        return _table(items, lambda item: gold_answer(item, store))
    if provider == "random":
        try:
            rng = random.Random(int(argument))
        except ValueError:
            raise AdapterError(f"random baseline needs an integer seed: random:<seed>, got {spec!r}") from None
        return _table(items, lambda item: random_answer(item, store, rng))
    if provider == "modal":
        if modal_path is None or not Path(modal_path).exists():
            raise AdapterError(f"modal baseline needs modal.json beside the items (looked at {modal_path})")
        modal = json.loads(Path(modal_path).read_text())
        return _table(items, lambda item: modal_answer(item, store, modal))
    return _table(items, template_answer)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_baselines.py -q`
Expected: 8 passed.

Mutation checks: (a) in `gold_answer`, call `prove(goal, store)` (unmasked) — `test_gold_hits_every_prove_item` fails (the C item's gold becomes a single hidden axiom); (b) in `_chain`, emit `"edge": [parent, child]` — the random test fails with `EDGE_NOT_FOUND` in `error_codes`; (c) in `modal_answer`, drop the subtraction loop — `..._leaves_the_subject_out...` fails (S2 and S3 get C2 and hit); (d) rank ties by `-term` (reverse) — the same test fails (S2/S3 get C2); (e) in `template_answer`, set `inputs` to `[]` — `..._one_on_every_hypothesize_rate` fails; (f) drop the wrong-track check — `..._usage_error` fails.

- [ ] **Step 5: Commit**

```
git add src/methods_graph/biolean/bench/baselines.py tests/test_biolean_bench_baselines.py
git commit -m "feat(biolean-bench): gold, random, modal and template baselines dispatched by track"
```

---
### Task 7: Runner and rescore (`biolean/bench/run.py`)

**Files:**
- Create: `src/methods_graph/biolean/bench/run.py`
- Test: `tests/test_biolean_bench_run.py`

**Interfaces:**
- Produces: `items_manifest(manifest) -> dict` (`{"release", "since"}`), `run_items(items, adapter, store, *, model: str, items_manifest: dict, resolve=None, sink=None) -> list[dict]`, `rescore(rows, store, *, resolve=None) -> list[dict]`, `release_mismatch(items_release: dict | None, store_release: dict) -> list[str]`.
- Consumes: `render.render_prompt`, `score.score_row`, `score.failure_row`, `bench.adapters.AdapterError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_bench_run.py`:

```python
"""Render, call, score, stream; rescore from rows alone; refuse a mismatched release."""
import json

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.baselines import gold_answer, template_answer
from methods_graph.biolean.bench.items import hypothesize_items, population, prove_items
from methods_graph.biolean.bench.run import items_manifest, release_mismatch, rescore, run_items
from methods_graph.biolean.bench.score import COMMON_KEYS, HYPOTHESIZE_KEYS, PROVE_KEYS, summarize
from tests.biolean_fixture import RELEASE, mini_store
from tests.test_biolean_kernel import B, D

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)
MANIFEST = {"release": RELEASE, "since": None}


def _gold_adapter():
    table = {}
    from methods_graph.biolean.bench.render import render_prompt
    for item in PROVE:
        table[render_prompt(item)] = json.dumps(gold_answer(item, STORE))
    for item in HYP:
        table[render_prompt(item)] = json.dumps(template_answer(item))
    return lambda prompt: table[prompt]


def _mixed_adapter():
    gold = _gold_adapter()

    def _adapter(prompt):
        if f"({B})" in prompt:
            raise AdapterError("rate limited")
        if f"({D})" in prompt:
            return "I would rather not."
        return gold(prompt)
    return _adapter


def test_rows_reconcile():
    rows = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST)
    summary = summarize(rows)
    assert summary["n_rows"] == 6
    assert summary["n_rows"] == summary["n_errors"] + summary["n_unparsed"] + summary["n_checked"]
    assert (summary["n_errors"], summary["n_unparsed"], summary["n_checked"]) == (1, 1, 4)
    assert summary["prove"]["n"] == 5                      # the error row is in no denominator
    assert summary["prove"]["hit_rate"] == 4 / 5           # the unparsed row is a miss
    assert summary["release"] == RELEASE and summary["since"] is None


def test_adapter_error_row_is_excluded_and_counted():
    rows = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST)
    failed = next(r for r in rows if r["goal"]["term"] == B)
    assert failed["error"] == "rate limited" and failed["raw"] is None and failed["parsed"] is False
    assert failed["hit"] is None and failed["error_codes"] is None and failed["render_error"] is None
    ok = next(r for r in rows if r["error"] is None and r["parsed"])
    assert set(failed) == set(ok) == COMMON_KEYS | PROVE_KEYS
    assert summarize(rows)["prove"]["error_items"] == {"UNPARSED": 1}      # not the error row


def test_render_failure_fails_its_own_row_and_the_run_continues():
    broken = {k: v for k, v in PROVE[0].items() if k != "symbol"}
    rows = run_items([broken, PROVE[1]], _gold_adapter(), STORE, model="t", items_manifest=MANIFEST)
    assert rows[0]["error"].startswith("render failed") and rows[0]["render_error"].startswith("KeyError")
    assert rows[0]["item"] == broken["id"]
    assert rows[1]["error"] is None and rows[1]["hit"] is True
    assert summarize(rows)["n_render_errors"] == 1


def test_rows_carry_model_and_items_manifest_and_stream_through_the_sink():
    seen = []
    rows = run_items(PROVE[:2], _gold_adapter(), STORE, model="gold:", items_manifest=MANIFEST,
                     sink=seen.append)
    assert seen == rows and [r["item"] for r in rows] == [PROVE[0]["id"], PROVE[1]["id"]]
    assert all(r["model"] == "gold:" and r["items_manifest"] == MANIFEST for r in rows)
    assert items_manifest({"release": RELEASE, "since": "2020-01-01", "seed": 0}) == \
        {"release": RELEASE, "since": "2020-01-01"}


def test_prove_and_hypothesize_rows_share_only_the_common_vocabulary():
    rows = run_items([PROVE[0], HYP[0]], _gold_adapter(), STORE, model="t", items_manifest=MANIFEST)
    hyp, prove = sorted(rows, key=lambda r: r["track"])
    assert set(prove) == COMMON_KEYS | PROVE_KEYS
    assert set(hyp) == COMMON_KEYS | HYPOTHESIZE_KEYS
    assert set(prove) & set(hyp) == COMMON_KEYS
    assert "hit" not in hyp and hyp["format_ok"] is True
    summary = summarize(rows)
    assert summary["prove"]["n"] == 1 and summary["hypothesize"]["n"] == 1
    assert not {"hit", "hit_rate", "accepted"} & set(summary["hypothesize"])


def test_rescore_reproduces_scores_from_the_row_alone():
    resolve = lambda name: name if name == "m:deseq2" else None
    rows = run_items(PROVE + HYP, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST,
                     resolve=resolve)
    kept = ("item", "track", "goal", "hidden", "hidden_classes", "gold_depth", "raw", "model",
            "items_manifest", "error", "render_error")
    stripped = [{k: v for k, v in r.items() if k in kept} for r in rows]
    again = rescore(stripped, STORE, resolve=resolve)
    for before, after in zip(rows, again):
        if before["error"] is not None:
            assert after == {k: v for k, v in before.items() if k in kept}     # untouched
        else:
            assert after == before
    assert summarize(again)["prove"]["hit_rate"] == summarize(rows)["prove"]["hit_rate"] == 4 / 5


def test_release_mismatch_names_each_differing_key():
    assert release_mismatch(RELEASE, RELEASE) == []
    changed = {**RELEASE, "go_basic_data_version": "releases/2027-01-01"}
    lines = release_mismatch(RELEASE, changed)
    assert len(lines) == 1 and lines[0].startswith("go_basic_data_version:")
    assert "releases/2026-01-01" in lines[0] and "releases/2027-01-01" in lines[0]
    assert len(release_mismatch(None, RELEASE)) == 3
    assert len(release_mismatch({}, RELEASE)) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_run.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.bench.run'`.

- [ ] **Step 3: Write the module**

`src/methods_graph/biolean/bench/run.py`:

```python
"""Render, call, score, retain — one row per item, streamed — and rescore from rows alone.

Same guarantees as ``bench/run.py``: an adapter failure is recorded against its item and the
run continues; a render failure fails only its own row; ``sink`` receives each row as it is
produced so an interrupted paid run keeps what it paid for; ``rescore`` re-derives every score
from the retained ``raw`` plus the row's own ``goal``/``hidden``, never from the item files.
"""
from __future__ import annotations

from typing import Any, Callable

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.render import render_prompt
from methods_graph.biolean.bench.score import Resolver, failure_row, score_row
from methods_graph.biolean.store import FactStore


def items_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """What every row carries from the items' manifest: enough to refuse a mismatched store
    and to echo the live cut with every score."""
    return {"release": manifest.get("release"), "since": manifest.get("since")}


def run_items(
    items: list[dict[str, Any]], adapter: Callable[[str], str], store: FactStore, *,
    model: str, items_manifest: dict[str, Any], resolve: Resolver | None = None,
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            prompt = render_prompt(item)
        except (KeyError, TypeError, ValueError) as exc:
            row = failure_row(item, error=f"render failed: {exc}",
                              render_error=f"{type(exc).__name__}: {exc}")
        else:
            try:
                raw = adapter(prompt)
            except AdapterError as exc:
                row = failure_row(item, error=str(exc), render_error=None)
            else:
                row = score_row(item, raw, store, resolve=resolve)
        row = {**row, "model": model, "items_manifest": items_manifest}
        rows.append(row)
        if sink is not None:
            sink(row)
    return rows


def rescore(
    rows: list[dict[str, Any]], store: FactStore, *, resolve: Resolver | None = None,
) -> list[dict[str, Any]]:
    """Re-derive every score from the retained raw output, leaving failure rows untouched.
    Keyed on ``error``, not on ``raw is None``: a null ``raw`` can be a genuine model answer."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("error") is not None:
            out.append(dict(row))
            continue
        item = {"id": row["item"], "track": row["track"], "goal": row["goal"], "hidden": row["hidden"],
                "hidden_classes": row.get("hidden_classes") or [], "gold_depth": row.get("gold_depth")}
        out.append({**score_row(item, row["raw"], store, resolve=resolve),
                    "model": row.get("model"), "items_manifest": row.get("items_manifest")})
    return out


def release_mismatch(items_release: dict[str, Any] | None, store_release: dict[str, Any]) -> list[str]:
    """One line per key whose value differs between the items' recorded release and the
    store's, sorted by key; empty when they agree. A missing record differs on every key."""
    recorded = items_release or {}
    out: list[str] = []
    for key in sorted(set(recorded) | set(store_release)):
        if recorded.get(key) != store_release.get(key):
            out.append(f"{key}: items {recorded.get(key)!r} vs store {store_release.get(key)!r}")
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PYTEST tests/test_biolean_bench_run.py -q`
Expected: 7 passed.

Mutation checks: (a) in `run_items`, replace the `AdapterError` branch with `row = score_row(item, "", ...)` — `test_rows_reconcile` fails (`n_errors 0`); (b) move `render_prompt` outside the `try` — `..._render_failure...` raises instead of recording; (c) in `rescore`, skip rows whose `raw is None`... not observable here, so instead drop `"model"` from the rescored row — `..._from_the_row_alone` fails; (d) in `release_mismatch`, compare only keys present in `recorded` — `release_mismatch({}, RELEASE)` returns `[]` and the test fails.

- [ ] **Step 5: Commit**

```
git add src/methods_graph/biolean/bench/run.py tests/test_biolean_bench_run.py
git commit -m "feat(biolean-bench): runner with streamed rows, rescore from rows alone, release check"
```

---
### Task 8: CLI — `mg biolean bench build|coverage|run|score`

**Files:**
- Modify: `src/methods_graph/cli.py` (imports; after `_prove_reason`; inside `cmd_biolean`; the `biolean` subparser)
- Test: `tests/test_biolean_bench_cli.py`

**Interfaces:**
- Produces: `_biolean_gaf_name(store_dir) -> str`, `_biolean_resolver(db, oracle_json) -> Resolver | None`, `_cmd_biolean_bench(args, parser) -> int`; `_biolean_store` now uses `_biolean_gaf_name`.
- Exit codes: 0 when the subcommand completed; 2 via `parser.error` for a missing store, an unreadable/empty item set, a malformed `--since`, a wrong-track or unknown baseline, a mismatched release, or an unreadable results file.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_bench_cli.py`:

```python
"""One test per subcommand over the fixture store: exit code, sorted JSON, refusals."""
import json

import pytest

from methods_graph import cli
from tests.biolean_fixture import RELEASE, copy_store


@pytest.fixture
def store_dir(tmp_path):
    return copy_store(tmp_path / "store")


@pytest.fixture
def bench_dir(tmp_path, store_dir, capsys):
    out = tmp_path / "bench"
    rc = cli.main(["biolean", "bench", "build", "--out", str(out), "--store", str(store_dir)])
    assert rc == 0
    capsys.readouterr()
    return out


def _sorted_json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_build_writes_the_item_set_and_prints_the_manifest(tmp_path, store_dir, capsys):
    out = tmp_path / "b"
    rc = cli.main(["biolean", "bench", "build", "--out", str(out), "--store", str(store_dir),
                   "--per-track", "3", "--seed", "7"])
    captured = capsys.readouterr()
    assert rc == 0
    manifest = _sorted_json(captured.out)
    assert manifest == json.loads((out / "manifest.json").read_text())
    assert manifest["release"] == RELEASE and manifest["seed"] == 7 and manifest["per_track"] == 3
    assert manifest["prove"]["sampled"] == 3 and manifest["hypothesize"]["sampled"] == 3
    assert (out / "modal.json").exists() and (out / "items" / "prove.json").exists()
    assert json.loads(captured.err)["load_report"]["gaf"]["annotations"] == 24


def test_since_must_be_a_date_and_is_recorded(tmp_path, store_dir, capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "build", "--out", str(tmp_path / "x"), "--store", str(store_dir),
                  "--since", "2020"])
    assert ex.value.code == 2 and "--since" in capsys.readouterr().err
    rc = cli.main(["biolean", "bench", "build", "--out", str(tmp_path / "y"), "--store", str(store_dir),
                   "--since", "2020-01-01"])
    manifest = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and manifest["since"] == "2020-01-01"
    assert manifest["prove"]["excluded_by_since"] == 1 and manifest["hypothesize"]["excluded_by_since"] == 1


def test_coverage_prints_the_manifest_and_a_missing_item_set_exits_2(tmp_path, bench_dir, capsys):
    rc = cli.main(["biolean", "bench", "coverage", "--items", str(bench_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and out["population"]["triples"] == 13 and out["prove"]["not_rederivable"] == 7
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "coverage", "--items", str(tmp_path / "nope")])
    assert ex.value.code == 2


def test_run_gold_hits_every_prove_item_and_writes_one_row_per_item(tmp_path, store_dir, bench_dir, capsys):
    results = tmp_path / "r.jsonl"
    rc = cli.main(["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
                   "--store", str(store_dir), "--out", str(results), "--db", str(tmp_path / "no.kuzu")])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["prove"]["hit_rate"] == 1.0 and summary["prove"]["n"] == 6
    assert summary["release"] == RELEASE
    rows = _rows(results)
    assert len(rows) == 6 and all(r["model"] == "gold:" and r["hit"] for r in rows)
    for line in results.read_text().splitlines():
        assert line == json.dumps(json.loads(line), sort_keys=True)
    rc = cli.main(["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
                   "--store", str(store_dir), "--out", str(results), "--limit", "2", "--db", str(tmp_path / "no.kuzu")])
    assert rc == 0 and len(_rows(results)) == 2


def test_run_template_saturates_hypothesize_and_method_resolves_needs_a_graph(tmp_path, store_dir, bench_dir, capsys):
    results = tmp_path / "h.jsonl"
    base = ["biolean", "bench", "run", "--model", "template:", "--track", "hypothesize", "--items", str(bench_dir),
            "--store", str(store_dir), "--out", str(results)]
    rc = cli.main(base + ["--db", str(tmp_path / "no.kuzu")])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["hypothesize"]["n"] == 13
    assert summary["hypothesize"]["format_ok"] == {"n": 13, "rate": 1.0}
    assert summary["hypothesize"]["method_resolves"] == {"n": 0, "rate": None}     # no graph: undefined
    assert summary["hypothesize"]["n_method_resolves_none"] == 13
    assert not {"hit", "hit_rate", "accepted"} & set(summary["hypothesize"])
    oracle = tmp_path / "oracle.json"
    oracle.write_text(json.dumps({"methods": ["m:deseq2"]}))
    rc = cli.main(base + ["--db", str(tmp_path / "no.kuzu"), "--oracle-json", str(oracle)])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["hypothesize"]["method_resolves"] == {"n": 13, "rate": 1.0}


def test_random_and_modal_baselines_run_end_to_end(tmp_path, store_dir, bench_dir, capsys):
    for spec, expect in (("random:0", None), ("modal:", {"AXIOM_NOT_FOUND": 6})):
        rc = cli.main(["biolean", "bench", "run", "--model", spec, "--track", "prove", "--items", str(bench_dir),
                       "--store", str(store_dir), "--out", str(tmp_path / "x.jsonl"), "--db", str(tmp_path / "no")])
        summary = _sorted_json(capsys.readouterr().out)
        assert rc == 0 and summary["prove"]["n"] == 6
        if expect is None:
            assert set(summary["prove"]["error_items"]) <= {"ROOT_MISMATCH"}
        else:
            assert summary["prove"]["error_items"] == expect and summary["prove"]["hit_rate"] == 0.0


def test_run_baseline_on_the_wrong_track_exits_2(tmp_path, store_dir, bench_dir, capsys):
    for extra in (["--model", "gold:"], ["--model", "template:", "--track", "prove"],
                  ["--model", "random:x", "--track", "prove"], ["--model", "nope:1", "--track", "prove"]):
        with pytest.raises(SystemExit) as ex:
            cli.main(["biolean", "bench", "run", *extra, "--items", str(bench_dir), "--store", str(store_dir),
                      "--out", str(tmp_path / "x.jsonl"), "--db", str(tmp_path / "no")])
        assert ex.value.code == 2, extra
        capsys.readouterr()


def test_run_and_score_refuse_a_mismatched_store_release(tmp_path, store_dir, bench_dir, capsys):
    other = copy_store(tmp_path / "other")
    obo = other / "go-basic.obo"
    obo.write_text(obo.read_text().replace("releases/2026-01-01", "releases/2026-02-02"))
    results = tmp_path / "r.jsonl"
    run = ["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
           "--out", str(results), "--db", str(tmp_path / "no")]
    with pytest.raises(SystemExit) as ex:
        cli.main(run + ["--store", str(other)])
    assert ex.value.code == 2 and "release" in capsys.readouterr().err
    assert cli.main(run + ["--store", str(store_dir)]) == 0
    capsys.readouterr()
    score = ["biolean", "bench", "score", "--results", str(results), "--db", str(tmp_path / "no")]
    with pytest.raises(SystemExit) as ex:
        cli.main(score + ["--store", str(other)])
    assert ex.value.code == 2 and "release" in capsys.readouterr().err
    rescored = tmp_path / "rescored.jsonl"
    assert cli.main(score + ["--store", str(store_dir), "--out", str(rescored)]) == 0
    summary = _sorted_json(capsys.readouterr().out)
    assert summary["prove"]["hit_rate"] == 1.0 and summary["since"] is None
    assert rescored.read_text() == results.read_text()


def test_score_refuses_an_unreadable_results_file(tmp_path, store_dir, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(bad), "--store", str(store_dir),
                  "--db", str(tmp_path / "no")])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(tmp_path / "missing.jsonl"),
                  "--store", str(store_dir), "--db", str(tmp_path / "no")])
    assert ex.value.code == 2


def test_missing_store_exits_2_for_every_store_taking_subcommand(tmp_path, bench_dir):
    missing = str(tmp_path / "nostore")
    for argv in (["build", "--out", str(tmp_path / "b")],
                 ["run", "--model", "gold:", "--items", str(bench_dir), "--out", str(tmp_path / "r")],
                 ["score", "--results", str(tmp_path / "r")]):
        with pytest.raises(SystemExit) as ex:
            cli.main(["biolean", "bench", *argv, "--store", missing])
        assert ex.value.code == 2, argv
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PYTEST tests/test_biolean_bench_cli.py -q`
Expected: FAIL — argparse rejects `bench` under `biolean` with exit 2 in the `bench_dir` fixture (`invalid choice: 'bench'`).

- [ ] **Step 3: Add the helpers and dispatcher to `cli.py`**

Add `import re` to the imports at the top of `cli.py` (after `import logging`).

Replace `_biolean_store`'s first two body lines so it uses the shared name helper, and add the new helpers after `_prove_reason`:

```python
_SINCE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _biolean_gaf_name(store_dir: Path) -> str:
    return "goa_human.gaf.gz" if (store_dir / "goa_human.gaf.gz").exists() else "goa_human.gaf"


def _biolean_store(store_dir: Path, parser: argparse.ArgumentParser):
    """Load the Biolean store or exit 2 naming what is missing."""
    from methods_graph.biolean.store import load_store

    gaf = _biolean_gaf_name(store_dir)
    missing = [name for name in (*_BIOLEAN_FILES, gaf) if not (store_dir / name).exists()]
    if missing:
        parser.error(f"biolean: --store {store_dir} lacks {', '.join(missing)}; "
                     f"run `mg biolean fetch --out {store_dir}`")
    return load_store(store_dir, gaf=gaf)
```

(`_biolean_store` keeps its position; only its body changes. `_BIOLEAN_FILES` stays.)

```python
def _biolean_resolver(db: Path, oracle_json: Path | None):
    """`m:` resolution for hypothesize `method_resolves`, or None when no graph is available —
    the field is then undefined (None), never False."""
    if oracle_json is None and not db.exists():
        return None
    from methods_graph.bench.normalize import normalize_name
    from methods_graph.bench.oracle import load_oracle

    oracle = load_oracle(db_path=db if db.exists() else None, json_path=oracle_json)
    return lambda name: normalize_name(name, oracle)


def _cmd_biolean_bench(args, parser: argparse.ArgumentParser) -> int:
    """`mg biolean bench build|coverage|run|score`. Exit 0 when complete, 2 for usage."""
    from methods_graph.biolean.bench.items import build_items, load_items, read_release
    from methods_graph.biolean.bench.run import items_manifest, release_mismatch, rescore, run_items
    from methods_graph.biolean.bench.score import summarize

    if args.bench_cmd == "coverage":
        try:
            _items, manifest = load_items(args.items)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"biolean bench: {exc}")
        print(json.dumps(manifest, sort_keys=True, indent=2))
        return 0

    store, report = _biolean_store(args.store, parser)
    print(json.dumps({"load_report": report}, sort_keys=True), file=sys.stderr)
    release = read_release(args.store, gaf=_biolean_gaf_name(args.store))

    if args.bench_cmd == "build":
        if args.since is not None and not _SINCE_RE.match(args.since):
            parser.error(f"biolean bench: --since must be YYYY-MM-DD, got {args.since!r}")
        manifest = build_items(store, args.out, release=release, per_track=args.per_track,
                               seed=args.seed, since=args.since)
        print(json.dumps(manifest, sort_keys=True, indent=2))
        return 0

    resolve = _biolean_resolver(args.db, args.oracle_json)

    if args.bench_cmd == "run":
        from methods_graph.bench.adapters import AdapterError, get_adapter
        from methods_graph.biolean.bench.baselines import baseline_adapter, is_baseline_spec

        try:
            items, manifest = load_items(args.items)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"biolean bench: {exc}")
        mismatch = release_mismatch(manifest.get("release"), release)
        if mismatch:
            parser.error("biolean bench: --store release differs from the items': " + "; ".join(mismatch))
        if args.track:
            items = [item for item in items if item["track"] == args.track]
        if args.limit is not None:
            items = items[:args.limit]
        try:
            adapter = (baseline_adapter(args.model, items, store, modal_path=args.items / "modal.json")
                       if is_baseline_spec(args.model) else get_adapter(args.model))
        except AdapterError as exc:
            parser.error(f"biolean bench: {exc}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Streamed and flushed per row: an interrupted paid run keeps every answer obtained.
        with args.out.open("w") as handle:
            def _write(row):
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()

            rows = run_items(items, adapter, store, model=args.model,
                             items_manifest=items_manifest(manifest), resolve=resolve, sink=_write)
        print(json.dumps(summarize(rows), sort_keys=True, indent=2))
        return 0

    if args.bench_cmd == "score":
        try:
            rows = [json.loads(line) for line in args.results.read_text().splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"biolean bench: cannot read results {args.results}: {exc}")
        recorded = {json.dumps((row.get("items_manifest") or {}).get("release"), sort_keys=True)
                    for row in rows}
        for blob in sorted(recorded):
            mismatch = release_mismatch(json.loads(blob), release)
            if mismatch:
                parser.error("biolean bench: --store release differs from the results': " + "; ".join(mismatch))
        rescored = rescore(rows, store, resolve=resolve)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rescored))
        print(json.dumps(summarize(rescored), sort_keys=True, indent=2))
        return 0

    raise ValueError(f"unknown biolean bench subcommand: {args.bench_cmd!r}")
```

In `cmd_biolean`, insert right after the `fetch` branch returns (before the `from methods_graph.biolean.elaborate import ...` line):

```python
    if args.biolean_cmd == "bench":
        return _cmd_biolean_bench(args, parser)
```

In the parser, after the `bl_goals.add_argument("--aspect", ...)` line:

```python
    bl_bench = bl_sub.add_parser("bench", help="two-track re-derivation benchmark (spec §6)")
    bl_bench_sub = bl_bench.add_subparsers(dest="bench_cmd", required=True)
    bb_build = bl_bench_sub.add_parser("build", help="store -> frozen items, manifest.json, modal.json")
    bb_build.add_argument("--out", type=Path, default=Path("biolean-bench"))
    bb_build.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bb_build.add_argument("--per-track", type=int, default=500,
                          help="items sampled per track (every eligible item when larger)")
    bb_build.add_argument("--seed", type=int, default=0)
    bb_build.add_argument("--since", default=None,
                          help="YYYY-MM-DD; keep items whose earliest hidden row is on or after it")
    bb_cov = bl_bench_sub.add_parser("coverage", help="print the build manifest: denominators and drop reasons")
    bb_cov.add_argument("--items", type=Path, default=Path("biolean-bench"))
    bb_run = bl_bench_sub.add_parser("run", help="run a model or baseline over the items")
    bb_run.add_argument("--model", required=True,
                        help="claude:<model> | openai:<model> | static:<path> | gold: | random:<seed> | modal: | template:")
    bb_run.add_argument("--items", type=Path, default=Path("biolean-bench"))
    bb_run.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bb_run.add_argument("--out", type=Path, required=True)
    bb_run.add_argument("--track", choices=["prove", "hypothesize"], default=None)
    bb_run.add_argument("--limit", type=int, default=None)
    bb_run.add_argument("--db", type=Path, default=Path("data/methods.kuzu"),
                        help="graph for hypothesize method_resolves; without one the field is null")
    bb_run.add_argument("--oracle-json", type=Path, default=None)
    bb_score = bl_bench_sub.add_parser("score", help="re-derive scores from retained raw output")
    bb_score.add_argument("--results", type=Path, required=True)
    bb_score.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bb_score.add_argument("--out", type=Path, default=None)
    bb_score.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))
    bb_score.add_argument("--oracle-json", type=Path, default=None)
```

- [ ] **Step 4: Run the CLI tests, then the whole suite**

Run: `$PYTEST tests/test_biolean_bench_cli.py tests/test_biolean_cli.py -q`
Expected: all pass (the existing `biolean` CLI tests are unchanged by the refactor of `_biolean_store`).

Run: `env -u OPENAI_API_KEY $PYTEST -q`
Expected: everything passes; in a worktree without `data/methods.kuzu` the DB-gated tests skip.

Mutation checks: (a) map REJECTED baselines' `AdapterError` to `return 1` instead of `parser.error` — `..._wrong_track_exits_2` fails; (b) skip the `release_mismatch` call in `run` — `..._mismatched_store_release` fails at the first `SystemExit`; (c) skip it in `score` — fails at the second; (d) drop the `_SINCE_RE` check — `..._since_must_be_a_date` fails; (e) in `_biolean_resolver`, return a resolver that maps every name to itself when no graph exists — `..._method_resolves_needs_a_graph` fails (`rate 1.0` without a graph).

- [ ] **Step 5: Commit**

```
git add src/methods_graph/cli.py tests/test_biolean_bench_cli.py
git commit -m "feat(cli): mg biolean bench build|coverage|run|score with release and track refusals"
```

---
### Task 9: Scale check on the real snapshot, docs

**Files:**
- Create: `tests/test_biolean_bench_scale.py`
- Modify: `CLAUDE.md` (run lines, layout row, test count), `README.md` (Biolean section)

**Interfaces:** none new. The scale test is snapshot-gated (skips without `snapshots/go/`), so it is **not** a CI gate; say so in its docstring and in the commit body.

- [ ] **Step 1: Write the scale test**

`tests/test_biolean_bench_scale.py`:

```python
"""Runs only when snapshots/go holds the real files. Not a CI gate.

Builds over a 300-subject slice (the same slice tests/test_biolean_scale.py uses) so the
whole check stays under two minutes, then pins the three properties a wrong build would
break: every counter reconciles, gold hits every prove item, template saturates hypothesize.
"""
import random
import time
from pathlib import Path

import pytest

from methods_graph.biolean.bench.baselines import baseline_adapter
from methods_graph.biolean.bench.items import build_items, load_items, read_release
from methods_graph.biolean.bench.run import items_manifest, run_items
from methods_graph.biolean.bench.score import DEPTH_BUCKETS, summarize
from methods_graph.biolean.store import load_store

SNAP = Path("snapshots/go")
pytestmark = pytest.mark.skipif(
    not all((SNAP / f).exists() for f in ("go-basic.obo", "goa_human.gaf.gz", "gaf-eco-mapping.txt")),
    reason="real GO/GOA snapshot not present")


def test_real_snapshot_build_reconciles_and_every_baseline_behaves(tmp_path):
    store, _ = load_store(SNAP)
    rng = random.Random(0)
    subjects = sorted({a.subject for s in rng.sample(range(1, 40_000), 2_000)
                       for a in store.annotations(f"UniProtKB:P{s:05d}")})[:300]
    t0 = time.monotonic()
    manifest = build_items(store, tmp_path, release=read_release(SNAP), per_track=100, seed=0,
                           subjects=subjects)
    assert time.monotonic() - t0 < 120, manifest["population"]

    pop = manifest["population"]
    assert pop["n_subjects"] == len(subjects)
    assert pop["rows"] == pop["eligible_rows"] + sum(pop["dropped"].values())
    assert pop["dropped"]["negated"] > 0 and pop["dropped"]["evidence_class"] > 0
    assert manifest["prove"]["eligible"] + manifest["prove"]["not_rederivable"] == pop["triples"]
    assert manifest["hypothesize"]["eligible"] + manifest["hypothesize"]["goal_not_statable_total"] == pop["triples"]
    assert manifest["prove"]["sampled"] == 100 and manifest["hypothesize"]["sampled"] == 100
    assert manifest["release"]["go_basic_data_version"].startswith("releases/")
    assert manifest["release"]["goa_go_version"]           # the real GAF names its GO release

    items, _ = load_items(tmp_path)
    prove = [i for i in items if i["track"] == "prove"]
    hyp = [i for i in items if i["track"] == "hypothesize"]
    im = items_manifest(manifest)

    gold = summarize(run_items(prove, baseline_adapter("gold:", prove, store), store,
                               model="gold:", items_manifest=im))
    assert gold["n_errors"] == 0 and gold["n_unparsed"] == 0
    assert gold["prove"]["hit_rate"] == 1.0
    assert tuple(gold["prove"]["by_gold_depth"]) == DEPTH_BUCKETS
    assert sum(b["n"] for b in gold["prove"]["by_gold_depth"].values()) == 100

    modal = summarize(run_items(prove, baseline_adapter("modal:", prove, store, modal_path=tmp_path / "modal.json"),
                                store, model="modal:", items_manifest=im))
    # Every modal reply is structurally valid at a visible or hidden axiom, so it is accepted
    # exactly when it hits; the only other outcome is AXIOM_NOT_FOUND.
    assert modal["prove"]["acceptance_rate"] == modal["prove"]["hit_rate"]
    assert set(modal["prove"]["error_items"]) <= {"AXIOM_NOT_FOUND"}

    randoms = summarize(run_items(prove, baseline_adapter("random:0", prove, store), store,
                                  model="random:0", items_manifest=im))
    assert set(randoms["prove"]["error_items"]) <= {"ROOT_MISMATCH"}

    template = summarize(run_items(hyp, baseline_adapter("template:", hyp, store), store,
                                   model="template:", items_manifest=im))
    assert template["hypothesize"]["format_ok"] == {"n": 100, "rate": 1.0}
    assert template["hypothesize"]["method_resolves"] == {"n": 0, "rate": None}
```

- [ ] **Step 2: Run it against the real snapshot (main checkout only; skips elsewhere)**

Run: `$PYTEST tests/test_biolean_bench_scale.py -q -rs`
Expected: `1 passed` when `snapshots/go/` is present (record the measured build time and the four rates in the commit body), `1 skipped` otherwise. If the build exceeds 120 s, do not loosen the bound — profile `hide_subtree`/`fit_modal` for a missing descendant cache first.

- [ ] **Step 3: Update `CLAUDE.md`**

In "Run things this way", replace the suite line's comment with the measured count and time (the count is the number pytest printed in Task 8's full run; it will be about 990), and add two lines to the Biolean block:

```bash
.venv/bin/python -m methods_graph.cli biolean bench build --out biolean-bench   # frozen items + manifest.json + modal.json
.venv/bin/python -m methods_graph.cli biolean bench run --model gold: --track prove --out gold.jsonl   # ceiling, must be 1.0
```

In the Layout table, replace the Biolean row with:

| `src/methods_graph/biolean/` | Biolean: a structural proof checker for GO claims (`kernel.py` is the only trusted file); `bench/` is its two-track benchmark; `mg biolean fetch|check|prove|goals|bench` |

Add to "Testing standards" after the DB-gated bullet:

- **Snapshot-gated tests** (`tests/test_biolean_scale.py`, `tests/test_biolean_bench_scale.py`) skip when `snapshots/go/` is absent, which it is in CI. Same rule: not enforced by CI.

- [ ] **Step 4: Update `README.md`**

Replace the `## Biolean` paragraph with:

```markdown
## Biolean

A proof assistant for biological claims. An agent emits a derivation of a GO claim (axiom,
`is_a`, `part_of`, `sorry`); `mg biolean check` accepts or rejects it against GO and human GOA
with typed errors and suggestions. `mg biolean prove` is the mechanical prover, `mg biolean
goals` lists what is derivable for a gene product. Design: `docs/superpowers/specs/2026-09-21-biolean-design.md`.

Its benchmark has two tracks. **prove** hides every row of one annotation and asks for a
closed-book re-derivation from a more specific term; a hit is an ACCEPTED derivation of the
item's claim with no `sorry`. **hypothesize** hides the whole subtree so nothing can be
derived, and measures format compliance only (a `sorry` root with provenance) until Phase B
can discharge the computation. Every rate ships with its denominator; the `modal:` baseline
(most common descendant for the goal term, gene-blind) is the number to beat, `gold:` must
score 1.0, and `template:` saturates the hypothesize track by construction.

```bash
mg biolean fetch --out snapshots/go                                  # GAF, the GO release it names, ECO
mg biolean bench build --out biolean-bench [--since 2026-01-01]       # frozen items, manifest, modal prior
mg biolean bench coverage --items biolean-bench                       # denominators; read before any score
mg biolean bench run --model gold: --track prove --out gold.jsonl     # then modal:, random:<seed>, claude:...
mg biolean bench run --model template: --track hypothesize --out t.jsonl
mg biolean bench score --results gold.jsonl                           # re-derive from retained raw output
```

`run` and `score` refuse a store whose GO/GOA release differs from the one the items were
built from. No items ship in the repo; `snapshots/go/` is gitignored.
```

- [ ] **Step 5: Run the full suite one last time and commit**

Run: `env -u OPENAI_API_KEY $PYTEST -q`
Expected: all pass (DB-gated and snapshot-gated tests skip where their data is absent).

```
git add tests/test_biolean_bench_scale.py CLAUDE.md README.md
git commit -m "test(biolean-bench): snapshot-gated scale check; docs for mg biolean bench"
```

---

## Spec coverage (self-review)

| Spec §6 requirement | Where |
|---|---|
| Population: five filters in order, first failure counted, term validity split three ways, only the hidden fact must be eligible | Task 3 `population`, `_drop_reason`; tests `..._first_failure_in_order`, `..._excludes_obsolete_terms` |
| Triples sorted by `(subject, qualifier, term)`, `Random(seed).sample` | Task 4 `sample`; test `..._seeded_and_sorted_first` |
| `coverage` prints eligible/sampled per track and every drop reason | Task 4 manifest; Task 8 `coverage` |
| `hide_exact`, `hide_subtree` (closure of the union, NOT never hidden) | Task 3; tests `..._only_the_exact_rows`, `..._closure_of_the_union`, `..._never_hides_not_rows` |
| Item records `hidden`, `hidden_dates`, `cut_date = min`, `hidden_classes`; scoring over `MaskedFactStore` | Task 4 `_item`; Task 5 `_checked` |
| Prove: rederivable check, `not_rederivable` counted, gold and `gold_depth` | Task 4 `prove_items` |
| Prove prompt (+ format block, deviation 2) | Task 2 |
| Row vocabulary from `bench/run.py`: `raw`, `error`, `render_error`, `parsed`; error rows excluded; unparsed rows are misses with `UNPARSED`; reconciliation identity | Tasks 5, 7; tests `test_rows_reconcile`, `..._unparsed_code`, `..._excluded_and_counted` |
| Scorer never trusts the reply's goal; `goal_match`, `goal_rewritten`, `hit`, `hit_with_sorry`, `depth`, `error_codes` | Task 5 `score_prove`; tests `..._goal_match_and_zero_used_sorries`, `..._is_counted`, `..._propagation_steps` |
| Aggregates: `hit_rate`, `acceptance_rate`, `mean_depth`, by evidence class, by depth bucket with sizes, `error_items` / `error_occurrences` with denominators | Task 5 `_summarize_prove`; tests `..._items_and_occurrences`, `..._every_depth_bucket` |
| Hypothesize: `BuildError` on a still-derivable triple; `goal_not_statable:<CODE>` | Task 4 `hypothesize_items`; tests `..._raises_build_error`, `..._counted_with_its_code` |
| Hypothesize prompt | Task 2 |
| `format_ok`, `goal_match`, `inputs_nonempty`, `method_resolves` via `normalize_name`, `method` verbatim, `method_normalized`, `None` without a graph; aggregates incl. `n_method_resolves_none`, `method_unresolved` | Task 5 `score_hypothesize`; tests `..._none_without_a_graph`, `..._exact_lookup_not_search` |
| `hypothesize_gold: null`; "format compliance only" heading; no `hit`/`hit_rate`/`accepted`; per-item key sets share only the row vocabulary | Task 4 manifest; Task 5 `HYPOTHESIZE_NOTE`; tests `..._carry_no_hit_keys`, `..._share_only_the_common_vocabulary` |
| Live cut: min over every hidden row, `excluded_by_since`, `since` recorded and echoed | Task 4 `apply_since`, `build_items`; Task 5 `summarize`; test `..._min_hidden_date` |
| Baselines dispatched by track; wrong track is a usage error; gold CI gate; random structurally valid; modal fit before sampling/cut, leave-subject-out, tie by term id, empty counter → hidden axiom; template saturates | Task 6; tests `test_gold_hits_every_prove_item`, `..._structurally_valid_and_seeded`, `..._before_sampling`, `..._leaves_the_subject_out...`, `..._one_on_every_hypothesize_rate`, `..._usage_error` |
| `UNKNOWN` does not exist; undefined is `None` | Task 5 `_rate`, `method_resolves`, `goal_match` |
| §7: layout, `bench` CLI rows, exit codes, release refusal | Tasks 1 (spec), 8 |
| §9 benchmark test table | mapped below |
| §9 CLI: one test per subcommand, exit codes, sorted output | Task 8 |
| §9 scale check | Task 9 |

**§9 test-name map** (the spec's row → this plan's test):

| Spec row | Plan test |
|---|---|
| `test_population_filters_count_the_first_failure_in_order` | same name (Task 3) |
| `test_population_excludes_obsolete_terms` | same (Task 3; asserts on `dropped.term_obsolete` and that `goal_not_statable` stays empty, since a dropped filter would surface the triple there, not as eligible) |
| `test_prove_item_hides_only_the_exact_rows` | same (Task 3) |
| `test_not_rederivable_triples_are_counted_not_dropped_silently` | same (Task 4) |
| `test_hypothesize_subtree_is_closure_of_the_union` | same (Task 3) |
| `test_hypothesize_never_hides_not_rows` | same (Task 3) |
| `test_hypothesize_still_derivable_raises_build_error` | same (Task 4) |
| `test_hypothesize_goal_not_statable_is_counted_with_its_code` | same (Task 4) |
| `test_gold_hits_every_prove_item` | same (Task 6) |
| `test_hit_requires_goal_match_and_zero_used_sorries` | same (Task 5) |
| `test_goal_rewritten_is_counted` | same (Task 5) |
| `test_scorer_uses_the_masked_store` | same (Task 5) |
| `test_rows_reconcile` | same (Task 7) |
| `test_unparsed_reply_is_a_miss_with_unparsed_code` | same (Task 5) |
| `test_adapter_error_row_is_excluded_and_counted` | same (Task 7) |
| `test_method_resolves_is_none_without_a_graph` | same (Task 5) |
| `test_method_is_resolved_by_exact_lookup_not_search` | same (Task 5) |
| `test_hypothesize_rows_carry_no_hit_keys` | `test_hypothesize_rows_and_summary_carry_no_hit_keys` (Task 5) + `..._share_only_the_common_vocabulary` (Task 7) |
| `test_template_baseline_scores_one_on_every_hypothesize_rate` | same (Task 6) |
| `test_live_cut_uses_min_hidden_date` | same (Task 4) |
| `test_sampling_is_seeded_and_sorted_first` | same (Task 4) |
| `test_modal_is_fit_before_sampling_and_leaves_the_subject_out` | split: `test_modal_is_fit_on_the_full_eligible_set_before_sampling` (Task 4) + `test_modal_leaves_the_subject_out_and_breaks_ties_by_sorted_term_id` (Task 6) |
| `test_random_baseline_is_structurally_valid` | `test_random_baseline_is_structurally_valid_and_seeded` (Task 6) |
| `test_error_histograms_count_items_and_occurrences` | same (Task 5) |
| `test_run_and_score_refuse_a_mismatched_store_release` | same (Task 8) |
| `test_rescore_reproduces_scores_from_the_row_alone` | same (Task 7) |

## Execution notes

- Work in a worktree branched from `main` at `7bc79ef` (`feat/biolean-bench`), with `$PYTEST` as defined in Global Constraints. The snapshot-gated tests will skip there (no `snapshots/go/` in the worktree); run Task 9's scale test from the main checkout after merging, or symlink `snapshots/go` into the worktree read-only.
- Tasks are sequential: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Task 6 depends on 4 and 5; Task 7 on 5 and 6; Task 8 on all.
- After Task 9, run a whole-branch review against this plan and spec §6 before offering the finishing menu. Nothing lands on `main` without the owner.
