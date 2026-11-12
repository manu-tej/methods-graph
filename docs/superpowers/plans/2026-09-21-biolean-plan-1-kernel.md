# Biolean Plan 1 — Facts, Kernel, Elaborator, Tactics, CLI

> **Status as of 2026-09-22: implemented and merged in `7bc79ef` (2026-09-21).** None of the 88 step checkboxes was ticked, but every task landed. Plan 2's prep refactor (`c732c6b`) then changed `kernel.py` (one propagation predicate) and `FactStore` (`subjects()`).
>
> As-built reference: [`docs/biolean/README.md`](../../biolean/README.md). Spec-level divergences are listed in the banner of [`specs/2026-09-21-biolean-design.md`](../specs/2026-09-21-biolean-design.md). Plan-specific ones:
>
> - The final task's `test_real_snapshot_loads_fast_and_the_prover_is_sound_over_a_sample` (`tried == accepted >= 200`, unmasked) was replaced by `test_real_snapshot_loads_fast_and_the_prover_is_sound_under_masking` (`39d0263`). The unmasked version only ever exercised 1-step axiom derivations.
> - The local `snapshots/go/` was not produced by the `mg biolean fetch` this plan builds. It is a release-skewed pair with no `snapshot.json`.
> - "`kernel.py` is the only trusted file" holds only for its direct imports. It imports `store`, which pulls in `obo`, `gaf` and `eco`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A checker that accepts or rejects an LLM-emitted derivation of a GO claim against GO + GOA facts, with typed errors, plus the loaders, elaborator, mechanical prover, fetchers, and `mg biolean fetch|check|prove|goals`.

**Architecture:** Pure-data records (`props.py`) are filled by stdlib parsers (`obo.py`, `gaf.py`, `eco.py`) into an in-memory `StaticFactStore` behind a `FactStore` protocol. `kernel.py` is the only trusted file: it validates a derivation's structure and identifiers, applies four rules (`axiom`, `is_a`, `part_of`, `sorry`), and returns a fully sorted verdict. `elaborate.py` normalizes identifiers before the kernel and reports every rewrite; `tactics.py` is the untrusted prover and goal enumerator over the same store.

**Tech Stack:** Python 3.12+ stdlib only (`dataclasses`, `hashlib`, `gzip`, `csv`-free tab splitting, `collections.deque`, `re`, `json`, `urllib`). No new runtime dependencies. pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-biolean-design.md` (§1–§5, §7 fetch and CLI, §9 kernel/loader/elaborator/tactics/CLI tests). Plan 2 covers §6.

## Global Constraints

- No new runtime dependencies: `pyproject.toml` stays `kuzu==0.11.3`, `polars`, `pyyaml`, `networkx`. The kernel and every loader here use stdlib only; `rdflib` is never imported.
- Determinism: sort every set iteration; every collection in a verdict is sorted by the key §3 names; JSON written `sort_keys=True`; no `datetime.now()` inside pure functions (timestamps are injected).
- Nothing dropped silently: every parser returns a `LoadReport` dict with **every key present even when zero**.
- Network takes an injectable `http_get` seam (signature `(url: str) -> tuple[bytes, dict[str, str]]`, as in `fetch_stato`); no test hits the network or spawns a process.
- The suite must pass with `OPENAI_API_KEY` unset: `env -u OPENAI_API_KEY $PYTEST -q`.
- Identifier discipline: `m:` ids are exact lookups, never `resolve_method_ids`; GO ids reach the kernel as primary ids only.
- Undefined is `None`, never `0.0` or `False`.
- Test discipline: before accepting a test, apply the mutation its row in the spec names and confirm the test fails; record "mutation checked" in the commit body. Kernel tests that expect rejection assert the `(step, code)` pair, never the verdict string alone; tests that expect acceptance assert `errors == []`.
- Run tests as `$PYTEST` where, in the main checkout, `PYTEST=".venv/bin/python -m pytest"` and, in a worktree without its own venv, `PYTEST="env PYTHONPATH=src <main-checkout>/.venv/bin/python -m pytest"` (the editable install points at the main checkout's `src`; `PYTHONPATH=src` makes the worktree's package win, verify with `python -c "import methods_graph; print(methods_graph.__file__)"`).
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- The spec deviates in one place from what this plan implements, deliberately: `Term` gains `alt_ids: tuple[str, ...]` (the OBO stanza owns its alt ids, and `StaticFactStore` needs them to build `primary_id`). Task 1 updates the spec's `Term` block.

## File structure

| File | Responsibility |
|---|---|
| `src/methods_graph/biolean/__init__.py` | package marker, one-line docstring |
| `src/methods_graph/biolean/props.py` | `Term`, `Edge`, `Annotation`, `Prop`; qualifier→aspect table; evidence classes; taxon normalization |
| `src/methods_graph/biolean/obo.py` | `parse_go_basic(text)` |
| `src/methods_graph/biolean/eco.py` | `parse_eco_mapping(text)` |
| `src/methods_graph/biolean/gaf.py` | `parse_gaf(lines, eco_map, primary_id, term)` |
| `src/methods_graph/biolean/store.py` | `FactStore` protocol, `StaticFactStore`, `MaskedFactStore`, `load_store` |
| `src/methods_graph/biolean/errors.py` | `Code` constants, `Error` record |
| `src/methods_graph/biolean/kernel.py` | `check(derivation, store)`, `ancestors`, `descendants` — the only trusted file |
| `src/methods_graph/biolean/elaborate.py` | `elaborate`, `elaborate_and_check` |
| `src/methods_graph/biolean/tactics.py` | `goals_for`, `applicable`, `prove` |
| `src/methods_graph/biolean/render.py` | `render_derivation`, `render_verdict` |
| `src/methods_graph/fetch.py` (modify) | `fetch_goa_human`, `fetch_go_basic`, `fetch_eco_mapping`, `write_biolean_manifest`, `fetch_biolean` |
| `src/methods_graph/cli.py` (modify) | `biolean` subparser, `cmd_biolean`, `_BIOLEAN_EXIT` |
| `tests/fixtures/biolean/go-mini.obo`, `goa-mini.gaf`, `eco-mini.txt`, `golden_verdict.json` | the one fixture inventory (§9) |
| `tests/test_biolean_props.py`, `_obo.py`, `_eco.py`, `_gaf.py`, `_store.py`, `_kernel.py`, `_elaborate.py`, `_tactics.py`, `_render.py`, `_fetch.py`, `_cli.py` | one test module per source module |
| `tests/biolean_fixture.py` | `mini_store()` builder shared by every test module (imported, not a conftest) |

---

### Task 1: Records and tables (`props.py`)

**Files:**
- Create: `src/methods_graph/biolean/__init__.py`
- Create: `src/methods_graph/biolean/props.py`
- Test: `tests/test_biolean_props.py`
- Modify: `docs/superpowers/specs/2026-09-21-biolean-design.md` (the `Term` block in §1 gains `alt_ids`)

**Interfaces:**
- Produces: `Term(id, name, namespace, obsolete, replaced_by, consider, alt_ids)`, `Edge(child, relation, parent)`, `Annotation(...)` with the 19 fields of §1 plus `term_raw` and `interacting_taxon`, `Prop(subject, qualifier, term, taxon, negated)` with `Prop.from_dict(d) -> Prop | None` and `Prop.to_dict()`, constants `QUALIFIER_ASPECT`, `ASPECT_NAMESPACE`, `NAMESPACE_ASPECT`, `EVIDENCE_CLASS`, `PROPAGATING_RELATIONS`, `TAXON_RE`, functions `normalize_taxon(raw) -> str | None`, `evidence_class(code) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_props.py`:

```python
from methods_graph.biolean.props import (
    ASPECT_NAMESPACE, EVIDENCE_CLASS, NAMESPACE_ASPECT, PROPAGATING_RELATIONS,
    QUALIFIER_ASPECT, TAXON_RE, Prop, evidence_class, normalize_taxon)


def test_thirteen_qualifiers_cover_the_three_aspects():
    assert len(QUALIFIER_ASPECT) == 13
    assert set(QUALIFIER_ASPECT.values()) == {"F", "P", "C"}
    assert QUALIFIER_ASPECT["part_of"] == "C"          # the qualifier, not the relation
    assert QUALIFIER_ASPECT["enables"] == "F"
    assert QUALIFIER_ASPECT["acts_upstream_of_or_within_negative_effect"] == "P"


def test_namespace_tables_are_inverses():
    assert {NAMESPACE_ASPECT[v] for v in ASPECT_NAMESPACE.values()} == {"F", "P", "C"}


def test_evidence_classes_cover_every_gaf_code_and_nothing_else():
    assert evidence_class("IDA") == "experimental"
    assert evidence_class("HDA") == "high_throughput"
    assert evidence_class("IBA") == "phylogenetic"
    assert evidence_class("ISS") == "computational"
    assert evidence_class("TAS") == "author_statement"
    assert evidence_class("ND") == "curatorial"
    assert evidence_class("IEA") == "electronic"
    assert evidence_class("XYZ") == "unknown"
    assert len(EVIDENCE_CLASS) == 26


def test_regulates_family_is_not_propagating():
    assert PROPAGATING_RELATIONS == ("is_a", "part_of")


def test_normalize_taxon_accepts_three_spellings_and_rejects_words():
    assert normalize_taxon("9606") == "NCBITaxon:9606"
    assert normalize_taxon("taxon:9606") == "NCBITaxon:9606"
    assert normalize_taxon("NCBITaxon:9606") == "NCBITaxon:9606"
    assert normalize_taxon("human") is None
    assert normalize_taxon("") is None
    assert TAXON_RE.match("NCBITaxon:9606") and not TAXON_RE.match("taxon:9606")


def test_prop_from_dict_requires_exactly_five_typed_fields():
    good = {"subject": "UniProtKB:P00001", "qualifier": "involved_in",
            "term": "GO:0000010", "taxon": "NCBITaxon:9606", "negated": False}
    p = Prop.from_dict(good)
    assert p == Prop("UniProtKB:P00001", "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    assert p.to_dict() == good
    assert Prop.from_dict({**good, "extra": 1}) is None
    assert Prop.from_dict({k: v for k, v in good.items() if k != "taxon"}) is None
    assert Prop.from_dict({**good, "negated": "false"}) is None
    assert Prop.from_dict("not a dict") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_props.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean'`

- [ ] **Step 3: Write the implementation**

`src/methods_graph/biolean/__init__.py`:

```python
"""Biolean: a structural proof checker for biological claims over GO + GOA facts."""
```

`src/methods_graph/biolean/props.py`:

```python
"""Facts and propositions of the GO slice. Pure data, no I/O, no store.

Every table here is the GAF 2.2 specification's or GO's documented grouping. They are
constants because the specification is; the code→ECO mapping is NOT here because it is
data (``eco.py`` reads the published file).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# GAF 2.2 column-4 qualifiers and the aspect each is legal for.
QUALIFIER_ASPECT: dict[str, str] = {
    "enables": "F",
    "contributes_to": "F",
    "involved_in": "P",
    "acts_upstream_of": "P",
    "acts_upstream_of_positive_effect": "P",
    "acts_upstream_of_negative_effect": "P",
    "acts_upstream_of_or_within": "P",
    "acts_upstream_of_or_within_positive_effect": "P",
    "acts_upstream_of_or_within_negative_effect": "P",
    "located_in": "C",
    "part_of": "C",
    "is_active_in": "C",
    "colocalizes_with": "C",
}

ASPECT_NAMESPACE: dict[str, str] = {
    "F": "molecular_function",
    "P": "biological_process",
    "C": "cellular_component",
}
NAMESPACE_ASPECT: dict[str, str] = {v: k for k, v in ASPECT_NAMESPACE.items()}

_EVIDENCE_GROUPS: dict[str, str] = {
    "experimental": "EXP IDA IPI IMP IGI IEP",
    "high_throughput": "HTP HDA HMP HGI HEP",
    "phylogenetic": "IBA IBD IKR IRD",
    "computational": "ISS ISO ISA ISM IGC RCA",
    "author_statement": "TAS NAS",
    "curatorial": "IC ND",
    "electronic": "IEA",
}
EVIDENCE_CLASS: dict[str, str] = {
    code: cls for cls, codes in _EVIDENCE_GROUPS.items() for code in codes.split()
}

# The only relations over which a gene-product annotation propagates upward.
PROPAGATING_RELATIONS: tuple[str, ...] = ("is_a", "part_of")

TAXON_RE = re.compile(r"^NCBITaxon:\d+$")


def normalize_taxon(raw: str) -> str | None:
    """``9606`` | ``taxon:9606`` | ``NCBITaxon:9606`` → ``NCBITaxon:9606``; ``None`` otherwise."""
    s = raw.strip()
    for prefix in ("NCBITaxon:", "taxon:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return f"NCBITaxon:{s}" if s.isdigit() else None


def evidence_class(code: str) -> str:
    return EVIDENCE_CLASS.get(code, "unknown")


@dataclass(frozen=True)
class Term:
    id: str
    name: str
    namespace: str
    obsolete: bool
    replaced_by: tuple[str, ...]
    consider: tuple[str, ...]
    alt_ids: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    child: str
    relation: str
    parent: str


@dataclass(frozen=True)
class Annotation:
    id: str
    subject: str
    symbol: str
    qualifier: str
    negated: bool
    term: str
    term_raw: str
    references: tuple[str, ...]
    code: str
    eco: str
    with_from: tuple[str, ...]
    aspect: str
    object_type: str
    taxon: str
    interacting_taxon: str
    date: str
    assigned_by: str
    extension: str
    form: str


_PROP_FIELDS: tuple[tuple[str, type], ...] = (
    ("subject", str), ("qualifier", str), ("term", str), ("taxon", str), ("negated", bool),
)


@dataclass(frozen=True)
class Prop:
    subject: str
    qualifier: str
    term: str
    taxon: str
    negated: bool

    @classmethod
    def from_dict(cls, d: Any) -> "Prop | None":
        """A well-formed proposition has exactly these five keys with these types."""
        if not isinstance(d, dict) or set(d) != {name for name, _ in _PROP_FIELDS}:
            return None
        for name, typ in _PROP_FIELDS:
            value = d[name]
            # bool is an int subclass; a string "false" or an int 0 is not a bool.
            if type(value) is not typ:
                return None
        return cls(d["subject"], d["qualifier"], d["term"], d["taxon"], d["negated"])

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "qualifier": self.qualifier, "term": self.term,
                "taxon": self.taxon, "negated": self.negated}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_props.py -q`
Expected: 6 passed

- [ ] **Step 5: Update the spec's `Term` block**

In `docs/superpowers/specs/2026-09-21-biolean-design.md` §1, add after `consider: tuple[str, ...]`:

```python
    alt_ids: tuple[str, ...]     # secondary ids that resolve to this term
```

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/__init__.py src/methods_graph/biolean/props.py tests/test_biolean_props.py docs/superpowers/specs/2026-09-21-biolean-design.md
git commit -m "feat(biolean): records, qualifier/aspect table, evidence classes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: OBO parser and the ontology fixture (`obo.py`)

**Files:**
- Create: `src/methods_graph/biolean/obo.py`
- Create: `tests/fixtures/biolean/go-mini.obo`
- Test: `tests/test_biolean_obo.py`

**Interfaces:**
- Consumes: `Term`, `Edge` from Task 1.
- Produces: `parse_go_basic(text: str) -> tuple[list[Term], list[Edge], dict[str, int]]`, terms sorted by id, edges sorted by `(child, relation, parent)`, report keys `term_stanzas`, `typedef_stanzas`, `other_stanzas`, `unknown_relation`, `edges`, `obsolete_terms`.

- [ ] **Step 1: Write the ontology fixture**

`tests/fixtures/biolean/go-mini.obo` — the §9 inventory. Diamond A→C with unequal depths (B sorts before C and D), two starting points X→Y→T, mixed chain C2 is_a C1 part_of T0, one regulates edge within BP, one synthetic MF→BP part_of, two obsolete terms, one alt_id:

```
format-version: 1.2
data-version: releases/2026-01-01
ontology: go-mini

[Term]
id: GO:0000005
name: B
namespace: biological_process
is_a: GO:0000010 ! C

[Term]
id: GO:0000010
name: C
namespace: biological_process
alt_id: GO:0000011

[Term]
id: GO:0000020
name: D
namespace: biological_process
is_a: GO:0000010 ! C

[Term]
id: GO:0000030
name: A
namespace: biological_process
is_a: GO:0000005 ! B
relationship: part_of GO:0000010 ! C
relationship: part_of GO:0000020 ! D

[Term]
id: GO:0000040
name: X
namespace: biological_process
is_a: GO:0000050 ! Y

[Term]
id: GO:0000050
name: Y
namespace: biological_process
is_a: GO:0000060 ! T

[Term]
id: GO:0000060
name: T
namespace: biological_process

[Term]
id: GO:0000070
name: T0
namespace: biological_process

[Term]
id: GO:0000080
name: C1
namespace: biological_process
relationship: part_of GO:0000070 ! T0

[Term]
id: GO:0000090
name: C2
namespace: biological_process
is_a: GO:0000080 ! C1

[Term]
id: GO:0000100
name: R
namespace: biological_process
relationship: regulates GO:0000010 ! C

[Term]
id: GO:0000110
name: obsolete old C
namespace: biological_process
is_obsolete: true
replaced_by: GO:0000010
consider: GO:0000020

[Term]
id: GO:0000120
name: obsolete orphan
namespace: biological_process
is_obsolete: true

[Term]
id: GO:0000200
name: MF1
namespace: molecular_function

[Term]
id: GO:0000210
name: MF2
namespace: molecular_function
is_a: GO:0000200 ! MF1
relationship: part_of GO:0000010 ! C

[Term]
id: GO:0000300
name: CC1
namespace: cellular_component

[Term]
id: GO:0000310
name: CC2
namespace: cellular_component
relationship: part_of GO:0000300 ! CC1
relationship: has_part GO:0000300 ! CC1

[Typedef]
id: part_of
name: part of
is_transitive: true

[Typedef]
id: regulates
name: regulates
```

Inventory this file pins (used by later tasks): 17 terms (15 live, 2 obsolete); is_a edges B→C, D→C, A→B, X→Y, Y→T, C2→C1, MF2→MF1; part_of edges A→C, A→D, C1→T0, MF2→C (cross-namespace), CC2→CC1; one regulates R→C; one `has_part` CC2→CC1 (unknown relation, kept and counted); alt_id GO:0000011 → GO:0000010.

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_obo.py`:

```python
from pathlib import Path

from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.props import Edge

FIXTURE = Path(__file__).parent / "fixtures" / "biolean" / "go-mini.obo"


def _parsed():
    return parse_go_basic(FIXTURE.read_text(encoding="utf-8"))


def test_terms_are_sorted_and_counted():
    terms, _, report = _parsed()
    assert [t.id for t in terms] == sorted(t.id for t in terms)
    assert report["term_stanzas"] == 17
    assert report["obsolete_terms"] == 2


def test_obo_alt_id_maps_to_primary_and_primary_maps_to_itself():
    terms, _, _ = _parsed()
    c = next(t for t in terms if t.id == "GO:0000010")
    assert c.alt_ids == ("GO:0000011",)
    assert all(t.alt_ids == () for t in terms if t.id != "GO:0000010")


def test_obo_obsolete_term_keeps_replaced_by_and_consider():
    terms, _, _ = _parsed()
    old = next(t for t in terms if t.id == "GO:0000110")
    assert old.obsolete is True
    assert old.replaced_by == ("GO:0000010",)
    assert old.consider == ("GO:0000020",)
    orphan = next(t for t in terms if t.id == "GO:0000120")
    assert orphan.obsolete is True and orphan.replaced_by == () and orphan.consider == ()


def test_obo_typedef_stanzas_are_skipped_and_counted():
    terms, _, report = _parsed()
    assert report["typedef_stanzas"] == 2
    assert not any(t.id in ("part_of", "regulates") for t in terms)


def test_edges_carry_relation_and_trailing_comments_are_stripped():
    _, edges, report = _parsed()
    assert Edge("GO:0000030", "part_of", "GO:0000010") in edges
    assert Edge("GO:0000005", "is_a", "GO:0000010") in edges
    assert Edge("GO:0000100", "regulates", "GO:0000010") in edges
    assert edges == sorted(edges, key=lambda e: (e.child, e.relation, e.parent))
    assert report["edges"] == len(edges) == 14


def test_unknown_relation_is_kept_and_counted():
    _, edges, report = _parsed()
    assert Edge("GO:0000310", "has_part", "GO:0000300") in edges
    assert report["unknown_relation"] == 1


def test_namespaces_and_names_are_read():
    terms, _, _ = _parsed()
    by_id = {t.id: t for t in terms}
    assert by_id["GO:0000210"].namespace == "molecular_function"
    assert by_id["GO:0000310"].namespace == "cellular_component"
    assert by_id["GO:0000030"].name == "A"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_obo.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.obo'`

- [ ] **Step 4: Write the implementation**

`src/methods_graph/biolean/obo.py`:

```python
"""OBO 1.2 flat-file parser for ``go-basic.obo``. Stdlib only.

Reads only what the kernel needs from a ``[Term]`` stanza: ``id``, ``name``, ``namespace``,
``alt_id``, ``is_a``, ``relationship``, ``is_obsolete``, ``replaced_by``, ``consider``.
Every other tag is ignored; every non-Term stanza is skipped and counted.
"""
from __future__ import annotations

from methods_graph.biolean.props import Edge, Term

KNOWN_RELATIONS = frozenset({
    "is_a", "part_of", "regulates", "positively_regulates", "negatively_regulates",
})

_REPORT_KEYS = (
    "term_stanzas", "typedef_stanzas", "other_stanzas", "unknown_relation", "edges",
    "obsolete_terms",
)


def _strip_comment(value: str) -> str:
    """``GO:0000010 ! C`` → ``GO:0000010``."""
    return value.split(" ! ", 1)[0].split("!", 1)[0].strip() if "!" in value else value.strip()


def parse_go_basic(text: str) -> tuple[list[Term], list[Edge], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    terms: list[Term] = []
    edges: list[Edge] = []

    stanza: str | None = None
    fields: dict[str, list[str]] = {}

    def flush() -> None:
        if stanza != "Term" or "id" not in fields:
            return
        term_id = fields["id"][0]
        obsolete = "true" in [v.lower() for v in fields.get("is_obsolete", [])]
        terms.append(Term(
            id=term_id,
            name=fields.get("name", [""])[0],
            namespace=fields.get("namespace", [""])[0],
            obsolete=obsolete,
            replaced_by=tuple(sorted(fields.get("replaced_by", []))),
            consider=tuple(sorted(fields.get("consider", []))),
            alt_ids=tuple(sorted(fields.get("alt_id", []))),
        ))
        if obsolete:
            report["obsolete_terms"] += 1
        for parent in fields.get("is_a", []):
            edges.append(Edge(term_id, "is_a", parent))
        for rel_line in fields.get("relationship", []):
            parts = rel_line.split()
            if len(parts) < 2:
                continue
            relation, parent = parts[0], parts[1]
            if relation not in KNOWN_RELATIONS:
                report["unknown_relation"] += 1
            edges.append(Edge(term_id, relation, parent))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            flush()
            stanza = line[1:-1]
            fields = {}
            if stanza == "Term":
                report["term_stanzas"] += 1
            elif stanza == "Typedef":
                report["typedef_stanzas"] += 1
            else:
                report["other_stanzas"] += 1
            continue
        if stanza != "Term" or not line or line.startswith("!"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields.setdefault(key.strip(), []).append(_strip_comment(value))
    flush()

    terms.sort(key=lambda t: t.id)
    edges = sorted(set(edges), key=lambda e: (e.child, e.relation, e.parent))
    report["edges"] = len(edges)
    return terms, edges, report
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_obo.py -q`
Expected: 7 passed

- [ ] **Step 6: Mutation check**

Temporarily change `alt_ids=tuple(sorted(fields.get("alt_id", [])))` to `alt_ids=()`; run the file; `test_obo_alt_id_maps_to_primary_and_primary_maps_to_itself` must fail. Revert. Temporarily make `flush` skip when `stanza == "Typedef"` is false (i.e. parse Typedefs as terms): `test_obo_typedef_stanzas_are_skipped_and_counted` must fail. Revert.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/obo.py tests/fixtures/biolean/go-mini.obo tests/test_biolean_obo.py
git commit -m "feat(biolean): go-basic.obo parser and the mini ontology fixture

Mutation checked: alt_id dropped, typedef parsed as term.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: ECO mapping parser (`eco.py`)

**Files:**
- Create: `src/methods_graph/biolean/eco.py`
- Create: `tests/fixtures/biolean/eco-mini.txt`
- Test: `tests/test_biolean_eco.py`

**Interfaces:**
- Produces: `parse_eco_mapping(text: str) -> tuple[dict[str, str], dict[str, int]]` with report keys `comment_lines`, `default_rows`, `non_default_row`, `bad_row`.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/biolean/eco-mini.txt` (tab-separated; the non-`Default` IDA row comes *after* the `Default` one on purpose):

```
# mini gaf-eco-mapping
EXP	Default	ECO:0000269
IDA	Default	ECO:0000314
IDA	GO_REF:0000001	ECO:9999999
IPI	Default	ECO:0000353
IMP	Default	ECO:0000315
IEA	Default	ECO:0000501
HDA	Default	ECO:0007005
IGI	Default	ECO:0000316
IEP	Default	ECO:0000270
malformed line without tabs
```

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_eco.py`:

```python
from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping

FIXTURE = Path(__file__).parent / "fixtures" / "biolean" / "eco-mini.txt"


def test_eco_mapping_default_rows_win():
    mapping, report = parse_eco_mapping(FIXTURE.read_text())
    assert mapping["IDA"] == "ECO:0000314"
    assert report["non_default_row"] == 1


def test_eco_mapping_counts_every_line_kind():
    mapping, report = parse_eco_mapping(FIXTURE.read_text())
    assert len(mapping) == 8
    assert report == {"comment_lines": 1, "default_rows": 8, "non_default_row": 1, "bad_row": 1}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_eco.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the implementation**

`src/methods_graph/biolean/eco.py`:

```python
"""Reader for the published ``gaf-eco-mapping.txt``: GAF evidence code → ECO id.

The mapping is data, fetched from ``http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt``,
never a constant in source. Only ``Default`` rows are used; the first ``Default`` row for a
code wins and every other kind of row is counted.
"""
from __future__ import annotations

_REPORT_KEYS = ("comment_lines", "default_rows", "non_default_row", "bad_row")


def parse_eco_mapping(text: str) -> tuple[dict[str, str], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            report["comment_lines"] += 1
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            report["bad_row"] += 1
            continue
        code, kind, eco = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if kind != "Default":
            report["non_default_row"] += 1
            continue
        report["default_rows"] += 1
        mapping.setdefault(code, eco)
    return mapping, report
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_eco.py -q`
Expected: 2 passed

- [ ] **Step 6: Mutation check**

Change `if kind != "Default": ... continue` so non-Default rows also write `mapping[code] = eco` (last row wins): `test_eco_mapping_default_rows_win` must fail. Revert.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/eco.py tests/fixtures/biolean/eco-mini.txt tests/test_biolean_eco.py
git commit -m "feat(biolean): GAF-to-ECO mapping reader

Mutation checked: last row per code.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 4: GAF parser and the annotation fixture (`gaf.py`)

**Files:**
- Create: `src/methods_graph/biolean/gaf.py`
- Create: `tests/fixtures/biolean/goa-mini.gaf`
- Test: `tests/test_biolean_gaf.py`

**Interfaces:**
- Consumes: `Annotation`, `QUALIFIER_ASPECT`, `normalize_taxon`, `Term` from Task 1.
- Produces: `parse_gaf(lines, eco_map, primary_id, term) -> tuple[list[Annotation], dict[str, int]]` where `primary_id: Callable[[str], str | None]` and `term: Callable[[str], Term | None]` are the ontology seam; annotations sorted by id; report keys `comment_lines`, `rows`, `bad_column_count`, `unknown_qualifier`, `bad_taxon_cardinality`, `bad_taxon_format`, `multi_taxon`, `duplicate_row`, `term_alt_id`, `term_not_in_ontology`, `term_obsolete`, `eco_unmapped`, `annotations`. Also `annotation_id(cols: list[str]) -> str`.

- [ ] **Step 1: Write the annotation fixture**

`tests/fixtures/biolean/goa-mini.gaf`. Seventeen tab-separated columns per data row. Rows are written in **reverse** `(subject, qualifier, term)` order on purpose (Plan 2's sampling test depends on it). Write the file with real tab characters; the table below is the content, one row per line, `⇥` marking a tab:

```
!gaf-version: 2.2
!generated-by: biolean-fixture
!date-generated: 2026-01-01
UniProtKB⇥P00009⇥DUP⇥involved_in⇥GO:0000030⇥GO_REF:0000002⇥IEA⇥⇥P⇥dup gene 2⇥⇥protein⇥taxon:9606⇥20260301⇥UniProt⇥⇥
UniProtKB⇥P00008⇥DUP⇥involved_in⇥GO:0000030⇥GO_REF:0000002⇥IEA⇥⇥P⇥dup gene 1⇥⇥protein⇥taxon:9606⇥20260301⇥UniProt⇥⇥
UniProtKB⇥P00007⇥GG⇥involved_in⇥GO:0009999⇥PMID:22⇥IDA⇥⇥P⇥gene G⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00007⇥GG⇥involved_in⇥GO:0000100⇥PMID:24⇥IDA⇥⇥P⇥gene G⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00007⇥GG⇥involved_in⇥GO:0000090⇥PMID:23⇥XYZ⇥⇥P⇥gene G⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00007⇥GG⇥involved_in⇥GO:0000090⇥PMID:21⇥IDA⇥⇥P⇥gene G⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00006⇥GF⇥involved_in⇥GO:0000011⇥PMID:20⇥IDA⇥⇥P⇥gene F⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00005⇥GE⇥involved_in⇥GO:0000110⇥PMID:19⇥IDA⇥⇥P⇥gene E⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00004⇥GD⇥located_in⇥GO:0000310⇥PMID:15⇥HDA⇥⇥C⇥gene D⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00004⇥GD⇥located_in⇥GO:0000310⇥PMID:15⇥HDA⇥⇥C⇥gene D⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00004⇥GD⇥binds⇥GO:0000310⇥PMID:16⇥IDA⇥⇥C⇥gene D⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00004⇥GD⇥located_in⇥GO:0000300⇥PMID:17⇥HDA⇥⇥C⇥gene D⇥⇥protein⇥⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00004⇥GD⇥located_in⇥GO:0000310⇥PMID:18⇥IDA⇥⇥C⇥gene D⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥
UniProtKB⇥P00003⇥GC⇥enables⇥GO:0000210⇥PMID:13⇥IPI⇥UniProtKB:Q0002⇥F⇥gene C⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00003⇥GC⇥enables⇥GO:0000210⇥PMID:11|PMID:12⇥IDA⇥⇥F⇥gene C⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00003⇥GC⇥enables⇥GO:0000200⇥PMID:14⇥IDA⇥⇥F⇥gene C⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00002⇥GB⇥involved_in⇥GO:0000060⇥PMID:10⇥IMP⇥⇥P⇥gene B⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00002⇥GB⇥involved_in⇥GO:0000050⇥PMID:9⇥IDA⇥⇥P⇥gene B⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00002⇥GB⇥involved_in⇥GO:0000040⇥PMID:8⇥IMP⇥⇥P⇥gene B⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00002⇥GB⇥NOT|involved_in⇥GO:0000040⇥PMID:25⇥IDA⇥⇥P⇥gene B⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000030⇥PMID:2⇥IPI⇥UniProtKB:Q0001⇥P⇥gene A⇥⇥protein⇥taxon:9606|taxon:562⇥20200102⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000030⇥PMID:1⇥IDA⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000020⇥PMID:7⇥IMP⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000010⇥GO_REF:0000002⇥IEA⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20260301⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000010⇥PMID:3⇥IDA⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20190101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥involved_in⇥GO:0000005⇥PMID:6⇥IDA⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥acts_upstream_of_or_within⇥GO:0000010⇥PMID:4⇥IMP⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
UniProtKB⇥P00001⇥GA⇥NOT|involved_in⇥GO:0000010⇥PMID:5⇥IDA⇥⇥P⇥gene A⇥⇥protein⇥taxon:9606⇥20200101⇥UniProt⇥⇥
```

What each odd row is for: the two `DUP` rows are the ambiguous symbol; `GO:0009999` is a term not in the ontology (kept, counted); `XYZ` is an unmapped evidence code (kept, `eco == ""`); `GO:0000011` is the alt_id of `GO:0000010` (canonicalized, counted); `GO:0000110` is obsolete (kept, counted); the two identical `P00004` rows collapse (counted); `binds` is an unknown qualifier (dropped, counted); the row with an empty taxon column is dropped (counted); the 16-column row is dropped (counted); `PMID:11|PMID:12` is the two-reference row; `taxon:9606|taxon:562` is the two-taxon row. For subject `P00001` and target `GO:0000010` (C): two rows at the exact proposition with codes IDA and IEA, one row at the same `(subject, term)` under `acts_upstream_of_or_within`, the fixture's NOT row, and visible rows at descendants A (`GO:0000030`), B, D.

Two rows exist only for kernel tests: `P00007 involved_in GO:0000100` (R, the term with the regulates edge, so a `regulates` step can otherwise be fully valid) and `P00002 NOT|involved_in GO:0000040` (a NOT at X, which has an `is_a` parent, so a negated premise can otherwise be fully valid). The fixture therefore has two NOT rows.

Expected report over this file: `comment_lines 3, rows 28, bad_column_count 1, unknown_qualifier 1, bad_taxon_cardinality 1, bad_taxon_format 0, multi_taxon 1, duplicate_row 1, term_alt_id 1, term_not_in_ontology 1, term_obsolete 1, eco_unmapped 1, annotations 24`.

- [ ] **Step 2: Write the failing tests**

`tests/test_biolean_gaf.py`:

```python
from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import annotation_id, parse_gaf
from methods_graph.biolean.obo import parse_go_basic

FIX = Path(__file__).parent / "fixtures" / "biolean"


def _ontology():
    terms, _, _ = parse_go_basic((FIX / "go-mini.obo").read_text(encoding="utf-8"))
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}

    def primary_id(go_id: str) -> str | None:
        return go_id if go_id in by_id else alt.get(go_id)

    return primary_id, by_id.get


def _parse(lines=None):
    eco_map, _ = parse_eco_mapping((FIX / "eco-mini.txt").read_text())
    primary_id, term = _ontology()
    if lines is None:
        lines = (FIX / "goa-mini.gaf").read_text(encoding="utf-8").splitlines()
    return parse_gaf(lines, eco_map, primary_id, term)


def test_report_has_every_key_and_the_fixture_counts():
    _, report = _parse()
    assert report == {
        "comment_lines": 3, "rows": 28, "bad_column_count": 1, "unknown_qualifier": 1,
        "bad_taxon_cardinality": 1, "bad_taxon_format": 0, "multi_taxon": 1,
        "duplicate_row": 1, "term_alt_id": 1, "term_not_in_ontology": 1,
        "term_obsolete": 1, "eco_unmapped": 1, "annotations": 24,
    }


def _rows(subject, qualifier=None, term=None, negated=None):
    anns, _ = _parse()
    return [a for a in anns if a.subject == subject
            and (qualifier is None or a.qualifier == qualifier)
            and (term is None or a.term == term)
            and (negated is None or a.negated == negated)]


def test_gaf_not_qualifier_sets_negated_and_strips_prefix():
    [row] = _rows("UniProtKB:P00001", negated=True)
    assert row.qualifier == "involved_in" and row.term == "GO:0000010"
    anns, _ = _parse()
    assert not any("NOT" in a.qualifier for a in anns)
    assert sum(a.negated for a in anns) == 2


def test_gaf_bad_column_count_is_counted_and_dropped():
    assert not any(a.references == ("PMID:18",) for a in _parse()[0])


def test_gaf_unknown_qualifier_is_counted_and_dropped():
    assert not any(a.qualifier == "binds" for a in _parse()[0])


def test_gaf_alt_id_term_is_canonicalized_and_counted():
    [row] = _rows("UniProtKB:P00006")
    assert row.term == "GO:0000010" and row.term_raw == "GO:0000011"


def test_gaf_term_not_in_ontology_is_kept_and_counted():
    [row] = _rows("UniProtKB:P00007", term="GO:0009999")
    assert row.term == row.term_raw == "GO:0009999"


def test_gaf_obsolete_term_row_is_kept_and_counted():
    [row] = _rows("UniProtKB:P00005")
    assert row.term == "GO:0000110"


def test_gaf_first_taxon_is_normalized_and_second_retained():
    [row] = [a for a in _rows("UniProtKB:P00001", term="GO:0000030") if a.code == "IPI"]
    assert row.taxon == "NCBITaxon:9606"
    assert row.interacting_taxon == "NCBITaxon:562"
    assert row.with_from == ("UniProtKB:Q0001",)
    [ida] = [a for a in _rows("UniProtKB:P00001", term="GO:0000030") if a.code == "IDA"]
    assert ida.interacting_taxon == ""


def test_gaf_bad_taxon_cardinality_is_counted_and_dropped():
    assert not any(a.term == "GO:0000300" for a in _rows("UniProtKB:P00004"))


def test_gaf_duplicate_rows_are_collapsed_and_counted():
    rows = _rows("UniProtKB:P00004", term="GO:0000310")
    assert len(rows) == 1 and rows[0].code == "HDA"


def test_gaf_two_references_are_split_and_sorted():
    [row] = [a for a in _rows("UniProtKB:P00003", term="GO:0000210") if a.code == "IDA"]
    assert row.references == ("PMID:11", "PMID:12")


def test_eco_is_mapped_and_unmapped_is_empty_string():
    by_code = {a.code: a for a in _rows("UniProtKB:P00007", term="GO:0000090")}
    assert by_code["IDA"].eco == "ECO:0000314"
    assert by_code["XYZ"].eco == ""


def test_date_is_iso_and_annotations_are_sorted_by_id():
    anns, _ = _parse()
    assert all(len(a.date) == 10 and a.date[4] == "-" for a in anns)
    assert [a.id for a in anns] == sorted(a.id for a in anns)


def test_annotation_id_is_stable_across_loads_and_row_order():
    lines = (FIX / "goa-mini.gaf").read_text(encoding="utf-8").splitlines()
    forward = {a.id: a for a in _parse(lines)[0]}
    header, data = lines[:3], lines[3:]
    backward = {a.id: a for a in _parse(header + list(reversed(data)))[0]}
    assert forward == backward
    cols = data[0].split("\t")
    assert annotation_id(cols).startswith("gaf:") and len(annotation_id(cols)) == 20
    assert annotation_id(cols) != annotation_id(cols[:-1] + ["x"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_gaf.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.gaf'`

- [ ] **Step 4: Write the implementation**

`src/methods_graph/biolean/gaf.py`:

```python
"""GAF 2.2 reader. Stdlib only; the ontology is an injected seam.

Filters apply in a fixed order and a row is counted under the first one it fails:
column count, qualifier, taxon cardinality, taxon format, duplicate. Term canonicalization
and the term/ECO counters never drop a row; the kernel refuses to cite what it must.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Iterable, Mapping

from methods_graph.biolean.props import QUALIFIER_ASPECT, Annotation, Term, normalize_taxon

_REPORT_KEYS = (
    "comment_lines", "rows", "bad_column_count", "unknown_qualifier",
    "bad_taxon_cardinality", "bad_taxon_format", "multi_taxon", "duplicate_row",
    "term_alt_id", "term_not_in_ontology", "term_obsolete", "eco_unmapped", "annotations",
)
_COLUMNS = 17


def annotation_id(cols: list[str]) -> str:
    """``gaf:`` + first 16 hex of sha256 over the raw columns joined by tab."""
    digest = hashlib.sha256("\t".join(cols).encode("utf-8")).hexdigest()
    return f"gaf:{digest[:16]}"


def _split_pipe(value: str) -> tuple[str, ...]:
    return tuple(sorted(v for v in value.split("|") if v))


def _iso_date(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}" if len(raw) == 8 and raw.isdigit() else raw


def parse_gaf(
    lines: Iterable[str],
    eco_map: Mapping[str, str],
    primary_id: Callable[[str], str | None],
    term: Callable[[str], Term | None],
) -> tuple[list[Annotation], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    seen: set[str] = set()
    out: list[Annotation] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line or line.startswith("!"):
            report["comment_lines"] += 1
            continue
        report["rows"] += 1
        cols = line.split("\t")
        if len(cols) != _COLUMNS:
            report["bad_column_count"] += 1
            continue
        qualifier = cols[3]
        negated = qualifier.startswith("NOT|")
        if negated:
            qualifier = qualifier[4:]
        if qualifier not in QUALIFIER_ASPECT:
            report["unknown_qualifier"] += 1
            continue
        taxa = [t for t in cols[12].split("|") if t]
        if len(taxa) not in (1, 2):
            report["bad_taxon_cardinality"] += 1
            continue
        normalized = [normalize_taxon(t) for t in taxa]
        if any(t is None for t in normalized):
            report["bad_taxon_format"] += 1
            continue
        ann_id = annotation_id(cols)
        if ann_id in seen:
            report["duplicate_row"] += 1
            continue
        seen.add(ann_id)
        if len(taxa) == 2:
            report["multi_taxon"] += 1

        term_raw = cols[4]
        primary = primary_id(term_raw)
        if primary is None:
            term_id = term_raw
            report["term_not_in_ontology"] += 1
        else:
            term_id = primary
            if primary != term_raw:
                report["term_alt_id"] += 1
            resolved = term(primary)
            if resolved is not None and resolved.obsolete:
                report["term_obsolete"] += 1

        eco = eco_map.get(cols[6], "")
        if not eco:
            report["eco_unmapped"] += 1

        out.append(Annotation(
            id=ann_id,
            subject=f"{cols[0]}:{cols[1]}",
            symbol=cols[2],
            qualifier=qualifier,
            negated=negated,
            term=term_id,
            term_raw=term_raw,
            references=_split_pipe(cols[5]),
            code=cols[6],
            eco=eco,
            with_from=_split_pipe(cols[7]),
            aspect=cols[8],
            object_type=cols[11],
            taxon=normalized[0] or "",
            interacting_taxon=(normalized[1] or "") if len(normalized) == 2 else "",
            date=_iso_date(cols[13]),
            assigned_by=cols[14],
            extension=cols[15],
            form=cols[16],
        ))
    out.sort(key=lambda a: a.id)
    report["annotations"] = len(out)
    return out, report
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_gaf.py -q`
Expected: 14 passed. If `test_report_has_every_key_and_the_fixture_counts` fails on a count, the fixture file was not written with real tabs or a row lost a column; fix the fixture, not the parser.

- [ ] **Step 6: Mutation checks**

Apply each, run the file, confirm the named test fails, revert:
- `term_id = term_raw` unconditionally → `test_gaf_alt_id_term_is_canonicalized_and_counted`.
- delete the `if ann_id in seen` block → `test_gaf_duplicate_rows_are_collapsed_and_counted`.
- keep `qualifier` with its `NOT|` prefix → `test_gaf_not_qualifier_sets_negated_and_strips_prefix`.
- `interacting_taxon=""` always → `test_gaf_first_taxon_is_normalized_and_second_retained`.
- `ann_id = f"gaf:{report['rows']}"` → `test_annotation_id_is_stable_across_loads_and_row_order`.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/gaf.py tests/fixtures/biolean/goa-mini.gaf tests/test_biolean_gaf.py
git commit -m "feat(biolean): GAF 2.2 reader with counted filters and the mini annotation fixture

Mutation checked: alt_id kept raw, duplicates kept, NOT kept in qualifier,
second taxon dropped, positional ids.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Fact store (`store.py`) and the shared fixture builder

**Files:**
- Create: `src/methods_graph/biolean/store.py`
- Create: `tests/biolean_fixture.py`
- Test: `tests/test_biolean_store.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `FactStore` protocol (§4 signatures), `StaticFactStore(terms, edges, annotations)`, `MaskedFactStore(base, hidden: frozenset[str])`, `load_store(snapshot_dir, *, obo="go-basic.obo", gaf="goa_human.gaf.gz", eco="gaf-eco-mapping.txt") -> tuple[StaticFactStore, dict[str, dict[str, int]]]`, and in tests `mini_store() -> StaticFactStore` plus `mini_report()`.

- [ ] **Step 1: Write the failing tests**

`tests/biolean_fixture.py`:

```python
"""The one fixture inventory, loaded from the three files under tests/fixtures/biolean."""
from pathlib import Path

from methods_graph.biolean.store import StaticFactStore, load_store

FIX = Path(__file__).parent / "fixtures" / "biolean"


def mini_store() -> StaticFactStore:
    store, _ = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return store


def mini_report() -> dict:
    _, report = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return report
```

`tests/test_biolean_store.py`:

```python
import pytest

from methods_graph.biolean.props import Annotation, Edge, Prop, Term
from methods_graph.biolean.store import MaskedFactStore, StaticFactStore
from tests.biolean_fixture import mini_report, mini_store

P1 = "UniProtKB:P00001"


def test_load_report_has_every_section_and_every_key_even_when_zero():
    report = mini_report()
    assert set(report) == {"obo", "eco", "gaf"}
    assert report["gaf"]["bad_taxon_format"] == 0
    assert report["obo"]["other_stanzas"] == 0


def test_primary_id_resolves_alt_and_identity_and_unknown():
    s = mini_store()
    assert s.primary_id("GO:0000011") == "GO:0000010"
    assert s.primary_id("GO:0000010") == "GO:0000010"
    assert s.primary_id("GO:0009999") is None
    assert s.term("GO:0000011") is None            # alt ids are not terms
    assert s.term("GO:0000010").name == "C"


def test_parents_and_children_are_sorted_and_carry_relations():
    s = mini_store()
    assert s.parents("GO:0000030") == (
        Edge("GO:0000030", "is_a", "GO:0000005"),
        Edge("GO:0000030", "part_of", "GO:0000010"),
        Edge("GO:0000030", "part_of", "GO:0000020"),
    )
    assert s.children("GO:0000010") == (
        Edge("GO:0000005", "is_a", "GO:0000010"),
        Edge("GO:0000020", "is_a", "GO:0000010"),
        Edge("GO:0000030", "part_of", "GO:0000010"),
        Edge("GO:0000210", "part_of", "GO:0000010"),
        Edge("GO:0000100", "regulates", "GO:0000010"),
    )
    assert s.parents("GO:0000060") == ()


def test_matching_is_exact_on_all_five_fields():
    s = mini_store()
    pos = Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    assert sorted(a.code for a in s.matching(pos)) == ["IDA", "IEA"]
    assert [a.code for a in s.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", True))] == ["IDA"]
    assert s.matching(Prop(P1, "enables", "GO:0000010", "NCBITaxon:9606", False)) == ()
    assert s.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:10090", False)) == ()


def test_annotations_are_sorted_by_id_and_subject_lookups_work():
    s = mini_store()
    anns = s.annotations(P1)
    assert [a.id for a in anns] == sorted(a.id for a in anns) and len(anns) == 8
    assert s.subject_exists(P1) and not s.subject_exists("UniProtKB:NOPE")
    assert s.subject_for_symbol("GA") == (P1,)
    assert s.subject_for_symbol("DUP") == ("UniProtKB:P00008", "UniProtKB:P00009")
    assert s.subject_for_symbol("nope") == ()
    assert len(s.annotations("UniProtKB:P00002")) == 4


def _term(i, ns="biological_process", alt=()):
    return Term(i, i, ns, False, (), (), tuple(alt))


def _ann(i, term, subject="UniProtKB:X"):
    return Annotation(i, subject, "X", "involved_in", False, term, term, (), "IDA",
                      "ECO:0000314", (), "P", "protein", "NCBITaxon:9606", "", "2020-01-01",
                      "UniProt", "", "")


def test_store_rejects_duplicate_ids_and_alt_id_terms():
    terms = [_term("GO:1", alt=["GO:9"])]
    with pytest.raises(ValueError, match="duplicate"):
        StaticFactStore(terms, [], [_ann("gaf:a", "GO:1"), _ann("gaf:a", "GO:1")])
    with pytest.raises(ValueError, match="alt_id"):
        StaticFactStore(terms, [], [_ann("gaf:b", "GO:9")])


def test_masked_store_hides_only_the_listed_ids():
    s = mini_store()
    pos = Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    ida = next(a for a in s.matching(pos) if a.code == "IDA")
    m = MaskedFactStore(s, frozenset({ida.id}))
    assert [a.code for a in m.matching(pos)] == ["IEA"]
    assert len(m.annotations(P1)) == 7
    assert len(m.matching(Prop(P1, "involved_in", "GO:0000010", "NCBITaxon:9606", True))) == 1


def test_masked_store_keeps_a_fully_hidden_subject_visible():
    s = mini_store()
    hidden = frozenset(a.id for a in s.annotations("UniProtKB:P00005"))
    m = MaskedFactStore(s, hidden)
    assert m.annotations("UniProtKB:P00005") == ()
    assert m.subject_exists("UniProtKB:P00005") is True
    assert m.subject_for_symbol("GE") == ("UniProtKB:P00005",)
    assert m.term("GO:0000010") is s.term("GO:0000010")
    assert m.parents("GO:0000030") == s.parents("GO:0000030")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.store'`

- [ ] **Step 3: Write the implementation**

`src/methods_graph/biolean/store.py`:

```python
"""The fact store: a Protocol, a dict-backed implementation, a masking view, a loader.

Mirrors ``bench/oracle.py``: ``StaticFactStore`` holds all the logic and the loaders only
fill it, so the kernel's tests run on hand-built stores with no files and no database.
"""
from __future__ import annotations

import gzip
from pathlib import Path
from typing import Iterable, Protocol

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.props import Annotation, Edge, Prop, Term


class FactStore(Protocol):
    """What the kernel and the tactics need from the facts, and nothing more."""

    def term(self, go_id: str) -> Term | None: ...
    def primary_id(self, go_id: str) -> str | None: ...
    def parents(self, go_id: str) -> tuple[Edge, ...]: ...
    def children(self, go_id: str) -> tuple[Edge, ...]: ...
    def annotations(self, subject: str) -> tuple[Annotation, ...]: ...
    def matching(self, prop: Prop) -> tuple[Annotation, ...]: ...
    def subject_for_symbol(self, symbol: str) -> tuple[str, ...]: ...
    def subject_exists(self, subject: str) -> bool: ...


def _key(a: Annotation) -> tuple[str, str, str, str, bool]:
    return (a.subject, a.qualifier, a.term, a.taxon, a.negated)


class StaticFactStore:
    def __init__(
        self, terms: Iterable[Term], edges: Iterable[Edge], annotations: Iterable[Annotation],
    ) -> None:
        self._terms: dict[str, Term] = {t.id: t for t in terms}
        self._alt: dict[str, str] = {}
        for t in self._terms.values():
            for alt in t.alt_ids:
                self._alt[alt] = t.id

        parents: dict[str, list[Edge]] = {}
        children: dict[str, list[Edge]] = {}
        for e in edges:
            parents.setdefault(e.child, []).append(e)
            children.setdefault(e.parent, []).append(e)
        self._parents = {k: tuple(sorted(v, key=lambda e: (e.relation, e.parent)))
                         for k, v in parents.items()}
        self._children = {k: tuple(sorted(v, key=lambda e: (e.relation, e.child)))
                          for k, v in children.items()}

        by_subject: dict[str, list[Annotation]] = {}
        by_key: dict[tuple[str, str, str, str, bool], list[Annotation]] = {}
        by_symbol: dict[str, set[str]] = {}
        seen: set[str] = set()
        for a in annotations:
            if a.id in seen:
                raise ValueError(f"duplicate annotation id {a.id}")
            seen.add(a.id)
            if a.term in self._alt:
                raise ValueError(f"annotation {a.id} is at alt_id {a.term}; canonicalize first")
            by_subject.setdefault(a.subject, []).append(a)
            by_key.setdefault(_key(a), []).append(a)
            by_symbol.setdefault(a.symbol, set()).add(a.subject)
        self._by_subject = {k: tuple(sorted(v, key=lambda a: a.id)) for k, v in by_subject.items()}
        self._by_key = {k: tuple(sorted(v, key=lambda a: a.id)) for k, v in by_key.items()}
        self._by_symbol = {k: tuple(sorted(v)) for k, v in by_symbol.items()}

    def term(self, go_id: str) -> Term | None:
        return self._terms.get(go_id)

    def primary_id(self, go_id: str) -> str | None:
        if go_id in self._terms:
            return go_id
        return self._alt.get(go_id)

    def parents(self, go_id: str) -> tuple[Edge, ...]:
        return self._parents.get(go_id, ())

    def children(self, go_id: str) -> tuple[Edge, ...]:
        return self._children.get(go_id, ())

    def annotations(self, subject: str) -> tuple[Annotation, ...]:
        return self._by_subject.get(subject, ())

    def matching(self, prop: Prop) -> tuple[Annotation, ...]:
        return self._by_key.get((prop.subject, prop.qualifier, prop.term, prop.taxon, prop.negated), ())

    def subject_for_symbol(self, symbol: str) -> tuple[str, ...]:
        return self._by_symbol.get(symbol, ())

    def subject_exists(self, subject: str) -> bool:
        return subject in self._by_subject


class MaskedFactStore:
    """A view that hides annotation ids and nothing else (the subject universe stays whole)."""

    def __init__(self, base: FactStore, hidden: frozenset[str]) -> None:
        self._base = base
        self._hidden = frozenset(hidden)

    def term(self, go_id: str) -> Term | None:
        return self._base.term(go_id)

    def primary_id(self, go_id: str) -> str | None:
        return self._base.primary_id(go_id)

    def parents(self, go_id: str) -> tuple[Edge, ...]:
        return self._base.parents(go_id)

    def children(self, go_id: str) -> tuple[Edge, ...]:
        return self._base.children(go_id)

    def annotations(self, subject: str) -> tuple[Annotation, ...]:
        return tuple(a for a in self._base.annotations(subject) if a.id not in self._hidden)

    def matching(self, prop: Prop) -> tuple[Annotation, ...]:
        return tuple(a for a in self._base.matching(prop) if a.id not in self._hidden)

    def subject_for_symbol(self, symbol: str) -> tuple[str, ...]:
        return self._base.subject_for_symbol(symbol)

    def subject_exists(self, subject: str) -> bool:
        return self._base.subject_exists(subject)


def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def load_store(
    snapshot_dir: Path,
    *,
    obo: str = "go-basic.obo",
    gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> tuple[StaticFactStore, dict[str, dict[str, int]]]:
    """Read the three files and build the store. Raises FileNotFoundError for a missing file."""
    snapshot_dir = Path(snapshot_dir)
    terms, edges, obo_report = parse_go_basic(_read_text(snapshot_dir / obo))
    eco_map, eco_report = parse_eco_mapping(_read_text(snapshot_dir / eco))
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}

    def primary_id(go_id: str) -> str | None:
        return go_id if go_id in by_id else alt.get(go_id)

    annotations, gaf_report = parse_gaf(
        _read_text(snapshot_dir / gaf).splitlines(), eco_map, primary_id, by_id.get)
    store = StaticFactStore(terms, edges, annotations)
    return store, {"obo": obo_report, "eco": eco_report, "gaf": gaf_report}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_store.py tests/test_biolean_gaf.py -q`
Expected: all passed

- [ ] **Step 5: Mutation checks**

- In `MaskedFactStore.subject_exists`, return `bool(self.annotations(subject))` → `test_masked_store_keeps_a_fully_hidden_subject_visible` must fail. Revert.
- In `MaskedFactStore.matching`, filter on `a.term != prop.term` instead of ids → `test_masked_store_hides_only_the_listed_ids` must fail. Revert.
- Remove the two `raise ValueError` lines → `test_store_rejects_duplicate_ids_and_alt_id_terms` must fail. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/store.py tests/biolean_fixture.py tests/test_biolean_store.py
git commit -m "feat(biolean): FactStore protocol, StaticFactStore, MaskedFactStore, load_store

Mutation checked: masked subject_exists from annotations, mask by term, silent construction.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 6: Error records and the kernel's structural and identifier checks (`errors.py`, `kernel.py`)

**Files:**
- Create: `src/methods_graph/biolean/errors.py`
- Create: `src/methods_graph/biolean/kernel.py` (structure, identifiers, root, verdict assembly; rule bodies are stubs filled in Task 7)
- Test: `tests/test_biolean_kernel.py` (structural half)
- Modify: `docs/superpowers/specs/2026-09-21-biolean-design.md` §3 Checking (one sentence on precedence)

**Interfaces:**
- Consumes: Task 1 records and tables, `FactStore` from Task 5, `mini_store()`.
- Produces: `errors.Code` (string constants), `errors.ALL_CODES`, `errors.Error(code, message, step=None, expected=None, actual=None, suggestions=())` with `to_dict()`; `kernel.check(derivation, store) -> dict`, `kernel.ancestors(term_id, store) -> tuple[str, ...]`, `kernel.descendants(term_id, store) -> tuple[str, ...]`, `kernel.RULES`, `kernel.ARITY`. The verdict dict has exactly the keys `verdict, goal, steps_checked, sorry_count, unused_sorries, unused_steps, premise_failed, errors, axioms, sorries, conflicts, elaboration`.

- [ ] **Step 1: Amend the spec's precedence sentence**

In §3 Checking of the spec, replace:

> Per-step precedence: if a step is `MALFORMED` or its stated conclusion fails the identifier checks, no rule-application error is raised for that step.

with:

> Per-step precedence: if a step is `MALFORMED`, names an unknown rule, or its stated conclusion fails identifier *resolution* (`UNKNOWN_SUBJECT`, `UNKNOWN_TERM`, `OBSOLETE_TERM`, `ALT_ID_IN_KERNEL`, `UNKNOWN_QUALIFIER`, malformed taxon), no rule-application error is raised for that step. `QUALIFIER_ASPECT_MISMATCH` does not suppress rule application: every identifier resolved, so the rule's own checks are meaningful, and a cross-namespace propagation reports both it and `NAMESPACE_CROSSED`.

- [ ] **Step 2: Write the failing tests (structural half)**

`tests/test_biolean_kernel.py` — the helpers at the top are shared by Tasks 7 and 8, which append to this file:

```python
"""Kernel tests. Every rejection test asserts the (step, code) pair; every acceptance test
asserts errors == []. Fixture: tests/fixtures/biolean via mini_store()."""
import json

from methods_graph.biolean.errors import ALL_CODES, Code
from methods_graph.biolean.kernel import ancestors, check, descendants
from methods_graph.biolean.props import Prop
from tests.biolean_fixture import mini_store

P1, P2, P3, P5, P7 = ("UniProtKB:P00001", "UniProtKB:P00002", "UniProtKB:P00003",
                      "UniProtKB:P00005", "UniProtKB:P00007")
TAX = "NCBITaxon:9606"
A, B, C, D = "GO:0000030", "GO:0000005", "GO:0000010", "GO:0000020"
X, Y, T = "GO:0000040", "GO:0000050", "GO:0000060"
R, OBS, ALT, MF1, MF2 = "GO:0000100", "GO:0000110", "GO:0000011", "GO:0000200", "GO:0000210"


def prop(term, subject=P1, qualifier="involved_in", negated=False, taxon=TAX):
    return {"subject": subject, "qualifier": qualifier, "term": term, "taxon": taxon,
            "negated": negated}


def axiom(sid, term, **kw):
    extra = {k: kw.pop(k) for k in ("code", "reference") if k in kw}
    return {"id": sid, "rule": "axiom", "conclusion": prop(term, **kw), **extra}


def prop_step(sid, rule, premise, child, parent, **kw):
    return {"id": sid, "rule": rule, "premises": [premise], "edge": [child, parent],
            "conclusion": prop(parent, **kw)}


def sorry(sid, term, provenance=None, **kw):
    if provenance is None:
        provenance = {"method": "m:deseq2", "inputs": ["GEO:GSE1"], "parameters": {},
                      "claim": "computed"}
    return {"id": sid, "rule": "sorry", "conclusion": prop(term, **kw), "provenance": provenance}


def deriv(goal, steps, root):
    return {"biolean": "0.1", "goal": goal, "steps": steps, "root": root}


def codes(verdict, step):
    return sorted(e["code"] for e in verdict["errors"] if e["step"] == step)


def only(verdict, step, code):
    """The single error on `step`, which must carry `code`."""
    errs = [e for e in verdict["errors"] if e["step"] == step]
    assert [e["code"] for e in errs] == [code], verdict["errors"]
    return errs[0]


STORE = mini_store()


# ---------- structure ----------

def test_non_object_derivation_is_malformed():
    v = check("not a derivation", STORE)
    assert v["verdict"] == "REJECTED"
    assert [(e["step"], e["code"]) for e in v["errors"]] == [(None, Code.MALFORMED)]
    assert v["steps_checked"] == 0 and v["goal"] is None


def test_verdict_has_exactly_the_documented_keys():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert set(v) == {"verdict", "goal", "steps_checked", "sorry_count", "unused_sorries",
                      "unused_steps", "premise_failed", "errors", "axioms", "sorries",
                      "conflicts", "elaboration"}
    assert v["elaboration"] == []
    assert all(e["code"] in ALL_CODES for e in v["errors"])


def test_duplicate_step_ids_are_reported():
    v = check(deriv(prop(A), [axiom("s1", A), axiom("s1", A)], "s1"), STORE)
    assert Code.DUPLICATE_STEP in codes(v, "s1")


def test_unknown_step_ref_and_unknown_root():
    v = check(deriv(prop(C), [prop_step("s2", "is_a", "s1", B, C)], "nope"), STORE)
    assert Code.UNKNOWN_STEP_REF in codes(v, "s2")
    assert (None, Code.UNKNOWN_STEP_REF) in [(e["step"], e["code"]) for e in v["errors"]]


def test_premise_after_use_is_step_order_not_a_hang():
    s1 = {"id": "s1", "rule": "is_a", "premises": ["s2"], "edge": [B, C], "conclusion": prop(C)}
    s2 = {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": [B, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s1, s2], "s2"), STORE)
    assert Code.STEP_ORDER in codes(v, "s1")
    assert Code.STEP_ORDER not in codes(v, "s2")


def test_is_a_with_no_premise_is_premise_arity():
    s = {"id": "s1", "rule": "is_a", "premises": [], "edge": [B, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s], "s1"), STORE)
    e = only(v, "s1", Code.PREMISE_ARITY)
    assert e["expected"] == 1 and e["actual"] == 0


def test_axiom_with_a_premise_is_premise_arity():
    steps = [axiom("s1", A), {**axiom("s2", B), "premises": ["s1"]}]
    v = check(deriv(prop(B), steps, "s2"), STORE)
    e = only(v, "s2", Code.PREMISE_ARITY)
    assert e["expected"] == 0 and e["actual"] == 1


def test_unknown_rule_is_reported_and_nothing_else_on_that_step():
    s = {"id": "s1", "rule": "regulates", "premises": [], "edge": [R, C], "conclusion": prop(C)}
    v = check(deriv(prop(C), [s], "s1"), STORE)
    only(v, "s1", Code.UNKNOWN_RULE)


def test_unknown_keys_are_malformed_naming_the_key():
    v = check(deriv(prop(A), [{**axiom("s1", A), "edge": [A, B]}], "s1"), STORE)
    e = only(v, "s1", Code.MALFORMED)
    assert "edge" in e["message"] and e["actual"] == ["edge"]


def test_code_on_a_non_axiom_step_is_malformed():
    v = check(deriv(prop(C), [axiom("s1", A), {**prop_step("s2", "part_of", "s1", A, C), "code": "IDA"}], "s2"), STORE)
    assert Code.MALFORMED in codes(v, "s2")


def test_conclusion_with_wrong_shape_is_malformed():
    bad = {"id": "s1", "rule": "axiom", "conclusion": {"subject": P1, "term": A}}
    v = check(deriv(prop(A), [bad], "s1"), STORE)
    only(v, "s1", Code.MALFORMED)


# ---------- identifiers ----------

def test_unknown_term_is_reported():
    v = check(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999")], "s1"), STORE)
    assert Code.UNKNOWN_TERM in codes(v, "s1")
    assert Code.UNKNOWN_TERM in codes(v, None)


def test_obsolete_term_error_carries_replaced_by():
    v = check(deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1"), STORE)
    e = only(v, "s1", Code.OBSOLETE_TERM)
    assert e["expected"] == {"replaced_by": [C], "consider": [D]}


def test_alt_id_reaching_the_kernel_is_an_error():
    v = check(deriv(prop(ALT), [axiom("s1", ALT)], "s1"), STORE)
    e = only(v, "s1", Code.ALT_ID_IN_KERNEL)
    assert e["expected"] == C
    good = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert good["errors"] == []
    via_edge = deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, ALT)], "s2")
    v2 = check(via_edge, STORE)
    assert Code.ALT_ID_IN_KERNEL in codes(v2, "s2")
    assert check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"), STORE)["errors"] == []


def test_unknown_subject_carries_symbol_candidates():
    v = check(deriv(prop(A, subject="DUP"), [axiom("s1", A, subject="DUP")], "s1"), STORE)
    e = only(v, "s1", Code.UNKNOWN_SUBJECT)
    assert e["expected"] == ["UniProtKB:P00008", "UniProtKB:P00009"]


def test_taxon_must_be_ncbitaxon_curie():
    v = check(deriv(prop(A, taxon="human"), [axiom("s1", A, taxon="human")], "s1"), STORE)
    assert Code.MALFORMED in codes(v, "s1") and Code.MALFORMED in codes(v, None)


def test_unknown_qualifier_and_aspect_mismatch():
    v = check(deriv(prop(A, qualifier="binds"), [axiom("s1", A, qualifier="binds")], "s1"), STORE)
    assert Code.UNKNOWN_QUALIFIER in codes(v, "s1")
    v = check(deriv(prop(A, qualifier="enables"), [axiom("s1", A, qualifier="enables")], "s1"), STORE)
    assert Code.QUALIFIER_ASPECT_MISMATCH in codes(v, "s1")


def test_root_differing_only_in_qualifier_is_root_mismatch():
    v = check(deriv(prop(A, qualifier="acts_upstream_of"), [axiom("s1", A)], "s1"), STORE)
    e = only(v, None, Code.ROOT_MISMATCH)
    assert e["expected"]["qualifier"] == "acts_upstream_of" and e["actual"]["qualifier"] == "involved_in"


def test_goal_errors_carry_step_none_and_sort_first():
    v = check(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999"), axiom("s2", A)], "s1"), STORE)
    assert v["errors"][0]["step"] is None
    steps_in_order = [e["step"] for e in v["errors"]]
    assert steps_in_order == sorted(steps_in_order, key=lambda s: -1 if s is None else int(s[1:]))


def test_errors_are_json_serializable_and_sorted_by_step_code_message():
    v = check(deriv(prop(A), [axiom("s2", "GO:0009999", qualifier="enables"), axiom("s1", A)], "s1"), STORE)
    json.dumps(v, sort_keys=True)
    keyed = [(0 if e["step"] == "s2" else 1, e["code"], e["message"]) for e in v["errors"]]
    assert keyed == sorted(keyed)


# ---------- closure helpers ----------

def test_ancestors_follow_is_a_and_part_of_within_namespace_only():
    assert ancestors(A, STORE) == (B, C, D)
    assert ancestors(MF2, STORE) == (MF1,)        # the part_of into BP is not followed
    assert ancestors(R, STORE) == ()               # regulates is not followed
    assert ancestors("GO:0009999", STORE) == ()


def test_descendants_are_the_dual_within_namespace():
    assert descendants(C, STORE) == tuple(sorted((A, B, D)))   # MF2 and R are not followed
    assert descendants("GO:0000070", STORE) == ("GO:0000080", "GO:0000090")
    assert descendants(Y, STORE) == (X,)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.biolean.errors'`

- [ ] **Step 4: Write `errors.py`**

`src/methods_graph/biolean/errors.py`:

```python
"""Error codes and the error record every rejection carries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Code:
    MALFORMED = "MALFORMED"
    UNKNOWN_RULE = "UNKNOWN_RULE"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    UNKNOWN_STEP_REF = "UNKNOWN_STEP_REF"
    STEP_ORDER = "STEP_ORDER"
    PREMISE_ARITY = "PREMISE_ARITY"
    ROOT_MISMATCH = "ROOT_MISMATCH"
    UNKNOWN_TERM = "UNKNOWN_TERM"
    OBSOLETE_TERM = "OBSOLETE_TERM"
    ALT_ID_IN_KERNEL = "ALT_ID_IN_KERNEL"
    UNKNOWN_SUBJECT = "UNKNOWN_SUBJECT"
    UNKNOWN_QUALIFIER = "UNKNOWN_QUALIFIER"
    QUALIFIER_ASPECT_MISMATCH = "QUALIFIER_ASPECT_MISMATCH"
    AXIOM_NOT_FOUND = "AXIOM_NOT_FOUND"
    EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
    NAMESPACE_CROSSED = "NAMESPACE_CROSSED"
    NEGATED_PREMISE = "NEGATED_PREMISE"
    PREMISE_MISMATCH = "PREMISE_MISMATCH"
    CONCLUSION_MISMATCH = "CONCLUSION_MISMATCH"
    SORRY_MALFORMED = "SORRY_MALFORMED"
    SORRY_NEGATED = "SORRY_NEGATED"


ALL_CODES: frozenset[str] = frozenset(
    v for k, v in vars(Code).items() if k.isupper() and isinstance(v, str))


@dataclass(frozen=True)
class Error:
    code: str
    message: str
    step: str | None = None
    expected: Any = None
    actual: Any = None
    suggestions: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "code": self.code, "message": self.message,
                "expected": self.expected, "actual": self.actual,
                "suggestions": list(self.suggestions)}
```

- [ ] **Step 5: Write `kernel.py` (structure, identifiers, root, assembly; rule stubs)**

`src/methods_graph/biolean/kernel.py`:

```python
"""The trusted checker.

Imports ``props``, ``errors`` and the ``FactStore`` protocol and nothing else in the
package. No I/O. ``check`` validates structure, resolves identifiers, applies one rule per
step, checks the root, and assembles a verdict whose every collection is sorted.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from methods_graph.biolean.errors import Code, Error
from methods_graph.biolean.props import (
    NAMESPACE_ASPECT, PROPAGATING_RELATIONS, QUALIFIER_ASPECT, TAXON_RE, Annotation, Prop)
from methods_graph.biolean.store import FactStore

RULES: tuple[str, ...] = ("axiom", "is_a", "part_of", "sorry")
ARITY: dict[str, int] = {"axiom": 0, "sorry": 0, "is_a": 1, "part_of": 1}
_COMMON_KEYS = frozenset({"id", "rule", "conclusion", "premises"})
_RULE_KEYS: dict[str, frozenset[str]] = {
    "axiom": frozenset({"code", "reference"}),
    "is_a": frozenset({"edge"}),
    "part_of": frozenset({"edge"}),
    "sorry": frozenset({"provenance"}),
}
_PROVENANCE_TYPES: dict[str, type] = {
    "method": str, "inputs": list, "parameters": dict, "claim": str}
# Codes that mean an identifier did not resolve; a step carrying one gets no rule check.
_RESOLUTION_FAILURES = frozenset({
    Code.MALFORMED, Code.UNKNOWN_SUBJECT, Code.UNKNOWN_TERM, Code.OBSOLETE_TERM,
    Code.ALT_ID_IN_KERNEL, Code.UNKNOWN_QUALIFIER})


@dataclass
class _Step:
    index: int
    raw: Any
    id: str | None = None
    rule: str | None = None
    malformed: bool = False
    prop: Prop | None = None
    resolved: bool = False           # stated conclusion passed identifier resolution
    premises: list[str] = field(default_factory=list)
    arity_ok: bool = False
    edge: tuple[str, str] | None = None
    edge_resolved: bool = False
    errors: list[Error] = field(default_factory=list)
    axioms: tuple[Annotation, ...] = ()
    premise_failed: bool = False

    def err(self, code: str, message: str, **kw: Any) -> None:
        self.errors.append(Error(code=code, message=message, step=self.id, **kw))


# ---------------------------------------------------------------------------
# closure helpers (also used by tactics)
# ---------------------------------------------------------------------------

def ancestors(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict ancestors over is_a/part_of, same namespace, live terms only, sorted."""
    start = store.term(term_id)
    if start is None:
        return ()
    seen: set[str] = set()
    queue: deque[str] = deque([term_id])
    while queue:
        cur = queue.popleft()
        for e in store.parents(cur):
            if e.relation not in PROPAGATING_RELATIONS or e.parent in seen:
                continue
            parent = store.term(e.parent)
            if parent is None or parent.obsolete or parent.namespace != start.namespace:
                continue
            seen.add(e.parent)
            queue.append(e.parent)
    return tuple(sorted(seen))


def descendants(term_id: str, store: FactStore) -> tuple[str, ...]:
    """Strict descendants: the exact dual of :func:`ancestors`, walked with children()."""
    start = store.term(term_id)
    if start is None:
        return ()
    seen: set[str] = set()
    queue: deque[str] = deque([term_id])
    while queue:
        cur = queue.popleft()
        for e in store.children(cur):
            if e.relation not in PROPAGATING_RELATIONS or e.child in seen:
                continue
            child = store.term(e.child)
            if child is None or child.obsolete or child.namespace != start.namespace:
                continue
            seen.add(e.child)
            queue.append(e.child)
    return tuple(sorted(seen))


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

def _parse_step(index: int, raw: Any) -> _Step:
    st = _Step(index=index, raw=raw)
    if not isinstance(raw, dict):
        st.errors.append(Error(Code.MALFORMED, f"step {index} must be an object"))
        st.malformed = True
        return st
    sid = raw.get("id")
    st.id = sid if isinstance(sid, str) else None
    if st.id is None:
        st.err(Code.MALFORMED, f"step {index} needs a string id")
        st.malformed = True
    rule = raw.get("rule")
    if not isinstance(rule, str):
        st.err(Code.MALFORMED, "rule must be a string")
        st.malformed = True
        return st
    st.rule = rule
    if rule not in RULES:
        st.err(Code.UNKNOWN_RULE, f"unknown rule {rule!r}", expected=list(RULES), actual=rule)
        st.malformed = True
        return st
    unknown = sorted(set(raw) - _COMMON_KEYS - _RULE_KEYS[rule])
    if unknown:
        st.err(Code.MALFORMED, f"unknown keys for rule {rule}: {', '.join(unknown)}",
               actual=unknown)
        st.malformed = True
    premises = raw.get("premises", [])
    if isinstance(premises, list) and all(isinstance(p, str) for p in premises):
        st.premises = list(premises)
    else:
        st.err(Code.MALFORMED, "premises must be a list of step ids")
        st.malformed = True
    if rule in ("is_a", "part_of") and "premises" not in raw:
        st.err(Code.MALFORMED, f"{rule} step needs premises")
        st.malformed = True
    if "conclusion" not in raw:
        st.err(Code.MALFORMED, "step needs a conclusion")
        st.malformed = True
    else:
        st.prop = Prop.from_dict(raw["conclusion"])
        if st.prop is None:
            st.err(Code.MALFORMED, "conclusion must have exactly subject, qualifier, term, "
                                   "taxon (strings) and negated (bool)")
            st.malformed = True
    if rule in ("is_a", "part_of"):
        edge = raw.get("edge")
        if isinstance(edge, list) and len(edge) == 2 and all(isinstance(t, str) for t in edge):
            st.edge = (edge[0], edge[1])
        else:
            st.err(Code.MALFORMED, f"{rule} step needs edge: [child, parent]")
            st.malformed = True
    if rule == "axiom":
        for key in ("code", "reference"):
            if key in raw and not isinstance(raw[key], str):
                st.err(Code.MALFORMED, f"{key} must be a string")
                st.malformed = True
    return st


def _check_refs_and_arity(st: _Step, index_of: dict[str, int]) -> None:
    for p in st.premises:
        if p not in index_of:
            st.err(Code.UNKNOWN_STEP_REF, f"premise {p!r} names no step", actual=p)
        elif index_of[p] >= st.index:
            st.err(Code.STEP_ORDER, f"premise {p!r} must come before step {st.id!r}", actual=p)
    if st.rule in ARITY:
        expected = ARITY[st.rule]
        if len(st.premises) != expected:
            st.err(Code.PREMISE_ARITY,
                   f"{st.rule} consumes {expected} premise(s), got {len(st.premises)}",
                   expected=expected, actual=len(st.premises))
        else:
            st.arity_ok = True


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------

def _check_term(term_id: str, store: FactStore, step: str | None) -> list[Error]:
    term = store.term(term_id)
    if term is None:
        primary = store.primary_id(term_id)
        if primary is not None:
            return [Error(Code.ALT_ID_IN_KERNEL, f"{term_id} is an alt_id of {primary}",
                          step=step, expected=primary, actual=term_id)]
        return [Error(Code.UNKNOWN_TERM, f"unknown term {term_id}", step=step, actual=term_id)]
    if term.obsolete:
        return [Error(Code.OBSOLETE_TERM, f"{term_id} is obsolete", step=step, actual=term_id,
                      expected={"replaced_by": list(term.replaced_by),
                                "consider": list(term.consider)})]
    return []


def _check_prop(prop: Prop, store: FactStore, step: str | None) -> list[Error]:
    errs: list[Error] = []
    if not store.subject_exists(prop.subject):
        errs.append(Error(Code.UNKNOWN_SUBJECT, f"unknown subject {prop.subject}", step=step,
                          actual=prop.subject,
                          expected=list(store.subject_for_symbol(prop.subject))))
    errs.extend(_check_term(prop.term, store, step))
    if not TAXON_RE.match(prop.taxon):
        errs.append(Error(Code.MALFORMED, f"taxon must be NCBITaxon:<digits>, got {prop.taxon!r}",
                          step=step, actual=prop.taxon))
    if prop.qualifier not in QUALIFIER_ASPECT:
        errs.append(Error(Code.UNKNOWN_QUALIFIER, f"unknown qualifier {prop.qualifier!r}",
                          step=step, expected=sorted(QUALIFIER_ASPECT), actual=prop.qualifier))
    else:
        term = store.term(prop.term)
        if term is not None and not term.obsolete:
            aspect = NAMESPACE_ASPECT.get(term.namespace)
            wanted = QUALIFIER_ASPECT[prop.qualifier]
            if aspect != wanted:
                errs.append(Error(
                    Code.QUALIFIER_ASPECT_MISMATCH,
                    f"{prop.qualifier} is a {wanted}-aspect qualifier; {prop.term} is {term.namespace}",
                    step=step, expected=wanted, actual=aspect))
    return errs


# ---------------------------------------------------------------------------
# rules — bodies are filled in Task 7
# ---------------------------------------------------------------------------

def _apply_axiom(st: _Step, store: FactStore) -> None:
    return None


def _apply_propagation(st: _Step, premise: _Step | None, store: FactStore) -> None:
    return None


def _apply_sorry(st: _Step) -> None:
    return None


def _conflicts(steps: list[_Step], index_of: dict[str, int], store: FactStore) -> list[dict[str, Any]]:
    return []


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def check(derivation: Any, store: FactStore) -> dict[str, Any]:
    top: list[Error] = []
    if not (isinstance(derivation, dict) and isinstance(derivation.get("steps"), list)
            and "goal" in derivation and isinstance(derivation.get("root"), str)):
        top.append(Error(Code.MALFORMED,
                         "derivation must be an object with goal, steps (list) and root (string)"))
        return _assemble(None, [], top, root_id=None, index_of={}, store=store)

    goal = Prop.from_dict(derivation["goal"])
    if goal is None:
        top.append(Error(Code.MALFORMED, "goal must have exactly subject, qualifier, term, "
                                         "taxon (strings) and negated (bool)"))
    else:
        top.extend(_check_prop(goal, store, step=None))

    steps = [_parse_step(i, raw) for i, raw in enumerate(derivation["steps"])]
    index_of: dict[str, int] = {}
    for st in steps:
        if st.id is None:
            continue
        if st.id in index_of:
            st.err(Code.DUPLICATE_STEP, f"step id {st.id!r} is used more than once", actual=st.id)
        else:
            index_of[st.id] = st.index

    for st in steps:
        if st.malformed and st.rule not in RULES:
            continue
        _check_refs_and_arity(st, index_of)
        if st.prop is not None:
            errs = _check_prop(st.prop, store, step=st.id)
            st.errors.extend(errs)
            st.resolved = not any(e.code in _RESOLUTION_FAILURES for e in errs)
        if st.edge is not None:
            errs = [e for t in st.edge for e in _check_term(t, store, step=st.id)]
            st.errors.extend(errs)
            st.edge_resolved = not errs

    for st in steps:
        premise: _Step | None = None
        if st.arity_ok and st.premises:
            p = st.premises[0]
            if p in index_of and index_of[p] < st.index:
                premise = steps[index_of[p]]
        if premise is not None and premise.errors:
            st.premise_failed = True
        if st.malformed or st.rule not in RULES or not st.resolved:
            continue
        if st.rule == "axiom":
            _apply_axiom(st, store)
        elif st.rule == "sorry":
            _apply_sorry(st)
        else:
            _apply_propagation(st, premise, store)

    root_id = derivation["root"]
    if root_id not in index_of:
        top.append(Error(Code.UNKNOWN_STEP_REF, f"root names no step: {root_id!r}", actual=root_id))
    else:
        root_step = steps[index_of[root_id]]
        if goal is not None and root_step.prop is not None and root_step.prop != goal:
            top.append(Error(Code.ROOT_MISMATCH, "root conclusion differs from goal",
                             expected=goal.to_dict(), actual=root_step.prop.to_dict()))
    return _assemble(goal, steps, top, root_id=root_id, index_of=index_of, store=store)


def _assemble(
    goal: Prop | None, steps: list[_Step], top: list[Error], *, root_id: str | None,
    index_of: dict[str, int], store: FactStore,
) -> dict[str, Any]:
    used: list[str] = []
    if root_id is not None and root_id in index_of:
        cur: _Step | None = steps[index_of[root_id]]
        guard: set[str] = set()
        while cur is not None and cur.id is not None and cur.id not in guard:
            guard.add(cur.id)
            used.append(cur.id)
            nxt = cur.premises[0] if cur.premises else None
            cur = (steps[index_of[nxt]]
                   if nxt is not None and nxt in index_of and index_of[nxt] < cur.index else None)
    used_set = set(used)
    all_ids = sorted({st.id for st in steps if st.id is not None})
    unused = [sid for sid in all_ids if sid not in used_set]

    sorries: list[dict[str, Any]] = []
    for st in steps:
        if st.rule != "sorry" or st.id is None:
            continue
        prov = st.raw.get("provenance") if isinstance(st.raw, dict) else None
        prov = prov if isinstance(prov, dict) else {}
        inputs = prov.get("inputs")
        sorries.append({
            "step": st.id, "used": st.id in used_set,
            "method": prov.get("method") if isinstance(prov.get("method"), str) else None,
            "inputs": list(inputs) if isinstance(inputs, list) else None,
        })
    sorries.sort(key=lambda s: index_of.get(s["step"], -1))
    sorry_count = sum(1 for s in sorries if s["used"])

    axioms = sorted(
        ({"step": st.id, "annotation": a.id, "code": a.code, "eco": a.eco,
          "references": sorted(a.references)}
         for st in steps for a in st.axioms),
        key=lambda d: d["annotation"])

    def _order(e: Error) -> tuple[int, str, str]:
        return (-1 if e.step is None else index_of.get(e.step, -1), e.code, e.message)

    errors = sorted(top + [e for st in steps for e in st.errors], key=_order)
    premise_failed = sorted(st.id for st in steps if st.premise_failed and st.id is not None)
    return {
        "verdict": "ACCEPTED" if not errors else "REJECTED",
        "goal": goal.to_dict() if goal is not None else None,
        "steps_checked": len(steps),
        "sorry_count": sorry_count,
        "unused_sorries": len(sorries) - sorry_count,
        "unused_steps": unused,
        "premise_failed": premise_failed,
        "errors": [e.to_dict() for e in errors],
        "axioms": axioms,
        "sorries": sorries,
        "conflicts": _conflicts(steps, index_of, store),
        "elaboration": [],
    }


def dumps(verdict: dict[str, Any]) -> str:
    """The canonical serialization: sorted keys, two-space indent."""
    return json.dumps(verdict, sort_keys=True, indent=2)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: 22 passed

- [ ] **Step 7: Mutation checks**

- In `_check_refs_and_arity`, replace `index_of[p] >= st.index` with `False` → `test_premise_after_use_is_step_order_not_a_hang` fails. Revert.
- Replace the arity branch with `st.arity_ok = True` unconditionally → both `*_is_premise_arity` tests fail. Revert.
- In `_check_term`, return `[]` when `primary is not None` (resolve alt ids silently) → `test_alt_id_reaching_the_kernel_is_an_error` fails. Revert.
- In `_check_term`, drop `expected=` from the obsolete error → `test_obsolete_term_error_carries_replaced_by` fails. Revert.
- In `check`, compare `root_step.prop.term != goal.term` instead of the whole prop → `test_root_differing_only_in_qualifier_is_root_mismatch` fails. Revert.

- [ ] **Step 8: Commit**

```bash
git add src/methods_graph/biolean/errors.py src/methods_graph/biolean/kernel.py tests/test_biolean_kernel.py docs/superpowers/specs/2026-09-21-biolean-design.md
git commit -m "feat(biolean): kernel structure, identifier resolution, root check, verdict assembly

Rules are stubs until the next commit. Mutation checked: forward premise refs,
arity ignored, alt ids resolved in kernel, obsolete replacement dropped, root on term only.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The four rules (`kernel.py`)

**Files:**
- Modify: `src/methods_graph/biolean/kernel.py` (replace the three rule stubs, add `_axiom_suggestions`)
- Test: `tests/test_biolean_kernel.py` (append)

**Interfaces:**
- Consumes: Task 6.
- Produces: `check` now applies `axiom`, `is_a`, `part_of`, `sorry` per §3; `axioms`, `sorries`, `sorry_count`, `unused_sorries`, `premise_failed` are meaningful.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_biolean_kernel.py`:

```python
# ---------- rules ----------

def test_axiom_only_derivation_is_accepted_and_lists_its_rows():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert sorted(a["code"] for a in v["axioms"]) == ["IDA", "IPI"]
    assert [a["annotation"] for a in v["axioms"]] == sorted(a["annotation"] for a in v["axioms"])
    assert v["axioms"][0]["eco"] in ("ECO:0000314", "ECO:0000353")


def test_axiom_requires_the_exact_qualifier():
    v = check(deriv(prop(MF2, subject=P3, qualifier="contributes_to"),
                    [axiom("s1", MF2, subject=P3, qualifier="contributes_to")], "s1"), STORE)
    e = only(v, "s1", Code.AXIOM_NOT_FOUND)
    assert {"rule": "axiom", "conclusion": prop(MF2, subject=P3, qualifier="enables")} in e["suggestions"]


def test_axiom_with_code_requires_a_row_with_that_code():
    v = check(deriv(prop(A, subject="UniProtKB:P00008"),
                    [axiom("s1", A, subject="UniProtKB:P00008", code="IDA")], "s1"), STORE)
    only(v, "s1", Code.AXIOM_NOT_FOUND)
    ok = check(deriv(prop(A, subject="UniProtKB:P00008"),
                     [axiom("s1", A, subject="UniProtKB:P00008", code="IEA")], "s1"), STORE)
    assert ok["errors"] == []


def test_axiom_code_and_reference_must_be_on_one_row():
    split = axiom("s1", MF2, subject=P3, qualifier="enables", code="IPI", reference="PMID:11")
    v = check(deriv(prop(MF2, subject=P3, qualifier="enables"), [split], "s1"), STORE)
    only(v, "s1", Code.AXIOM_NOT_FOUND)
    same = axiom("s1", MF2, subject=P3, qualifier="enables", code="IDA", reference="PMID:12")
    ok = check(deriv(prop(MF2, subject=P3, qualifier="enables"), [same], "s1"), STORE)
    assert ok["errors"] == [] and [a["code"] for a in ok["axioms"]] == ["IDA"]


def test_axiom_without_code_lists_every_matching_row():
    v = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert v["errors"] == []
    assert sorted(a["code"] for a in v["axioms"]) == ["IDA", "IEA"]


def test_axiom_at_obsolete_term_is_rejected_even_though_the_row_exists():
    assert STORE.matching(Prop(P5, "involved_in", OBS, TAX, False))   # the row IS in the store
    v = check(deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1"), STORE)
    e = only(v, "s1", Code.OBSOLETE_TERM)
    assert e["expected"]["replaced_by"] == [C]


def test_is_a_and_part_of_chains_are_accepted():
    v = check(deriv(prop(C), [axiom("s1", B), prop_step("s2", "is_a", "s1", B, C)], "s2"), STORE)
    assert v["errors"] == [] and v["unused_steps"] == [] and v["premise_failed"] == []
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"), STORE)
    assert v["errors"] == []
    two = [axiom("s1", A), prop_step("s2", "is_a", "s1", A, B), prop_step("s3", "is_a", "s2", B, C)]
    assert check(deriv(prop(C), two, "s3"), STORE)["errors"] == []


def test_regulates_edge_is_not_a_rule():
    s2 = {"id": "s2", "rule": "regulates", "premises": ["s1"], "edge": [R, C],
          "conclusion": prop(C, subject=P7)}
    v = check(deriv(prop(C, subject=P7), [axiom("s1", R, subject=P7), s2], "s2"), STORE)
    only(v, "s2", Code.UNKNOWN_RULE)
    assert codes(v, "s1") == []            # the mutant that adds `regulates` ACCEPTS this


def test_is_a_step_citing_a_regulates_edge_is_edge_not_found_with_actual_relation():
    v = check(deriv(prop(C, subject=P7),
                    [axiom("s1", R, subject=P7), prop_step("s2", "is_a", "s1", R, C, subject=P7)], "s2"), STORE)
    e = only(v, "s2", Code.EDGE_NOT_FOUND)
    assert e["actual"] == {"parents_of_child": [["regulates", C]]}
    assert e["suggestions"] == []


def test_edge_not_found_suggests_the_other_propagating_relation():
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", A, C)], "s2"), STORE)
    e = only(v, "s2", Code.EDGE_NOT_FOUND)
    assert e["suggestions"] == [{"rule": "part_of", "edge": [A, C]}]
    assert e["actual"]["parents_of_child"] == [["is_a", B], ["part_of", C], ["part_of", D]]


def test_part_of_across_namespaces_is_namespace_crossed():
    steps = [axiom("s1", MF2, subject=P3, qualifier="enables"),
             prop_step("s2", "part_of", "s1", MF2, C, subject=P3, qualifier="enables")]
    v = check(deriv(prop(C, subject=P3, qualifier="enables"), steps, "s2"), STORE)
    assert codes(v, "s2") == [Code.NAMESPACE_CROSSED, Code.QUALIFIER_ASPECT_MISMATCH]
    assert codes(v, "s1") == []


def test_negated_premise_cannot_propagate():
    for stated_negated in (False, True):
        steps = [axiom("s1", X, subject=P2, negated=True),
                 prop_step("s2", "is_a", "s1", X, Y, subject=P2, negated=stated_negated)]
        v = check(deriv(prop(Y, subject=P2, negated=stated_negated), steps, "s2"), STORE)
        assert Code.NEGATED_PREMISE in codes(v, "s2"), stated_negated
        assert codes(v, "s1") == []
    v = check(deriv(prop(Y, subject=P2), [axiom("s1", X, subject=P2, negated=True),
                                          prop_step("s2", "is_a", "s1", X, Y, subject=P2)], "s2"), STORE)
    assert codes(v, "s2") == [Code.NEGATED_PREMISE]


def test_conclusion_must_equal_computed_conclusion():
    bad = {**prop_step("s2", "is_a", "s1", B, C), "conclusion": prop(D)}
    v = check(deriv(prop(D), [axiom("s1", B), bad], "s2"), STORE)
    e = only(v, "s2", Code.CONCLUSION_MISMATCH)
    assert e["expected"] == prop(C) and e["actual"] == prop(D)


def test_premise_mismatch_when_edge_starts_elsewhere():
    v = check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", B, C)], "s2"), STORE)
    e = only(v, "s2", Code.PREMISE_MISMATCH)
    assert e["expected"] == B and e["actual"] == A


def test_every_error_is_reported_not_just_the_first():
    steps = [axiom("s1", "GO:0009999"), axiom("s2", C, qualifier="enables")]
    v = check(deriv(prop(C, qualifier="enables"), steps, "s2"), STORE)
    assert Code.UNKNOWN_TERM in codes(v, "s1")
    assert Code.QUALIFIER_ASPECT_MISMATCH in codes(v, "s2")


def test_one_broken_axiom_yields_one_error_down_a_chain():
    steps = [axiom("s1", X), prop_step("s2", "is_a", "s1", X, Y), prop_step("s3", "is_a", "s2", Y, T)]
    v = check(deriv(prop(T), steps, "s3"), STORE)
    assert [(e["step"], e["code"]) for e in v["errors"]] == [("s1", Code.AXIOM_NOT_FOUND)]
    assert v["premise_failed"] == ["s2"]


def test_dependent_step_is_still_checked_when_premise_failed():
    steps = [axiom("s1", X), prop_step("s2", "is_a", "s1", X, T)]
    v = check(deriv(prop(T), steps, "s2"), STORE)
    assert codes(v, "s1") == [Code.AXIOM_NOT_FOUND]
    assert codes(v, "s2") == [Code.EDGE_NOT_FOUND]
    assert v["premise_failed"] == ["s2"]


def test_sorry_is_counted_and_does_not_reject():
    v = check(deriv(prop(T), [sorry("s1", T)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert v["sorry_count"] == 1 and v["unused_sorries"] == 0
    assert v["sorries"] == [{"step": "s1", "used": True, "method": "m:deseq2", "inputs": ["GEO:GSE1"]}]


def test_unused_sorry_does_not_count_toward_sorry_count():
    steps = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)]
    v = check(deriv(prop(C), steps, "s2"), STORE)
    assert v["errors"] == []
    assert v["sorry_count"] == 0 and v["unused_sorries"] == 1
    assert v["unused_steps"] == ["s3"] and v["sorries"][0]["used"] is False


def test_error_in_unused_step_still_rejects():
    steps = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), axiom("s3", "GO:0009999")]
    v = check(deriv(prop(C), steps, "s2"), STORE)
    assert v["verdict"] == "REJECTED" and codes(v, "s3") == [Code.UNKNOWN_TERM]
    assert v["unused_steps"] == ["s3"]


def test_sorry_with_missing_inputs_is_malformed():
    bad = sorry("s1", T, provenance={"method": "m:x", "parameters": {}, "claim": "c"})
    only(check(deriv(prop(T), [bad], "s1"), STORE), "s1", Code.SORRY_MALFORMED)
    empty = sorry("s1", T, provenance={"method": "m:x", "inputs": [], "parameters": {}, "claim": "c"})
    only(check(deriv(prop(T), [empty], "s1"), STORE), "s1", Code.SORRY_MALFORMED)
    missing = {"id": "s1", "rule": "sorry", "conclusion": prop(T)}
    only(check(deriv(prop(T), [missing], "s1"), STORE), "s1", Code.SORRY_MALFORMED)


def test_sorry_negated_is_rejected():
    v = check(deriv(prop(T, negated=True), [sorry("s1", T, negated=True)], "s1"), STORE)
    only(v, "s1", Code.SORRY_NEGATED)


def test_sorry_at_unknown_subject_is_unknown_subject():
    v = check(deriv(prop(T, subject="UniProtKB:NOPE"), [sorry("s1", T, subject="UniProtKB:NOPE")], "s1"), STORE)
    assert Code.UNKNOWN_SUBJECT in codes(v, "s1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: the 23 new tests fail (rule stubs never raise `AXIOM_NOT_FOUND` etc.); the 22 from Task 6 still pass.

- [ ] **Step 3: Replace the rule stubs in `kernel.py`**

Replace the block between the `# rules` banner and the `# check` banner with:

```python
# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def _fragment(prop: Prop) -> dict[str, Any]:
    return {"rule": "axiom", "conclusion": prop.to_dict()}


def _axiom_suggestions(prop: Prop, store: FactStore) -> tuple[dict[str, Any], ...]:
    """Well-formed axiom fragments near a missing one: other qualifier at the term, same
    qualifier at a descendant, same proposition under another taxon."""
    out: dict[str, dict[str, Any]] = {}
    for a in store.annotations(prop.subject):
        if a.negated:
            continue
        same_term_other_q = a.term == prop.term and a.qualifier != prop.qualifier and a.taxon == prop.taxon
        other_taxon = a.term == prop.term and a.qualifier == prop.qualifier and a.taxon != prop.taxon
        below = (a.qualifier == prop.qualifier and a.taxon == prop.taxon and a.term != prop.term
                 and prop.term in ancestors(a.term, store))
        if same_term_other_q or other_taxon or below:
            frag = _fragment(Prop(a.subject, a.qualifier, a.term, a.taxon, False))
            out.setdefault(json.dumps(frag, sort_keys=True), frag)
    return tuple(out[k] for k in sorted(out))


def _apply_axiom(st: _Step, store: FactStore) -> None:
    assert st.prop is not None
    rows = list(store.matching(st.prop))
    code = st.raw.get("code")
    reference = st.raw.get("reference")
    if code is not None:
        rows = [r for r in rows if r.code == code]
    if reference is not None:
        rows = [r for r in rows if reference in r.references]
    if rows:
        st.axioms = tuple(sorted(rows, key=lambda a: a.id))
        return
    filters = {k: v for k, v in (("code", code), ("reference", reference)) if v is not None}
    st.err(Code.AXIOM_NOT_FOUND,
           "no annotation matches" + (f" with {filters}" if filters else ""),
           expected={**st.prop.to_dict(), **filters},
           suggestions=_axiom_suggestions(st.prop, store))


def _apply_propagation(st: _Step, premise: _Step | None, store: FactStore) -> None:
    assert st.prop is not None and st.edge is not None and st.rule is not None
    relation = st.rule
    child, parent = st.edge
    if st.edge_resolved:
        edges = store.parents(child)
        if not any(e.relation == relation and e.parent == parent for e in edges):
            suggestions = tuple(
                {"rule": e.relation, "edge": [child, parent]}
                for e in edges if e.parent == parent and e.relation in PROPAGATING_RELATIONS)
            st.err(Code.EDGE_NOT_FOUND, f"no {relation} edge {child} -> {parent}",
                   expected={"child": child, "relation": relation, "parent": parent},
                   actual={"parents_of_child": [[e.relation, e.parent] for e in edges]},
                   suggestions=suggestions)
        child_term, parent_term = store.term(child), store.term(parent)
        if child_term is not None and parent_term is not None \
                and child_term.namespace != parent_term.namespace:
            st.err(Code.NAMESPACE_CROSSED,
                   f"{child} is {child_term.namespace}, {parent} is {parent_term.namespace}",
                   expected=child_term.namespace, actual=parent_term.namespace)
    if premise is None or premise.prop is None:
        return
    pp = premise.prop
    if pp.term != child:
        st.err(Code.PREMISE_MISMATCH, f"premise concludes {pp.term}; edge starts at {child}",
               expected=child, actual=pp.term)
    if pp.negated:
        st.err(Code.NEGATED_PREMISE, "a NOT annotation does not propagate upward")
    computed = Prop(pp.subject, pp.qualifier, parent, pp.taxon, False)
    if computed != st.prop:
        st.err(Code.CONCLUSION_MISMATCH, "stated conclusion differs from the rule's conclusion",
               expected=computed.to_dict(), actual=st.prop.to_dict())


def _apply_sorry(st: _Step) -> None:
    assert st.prop is not None
    prov = st.raw.get("provenance")
    well_formed = (
        isinstance(prov, dict)
        and set(prov) == set(_PROVENANCE_TYPES)
        and all(type(prov[k]) is t for k, t in _PROVENANCE_TYPES.items())
        and bool(prov["inputs"])
        and all(isinstance(i, str) for i in prov["inputs"])
    )
    if not well_formed:
        st.err(Code.SORRY_MALFORMED,
               "provenance needs method (str), inputs (non-empty list of str), "
               "parameters (object), claim (str)",
               expected=sorted(_PROVENANCE_TYPES))
    if st.prop.negated:
        st.err(Code.SORRY_NEGATED, "a sorry step cannot conclude a NOT proposition")


def _conflicts(steps: list[_Step], index_of: dict[str, int], store: FactStore) -> list[dict[str, Any]]:
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: 45 passed

- [ ] **Step 5: Mutation checks** (apply, run, confirm the named test fails, revert)

- `RULES = (..., "regulates")`, `ARITY["regulates"] = 1`, `_RULE_KEYS["regulates"] = {"edge"}`, and in `check` route `"regulates"` to `_apply_propagation` → `test_regulates_edge_is_not_a_rule` fails with verdict ACCEPTED. Record "mutant verdict: ACCEPTED".
- In `_apply_propagation`, match edges with `e.parent == parent` only → `test_is_a_step_citing_a_regulates_edge_is_edge_not_found_with_actual_relation` fails.
- Delete the `NAMESPACE_CROSSED` block → `test_part_of_across_namespaces_is_namespace_crossed` fails (only `QUALIFIER_ASPECT_MISMATCH` remains).
- Delete the `if pp.negated` block → `test_negated_premise_cannot_propagate` fails on the `stated_negated=False` case with verdict ACCEPTED. Record it.
- In `_apply_axiom`, replace `store.matching(st.prop)` with a scan of `store.annotations(st.prop.subject)` filtered on term only → `test_axiom_requires_the_exact_qualifier` fails (mutant ACCEPTED).
- Drop the `code` filter → `test_axiom_with_code_requires_a_row_with_that_code` fails.
- Apply the `code` and `reference` filters as `rows = [r for r in rows if r.code == code or reference in r.references]` → `test_axiom_code_and_reference_must_be_on_one_row` fails.
- `st.axioms = (rows[0],)` → `test_axiom_without_code_lists_every_matching_row` fails.
- Replace `computed != st.prop` with `False` → `test_conclusion_must_equal_computed_conclusion` fails.
- In `check`, `break` after the first step with errors → `test_every_error_is_reported_not_just_the_first` and `test_dependent_step_is_still_checked_when_premise_failed` fail.
- In `check`, `continue` when `st.premise_failed` → `test_dependent_step_is_still_checked_when_premise_failed` fails.
- In `_assemble`, `sorry_count = len(sorries)` → `test_unused_sorry_does_not_count_toward_sorry_count` fails.
- In `_assemble`, filter `errors` to used steps → `test_error_in_unused_step_still_rejects` fails.
- In `_apply_sorry`, `well_formed = isinstance(prov, dict)` → `test_sorry_with_missing_inputs_is_malformed` fails.
- Delete the `SORRY_NEGATED` block → `test_sorry_negated_is_rejected` fails.
- In `check`, guard `_check_prop` for steps with `rule == "sorry"` → `test_sorry_at_unknown_subject_is_unknown_subject` fails.
- In `check`, run `_check_prop` only when `store.matching(st.prop)` is empty → `test_axiom_at_obsolete_term_is_rejected_even_though_the_row_exists` fails.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/kernel.py tests/test_biolean_kernel.py
git commit -m "feat(biolean): axiom, is_a, part_of and sorry rules

Mutation checked (17 mutants, each failing its named test; regulates-as-rule and
negated-premise mutants ACCEPT the fixture derivation).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 8: Conflicts, sortedness, and the golden verdict (`kernel.py`)

**Files:**
- Modify: `src/methods_graph/biolean/kernel.py` (replace the `_conflicts` stub)
- Create: `tests/fixtures/biolean/golden_verdict.json`
- Test: `tests/test_biolean_kernel.py` (append)

**Interfaces:**
- Consumes: Task 7.
- Produces: `Verdict.conflicts` per §3 (closure-based, verdict-neutral); the golden derivation `GOLDEN` in the test module, reused by the CLI test.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_biolean_kernel.py`:

```python
# ---------- conflicts ----------

def test_conflict_at_the_term_is_listed_without_changing_the_verdict():
    v = check(deriv(prop(C), [axiom("s1", C)], "s1"), STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    [c] = v["conflicts"]
    assert c["step"] == "s1" and c["negated"] is True and c["code"] == "IDA"
    assert c["at"] == "term" and c["via"] == C


def test_conflict_at_an_ancestor_is_listed():
    v = check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert v["errors"] == []
    [c] = v["conflicts"]
    assert c == {"step": "s1", "annotation": c["annotation"], "negated": True, "code": "IDA",
                 "at": "ancestor", "via": C}


def test_conflict_at_a_descendant_of_a_negated_conclusion_is_listed():
    v = check(deriv(prop(C, negated=True), [axiom("s1", C, negated=True)], "s1"), STORE)
    assert v["errors"] == []
    ats = sorted((c["at"], c["via"]) for c in v["conflicts"])
    assert ("term", C) in ats                                  # the positive IDA/IEA rows at C
    assert {via for at, via in ats if at == "descendant"} == {A, B, D}
    assert all(c["negated"] is False for c in v["conflicts"])
    assert [c["annotation"] for c in v["conflicts"]] == sorted(c["annotation"] for c in v["conflicts"])


def test_conflicts_never_follow_regulates_and_list_each_annotation_once():
    v = check(deriv(prop(C, subject=P7), [axiom("s1", R, subject=P7), sorry("s2", C, subject=P7)], "s2"), STORE)
    assert v["conflicts"] == []                                # P00007 has no NOT rows anywhere
    two = [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)]
    v = check(deriv(prop(C), two, "s2"), STORE)
    ids = [c["annotation"] for c in v["conflicts"]]
    assert len(ids) == len(set(ids)) == 1 and v["conflicts"][0]["step"] == "s1"


# ---------- sortedness and the golden verdict ----------

GOLDEN = deriv(prop(T, subject=P2), [
    axiom("s9", Y, subject=P2),
    prop_step("s8", "is_a", "s9", Y, T, subject=P2),
    sorry("s7", T, subject=P2),
    axiom("s6", A),
    prop_step("s5", "part_of", "s6", A, C),
    sorry("s4", D),
    axiom("s3", MF2, subject=P3, qualifier="enables", code="IDA"),
    axiom("s2", X),
    prop_step("s1", "is_a", "s2", X, Y),
], "s8")

IDX = {s["id"]: i for i, s in enumerate(GOLDEN["steps"])}   # step id -> position

# Collection -> the key §3 declares. `sorries` and `conflicts` sort by step POSITION (the
# derivation's order), `unused_steps`/`premise_failed` by step id string.
_SORT_KEYS = {
    "unused_steps": lambda x: x,
    "premise_failed": lambda x: x,
    "axioms": lambda d: d["annotation"],
    "sorries": lambda d: IDX[d["step"]],
    "conflicts": lambda d: (IDX[d["step"]], d["annotation"]),
    "references": lambda x: x,
    "suggestions": lambda d: json.dumps(d, sort_keys=True),
}


def test_report_collections_are_sorted_by_their_declared_keys():
    v = check(GOLDEN, STORE)
    assert v["verdict"] == "REJECTED" and len(v["errors"]) == 1
    assert v["unused_steps"] == ["s1", "s2", "s3", "s4", "s7"]      # id order, not position
    assert v["premise_failed"] == ["s1"]
    assert [s["step"] for s in v["sorries"]] == ["s7", "s4"]        # position order
    for key, sort_key in _SORT_KEYS.items():
        for node in _walk(v, key):
            assert node == sorted(node, key=sort_key), key


def _walk(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, list):
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)


def test_verdict_matches_committed_golden():
    from pathlib import Path
    from methods_graph.biolean.kernel import dumps
    golden = Path(__file__).parent / "fixtures" / "biolean" / "golden_verdict.json"
    assert dumps(check(GOLDEN, STORE)) + "\n" == golden.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: the four conflict tests fail (`conflicts == []`), `test_verdict_matches_committed_golden` fails with `FileNotFoundError`, the sortedness test passes or fails depending on the stub; 45 earlier tests pass.

- [ ] **Step 3: Replace `_conflicts` in `kernel.py`**

```python
def _conflicts(steps: list[_Step], index_of: dict[str, int], store: FactStore) -> list[dict[str, Any]]:
    """Store annotations contradicting any step's conclusion over the propagation closure.

    A positive conclusion at t is contradicted by a NOT row at t or at any is_a/part_of
    ancestor of t (within namespace); a negated conclusion at t by a positive row at t or at
    any descendant. Each annotation is listed once, against the earliest step it contradicts.
    Verdict-neutral: this is the defeasibility seam.
    """
    found: dict[str, dict[str, Any]] = {}
    for st in steps:
        p = st.prop
        if p is None or st.id is None:
            continue
        if not p.negated:
            candidates = [(p.term, "term")] + [(u, "ancestor") for u in ancestors(p.term, store)]
            flag = True
        else:
            candidates = [(p.term, "term")] + [(d, "descendant") for d in descendants(p.term, store)]
            flag = False
        for via, at in candidates:
            for a in store.matching(Prop(p.subject, p.qualifier, via, p.taxon, flag)):
                found.setdefault(a.id, {"step": st.id, "annotation": a.id, "negated": a.negated,
                                        "code": a.code, "at": at, "via": via})
    return sorted(found.values(), key=lambda c: (index_of.get(c["step"], -1), c["annotation"]))
```

- [ ] **Step 4: Generate and inspect the golden verdict**

Run once, from the repo root, with the same interpreter the tests use:

```bash
$PYTHON - <<'EOF'
from methods_graph.biolean.kernel import check, dumps
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import GOLDEN
from pathlib import Path
out = Path("tests/fixtures/biolean/golden_verdict.json")
out.write_text(dumps(check(GOLDEN, mini_store())) + "\n", encoding="utf-8")
print(out.read_text())
EOF
```

(`$PYTHON` is the interpreter part of `$PYTEST`, without `-m pytest`.) Read the printed verdict against §3 by eye: `verdict` REJECTED; exactly one error, `s2` `AXIOM_NOT_FOUND`; `axioms` with four entries (two rows for `s6`, one for `s9`, one for `s3`); `sorries` for `s7` and `s4`, both `used: false`; `sorry_count` 0, `unused_sorries` 2; `unused_steps` `["s1","s2","s3","s4","s7"]`; `premise_failed` `["s1"]`; exactly one conflict, listed against `s6` (the earliest step it contradicts: `s6` concludes `involved_in A` and the NOT row sits at the ancestor `C`), with `at: "ancestor"` and `via: "GO:0000010"`; `s5` would hit the same row at `term` but an annotation is listed once; `elaboration` `[]`. If anything differs, the kernel is wrong, not the golden: fix the kernel and regenerate.

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_kernel.py -q`
Expected: 51 passed

- [ ] **Step 6: Mutation checks**

- In `_conflicts`, replace `candidates` for the positive case with `[(p.term, "term")]` only → `test_conflict_at_an_ancestor_is_listed` fails. Revert.
- Replace the negated branch with `candidates = []` → `test_conflict_at_a_descendant_of_a_negated_conclusion_is_listed` fails. Revert.
- Make conflicts append an error → `test_conflict_at_the_term_is_listed_without_changing_the_verdict` fails. Revert.
- In `_assemble`, emit `unused` in step order (`[st.id for st in steps if st.id not in used_set]`) → `test_report_collections_are_sorted_by_their_declared_keys` fails (the golden lists steps s9..s1). Revert.
- In `_assemble`, change any key name → `test_verdict_matches_committed_golden` fails. Revert.

- [ ] **Step 7: Commit**

```bash
git add src/methods_graph/biolean/kernel.py tests/fixtures/biolean/golden_verdict.json tests/test_biolean_kernel.py
git commit -m "feat(biolean): closure-based conflicts, sortedness test, golden verdict

Mutation checked: exact-term conflicts only, no descendant side, conflicts reject,
unsorted unused_steps, renamed verdict key.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Elaborator (`elaborate.py`)

**Files:**
- Create: `src/methods_graph/biolean/elaborate.py`
- Test: `tests/test_biolean_elaborate.py`

**Interfaces:**
- Consumes: `FactStore`, `normalize_taxon`, `TAXON_RE`, `kernel.check`.
- Produces: `elaborate(derivation, store) -> tuple[Any, list[dict]]` (a deep copy with identifiers rewritten, and `Elaboration` dicts `{"path", "kind", "before", "after"}` sorted by path), `elaborate_and_check(derivation, store) -> dict` (the verdict with `elaboration` filled).

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_elaborate.py`:

```python
import copy

from methods_graph.biolean.elaborate import elaborate, elaborate_and_check
from methods_graph.biolean.errors import Code
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, ALT, C, OBS, P1, P5, axiom, deriv, prop, prop_step

STORE = mini_store()


def test_symbol_alt_id_and_taxon_are_rewritten_and_reported_with_paths():
    d = deriv({**prop(ALT, subject="GA", taxon="9606")},
              [{**axiom("s1", A, subject="GA", taxon="taxon:9606")},
               prop_step("s2", "part_of", "s1", A, ALT, subject="GA")], "s2")
    out, report = elaborate(d, STORE)
    assert out["goal"] == prop(C)
    assert out["steps"][0]["conclusion"]["subject"] == P1
    assert out["steps"][1]["edge"] == [A, C]
    assert out["steps"][1]["conclusion"] == prop(C)
    assert report == sorted(report, key=lambda e: e["path"])
    kinds = {(e["path"], e["kind"]) for e in report}
    assert ("goal/subject", "SYMBOL_RESOLVED") in kinds
    assert ("goal/term", "ALT_ID_RESOLVED") in kinds
    assert ("goal/taxon", "TAXON_NORMALIZED") in kinds
    assert ("steps/0/conclusion/taxon", "TAXON_NORMALIZED") in kinds
    assert ("steps/1/edge/1", "ALT_ID_RESOLVED") in kinds
    assert ("steps/1/conclusion/term", "ALT_ID_RESOLVED") in kinds
    assert all(set(e) == {"path", "kind", "before", "after"} for e in report)


def test_every_rewrite_is_reported_with_its_path():
    d = deriv(prop(A, taxon="9606"), [axiom("s1", A, taxon="9606")], "s1")
    _, report = elaborate(d, STORE)
    assert [(e["path"], e["before"], e["after"]) for e in report] == [
        ("goal/taxon", "9606", "NCBITaxon:9606"),
        ("steps/0/conclusion/taxon", "9606", "NCBITaxon:9606"),
    ]


def test_input_is_not_mutated():
    d = deriv(prop(ALT), [axiom("s1", ALT)], "s1")
    snapshot = copy.deepcopy(d)
    elaborate(d, STORE)
    assert d == snapshot


def test_ambiguous_symbol_is_not_resolved():
    d = deriv(prop(A, subject="DUP"), [axiom("s1", A, subject="DUP")], "s1")
    out, report = elaborate(d, STORE)
    assert out["steps"][0]["conclusion"]["subject"] == "DUP"
    assert [e["kind"] for e in report] == ["SYMBOL_AMBIGUOUS", "SYMBOL_AMBIGUOUS"]
    assert report[0]["after"] is None
    v = elaborate_and_check(d, STORE)
    assert any(e["code"] == Code.UNKNOWN_SUBJECT and e["step"] == "s1" for e in v["errors"])


def test_obsolete_term_is_not_silently_replaced():
    d = deriv(prop(OBS, subject=P5), [axiom("s1", OBS, subject=P5)], "s1")
    out, report = elaborate(d, STORE)
    assert out == d and report == []
    v = elaborate_and_check(d, STORE)
    assert any(e["code"] == Code.OBSOLETE_TERM for e in v["errors"])


def test_elaborate_and_check_fills_the_elaboration_field():
    d = deriv(prop(ALT), [axiom("s1", ALT)], "s1")
    v = elaborate_and_check(d, STORE)
    assert v["errors"] == [] and v["verdict"] == "ACCEPTED"
    assert [e["kind"] for e in v["elaboration"]] == ["ALT_ID_RESOLVED", "ALT_ID_RESOLVED"]


def test_malformed_shapes_pass_through_untouched():
    for bad in ("nope", {"goal": 1, "steps": "x", "root": 2}, {"goal": {}, "steps": [1, {"edge": "y"}], "root": "s"}):
        out, report = elaborate(bad, STORE)
        assert out == bad and report == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_elaborate.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/methods_graph/biolean/elaborate.py`:

```python
"""Identifier normalization before the kernel. Every rewrite is a lookup and is reported.

Positions touched: goal.{subject,term,taxon}, steps[*].conclusion.{subject,term,taxon},
steps[*].edge[0], steps[*].edge[1]. Nothing else in the document is an identifier.
Obsolete terms are never rewritten: the kernel's OBSOLETE_TERM carries the replacement.
"""
from __future__ import annotations

import copy
from typing import Any

from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import TAXON_RE, normalize_taxon
from methods_graph.biolean.store import FactStore

SYMBOL_RESOLVED = "SYMBOL_RESOLVED"
SYMBOL_AMBIGUOUS = "SYMBOL_AMBIGUOUS"
ALT_ID_RESOLVED = "ALT_ID_RESOLVED"
TAXON_NORMALIZED = "TAXON_NORMALIZED"


def _record(report: list[dict[str, Any]], path: str, kind: str, before: str, after: str | None) -> None:
    report.append({"path": path, "kind": kind, "before": before, "after": after})


def _subject(container: Any, key: Any, path: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or store.subject_exists(value):
        return
    candidates = store.subject_for_symbol(value)
    if len(candidates) == 1:
        container[key] = candidates[0]
        _record(report, path, SYMBOL_RESOLVED, value, candidates[0])
    elif len(candidates) > 1:
        _record(report, path, SYMBOL_AMBIGUOUS, value, None)


def _term(container: Any, key: Any, path: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or store.term(value) is not None:
        return
    primary = store.primary_id(value)
    if primary is not None:
        container[key] = primary
        _record(report, path, ALT_ID_RESOLVED, value, primary)


def _taxon(container: Any, key: Any, path: str, report: list[dict[str, Any]]) -> None:
    value = container[key]
    if not isinstance(value, str) or TAXON_RE.match(value):
        return
    normalized = normalize_taxon(value)
    if normalized is not None:
        container[key] = normalized
        _record(report, path, TAXON_NORMALIZED, value, normalized)


def _prop_positions(d: Any, prefix: str, store: FactStore, report: list[dict[str, Any]]) -> None:
    if not isinstance(d, dict):
        return
    if "subject" in d:
        _subject(d, "subject", f"{prefix}/subject", store, report)
    if "term" in d:
        _term(d, "term", f"{prefix}/term", store, report)
    if "taxon" in d:
        _taxon(d, "taxon", f"{prefix}/taxon", report)


def elaborate(derivation: Any, store: FactStore) -> tuple[Any, list[dict[str, Any]]]:
    """A deep copy with identifiers canonicalized, plus the sorted rewrite report."""
    out = copy.deepcopy(derivation)
    report: list[dict[str, Any]] = []
    if not isinstance(out, dict):
        return out, report
    _prop_positions(out.get("goal"), "goal", store, report)
    steps = out.get("steps")
    if isinstance(steps, list):
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            _prop_positions(step.get("conclusion"), f"steps/{i}/conclusion", store, report)
            edge = step.get("edge")
            if isinstance(edge, list):
                for j in range(min(len(edge), 2)):
                    _term(edge, j, f"steps/{i}/edge/{j}", store, report)
    report.sort(key=lambda e: e["path"])
    return out, report


def elaborate_and_check(derivation: Any, store: FactStore) -> dict[str, Any]:
    """The CLI's path: elaborate, check, attach the rewrite report to the verdict."""
    canonical, report = elaborate(derivation, store)
    verdict = check(canonical, store)
    verdict["elaboration"] = report
    return verdict
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_elaborate.py -q`
Expected: 7 passed

- [ ] **Step 5: Mutation checks**

- In `_subject`, resolve when `len(candidates) >= 1` using `candidates[0]` → `test_ambiguous_symbol_is_not_resolved` fails. Revert.
- In `_term`, also rewrite an obsolete term to `term.replaced_by[0]` → `test_obsolete_term_is_not_silently_replaced` fails. Revert.
- Remove the `_record` call in `_taxon` → `test_every_rewrite_is_reported_with_its_path` fails. Revert.
- Remove the `edge` loop → `test_symbol_alt_id_and_taxon_are_rewritten_and_reported_with_paths` fails on `steps/1/edge/1`. Revert.
- Replace `copy.deepcopy(derivation)` with `derivation` → `test_input_is_not_mutated` fails. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/elaborate.py tests/test_biolean_elaborate.py
git commit -m "feat(biolean): elaborator — symbol, alt_id and taxon rewrites, reported by path

Mutation checked: first-candidate symbol, obsolete replaced, unreported taxon,
edge endpoints skipped, input mutated.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 10: Tactics — goals, applicable rules, the mechanical prover (`tactics.py`)

**Files:**
- Create: `src/methods_graph/biolean/tactics.py`
- Test: `tests/test_biolean_tactics.py`

**Interfaces:**
- Consumes: `FactStore`, `Prop`, `PROPAGATING_RELATIONS`, `NAMESPACE_ASPECT`, `kernel.check`, `kernel.ancestors`.
- Produces: `goals_for(subject, store, *, aspect=None) -> tuple[list[dict], dict[str, int]]` (each goal `{"prop": dict, "direct": bool, "depth": int}`, sorted by `(term, qualifier, taxon)`; report keys `skipped_negated`, `skipped_obsolete`, `skipped_unknown_term`); `applicable(prop, store) -> list[dict]` (step fragments, sorted); `prove(prop, store) -> dict | None` (a checkable derivation).

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_tactics.py`:

```python
from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Prop
from methods_graph.biolean.store import MaskedFactStore
from methods_graph.biolean.tactics import applicable, goals_for, prove
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, B, C, D, MF1, MF2, P1, P2, P3, P5, P7, R, T, TAX, X, Y

STORE = mini_store()


def _p(term, subject=P1, qualifier="involved_in", negated=False):
    return Prop(subject, qualifier, term, TAX, negated)


def _goal_terms(subject, **kw):
    goals, _ = goals_for(subject, STORE, **kw)
    return {(g["prop"]["term"], g["direct"], g["depth"]) for g in goals}


def test_goals_are_the_upward_closure_with_direct_flag_and_shortest_depth():
    goals = _goal_terms(P2)
    assert goals == {(X, True, 0), (Y, True, 0), (T, True, 0)}
    goals = _goal_terms(P7)
    assert (R, True, 0) in goals and (C, False, 1) not in goals   # regulates does not lift


def test_goals_exclude_negated_annotations():
    goals, report = goals_for(P2, STORE)
    assert all(not g["prop"]["negated"] for g in goals)
    assert report["skipped_negated"] == 1


def test_goals_skip_obsolete_term_annotations_and_count_them():
    goals, report = goals_for(P5, STORE)
    assert goals == [] and report["skipped_obsolete"] == 1
    _, report = goals_for(P7, STORE)
    assert report["skipped_unknown_term"] == 1


def test_goals_depth_is_shortest_over_the_diamond():
    goals, _ = goals_for(P1, STORE)
    depth = {g["prop"]["term"]: g["depth"] for g in goals}
    assert depth[A] == 0 and depth[C] == 0                    # C is also direct
    goals, _ = goals_for("UniProtKB:P00008", STORE)             # annotated at A only
    depth = {g["prop"]["term"]: g["depth"] for g in goals}
    assert depth == {A: 0, B: 1, C: 1, D: 1}                    # C via part_of, not via B


def test_goals_are_sorted_and_aspect_filtered():
    goals, _ = goals_for(P3, STORE, aspect="F")
    assert [g["prop"]["term"] for g in goals] == [MF1, MF2]
    assert goals_for(P3, STORE, aspect="P")[0] == []


def test_applicable_lists_axiom_and_child_fragments_and_never_regulates():
    frags = applicable(_p(C), STORE)
    rules = sorted((f["rule"], f.get("edge", [None])[0]) for f in frags)
    assert ("axiom", None) in rules
    assert ("is_a", B) in rules and ("is_a", D) in rules and ("part_of", A) in rules
    assert not any(f["rule"] == "regulates" for f in frags)
    assert frags == sorted(frags, key=lambda f: (f["rule"], f.get("edge", [])))
    assert applicable(_p(C, subject=P7), STORE) == []          # P00007 sits at R only


def test_prove_returns_the_shortest_derivation():
    d = prove(_p(C, subject="UniProtKB:P00008"), STORE)
    assert d is not None
    assert [s["rule"] for s in d["steps"]] == ["axiom", "part_of"]
    assert d["steps"][1]["edge"] == [A, C]
    assert check(d, STORE)["errors"] == []


def test_prove_is_shortest_over_all_direct_annotations():
    d = prove(_p(T, subject=P2), STORE)
    assert [s["rule"] for s in d["steps"]] == ["axiom"] or d["steps"][0]["conclusion"]["term"] == T
    hidden = MaskedFactStore(STORE, frozenset(a.id for a in STORE.annotations(P2) if a.term == T))
    d = prove(_p(T, subject=P2), hidden)
    assert d["steps"][0]["conclusion"]["term"] == Y                # not X, though X sorts first
    assert len(d["steps"]) == 2 and check(d, hidden)["errors"] == []


def test_prove_tie_break_is_sorted_term_id():
    d = prove(_p(C, subject=P1), STORE)
    assert [s["rule"] for s in d["steps"]] == ["axiom"]           # direct wins
    masked = MaskedFactStore(
        STORE, frozenset(a.id for a in STORE.annotations(P1) if a.term == C and not a.negated))
    d = prove(_p(C, subject=P1), masked)
    # depth-1 routes: B is_a C, D is_a C, A part_of C — starting terms sorted: B < D < A
    assert d["steps"][0]["conclusion"]["term"] == B and d["steps"][1]["rule"] == "is_a"


def test_prove_returns_none_when_nothing_reaches_the_target():
    assert prove(_p(C, subject=P7), STORE) is None
    assert prove(_p(C, negated=True), STORE) is None
    assert prove(_p("GO:0009999"), STORE) is None


def test_prove_output_is_accepted_by_the_kernel():
    for subject, term, qualifier in ((P1, B, "involved_in"), (P2, T, "involved_in"),
                                     (P3, MF1, "enables"), ("UniProtKB:P00004", "GO:0000300", "located_in")):
        d = prove(Prop(subject, qualifier, term, TAX, False), STORE)
        assert d is not None and check(d, STORE)["errors"] == [], (subject, term)
        assert d["goal"] == Prop(subject, qualifier, term, TAX, False).to_dict()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_tactics.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/methods_graph/biolean/tactics.py`:

```python
"""Untrusted convenience over the kernel: what can be proved, and how.

``goals_for`` enumerates every well-typed proposition derivable for a subject, ``applicable``
lists the rule applications that would conclude a proposition now, and ``prove`` is the
mechanical breadth-first prover (the gold baseline). Every derivation ``prove`` emits is
accepted by the kernel; a test pins that.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from methods_graph.biolean.props import NAMESPACE_ASPECT, PROPAGATING_RELATIONS, Prop
from methods_graph.biolean.store import FactStore

_REPORT_KEYS = ("skipped_negated", "skipped_obsolete", "skipped_unknown_term")


def _live_parents(term_id: str, store: FactStore) -> list[tuple[str, str]]:
    """(parent, relation) over propagating relations within namespace, sorted by parent id."""
    start = store.term(term_id)
    if start is None:
        return []
    out: list[tuple[str, str]] = []
    for e in store.parents(term_id):
        if e.relation not in PROPAGATING_RELATIONS:
            continue
        parent = store.term(e.parent)
        if parent is None or parent.obsolete or parent.namespace != start.namespace:
            continue
        out.append((e.parent, e.relation))
    return sorted(out)


def _starts(subject: str, qualifier: str, taxon: str, store: FactStore) -> list[str]:
    """Live, non-negated direct annotation terms of the subject under (qualifier, taxon)."""
    terms: set[str] = set()
    for a in store.annotations(subject):
        if a.negated or a.qualifier != qualifier or a.taxon != taxon:
            continue
        t = store.term(a.term)
        if t is None or t.obsolete:
            continue
        terms.add(a.term)
    return sorted(terms)


def goals_for(
    subject: str, store: FactStore, *, aspect: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    depth: dict[tuple[str, str, str], int] = {}
    direct: set[tuple[str, str, str]] = set()
    for a in store.annotations(subject):
        if a.negated:
            report["skipped_negated"] += 1
            continue
        t = store.term(a.term)
        if t is None:
            report["skipped_unknown_term"] += 1
            continue
        if t.obsolete:
            report["skipped_obsolete"] += 1
            continue
        if aspect is not None and NAMESPACE_ASPECT.get(t.namespace) != aspect:
            continue
        key = (a.qualifier, a.term, a.taxon)
        direct.add(key)
        depth[key] = 0
        queue: deque[tuple[str, int]] = deque([(a.term, 0)])
        while queue:
            cur, d = queue.popleft()
            for parent, _relation in _live_parents(cur, store):
                k = (a.qualifier, parent, a.taxon)
                if k in depth and depth[k] <= d + 1:
                    continue
                depth[k] = d + 1
                queue.append((parent, d + 1))
    goals = [
        {"prop": Prop(subject, q, t, tax, False).to_dict(), "direct": (q, t, tax) in direct,
         "depth": depth[(q, t, tax)]}
        for (q, t, tax) in sorted(depth, key=lambda k: (k[1], k[0], k[2]))
    ]
    return goals, report


def applicable(prop: Prop, store: FactStore) -> list[dict[str, Any]]:
    """Rule applications that would conclude ``prop`` against this store, sorted."""
    if prop.negated:
        return []
    frags: list[dict[str, Any]] = []
    if store.matching(prop):
        frags.append({"rule": "axiom", "conclusion": prop.to_dict()})
    derivable = {(g["prop"]["term"]) for g in goals_for(prop.subject, store)[0]
                 if g["prop"]["qualifier"] == prop.qualifier and g["prop"]["taxon"] == prop.taxon}
    target = store.term(prop.term)
    if target is not None and not target.obsolete:
        for e in store.children(prop.term):
            if e.relation not in PROPAGATING_RELATIONS or e.child not in derivable:
                continue
            child = store.term(e.child)
            if child is None or child.obsolete or child.namespace != target.namespace:
                continue
            frags.append({"rule": e.relation, "edge": [e.child, prop.term],
                          "conclusion": prop.to_dict()})
    return sorted(frags, key=lambda f: (f["rule"], f.get("edge", [])))


def prove(prop: Prop, store: FactStore) -> dict[str, Any] | None:
    """Shortest derivation of ``prop`` by multi-source breadth-first search, or ``None``.

    Starts simultaneously from every direct annotation of the subject under the same
    qualifier and taxon, expands parents in sorted term-id order, and reconstructs the first
    path that reaches the target. Ties are therefore broken by sorted term id.
    """
    if prop.negated:
        return None
    target = store.term(prop.term)
    if target is None or target.obsolete:
        return None
    starts = _starts(prop.subject, prop.qualifier, prop.taxon, store)
    if not starts:
        return None
    came_from: dict[str, tuple[str, str] | None] = {s: None for s in starts}
    queue: deque[str] = deque(starts)
    found: str | None = prop.term if prop.term in came_from else None
    while queue and found is None:
        cur = queue.popleft()
        for parent, relation in _live_parents(cur, store):
            if parent in came_from:
                continue
            came_from[parent] = (cur, relation)
            if parent == prop.term:
                found = parent
                break
            queue.append(parent)
    if found is None:
        return None
    chain: list[tuple[str, str, str]] = []     # (child, relation, parent), root-most last
    node = found
    while came_from[node] is not None:
        child, relation = came_from[node]        # type: ignore[misc]
        chain.append((child, relation, node))
        node = child
    chain.reverse()
    start = node
    steps: list[dict[str, Any]] = [{
        "id": "s1", "rule": "axiom",
        "conclusion": Prop(prop.subject, prop.qualifier, start, prop.taxon, False).to_dict(),
    }]
    for i, (child, relation, parent) in enumerate(chain, start=2):
        steps.append({
            "id": f"s{i}", "rule": relation, "premises": [f"s{i - 1}"], "edge": [child, parent],
            "conclusion": Prop(prop.subject, prop.qualifier, parent, prop.taxon, False).to_dict(),
        })
    return {"biolean": "0.1", "goal": prop.to_dict(), "steps": steps, "root": steps[-1]["id"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_tactics.py -q`
Expected: 11 passed

- [ ] **Step 5: Mutation checks**

- In `goals_for`, replace the `deque` with a list popped from the end (depth-first, last-sorted-first) and drop the `depth[k] <= d + 1` guard's `<=` (record first path found) → `test_goals_depth_is_shortest_over_the_diamond` fails (`C` at depth 2 via `B`). Also try `queue.pop(0)` after inserting parents in reverse (first-sorted-first DFS) → still fails. Revert.
- In `prove`, replace `queue.popleft()` with `queue.pop()` → `test_prove_returns_the_shortest_derivation` fails (route via D). Revert.
- In `prove`, run the search from each start in turn and return the first success → `test_prove_is_shortest_over_all_direct_annotations` fails (X is tried first and yields depth 2). Revert.
- In `prove`, iterate `store.parents(cur)` unsorted (insertion order) instead of `_live_parents` → `test_prove_tie_break_is_sorted_term_id` fails only if insertion order differs from sorted; the fixture lists `A part_of C` before `A part_of D` in the OBO, and starts `B < D < A` come from a sorted set, so instead mutate `_starts` to return `sorted(terms, reverse=True)` → the test fails (start `A`, rule `part_of`). Revert.
- In `prove`, build each propagation step with `"conclusion"` copied from the previous step → `test_prove_output_is_accepted_by_the_kernel` fails with `CONCLUSION_MISMATCH`. Revert.
- In `applicable`, drop the `e.relation not in PROPAGATING_RELATIONS` guard → `test_applicable_lists_axiom_and_child_fragments_and_never_regulates` fails only if `R` is derivable for `P1`, which it is not; so also mutate `derivable` to `{e.child for e in store.children(prop.term)}` → the test fails on the `regulates` fragment. Revert.
- In `goals_for`, remove the `a.negated` branch → `test_goals_exclude_negated_annotations` fails. Revert.
- Remove the `t.obsolete` branch → `test_goals_skip_obsolete_term_annotations_and_count_them` fails. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/biolean/tactics.py tests/test_biolean_tactics.py
git commit -m "feat(biolean): goals_for, applicable, and the breadth-first prover

Mutation checked: DFS in both orders, per-start search, reversed starts,
stale conclusions, regulates in applicable, negated/obsolete included.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Rendering (`render.py`)

**Files:**
- Create: `src/methods_graph/biolean/render.py`
- Test: `tests/test_biolean_render.py`

**Interfaces:**
- Consumes: `FactStore`, `Prop`, `evidence_class`.
- Produces: `render_derivation(derivation, store) -> str` (one line per step), `render_verdict(verdict) -> str` (one line per error with its first suggestion, or the acceptance line).

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_render.py`:

```python
from methods_graph.biolean.elaborate import elaborate_and_check
from methods_graph.biolean.render import render_derivation, render_verdict
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, C, GOLDEN, P1, axiom, deriv, prop, prop_step, sorry

STORE = mini_store()


def test_render_derivation_names_terms_and_subjects_and_marks_sorry():
    d = deriv(prop(C), [axiom("s1", A, code="IDA"), prop_step("s2", "part_of", "s1", A, C), sorry("s3", C)], "s2")
    text = render_derivation(d, STORE)
    lines = text.splitlines()
    assert lines[0].startswith("s1: axiom") and "GA (UniProtKB:P00001)" in lines[0] and "A (GO:0000030)" in lines[0] and "[IDA]" in lines[0]
    assert lines[1].startswith("s2: part_of") and "because A (GO:0000030) part_of C (GO:0000010)" in lines[1]
    assert lines[2].startswith("s3: sorry") and "m:deseq2" in lines[2] and "unverified" in lines[2]
    assert lines[-1] == "root: s2 proves GA (UniProtKB:P00001) involved_in C (GO:0000010) in NCBITaxon:9606"


def test_render_derivation_survives_unknown_ids_and_bad_shapes():
    text = render_derivation(deriv(prop("GO:0009999"), [axiom("s1", "GO:0009999")], "s1"), STORE)
    assert "GO:0009999" in text
    assert render_derivation("nope", STORE) == "unrenderable: not a derivation object"
    assert "s?: ?" in render_derivation({"goal": {}, "steps": [1], "root": "x"}, STORE)


def test_render_verdict_accepted_and_rejected():
    ok = elaborate_and_check(deriv(prop(A), [axiom("s1", A)], "s1"), STORE)
    assert render_verdict(ok).splitlines()[0] == "ACCEPTED: 1 step, 0 sorry, 1 conflict"
    bad = elaborate_and_check(GOLDEN, STORE)
    lines = render_verdict(bad).splitlines()
    assert lines[0] == "REJECTED: 9 steps, 1 error, 2 unused sorry, 5 unused steps"
    assert any(line.startswith("  s2 AXIOM_NOT_FOUND:") for line in lines)


def test_render_verdict_shows_the_first_suggestion_and_elaboration():
    v = elaborate_and_check(deriv(prop(C), [axiom("s1", A), prop_step("s2", "is_a", "s1", A, "GO:0000011")], "s2"), STORE)
    text = render_verdict(v)
    assert "suggest: part_of [GO:0000030, GO:0000010]" in text
    assert "elaborated: steps/1/edge/1 GO:0000011 -> GO:0000010 (ALT_ID_RESOLVED)" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_render.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/methods_graph/biolean/render.py`:

```python
"""Prose for humans reviewing a derivation, and text an agent reads for a verdict."""
from __future__ import annotations

import json
from typing import Any

from methods_graph.biolean.store import FactStore


def _name(term_id: Any, store: FactStore) -> str:
    if not isinstance(term_id, str):
        return "?"
    t = store.term(term_id)
    return f"{t.name} ({term_id})" if t is not None else term_id


def _subject(subject: Any, store: FactStore) -> str:
    if not isinstance(subject, str):
        return "?"
    anns = store.annotations(subject)
    return f"{anns[0].symbol} ({subject})" if anns else subject


def _prop(p: Any, store: FactStore) -> str:
    if not isinstance(p, dict):
        return "?"
    neg = "NOT " if p.get("negated") is True else ""
    return (f"{_subject(p.get('subject'), store)} {neg}{p.get('qualifier', '?')} "
            f"{_name(p.get('term'), store)} in {p.get('taxon', '?')}")


def render_derivation(derivation: Any, store: FactStore) -> str:
    if not isinstance(derivation, dict) or not isinstance(derivation.get("steps"), list):
        return "unrenderable: not a derivation object"
    lines: list[str] = []
    for step in derivation["steps"]:
        if not isinstance(step, dict):
            lines.append("s?: ? (not an object)")
            continue
        sid, rule = step.get("id", "s?"), step.get("rule", "?")
        concl = _prop(step.get("conclusion"), store)
        if rule == "axiom":
            code = f" [{step['code']}]" if isinstance(step.get("code"), str) else ""
            lines.append(f"{sid}: axiom — {concl}{code}")
        elif rule in ("is_a", "part_of") and isinstance(step.get("edge"), list) and len(step["edge"]) == 2:
            child, parent = step["edge"]
            lines.append(f"{sid}: {rule} — because {_name(child, store)} {rule} {_name(parent, store)}, {concl}")
        elif rule == "sorry":
            prov = step.get("provenance") if isinstance(step.get("provenance"), dict) else {}
            method = prov.get("method", "?")
            inputs = ", ".join(str(i) for i in prov.get("inputs", [])) if isinstance(prov.get("inputs"), list) else "?"
            lines.append(f"{sid}: sorry — {concl} via {method} on {inputs} (unverified)")
        else:
            lines.append(f"{sid}: {rule} — {concl}")
    lines.append(f"root: {derivation.get('root', '?')} proves {_prop(derivation.get('goal'), store)}")
    return "\n".join(lines)


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 or noun == "sorry" else "s")


def render_verdict(verdict: dict[str, Any]) -> str:
    lines: list[str] = []
    n_steps = verdict.get("steps_checked", 0)
    if verdict.get("verdict") == "ACCEPTED":
        lines.append(f"ACCEPTED: {_plural(n_steps, 'step')}, {verdict.get('sorry_count', 0)} sorry, "
                     f"{_plural(len(verdict.get('conflicts', [])), 'conflict')}")
    else:
        lines.append(f"REJECTED: {_plural(n_steps, 'step')}, {_plural(len(verdict.get('errors', [])), 'error')}, "
                     f"{verdict.get('unused_sorries', 0)} unused sorry, "
                     f"{_plural(len(verdict.get('unused_steps', [])), 'unused step')}")
    for e in verdict.get("errors", []):
        step = e.get("step") or "goal"
        lines.append(f"  {step} {e.get('code')}: {e.get('message')}")
        suggestions = e.get("suggestions") or []
        if suggestions:
            s = suggestions[0]
            if "edge" in s:
                lines.append(f"    suggest: {s['rule']} [{s['edge'][0]}, {s['edge'][1]}]")
            else:
                lines.append(f"    suggest: {s['rule']} {json.dumps(s.get('conclusion'), sort_keys=True)}")
    for c in verdict.get("conflicts", []):
        lines.append(f"  conflict: {c.get('step')} contradicted at {c.get('at')} {c.get('via')} "
                     f"by {c.get('annotation')} [{c.get('code')}]")
    for el in verdict.get("elaboration", []):
        lines.append(f"  elaborated: {el.get('path')} {el.get('before')} -> {el.get('after')} ({el.get('kind')})")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_render.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/biolean/render.py tests/test_biolean_render.py
git commit -m "feat(biolean): prose rendering of derivations and verdicts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---
### Task 12: Fetchers with a pinned GO release (`fetch.py`)

**Files:**
- Modify: `src/methods_graph/fetch.py` (append after `fetch_obi`; add `import gzip`, `import io` to the imports if absent)
- Test: `tests/test_biolean_fetch.py`

**Interfaces:**
- Consumes: `_stdlib_http_get` (existing seam, signature `(url) -> (bytes, headers)`), `hashlib`, `json`, `re`.
- Produces: `GOA_HUMAN_URL`, `GO_BASIC_LATEST_URL`, `ECO_MAPPING_URL`, `go_basic_release_url(release) -> str`, `gaf_header(body: bytes) -> dict[str, str]` (`date_generated`, `go_version`, `go_release`), `fetch_goa_human(dest_dir, *, url=..., fetched_at, http_get=None)`, `fetch_go_basic(dest_dir, *, release, fetched_at, url=None, http_get=None)`, `fetch_eco_mapping(dest_dir, *, url=..., fetched_at, http_get=None)`, `write_biolean_manifest(dest_dir, *, goa_human, go_basic, gaf_eco_mapping, created_at) -> Path`, `fetch_biolean(dest_dir, *, fetched_at, http_get=None) -> dict`. `http_get=None` resolves to `_stdlib_http_get` at call time so a test can monkeypatch the module attribute.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_fetch.py`:

```python
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from methods_graph import fetch

GAF = ("!gaf-version: 2.2\n!generated-by: GOC\n!date-generated: 2026-05-21T08:10\n"
       "!go-version: http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn\n"
       "UniProtKB\tP1\tG\tinvolved_in\tGO:1\tPMID:1\tIDA\t\tP\tg\t\tprotein\ttaxon:9606\t20200101\tUniProt\t\t\n")
OBO = "format-version: 1.2\ndata-version: releases/2026-04-27\n\n[Term]\nid: GO:1\nname: x\nnamespace: biological_process\n"
ECO = "# mapping\nIDA\tDefault\tECO:0000314\n"


def _http(calls):
    def http_get(url):
        calls.append(url)
        if url.endswith("goa_human.gaf.gz"):
            return gzip.compress(GAF.encode()), {}
        if url.endswith("go-basic.obo"):
            return OBO.encode(), {}
        if url.endswith("gaf-eco-mapping.txt"):
            return ECO.encode(), {}
        raise AssertionError(url)
    return http_get


def test_gaf_header_reads_gzipped_and_plain_and_extracts_the_release():
    expect = {"date_generated": "2026-05-21T08:10",
              "go_version": "http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn",
              "go_release": "2026-04-27"}
    assert fetch.gaf_header(gzip.compress(GAF.encode())) == expect
    assert fetch.gaf_header(GAF.encode()) == expect
    assert fetch.gaf_header(b"no header\n") == {"date_generated": "", "go_version": "", "go_release": ""}


def test_go_basic_url_is_pinned_to_the_release_or_latest():
    assert fetch.go_basic_release_url("2026-04-27") == "http://purl.obolibrary.org/obo/go/releases/2026-04-27/go-basic.obo"
    assert fetch.go_basic_release_url(None) == fetch.GO_BASIC_LATEST_URL


def test_fetch_biolean_downloads_the_obo_at_the_gaf_release_and_writes_the_manifest(tmp_path):
    calls = []
    manifest = fetch.fetch_biolean(tmp_path, fetched_at="2026-09-21T00:00:00Z", http_get=_http(calls))
    assert calls == [fetch.GOA_HUMAN_URL,
                     "http://purl.obolibrary.org/obo/go/releases/2026-04-27/go-basic.obo",
                     fetch.ECO_MAPPING_URL]
    assert (tmp_path / "goa_human.gaf.gz").exists() and (tmp_path / "go-basic.obo").read_text() == OBO
    assert (tmp_path / "gaf-eco-mapping.txt").read_text() == ECO
    on_disk = json.loads((tmp_path / "snapshot.json").read_text())
    assert on_disk == manifest
    assert set(manifest) == {"created_at", "sources"}
    assert set(manifest["sources"]) == {"goa_human", "go_basic", "gaf_eco_mapping"}
    assert manifest["sources"]["go_basic"]["version"] == {"data_version": "releases/2026-04-27", "release": "2026-04-27"}
    assert manifest["sources"]["goa_human"]["version"]["go_release"] == "2026-04-27"
    assert manifest["sources"]["go_basic"]["sha256"] == hashlib.sha256(OBO.encode()).hexdigest()
    assert manifest["created_at"] == "2026-09-21T00:00:00Z"
    text = (tmp_path / "snapshot.json").read_text()
    assert text == json.dumps(on_disk, sort_keys=True, indent=2) + "\n"


def test_fetch_biolean_falls_back_to_latest_when_the_gaf_names_no_release(tmp_path):
    calls = []
    plain = GAF.replace("!go-version: http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn\n", "")

    def http_get(url):
        calls.append(url)
        return (gzip.compress(plain.encode()) if url.endswith(".gz") else
                OBO.encode() if url.endswith(".obo") else ECO.encode()), {}
    manifest = fetch.fetch_biolean(tmp_path, fetched_at="t", http_get=http_get)
    assert calls[1] == fetch.GO_BASIC_LATEST_URL
    assert manifest["sources"]["go_basic"]["version"]["release"] == ""


def test_http_get_defaults_resolve_at_call_time(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fetch, "_stdlib_http_get", _http(calls))
    fetch.fetch_eco_mapping(tmp_path, fetched_at="t")
    assert calls == [fetch.ECO_MAPPING_URL]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_fetch.py -q`
Expected: FAIL with `AttributeError: module 'methods_graph.fetch' has no attribute 'gaf_header'`

- [ ] **Step 3: Append to `fetch.py`**

Ensure `import gzip` and `import io` are among the imports, then append after `fetch_obi`:

```python
# ---------------------------------------------------------------------------
# Biolean sources: human GOA, the GO release it was built against, the ECO mapping
# ---------------------------------------------------------------------------

GOA_HUMAN_URL = "http://geneontology.org/gene-associations/goa_human.gaf.gz"
GO_BASIC_LATEST_URL = "http://purl.obolibrary.org/obo/go/go-basic.obo"
ECO_MAPPING_URL = "http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt"
_GO_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")
_OBO_DATA_VERSION_RE = re.compile(r"^data-version:\s*(.+?)\s*$", re.MULTILINE)


def go_basic_release_url(release: str | None) -> str:
    """The PURL for one GO release, or the moving 'latest' PURL when no release is known."""
    if release is None:
        return GO_BASIC_LATEST_URL
    return f"http://purl.obolibrary.org/obo/go/releases/{release}/go-basic.obo"


def gaf_header(body: bytes) -> dict[str, str]:
    """``date-generated``, ``go-version`` and the release date inside it, from a GAF's ``!`` header.

    Accepts gzipped or plain bytes and reads only the header lines. Missing fields are ``""``.
    """
    fields = {"date_generated": "", "go_version": "", "go_release": ""}
    stream = gzip.GzipFile(fileobj=io.BytesIO(body)) if body[:2] == b"\x1f\x8b" else io.BytesIO(body)
    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("!"):
            break
        key, _, value = line[1:].partition(":")
        key, value = key.strip(), value.strip()
        if key == "date-generated" and not fields["date_generated"]:
            fields["date_generated"] = value
        elif key == "go-version" and not fields["go_version"]:
            fields["go_version"] = value
            match = _GO_RELEASE_RE.search(value)
            fields["go_release"] = match.group(1) if match else ""
    return fields


def _entry(url: str, body: bytes, version: Any, fetched_at: str) -> dict[str, Any]:
    return {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "version": version,
            "fetched_at": fetched_at}


def fetch_goa_human(
    dest_dir: Path, *, url: str = GOA_HUMAN_URL, fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    http_get = http_get or _stdlib_http_get
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, _headers = http_get(url)
    (dest_dir / "goa_human.gaf.gz").write_bytes(body)
    return _entry(url, body, gaf_header(body), fetched_at)


def fetch_go_basic(
    dest_dir: Path, *, release: str | None, fetched_at: str, url: str | None = None,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    http_get = http_get or _stdlib_http_get
    url = url or go_basic_release_url(release)
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, _headers = http_get(url)
    (dest_dir / "go-basic.obo").write_bytes(body)
    match = _OBO_DATA_VERSION_RE.search(body.decode("utf-8", "replace"))
    version = {"data_version": match.group(1) if match else "", "release": release or ""}
    return _entry(url, body, version, fetched_at)


def fetch_eco_mapping(
    dest_dir: Path, *, url: str = ECO_MAPPING_URL, fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    http_get = http_get or _stdlib_http_get
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, _headers = http_get(url)
    (dest_dir / "gaf-eco-mapping.txt").write_bytes(body)
    return _entry(url, body, "", fetched_at)


def write_biolean_manifest(
    dest_dir: Path, *, goa_human: dict[str, Any], go_basic: dict[str, Any],
    gaf_eco_mapping: dict[str, Any], created_at: str,
) -> Path:
    """``snapshot.json`` in the Biolean snapshot directory, the shape ``write_manifest`` uses."""
    manifest = {"created_at": created_at,
                "sources": {"goa_human": goa_human, "go_basic": go_basic,
                            "gaf_eco_mapping": gaf_eco_mapping}}
    out_path = dest_dir / "snapshot.json"
    out_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return out_path


def fetch_biolean(
    dest_dir: Path, *, fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """GAF first, then the OBO at the release the GAF header names, then the ECO mapping."""
    goa = fetch_goa_human(dest_dir, fetched_at=fetched_at, http_get=http_get)
    release = goa["version"]["go_release"] or None
    obo = fetch_go_basic(dest_dir, release=release, fetched_at=fetched_at, http_get=http_get)
    eco = fetch_eco_mapping(dest_dir, fetched_at=fetched_at, http_get=http_get)
    path = write_biolean_manifest(dest_dir, goa_human=goa, go_basic=obo, gaf_eco_mapping=eco,
                                  created_at=fetched_at)
    return json.loads(path.read_text())
```

`Any` and `Callable` are already imported in `fetch.py`; if not, add `from typing import Any, Callable`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_fetch.py tests/test_fetch.py -q`
Expected: all passed (the existing fetch tests must be untouched)

- [ ] **Step 5: Mutation checks**

- In `fetch_biolean`, pass `release=None` → `test_fetch_biolean_downloads_the_obo_at_the_gaf_release_and_writes_the_manifest` fails on `calls[1]`. Revert.
- In `gaf_header`, drop the gzip branch → the same test fails (header unreadable). Revert.
- In `write_biolean_manifest`, drop `sort_keys=True` → the byte-equality assertion fails only if key order differs; `sources` is inserted before `created_at`? No: change the dict literal so `sources` comes first and drop `sort_keys` → fails. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/fetch.py tests/test_biolean_fetch.py
git commit -m "feat(fetch): Biolean sources — GOA, GO at the GAF's release, ECO mapping, manifest

Mutation checked: unpinned release, gzip header unread, unsorted manifest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: CLI (`mg biolean fetch|check|prove|goals`) and docs

**Files:**
- Modify: `src/methods_graph/cli.py` (add `_BIOLEAN_EXIT`, `_biolean_store`, `_parse_claim`, `cmd_biolean`, the `biolean` subparser, the dispatch branch)
- Modify: `CLAUDE.md` (Layout table row and a run-things line), `README.md` (one short section)
- Test: `tests/test_biolean_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `cli.main(["biolean", ...]) -> int` with exit codes 0 / 2 / 3 per §7.

- [ ] **Step 1: Write the failing tests**

`tests/test_biolean_cli.py`:

```python
import gzip
import json
import shutil
from pathlib import Path

import pytest

from methods_graph import cli, fetch
from tests.test_biolean_kernel import A, C, GOLDEN, axiom, deriv, prop, prop_step

FIX = Path(__file__).parent / "fixtures" / "biolean"


@pytest.fixture
def store_dir(tmp_path):
    shutil.copy(FIX / "go-mini.obo", tmp_path / "go-basic.obo")
    shutil.copy(FIX / "goa-mini.gaf", tmp_path / "goa_human.gaf")
    shutil.copy(FIX / "eco-mini.txt", tmp_path / "gaf-eco-mapping.txt")
    return tmp_path


def _write(tmp_path, derivation):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(derivation))
    return str(p)


def _sorted_json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def test_check_accepted_exits_0_and_prints_sorted_json(store_dir, capsys):
    path = _write(store_dir, deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"))
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "ACCEPTED"


def test_check_rejected_exits_3_and_render_prints_prose(store_dir, capsys):
    path = _write(store_dir, GOLDEN)
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    assert rc == 3 and _sorted_json(capsys.readouterr().out)["verdict"] == "REJECTED"
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir), "--render"])
    assert rc == 3 and capsys.readouterr().out.startswith("REJECTED: 9 steps")


def test_check_elaborates_before_checking(store_dir, capsys):
    path = _write(store_dir, deriv(prop("GO:0000011", subject="GA", taxon="9606"),
                                   [axiom("s1", "GO:0000011", subject="GA", taxon="9606")], "s1"))
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and len(out["elaboration"]) == 6


def test_prove_found_exits_0_and_not_found_exits_3(store_dir, capsys):
    rc = cli.main(["biolean", "prove", "UniProtKB:P00008 involved_in GO:0000010", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and [s["rule"] for s in out["derivation"]["steps"]] == ["axiom", "part_of"]
    rc = cli.main(["biolean", "prove", "GA involved_in GO:0000060", "--store", str(store_dir), "--taxon", "9606"])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 3 and out["derivation"] is None and out["reason"] == "no_derivation"
    assert out["goal"]["subject"] == "UniProtKB:P00001" and out["goal"]["taxon"] == "NCBITaxon:9606"


def test_goals_lists_direct_and_inferred(store_dir, capsys):
    rc = cli.main(["biolean", "goals", "UniProtKB:P00008", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0
    assert {(g["prop"]["term"], g["direct"], g["depth"]) for g in out["goals"]} == {
        ("GO:0000030", True, 0), ("GO:0000005", False, 1), ("GO:0000010", False, 1), ("GO:0000020", False, 1)}
    assert out["report"]["skipped_negated"] == 0


def test_usage_errors_exit_2(tmp_path, store_dir):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "goals", "UniProtKB:P00008", "--store", str(tmp_path / "missing")])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "prove", "two parts", "--store", str(store_dir)])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "prove", "GA involved_in GO:0000010", "--store", str(store_dir), "--taxon", "human"])
    assert ex.value.code == 2


def test_fetch_uses_the_seam_and_writes_the_manifest(tmp_path, monkeypatch, capsys):
    from tests.test_biolean_fetch import _http
    calls = []
    monkeypatch.setattr(fetch, "_stdlib_http_get", _http(calls))
    rc = cli.main(["biolean", "fetch", "--out", str(tmp_path)])
    assert rc == 0 and (tmp_path / "snapshot.json").exists()
    assert "2026-04-27" in calls[1]
    out = _sorted_json(capsys.readouterr().out)
    assert set(out["sources"]) == {"goa_human", "go_basic", "gaf_eco_mapping"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_biolean_cli.py -q`
Expected: FAIL with `SystemExit: 2` (argparse: invalid choice 'biolean')

- [ ] **Step 3: Add the CLI**

In `src/methods_graph/cli.py`, next to `_GUARDRAIL_EXIT`:

```python
_BIOLEAN_EXIT = {"ACCEPTED": 0, "REJECTED": 3}
_BIOLEAN_FILES = ("go-basic.obo", "gaf-eco-mapping.txt")


def _biolean_store(store_dir: Path, parser: argparse.ArgumentParser):
    """Load the Biolean store or exit 2 naming what is missing."""
    from methods_graph.biolean.store import load_store

    gaf = "goa_human.gaf.gz" if (store_dir / "goa_human.gaf.gz").exists() else "goa_human.gaf"
    missing = [name for name in (*_BIOLEAN_FILES, gaf) if not (store_dir / name).exists()]
    if missing:
        parser.error(f"biolean: --store {store_dir} lacks {', '.join(missing)}; "
                     f"run `mg biolean fetch --out {store_dir}`")
    return load_store(store_dir, gaf=gaf)


def _biolean_claim(text: str, taxon: str, parser: argparse.ArgumentParser) -> dict:
    from methods_graph.biolean.props import normalize_taxon

    parts = text.split()
    if len(parts) != 3:
        parser.error("biolean: claim must be 'SUBJECT QUALIFIER TERM', e.g. "
                     "'UniProtKB:P04637 involved_in GO:0006915'")
    normalized = normalize_taxon(taxon)
    if normalized is None:
        parser.error(f"biolean: --taxon must be an NCBI taxon id, got {taxon!r}")
    return {"subject": parts[0], "qualifier": parts[1], "term": parts[2],
            "taxon": normalized, "negated": False}


def cmd_biolean(args, parser: argparse.ArgumentParser) -> int:
    """Dispatch `mg biolean` subcommands. Exit: 0 ok/ACCEPTED, 2 usage, 3 REJECTED/no proof."""
    import datetime as _dt

    if args.biolean_cmd == "fetch":
        from methods_graph.fetch import fetch_biolean

        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = fetch_biolean(args.out, fetched_at=now)
        print(json.dumps(manifest, sort_keys=True, indent=2))
        return 0

    from methods_graph.biolean.elaborate import elaborate, elaborate_and_check
    from methods_graph.biolean.props import Prop
    from methods_graph.biolean.render import render_verdict
    from methods_graph.biolean.tactics import goals_for, prove

    store, _report = _biolean_store(args.store, parser)

    if args.biolean_cmd == "check":
        derivation = json.loads(Path(args.derivation).read_text(encoding="utf-8"))
        verdict = elaborate_and_check(derivation, store)
        print(render_verdict(verdict) if args.render else json.dumps(verdict, sort_keys=True, indent=2))
        return _BIOLEAN_EXIT[verdict["verdict"]]

    if args.biolean_cmd == "prove":
        goal = _biolean_claim(args.claim, args.taxon, parser)
        canonical, elaboration = elaborate({"goal": goal, "steps": [], "root": ""}, store)
        target = Prop.from_dict(canonical["goal"])
        derivation = prove(target, store) if target is not None else None
        if derivation is None:
            print(json.dumps({"derivation": None, "reason": "no_derivation",
                              "goal": canonical["goal"], "elaboration": elaboration},
                             sort_keys=True, indent=2))
            return 3
        print(json.dumps({"derivation": derivation, "elaboration": elaboration},
                         sort_keys=True, indent=2))
        return 0

    if args.biolean_cmd == "goals":
        claim = _biolean_claim(f"{args.subject} involved_in GO:0000000", args.taxon, parser)
        canonical, elaboration = elaborate({"goal": claim, "steps": [], "root": ""}, store)
        subject, taxon = canonical["goal"]["subject"], canonical["goal"]["taxon"]
        goals, report = goals_for(subject, store, aspect=args.aspect)
        goals = [g for g in goals if g["prop"]["taxon"] == taxon]
        print(json.dumps({"subject": subject, "taxon": taxon, "goals": goals, "report": report,
                          "elaboration": elaboration}, sort_keys=True, indent=2))
        return 0

    raise ValueError(f"unknown biolean subcommand: {args.biolean_cmd!r}")
```

In `main()`, after the `bench` parser block:

```python
    p_bl = sub.add_parser("biolean", help="proof checker for GO claims")
    bl_sub = p_bl.add_subparsers(dest="biolean_cmd", required=True)
    bl_fetch = bl_sub.add_parser("fetch", help="download GOA, the GO release it names, the ECO mapping")
    bl_fetch.add_argument("--out", type=Path, default=Path("snapshots/go"))
    bl_check = bl_sub.add_parser("check", help="elaborate and check a derivation JSON file")
    bl_check.add_argument("derivation", type=Path)
    bl_check.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bl_check.add_argument("--render", action="store_true", help="print prose instead of JSON")
    bl_prove = bl_sub.add_parser("prove", help="mechanical derivation of 'SUBJECT QUALIFIER TERM'")
    bl_prove.add_argument("claim")
    bl_prove.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bl_prove.add_argument("--taxon", default="NCBITaxon:9606")
    bl_goals = bl_sub.add_parser("goals", help="derivable propositions for a subject")
    bl_goals.add_argument("subject")
    bl_goals.add_argument("--store", type=Path, default=Path("snapshots/go"))
    bl_goals.add_argument("--taxon", default="NCBITaxon:9606")
    bl_goals.add_argument("--aspect", choices=["F", "P", "C"], default=None)
```

In the dispatch chain, before `return 0`:

```python
    elif args.cmd == "biolean":
        return cmd_biolean(args, parser)
```

`json` and `Path` are already imported in `cli.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_biolean_cli.py tests/test_cli.py -q`
Expected: all passed

- [ ] **Step 5: Mutation check**

Set `_BIOLEAN_EXIT["REJECTED"] = 1` → `test_check_rejected_exits_3_and_render_prints_prose` fails. Revert. Replace `parser.error(...)` in `_biolean_store` with `raise SystemExit("missing")` → `test_usage_errors_exit_2` fails (code is 1). Revert.

- [ ] **Step 6: Docs**

`CLAUDE.md`, Layout table, add a row after `src/methods_graph/bench/`:

```
| `src/methods_graph/biolean/` | Biolean: a structural proof checker for GO claims (`kernel.py` is the only trusted file); `mg biolean fetch|check|prove|goals` |
```

`CLAUDE.md`, "Run things this way" block, add:

```bash
.venv/bin/python -m methods_graph.cli biolean fetch --out snapshots/go   # ~50MB; pins GO to the GAF's release
.venv/bin/python -m methods_graph.cli biolean prove "UniProtKB:P04637 involved_in GO:0006915"
```

`README.md`, a new section before the benchmark section:

```markdown
## Biolean

A proof assistant for biological claims. An agent emits a derivation of a GO claim (axiom,
`is_a`, `part_of`, `sorry`); `mg biolean check` accepts or rejects it against GO and human GOA
with typed errors and suggestions. `mg biolean prove` is the mechanical prover, `mg biolean
goals` lists what is derivable for a gene product. Design: `docs/superpowers/specs/2026-09-21-biolean-design.md`.
```

- [ ] **Step 7: Full suite, with the environment the CI uses**

Run: `env -u OPENAI_API_KEY $PYTEST -q`
Expected: every test passes; the only skips are the pre-existing DB-gated ones.

- [ ] **Step 8: Commit**

```bash
git add src/methods_graph/cli.py tests/test_biolean_cli.py CLAUDE.md README.md
git commit -m "feat(cli): mg biolean fetch|check|prove|goals with 0/2/3 exit codes; docs

Mutation checked: REJECTED mapped to 1, SystemExit instead of parser.error.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Scale check on the real snapshot (skipped in CI)

**Files:**
- Test: `tests/test_biolean_scale.py`

- [ ] **Step 1: Write the test**

```python
"""Runs only when snapshots/go holds the real files. Not a CI gate."""
import random
import time
from pathlib import Path

import pytest

from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Prop, evidence_class
from methods_graph.biolean.store import load_store
from methods_graph.biolean.tactics import prove

SNAP = Path("snapshots/go")
pytestmark = pytest.mark.skipif(
    not all((SNAP / f).exists() for f in ("go-basic.obo", "goa_human.gaf.gz", "gaf-eco-mapping.txt")),
    reason="real GO/GOA snapshot not present")


def test_real_snapshot_loads_fast_and_the_prover_is_sound_over_a_sample():
    t0 = time.monotonic()
    store, report = load_store(SNAP)
    assert time.monotonic() - t0 < 30, report
    assert report["gaf"]["annotations"] > 800_000
    rng = random.Random(0)
    subjects = sorted({a.subject for s in rng.sample(range(1, 40_000), 2_000)
                       for a in store.annotations(f"UniProtKB:P{s:05d}")})[:300]
    tried = accepted = 0
    for subject in subjects:
        for a in store.annotations(subject):
            if a.negated or evidence_class(a.code) not in ("experimental", "high_throughput"):
                continue
            t = store.term(a.term)
            if t is None or t.obsolete:
                continue
            d = prove(Prop(subject, a.qualifier, a.term, a.taxon, False), store)
            tried += 1
            assert d is not None
            assert check(d, store)["errors"] == [], (subject, a.term)
            accepted += 1
            if tried >= 1_000:
                break
        if tried >= 1_000:
            break
    assert tried == accepted >= 200
```

- [ ] **Step 2: Run it against the real snapshot when present**

Run: `$PYTEST tests/test_biolean_scale.py -q -rs`
Expected: passes (or is skipped with the reason above where the snapshot is absent). Note the load time in the commit body.

- [ ] **Step 3: Commit**

```bash
git add tests/test_biolean_scale.py
git commit -m "test(biolean): scale check over the real snapshot, skipped without it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- **§1 records and tables** → Task 1; `alt_ids` addition recorded in the spec.
- **§1 sources, release skew** → Task 12 pins the OBO to the GAF's release; Task 4 counts `term_obsolete`.
- **§2 propositions** → Task 1 `Prop.from_dict` strictness; Task 6 `ALT_ID_IN_KERNEL` at every term position.
- **§3 structure, arity, identifier checks, rules, precedence, checking, verdict shape, error codes, sorted collections** → Tasks 6–8; the precedence sentence amended in Task 6.
- **§4 store protocol, StaticFactStore invariants, MaskedFactStore, loaders and every counter, elaborator positions and kinds** → Tasks 2–5, 9.
- **§5 tactics** → Task 10.
- **§7 layout, fetch, manifest, CLI, exit codes** → Tasks 12–13; `bench/` is Plan 2.
- **§9 kernel/loader/elaborator/tactics/CLI/scale tests** → every named test appears in a task; `test_conflict_at_the_term_is_listed_without_changing_the_verdict` uses an axiom at the term itself because an annotation is listed once against the earliest step.
- **Type consistency**: `parse_gaf(lines, eco_map, primary_id, term)` (Task 4) is what `load_store` calls (Task 5); `check(derivation, store)` (Task 6) is what `elaborate_and_check` (Task 9), `prove`'s test (Task 10) and the CLI (Task 13) call; `MaskedFactStore(base, hidden)` (Task 5) is what Task 10's tests construct; `fetch_biolean(dest_dir, *, fetched_at, http_get=None)` (Task 12) is what `cmd_biolean` calls (Task 13).
- **Placeholders**: none; every step carries its code.

Plan 2 (§6 benchmark, `mg biolean bench build|coverage|run|score`) is written after this plan's Task 8 is merged, against the real `check`/`prove`/`MaskedFactStore` signatures.
