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


def gold_sequence(
    mmd_text: str,
    proc_to_module: dict[str, str],
    *,
    exclude: frozenset[str] = BOOKKEEPING,
) -> list[str]:
    """Ordered module ids for one pipeline, from its Nextflow DAG.

    Processes with no module mapping are dropped rather than guessed at.
    """
    edges: list[tuple[str, str, int]] = []
    for source_label, target_label, rank in parse_dag_process_edges(mmd_text):
        source = proc_to_module.get(source_label)
        target = proc_to_module.get(target_label)
        if not source or not target or source == target:
            continue
        edges.append((source, target, rank))

    ordered = _topological_order(break_cycles(edges))
    return [node for node in ordered if _bare(node) not in exclude]
