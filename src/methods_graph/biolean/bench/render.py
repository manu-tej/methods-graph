"""Item → closed-book prompt, and model reply → JSON object. Mirrors ``bench/render.py``.

The prompt is the spec's text plus one fixed ``FORMAT_BLOCK``. A model that has never seen
Biolean cannot emit its JSON from the claim alone, and a benchmark where every reply is
``UNPARSED`` measures nothing; the block is identical for every item and both tracks, so
it adds no per-item information.
"""
from __future__ import annotations

import json
from typing import Any

FORMAT_BLOCK = (
    'Format: {"biolean": "0.1", "goal": P, "root": "<id of the final step>", "steps": [...]}, '
    'where P is {"subject": "<UniProtKB accession, e.g. UniProtKB:P04637>", '
    '"qualifier": "<GAF qualifier, e.g. involved_in>", "term": "<GO id>", '
    '"taxon": "<NCBITaxon:id>", "negated": false}. '
    'Steps: {"id": "s1", "rule": "axiom", "conclusion": P} cites a recorded annotation; '
    '{"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["<GO child>", "<GO parent>"], '
    '"conclusion": P} lifts the premise along an is_a edge, and rule "part_of" does the same '
    'along a part_of edge; '
    '{"id": "s1", "rule": "sorry", "conclusion": P, "provenance": {"method": "<method>", '
    '"inputs": ["<dataset>"], "parameters": {}, "claim": "<what the computation shows>"}} '
    'admits a computed result. Every step id is unique and a premise must come earlier.')

PROVE_TEMPLATE = (
    "Prove the following claim as a Biolean derivation.\n"
    "Claim: {claim}\n"
    "The direct annotation of this gene product to this term is not available to you. Derive\n"
    "it from an annotation to a more specific term using the rules is_a and part_of.\n"
    "Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only.\n"
    "{format}")

HYPOTHESIZE_TEMPLATE = (
    "No recorded annotation supports the following claim.\n"
    "Claim: {claim}\n"
    "Propose the computation that would establish it: a Biolean derivation whose root is a\n"
    "sorry step with provenance naming the method, the input datasets, and parameters.\n"
    "Answer with the JSON document only.\n"
    "{format}")

_TEMPLATES = {"prove": PROVE_TEMPLATE, "hypothesize": HYPOTHESIZE_TEMPLATE}
_ORGANISM = {"NCBITaxon:9606": "human"}


def organism(taxon: str) -> str:
    """A common name where one is known, else the taxon id verbatim — never a guess."""
    return _ORGANISM.get(taxon, taxon)


def claim_text(item: dict[str, Any]) -> str:
    goal = item["goal"]
    return (f"{item['symbol']} ({goal['subject']}) {goal['qualifier']} "
            f"{item['term_name']} ({goal['term']}), {organism(goal['taxon'])}.")


def render_prompt(item: dict[str, Any]) -> str:
    """The closed-book prompt for one item. Raises ``KeyError`` for a malformed item."""
    return _TEMPLATES[item["track"]].format(claim=claim_text(item), format=FORMAT_BLOCK)


_DOCUMENT_KEYS = frozenset({"steps", "root", "biolean"})


def parse_reply(raw: Any) -> dict[str, Any] | None:
    """The first balanced JSON object that looks like a derivation, or ``None``.

    ``None`` is a FORMATTING failure — prose, a refusal, a bare list, a truncated document,
    a trailing comma, a Python-style ``False``/``True``/``None`` in place of JSON's — and is
    scored as ``UNPARSED``; it is never turned into an empty derivation, because the kernel
    would then report the model's formatting as a knowledge failure. Fences and surrounding
    prose are skipped by decoding from each ``{`` left to right, but a decoded dict only
    counts as the reply's document when it carries at least one of ``"steps"``, ``"root"``,
    or ``"biolean"``; otherwise scanning continues past it. Without that check, a malformed
    top-level document (truncated, a trailing comma, an invalid literal buried in one field)
    can still let an EARLIER or NESTED object decode cleanly on its own — the goal ``Prop``,
    a single step, a ``sorry``'s provenance — and that object would wrongly stand in for the
    whole reply.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.keys() & _DOCUMENT_KEYS:
            return value
    return None
