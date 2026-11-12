"""Loading a ledger beside a base (spec §3): base binding, staleness, supersession, duplicate
content, contested, the ``ledger`` report block, and ``verify --recheck`` for derived entries.

A derived entry adds nothing to the store, so no load re-proves it and none fails on it (plan
refinement 24): only ``--recheck`` re-runs the §2 ``derived`` rule. A failure is listed and
counted, never ``LEDGER_INVALID_ENTRY``; ``same_base`` says whether it failed on the base the
entry names, which is what ``verify|show --recheck`` exit 2 on."""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.kernel import check
from methods_graph.biolean.ledger.check import (
    CheckContext, check_axiom, check_derived, content_key, content_key_json)
from methods_graph.biolean.ledger.errors import BASE_INDEPENDENT_CODES, LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.integrity import LedgerEntry, LedgerState, integrity_report, verify_ledger
from methods_graph.biolean.props import Annotation, Prop
from methods_graph.biolean.store import BaseLoad, FactStore, StaticFactStore, load_base

ADMITTED, STALE, SUPERSEDED, RECORDED = "admitted", "stale", "superseded_by_base", "recorded"

# What reading a present base file can raise: gzip.BadGzipFile is an OSError, a truncated gzip is
# EOFError, a corrupt deflate stream is zlib.error, a non-UTF-8 OBO or ECO file is UnicodeDecodeError.
BASE_READ_ERRORS = (OSError, EOFError, UnicodeDecodeError, zlib.error)


def load_base_or_fail(snapshot_dir: Path, *, obo: str, gaf: str, eco: str) -> BaseLoad:
    """`load_base`, with a present but unreadable base file reported as LEDGER_MALFORMED (exit 2,
    JSON) instead of a traceback (spec §7; plan refinement 18). A missing file is the CLI's usage error."""
    try:
        return load_base(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    except BASE_READ_ERRORS as exc:
        raise LedgerIntegrityError([LedgerError(LedgerCode.LEDGER_MALFORMED,
                                                f"cannot read the store under {snapshot_dir}: {exc}", None,
                                                context={"file": str(snapshot_dir), "line": None})]) from exc


@dataclass
class BoundEntry:
    entry: LedgerEntry
    status: str
    annotation: Annotation | None
    code: str | None                  # the first §2 code, for a stale entry
    base_annotation_id: str | None    # for a superseded entry
    rechecked_ok: bool                # admitted on a base other than the one it names
    gaf_report: dict[str, int] | None


@dataclass
class LoadedLedger:
    state: LedgerState
    base: BaseLoad
    bound: list[BoundEntry]
    report: dict[str, Any]

    @property
    def admitted(self) -> list[BoundEntry]:
        return [b for b in self.bound if b.status == ADMITTED]

    @property
    def sources(self) -> dict[str, str]:
        return {b.annotation.id: f"{b.entry.file}:{b.entry.line}" for b in self.admitted if b.annotation is not None}


def _prop(a: Annotation) -> Prop:
    return Prop(a.subject, a.qualifier, a.term, a.taxon, a.negated)


def _same_base(e: LedgerEntry, base: BaseLoad) -> bool:
    """The entry's ``base`` names the loaded base: its three content digests are the base's."""
    return {k: e.entry["base"][k] for k in ("obo", "gaf", "eco")} == base.digests


def superseded_by(annotation: Annotation, base_store: FactStore) -> str | None:
    """The smallest base annotation id with the same content key (spec §1), or None."""
    key = content_key(annotation)
    ids = sorted(a.id for a in base_store.matching(_prop(annotation)) if content_key(a) == key)
    return ids[0] if ids else None


def bind_entries(state: LedgerState, base: BaseLoad, base_store: FactStore) -> list[BoundEntry]:
    """Spec §3 base binding: re-run §2 steps 1-7a on every axiom entry against the loaded base.
    Invalid (integrity failure) when the base matches or the failing check is base-independent;
    otherwise superseded (tested first), stale, or admitted."""
    errors: list[LedgerError] = []
    bound: list[BoundEntry] = []
    for e in state.entries():
        if e.entry["kind"] != "axiom":
            bound.append(BoundEntry(e, RECORDED, None, None, None, False, None))
            continue
        ctx = CheckContext(store=base_store, eco_map=base.eco_map, primary_id=base.primary_id,
                           term=base.term, key16=e.key16)
        res = check_axiom(e.entry["fact"], ctx, mode="recheck")
        same_base = _same_base(e, base)
        if res.errors and (same_base or any(x.code in BASE_INDEPENDENT_CODES for x in res.errors)):
            # Name the check that makes the entry invalid: on its own base any failure does; on another
            # base only a base-independent one (spec §3), since the rest would have meant `stale`.
            first = res.errors[0] if same_base else next(x for x in res.errors if x.code in BASE_INDEPENDENT_CODES)
            errors.append(LedgerError(LedgerCode.LEDGER_INVALID_ENTRY, f"{first.code}: {first.message}", first.field,
                                      got=first.got, context={"file": e.file, "line": e.line, "code": first.code,
                                                              "same_base": same_base}))
            continue
        ann = res.annotation
        sup = superseded_by(ann, base_store) if ann is not None else None
        if sup is not None:
            bound.append(BoundEntry(e, SUPERSEDED, ann, None, sup, False, res.gaf_report))
        elif res.errors:
            bound.append(BoundEntry(e, STALE, ann, res.errors[0].code, None, False, res.gaf_report))
        else:
            bound.append(BoundEntry(e, ADMITTED, ann, None, None, not same_base, res.gaf_report))
    if errors:
        raise LedgerIntegrityError(errors)
    return bound


def _ledger_gaf_report(bound: list[BoundEntry]) -> dict[str, int]:
    total = parse_gaf([], {}, lambda g: None, lambda g: None)[1]        # every key, all zero
    for b in bound:
        if b.status == ADMITTED and b.gaf_report:
            for k, v in b.gaf_report.items():
                total[k] += v
    return total


def contested_entries(bound: list[BoundEntry], full_store: FactStore) -> list[str]:
    """Admitted axiom entries whose Prop has non-empty kernel conflicts over the loaded store
    (base plus every admitted ledger fact). Recomputed; never read from check.contested_by."""
    out = []
    for b in bound:
        if b.status != ADMITTED or b.annotation is None:
            continue
        goal = _prop(b.annotation).to_dict()
        verdict = check({"goal": goal, "steps": [{"id": "s1", "rule": "axiom", "conclusion": goal}], "root": "s1"},
                        full_store)
        if verdict["conflicts"]:
            out.append(b.annotation.id)
    return sorted(out)


def ledger_report(state: LedgerState, bound: list[BoundEntry], full_store: FactStore) -> dict[str, Any]:
    admitted = [b for b in bound if b.status == ADMITTED]
    groups: dict[tuple, list[str]] = {}
    for b in admitted:
        groups.setdefault(content_key(b.annotation), []).append(b.annotation.id)
    dup = sorted(({"content_key": content_key_json(next(b.annotation for b in admitted if b.annotation.id == ids[0])),
                   "annotation_ids": sorted(ids)} for ids in groups.values() if len(ids) > 1),
                 key=lambda d: d["annotation_ids"])
    stale = [b for b in bound if b.status == STALE]
    sup = [b for b in bound if b.status == SUPERSEDED]
    contested = contested_entries(bound, full_store)
    report = integrity_report(state)
    report.update({
        "admitted": len(admitted), "rechecked_ok": sum(1 for b in admitted if b.rechecked_ok),
        "stale": len(stale),
        "stale_entries": [{"annotation_id": b.entry.entry["check"]["annotation_id"], "code": b.code,
                           "file": b.entry.file, "line": b.entry.line} for b in stale],
        "superseded_by_base": len(sup),
        "superseded_entries": [{"annotation_id": b.entry.entry["check"]["annotation_id"],
                                "base_annotation_id": b.base_annotation_id,
                                "file": b.entry.file, "line": b.entry.line} for b in sup],
        "duplicate_content": len(dup), "duplicate_content_entries": dup,
        "contested": len(contested), "contested_entries": contested,
    })
    return report


def load_with_ledger(
    snapshot_dir: Path, ledger_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt", expected_signers_sha256: str | None = None,
    cache_dir: Path | None = None, use_cache: bool = True,
) -> tuple[StaticFactStore, dict[str, dict[str, Any]], LoadedLedger]:
    """Base, then integrity, then base binding, then the store over base plus admitted facts.
    Derived entries are recorded, never re-proved here (refinement 24). Raises
    LedgerIntegrityError (exit 2 at the CLI), including for a base file that is present but cannot
    be read; a missing base file is the CLI's usage error (refinement 18)."""
    base = load_base_or_fail(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    base_store = StaticFactStore(base.terms, base.edges, base.annotations)
    state = verify_ledger(ledger_dir, expected_signers_sha256=expected_signers_sha256,
                          cache_dir=cache_dir, use_cache=use_cache)
    bound = bind_entries(state, base, base_store)
    admitted = [b.annotation for b in bound if b.status == ADMITTED and b.annotation is not None]
    # A duplicate id here would be a defect: column 15 separates ledger ids from base ids and
    # signers from each other, and integrity step 7 refuses a repeated row within one file.
    full = StaticFactStore(base.terms, base.edges, base.annotations + admitted)
    block = ledger_report(state, bound, full)
    report: dict[str, dict[str, Any]] = {**base.report, "ledger_gaf": _ledger_gaf_report(bound), "ledger": block}
    return full, report, LoadedLedger(state, base, bound, block)


def _reprove(e: LedgerEntry, base: BaseLoad, store: FactStore) -> list[LedgerError]:
    """The §2 ``derived`` rule on a signed derived entry, over ``store``: its errors, [] on a pass."""
    ctx = CheckContext(store=store, eco_map=base.eco_map, primary_id=base.primary_id, term=base.term, key16=e.key16)
    return check_derived({"derivation": e.entry["derivation"], "conclusion": e.entry["conclusion"]}, ctx).errors


def _kernel_codes(errors: list[LedgerError]) -> list[str]:
    """The kernel's own error codes behind a LEDGER_DERIVATION_REJECTED, sorted, unique."""
    codes = {k.get("code") for x in errors for k in ((x.context or {}).get("kernel") or {}).get("errors", [])
             if isinstance(k, dict)}
    return sorted(codes, key=str)


def recheck_derived(loaded: LoadedLedger, store: FactStore) -> dict[str, Any]:
    """``verify|show --recheck``: re-prove every derived entry (spec §2 derived rule) over ``store``.
    Every failure is counted in ``derived_failed`` and listed in ``derived_failed_entries`` with its
    errors, the kernel's codes and ``same_base``: true when the entry's ``base`` names the loaded
    base. A failure is never LEDGER_INVALID_ENTRY; the CLI exits 2 on one with ``same_base`` true
    (refinement 24)."""
    rechecked = 0
    failed: list[dict[str, Any]] = []
    for b in loaded.bound:
        e = b.entry
        if e.entry["kind"] != "derived":
            continue
        rechecked += 1
        errors = _reprove(e, loaded.base, store)
        if errors:
            failed.append({"file": e.file, "line": e.line, "hash": e.hash, "same_base": _same_base(e, loaded.base),
                           "kernel_codes": _kernel_codes(errors), "errors": [x.to_dict() for x in errors]})
    return {"derived_rechecked": rechecked, "derived_failed": len(failed), "derived_failed_entries": failed}


def own_base_failures(block: dict[str, Any]) -> int:
    """How many ``derived_failed_entries`` failed on the base their entry names (0 without --recheck)."""
    return sum(1 for f in block.get("derived_failed_entries") or [] if f["same_base"])
