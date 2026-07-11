"""Parse Nextflow's ground-truth mermaid DAG (``-with-dag``) into process edges.

Nextflow's DAG is channel-level: process nodes are stadium-shaped ``vN([NAME])``;
channels/values are ``vN[..]`` and operators are ``vN((..))``.  We collapse every
path ``process -> (channel/operator nodes) -> process`` into a direct
producer->consumer edge — EXCLUDING accumulator hubs (the ``versions``/``multiqc``
collector channels: high fan-in feeding a single sink), which would otherwise wire
every process to every other through the QC/version aggregation.

Pure / deterministic: text in, sorted ``(producer, consumer)`` label pairs out;
self-loops dropped (multi-instance processes share a label).  No clock, no RNG.

Each edge also carries a ``rank`` (its earliest producer ``vN``); :func:`break_cycles`
uses it to resolve collapse cycles — when one tool runs at two pipeline stages under
aliases, its instances quotient into a single node and can yield both A->B and B->A.
"""
from __future__ import annotations

import re
from collections import defaultdict

_NODE = re.compile(r'(v\d+)(\(\[|\(\(|\[)"?(.*?)"?(\]\)|\)\)|\])')
_EDGE = re.compile(r"(v\d+)\s*-->\s*(v\d+)")


def parse_dag_process_edges(mmd_text: str) -> list[tuple[str, str, int]]:
    """Return sorted (producer_label, consumer_label, rank) process edges.

    ``rank`` is the smallest ``vN`` index of any producer instance of the edge —
    a stable proxy for the edge's pipeline stage, used to break collapse cycles.
    """
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

    # rank each (producer, consumer) label edge by its EARLIEST producer instance
    # (smallest vN).  vN is assigned in DAG-construction order, a strong proxy for
    # pipeline stage — so the rank tells us which direction of a collapsed cycle
    # is the primary (first-occurring) dataflow.
    rank: dict[tuple[str, str], int] = {}
    for p in (v for v in label if is_proc[v]):
        pv = int(p[1:])
        for q in reach(p):
            a, b = label[p], label[q]
            if a and b and a != b:          # drop self-loops (instance-label merge)
                key = (a, b)
                if pv < rank.get(key, pv + 1):
                    rank[key] = pv
    return sorted((a, b, r) for (a, b), r in rank.items())


def parse_dag_edges(mmd_text: str) -> list[tuple[str, str]]:
    """Return sorted, deduped (producer_label, consumer_label) process edges."""
    return [(a, b) for a, b, _r in parse_dag_process_edges(mmd_text)]


def break_cycles(edges: list[tuple[str, str, int]]) -> list[tuple[str, str]]:
    """Greedy feedback-arc removal yielding a guaranteed-acyclic edge subset.

    Edges are added in ascending ``(rank, src, dst)`` order — earliest dataflow
    first.  An edge is skipped iff its consumer already reaches its producer
    (adding it would close a directed cycle).  Because aliased process instances
    collapse distinct DAG positions of one tool into a single module node, the
    module-level graph can legitimately contain both A->B and B->A (a tool used at
    two stages); this keeps the primary (first-occurring) direction and drops the
    re-entrant back-edge.  Pure & deterministic; ties broken by (src, dst)."""
    from collections import defaultdict

    adj: dict[str, set[str]] = defaultdict(set)
    kept: list[tuple[str, str]] = []

    def reaches(src: str, dst: str) -> bool:
        if src == dst:
            return True
        seen = {src}
        stack = [src]
        while stack:
            u = stack.pop()
            for w in adj[u]:
                if w == dst:
                    return True
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        return False

    for a, b, _r in sorted(edges, key=lambda e: (e[2], e[0], e[1])):
        if a == b or reaches(b, a):
            continue
        adj[a].add(b)
        kept.append((a, b))
    return sorted(set(kept))
