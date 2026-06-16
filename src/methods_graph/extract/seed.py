"""Seed-subgraph extraction over the Kùzu methods graph."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import kuzu


@dataclass
class Subgraph:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def _node_dict(row_id: str, row_name: str, row_kind: str, row_properties: str) -> dict[str, Any]:
    """Build a clean node dict from positional query columns."""
    props_raw = row_properties
    if isinstance(props_raw, str):
        props = json.loads(props_raw or "{}")
    elif isinstance(props_raw, dict):
        props = props_raw
    else:
        props = {}
    return {"id": row_id, "name": row_name, "kind": row_kind, "properties": props}


def seed(conn: kuzu.Connection, seed_ids: list[str], *, k_hops: int = 1) -> Subgraph:
    """Bounded undirected expansion from seed nodes out to k hops.

    Returns a Subgraph with all nodes reachable within k_hops of any seed (including
    the seeds themselves) and all edges between those gathered nodes.

    Values of k_hops less than 1 are treated as 1; seeds-only (0-hop) extraction is
    not supported — the minimum expansion is always 1 hop.

    Cypher notes (kuzu 0.11.3):
    - Variable-length syntax: ``-[r:Rel*1..k]-`` (undirected, no named edge variable needed).
    - ``list_contains($param, value)`` works with a query parameter list.
    - Inline rel property filter ``{kind: $k}`` is supported on single-hop MATCH.
    """
    k = max(1, k_hops)
    sg = Subgraph()
    seen: set[str] = set()

    # Include the seed nodes themselves.
    seed_res = conn.execute(
        "MATCH (s:Entity) WHERE list_contains($seeds, s.id) "
        "RETURN s.id, s.name, s.kind, s.properties",
        parameters={"seeds": seed_ids},
    )
    for row in seed_res:
        nid = row[0]
        if nid not in seen:
            seen.add(nid)
            sg.nodes.append(_node_dict(row[0], row[1], row[2], row[3]))

    # Expand up to k hops (undirected) from the seeds.
    neighbor_res = conn.execute(
        "MATCH (s:Entity)-[:Rel*1..%d]-(n:Entity) "
        "WHERE list_contains($seeds, s.id) "
        "RETURN DISTINCT n.id, n.name, n.kind, n.properties" % k,
        parameters={"seeds": seed_ids},
    )
    for row in neighbor_res:
        nid = row[0]
        if nid not in seen:
            seen.add(nid)
            sg.nodes.append(_node_dict(row[0], row[1], row[2], row[3]))

    # Collect all edges whose both endpoints are in the gathered node set.
    node_ids = list(seen)
    edge_res = conn.execute(
        "MATCH (a:Entity)-[r:Rel]->(b:Entity) "
        "WHERE list_contains($ids, a.id) AND list_contains($ids, b.id) "
        "RETURN a.id, b.id, r.kind",
        parameters={"ids": node_ids},
    )
    for row in edge_res:
        sg.edges.append({"from": row[0], "to": row[1], "kind": row[2]})

    return sg


def method_ids_matching(conn: kuzu.Connection, keywords: list[str]) -> list[str]:
    """Resolve keywords to Method ids: direct name/property substring hits, plus
    methods that reach a matched non-method entity within 1-2 outward hops
    (asymmetric — covers Method-PERFORMS->ChildOp-IS_A->ParentOp), plus matched
    Assumption nodes seeded directly. Deduped, order-preserving. Read-only."""
    ids: list[str] = []
    for kw in keywords:
        all_rows = conn.execute(
            "MATCH (n:Entity) "
            "WHERE contains(lower(n.name), lower($kw)) "
            "   OR contains(lower(n.properties), lower($kw)) "
            "RETURN n.id, n.kind ORDER BY n.id",
            parameters={"kw": kw},
        )
        direct_method_ids: list[str] = []
        non_method_ids: list[str] = []
        matched_assumption_ids: list[str] = []
        for row in all_rows:
            nid, kind = row[0], row[1]
            if kind == "Method":
                direct_method_ids.append(nid)
            else:
                non_method_ids.append(nid)
                if kind == "Assumption":
                    matched_assumption_ids.append(nid)
        ids.extend(direct_method_ids)
        if non_method_ids:
            resolved = conn.execute(
                "MATCH (meth:Entity {kind:'Method'})-[r:Rel*1..2]->(x:Entity) "
                "WHERE list_contains($matched, x.id) "
                "RETURN DISTINCT meth.id ORDER BY meth.id",
                parameters={"matched": non_method_ids},
            )
            ids.extend(row[0] for row in resolved)
        ids.extend(matched_assumption_ids)
    return list(dict.fromkeys(ids))


def method_neighborhood(conn: kuzu.Connection, method_id: str) -> dict[str, Any]:
    """Return the 1-hop slice needed to materialize one AnalysisMethod.

    Returns a dict with keys:
    - ``method``: the method node dict (includes bioconda_pkg, biotools_id)
    - ``operations``: list of nodes connected via PERFORMS edges
    - ``containers``: list of nodes connected via PACKAGED_AS edges
    - ``inputs``: list of Data/Format nodes connected via INPUT edges
    - ``outputs``: list of Data/Format nodes connected via OUTPUT edges
    - ``statistical_methods``: StatisticalMethod nodes via USES_STATISTICAL_METHOD
      (each carries the ``evidence`` token grounding the link)
    - ``assumptions``: Assumption nodes inherited transitively
      (Method→StatisticalMethod→Assumption), deduped by assumption. Each carries
      a ``via`` list of ``{"statistical_method": <name>, "evidence": <token>}``
      entries — one per statistical method the assumption is reached through, so
      the grounding evidence is preserved *per via* (a single assumption inherited
      via two methods keeps both citations).
    - ``amenable_statistics``: StatisticalMethod nodes the method's results are
      *amenable to* (statistics you can run on its output), reached via
      Method→PERFORMS→Operation→AMENABLE_TO→StatisticalMethod, deduped by statistic.
      Each carries a ``via`` list of ``{"operation": <name>, "evidence": <token>}``.
      Distinct from ``statistical_methods`` (what the tool uses internally).
    """
    method_res = list(conn.execute(
        "MATCH (m:Entity {id: $id}) "
        "RETURN m.id, m.name, m.kind, m.properties, m.bioconda_pkg, m.biotools_id",
        parameters={"id": method_id},
    ))
    if not method_res:
        raise KeyError(method_id)

    r = method_res[0]
    method = {
        "id": r[0],
        "name": r[1],
        "kind": r[2],
        "properties": json.loads(r[3] or "{}"),
        "bioconda_pkg": r[4],
        "biotools_id": r[5],
    }

    buckets = {
        "operations": "PERFORMS",
        "containers": "PACKAGED_AS",
        "inputs": "INPUT",
        "outputs": "OUTPUT",
    }
    out: dict[str, Any] = {"method": method}
    for key, edge_kind in buckets.items():
        rows = conn.execute(
            "MATCH (m:Entity {id: $id})-[r:Rel {kind: $k}]->(o:Entity) "
            "RETURN o.id, o.name, o.kind, o.properties ORDER BY o.id",
            parameters={"id": method_id, "k": edge_kind},
        )
        out[key] = [_node_dict(x[0], x[1], x[2], x[3]) for x in rows]

    # Statistical methods used directly, each with the evidence grounding it.
    sm_rows = conn.execute(
        "MATCH (m:Entity {id: $id})-[r:Rel {kind: 'USES_STATISTICAL_METHOD'}]->(s:Entity) "
        "RETURN s.id, s.name, s.kind, s.properties, r.properties ORDER BY s.name",
        parameters={"id": method_id},
    )
    statistical_methods = []
    for x in sm_rows:
        d = _node_dict(x[0], x[1], x[2], x[3])
        d["evidence"] = json.loads(x[4] or "{}").get("evidence", "")
        statistical_methods.append(d)
    out["statistical_methods"] = statistical_methods

    # Assumptions inherited transitively (Method→StatisticalMethod→Assumption),
    # deduped by assumption, recording which statistical method(s) it comes via.
    a_rows = conn.execute(
        "MATCH (m:Entity {id: $id})-[:Rel {kind: 'USES_STATISTICAL_METHOD'}]->"
        "(s:Entity)-[ra:Rel {kind: 'REQUIRES_ASSUMPTION'}]->(a:Entity) "
        "RETURN a.id, a.name, a.kind, a.properties, s.name, ra.properties "
        "ORDER BY a.name, s.name",
        parameters={"id": method_id},
    )
    assumptions: dict[str, dict[str, Any]] = {}
    for x in a_rows:
        aid = x[0]
        if aid not in assumptions:
            d = _node_dict(x[0], x[1], x[2], x[3])
            d["via"] = []
            assumptions[aid] = d
        s_name = x[4]
        evidence = json.loads(x[5] or "{}").get("evidence", "")
        # One via entry per statistical method, carrying that edge's own evidence
        # (rows are ordered by a.name, s.name → via is sorted and deterministic).
        if not any(v["statistical_method"] == s_name for v in assumptions[aid]["via"]):
            assumptions[aid]["via"].append({"statistical_method": s_name, "evidence": evidence})
    out["assumptions"] = list(assumptions.values())

    # Applicable statistics: what statistics can be run ON this method's results,
    # reached via PERFORMS→AMENABLE_TO (operation-mediated), deduped by statistic.
    # Each carries a ``via`` list of {operation, evidence} entries — the operation(s)
    # the statistic is applicable through, with that link's grounding citation.
    am_rows = conn.execute(
        "MATCH (m:Entity {id: $id})-[:Rel {kind: 'PERFORMS'}]->"
        "(o:Entity {kind: 'Operation'})-[ra:Rel {kind: 'AMENABLE_TO'}]->(s:Entity) "
        "RETURN s.id, s.name, s.kind, s.properties, o.name, ra.properties "
        "ORDER BY s.name, o.name",
        parameters={"id": method_id},
    )
    amenable: dict[str, dict[str, Any]] = {}
    for x in am_rows:
        sid = x[0]
        if sid not in amenable:
            d = _node_dict(x[0], x[1], x[2], x[3])
            d["via"] = []
            amenable[sid] = d
        o_name = x[4]
        evidence = json.loads(x[5] or "{}").get("evidence", "")
        if not any(v["operation"] == o_name for v in amenable[sid]["via"]):
            amenable[sid]["via"].append({"operation": o_name, "evidence": evidence})
    out["amenable_statistics"] = list(amenable.values())

    return out
