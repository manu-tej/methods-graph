"""The fact store: a Protocol, a dict-backed implementation, a masking view, a loader.

Mirrors ``bench/oracle.py``: ``StaticFactStore`` holds all the logic and the loaders only
fill it, so the kernel's tests run on hand-built stores with no files and no database.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

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
    def subjects(self) -> tuple[str, ...]: ...


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
        self._subjects: tuple[str, ...] = tuple(sorted(by_subject))

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

    def subjects(self) -> tuple[str, ...]:
        """Every subject with at least one annotation, sorted. The population enumerates over it."""
        return self._subjects


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

    def subjects(self) -> tuple[str, ...]:
        return self._base.subjects()


# ---------------------------------------------------------------------------
# release identity and base identity
# ---------------------------------------------------------------------------

_GO_RELEASE_RE = re.compile(r"releases/(\d{4}-\d{2}-\d{2})")


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


def _read_bytes(path: Path) -> bytes:
    """The bytes ``load_base`` parses: gunzipped for ``.gz``. A gzip header carries an mtime and a
    name, so a base digest over the compressed file would change on recompression."""
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def base_digests(
    snapshot_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> dict[str, str]:
    """sha256 hex of each file's parsed content. Base identity for the ledger (spec §1)."""
    snapshot_dir = Path(snapshot_dir)
    return {name: hashlib.sha256(_read_bytes(snapshot_dir / fname)).hexdigest()
            for name, fname in (("obo", obo), ("gaf", gaf), ("eco", eco))}


@dataclass
class BaseLoad:
    """The three parsed files plus what the ledger needs to check a row against them."""
    terms: list[Term]
    edges: list[Edge]
    annotations: list[Annotation]
    eco_map: dict[str, str]
    primary_id: Callable[[str], str | None]
    term: Callable[[str], Term | None]
    digests: dict[str, str]
    report: dict[str, dict[str, int]]


def load_base(
    snapshot_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
) -> BaseLoad:
    """Read the three files once, hashing the bytes that are parsed. Raises FileNotFoundError."""
    snapshot_dir = Path(snapshot_dir)
    raw = {name: _read_bytes(snapshot_dir / fname) for name, fname in (("obo", obo), ("gaf", gaf), ("eco", eco))}
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    terms, edges, obo_report = parse_go_basic(raw["obo"].decode("utf-8"))
    eco_map, eco_report = parse_eco_mapping(raw["eco"].decode("utf-8"))
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}

    def primary_id(go_id: str) -> str | None:
        return go_id if go_id in by_id else alt.get(go_id)

    annotations, gaf_report = parse_gaf(raw["gaf"].decode("utf-8").splitlines(), eco_map, primary_id, by_id.get)
    return BaseLoad(terms, edges, annotations, eco_map, primary_id, by_id.get, digests,
                    {"obo": obo_report, "eco": eco_report, "gaf": gaf_report})


def load_store(
    snapshot_dir: Path,
    *,
    obo: str = "go-basic.obo",
    gaf: str = "goa_human.gaf.gz",
    eco: str = "gaf-eco-mapping.txt",
    ledger_dir: Path | None = None,
    expected_signers_sha256: str | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> tuple[StaticFactStore, dict[str, dict[str, Any]]]:
    """Read the three files and build the store. Without ``ledger_dir``, raises FileNotFoundError
    for a missing file.

    With ``ledger_dir`` the store is base plus admitted ledger facts and the report gains
    ``ledger_gaf`` and ``ledger`` (spec §3); ``LedgerIntegrityError`` is raised when the ledger
    is not intact, and also for a base file that is missing or cannot be read (LEDGER_MALFORMED:
    ``load_with_ledger`` reports every read failure of the base that way, never FileNotFoundError).
    The import is function-level: ``kernel`` imports this module and the ledger imports
    ``kernel``, so a module-level import would be a cycle.
    """
    if ledger_dir is not None:
        from methods_graph.biolean.ledger.load import load_with_ledger

        store, report, _ = load_with_ledger(
            snapshot_dir, ledger_dir, obo=obo, gaf=gaf, eco=eco,
            expected_signers_sha256=expected_signers_sha256, cache_dir=cache_dir, use_cache=use_cache)
        return store, report
    base = load_base(snapshot_dir, obo=obo, gaf=gaf, eco=eco)
    return StaticFactStore(base.terms, base.edges, base.annotations), base.report
