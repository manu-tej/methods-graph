"""The append check (spec §2): axiom, derived and computed bodies against a store.

Every failure is a ``LedgerError`` in the §7 shape. The kernel's ``check_term``,
``check_qualifier_aspect`` and ``check`` are reused and re-emitted; no kernel ``Error`` passes
through. Order of an axiom check: step 1 (shape; nothing else runs on failure), 1a
(characters; its fixes feed every later step), 2, 3, 4, 5, 6, 7 on the cleaned row, then 7a
and 8 on the row with every non-null fix applied, then 9 only when everything passed.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import methods_graph
from methods_graph.biolean.elaborate import elaborate
from methods_graph.biolean.errors import Code
from methods_graph.biolean.gaf import GAF_COLUMNS, annotation_id, parse_gaf
from methods_graph.biolean.kernel import check, check_qualifier_aspect, check_term
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError
from methods_graph.biolean.ledger.format import ASSIGNED_BY_PREFIX, column_character_error
from methods_graph.biolean.props import (
    NAMESPACE_ASPECT, QUALIFIER_ASPECT, Annotation, Prop, Term, normalize_taxon)
from methods_graph.biolean.store import FactStore

# `\Z`, not `$`: `$` also matches just before a final "\n" (as in format.py). Step 1a catches a
# "\n" in a fact column first in append mode, but recheck runs on the row as signed, and nothing
# before check_computed looks at "\n" outside the fact columns.
_DB_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*\Z")
_REFERENCE_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DOI:", re.compile(r"^DOI:10\.[0-9]{4,9}/\S+\Z")),
    ("PMID:", re.compile(r"^PMID:[1-9][0-9]*\Z")),
    ("GO_REF:", re.compile(r"^GO_REF:[0-9]{7}\Z")),
)
# Canonical column 13 value: no leading zero (refinement 22), so one taxon has one spelling and
# a respelled row cannot dodge the step 8 duplicate check.
_TAXON_COL_RE = re.compile(r"^taxon:(?:0|[1-9][0-9]*)\Z")
_ASCII_NCBI_TAXON_RE = re.compile(r"^NCBITaxon:([0-9]+)\Z")
_DATE_RE = re.compile(r"^[0-9]{8}\Z")
_ISO_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_GRAPH_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")
_STATUSES: tuple[str, ...] = ("met", "unknown", "unmet")
_DROP_COUNTERS = ("bad_column_count", "unknown_qualifier", "bad_taxon_cardinality",
                  "bad_taxon_format", "duplicate_row")
_COMPUTED_KEYS: tuple[str, ...] = ("method", "dataset", "graph_hash", "preconditions", "run", "conclusion")


@dataclass
class CheckContext:
    """What the check needs. ``store`` is the base plus admitted ledger facts at append time;
    ``ledger_sources`` names where each admitted ledger annotation lives, for step 8."""
    store: FactStore
    eco_map: Mapping[str, str]
    primary_id: Callable[[str], str | None]
    term: Callable[[str], Term | None]
    key16: str
    ledger_sources: Mapping[str, str] = field(default_factory=dict)
    kernel_version: str = methods_graph.__version__


@dataclass
class AxiomResult:
    errors: list[LedgerError]
    deferred: list[dict[str, Any]]
    fact: list[str] | None            # the final row (column 15 filled) when it parsed
    annotation: Annotation | None
    check: dict[str, Any] | None      # the entry's `check` block, only when ok
    counters: dict[str, int]
    gaf_report: dict[str, int] | None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class DerivedResult:
    errors: list[LedgerError]
    derivation: Any                   # elaborated
    conclusion: dict[str, Any] | None
    check: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        return not self.errors


def _col(i: int) -> str:
    return f"/fact/{i}"


def _sorted_options(values) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def content_key(a: Annotation) -> tuple:
    """Spec §1 "Content key": the parsed fields that make a row a distinct piece of evidence."""
    return (a.subject, a.qualifier, a.negated, a.term, a.taxon, a.references, a.code, a.with_from,
            a.interacting_taxon, a.extension, a.form)


def content_key_json(a: Annotation) -> list[Any]:
    return [a.subject, a.qualifier, a.negated, a.term, a.taxon, list(a.references), a.code,
            list(a.with_from), a.interacting_taxon, a.extension, a.form]


def fact_from_body(body: Any) -> tuple[list[str] | None, list[LedgerError]]:
    """The 17-list from a list body or an object body keyed by column name (spec §7)."""
    if isinstance(body, list):
        return body, []
    if isinstance(body, dict):
        extra = sorted(set(body) - set(GAF_COLUMNS))
        if extra:
            return None, [LedgerError(LedgerCode.LEDGER_BAD_COLUMNS,
                                      f"unknown column key(s): {', '.join(extra)}", "/fact",
                                      got=body, context={"columns": list(GAF_COLUMNS)})]
        return [body.get(name, "") for name in GAF_COLUMNS], []
    return None, [LedgerError(LedgerCode.LEDGER_BAD_BODY,
                              "a fact is a 17-element list or an object keyed by GAF column name",
                              "/fact", got=body)]


# ---------------------------------------------------------------------------
# terms and qualifiers (steps 3 and 4)
# ---------------------------------------------------------------------------

def _live(ids, store: FactStore) -> list[str]:
    out = []
    for t in ids:
        term = store.term(t)
        if term is not None and not term.obsolete:
            out.append(t)
    return sorted(set(out))


def _obsolete(term_id: str, store: FactStore, field_: str, got: str, prefix: str, code: str) -> LedgerError:
    """fix = the single live replaced_by; else options = several live replaced_by, else the live
    consider terms (even one), else []. Never an obsolete or non-term id."""
    term = store.term(term_id)
    assert term is not None
    replaced = _live(term.replaced_by, store)
    consider = _live(term.consider, store)
    context = {"replaced_by": list(term.replaced_by), "consider": list(term.consider)}
    if len(replaced) == 1:
        return LedgerError(code, f"{prefix}; replaced by {replaced[0]}", field_, got=got,
                           fix=replaced[0], context=context)
    options = replaced if len(replaced) > 1 else consider
    what = "choose one of replaced_by" if replaced else ("consider one of these" if consider else "no live replacement")
    return LedgerError(code, f"{prefix}; {what}", field_, got=got, options=tuple(options), context=context)


def term_errors(term_id: str, store: FactStore, field_: str) -> list[LedgerError]:
    """Spec §2 step 3 over the kernel's check_term; [] for a live primary id. The kernel stops
    at an alt id, so an alt id's primary is checked again here."""
    errs = check_term(term_id, store, None)
    if not errs:
        return []
    err = errs[0]
    if err.code == Code.UNKNOWN_TERM:
        return [LedgerError(LedgerCode.UNKNOWN_TERM, f"unknown term {term_id}", field_, got=term_id)]
    if err.code == Code.ALT_ID_IN_KERNEL:
        primary = err.expected
        if not check_term(primary, store, None):
            return [LedgerError(LedgerCode.LEDGER_ALT_ID, f"{term_id} is an alt_id of {primary}",
                                field_, got=term_id, fix=primary)]
        return [_obsolete(primary, store, field_, term_id,
                          f"{term_id} is an alt_id of {primary}, which is obsolete", LedgerCode.LEDGER_ALT_ID)]
    return [_obsolete(term_id, store, field_, term_id, f"{term_id} is obsolete", LedgerCode.OBSOLETE_TERM)]


def qualifier_options(aspect: str | None, prefix: str = "") -> tuple[str, ...]:
    """The qualifiers legal for ``aspect`` (all 13 when None), each carrying ``prefix``."""
    return _sorted_options(prefix + q for q, a in QUALIFIER_ASPECT.items() if aspect is None or a == aspect)


def _real_date(yyyymmdd: str) -> bool:
    try:
        _dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))
    except ValueError:
        return False
    return True


def _ascii_taxon_digits(raw: str) -> str | None:
    """The digits of ``raw`` when ``normalize_taxon`` accepts it and every digit is ASCII 0-9;
    else None. ``normalize_taxon`` accepts any ``str.isdigit()`` character, and ``int()`` refuses
    some of them (U+00B2), so a non-ASCII digit is treated as a non-numeric taxon: no fix."""
    normalized = normalize_taxon(raw)
    m = _ASCII_NCBI_TAXON_RE.match(normalized) if normalized is not None else None
    return m.group(1) if m else None


def _key_pointer(key: str) -> str:
    """The RFC 6901 pointer to a top-level body key: ``~`` is ``~0`` and ``/`` is ``~1``."""
    return "/" + key.replace("~", "~0").replace("/", "~1")


def _utf8_encodable(s: str) -> bool:
    """False for a string holding a lone surrogate, the only str that UTF-8 cannot encode."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# axiom
# ---------------------------------------------------------------------------

def check_axiom(fact: Any, ctx: CheckContext, *, mode: str = "append") -> AxiomResult:
    """Spec §2 ``axiom``.

    ``append``: steps 1-9 with fix application; ``fact`` is the final row with column 15 filled.
    ``recheck`` (spec §3 base binding): steps 1-7a on the row as signed, no fix applied, column 15
    must equal ``biolean:<ctx.key16>``, no duplicate or contested step; ``annotation`` is set
    whenever the row round-trips so the loader can test supersession even for a stale row.
    """
    if mode not in ("append", "recheck"):
        raise ValueError(mode)
    counters = {"new_subject": 0}
    # step 1
    if not (isinstance(fact, list) and len(fact) == len(GAF_COLUMNS) and all(isinstance(c, str) for c in fact)):
        err = LedgerError(LedgerCode.LEDGER_BAD_COLUMNS, "fact must be exactly 17 string columns in GAF 2.2 order",
                          "/fact", got=fact,
                          context={"columns": list(GAF_COLUMNS)})
        return AxiomResult([err], [], None, None, None, counters, None)

    errors: list[LedgerError] = []
    deferred: list[dict[str, Any]] = []
    fixes: dict[int, str] = {}
    unfixable: set[int] = set()

    def emit(err: LedgerError) -> None:
        errors.append(err)
        col = int(err.field[len("/fact/"):])
        if err.fix is None:
            unfixable.add(col)
        else:
            fixes[col] = err.fix

    # step 1a: the cleaned row is what every later step sees (plan refinement 1)
    row = list(fact)
    for i, value in enumerate(fact):
        err = column_character_error(i, value)
        if err is not None:
            emit(err)
            if mode == "append":
                row[i] = err.fix

    # step 2
    db_ok = bool(row[0]) and _DB_RE.match(row[0]) is not None
    id_ok = bool(row[1]) and not any(c.isspace() for c in row[1]) and "|" not in row[1]
    if not db_ok:
        emit(LedgerError(LedgerCode.LEDGER_BAD_SUBJECT, "column 1 must match ^[A-Za-z][A-Za-z0-9_.-]*$",
                         _col(0), got=row[0]))
    if not id_ok:
        emit(LedgerError(LedgerCode.LEDGER_BAD_SUBJECT, "column 2 must be non-empty with no whitespace or |",
                         _col(1), got=row[1]))
    subject = f"{row[0]}:{row[1]}"
    known_subject = ctx.store.subject_exists(subject)
    if db_ok and id_ok and not known_subject:
        counters["new_subject"] = 1

    # step 3
    errs3 = term_errors(row[4], ctx.store, _col(4))
    for err in errs3:
        emit(err)
    resolved_term: str | None = row[4] if not errs3 else (errs3[0].fix if mode == "append" else None)
    term_obj = ctx.store.term(resolved_term) if resolved_term is not None else None
    aspect = NAMESPACE_ASPECT.get(term_obj.namespace) if term_obj is not None else None

    # step 4, qualifier half (always) and aspect half (waits on column 5)
    negated = row[3].startswith("NOT|")
    prefix = "NOT|" if negated else ""
    bare = row[3][4:] if negated else row[3]
    if "|" in bare:
        emit(LedgerError(LedgerCode.UNKNOWN_QUALIFIER, "column 4 is NOT|q or q, with no other |",
                         _col(3), got=row[3]))
    elif bare not in QUALIFIER_ASPECT:
        emit(LedgerError(LedgerCode.UNKNOWN_QUALIFIER, f"unknown qualifier {bare!r}", _col(3),
                         got=row[3], options=qualifier_options(aspect, prefix)))
    if term_obj is None:
        if mode == "append":
            deferred.append({"step": 4, "waits_on": [5]})
    else:
        if bare in QUALIFIER_ASPECT and check_qualifier_aspect(bare, resolved_term, ctx.store):
            emit(LedgerError(LedgerCode.QUALIFIER_ASPECT_MISMATCH,
                             f"{bare} is a {QUALIFIER_ASPECT[bare]}-aspect qualifier; {resolved_term} is {term_obj.namespace}",
                             _col(3), got=row[3], options=qualifier_options(aspect, prefix)))
        if row[8] != aspect:
            emit(LedgerError(LedgerCode.LEDGER_ASPECT_MISMATCH,
                             f"column 9 must be {aspect} for {resolved_term} ({term_obj.namespace})",
                             _col(8), got=row[8], fix=aspect))

    # step 5
    refs = [v for v in row[5].split("|") if v]
    carried = False
    for value in refs:
        for pfx, pattern in _REFERENCE_FORMS:
            if value.startswith(pfx):
                carried = True
                if not pattern.match(value):
                    emit(LedgerError(LedgerCode.LEDGER_BAD_REFERENCE,
                                     f"{value!r} does not match the {pfx} form", _col(5), got=row[5]))
                break
    if not carried:
        emit(LedgerError(LedgerCode.LEDGER_REFERENCE_REQUIRED,
                         "column 6 needs at least one DOI:, PMID: or GO_REF: value", _col(5), got=row[5]))
    if row[6] not in ctx.eco_map:
        emit(LedgerError(LedgerCode.LEDGER_ECO_UNMAPPED, f"evidence code {row[6]!r} has no ECO mapping in the base",
                         _col(6), got=row[6], options=_sorted_options(ctx.eco_map)))

    # step 6 (by column: 12, 13, 14)
    if not row[11]:
        fix = None
        if known_subject:
            anns = ctx.store.annotations(subject)          # sorted by id; refinement 8
            fix = anns[0].object_type or None
        emit(LedgerError(LedgerCode.LEDGER_BAD_OBJECT_TYPE, "column 12 must be non-empty", _col(11),
                         got=row[11], fix=fix))
    taxa = row[12].split("|")
    if len(taxa) not in (1, 2) or not all(_TAXON_COL_RE.match(t) for t in taxa):
        digits = [_ascii_taxon_digits(t) for t in taxa]
        if len(taxa) in (1, 2) and all(d is not None for d in digits):
            # Not str(int(d)): int() refuses more than 4300 digits (CPython's default limit).
            fix = "|".join("taxon:" + (d.lstrip("0") or "0") for d in digits)
            emit(LedgerError(LedgerCode.LEDGER_BAD_TAXON,
                             "column 13 values must be spelled taxon:<digits>, with no leading zero",
                             _col(12), got=row[12], fix=fix))
        else:
            emit(LedgerError(LedgerCode.LEDGER_BAD_TAXON, "column 13 is one or two |-separated taxon:<digits> values",
                             _col(12), got=row[12], context={"form": "taxon:<digits>"}))
    date = row[13]
    if not (_DATE_RE.match(date) and _real_date(date)):
        m = _ISO_DATE_RE.match(date)
        iso = m.group(1) + m.group(2) + m.group(3) if m else None
        if iso is not None and _real_date(iso):
            emit(LedgerError(LedgerCode.LEDGER_BAD_DATE, "column 14 must be YYYYMMDD", _col(13), got=date, fix=iso))
        else:
            emit(LedgerError(LedgerCode.LEDGER_BAD_DATE, "column 14 must be YYYYMMDD, a real date", _col(13),
                             got=date, context={"form": "YYYYMMDD"}))

    # step 7
    expected_by = ASSIGNED_BY_PREFIX + ctx.key16
    if row[14] != expected_by and (mode == "recheck" or row[14] != ""):
        emit(LedgerError(LedgerCode.LEDGER_ASSIGNED_BY, f"column 15 must be {expected_by} (or empty, to be filled)",
                         _col(14), got=row[14], fix=expected_by))

    # the final row: every non-null fix applied, column 15 filled (append only)
    final = list(row)
    if mode == "append":
        for i, value in fixes.items():
            final[i] = value
        if final[14] == "":
            final[14] = expected_by
        if unfixable:
            deferred.append({"step": 8, "waits_on": sorted(c + 1 for c in unfixable)})
            return AxiomResult(errors, deferred, None, None, None, counters, None)

    # Steps 7a and 8 hash the row as UTF-8 (annotation_id). Append has cleaned every column at
    # step 1a; recheck hashes the row as signed, and a lone surrogate cannot be encoded. Step 1a
    # has already reported it, so the hashing steps are skipped with no second error.
    if not all(_utf8_encodable(c) for c in final):
        return AxiomResult(errors, deferred, final if mode == "recheck" else None, None, None, counters, None)

    # step 7a. In append mode this LEDGER_MALFORMED (inside an exit-3 REJECTED result) is a defect
    # guard: a row reaches here only after steps 1-7 passed or were fixed, and none of 20,000 fuzzed
    # rows in the final review reached it, so it is unreachable there as far as anyone has found.
    anns, rep = parse_gaf(["\t".join(final)], ctx.eco_map, ctx.primary_id, ctx.term)
    if len(anns) != 1 or any(rep[k] for k in _DROP_COUNTERS) or anns[0].id != annotation_id(final):
        errors.append(LedgerError(LedgerCode.LEDGER_MALFORMED,
                                  "row does not round-trip through parse_gaf as exactly one annotation",
                                  "/fact", got=list(fact)))
        return AxiomResult(errors, deferred, final if mode == "recheck" else None, None, None, counters, rep)
    ann = anns[0]
    if mode == "recheck":
        return AxiomResult(errors, [], final, ann, None, counters, rep)

    # step 8
    key = content_key(ann)
    existing = [{"annotation_id": a.id, "source": ctx.ledger_sources.get(a.id, "base")}
                for a in ctx.store.matching(Prop(ann.subject, ann.qualifier, ann.term, ann.taxon, ann.negated))
                if content_key(a) == key]
    if existing:
        existing.sort(key=lambda e: (e["source"], e["annotation_id"]))
        errors.append(LedgerError(LedgerCode.LEDGER_DUPLICATE, "an identical fact already exists; the row must change",
                                  "/fact", got=list(fact), context={"existing": existing}))
    if errors:
        return AxiomResult(errors, deferred, None, ann, None, counters, rep)

    # step 9
    goal = Prop(ann.subject, ann.qualifier, ann.term, ann.taxon, ann.negated).to_dict()
    verdict = check({"goal": goal, "steps": [{"id": "s1", "rule": "axiom", "conclusion": goal}], "root": "s1"},
                    ctx.store)
    contested_by = sorted({c["annotation"] for c in verdict["conflicts"]})
    block = {"kernel": ctx.kernel_version, "annotation_id": ann.id, "contested_by": contested_by,
             "counters": dict(counters)}
    return AxiomResult([], [], final, ann, block, counters, rep)


# ---------------------------------------------------------------------------
# derived
# ---------------------------------------------------------------------------

def check_derived(body: Any, ctx: CheckContext) -> DerivedResult:
    """Spec §2 ``derived``: the elaborated derivation must be ACCEPTED with no sorry, used or
    unused, and ``conclusion`` must equal the elaborated goal (filled when absent)."""
    shape = 'a derived body is {"derivation": <derivation>, "conclusion"?: <Prop>}'
    # got is the value at field as submitted, or null if absent (spec §7)
    if not isinstance(body, dict):
        return DerivedResult([LedgerError(LedgerCode.LEDGER_BAD_BODY, shape, "/derivation", got=None)],
                             None, None, None)
    body_errors = [] if "derivation" in body else [
        LedgerError(LedgerCode.LEDGER_BAD_BODY, shape, "/derivation", got=None)]
    for k in sorted(set(body) - {"derivation", "conclusion"}):
        body_errors.append(LedgerError(LedgerCode.LEDGER_BAD_BODY, f"unknown key {k!r}; {shape}", _key_pointer(k),
                                       got=body[k]))
    if body_errors:
        return DerivedResult(body_errors, None, None, None)
    elaborated, report = elaborate(body["derivation"], ctx.store)
    verdict = check(elaborated, ctx.store)
    errors: list[LedgerError] = []
    if verdict["verdict"] != "ACCEPTED":
        errors.append(LedgerError(LedgerCode.LEDGER_DERIVATION_REJECTED,
                                  "the kernel rejected the derivation; iterate on context.kernel.errors",
                                  "/derivation", got=None,
                                  context={"kernel": {"errors": verdict["errors"], "elaboration": report}}))
    index_of: dict[str, int] = {}
    steps = elaborated.get("steps") if isinstance(elaborated, dict) else None
    if isinstance(steps, list):
        for i, st in enumerate(steps):
            if isinstance(st, dict) and isinstance(st.get("id"), str):
                index_of.setdefault(st["id"], i)
    for s in verdict["sorries"]:
        idx = index_of.get(s["step"])
        code = LedgerCode.LEDGER_SORRY_USED if s["used"] else LedgerCode.LEDGER_SORRY_UNUSED
        where = "on" if s["used"] else "off"
        errors.append(LedgerError(code, f"sorry step {s['step']!r} is {where} the used chain; a ledger entry proves from facts only",
                                  f"/derivation/steps/{idx}" if idx is not None else "/derivation", got=s))
    goal = verdict["goal"]
    conclusion = body.get("conclusion", goal)
    if goal is not None and conclusion != goal:
        errors.append(LedgerError(LedgerCode.LEDGER_CONCLUSION_MISMATCH, "conclusion must equal the elaborated goal",
                                  "/conclusion", got=body.get("conclusion"), fix=goal))
    block = {"kernel": ctx.kernel_version,
             "axioms": sorted({a["annotation"] for a in verdict["axioms"]}),
             "conflicts": sorted({c["annotation"] for c in verdict["conflicts"]})}
    return DerivedResult(errors, elaborated, goal, block if goal is not None else None)


# ---------------------------------------------------------------------------
# computed (spec §5): schema-checked, then refused
# ---------------------------------------------------------------------------

def _not_yet() -> LedgerError:
    return LedgerError(LedgerCode.NOT_YET_DISCHARGEABLE,
                       "computed entries are refused until discharge exists (spec §0.3, §5)", None)


def check_computed(body: Any, ctx: CheckContext) -> list[LedgerError]:
    if not isinstance(body, dict):
        return [LedgerError(LedgerCode.LEDGER_BAD_BODY, "a computed body is a JSON object (spec §5)", None, got=body),
                _not_yet()]
    errors: list[LedgerError] = []

    def bad(field_: str, message: str, got: Any, *, fix: Any = None, options=(), context=None) -> None:
        errors.append(LedgerError(LedgerCode.LEDGER_BAD_COMPUTED, message, field_, got=got, fix=fix,
                                  options=tuple(options), context=context))

    for k in _COMPUTED_KEYS:
        if k not in body:
            bad(f"/{k}", f"{k} is required", None)
    for k in sorted(set(body) - set(_COMPUTED_KEYS)):
        bad(_key_pointer(k), f"unknown key {k}", body[k])
    if "method" in body:
        m = body["method"]
        if not (isinstance(m, str) and m.startswith("m:") and len(m) > 2 and m == m.lower() and m == m.strip()
                and not any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in m)):     # Cc: C0, DEL, C1
            bad("/method", "method is m: + the lowercased method name, no surrounding whitespace, no control characters", m)
    if "dataset" in body:
        ds = body["dataset"]
        if not (isinstance(ds, dict) and set(ds) == {"id", "sha256"}):
            bad("/dataset", "dataset is {id, sha256}", ds)
        else:
            for k in ("id", "sha256"):
                if not (isinstance(ds[k], str) and ds[k]):
                    bad(f"/dataset/{k}", f"dataset.{k} is a non-empty string", ds[k])
    if "graph_hash" in body and not (isinstance(body["graph_hash"], str) and _GRAPH_HASH_RE.match(body["graph_hash"])):
        bad("/graph_hash", "graph_hash is sha256:<64 hex>, the methods.lock.json form", body["graph_hash"])
    if "preconditions" in body:
        pre = body["preconditions"]
        if not (isinstance(pre, list) and pre):
            bad("/preconditions", "preconditions is a non-empty list", pre)
        else:
            for i, p in enumerate(pre):
                if not (isinstance(p, dict) and set(p) == {"id", "status", "diagnostic"}):
                    bad(f"/preconditions/{i}", "a precondition is {id, status, diagnostic}", p)
                    continue
                if not (isinstance(p["id"], str) and p["id"]):
                    bad(f"/preconditions/{i}/id", "id is a non-empty string", p["id"])
                if p["status"] not in _STATUSES:
                    bad(f"/preconditions/{i}/status", "status is met, unmet or unknown", p["status"], options=_STATUSES)
                if not isinstance(p["diagnostic"], str):
                    bad(f"/preconditions/{i}/diagnostic", "diagnostic is a string", p["diagnostic"])
    if "run" in body:
        run = body["run"]
        if not (isinstance(run, dict) and set(run) == {"command", "container", "exit_code"}):
            bad("/run", "run is {command, container, exit_code}", run)
        else:
            for k in ("command", "container"):
                if not (isinstance(run[k], str) and run[k]):
                    bad(f"/run/{k}", f"run.{k} is a non-empty string", run[k])
            if type(run["exit_code"]) is not int:
                bad("/run/exit_code", "run.exit_code is a JSON integer, not a boolean", run["exit_code"])
    if "conclusion" in body:
        prop = Prop.from_dict(body["conclusion"])
        if prop is None:
            bad("/conclusion", "conclusion is a Prop: subject, qualifier, term, taxon (strings), negated (bool)",
                body["conclusion"])
        else:
            errors.extend(term_errors(prop.term, ctx.store, "/conclusion/term"))
            term = ctx.store.term(prop.term)
            aspect = NAMESPACE_ASPECT.get(term.namespace) if term is not None and not term.obsolete else None
            for err in check_qualifier_aspect(prop.qualifier, prop.term, ctx.store):
                code = (LedgerCode.UNKNOWN_QUALIFIER if err.code == Code.UNKNOWN_QUALIFIER
                        else LedgerCode.QUALIFIER_ASPECT_MISMATCH)
                errors.append(LedgerError(code, err.message, "/conclusion/qualifier", got=prop.qualifier,
                                          options=qualifier_options(aspect)))
            # Not props.TAXON_RE (the kernel's ^NCBITaxon:\d+$): \d takes any Unicode decimal digit
            # and $ matches before a final "\n". The fix comes from a match of this same pattern,
            # so it always clears the error (spec §2).
            if not _ASCII_NCBI_TAXON_RE.match(prop.taxon):
                digits = _ascii_taxon_digits(prop.taxon)
                fix = "NCBITaxon:" + digits if digits is not None else None
                bad("/conclusion/taxon", "taxon is NCBITaxon:<digits>", prop.taxon, fix=fix,
                    context=None if fix else {"form": "NCBITaxon:<digits>"})
    errors.append(_not_yet())
    return errors
