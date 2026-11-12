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
