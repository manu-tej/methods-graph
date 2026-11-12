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
