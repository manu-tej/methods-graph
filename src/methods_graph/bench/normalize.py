"""Three vocabularies, one comparison space.

Gold speaks ``mod:`` module ids, the oracle speaks ``m:`` method ids, and models speak
English. Everything is resolved into method space here so the metrics never have to
know which vocabulary a name arrived in.

Resolution is EXACT, deliberately. ``m:<lowercased name>`` holds for all 905 methods
with no exceptions and no collisions, so an exact lookup is both sufficient and safe.
The graph's fuzzy resolver is not used: ``resolve_method_ids(["STAR"])`` returns
``m:ea-utils``, ``m:find`` and ``m:gedi`` before it returns ``m:star``, and a normalizer
that guesses would score models on the guess.
"""
from __future__ import annotations

import re

from methods_graph.bench.oracle import Oracle

# Names whose canonical form is not recoverable by punctuation stripping alone. Every
# entry must name a method the graph actually carries; ``normalize_name`` re-checks
# against the oracle, so a stale alias degrades to "unresolved" rather than to a wrong id.
#
# KEYS ARE LOOKED UP IN SPACE-SEPARATED FORM. `_candidates` collapses all punctuation to
# single spaces BEFORE consulting this table, so an entry like "bwa-mem" can never match
# — "bwa mem" is what arrives, and it already covers "BWA-MEM", "bwa_mem" and "BWA MEM".
_ALIASES = {
    "bwa mem": "bwa",
    "bwa aln": "bwa",
    "trim galore": "trimgalore",
    "cut adapt": "cutadapt",
    "star aligner": "star",
    "samtools sort": "samtools",
    "samtools index": "samtools",
    "picard markduplicates": "picard",
    "gatk haplotypecaller": "gatk4",
    "deseq": "deseq2",
}


def _candidates(text: str) -> list[str]:
    """Canonical-form candidates for a free-text tool name, most literal first."""
    stripped = text.strip().lower()
    if stripped.startswith("m:"):
        stripped = stripped[2:]
    if not stripped:
        return []

    spaced = re.sub(r"[^a-z0-9]+", " ", stripped).strip()
    out = [stripped]
    if spaced in _ALIASES:
        out.append(_ALIASES[spaced])
    # "Trim Galore!" -> "trimgalore"; "BWA-MEM2" -> "bwamem2"
    out.append(spaced.replace(" ", ""))
    # "ea utils" -> "ea-utils"
    out.append(spaced.replace(" ", "-"))
    return [c for c in out if c]


def normalize_name(text: str, oracle: Oracle) -> str | None:
    """A free-text tool name as an ``m:`` id, or ``None`` if the graph has no such tool."""
    for candidate in _candidates(text):
        method_id = f"m:{candidate}"
        if oracle.has_method(method_id):
            return method_id
    return None


def normalize_answer(
    names: list[str], oracle: Oracle,
) -> tuple[list[str], list[str]]:
    """A model's answer as ordered, deduped method ids plus the names that did not resolve.

    Unresolved names are RETURNED, not dropped: silently discarding them would let a
    model that names five imaginary tools and one real one score like a model that
    named one tool.
    """
    ids: list[str] = []
    unresolved: list[str] = []
    for name in names:
        method_id = normalize_name(name, oracle)
        if method_id is None:
            if name not in unresolved:
                unresolved.append(name)
        elif method_id not in ids:
            ids.append(method_id)
    return ids, unresolved


def project_sequence(
    module_ids: list[str], oracle: Oracle,
) -> tuple[list[str], list[str]]:
    """Gold ``mod:`` ids as ordered, deduped ``m:`` ids, plus the modules with no method.

    Deduping is the point, not a side effect: ``star_genomegenerate`` then ``star_align``
    is one tool choice, and asking a model to name it twice measures nf-core familiarity.
    """
    sequence: list[str] = []
    unresolved: list[str] = []
    for module_id in module_ids:
        method_id = oracle.method_for_module(module_id)
        if method_id is None:
            if module_id not in unresolved:
                unresolved.append(module_id)
        elif method_id not in sequence:
            sequence.append(method_id)
    return sequence, unresolved


def project_edges(
    edges: list[tuple[str, str]] | list[list[str]],
    module_ids: list[str],
    oracle: Oracle,
) -> tuple[list[tuple[str, str]], int]:
    """Gold precedence edges projected into method space, kept acyclic.

    Collapsing can manufacture a contradiction the DAG never contained: if A precedes B
    precedes C and A and C are the same tool, method space gets ``X -> Y`` and
    ``Y -> X``. Those edges are resolved against the projected sequence's order — which
    came from a topological sort of the uncollapsed DAG — and the discarded count is
    returned so the loss is visible rather than inferred.
    """
    sequence, _ = project_sequence(module_ids, oracle)
    position = {method_id: index for index, method_id in enumerate(sequence)}

    kept: set[tuple[str, str]] = set()
    dropped_cyclic = 0
    for source, target in edges:
        from_id = oracle.method_for_module(source)
        to_id = oracle.method_for_module(target)
        if from_id is None or to_id is None or from_id == to_id:
            continue
        if from_id not in position or to_id not in position:
            continue
        if position[from_id] < position[to_id]:
            kept.add((from_id, to_id))
        else:
            dropped_cyclic += 1
    return sorted(kept), dropped_cyclic
