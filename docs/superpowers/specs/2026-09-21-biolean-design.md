# Biolean — Phase A design

> **Status as of 2026-09-22: Phase A implemented; Phase B (`discharge`) and §8 defeasibility (STANDING/CONTESTED) not started.**
>
> Plan 1 merged in `7bc79ef` (2026-09-21), Plan 2 in `b0f80c4` (2026-09-22). Follow-ups: closed-book `claude:` adapter `894072d`; `bench run --workers/--resume` `6b28222`, which has no spec. None of it is pushed.
>
> As-built references: [`docs/biolean/README.md`](../../biolean/README.md) (kernel, rules, errors, CLI) and [`docs/biolean/benchmark.md`](../../biolean/benchmark.md). Where this spec disagrees with the code, the code wins. Known divergences:
>
> - §0.4: `render_derivation` exists (`biolean/render.py:32-56`) but has no CLI surface. `check --render` prints prose for the *verdict*, not the derivation.
> - §1 Sources: the fetcher does pin the OBO to the GAF's release (`fetch.py:828-839`), but the `snapshots/go/` on disk was not made by it. The OBO is `2026-07-26` and the GAF names `2026-04-27`; there is no `snapshot.json`, and 162 rows load as `term_obsolete`. The frozen items and all results were built on this pair.
> - §1 Sources: the `is_a` count is 57,456, not 57,458. The other 2 `is_a:` lines sit in `[Typedef]` stanzas, which `obo.py` skips. Every other OBO/GAF count in that table reproduces.
> - §2/§4: "every substitution is reported" is not true for `prove` and `goals`. Their CLI normalizes `--taxon` before elaboration (`cli.py:1197-1201, 1213-1216`), so no `TAXON_NORMALIZED` entry appears.
> - §3: `kernel.py` imports `store`, which imports `obo`, `gaf` and `eco` at module level (`store.py:12-14`). The verdict also depends on `StaticFactStore`'s indexes, so the kernel is not literally the only trusted file.
> - §3 Checking (also §7, §8): there is no `Verdict` type. `check()` returns a plain dict with 12 keys (`kernel.py:387, 498-513`).
> - §3 Error codes: suggestions are not verbatim-spliceable steps. `EDGE_NOT_FOUND` gives `{rule, edge}` (`kernel.py:307-309`), `AXIOM_NOT_FOUND` gives `{rule: "axiom", conclusion}` (`kernel.py:257-258`), and neither has an id.
> - §4 Elaborator: a bare symbol resolves to *any* unique subject, whatever its prefix (RNAcentral, ComplexPortal) and ignoring taxon (`elaborate.py:30-33`), not only a `UniProtKB:` id.
> - §6 Population: items are cut by `--since`, sorted by id, and the RNG is skipped when N ≥ the population; the result is re-sorted by id (`bench/items.py:260-264, 310-313`).
> - §6 Prove track: `hit_rate` is per track (hits / error-free prove rows, `bench/score.py:203-216, 264`), not `hits / (n_rows - n_errors)` over both tracks.
> - §6 Prove track: the error denominator key is `error_occurrences_denominator` (`score.py:192-194`), not `n_errors_total`.
> - §6 Hypothesize track: there is no "format compliance only" heading. The hypothesize summary block carries a `note` string that begins with that phrase (`score.py:33-36, 236`).
> - §6 Baselines and Risks: "a model that cannot beat it knows GO's shape, not the gene" is **contradicted by the 2026-09-22 Opus 5 run**. Opus scores 205/500 vs modal 264 under the strict kernel, but beats modal on a post-hoc, biology-only rescoring that checks only the chain's gene-level axiom (305 vs 264, p = 0.0015). Its gap to modal closes under a relation-aware transitive rescoring (269 vs 264, p = 0.76), so the gap comes from exact-edge errors; which rule the kernel should use is open. See [`results`](../../biolean/results-2026-09-22-opus-5.md) and the open [decision memo](../../decisions/2026-09-22-biolean-transitive-edges.md).
> - §7 CLI: `bench run` also takes `--workers N`, `--resume`, `--db` and `--oracle-json`, and `bench score` takes `--db` and `--oracle-json` (`cli.py:1958-1990`).
> - §9 Tests: several named tests were renamed or split. Current names include `test_hypothesize_rows_and_summary_carry_no_hit_keys`, `test_random_baseline_is_structurally_valid_and_seeded`, the two `test_modal_…` tests, `test_gaf_two_references_are_split_and_sorted`, `test_applicable_lists_axiom_and_child_fragments_and_never_regulates`. `test_unused_steps_are_reported` does not exist; its `unused_steps == ["s3"]` assertion is made inside two other tests (`tests/test_biolean_kernel.py:448, :455`).
> - §9 Scale check: the test runs under masking and allows `not_rederivable` (`39d0263`). Recorded: 1,000 tried, 815 accepted, 30 propagated, 185 not rederivable. It asserts propagated ≥ 20 and accepted ≥ 200, not "1,000, all accepted". It is snapshot-gated, so CI skips it.

**Date:** 2026-09-21
**Status:** §0 fixed with the owner; §1–§9 revised against a 31-finding adversarial review

Biolean is a proof assistant for biological claims. An LLM agent emits a derivation; Biolean
checks it structurally and returns ACCEPTED or REJECTED with typed errors. The axiom library
is not curated here: it is the Gene Ontology and its annotations, loaded as facts.

## §0 — Fixed decisions

These were settled with the owner and are not reopened by this document.

1. **Phase A now, Phase B later.** A = a typed checker for claims over existing ontologies.
   B = verification of analyses (a pipeline run as a proof that its result is valid given
   method assumptions), discharged through the methods graph.
2. **Kernel guarantee is structural soundness only.** A checked claim means every step
   traces to a recorded fact through a declared rule with its side conditions met. It says
   nothing about truth. No scores, no probabilities, no belief.
3. **Library = existing ontologies.** v1 slice is GO (`go-basic.obo`) plus human GOA
   (GAF 2.2). Evidence codes are *types*, never weights.
4. **The prover is an LLM agent.** Biolean is a checker with a JSON derivation format and
   errors written for a model to act on. There is no human surface syntax in v1; there is a
   prose rendering of any derivation for review.
5. **Computed evidence is admitted as `sorry`.** A step may assert that a method run on a
   dataset yields a fact. v1 accepts the step structurally, records its provenance, and
   reports the count. Phase B discharges `sorry` steps against method preconditions.
6. **Success criteria.** (a) Kernel soundness proven by tests under the repo's mutation
   discipline, as the CI gate. (b) A leave-one-out benchmark on the same footing as the
   method-sequencing benchmark: gold from the data, coverage reported with every number.
7. **Lives in this repo** as `src/methods_graph/biolean/`.

**One correction to what was agreed in conversation.** Hiding a gene's annotations under a
term *and its whole subtree* makes re-derivation from the remaining facts impossible by
construction: propagation only moves upward, and the subtree is exactly the set of terms
from which the target is reachable. That variant cannot measure proving. It is retained as
the **hypothesize** track, where the only admissible proof is a `sorry` step and, in v1,
every rate is a format-compliance rate with no data-derived gold. The **prove** track hides
the direct annotation only, so a derivation through a visible descendant exists and the
agent has to find it closed-book. §6 defines both.

## Non-goals for v1

- No human syntax, editor loop, or REPL. The benchmark is single-shot: error suggestions are
  part of the check output and are never fed back to the model.
- No NOT propagation. The contrapositive of upward propagation (NOT at a parent implies NOT
  at every descendant) is sound under these rules, but GO's NOT qualifier is a curatorial
  exception marker, and admitting the contrapositive is a defeasibility-milestone decision.
- No inference over `regulates`, `positively_regulates`, or `negatively_regulates`.
  Gene-product annotations do not propagate over them, and a derivation that uses one is
  rejected, not ignored.
- No annotation-extension semantics (GAF column 16), no isoform-specific subjects
  (column 17), and no interacting-organism semantics (second value of column 13). All three
  are retained on the fact record and ignored by the rules.
- No organisms other than human in the shipped fetch. The store is organism-agnostic.
- No Kuzu storage, no KGX export of derivations, no Biolink predicate mapping. Slice 2
  (gene to disease) will need the mapping; v1 uses GAF qualifiers as the predicate
  vocabulary verbatim.
- No discharge of `sorry` steps and no knowledge measure for the hypothesize track. Both
  are Phase B.

## §1 — Facts

Everything the kernel can cite is one of three record kinds, all frozen dataclasses.

```python
@dataclass(frozen=True)
class Term:
    id: str                 # "GO:0006915", primary id only
    name: str
    namespace: str          # biological_process | molecular_function | cellular_component
    obsolete: bool
    replaced_by: tuple[str, ...]
    consider: tuple[str, ...]
    alt_ids: tuple[str, ...]     # secondary ids that resolve to this term

@dataclass(frozen=True)
class Edge:
    child: str
    relation: str           # is_a | part_of | regulates | positively_regulates | negatively_regulates
    parent: str

@dataclass(frozen=True)
class Annotation:
    id: str                 # "gaf:" + sha256 of the 17 raw columns joined by tab, first 16 hex.
                            # Stable across loads and row order.
    subject: str            # "UniProtKB:P04637"  (col1 ":" col2)
    symbol: str             # col3
    qualifier: str          # col4 without any NOT| prefix, e.g. "involved_in"
    negated: bool           # col4 had NOT|
    term: str               # col5 resolved to its primary id (§4); the id the kernel matches on
    term_raw: str           # col5 verbatim
    references: tuple[str, ...]   # col6 split on "|"
    code: str               # col7, e.g. "IDA"
    eco: str                # from the official GAF→ECO mapping, "" if unmapped (counted)
    with_from: tuple[str, ...]    # col8 split on "|"
    aspect: str             # col9: F | P | C
    object_type: str        # col12
    taxon: str              # first value of col13, normalized "NCBITaxon:9606"
    interacting_taxon: str  # second value of col13 normalized, "" when absent; not a Prop field
    date: str               # col14 as YYYY-MM-DD
    assigned_by: str        # col15
    extension: str          # col16 raw, may be ""
    form: str               # col17 raw, may be ""
```

`interacting_taxon`, `extension`, and `form` are retained and never read by a rule. None is
part of the `matching()` key, so hiding a proposition in §6 hides every variant of it.

### Sources and what they guarantee

| Source | Measured 2026-09-21 | Guarantees the kernel relies on |
|---|---|---|
| `go-basic.obo` release 2026-07-26 | 48,340 terms, 10,248 obsolete, 57,458 `is_a`, 6,270 `part_of`, 7,770 regulates-family, 3,646 `alt_id`, 14,673 terms with two or more `is_a` parents | acyclic; no relation crosses a namespace; obsolete terms carry no edges |
| `goa_human.gaf.gz` generated 2026-05-21, built against GO release 2026-04-27 | 906,445 data rows; 906,422 annotations after 23 byte-identical rows collapse; 38,924 subjects; 18,032 terms; 1,501 NOT rows; 851 rows with two taxa; 13 distinct qualifiers; IEA is 21% of rows; 162 rows at terms obsolete in the 2026-07-26 OBO | GAF 2.2 column layout; qualifier always present and aspect-consistent; column 13 has one or two values |
| `gaf-eco-mapping.txt` from `http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt` | 26 `CODE<tab>Default<tab>ECO:id` rows; `GO_REF`-specific rows were removed in January 2026 | the `code → ECO` table is data, not a constant in source; rows whose second column is not `Default` are counted and ignored |

The 162 obsolete-term rows are release skew: the GAF header names the GO release it was
built against, and the OBO PURL always serves the latest. The fetcher (§7) therefore reads
the GAF header first and downloads the OBO at that release, so the shipped pair is
consistent. The counters stay, because a user can load any pair.

The namespace guarantee is a property of `go-basic`, not of GO. Full `go.obo` has
`part_of` edges from molecular function into biological process, and propagating
`enables` across one would produce a qualifier that is illegal for the target aspect. The
kernel checks namespaces on every propagation step even though the shipped data never
triggers it. The synthetic test fixture does trigger it.

### Qualifier and aspect

The kernel refuses any proposition whose qualifier is not legal for its term's aspect. The
table is the GAF 2.2 specification's and is a constant in `props.py`:

| Aspect | Qualifiers |
|---|---|
| F (molecular_function) | `enables`, `contributes_to` |
| P (biological_process) | `involved_in`, `acts_upstream_of`, `acts_upstream_of_positive_effect`, `acts_upstream_of_negative_effect`, `acts_upstream_of_or_within`, `acts_upstream_of_or_within_positive_effect`, `acts_upstream_of_or_within_negative_effect` |
| C (cellular_component) | `located_in`, `part_of`, `is_active_in`, `colocalizes_with` |

All 13 qualifiers observed in the 2026-05-21 human file are in this table. A row with any
other qualifier is a load error counted under `unknown_qualifier`, never silently kept or
dropped.

### Evidence classes

Evidence codes are grouped into the classes GO documents. The class is a type on the
`Annotation`'s report line and a filter in the benchmark; it never affects a verdict.

| Class | Codes |
|---|---|
| experimental | EXP IDA IPI IMP IGI IEP |
| high_throughput | HTP HDA HMP HGI HEP |
| phylogenetic | IBA IBD IKR IRD |
| computational | ISS ISO ISA ISM IGC RCA |
| author_statement | TAS NAS |
| curatorial | IC ND |
| electronic | IEA |

## §2 — Propositions

One proposition shape in v1:

```python
@dataclass(frozen=True)
class Prop:
    subject: str      # "UniProtKB:P04637"
    qualifier: str    # one of the 13 GAF qualifiers
    term: str         # primary GO id
    taxon: str        # "NCBITaxon:<digits>"
    negated: bool
```

Equality is field-wise. Two propositions that differ only in qualifier are different
propositions; `enables` and `contributes_to` at the same term are not interchangeable.

The kernel sees canonical identifiers only. Symbols, `alt_id`s, bare taxon numbers, and
obsolete terms are handled by the elaborator (§4) *before* the kernel, and every
substitution the elaborator makes is reported. A raw `alt_id` reaching the kernel at any
term position is an error, so a test can prove the kernel never resolves one itself.

## §3 — Kernel

`kernel.py` is the only trusted file. It imports `props.py`, `errors.py`, and the
`FactStore` protocol and nothing else in the package. It has no I/O.

### Judgments

- `Fact(annotation)`: the store holds this annotation.
- `Edge(child, relation, parent)`: the store holds this edge.
- `Proves(derivation, prop)`: the checker's output; true when every step checks and the
  root step's conclusion equals the goal.

### Derivation format

```json
{
  "biolean": "0.1",
  "goal": {"subject": "UniProtKB:P04637", "qualifier": "involved_in",
           "term": "GO:0006915", "taxon": "NCBITaxon:9606", "negated": false},
  "steps": [
    {"id": "s1", "rule": "axiom",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in",
                    "term": "GO:0097193", "taxon": "NCBITaxon:9606", "negated": false},
     "code": "IDA"},
    {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0097193", "GO:0006915"],
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in",
                    "term": "GO:0006915", "taxon": "NCBITaxon:9606", "negated": false}},
    {"id": "s3", "rule": "sorry",
     "conclusion": {"subject": "UniProtKB:P04637", "qualifier": "involved_in",
                    "term": "GO:0006915", "taxon": "NCBITaxon:9606", "negated": false},
     "provenance": {"method": "m:deseq2", "inputs": ["GEO:GSE12345"],
                    "parameters": {"contrast": "irradiated_vs_control", "padj": 0.05},
                    "claim": "TP53 targets in the apoptosis branch are induced after irradiation"}}
  ],
  "root": "s2"
}
```

Keys per rule. Every step has `id`, `rule`, `conclusion`; `premises` is optional on
`axiom` and `sorry` (absent is `[]`) and required on `is_a` and `part_of`. `axiom` may
carry optional `code` (string) and `reference` (string). `is_a` and `part_of` carry
`edge: [child, parent]`. `sorry` carries `provenance`. A missing, ill-typed, or unknown key
for the rule is `MALFORMED`, with the key named in the message. `code` or `reference` on a
non-axiom step is `MALFORMED`.

Structural requirements, each with its own error code, checked in this order before any
rule runs:

1. `steps[*].id` unique (`DUPLICATE_STEP`).
2. Every premise names an *earlier* step (`UNKNOWN_STEP_REF` if absent, `STEP_ORDER` if
   later or self). Earlier-only references make cycles unrepresentable, so acyclicity
   needs no separate check.
3. Arity. `axiom` and `sorry` consume 0 premises, `is_a` and `part_of` consume exactly 1.
   A different count is `PREMISE_ARITY` carrying `expected` and `actual`.
4. Every identifier position is type-checked: `goal.subject`, `goal.term`, `goal.taxon`,
   each `steps[*].conclusion.{subject,term,taxon}`, each `steps[*].edge[0]` and
   `edge[1]`. Terms: `UNKNOWN_TERM`, `OBSOLETE_TERM` (carries `replaced_by` and
   `consider`), `ALT_ID_IN_KERNEL`. Subjects: `UNKNOWN_SUBJECT` (carries the elaborator's
   candidates when a symbol was ambiguous). Taxon: must match `NCBITaxon:<digits>` or it
   is `MALFORMED`. Qualifier: `UNKNOWN_QUALIFIER`, then `QUALIFIER_ASPECT_MISMATCH`
   against the term's namespace. These run for every step including an `axiom` whose
   matching annotation is in the store: an annotation at an obsolete term is kept by the
   loader but can never be cited. Goal errors carry `step: null`. A step without a usable
   string `id` is reported as `step: "#<position>"`, so `null` always means the goal.
5. `root` names a step (`UNKNOWN_STEP_REF`) whose conclusion equals `goal`
   (`ROOT_MISMATCH`).

`used` is the transitive premise closure of `root`, always a single chain because every
rule has at most one premise. `unused_steps` lists every step not in `used`, sorted. Every
step is checked regardless of use: an error in an unused step still rejects, because
`Proves` quantifies over every step. `sorry_count` counts `sorry` steps in `used`;
`unused_sorries` counts the rest. `sorries[]` lists every `sorry` step with a `used` flag,
because it is Phase B's work list.

`sorry.provenance` requires `method` (string), `inputs` (non-empty list of strings),
`parameters` (object), `claim` (string). Anything else is `SORRY_MALFORMED`. The kernel
treats `method` as opaque; the benchmark resolves it (§6).

### Rules

Four rules exist. A step naming any other rule is `UNKNOWN_RULE`. A rule consumes its
premise step's **stated** `conclusion`, whether or not that step checked; soundness is
unaffected because ACCEPTED requires every step error-free, and then every stated
conclusion equals its computed one by induction over the earlier-only premise order.

| Rule | Premise `s` | Conclusion | Side conditions |
|---|---|---|---|
| `axiom` | none | `P` | let `rows = store.matching(P)`; if the step names `code`, keep rows with that `code`; if it names `reference`, keep rows whose `references` tuple contains it; the step checks iff the surviving set is non-empty (`AXIOM_NOT_FOUND` otherwise). Both filters must hold on one row. `axioms` lists exactly the surviving rows |
| `is_a` | `s` concluding `(g, q, t1, tax, false)` | `(g, q, t2, tax, false)` | `edge[0] == s.conclusion.term` (`PREMISE_MISMATCH`); `s.conclusion.negated` is false (`NEGATED_PREMISE`); `Edge(t1, is_a, t2)` in the store (`EDGE_NOT_FOUND`, carrying the child's actual parents with relations); `namespace(t1) == namespace(t2)` (`NAMESPACE_CROSSED`); stated conclusion equals `(g, q, edge[1], tax, false)` (`CONCLUSION_MISMATCH`, carrying both) |
| `part_of` | as `is_a` | as `is_a` | as `is_a` with `Edge(t1, part_of, t2)` |
| `sorry` | none | `P` with `negated` false (`SORRY_NEGATED`) | `provenance` well-formed |

`regulates` and its two sub-relations are not rules. A step with `"rule": "regulates"` is
`UNKNOWN_RULE`; an `is_a` step citing an edge whose recorded relation is `regulates` is
`EDGE_NOT_FOUND` with the actual relation in the error.

The qualifier `part_of` (a cellular-component annotation, GAF column 4) and the relation
`part_of` (an ontology edge) share a name and nothing else. A `located_in` or `part_of`
qualifier propagates over `is_a` and `part_of` *relations* like any other qualifier; the
qualifier never changes along a chain. Propagation copies subject, qualifier, and taxon, so
a changed taxon is a `CONCLUSION_MISMATCH` and an axiom under the wrong taxon is
`AXIOM_NOT_FOUND` with the other-taxon rows as suggestions. There is no `TAXON_MISMATCH`:
a code no derivation can trigger is a code no test can exercise.

### Checking

`check(derivation, store) -> Verdict` checks every step, in order, and does not stop at
the first failure. Per-step precedence: if a step is `MALFORMED`, names an unknown rule, or
its stated conclusion fails identifier *resolution* (`UNKNOWN_SUBJECT`, `UNKNOWN_TERM`,
`OBSOLETE_TERM`, `ALT_ID_IN_KERNEL`, `UNKNOWN_QUALIFIER`, malformed taxon), no
rule-application error is raised for that step. `QUALIFIER_ASPECT_MISMATCH` does not
suppress rule application: every identifier resolved, so the rule's own checks are
meaningful, and a cross-namespace propagation reports both it and `NAMESPACE_CROSSED`. If a
premise step's stated conclusion is not a well-formed `Prop`, the consumer skips only
`PREMISE_MISMATCH`, `NEGATED_PREMISE`, and `CONCLUSION_MISMATCH`; its `edge` conditions
still run. A premise step that carried any error marks the consumer in `premise_failed`
(a sorted list of step ids in the verdict) and never itself produces an error on the
consumer. One broken axiom therefore yields exactly one error down a chain, and a chain
with two independent defects yields two.

```json
{
  "verdict": "REJECTED",
  "goal": {...},
  "steps_checked": 3,
  "sorry_count": 0,
  "unused_sorries": 1,
  "unused_steps": ["s3"],
  "premise_failed": [],
  "errors": [
    {"step": "s2", "code": "EDGE_NOT_FOUND",
     "message": "no is_a edge GO:0097193 -> GO:0006915",
     "expected": {"child": "GO:0097193", "relation": "is_a", "parent": "GO:0006915"},
     "actual": {"parents_of_child": [["is_a", "GO:0012501"], ["part_of", "GO:0006915"]]},
     "suggestions": [{"rule": "part_of", "edge": ["GO:0097193", "GO:0006915"]}]}
  ],
  "axioms": [{"step": "s1", "annotation": "gaf:3f9c1e7a20b4d6f8", "code": "IDA",
              "eco": "ECO:0000314", "references": ["PMID:12345678"]}],
  "sorries": [{"step": "s3", "used": false, "method": "m:deseq2", "inputs": ["GEO:GSE12345"]}],
  "conflicts": [{"step": "s2", "annotation": "gaf:a1b2c3d4e5f60718", "negated": true,
                 "code": "IDA", "at": "ancestor", "via": "GO:0008219"}],
  "elaboration": []
}
```

- `verdict` is `ACCEPTED` iff `errors` is empty. A `sorry` never causes rejection.
- `conflicts` is computed from the closure of the derivation. Let S+ be the terms of every
  step conclusion with `negated` false and S- the terms of every step conclusion with
  `negated` true. A conflict is a store annotation with the contradicted step's subject,
  qualifier, and taxon and (a) `negated` true at a term in S+ or at any `is_a`/`part_of`
  ancestor of one within namespace, or (b) `negated` false at a term in S- or at any
  `is_a`/`part_of` descendant of one within namespace. Regulates edges are never followed.
  Each annotation is listed once with `step` (the earliest contradicted step),
  `annotation`, `negated`, `code`, `at` in `{"term", "ancestor", "descendant"}`, and `via`
  (the conflicting row's term). Verdict-neutral in v1. This is the defeasibility seam.
- `axioms` lists the rows each `axiom` step matched after its filters, sorted by annotation
  id. With no filters that is every matching row, so a report never hides that a fact rests
  on IEA alone.
- Sorted collections and their keys: `errors` by (step index, code, message) with goal
  errors first; `axioms` by annotation id; `sorries` and `conflicts` by step **position**
  (the derivation's order, not the step id string — `conflicts` breaks ties by annotation);
  `unused_steps`, `premise_failed` by step id; `elaboration` by path;
  `suggestions` by (rule, edge); `actual.parents_of_child` by (relation, parent);
  `references` by string. Positional and never sorted: `edge`, each
  `parents_of_child` pair, `expected`, `inputs`. JSON is written `sort_keys=True`.

### Error codes

`MALFORMED`, `UNKNOWN_RULE`, `DUPLICATE_STEP`, `UNKNOWN_STEP_REF`, `STEP_ORDER`,
`PREMISE_ARITY`, `ROOT_MISMATCH`, `UNKNOWN_TERM`, `OBSOLETE_TERM`, `ALT_ID_IN_KERNEL`,
`UNKNOWN_SUBJECT`, `UNKNOWN_QUALIFIER`, `QUALIFIER_ASPECT_MISMATCH`, `AXIOM_NOT_FOUND`
(suggestions: the subject's annotations at that term under other qualifiers, at descendant
terms under the same qualifier, and at that term under another taxon), `EDGE_NOT_FOUND`,
`NAMESPACE_CROSSED`, `NEGATED_PREMISE`, `PREMISE_MISMATCH`, `CONCLUSION_MISMATCH`,
`SORRY_MALFORMED`, `SORRY_NEGATED`.

Every error carries `step`, `code`, `message`, and where meaningful `expected`, `actual`,
`suggestions`. Suggestions are computed from the store and are themselves well-formed step
fragments, so an agent could splice one in verbatim. `NAMESPACE_CROSSED` is a refinement
of the aspect check, not an independent soundness guard: a cross-namespace step also fails
`QUALIFIER_ASPECT_MISMATCH`, and both are reported.

## §4 — Fact store and elaborator

### `FactStore` protocol

Mirrors `bench/oracle.py`: a `Protocol`, a dict-backed `StaticFactStore` that holds all the
logic, and loaders that only fill it. Kernel tests run on hand-built stores.

```python
class FactStore(Protocol):
    def term(self, go_id: str) -> Term | None: ...
    def primary_id(self, go_id: str) -> str | None: ...          # alt_id -> primary; primary -> itself
    def parents(self, go_id: str) -> tuple[Edge, ...]: ...        # sorted by (relation, parent)
    def children(self, go_id: str) -> tuple[Edge, ...]: ...       # sorted by (relation, child)
    def annotations(self, subject: str) -> tuple[Annotation, ...]: ...   # sorted by id
    def matching(self, prop: Prop) -> tuple[Annotation, ...]: ...        # exact-field match, sorted
    def subject_for_symbol(self, symbol: str) -> tuple[str, ...]: ...    # all subjects, sorted
    def subject_exists(self, subject: str) -> bool: ...
    def subjects(self) -> tuple[str, ...]: ...                       # every annotated subject, sorted
```

`StaticFactStore` indexes on construction: term by id, alt_id to primary, edges both
directions, annotations by subject, annotations by `(subject, qualifier, term, taxon,
negated)`, subjects by symbol. It raises `ValueError` if two annotations share an id or if
any annotation's `term` is a known alt_id: the store cannot be built in a state the kernel
cannot reach.

`MaskedFactStore(base, hidden: frozenset[str])` implements `FactStore` for the benchmark.
It filters `annotations()` and `matching()` by annotation id, which is what the kernel's
`axioms`, `conflicts`, and `AXIOM_NOT_FOUND` suggestions read. `term`, `primary_id`,
`parents`, `children`, `subject_exists`, and `subject_for_symbol` delegate unmasked: the
subject universe is the whole file, so a subject whose every row is hidden still exists.
`subjects` also delegates unmasked.

### Loaders

- `obo.py::parse_go_basic(text) -> tuple[list[Term], list[Edge], LoadReport]`. Stanza
  parser over `[Term]` blocks; reads `id`, `name`, `namespace`, `alt_id`, `is_a`,
  `relationship`, `is_obsolete`, `replaced_by`, `consider`. `[Typedef]` stanzas are
  skipped and counted. Unknown relation names are counted under `unknown_relation` and the
  edge is kept, because the kernel rejects them by name anyway.
- `eco.py::parse_eco_mapping(text) -> tuple[dict[str, str], LoadReport]` over
  `gaf-eco-mapping.txt`; `Default` rows give the mapping; other rows are counted under
  `non_default_row` and ignored.
- `gaf.py::parse_gaf(lines, eco_map, primary_id: Callable[[str], str | None], terms:
  Callable[[str], Term | None]) -> tuple[list[Annotation], LoadReport]`. The two callables
  are the ontology seam; `load_store` passes the parsed OBO's. Per row, in order:
  comment lines skipped and counted; other than 17 columns is `bad_column_count`, dropped;
  qualifier parsed as `NOT|x` or `x`, unknown `x` is `unknown_qualifier`, dropped;
  column 13 with zero or more than two values is `bad_taxon_cardinality`, dropped; a taxon
  value that is not digits after its prefix is `bad_taxon_format`, dropped; two values is
  `multi_taxon`, kept; `term_raw = col5`, `term = primary_id(col5)` with
  `term_alt_id` counted when they differ; `primary_id` returning `None` keeps the row with
  `term = col5` and counts `term_not_in_ontology`; a term that resolves to an obsolete
  `Term` keeps the row and counts `term_obsolete`; an unmapped evidence code keeps the row
  with `eco = ""` and counts `eco_unmapped`. Byte-identical rows collapse to one
  annotation and each extra copy counts under `duplicate_row`; `parse_gaf` is the only
  layer that collapses, so a duplicate reaching the store is a defect.
- `store.py::load_store(snapshot_dir) -> tuple[StaticFactStore, dict]` reads the three
  files and returns the store plus the merged load report. The report is printed by the CLI
  and written next to any artifact the store produced.

`LoadReport` is a dict of integer counters, every key present even when zero, written
`sort_keys=True`.

### Elaborator

`elaborate.py::elaborate(derivation_json, store) -> tuple[dict, list[Elaboration]]` runs
before the kernel and rewrites identifiers only, at these positions: `goal.subject`,
`goal.term`, `goal.taxon`, `steps[*].conclusion.subject`, `steps[*].conclusion.term`,
`steps[*].conclusion.taxon`, `steps[*].edge[0]`, `steps[*].edge[1]`. The same raw string
rewrites identically at every position, because a rewrite is a lookup.

| Input | Rewrite | Reported as |
|---|---|---|
| a subject that is a bare symbol, e.g. `TP53`, with exactly one `UniProtKB:` id | that id | `SYMBOL_RESOLVED` |
| a symbol with several subjects | not rewritten; the kernel reports `UNKNOWN_SUBJECT` with the candidates | `SYMBOL_AMBIGUOUS` |
| a term that is an `alt_id` | its primary id | `ALT_ID_RESOLVED` |
| a taxon spelled `9606` or `taxon:9606` | `NCBITaxon:9606` | `TAXON_NORMALIZED` |
| an obsolete term, whatever its `replaced_by` | **not rewritten**; the kernel's `OBSOLETE_TERM` carries the replacement | none |

`Elaboration(path, kind, before, after)` where `path` is the JSON position, e.g.
`steps/1/edge/0`. The elaborator never guesses. An obsolete term is not silently replaced
because the replacement can change meaning and eight of the 34 obsolete-term population
triples have no replacement at all; the agent is told and resubmits. This is the lesson
from `resolve_method_ids`: normalization is a lookup or it is an error, never a search.

## §5 — Tactics

`tactics.py` is untrusted convenience over the kernel and the store. It is what makes
hypothesis generation *directed*: an agent can only be handed goals that are well-typed and
rule applications that would check. Annotations at obsolete terms are skipped by every
function here, as are annotations whose qualifier is illegal for the term's aspect (a
loaded pair can be skewed), with the skipped count in the returned report, so that
guarantee holds on a skewed load.

- `goals_for(subject, store, *, aspect=None) -> tuple[list[Goal], dict]`. Every
  proposition derivable for the subject: the upward closure of its non-negated annotations
  over `is_a` and `part_of` within namespace. Each `Goal` carries `prop`, `direct: bool`,
  and `depth: int`, the shortest distance over the diamond. Sorted by `(term, qualifier)`.
- `applicable(prop, store) -> list[dict]`. Rule applications that would conclude `prop`
  right now: an `axiom` fragment if matching annotations exist; one `is_a` or `part_of`
  fragment per child term at which the subject has a derivable proposition. Never a
  regulates edge. This is the `apply?` analogue.
- `prove(prop, store) -> dict | None`. The mechanical prover. Breadth-first over the union
  of `is_a` and `part_of` parents, started simultaneously from every direct non-negated
  annotation of the subject under the same qualifier and taxon, so the result is shortest
  across all starting points; ties broken by sorted term id at every expansion. Returns
  the shortest derivation as a checkable JSON document, or `None`. It is the gold baseline
  and the eligibility test in §6, and a test asserts that every derivation it emits is
  `ACCEPTED` by the kernel.

## §6 — Benchmark

Same footing as `bench/`: items are frozen files with provenance, the store is the scoring
oracle, adapters are `(prompt: str) -> str`, raw model output is retained and re-scorable,
and every rate ships with its denominator.

### Population

Rows of human GOA pass five filters, applied in this order, and a row is counted under
the first filter it fails: `negated` false (`negated`); qualifier in `{involved_in,
enables, located_in, part_of, is_active_in}` (`qualifier_out_of_scope`); evidence class
`experimental` or `high_throughput` (`evidence_class`); `object_type == "protein"`
(`object_type`); term is a known, primary, non-obsolete id (`term_not_in_ontology`,
`term_alt_id`, `term_obsolete`, measured 0 / 0 / 60 rows on the shipped pair). Only the
hidden fact must be in the population; the visible store is the whole file minus the
hidden rows, and the subject universe is the whole file.

Eligible triples are enumerated per track, sorted by `(subject, qualifier, term)`, then
sampled with `random.Random(seed).sample(triples, min(N, len(triples)))`. `coverage` prints
eligible and sampled counts per track and every drop reason.

### Hiding

Item construction takes `hide: Callable[[FactStore, Prop], frozenset[str]]` returning
annotation ids. Two hiders exist:

- `hide_exact(store, p)`: every row matching `(p.subject, p.qualifier, p.term, p.taxon,
  false)`, all evidence classes and codes. The prove track's hider.
- `hide_subtree(store, p)`: `hide_exact` at `p.term` and at every term from which `p.term`
  is reachable over any sequence of `is_a` and `part_of` edges walked downward with
  `children()`, the transitive closure of the union, the exact dual of the prover's upward
  walk. The hypothesize track's hider. NOT rows are never hidden.

Every item records `hidden` (sorted annotation ids), `hidden_dates` (sorted, one per hidden
row), `cut_date = min(hidden_dates)`, and `hidden_classes` (evidence class per hidden row).
Scoring an item uses `MaskedFactStore(store, hidden)`.

### Prove track

An item is a population triple `(subject, qualifier, term)` for which, after `hide_exact`,
`prove` still finds a derivation. Triples where it does not are counted under
`not_rederivable`. Items record the gold derivation and `gold_depth`.

Prompt (closed book, no store access, single shot):

```
Prove the following claim as a Biolean derivation.
Claim: TP53 (UniProtKB:P04637) involved_in apoptotic process (GO:0006915), human.
The direct annotation of this gene product to this term is not available to you. Derive
it from an annotation to a more specific term using the rules is_a and part_of.
Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only.
```

Both prompts end with one fixed `Format:` paragraph (`biolean/bench/render.py::FORMAT_BLOCK`)
that states the derivation JSON shape: the top-level keys, the five `Prop` keys, and one
line each for an `axiom`, a propagation, and a `sorry` step. It is part of the prompt,
identical for every item and both tracks, so a closed-book model is measured on the claim,
not on guessing a private schema.

Rows use the vocabulary of `bench/run.py` verbatim: `raw` retained on every row; `error`
(string or `None`) when the adapter raised or the prompt could not be rendered, with
`render_error` holding the render detail exactly as `_failure_row` does; `parsed` (bool),
whether the reply was a JSON object. A row with `error` set carries `None` for every score
field and is excluded from every denominator, counted as `n_errors`. A row with
`parsed: false` and no `error` stays in every denominator as a miss and contributes the
synthetic code `UNPARSED` to the histogram. The reconciliation identity
`n_rows == n_errors + n_unparsed + n_checked` is pinned by a test. Rows also retain `item`,
`track`, `model`, the item's `goal`, `hidden`, `hidden_classes`, `gold_depth` (prove rows),
and `items_manifest` (`{"release", "since"}` copied from the items' `manifest.json`), so
`rescore` and the release check need nothing but the row and the store.

The scorer never trusts the reply's `goal`. It reads the elaborated conclusion of the step
named by `root` and compares it field-wise to the item's `Prop`:

| Field | Meaning |
|---|---|
| `accepted` | verdict ACCEPTED |
| `goal_match` | the elaborated root conclusion equals the item's `Prop`; `None` when unparsed or `root` names no step |
| `goal_rewritten` | the reply's own `goal`, elaborated, differs from the item's `Prop`; counted in aggregates |
| `hit` | `accepted and goal_match and sorry_count == 0` |
| `hit_with_sorry` | `accepted and goal_match and sorry_count > 0` |
| `sorry_count`, `unused_sorries` | from the verdict |
| `depth` | propagation steps in the used chain (used steps minus the axiom), or `None` when rejected; comparable with `gold_depth`, which is the gold derivation's step count minus one |
| `error_codes` | sorted list of the `code` of every entry in `verdict.errors`, repeats kept; `["UNPARSED"]` for an unparsed reply; `[]` when accepted |

Aggregates: `hit_rate = hits / (n_rows - n_errors)`, `acceptance_rate`, `mean_depth` over
hits (`None` if no hits), hit rate by hidden-fact evidence class, hit rate by `gold_depth`
in buckets `1`, `2`, `3`, `4+` with bucket sizes, and two histograms keyed by code:
`error_items` (items whose `error_codes` contains the code; denominator `n_rows - n_errors`)
and `error_occurrences` (error records carrying the code; denominator `n_errors_total`).
`error_items` is the headline, since it is invariant to derivation length.

### Hypothesize track

An item is a population triple hidden with `hide_subtree`. At build time two checks run per
triple: `prove` over the masked store must return `None`, and a non-`None` result raises a
`BuildError` naming the triple and carrying the derivation, because the hider is injectable
and a wrong hider is a defect, not a dropped item; and a single-`sorry` derivation at the
goal with placeholder provenance must be ACCEPTED over the masked store, otherwise the
triple is counted once under `goal_not_statable[<CODE>]`, where `<CODE>` is the
alphabetically first code among the rejection's errors, alongside `goal_not_statable_total`,
and dropped.

Prompt:

```
No recorded annotation supports the following claim.
Claim: TP53 (UniProtKB:P04637) involved_in apoptotic process (GO:0006915), human.
Propose the computation that would establish it: a Biolean derivation whose root is a
sorry step with provenance naming the method, the input datasets, and parameters.
Answer with the JSON document only.
```

Per item, all format-compliance fields: `format_ok` (verdict ACCEPTED and the root step is
a `sorry`), `goal_match` (as above), `inputs_nonempty`, and `method_resolves`. The last
resolves the root sorry's `provenance.method` through `normalize_name` from
`bench/normalize.py`, an exact lookup, never `resolve_method_ids`; the row keeps `method`
verbatim and `method_normalized` (the `m:` id or `None`). The scorer takes `resolve:
Callable[[str], str | None] | None`; with `None` (no graph) both fields are `None`.
Aggregates: the four rates over items where the field is not `None`, `n_method_resolves_none`,
and `method_unresolved` as a sorted list of raw names with counts.

GAF records PMIDs and evidence codes, never datasets or `m:` ids, so no data-derived gold
exists for provenance, and a constant reply saturates every rate. The items manifest
records `"hypothesize_gold": null`; `score` prints this track under the heading
`format compliance only` with no `hit`, `hit_rate`, or `accepted` keys, never in the same
table as prove rates; a test asserts the two tracks' per-item key sets share only the row
vocabulary. The track's knowledge measure arrives with Phase B's `discharge`.

### Live cut

`--since YYYY-MM-DD` keeps an item iff `cut_date >= since`. The minimum is taken over
every hidden row of every evidence code, because IEA rows carry the pipeline-run date and
any max-or-exists rule would admit facts curated decades earlier as recent. Items removed
are counted under `excluded_by_since`; `since` is recorded in `manifest.json` and echoed
with every score. Without `--since`, `since` is `null` and the count is 0.

### Baselines

`biolean/bench/baselines.py`, dispatched by item track; a baseline on the wrong track is a
usage error.

- `gold` (prove): the mechanical prover over the masked store. The CI gate asserts
  `hit_rate == 1.0` on the fixture items.
- `random` (prove, store-informed by design): a seeded random visible annotation of the
  subject under the item's qualifier, a seeded random upward path of seeded random length,
  root at the path's end. Structurally valid, so accepted exactly when the end is the
  target. Its hit rate is the floor.
- `modal` (prove, gene-blind prior): fit at `bench build` over the full eligible
  enumeration before sampling and before any live cut, keyed on `(qualifier, goal term)`,
  counting every visible annotated proper descendant across eligible triples, ties by
  sorted term id, frozen as `modal.json` beside `manifest.json`. At answer time it takes
  the counts for the item's key with the item's own subject subtracted, emits an axiom at
  the modal descendant plus the shortest path to the target, and is accepted exactly when
  the subject has a visible annotation there. An empty leave-subject-out counter emits an
  axiom at the goal term itself, which is hidden, so the item is a counted miss. Measured on
  the shipped pair over 500 sampled prove items (seed 0, full population, leave-subject-out)
  it hits 52.8% (gold 100%, random 5.2%); a model that cannot beat it knows GO's
  shape, not the gene.
- `template` (hypothesize): a constant sorry-root reply with the item's claim, method
  `m:deseq2`, inputs `["GEO:GSE0"]`, empty parameters. It saturates every rate and is
  printed beside every model so the ceiling is visible.

`UNKNOWN` does not exist in this benchmark: every checked reply is accepted or rejected.
What can be undefined is `method_resolves` and `goal_match`, and each is `None`, never
`false`.

## §7 — Package layout and CLI

Implementation is two plans. Plan 1 delivers §1–§5, the fetchers, and the `fetch`,
`check`, `prove`, and `goals` subcommands. Plan 2 delivers §6 and the `bench`
subcommands. Plan 2 starts only when Plan 1's kernel tests are merged.

```
src/methods_graph/biolean/
  __init__.py
  props.py        Term, Edge, Annotation, Prop; qualifier→aspect table; evidence classes
  obo.py          parse_go_basic
  gaf.py          parse_gaf
  eco.py          parse_eco_mapping
  store.py        FactStore protocol, StaticFactStore, MaskedFactStore, load_store
  kernel.py       rules, check, Verdict — the only trusted file
  errors.py       error codes and the Error record
  elaborate.py    identifier normalization, reported
  tactics.py      goals_for, applicable, prove
  render.py       derivation → prose; verdict → text an agent reads
  bench/
    __init__.py
    items.py      population, hiders, prove/hypothesize items, sampling, live cut, modal fit
    render.py     item → prompt (claim text + the fixed FORMAT_BLOCK); reply → JSON object or None
    score.py      per-item scoring for both tracks, aggregates, histograms
    baselines.py  gold, random, modal, template
    run.py        load items, run an adapter (reused from methods_graph.bench.adapters),
                  retain raw output, rescore
src/methods_graph/fetch.py   + fetch_goa_human, fetch_go_basic, fetch_eco_mapping
tests/fixtures/biolean/      go-mini.obo, goa-mini.gaf, eco-mini.txt
tests/test_biolean_*.py
```

### Fetch and manifest

`mg biolean fetch --out snapshots/go` downloads `goa_human.gaf.gz` first, reads its
`!go-version:` header, downloads `go-basic.obo` from
`http://purl.obolibrary.org/obo/go/releases/<date>/go-basic.obo` at that release, and
downloads the ECO mapping from its PURL. Each fetcher has the shape of `fetch_stato`: an
`http_get` seam, `fetched_at` injected, a manifest entry with `url`, `sha256`, `version`
(the OBO `data-version`; the GAF `date-generated` and `go-version`). The ECO mapping entry's
`version` is `""` — the file carries no version string of its own — so its identity for
change detection is its `sha256`.
The manifest is `snapshots/go/snapshot.json` with the same shape `write_manifest` produces,
`created_at` plus `sources` keyed `goa_human`, `go_basic`, `gaf_eco_mapping`, written
`sort_keys=True`. The benchmark's `manifest.json` records the release it was built from as
read from the files themselves — the OBO header's `data-version` and the GAF header's
`date-generated` and `go-version` — because those headers are what `snapshot.json` copies
and a snapshot fetched by hand has no manifest. `bench run` and `bench score` refuse a store
whose file headers differ from the items' record.

### CLI

Under `mg biolean`. `--store DIR` defaults to `snapshots/go` everywhere it appears;
`--taxon` defaults to `NCBITaxon:9606` and accepts the spellings the elaborator does.

| Command | Does |
|---|---|
| `fetch --out snapshots/go` | download the three files, write the manifest |
| `check DERIVATION.json [--store DIR] [--render]` | elaborate, check, print the verdict JSON; `--render` prints prose instead |
| `prove "UniProtKB:P04637 involved_in GO:0006915" [--taxon T] [--store DIR]` | print the mechanical derivation, or `derivation: null` with a reason from negated_goal, unknown_term, obsolete_term, no_direct_annotations, no_path |
| `goals SUBJECT [--aspect P] [--taxon T] [--store DIR]` | print derivable propositions with direct/inferred flags and depth; subject must be a single token; a symbol resolving to one subject is used and reported; an ambiguous symbol exits 2 naming the candidates |
| `bench build --out biolean-bench [--store DIR] [--per-track N] [--seed S] [--since DATE]` | frozen items under `items/`, `manifest.json` with every count, `modal.json`; `--per-track` defaults to 500 |
| `bench coverage --items DIR` | prints `manifest.json` — the denominators — read before any score; `DIR` is the `build --out` directory |
| `bench run --model SPEC --items DIR --store DIR --out results.jsonl [--track T] [--limit N]` | run an adapter or baseline, retain raw output; `--track` is required for a baseline when the item set mixes tracks |
| `bench score --results results.jsonl --store DIR [--out FILE]` | re-derive scores from retained output |

Exit codes, via a `_BIOLEAN_EXIT` dict beside `_GUARDRAIL_EXIT` in `cli.py`:

| Exit | Meaning |
|---|---|
| 0 | `check` ACCEPTED; `prove` found a derivation; every other subcommand completed |
| 2 | usage error through `parser.error`, including a `--store` that is missing or lacks the three files, and a store whose release differs from the items' |
| 3 | `check` REJECTED, verdict still on stdout; `prove` found no derivation, counted reason still on stdout |

1 stays reserved for an uncaught exception and is never a verdict; the hypothesize
`BuildError` raises and so exits 1 by construction.

## §8 — Seams for what comes next

- **Phase B.** `Verdict.sorries` is the work list. A `discharge(sorry, provider)` function
  will call `KuzuMethodsGraphProvider.method_preconditions(method)` and turn a `sorry` into
  a `computed` rule application or a typed refusal. The kernel gains one rule and loses
  nothing; `sorry` stays for methods the graph does not know. The hypothesize track gets
  its knowledge measure from the same function.
- **Defeasibility.** `Verdict.conflicts` already lists contradicting annotations over the
  closure. The milestone adds a status (`STANDING` / `CONTESTED`) derived from it and, if
  the owner chooses, the NOT contrapositive as a fifth rule.
- **Slice 2, gene to disease.** New `Prop` variant, new loaders, new rules, and the Biolink
  predicate mapping. Kernel dispatch is by `rule` name, so slice-2 rules register beside
  the GO rules without editing them.
- **Other organisms.** `load_store` takes any GAF; the prompt's "human" comes from the
  item's taxon.

## §9 — Tests

Every test names the mutation that must make it fail. The plan states, per test, that the
mutation was applied and the test failed, and for kernel tests it records the mutant's
verdict. Rules that apply to every kernel test:

- A test that expects rejection asserts the specific `(step, code)` pair in `errors`,
  never the verdict string alone: the verdict is a disjunction over every check, and a
  removed side condition is masked by any other code that fires.
- A test that expects acceptance asserts `errors == []`.
- A field-presence test asserts the field's value.

### Fixture inventory

One inventory, hand-built as a `StaticFactStore` for kernel tests and written verbatim as
`tests/fixtures/biolean/go-mini.obo` and `goa-mini.gaf` for loader, tactic, and benchmark
tests, so every layer sees the same facts. It is asymmetric by construction:

- **Diamond with unequal depths:** `A is_a B`, `B is_a C`, `A part_of C`, `A part_of D`,
  `D is_a C`, with ids chosen so `B` sorts before `C` and `D`. Shortest `A → C` is depth 1
  by `part_of`; a recursive DFS over sorted parents takes `is_a B` first and a stack DFS
  takes `part_of D` first, and both return depth 2.
- **Two starting points at unequal distance:** a subject with direct annotations at `X` and
  `Y` under one qualifier, `X is_a Y is_a T`, `X` sorting before `Y`.
- **Mixed-relation chain** `C2 is_a C1 part_of T0` so the subtree hider's union closure
  differs from the union of two closures.
- One `regulates` edge within one namespace.
- One synthetic `part_of` edge from a molecular-function term into a biological-process
  term.
- One obsolete term with `replaced_by` and `consider`, carrying an experimental-code
  population-eligible annotation, and one obsolete term with neither.
- One `alt_id`, with a GAF row annotated to the alt_id.
- For one subject `g` and one target `t`: two non-identical rows at
  `(g, involved_in, t, NCBITaxon:9606, false)` with codes IDA and IEA; one row at the same
  `(g, t)` under `acts_upstream_of_or_within`; the fixture's NOT row at
  `(g, involved_in, t, NCBITaxon:9606, true)`; and a visible positive row at a descendant
  of `t`, so the prove item is rederivable.
- One row with two references in column 6; one row with two taxa in column 13; one row
  with zero taxa; one pair of byte-identical rows; one row with 16 columns; one row with an
  unknown qualifier.
- Two symbols that resolve to one subject each and one symbol shared by two subjects.
- Enough population-eligible prove triples (exactly 6) that `--per-track 3` is a strict
  sample, written to `goa-mini.gaf` in reverse `(subject, qualifier, term)` order.
- Every sorted verdict collection is pinned by at least one derivation whose insertion order
  differs from its sort order, so an unsorted mutant cannot pass by chance.

### Kernel

| Test | Asserts | Mutation |
|---|---|---|
| `test_regulates_edge_is_not_a_rule` | `UNKNOWN_RULE` on the step; mutant ACCEPTED | add `regulates` to the propagating rules |
| `test_is_a_step_citing_a_regulates_edge_is_edge_not_found_with_actual_relation` | `EDGE_NOT_FOUND` with `regulates` in `actual` | match edges by endpoints only |
| `test_part_of_across_namespaces_is_namespace_crossed` | `NAMESPACE_CROSSED` and `QUALIFIER_ASPECT_MISMATCH` both on the step | remove the namespace check |
| `test_negated_premise_cannot_propagate` | `NEGATED_PREMISE` on `s2` for both a `negated: false` and a `negated: true` stated conclusion; mutant accepts one | drop the negated side condition |
| `test_axiom_requires_the_exact_qualifier` | `AXIOM_NOT_FOUND` for `contributes_to` where only `enables` exists at an MF term; mutant ACCEPTED | match annotations on `(subject, term)` only |
| `test_axiom_with_code_requires_a_row_with_that_code` | `AXIOM_NOT_FOUND` naming `IDA` where only IEA exists | ignore `code` |
| `test_axiom_code_and_reference_must_be_on_one_row` | `AXIOM_NOT_FOUND` when the code is on one row and the reference on another | check the filters independently |
| `test_axiom_without_code_lists_every_matching_row` | `axioms` has both the IDA and IEA rows | return the first match |
| `test_axiom_at_obsolete_term_is_rejected_even_though_the_row_exists` | `OBSOLETE_TERM` on the axiom step, `replaced_by` populated | run identifier checks only when no row matches |
| `test_alt_id_reaching_the_kernel_is_an_error` | `ALT_ID_IN_KERNEL` at `conclusion.term` and, in a second derivation, at `edge[0]`; both ACCEPTED once replaced by the primary | resolve alt ids inside the kernel |
| `test_conclusion_must_equal_computed_conclusion` | `CONCLUSION_MISMATCH` carrying both props | trust the stated conclusion |
| `test_root_differing_only_in_qualifier_is_root_mismatch` | `ROOT_MISMATCH` | compare root on `term` only |
| `test_premise_after_use_is_step_order_not_a_hang` | `STEP_ORDER`, test completes | resolve premises against all steps |
| `test_is_a_with_no_premise_is_premise_arity` | `PREMISE_ARITY` expected 1 actual 0; mutant ACCEPTED | iterate premises instead of indexing exactly one |
| `test_axiom_with_a_premise_is_premise_arity` | `PREMISE_ARITY` expected 0 actual 1 | ignore premises on nullary rules |
| `test_every_error_is_reported_not_just_the_first` | two errors on two steps | return on first error |
| `test_one_broken_axiom_yields_one_error_down_a_chain` | exactly one error, `premise_failed == ["s2"]` | consume the computed conclusion |
| `test_dependent_step_is_still_checked_when_premise_failed` | `AXIOM_NOT_FOUND` on `s1` and `EDGE_NOT_FOUND` on `s2`; `s1` at a valid term with no row, `s2` at a same-namespace live term with no edge | skip steps whose premise failed |
| `test_obsolete_term_error_carries_replaced_by` | `replaced_by` and `consider` values | drop the field |
| `test_sorry_is_counted_and_does_not_reject` | `errors == []`, `sorry_count == 1` | treat `sorry` as an error |
| `test_unused_sorry_does_not_count_toward_sorry_count` | `sorry_count == 0`, `unused_sorries == 1`, `sorries[0].used is False` | count all sorry steps |
| `test_error_in_unused_step_still_rejects` | `UNKNOWN_TERM` on an unused step, REJECTED | check used steps only |
| `test_sorry_with_missing_inputs_is_malformed` | `SORRY_MALFORMED` | accept any provenance object |
| `test_sorry_negated_is_rejected` | `SORRY_NEGATED` | allow negated sorry |
| `test_sorry_at_unknown_subject_is_unknown_subject` | `UNKNOWN_SUBJECT` | skip subject check for sorry |
| `test_conflict_at_the_term_is_listed_without_changing_the_verdict` | `errors == []`, conflict with `at == "term"` | let conflicts reject |
| `test_conflict_at_an_ancestor_is_listed` | conflict with `at == "ancestor"` and `via` | look up the exact term only |
| `test_conflict_at_a_descendant_of_a_negated_conclusion_is_listed` | `at == "descendant"` | skip the S- side |
| `test_unused_steps_are_reported` | `unused_steps == ["s3"]` | drop the field |
| `test_report_collections_are_sorted_by_their_declared_keys` | every sorted collection equals its sorted form | emit any collection in insertion order |
| `test_verdict_matches_committed_golden` | byte equality with `tests/fixtures/biolean/golden_verdict.json` | any change to the report shape |
| `test_taxon_must_be_ncbitaxon_curie` | `MALFORMED` for `"human"` | accept any string |

### Loaders and store

| Test | Mutation |
|---|---|
| `test_obo_alt_id_maps_to_primary_and_primary_maps_to_itself` | skip `alt_id` lines |
| `test_obo_obsolete_term_keeps_replaced_by_and_consider` | drop either field |
| `test_obo_typedef_stanzas_are_skipped_and_counted` | parse them as terms |
| `test_gaf_not_qualifier_sets_negated_and_strips_prefix` | keep `NOT\|` in qualifier |
| `test_gaf_bad_column_count_is_counted_and_dropped` | pad or truncate silently |
| `test_gaf_unknown_qualifier_is_counted_and_dropped` | keep the row |
| `test_gaf_alt_id_term_is_canonicalized_and_counted` | keep col5 verbatim |
| `test_gaf_term_not_in_ontology_is_kept_and_counted` | drop the row |
| `test_gaf_obsolete_term_row_is_kept_and_counted` | drop the row, or do not count |
| `test_gaf_first_taxon_is_normalized_and_second_retained` | keep `taxon:9606\|taxon:562` verbatim |
| `test_gaf_bad_taxon_cardinality_is_counted_and_dropped` | keep the row |
| `test_gaf_duplicate_rows_are_collapsed_and_counted` | index without counting; keep both |
| `test_gaf_two_references_are_split` | keep the raw column |
| `test_eco_mapping_default_rows_win` | take the last row per code (the fixture carries a non-`Default` row after the `Default` one) |
| `test_annotation_id_is_stable_across_loads_and_row_order` | derive the id from position |
| `test_load_report_has_every_key_even_when_zero` | emit only non-zero counters |
| `test_store_rejects_duplicate_ids_and_alt_id_terms` | construct silently |
| `test_masked_store_hides_only_the_listed_ids` | hide by `(subject, term)` |
| `test_masked_store_keeps_a_fully_hidden_subject_visible` | derive `subject_exists` from filtered annotations |

### Elaborator and tactics

| Test | Mutation |
|---|---|
| `test_ambiguous_symbol_is_not_resolved` | pick the first candidate |
| `test_obsolete_term_is_not_silently_replaced` | rewrite to `replaced_by` |
| `test_every_rewrite_is_reported_with_its_path` | rewrite without appending, or omit the path |
| `test_edge_endpoints_are_elaborated` | walk conclusions only |
| `test_goals_exclude_negated_annotations` | include them |
| `test_goals_skip_obsolete_term_annotations_and_count_them` | include them |
| `test_goals_depth_is_shortest_over_the_diamond` | depth-first over sorted parents in either order, take the first path |
| `test_prove_returns_the_shortest_derivation` | same |
| `test_prove_is_shortest_over_all_direct_annotations` | search from each direct annotation in sorted order and return the first success |
| `test_prove_tie_break_is_sorted_term_id` | tie-break by insertion order |
| `test_prove_output_is_accepted_by_the_kernel` | emit a step with a stale conclusion |
| `test_applicable_never_suggests_a_regulates_edge` | include all parent edges |

### Benchmark

| Test | Mutation |
|---|---|
| `test_population_filters_count_the_first_failure_in_order` | count every failure, or reorder |
| `test_population_excludes_obsolete_terms` | drop the filter; asserts on the hypothesize eligible set and `term_obsolete == 1`, since the prove track excludes the triple anyway |
| `test_prove_item_hides_only_the_exact_rows` | hide by `(subject, term)`; asserts the other-qualifier row and the NOT row are still visible and both IDA and IEA rows are hidden |
| `test_not_rederivable_triples_are_counted_not_dropped_silently` | drop without counting |
| `test_hypothesize_subtree_is_closure_of_the_union` | compute is_a-closure ∪ part_of-closure |
| `test_hypothesize_never_hides_not_rows` | hide by term only |
| `test_hypothesize_still_derivable_raises_build_error` | injects `hide_exact` into the hypothesize builder; drop quietly |
| `test_hypothesize_goal_not_statable_is_counted_with_its_code` | drop quietly |
| `test_gold_hits_every_prove_item` | gold uses the hidden rows |
| `test_hit_requires_goal_match_and_zero_used_sorries` | count `hit_with_sorry` as `hit`; compare to the reply's goal |
| `test_goal_rewritten_is_counted` | ignore the reply's goal entirely |
| `test_scorer_uses_the_masked_store` | score against the unmasked store |
| `test_rows_reconcile` | `n_rows == n_errors + n_unparsed + n_checked` |
| `test_unparsed_reply_is_a_miss_with_unparsed_code` | exclude it from the denominator |
| `test_adapter_error_row_is_excluded_and_counted` | score it as a miss |
| `test_method_resolves_is_none_without_a_graph` | default to `False` |
| `test_method_is_resolved_by_exact_lookup_not_search` | use `resolve_method_ids` |
| `test_hypothesize_rows_carry_no_hit_keys` | emit `hit` for hypothesize items |
| `test_template_baseline_scores_one_on_every_hypothesize_rate` | make any rate depend on item content |
| `test_live_cut_uses_min_hidden_date` | use max, or any |
| `test_sampling_is_seeded_and_sorted_first` | builds twice from forward and reversed rows, same seed, asserts identical 3-of-6 lists; a second seed differs |
| `test_modal_is_fit_before_sampling_and_leaves_the_subject_out` | fit on the sample, or include the subject |
| `test_random_baseline_is_structurally_valid` | emit a path with a missing edge |
| `test_error_histograms_count_items_and_occurrences` | fixture has one item with two occurrences of one code and one of another |
| `test_run_and_score_refuse_a_mismatched_store_release` | skip the check |
| `test_rescore_reproduces_scores_from_the_row_alone` | read the item file |

### CLI

One test per subcommand over the fixture store, asserting exit code and that output JSON is
sorted. `check` on a rejected fixture derivation asserts 3 (mutation: map REJECTED to 1);
a missing `--store` asserts 2. `fetch` is tested with an injected `http_get` that serves a
GAF header naming a release and asserts the OBO URL requested carries that release; it
never touches the network.

Scale check, DB-free, runs on the real snapshot when present and skips otherwise, so it is
not a CI gate: load time under 30 s, `prove` over 1,000 sampled population triples with
every derivation accepted. A second snapshot-gated check, `tests/test_biolean_bench_scale.py`,
builds the benchmark over a 300-subject slice (118 annotated subjects on the shipped pair)
with `--per-track 100` and asserts that every manifest counter reconciles, `gold` hits every
prove item, `modal` is accepted exactly when it hits, `random` fails only by `ROOT_MISMATCH`,
and `template` saturates `format_ok`; it bounds the build, not the load, at 120 s.

## Risks

- **Contamination.** GOA is in every training set. The live cut mitigates; it does not
  remove the risk. Report the cutoff with every number.
- **Structure prior.** The modal baseline hits 52.8% of prove items closed-book on the shipped pair. Every
  score is printed beside it; a model below it is reporting GO's shape.
- **Shallow items.** Depth is on every item and hit rate is reported by depth with bucket
  sizes so a one-hop-only model is visible.
- **Cosmetic rejections.** The kernel is exact. The elaborator absorbs symbols, alt ids,
  and taxon spellings, and reports each. Watch `error_items` for a code that dominates for
  spelling reasons.
- **Release drift.** The population and denominators change with every GOA release; the
  manifest pins the pair and items are frozen.
