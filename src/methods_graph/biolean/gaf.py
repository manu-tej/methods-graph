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
# GAF 2.2 column names, in order. The ledger's object-form `--fact` uses them as keys and
# `LEDGER_BAD_COLUMNS` lists them (spec §2 step 1, §7).
GAF_COLUMNS: tuple[str, ...] = (
    "db", "db_object_id", "db_object_symbol", "qualifier", "go_id", "db_reference",
    "evidence_code", "with_from", "aspect", "db_object_name", "db_object_synonym",
    "db_object_type", "taxon", "date", "assigned_by", "annotation_extension",
    "gene_product_form_id",
)
_COLUMNS = len(GAF_COLUMNS)


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
