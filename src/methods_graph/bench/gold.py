"""A Nextflow DAG becomes a deterministic, ordered list of module ids.

This is the benchmark's ground truth. It reads the pipeline's own channel wiring —
never an inference from typed I/O, which is the reasoning the benchmark scores.
"""
from __future__ import annotations

from methods_graph.connectors.nextflow_dag import break_cycles, parse_dag_process_edges

# Reporting/aggregation steps. Present in almost every pipeline, chosen by nobody,
# and predicting them measures familiarity with nf-core conventions rather than
# method knowledge.
BOOKKEEPING = frozenset({
    "multiqc", "versions", "dumpsoftwareversions", "custom_dumpsoftwareversions",
})


def _bare(module_id: str) -> str:
    """``mod:samtools_sort`` -> ``samtools_sort``."""
    return module_id.split(":", 1)[1] if ":" in module_id else module_id


def _topological_order(edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm, with every iteration sorted so output is deterministic."""
    unique = sorted(set(edges))
    nodes = sorted({node for pair in unique for node in pair})
    incoming = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in unique:
        outgoing[source].append(target)
        incoming[target] += 1

    ready = sorted(node for node in nodes if incoming[node] == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(outgoing[node]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
        ready.sort()
    return order


def _module_edges(
    mmd_text: str, proc_to_module: dict[str, str],
) -> list[tuple[str, str]]:
    """The DAG's process edges collapsed onto module ids, made acyclic.

    Processes with no module mapping are dropped rather than guessed at.
    """
    ranked: list[tuple[str, str, int]] = []
    for source_label, target_label, rank in parse_dag_process_edges(mmd_text):
        source = proc_to_module.get(source_label)
        target = proc_to_module.get(target_label)
        if not source or not target or source == target:
            continue
        ranked.append((source, target, rank))
    return break_cycles(ranked)


def gold_sequence(
    mmd_text: str,
    proc_to_module: dict[str, str],
    *,
    exclude: frozenset[str] = BOOKKEEPING,
) -> list[str]:
    """Ordered module ids for one pipeline, from its Nextflow DAG.

    One valid linearization. Where the pipeline branches, the relative order of the
    branches is an arbitrary tie-break — see :func:`gold_edges` for the constraint that
    actually holds.
    """
    ordered = _topological_order(_module_edges(mmd_text, proc_to_module))
    return [node for node in ordered if _bare(node) not in exclude]


def gold_edges(
    mmd_text: str,
    proc_to_module: dict[str, str],
    *,
    exclude: frozenset[str] = BOOKKEEPING,
) -> list[tuple[str, str]]:
    """The precedence relation itself: deduped, sorted, bookkeeping removed.

    :func:`gold_sequence` linearizes this, and linearizing loses information — two modules
    on PARALLEL branches end up adjacent in the sequence though nothing orders them. A
    metric scoring adjacent pairs of the sequence therefore marks correct answers wrong.
    Freezing the edges alongside the sequence is what lets the metric score the ordering
    that is genuinely required; once the items are frozen the DAG cannot be recovered.
    """
    return sorted({
        (source, target) for source, target in _module_edges(mmd_text, proc_to_module)
        if _bare(source) not in exclude and _bare(target) not in exclude
    })
