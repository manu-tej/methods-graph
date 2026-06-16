"""Parse Nextflow's ground-truth mermaid DAG (``-with-dag``) into process edges.

Nextflow's DAG is channel-level: process nodes are stadium-shaped ``vN([NAME])``;
channels/values are ``vN[..]`` and operators are ``vN((..))``.  We collapse every
path ``process -> (channel/operator nodes) -> process`` into a direct
producer->consumer edge — EXCLUDING accumulator hubs (the ``versions``/``multiqc``
collector channels: high fan-in feeding a single sink), which would otherwise wire
every process to every other through the QC/version aggregation.

Pure / deterministic: text in, sorted ``(producer, consumer)`` label pairs out;
self-loops dropped (multi-instance processes share a label).  No clock, no RNG.
"""
from __future__ import annotations

import re
from collections import defaultdict

_NODE = re.compile(r'(v\d+)(\(\[|\(\(|\[)"?(.*?)"?(\]\)|\)\)|\])')
_EDGE = re.compile(r"(v\d+)\s*-->\s*(v\d+)")


def parse_dag_edges(mmd_text: str) -> list[tuple[str, str]]:
    """Return sorted, deduped (producer_label, consumer_label) process edges."""
    label: dict[str, str] = {}
    is_proc: dict[str, bool] = {}
    for vid, open_sh, lab, _close in _NODE.findall(mmd_text):
        # leaf name only (some Nextflow versions emit subworkflow-qualified A:B:C)
        label[vid] = lab.strip().strip('"').split(":")[-1]
        is_proc[vid] = (open_sh == "([")

    indeg: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in _EDGE.findall(mmd_text):
        adj[a].append(b)
        indeg[b] += 1

    def is_accumulator(n: str) -> bool:
        lab = label.get(n, "").lower()
        if "version" in lab or "multiqc" in lab or "mqc" in lab:
            return True
        # In Nextflow's RESOLVED preview DAG, conditionals collapse to the active
        # branch, so a real data channel merges only a few alternative producers
        # (<=4 here). A node fanning in >=5 distinct producers is an accumulator
        # (versions/multiqc/QC collect): crossing it would wire every producer to
        # every consumer (the hairball). Exclude it regardless of out-degree —
        # the version/multiqc hubs both fan in AND fan out.
        return indeg[n] >= 5

    def reach(p: str) -> set[str]:
        """Processes reachable from p through only non-process, non-accumulator nodes."""
        seen: set[str] = set()
        out: set[str] = set()
        stack = list(adj[p])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if is_proc.get(n):
                out.add(n)
            elif not is_accumulator(n):
                stack.extend(adj[n])
        return out

    edges: set[tuple[str, str]] = set()
    for p in (v for v in label if is_proc[v]):
        for q in reach(p):
            a, b = label[p], label[q]
            if a and b and a != b:          # drop self-loops (instance-label merge)
                edges.add((a, b))
    return sorted(edges)
