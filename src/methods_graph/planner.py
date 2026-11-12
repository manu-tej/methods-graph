"""Method-layer planner: advisory, attestation-ranked next-step suggestions.

Pure / deterministic / read-only over a built Kùzu methods graph. Given a frontier
(the Module step-nodes and/or EDAM Format/Data nodes the user currently has),
expand() returns the attestation-ranked next analysis steps, each resolved to a
concrete executor (the wrapped Method) with its container and inherited assumptions.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import kuzu

from methods_graph.extract.seed import method_ids_matching, method_neighborhood

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Executor:
    method_id: str
    name: str
    container: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"method_id": self.method_id, "name": self.name, "container": self.container}


@dataclass(frozen=True)
class Suggestion:
    module_id: str
    module_name: str
    chosen_executor: Executor
    alternatives: list[Executor] = field(default_factory=list)
    rank_signal: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "chosen_executor": self.chosen_executor.to_dict(),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "rank_signal": self.rank_signal,
            "evidence": self.evidence,
            "assumptions": self.assumptions,
            "why": self.why,
        }


@dataclass(frozen=True)
class _Candidate:
    module_id: str
    module_name: str
    kind: str            # "downstream" | "entry"
    count: int
    evidence: list[str]
    source_label: str    # the frontier step name (for the "why" string); "" for entry


def _candidates(conn: kuzu.Connection, frontier_ids: list[str],
                exclude: set[str]) -> list[_Candidate]:
    """Gather + rank next-step candidates from a frontier. Continue (step->step via
    DOWNSTREAM_OF, ranked by attestation count) and start (data->Method INPUT->Module
    WRAPS, ranked by HAS_MODULE popularity) are unified. When a module is reachable
    both ways the downstream (sequencing-evidence) candidate is preferred. Candidates
    in the frontier or `exclude` are dropped. Sorted by (count desc, module_id asc)."""
    blocked = set(frontier_ids) | exclude
    best: dict[str, _Candidate] = {}

    # Continue: frontier Module -DOWNSTREAM_OF-> next Module.
    # ORDER BY a.id makes the tie winner (and thus source_label/evidence) deterministic.
    for a_name, b_id, b_name, props in conn.execute(
        "MATCH (a:Entity {kind:'Module'})-[r:Rel {kind:'DOWNSTREAM_OF'}]->(b:Entity {kind:'Module'}) "
        "WHERE list_contains($frontier, a.id) "
        "RETURN a.name, b.id, b.name, r.properties ORDER BY a.id, b.id",
        parameters={"frontier": frontier_ids},
    ):
        if b_id in blocked:
            continue
        p = json.loads(props or "{}")
        count = int(p.get("attestations") or len(p.get("pipelines", [])))
        cand = _Candidate(b_id, b_name, "downstream", count,
                          sorted(p.get("pipelines", [])), a_name)
        cur = best.get(b_id)
        if cur is None or count > cur.count:
            best[b_id] = cand

    # Start: frontier Format/Data <-INPUT- Method <-WRAPS- Module
    entry_mods = list(conn.execute(
        "MATCH (mod:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->"
        "(m:Entity {kind:'Method'})-[:Rel {kind:'INPUT'}]->(f:Entity) "
        "WHERE list_contains($frontier, f.id) "
        "RETURN DISTINCT mod.id, mod.name",
        parameters={"frontier": frontier_ids},
    ))
    for mod_id, mod_name in entry_mods:
        if mod_id in blocked:
            continue
        pipes = [r[0] for r in conn.execute(
            "MATCH (p:Entity {kind:'Pipeline'})-[:Rel {kind:'HAS_MODULE'}]->(mod:Entity {id:$mid}) "
            "RETURN p.name ORDER BY p.name",
            parameters={"mid": mod_id},
        )]
        cand = _Candidate(mod_id, mod_name, "entry", len(pipes), pipes, "")
        cur = best.get(mod_id)
        # Dual-reachable: a downstream (sequencing-evidence) incumbent keeps its slot
        # on ties and only yields to an entry candidate with a strictly higher count
        # (spec: "keeps its higher signal; downstream wins ties"). entry_mods is
        # DISTINCT, so `cur` here is only ever a downstream incumbent.
        if cur is not None and cur.count >= cand.count:
            continue
        best[mod_id] = cand

    return sorted(best.values(), key=lambda c: (-c.count, c.module_id))


def _enrich(conn: kuzu.Connection, module_id: str):
    """Resolve a Module to its executor(s) via WRAPS and enrich the chosen one.

    Returns (chosen: Executor | None, alternatives: list[Executor],
    assumptions: list[dict]). chosen is the min-id wrapped Method (deterministic);
    its container (via PACKAGED_AS) and inherited assumptions come from one
    method_neighborhood call. Returns (None, [], []) if the module wraps no method."""
    rows = list(conn.execute(
        "MATCH (mod:Entity {id:$mid})-[:Rel {kind:'WRAPS'}]->(m:Entity {kind:'Method'}) "
        "RETURN m.id, m.name ORDER BY m.id",
        parameters={"mid": module_id},
    ))
    if not rows:
        return None, [], []
    execs = [Executor(r[0], r[1]) for r in rows]
    base, alternatives = execs[0], execs[1:]

    nb = method_neighborhood(conn, base.method_id)
    containers = nb.get("containers", [])
    container = None
    if containers:
        c0 = containers[0]
        container = c0["properties"].get("image_name", c0["name"])
    chosen = Executor(base.method_id, base.name, container)
    assumptions = [
        {"id": a["id"], "name": a["name"], "via": a.get("via", [])}
        for a in nb.get("assumptions", [])
    ]
    return chosen, alternatives, assumptions


def expand(conn: kuzu.Connection, frontier_ids: list[str], *,
           limit: int = 10, exclude: set[str] | None = None) -> list[Suggestion]:
    """Suggest the attestation-ranked next analysis steps from the current frontier.

    frontier_ids: the nodes the user "has" — Module step ids and/or EDAM Format/Data
        ids, order-insensitive. Returns up to `limit` Suggestions sorted by
        (rank_signal.count desc, module_id asc); candidates already in frontier_ids
        or `exclude` are dropped. Read-only, deterministic, no network.
    """
    cands = _candidates(conn, list(frontier_ids), exclude or set())
    out: list[Suggestion] = []
    for c in cands:
        if len(out) >= limit:
            break
        chosen, alternatives, assumptions = _enrich(conn, c.module_id)
        if chosen is None:
            # Only downstream candidates can reach here (entry candidates matched via
            # WRAPS, so they always have an executor). A downstream Module that wraps
            # no Method is a graph-integrity defect — surface it rather than hide it.
            _log.warning("planner: module %s has no WRAPS executor; skipping", c.module_id)
            continue
        if c.kind == "downstream":
            why = f"after {c.source_label}, {c.count} pipeline(s) run {c.module_name} next"
        else:
            why = f"{c.count} pipeline(s) start with {c.module_name}"
        out.append(Suggestion(
            module_id=c.module_id, module_name=c.module_name,
            chosen_executor=chosen, alternatives=alternatives,
            rank_signal={"kind": c.kind, "count": c.count},
            evidence=c.evidence, assumptions=assumptions, why=why,
        ))
    return out


def seed_from_edge(conn: kuzu.Connection, edge: Any, *,
                   dataset_format: str | None = None) -> list[str]:
    """Map a quration causal edge (+ optional dataset format) to an expand() frontier.

    Reads `source_label`, `target_label`, `relation` (dict keys or attributes),
    resolves their words to Method ids via method_ids_matching, maps those to their
    Modules (via WRAPS), and prepends the dataset Format id. Deduped, order-preserving.
    Deliberately thin — quration owns the causal layer; biological entity labels often
    don't match method vocabulary, so the dataset_format is the reliable seed."""
    def _get(key: str):
        return edge.get(key) if isinstance(edge, dict) else getattr(edge, key, None)

    labels = [str(_get(k)) for k in ("source_label", "target_label", "relation") if _get(k)]
    keywords = [w for label in labels for w in label.replace("-", " ").replace("_", " ").split()]

    frontier: list[str] = []
    if dataset_format:
        frontier.append(dataset_format)
    method_ids = method_ids_matching(conn, keywords) if keywords else []
    if method_ids:
        for row in conn.execute(
            "MATCH (mod:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->(m:Entity) "
            "WHERE list_contains($mids, m.id) "
            "RETURN DISTINCT mod.id ORDER BY mod.id",
            parameters={"mids": method_ids},
        ):
            frontier.append(row[0])
    return list(dict.fromkeys(frontier))
