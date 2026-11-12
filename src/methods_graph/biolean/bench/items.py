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
from methods_graph.biolean.store import FactStore, MaskedFactStore, read_release
from methods_graph.biolean.tactics import prove

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
