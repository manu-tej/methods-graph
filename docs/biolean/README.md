# Biolean guide

**What this is:** Biolean as built: the trust model, the facts, the four proof rules, every error code, the derivation format, the elaborator and tactics, and `mg biolean fetch|check|prove|goals`. The benchmark (`mg biolean bench`) has [its own doc](benchmark.md).
**Status, 2026-09-22:** Plan 1 (kernel and CLI) merged at `7bc79ef`. Plan 2 (benchmark) merged at `b0f80c4`. None of it is pushed: local `main` is 56 commits ahead of `origin/main` (`86ce425`), so GitHub CI has never run it. One kernel rule is an **open decision**: whether a step may skip intermediate terms ([memo](../decisions/2026-09-22-biolean-transitive-edges.md)).
**Read next:** [benchmark.md](benchmark.md), then [results-2026-09-22-opus-5.md](results-2026-09-22-opus-5.md). Terms are defined in [GLOSSARY.md](../GLOSSARY.md). The index of all docs is [docs/README.md](../README.md).
**Ledger:** [ledger.md](ledger.md) (signed, hash-chained facts that extend the base; `mg biolean ledger`).

Source code: `src/methods_graph/biolean/`, 11 modules and 1,445 lines excluding `bench/` (`wc -l src/methods_graph/biolean/*.py`). Spec: [2026-09-21-biolean-design.md](../superpowers/specs/2026-09-21-biolean-design.md). Plans: [Plan 1](../superpowers/plans/2026-09-21-biolean-plan-1-kernel.md), [Plan 2](../superpowers/plans/2026-09-22-biolean-plan-2-benchmark.md). All `file:line` citations are at `6b28222`. Spec line numbers are for the spec as committed there; the uncommitted status banner added to the spec on 2026-09-22 shifts them down.

## Contents

1. [What Biolean is](#1-what-biolean-is)
2. [Before you run anything](#2-before-you-run-anything)
3. [Trust model](#3-trust-model)
4. [Facts: propositions and the store](#4-facts-propositions-and-the-store)
5. [Proof rules](#5-proof-rules)
6. [Error codes](#6-error-codes)
7. [The verdict](#7-the-verdict)
8. [Derivation format, with real examples](#8-derivation-format-with-real-examples)
9. [Elaborator](#9-elaborator)
10. [Tactics](#10-tactics)
11. [CLI](#11-cli)
12. [Tests](#12-tests)
13. [As-built deviations from the spec](#13-as-built-deviations-from-the-spec)
14. [Owner-fixed decisions (spec §0)](#14-owner-fixed-decisions-spec-0)
15. [Not built, and open questions](#15-not-built-and-open-questions)

## 1. What Biolean is

Biolean checks proofs of Gene Ontology (GO) claims. A claim is a proposition such as "TP53 (`UniProtKB:P04637`) `involved_in` cell cycle (`GO:0007049`), human". An agent, in practice an LLM, submits a JSON *derivation*. Its steps are axioms that cite recorded human GOA annotations, and `is_a`/`part_of` steps that lift a claim along a GO edge. `kernel.check()` returns `ACCEPTED` or `REJECTED`, with typed errors a model can act on. The guarantee is structural only: every step traces to a recorded fact through a declared rule, with the rule's side conditions met. It says nothing about whether the biology is true (owner decision, spec §0.2). Why Biolean exists, per the owner's project notes (the repo holds no evaluation data for this): a corpus evaluation measured the guardrail's recall at 0%, which showed that advice-style gates fail. A checker the agent must satisfy is the alternative. The full backstory is in [HISTORY.md](../HISTORY.md).

## 2. Before you run anything

```bash
alias mg='.venv/bin/python -m methods_graph.cli'   # or .venv/bin/methods-graph (the installed console script)
```

- On macOS, a bare `mg` resolves to `/usr/bin/mg`, an unrelated text editor. In this doc, `mg` always means the alias above.
- Run every command from the repo root. The default `--store snapshots/go` is a relative path.
- `check`, `prove` and `goals` need `snapshots/go/` (gitignored, 45 MB by `du -sh`) holding `go-basic.obo`, `goa_human.gaf.gz` and `gaf-eco-mapping.txt`, or another directory given with `--store DIR`. They need no network, no `data/methods.kuzu` and no paid calls.
- Every call re-parses all three files. That takes about 12–16 s per call on this machine (measured 2026-09-22), and there is no cache. The load report goes to stderr as one JSON line.
- `fetch` needs the network. Read the `fetch` part of [§11](#11-cli) before running it: fetching into `snapshots/go` overwrites the pair that the frozen benchmark items were built on.

## 3. Trust model

**Fact:** `kernel.py` is the only file meant to be trusted (spec §3; `kernel.py:1-6`), for checking derivations; the ledger adds `ed25519.py`, `sshsig.py` and `ledger/` to the trusted set, because they decide what enters the store ([ledger.md](ledger.md) §6). The kernel does no I/O. Every other module either supplies facts to it or has its output re-checked by it.

| Module | Role | Trusted? |
|---|---|---|
| `kernel.py` (518 lines) | `check()`, the four rules, the closures `propagating_parents`/`ancestors`/`descendants` | yes |
| `errors.py`, `props.py` | error codes and the error record; `Prop`, `Term`, `Edge`, `Annotation`; the qualifier→aspect table; `PROPAGATING_RELATIONS` | imported by the kernel |
| `store.py`, plus `obo.py`, `gaf.py`, `eco.py` | `FactStore` protocol, `StaticFactStore`, `MaskedFactStore`, the loaders | imported by the kernel; the verdict relies on the store's indexes |
| `elaborate.py` | rewrites identifiers before the kernel and reports each rewrite | no, and it runs *before* the kernel on the CLI path |
| `tactics.py` | `goals_for`, `applicable`, `prove` | no; `prove`'s output is re-checked (`test_prove_output_is_accepted_by_the_kernel`, `tests/test_biolean_tactics.py:184`) |
| `render.py` | prose for verdicts and derivations | no; display only |
| `bench/` | benchmark build, prompts, scoring | no; the scorer calls `elaborate` + `check` and never re-implements a rule |
| `ed25519.py` | verify-only Ed25519 (RFC 8032 §5.1.7) | yes |
| `sshsig.py` | the `sshsig` signature blob, `allowed_signers`, key digests | yes |
| `ledger/` | `errors`, `format`, `check`, `integrity`, `load`, `append`: the signed fact ledger ([ledger.md](ledger.md)) | yes: it decides what enters the store |

What "the only trusted file" means in practice:

- **Fact:** the kernel imports three package modules directly: `errors`, `props` and `store.FactStore` (`kernel.py:14-17`). But `store.py` imports `eco`, `gaf` and `obo` at module level (`store.py:12-14`), so importing the kernel loads six other Biolean modules. Check with:
  `.venv/bin/python -c "import sys, methods_graph.biolean.kernel; print(sorted(m for m in sys.modules if m.startswith('methods_graph.biolean')))"`
- **Fact:** soundness also rests on `StaticFactStore` indexing correctly and on the parsers. For example, `matching()` is an exact lookup on a 5-field key (`store.py:91-92`).
- **Fact:** on the CLI path, the verdict is about the *elaborated* derivation. Every rewrite is listed in the verdict's `elaboration`. The one exception is `--taxon` ([§13](#13-as-built-deviations-from-the-spec)).
- **Not enforced:** no test pins the kernel's import set. The only import-closure test in the repo covers `rules.py` (`tests/test_rules.py:124`). Whether to add one is an open question ([BACKLOG.md](../BACKLOG.md)).

## 4. Facts: propositions and the store

### Propositions

`Prop` has five fields and is compared field by field (`props.py:116-138`).

| Field | JSON type | Example | Rule |
|---|---|---|---|
| `subject` | string | `UniProtKB:P04637` | GAF column 1 `:` column 2 |
| `qualifier` | string | `involved_in` | one of the 13 GAF 2.2 qualifiers |
| `term` | string | `GO:0007049` | a primary GO id |
| `taxon` | string | `NCBITaxon:9606` | must match `^NCBITaxon:\d+$` |
| `negated` | boolean | `false` | JSON `true`/`false` only; `0` or `"false"` is `MALFORMED` |

A Prop object with a missing or extra key is `MALFORMED` (`props.py:125-134`). Two propositions that differ only in qualifier are different: `enables` and `contributes_to` at the same term are not interchangeable.

Each qualifier is legal for exactly one aspect (`props.py:14-28`). A qualifier used with a term of another aspect is `QUALIFIER_ASPECT_MISMATCH`.

| Aspect | Namespace | Qualifiers |
|---|---|---|
| F | molecular_function | `enables`, `contributes_to` |
| P | biological_process | `involved_in`, `acts_upstream_of`, `acts_upstream_of_positive_effect`, `acts_upstream_of_negative_effect`, `acts_upstream_of_or_within`, `acts_upstream_of_or_within_positive_effect`, `acts_upstream_of_or_within_negative_effect` |
| C | cellular_component | `located_in`, `part_of`, `is_active_in`, `colocalizes_with` |

Evidence codes are types, never weights (owner decision, spec §0.3). The kernel uses a code only as an optional filter on an axiom step. Evidence classes (`props.py:37-48`) are used only by the benchmark.

### Sources: `snapshots/go/` as on disk, 2026-09-22

| File | Release, from its own header | Parser | Counts (load report) |
|---|---|---|---|
| `go-basic.obo` (32 MB) | `data-version: releases/2026-07-26` | `obo.py` | 48,340 terms, of which 10,248 are obsolete. 71,496 edges: `is_a` 57,456, `part_of` 6,270, `regulates` 2,820, `positively_regulates` 2,475, `negatively_regulates` 2,475. 3,646 alt ids |
| `goa_human.gaf.gz` (15 MB) | `!date-generated: 2026-05-21T08:10`; `!go-version: .../releases/2026-04-27/...` | `gaf.py` | 906,445 rows give 906,422 annotations (23 byte-identical rows collapsed). 1,501 NOT rows, 851 two-taxon rows, 162 rows at obsolete terms. 38,924 subjects: UniProtKB 19,796, RNAcentral 16,854, ComplexPortal 2,274 |
| `gaf-eco-mapping.txt` | none in the file. `fetch` records its sha256 in `snapshot.json` (absent here); the benchmark's release check ignores this file (`bench/items.py:138-154`) | `eco.py` | 26 `Default` rows |

Sources: the stderr `load_report` of any `mg biolean check|prove|goals` call. The per-relation edge, subject, NOT-row and alt-id counts come from a read-only script over `load_store(snapshots/go)` and `parse_go_basic`.

The loaders count everything and drop nothing silently. Every report key is present even when zero.

- `obo.py` reads `[Term]` stanzas only; the 5 `[Typedef]` stanzas are skipped and counted. It dedupes edges and keeps unknown relations, counting them (0 on this file). Obsolete terms keep `replaced_by` and `consider`. None of the 10,248 obsolete terms has an edge.
- `gaf.py` drops a row at the first filter it fails, in this order, and counts it there: column count ≠ 17; unknown qualifier after stripping `NOT|`; taxon cardinality not 1 or 2; bad taxon format; byte-identical duplicate (`gaf.py:45-73`). It keeps, and counts, rows at alt-id terms (rewritten to the primary id, with `term_raw` kept), rows at terms not in the ontology, rows at obsolete terms, and rows with unmapped evidence codes. An annotation id is `gaf:` plus the first 16 hex characters of sha256 over the tab-joined raw columns (`gaf.py:22-25`), so it is stable across loads and row orders.
- `eco.py` uses only `Default` rows. If a code has several, the first one wins.

### The `FactStore` protocol

It has nine methods (`store.py:18-29`): `term`, `primary_id`, `parents`, `children`, `annotations`, `matching`, `subject_for_symbol`, `subject_exists` and `subjects`.

- `StaticFactStore` (`store.py:36-102`) builds its indexes when constructed. It raises `ValueError` on a duplicate annotation id or on an annotation at an alt id.
- `MaskedFactStore(base, hidden)` (`store.py:105-137`) hides annotation ids from `annotations()` and `matching()` only. Terms, edges, subject existence and symbols stay unmasked. The benchmark checks every reply against one.
- `load_store(dir)` (`store.py:147-167`) reads the three files and returns `(store, report)`.
  With the `ledger_dir=` keyword (added by the ledger, with `expected_signers_sha256=`, `cache_dir=`
  and `use_cache=`) the store is the base plus the admitted ledger facts, and the report gains a
  `ledger` block (the verify report, [ledger.md](ledger.md) §5) and a `ledger_gaf` block (the GAF
  parser's counters summed over the admitted ledger rows). A ledger that fails integrity raises
  `LedgerIntegrityError` and nothing loads.

### Release identity, and the skewed pair on disk

- **Fact:** a snapshot's release identity comes from the file headers: the OBO's `data-version:` line, and the GAF's `!date-generated:` and `!go-version:` lines (`bench/items.py:138-154`, `fetch.py:752-773`). It does not come from `snapshot.json`.
- **Fact:** the pair on disk is skewed. The GAF was built against GO 2026-04-27, but the OBO is 2026-07-26, which is why 162 GAF rows sit at terms this OBO marks obsolete. There is no `snapshots/go/snapshot.json`. The OBO and GAF are dated 2026-09-21 00:09 and the ECO mapping 10:23, all before the pinning fetcher existed (`3398050`, 2026-09-21 15:49). `mg biolean fetch` would pin the OBO to the GAF's release (`fetch.py:828-839`).
- **Open question:** keep the skewed pair, or re-fetch and rebuild? Re-fetching changes the headers. `bench run`, `bench score` and `--resume` would then refuse the frozen items and every existing results file (exit 2). See [benchmark.md](benchmark.md) and [BACKLOG.md](../BACKLOG.md).

## 5. Proof rules

There are four rules and no others (`kernel.py:19-20`). This section describes what the code does.

| Rule | Premises | Step keys beyond `id`, `rule`, `conclusion` | Checks, with the error code for each | Conclusion |
|---|---|---|---|---|
| `axiom` | 0 | optional `code` (string); optional `reference` (string) | Take `rows = store.matching(conclusion)`, an exact match on all five fields including `negated`. If `code` is given, keep only rows with that code; if `reference` is given, keep only rows whose references contain it. Both filters must hold on the same row. If no row is left: `AXIOM_NOT_FOUND` | the stated Prop; `axioms` lists every surviving row |
| `is_a` | exactly 1, an earlier step | `edge: [child, parent]` | The premise's term equals `child` (`PREMISE_MISMATCH`). The premise is not negated (`NEGATED_PREMISE`). The store holds `Edge(child, is_a, parent)` (`EDGE_NOT_FOUND`). Child and parent share a namespace (`NAMESPACE_CROSSED`). The stated conclusion equals the computed one (`CONCLUSION_MISMATCH`) | `(premise.subject, premise.qualifier, parent, premise.taxon, negated=false)` |
| `part_of` | exactly 1, an earlier step | `edge: [child, parent]` | the same as `is_a`, with `Edge(child, part_of, parent)` | the same as `is_a` |
| `sorry` | 0 | `provenance` with exactly the keys `method` (string), `inputs` (non-empty list of strings), `parameters` (object) and `claim` (string) | A missing or wrong-shaped `provenance` is `SORRY_MALFORMED`; a negated conclusion is `SORRY_NEGATED`. Beyond the identifier checks, nothing is checked against the store | the stated Prop, unverified and counted |
| any other name, e.g. `regulates` | — | — | `UNKNOWN_RULE`, and the step gets no further checks | — |

Source: `kernel.py:281-350`.

### Propagation and composition

- **Fact:** a propagation step cites exactly one asserted edge, and the edge's relation must equal the rule's name. The computed conclusion does not depend on the relation (`kernel.py:328`), so `is_a` and `part_of` steps chain in any mix. The kernel composes no relations itself.
- **Fact:** a propagation step copies the premise's subject, qualifier and taxon, so the qualifier never changes along a chain. The qualifier `part_of` (a cellular-component annotation) and the relation `part_of` (a GO edge) share a name and nothing else.
- **Fact:** `regulates`, `positively_regulates` and `negatively_regulates` edges are loaded but never propagate. `PROPAGATING_RELATIONS = ("is_a", "part_of")` (`props.py:51`). A step with `"rule": "regulates"` is `UNKNOWN_RULE`. An `is_a` step over a regulates edge is `EDGE_NOT_FOUND`, and the error shows the real relation.
- **Fact:** a step consumes its premise's *stated* conclusion. That is sound because `ACCEPTED` requires every step to be free of errors.

### Direct edges only: an open decision

- **Fact:** a step's edge must be a direct parent edge in `go-basic.obo` (`kernel.py:304-313`). Citing a true ancestor two hops up is `EDGE_NOT_FOUND`, even though a longer chain would derive the same conclusion.
- **Open question (the owner has not decided):** stay strict; admit a relation-aware or a relation-blind transitive step; or keep the kernel strict and add an untrusted expander to the scorer. The choice changes the headline result. On the prove track, Opus 5's hit rate is 0.410 under the strict rule, 0.538 relation-aware and 0.574 relation-blind. The modal baseline scores 0.528 under all three. The benchmark prompt never says an edge must be direct (`bench/render.py:13-32`). See the [decision memo](../decisions/2026-09-22-biolean-transitive-edges.md).

### Namespaces

- `NAMESPACE_CROSSED` fires whenever the step reaches rule application, both edge endpoints resolve and their namespaces differ, whether or not the edge exists (`kernel.py:314-319`).
- **Fact:** `go-basic.obo` 2026-07-26 has 0 cross-namespace `is_a`/`part_of` edges. On real data, then, this code can only fire together with `EDGE_NOT_FOUND`. The test fixture has a synthetic molecular-function→biological-process `part_of` edge so that the check is exercised.
- A cross-namespace step also normally gets `QUALIFIER_ASPECT_MISMATCH` on its conclusion.
- The closures behind conflicts and suggestions follow only `is_a` and `part_of`, stay within one namespace and visit only live terms (`kernel.py:63-120`).

### Obsolete terms, alt ids, unknown ids

| Case | Kernel | Elaborator | Tactics |
|---|---|---|---|
| an obsolete term at any position (goal, conclusion, edge endpoint) | `OBSOLETE_TERM`, with `expected = {replaced_by, consider}`, even when a GAF row exists at that term | never rewritten | skipped (counted in the `goals` report) |
| an alt id | `ALT_ID_IN_KERNEL`, with `expected` = the primary id | rewritten to the primary id (`ALT_ID_RESOLVED`) | not applicable |
| an unknown id | `UNKNOWN_TERM` | left alone | `prove` returns nothing (reason `unknown_term`) |

- **Fact:** 10,248 of the 48,340 terms are obsolete. 2,232 have `replaced_by`, 2,191 have only `consider` and 5,825 have neither, so an `OBSOLETE_TERM` error often carries no replacement.
- **Fact:** `ALT_ID_IN_KERNEL` cannot occur through the CLI, because the elaborator rewrites every alt id first. Only a direct call to `kernel.check()` can reach it. The kernel never resolves an id itself; the code exists to prove that (`test_alt_id_reaching_the_kernel_is_an_error`, `tests/test_biolean_kernel.py:187`).

### NOT annotations

- An axiom can conclude a negated Prop when a NOT row matches it. A NOT goal is provable only by a direct axiom: a negated premise cannot propagate (`NEGATED_PREMISE`), and a `sorry` cannot conclude a negated Prop (`SORRY_NEGATED`).
- There is no NOT contrapositive (NOT at a parent implies NOT at every descendant). The owner deferred it to the defeasibility milestone (spec, "Non-goals for v1"; §8).

### Order of checks, and precedence

The checker runs these steps in order (`kernel.py:387-451`):

1. The top level must be an object with `goal`, `steps` (a list) and `root` (a string). If it is not, the result is one `MALFORMED` error and nothing else. `"biolean": "0.1"` and any other top-level key are ignored.
2. Each step is parsed. It needs a string `id`, a string `rule` that is a known rule, only the keys allowed for that rule, a well-formed `conclusion`, `premises` as a list of strings (required on `is_a` and `part_of`), a two-string `edge` on `is_a` and `part_of`, and string `code`/`reference` on an axiom. An unknown rule is `UNKNOWN_RULE`; any other failure is `MALFORMED`.
3. A reused id is `DUPLICATE_STEP`. References resolve to the first step with that id.
4. Each premise must name an earlier step. If it names no step, the error is `UNKNOWN_STEP_REF`; if it names the same or a later step, `STEP_ORDER`. So cycles cannot be written.
5. The premise count must fit the rule (`axiom` and `sorry` 0, `is_a` and `part_of` 1), else `PREMISE_ARITY`.
6. Identifiers are checked at the goal, at every conclusion and at both edge endpoints.
7. The step's rule is applied (see the table above).
8. `root` must name a step (`UNKNOWN_STEP_REF`) whose conclusion equals the goal in all five fields (`ROOT_MISMATCH`).

Precedence (`kernel.py:31-33`, `:412-441`):

- A step with an unknown or non-string rule skips checks 4–7.
- A `MALFORMED` step gets no rule application. Neither does a step whose conclusion fails resolution: a malformed taxon, `UNKNOWN_SUBJECT`, `UNKNOWN_TERM`, `OBSOLETE_TERM`, `ALT_ID_IN_KERNEL` or `UNKNOWN_QUALIFIER`. `QUALIFIER_ASPECT_MISMATCH` does not suppress rule application.
- An edge endpoint that fails its term check suppresses `EDGE_NOT_FOUND` and `NAMESPACE_CROSSED` for that step.
- If a premise step has any error, the consumer is listed in `premise_failed` and gets no error for that reason. So one broken axiom yields one error down a chain, and two independent defects yield two.
- Every step is checked, used or not, so an error in an unused step still rejects. The checker never stops at the first error.

### The used chain, unused steps and sorry counts

- `used` is the single chain from `root` that follows each step's first premise (every rule takes at most one). `unused_steps` holds every other id, sorted.
- `sorry_count` counts `sorry` steps on the used chain, and `unused_sorries` counts the rest. `sorries[]` lists every `sorry` step with a `used` flag; it is Phase B's work list.

### Conflicts (they never change the verdict)

- Conflicts are computed after the errors and never affect the verdict (`kernel.py:357-380`, `:509-511`).
- They are computed for every step with a parsed conclusion, used or not, with errors or without. A positive conclusion at term t conflicts with NOT rows at t or at any ancestor of t. A negated conclusion at t conflicts with positive rows at t or at any descendant. The subject, qualifier and taxon must match. Each annotation is listed once, against the earliest step it contradicts.
- **Fact:** contradictory claims are both ACCEPTED. On this snapshot, `KCNK1 enables GO:0005249` is ACCEPTED (via a TAS row at `GO:0005242` plus one `is_a` step), and so is `KCNK1 NOT enables GO:0005249` (via an IDA NOT row). Each verdict lists the other's row under `conflicts`.
- **Open question:** should callers gate on `conflicts` until the defeasibility status (`STANDING`/`CONTESTED`, spec §8) exists? That status is not built.

### What ACCEPTED means

- `verdict` is `ACCEPTED` exactly when `errors` is empty.
- It does not mean the claim was proved from facts alone. A derivation whose root is a `sorry` is ACCEPTED, with exit 0 and `sorry_count` 1. Check `sorry_count == 0`.
- It does not mean the claim is uncontested. Check `conflicts`.
- It covers the elaborated derivation, not the raw input. Check `elaboration`.

## 6. Error codes

There are 21 codes (`errors.py:8-29`). Every error serializes to exactly six keys: `step`, `code`, `message`, `expected`, `actual`, `suggestions`. `step` is `null` for goal-level and top-level errors, and `"#<index>"` for a step without a string id.

| Code | Fires when | `expected` / `actual` / `suggestions` |
|---|---|---|
| `MALFORMED` | The derivation is not `{goal, steps: list, root: str}`. Or a step is not an object; its id or rule is not a string; it has a key its rule does not allow; `premises` is not a list of strings; an `is_a`/`part_of` step lacks `premises` or `edge`; a conclusion or the goal is not exactly five keys of the exact types; an axiom's `code`/`reference` is not a string. Or a taxon is not `NCBITaxon:<digits>` | `actual` = the offending keys or taxon |
| `UNKNOWN_RULE` | `rule` is not `axiom`, `is_a`, `part_of` or `sorry` | `expected` = the four rules; `actual` = the rule |
| `DUPLICATE_STEP` | a step id is reused | `actual` = the id |
| `UNKNOWN_STEP_REF` | a premise or the root names no step | `actual` = the id |
| `STEP_ORDER` | a premise names the same step or a later one | `actual` = the id |
| `PREMISE_ARITY` | the premise count is wrong for the rule | `expected` / `actual` counts |
| `ROOT_MISMATCH` | the root's conclusion differs from the goal in any field | `expected` = the goal; `actual` = the root's conclusion |
| `UNKNOWN_TERM` | the term id is neither a primary id nor an alt id | `actual` = the id |
| `OBSOLETE_TERM` | the term is obsolete, even when a GAF row exists at it | `expected` = `{replaced_by, consider}` |
| `ALT_ID_IN_KERNEL` | an alt id reached the kernel (unreachable through the CLI) | `expected` = the primary id |
| `UNKNOWN_SUBJECT` | the subject has no annotation in the store | `expected` = the candidates for that string as a symbol (empty if none) |
| `UNKNOWN_QUALIFIER` | the qualifier is not one of the 13 | `expected` = the 13, sorted |
| `QUALIFIER_ASPECT_MISMATCH` | the qualifier is illegal for the term's aspect | `expected` / `actual` aspect letters |
| `AXIOM_NOT_FOUND` | no row survives the match and filters | `expected` = the Prop plus any filters. `suggestions` = axiom fragments `{rule, conclusion}` for three cases: the same term under another qualifier; the same qualifier at a descendant; the same qualifier and term under another taxon. Only fragments that pass the identifier checks are kept. A row at the same Prop that failed only the `code`/`reference` filter is never suggested |
| `EDGE_NOT_FOUND` | no edge with that exact relation runs from child to parent | `expected` = `{child, relation, parent}`; `actual` = `{parents_of_child: [[relation, parent], ...]}`; `suggestions` = `{rule, edge}` for each other propagating relation from child to that parent |
| `NAMESPACE_CROSSED` | the edge endpoints are in different namespaces (checked even if the edge is absent) | `expected` / `actual` namespaces |
| `NEGATED_PREMISE` | the step propagates from a NOT conclusion | none |
| `PREMISE_MISMATCH` | the premise's term is not `edge[0]` | `expected` = the child; `actual` = the premise's term |
| `CONCLUSION_MISMATCH` | the stated conclusion differs from the computed one | `expected` = computed; `actual` = stated |
| `SORRY_MALFORMED` | `provenance` is missing or has the wrong shape | `expected` = the key list |
| `SORRY_NEGATED` | a `sorry` step concludes a NOT | none |

Sources: `errors.py:36-52`; `kernel.py:127-350`, `:387-451`.

## 7. The verdict

`check()` returns a plain dict with 12 keys (`kernel.py:498-513`). There is no `Verdict` class.

| Key | Content |
|---|---|
| `verdict` | `"ACCEPTED"` or `"REJECTED"` |
| `goal` | the parsed goal Prop (elaborated on the CLI path), or `null` |
| `steps_checked` | the number of steps, used or not |
| `sorry_count` / `unused_sorries` | `sorry` steps on the used chain / off it |
| `unused_steps` | the step ids not on the used chain, sorted |
| `premise_failed` | the steps whose premise had an error, sorted by id |
| `errors` | the error records (§6) |
| `axioms` | `{step, annotation, code, eco, references}` for every row an axiom matched, sorted by annotation id |
| `sorries` | `{step, used, method, inputs}` for every `sorry` step, in step order |
| `conflicts` | `{step, annotation, negated, code, at, via}`, where `at` is `term`, `ancestor` or `descendant` and `via` is the conflicting row's term; sorted by step position, then annotation id |
| `elaboration` | `{path, kind, before, after}` for every rewrite (§9), sorted by path; `[]` from `check()` itself |

Errors are sorted by `(position, code, message)`, goal and top-level errors first. `position` is used only for sorting and is never serialized. The CLI prints `json.dumps(verdict, sort_keys=True, indent=2)` (`cli.py:1502`), the same serialization as `kernel.dumps`. **Fact:** the output was byte-identical across two separate CLI runs (checked with `cmp` in the 2026-09-22 survey).

## 8. Derivation format, with real examples

### Shape

The top level is `{"biolean": "0.1", "goal": <Prop>, "steps": [<step>, ...], "root": "<step id>"}`. Only `goal`, `steps` and `root` are validated. The `biolean` version field is ignored, and so is any other top-level key. Steps are ordered: a premise must come earlier.

| `rule` | Required keys | Optional keys | Any other key |
|---|---|---|---|
| `axiom` | `id`, `rule`, `conclusion` | `premises` (must be empty), `code`, `reference` | `MALFORMED` |
| `is_a`, `part_of` | `id`, `rule`, `conclusion`, `premises` (exactly one id), `edge` (`[child, parent]`) | — | `MALFORMED` |
| `sorry` | `id`, `rule`, `conclusion`, `provenance` (a missing one is `SORRY_MALFORMED`) | `premises` (must be empty) | `MALFORMED` |

### Example A: ACCEPTED (real, against `snapshots/go`)

TP53 is `involved_in` replicative senescence (`GO:0090399`) by an IMP row. `GO:0090399 is_a GO:0022402` (cell cycle process), and `GO:0022402 part_of GO:0007049` (cell cycle). The goal uses a symbol and a `taxon:` spelling on purpose, to show elaboration. The axiom is filtered by both code and reference.

```bash
cat > /tmp/biolean-accepted.json <<'EOF'
{
  "biolean": "0.1",
  "goal": {"subject": "TP53", "qualifier": "involved_in", "term": "GO:0007049", "taxon": "taxon:9606", "negated": false},
  "steps": [
    {"id": "s1", "rule": "axiom", "code": "IMP", "reference": "PMID:19951988",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0090399", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0090399", "GO:0022402"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0022402", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s3", "rule": "part_of", "premises": ["s2"], "edge": ["GO:0022402", "GO:0007049"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0007049", "taxon": "NCBITaxon:9606", "negated": false}}
  ],
  "root": "s3"
}
EOF
mg biolean check /tmp/biolean-accepted.json 2>/dev/null; echo "exit $?"      # exit 0
```

The output on 2026-09-22, compacted to one line per key (the CLI prints `indent=2`):

```json
{
  "axioms": [{"annotation": "gaf:e68befcebb0f4117", "code": "IMP", "eco": "ECO:0000315", "references": ["PMID:19951988"], "step": "s1"}],
  "conflicts": [],
  "elaboration": [{"after": "UniProtKB:P04637", "before": "TP53", "kind": "SYMBOL_RESOLVED", "path": "goal/subject"}, {"after": "NCBITaxon:9606", "before": "taxon:9606", "kind": "TAXON_NORMALIZED", "path": "goal/taxon"}],
  "errors": [],
  "goal": {"negated": false, "qualifier": "involved_in", "subject": "UniProtKB:P04637", "taxon": "NCBITaxon:9606", "term": "GO:0007049"},
  "premise_failed": [],
  "sorries": [],
  "sorry_count": 0,
  "steps_checked": 3,
  "unused_sorries": 0,
  "unused_steps": [],
  "verdict": "ACCEPTED"
}
```

`mg biolean prove "TP53 involved_in GO:0007049" --taxon 9606` finds the same three-step chain, without the `code`/`reference` filters.

### Example B: REJECTED (real, against `snapshots/go`)

This is the same chain with three changes. `s1` demands `code: "IDA"`, but only an IMP row exists. `s3` cites `is_a` where GO has `part_of`. `s4` is an unused `sorry`.

```bash
cat > /tmp/biolean-rejected.json <<'EOF'
{
  "biolean": "0.1",
  "goal": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0007049", "taxon": "NCBITaxon:9606", "negated": false},
  "steps": [
    {"id": "s1", "rule": "axiom", "code": "IDA",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0090399", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0090399", "GO:0022402"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0022402", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s3", "rule": "is_a", "premises": ["s2"], "edge": ["GO:0022402", "GO:0007049"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0007049", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s4", "rule": "sorry",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0007049", "taxon": "NCBITaxon:9606", "negated": false},
     "provenance": {"method": "m:deseq2", "inputs": ["GEO:GSE0"], "parameters": {}, "claim": "placeholder"}}
  ],
  "root": "s3"
}
EOF
mg biolean check /tmp/biolean-rejected.json 2>/dev/null; echo "exit $?"            # exit 3
mg biolean check /tmp/biolean-rejected.json --render 2>/dev/null                     # prose
```

The JSON output on 2026-09-22, compacted:

```json
{
  "axioms": [],
  "conflicts": [],
  "elaboration": [],
  "errors": [
    {"actual": null, "code": "AXIOM_NOT_FOUND", "expected": {"code": "IDA", "negated": false, "qualifier": "involved_in", "subject": "UniProtKB:P04637", "taxon": "NCBITaxon:9606", "term": "GO:0090399"}, "message": "no annotation matches with {'code': 'IDA'}", "step": "s1", "suggestions": []},
    {"actual": {"parents_of_child": [["is_a", "GO:0009987"], ["part_of", "GO:0007049"]]}, "code": "EDGE_NOT_FOUND", "expected": {"child": "GO:0022402", "parent": "GO:0007049", "relation": "is_a"}, "message": "no is_a edge GO:0022402 -> GO:0007049", "step": "s3", "suggestions": [{"edge": ["GO:0022402", "GO:0007049"], "rule": "part_of"}]}
  ],
  "goal": {"negated": false, "qualifier": "involved_in", "subject": "UniProtKB:P04637", "taxon": "NCBITaxon:9606", "term": "GO:0007049"},
  "premise_failed": ["s2"],
  "sorries": [{"inputs": ["GEO:GSE0"], "method": "m:deseq2", "step": "s4", "used": false}],
  "sorry_count": 0,
  "steps_checked": 4,
  "unused_sorries": 1,
  "unused_steps": ["s4"],
  "verdict": "REJECTED"
}
```

`--render` prints:

```
REJECTED: 4 steps, 2 errors, 1 unused sorry, 1 unused step
  s1 AXIOM_NOT_FOUND: no annotation matches with {'code': 'IDA'}
  s3 EDGE_NOT_FOUND: no is_a edge GO:0022402 -> GO:0007049
    suggest: part_of [GO:0022402, GO:0007049]
```

How to read it:

- The two independent defects give two errors. `s2` depends on the broken `s1`, so it appears only in `premise_failed`.
- `s1` gets no suggestions, even though an IMP row exists at the same Prop, because suggestions never offer "the same proposition with other evidence". Whether to add that is an open question ([§15](#15-not-built-and-open-questions)).
- The unused `sorry` does not reject. It is listed with `used: false` and counted in `unused_sorries`.

<details>
<summary>Example C: identifier and structure errors in one derivation (real; exit 3)</summary>

```bash
cat > /tmp/biolean-rejected2.json <<'EOF'
{
  "goal": {"subject": "GNAS", "qualifier": "involved_in", "term": "GO:0006917", "taxon": "9606", "negated": false},
  "steps": [
    {"id": "s1", "rule": "axiom",
     "conclusion": {"subject": "UniProtKB:A6NF01", "qualifier": "enables", "term": "GO:0008139", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s2", "rule": "axiom",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "enables", "term": "GO:0006915", "taxon": "human", "negated": false}},
    {"id": "s3", "rule": "regulates", "premises": ["s2"], "edge": ["GO:0006915", "GO:0008219"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0008219", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s1", "rule": "is_a", "premises": ["s9"], "edge": ["GO:0006915", "GO:0012501"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0012501", "taxon": "NCBITaxon:9606", "negated": false}}
  ],
  "root": "s3"
}
EOF
mg biolean check /tmp/biolean-rejected2.json --render 2>/dev/null
```

```
REJECTED: 4 steps, 7 errors, 0 unused sorry, 2 unused steps
  goal UNKNOWN_SUBJECT: unknown subject GNAS
  s1 OBSOLETE_TERM: GO:0008139 is obsolete
  s2 MALFORMED: taxon must be NCBITaxon:<digits>, got 'human'
  s2 QUALIFIER_ASPECT_MISMATCH: enables is a F-aspect qualifier; GO:0006915 is biological_process
  s3 UNKNOWN_RULE: unknown rule 'regulates'
  s1 DUPLICATE_STEP: step id 's1' is used more than once
  s1 UNKNOWN_STEP_REF: premise 's9' names no step
  elaborated: goal/subject GNAS -> None (SYMBOL_AMBIGUOUS)
  elaborated: goal/taxon 9606 -> NCBITaxon:9606 (TAXON_NORMALIZED)
  elaborated: goal/term GO:0006917 -> GO:0006915 (ALT_ID_RESOLVED)
```

`GNAS` maps to 4 UniProtKB ids, so the elaborator leaves it and the kernel reports `UNKNOWN_SUBJECT` with the candidates in `expected`. `GO:0008139` is obsolete even though a GAF row exists at it. There is no `ROOT_MISMATCH`, because the root `s3` has an unknown rule and its conclusion is never parsed. The last two error lines belong to the fourth step, which reuses the id `s1`. Both steps are reported as `s1`, because `position` is not serialized.

</details>

## 9. Elaborator

`elaborate(derivation, store)` (`elaborate.py:69-87`) deep-copies its input and rewrites identifiers only, by lookup. Every rewrite is reported. `elaborate_and_check` (`elaborate.py:90-95`) is the CLI's path: it elaborates, checks, and attaches the report as `verdict["elaboration"]`. It is untrusted.

| Kind | Input | Rewrite | Positions |
|---|---|---|---|
| `SYMBOL_RESOLVED` | a subject that is not a known subject but is a symbol of exactly one subject | that subject, whatever its prefix | `goal/subject`, `steps/<i>/conclusion/subject` |
| `SYMBOL_AMBIGUOUS` | a symbol of two or more subjects | none (`after` is `null`); the kernel then reports `UNKNOWN_SUBJECT` with the candidates | the same |
| `ALT_ID_RESOLVED` | a term that is not a primary id but is a known alt id | its primary id | `goal/term`, `steps/<i>/conclusion/term`, `steps/<i>/edge/0`, `steps/<i>/edge/1` |
| `TAXON_NORMALIZED` | a taxon that does not match `NCBITaxon:\d+` but is `<digits>` or `taxon:<digits>` | `NCBITaxon:<digits>` | `goal/taxon`, `steps/<i>/conclusion/taxon` |
| none | an obsolete term | never rewritten; the kernel's `OBSOLETE_TERM` carries `replaced_by` | — |

- Qualifiers and `negated` are never touched. The report is sorted by path.
- **Fact:** symbol resolution accepts any unique subject, not only UniProtKB ids, and ignores taxon (`elaborate.py:26-35`). Of 38,822 distinct symbols on this snapshot, 38,750 resolve uniquely, and 19,128 of those resolve to an RNAcentral or ComplexPortal subject. 72 symbols are ambiguous; `GNAS`, for example, has 4 candidates. See [§13](#13-as-built-deviations-from-the-spec).

## 10. Tactics

`tactics.py` is untrusted convenience over the kernel and the store. Every tactic skips negated rows, obsolete or unknown terms, and rows whose qualifier is illegal for the term's aspect.

- **`goals_for(subject, store, aspect=None)`** (`tactics.py:45-84`) lists every proposition derivable for a subject. It walks upward over `propagating_parents` from each qualifying annotation, keeping the shortest depth. It returns `{prop, direct, depth}` items, where `depth` counts propagation steps (0 for a direct annotation), sorted by `(term, qualifier, taxon)`, plus four skip counters. TP53 has 559 goals, 141 of them direct, with a maximum depth of 8 (`mg biolean goals TP53`).
- **`applicable(prop, store)`** (`tactics.py:87-104`) is the `apply?` analogue. It returns an axiom fragment if a row matches, plus one `is_a`/`part_of` fragment per live child term at which the subject has a derivable proposition. It never returns a regulates edge. **No CLI exposes it; only tests call it.**
- **`prove(prop, store)`** (`tactics.py:107-154`) is the mechanical prover. It runs a breadth-first search that starts at once from every direct annotation term of the subject under the same qualifier and taxon, and it expands parents in `(parent, relation)` order. The first path that reaches the target is a shortest derivation, with ties broken by sorted term id. It returns `{biolean, goal, steps s1..sn, root}`, or `None` for a negated, unknown or obsolete target or when no path exists. It is the benchmark's `gold:` baseline.
- **Soundness checks on `prove`:** `test_prove_output_is_accepted_by_the_kernel` runs on the fixture. The snapshot-gated scale test hides one real row at a time and requires every derivation `prove` finds to have `errors == []`. On the 2026-09-21 snapshot it recorded tried 1,000, accepted 815, not re-derivable 185, and propagated 30. About 785 of the 815 accepted derivations re-derive through a sibling evidence row (`tests/test_biolean_scale.py:48, :56-64`).
- **Rendering** (`render.py`): `render_verdict` backs `check --render`. `render_derivation` produces prose for a derivation, but no CLI command calls it; only tests do.

## 11. CLI

`--store` defaults to `snapshots/go`. `--taxon` defaults to `NCBITaxon:9606` and also accepts `9606` and `taxon:9606`. `check`, `prove` and `goals` print `{"load_report": ...}` to stderr. Source: `cli.py:1168-1240`, `:1473-1528`, `:1938-1954`.

| Command | Needs | Exit codes |
|---|---|---|
| `mg biolean fetch [--out DIR]` | network; writes about 47 MB (45M by `du -sh`) | 0 on success; exit 1 (uncaught exception) on a network error, from reading the code |
| `mg biolean check FILE [--store DIR] [--render]` | a snapshot | 0 ACCEPTED, 3 REJECTED, 2 usage |
| `mg biolean prove "SUBJECT QUALIFIER TERM" [--taxon T] [--store DIR]` | a snapshot | 0 found, 3 no derivation, 2 usage |
| `mg biolean goals SUBJECT [--aspect F\|P\|C] [--taxon T] [--store DIR]` | a snapshot | 0, or 2 usage (including an ambiguous symbol) |
| `mg biolean bench build\|coverage\|run\|score` | see [benchmark.md](benchmark.md); `run` with `claude:` or `openai:` **costs money** | see there |

`ledger init|append|verify|show`, and `--ledger` on `check|prove|goals`: [ledger.md](ledger.md).

Exit 2 (`parser.error`) covers: a `--store` that lacks any of the three files; an unreadable or non-JSON derivation file; a claim that is not exactly three tokens; a bad `--taxon`; a `goals` subject containing whitespace; and an ambiguous `goals` symbol. Exit 1 is reserved for uncaught exceptions and is never a verdict.

### `fetch`

```bash
mg biolean fetch --out /tmp/go-fresh      # network; a new directory leaves snapshots/go untouched
```

- It downloads the GAF first, then `go-basic.obo` at the release named in the GAF's `!go-version:` header, then the ECO mapping. It writes `snapshot.json` (`fetch.py:828-839`) and prints that manifest.
- **Caution:** `--out snapshots/go` (the default) overwrites the pair that `biolean-bench/`, `opus.jsonl` and `modal.jsonl` were built on. After that, `bench run`, `bench score` and `--resume` refuse them. Whether to re-fetch is an open question (§4).
- It writes each file as soon as it downloads, so a failure partway through leaves a mixed directory. This comes from reading `fetch.py:779-839`; it was not exercised live.
- If the GAF header names no release, it falls back to the moving `latest` OBO URL and records release `""`, with no error (`fetch.py:745-749`).
- **Not verified live on 2026-09-22** (the survey had no network). Only its 5 seam tests ran (`tests/test_biolean_fetch.py`).

### `check`

```bash
mg biolean check /tmp/biolean-accepted.json            # verdict JSON on stdout (sort_keys, indent 2)
mg biolean check /tmp/biolean-rejected.json --render   # the verdict as prose, not the derivation
```

Build the two files from [§8](#8-derivation-format-with-real-examples).

### `prove`

```bash
mg biolean prove "UniProtKB:P04637 involved_in GO:0006915"    # exit 0; 1 step: TP53 is annotated at apoptotic process directly
mg biolean prove "TP53 involved_in GO:0007049" --taxon 9606    # exit 0; axiom GO:0090399, is_a GO:0022402, part_of GO:0007049
mg biolean prove "UniProtKB:P04637 involved_in GO:0006917"    # exit 0; alt id, reported as ALT_ID_RESOLVED
mg biolean prove "UniProtKB:P04637 enables GO:0006915"        # exit 3; reason no_path
```

The output is `{derivation, elaboration}`, or `{derivation: null, reason, goal, elaboration}` with exit 3. The claim is always stated as non-negated. The reasons, checked in this order (`cli.py:1227-1240`):

| `reason` | When | Example |
|---|---|---|
| `negated_goal` | unreachable from the CLI | — |
| `unknown_term` | the term is not in the OBO | `UniProtKB:P04637 involved_in GO:9999999` |
| `obsolete_term` | the term is obsolete | `UniProtKB:A6NF01 enables GO:0008139` |
| `no_direct_annotations` | no live, aspect-legal row for (subject, qualifier, taxon), including when the subject is unknown | `NOSUCHGENE involved_in GO:0006915` |
| `no_path` | anything else, including a qualifier illegal for the term's aspect | `UniProtKB:P04637 enables GO:0006915` |

**Open question:** the last two reasons mislead. The kernel would report `UNKNOWN_SUBJECT` and `QUALIFIER_ASPECT_MISMATCH` for those cases.

### `goals`

```bash
mg biolean goals TP53                 # exit 0; 559 goals for UniProtKB:P04637 (141 direct, max depth 8)
mg biolean goals TP53 --aspect C      # cellular-component goals only
mg biolean goals GNAS                 # exit 2: "symbol 'GNAS' is ambiguous: UniProtKB:O95467, ..."
```

The output is `{subject, taxon, goals: [{prop, direct, depth}], report, elaboration}`. A symbol is resolved and reported with the path `subject` rather than `goal/subject`. `--taxon` filters the goals after they are computed. **Gap:** a subject that is neither a known subject nor a symbol returns `goals: []` with exit 0, not an error (`cli.py:1217-1224`).

## 12. Tests

| Scope | Tests | Files | Gated on |
|---|---|---|---|
| Plan 1's files: props, obo, eco, gaf, store, kernel, elaborate, tactics, render, fetch, cli, scale | 145 (142 at `7bc79ef`; Plan 2's `c732c6b` added 3) | 12 | `test_biolean_scale.py` (1 test) needs `snapshots/go` |
| Benchmark files: `test_biolean_bench_*.py` | 97 (73 at `b0f80c4`; the `--workers/--resume` merge `6b28222` added 24) | 7 | `test_biolean_bench_scale.py` (1 test) needs `snapshots/go` |
| **All Biolean** | **242** | **19** | 2 need the snapshot; none needs the DB |

Source: `.venv/bin/python -m pytest --co -q tests/test_biolean_*.py` → `242 tests collected`. Run them with:

```bash
env -u OPENAI_API_KEY .venv/bin/python -m pytest -q tests/test_biolean_*.py
```

- **Not enforced by CI yet:** CI's `test` job runs `pytest -q` on Python 3.12 on every push to `main` and on every PR (`.github/workflows/ci.yml`). No Biolean commit has been pushed, so CI has never run these tests. The local venv is Python 3.14.6.
- **Never a CI gate:** the 2 scale tests. CI has no `snapshots/go`, so they skip there.
- The fixture is one hand-built inventory, `tests/fixtures/biolean/` (`go-mini.obo`, `goa-mini.gaf`, `eco-mini.txt`, `golden_verdict.json`), plus `tests/biolean_fixture.py::mini_store()`. `test_verdict_matches_committed_golden` (`tests/test_biolean_kernel.py:638`) pins the verdict's shape byte for byte.
- Mutation discipline: every test in spec §9 names the mutation that must make it fail, and both plans' Global Constraints require each commit body to record "mutation checked". This doc did not re-run the mutations.

## 13. As-built deviations from the spec

Facts. Where the spec and the code disagree, the code is what runs.

| # | Spec says (line) | As built (evidence) |
|---|---|---|
| 1 | "`kernel.py` is the only trusted file. It imports `props.py`, `errors.py`, and the `FactStore` protocol and nothing else in the package" (§3, :183-184) | It imports the `store` module, which loads `obo`, `gaf` and `eco` (`kernel.py:17`, `store.py:12-14`). No test pins the import set |
| 2 | `check(derivation, store) -> Verdict` (:287; also :655, :720, :725) | a plain dict with 12 keys (`kernel.py:498-513`) |
| 3 | suggestions "are themselves well-formed step fragments, so an agent could splice one in verbatim" (:358-359) | `AXIOM_NOT_FOUND` suggestions are `{rule, conclusion}`; `EDGE_NOT_FOUND` suggestions are `{rule, edge}`. Neither has an `id`, and edge suggestions have no `premises` or `conclusion` (`kernel.py:257-258`, `:307-309`) |
| 4 | a bare symbol resolves only to "exactly one `UniProtKB:` id" (:437) | resolves to any unique subject of any prefix, ignoring taxon (`elaborate.py:26-35`); 19,128 of the 38,750 uniquely resolving symbols go to RNAcentral or ComplexPortal |
| 5 | "every substitution the elaborator makes is reported" (:177-178) | `prove` and `goals` normalize `--taxon` in `cli.py` before elaborating (`cli.py:1197-1201`, `:1213-1216`), so no `TAXON_NORMALIZED` entry appears. `check` does report taxa rewritten inside the file |
| 6 | "there is a prose rendering of any derivation for review" (§0.4, :23-24) | `render_derivation` exists (`render.py:32-56`), but only tests call it. `check --render` renders the verdict |
| 7 | the fetcher pins the OBO to the GAF's release, "so the shipped pair is consistent" (:118-121) | the fetcher does pin (`fetch.py:828-839`), but the pair on disk predates it and is skewed (§4) |
| 8 | `go-basic.obo` has "57,458 `is_a`" (:114) | the store holds 57,456; the other 2 `is_a:` lines sit in `[Typedef]` stanzas, which `obo.py` skips |
| 9 | scale check: "`prove` over 1,000 sampled population triples with every derivation accepted" (:897-898) | the test hides each sampled row and allows not-re-derivable triples; it asserts accepted ≥ 200 and propagated ≥ 20 (`tests/test_biolean_scale.py:48, :56-64`, commit `39d0263`). Every derivation found must still be accepted |
| 10 | test names `test_unused_steps_are_reported` (:812), `test_gaf_two_references_are_split` (:833), `test_load_report_has_every_key_even_when_zero` (:836), `test_edge_endpoints_are_elaborated` (:848), `test_applicable_never_suggests_a_regulates_edge` (:856) | the behaviour is tested under other names, e.g. `test_gaf_two_references_are_split_and_sorted` and `test_applicable_lists_axiom_and_child_fragments_and_never_regulates` |

The deliberate deviations recorded in the plans are already written back into the spec: Plan 1's `Term.alt_ids`, and the seven listed in Plan 2's Global Constraints, written in by `c732c6b` (see [benchmark.md §10](benchmark.md)). The Plan 1 document's 88 checkboxes are all still unticked, although every task merged in `7bc79ef`.

## 14. Owner-fixed decisions (spec §0)

These were settled with the owner and recorded in the spec dated 2026-09-21; this doc does not reopen them. The full text is in [spec §0](../superpowers/specs/2026-09-21-biolean-design.md#0--fixed-decisions); the decision log is [decisions/README.md](../decisions/README.md).

| # | Owner decision | As built, 2026-09-22 |
|---|---|---|
| 1 | Phase A now: a typed checker for claims over existing ontologies. Phase B later: an analysis verified as a proof, with `sorry` steps discharged through the methods graph | Phase A is built. Phase B has not started; there is no `discharge` anywhere in `src/` |
| 2 | The kernel guarantees structural soundness only. No scores, probabilities or belief | holds: the kernel produces no numbers about truth |
| 3 | The library is existing ontologies: `go-basic.obo` plus human GOA (GAF 2.2). Evidence codes are types, never weights | holds: a code is only an optional axiom filter |
| 4 | The prover is an LLM agent: JSON derivations, errors written for a model, no human syntax, and a prose rendering for review | JSON and typed errors are built. The prose rendering of a derivation exists but has no CLI |
| 5 | Computed evidence is admitted as `sorry`, with provenance recorded and the count reported | holds; `sorries[]` is Phase B's work list |
| 6 | Success means (a) kernel soundness tests under mutation discipline as the CI gate, and (b) a leave-one-out benchmark with gold from the data and coverage reported beside every number | (a) the tests exist, but CI has never run them (not pushed). (b) is built: [benchmark.md](benchmark.md) |
| 7 | It lives in this repo, as `src/methods_graph/biolean/` | holds |

The spec also records one correction to what was agreed in conversation. Hiding a gene's whole subtree makes re-derivation impossible by construction, so that variant became the **hypothesize** track (format compliance only in v1). The **prove** track hides only the direct annotation.

The v1 non-goals (spec, "Non-goals for v1"): no REPL or editor loop (single-shot; suggestions are never fed back); no NOT propagation; no inference over the regulates family; no semantics for annotation extensions, isoforms or interacting taxa (kept on the record, ignored by the rules); only human in the shipped fetch; no Kuzu storage, KGX export or Biolink mapping; no `sorry` discharge.

## 15. Not built, and open questions

Nothing in this table is settled unless it is marked as a fact. [BACKLOG.md](../BACKLOG.md) holds the prioritized list.

| Item | Kind | Detail |
|---|---|---|
| Transitive (non-direct) edge steps | **open decision** | [memo](../decisions/2026-09-22-biolean-transitive-edges.md); changes the Opus 5 headline from 0.410 to 0.538 or 0.574 |
| Re-fetch `snapshots/go` to a pinned pair | **open decision** | the pair on disk is skewed; re-fetching strands the frozen items and results (§4) |
| Defeasibility status `STANDING`/`CONTESTED`, and the optional NOT contrapositive as a fifth rule | not built; an owner choice (spec §8) | until then, contradictory claims are both ACCEPTED and only `conflicts` shows it |
| Phase B `discharge(sorry, provider)` | not built | spec §8; the hypothesize track waits on it |
| Slice 2 (gene → disease) | not built | the spec §8 names the slice. The intended sources (MONDO, HPO, Open Targets, Monarch) are named only in the owner's project notes, not in the spec |
| A test that pins the kernel's import set | open | §3 |
| The suggestion contract: spliceable verbatim, or only well-typed? | open | §13 row 3 |
| Suggest "the same Prop, other evidence" on `AXIOM_NOT_FOUND` | open | Example B |
| `prove` reason taxonomy (`no_path` / `no_direct_annotations` mislead) | open | §11 |
| Symbol resolution beyond UniProtKB, and taxon-blind | open | §9 |
| Validate the derivation's `"biolean"` version field | open | it is ignored today |
| Store re-parsed on every call (about 12–16 s), no cache or daemon | open | matters for any agent loop |
| `fetch` silently falls back to the `latest` OBO | open | §11 |
| `goals` on an unknown non-symbol subject exits 0 with no goals | open | §11 |
| Two steps sharing an id are both reported under that id | minor | `position` is not serialized |
| `applicable` and `render_derivation` have no CLI | open | wire them up or drop them from the pitch |
