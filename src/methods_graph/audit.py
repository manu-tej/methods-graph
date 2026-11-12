"""KG correctness audit — promoted from examples/kg_audit.py into production code.

Runs three classes of checks against a built Kùzu methods graph:
  1. Schema invariants  — edge endpoint kinds are valid (violations == 0 → PASS)
  2. Provenance        — every node carries a non-empty source string
  3. Duplicate ids      — node count equals distinct id count
  4. SAME_AS candidates — informational breakdown by basis
  5. Coverage          — informational per-method enrichment rates
  6. Reconciliation    — source snapshot counts vs graph counts (optional)

The ``ok`` gate is False if ANY invariant fails, provenance is missing, ids are
not unique, or (when reconciliation is requested) any EDAM kind count mismatches.
Coverage, SAME_AS counts, and source-count informational notes never fail the gate.
"""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Invariant:
    """One schema-invariant check."""
    name: str
    violations: int
    ok: bool  # violations == 0


@dataclass
class AuditResult:
    """Full audit report returned by :func:`audit_graph`."""
    node_count: int
    distinct_ids: int
    duplicate_ids_ok: bool          # node_count == distinct_ids
    provenance_missing: int          # nodes with empty/null source
    invariants: list[Invariant]
    same_as: dict                    # {"total": int, "by_basis": {...}}
    coverage: dict                   # per-metric {"count": n, "pct": f}
    reconciliation: dict | None      # None unless snapshot_dir given
    ok: bool                         # overall gate

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of every field."""
        return {
            "node_count": self.node_count,
            "distinct_ids": self.distinct_ids,
            "duplicate_ids_ok": self.duplicate_ids_ok,
            "provenance_missing": self.provenance_missing,
            "invariants": [
                {"name": inv.name, "violations": inv.violations, "ok": inv.ok}
                for inv in self.invariants
            ],
            "same_as": self.same_as,
            "coverage": self.coverage,
            "reconciliation": self.reconciliation,
            "ok": self.ok,
        }

    def to_text(self) -> str:  # noqa: C901 (complex but readable)
        """Render a human-readable multi-section report."""
        lines: list[str] = []
        sep = "=" * 70

        # --- Invariants ---
        lines.append(sep)
        lines.append("SCHEMA INVARIANTS")
        lines.append(sep)
        for inv in self.invariants:
            status = "PASS" if inv.ok else f"FAIL ({inv.violations} violation(s))"
            lines.append(f"  [{status}] {inv.name}")

        # --- Provenance ---
        lines.append("")
        lines.append(sep)
        lines.append("PROVENANCE")
        lines.append(sep)
        prov_status = "PASS" if self.provenance_missing == 0 else f"FAIL (missing={self.provenance_missing})"
        lines.append(f"  [{prov_status}] every node carries a provenance source")

        # --- Duplicate ids ---
        lines.append("")
        lines.append(sep)
        lines.append("NODE ID UNIQUENESS")
        lines.append(sep)
        dup_status = "PASS" if self.duplicate_ids_ok else "FAIL"
        lines.append(
            f"  [{dup_status}] node ids unique "
            f"({self.node_count} nodes / {self.distinct_ids} distinct ids)"
        )

        # --- SAME_AS candidates (informational) ---
        lines.append("")
        lines.append(sep)
        lines.append("SAME_AS CANDIDATE EDGES (informational)")
        lines.append(sep)
        lines.append(f"  total SAME_AS edges: {self.same_as['total']}")
        for basis, cnt in sorted(self.same_as.get("by_basis", {}).items()):
            lines.append(f"    {basis}: {cnt}")

        # --- Coverage (informational) ---
        lines.append("")
        lines.append(sep)
        lines.append("METHOD COVERAGE (informational)")
        lines.append(sep)
        cov = self.coverage
        mt = cov.get("methods_total", 0)
        lines.append(f"  methods_total: {mt}")
        for key in ("with_biotools_id", "with_bioconda_pkg", "with_container",
                    "with_edam_operation", "with_io_contract",
                    "with_statistical_method", "with_inherited_assumption",
                    "with_checked_assumption", "with_checked_via_operation"):
            v = cov.get(key, {})
            lines.append(f"  {key}: {v.get('count', 0)} ({v.get('pct', 0.0)}%)")
        ums = cov.get("used_method_set", {})
        lines.append(
            f"  evaluable_method_set (any grounded stat path): {ums.get('count', 0)}; "
            f"with complete assumption→diagnostic chain: "
            f"{ums.get('with_complete_chain', 0)} ({ums.get('pct', 0.0)}%)"
        )

        # --- Reconciliation (optional) ---
        if self.reconciliation is not None:
            lines.append("")
            lines.append(sep)
            lines.append("RECONCILIATION (source vs graph)")
            lines.append(sep)
            edam = self.reconciliation.get("edam", {})
            lines.append("  EDAM non-obsolete classes vs graph nodes (must match exactly):")
            for kind in ("operation", "data", "format"):
                entry = edam.get(kind, {})
                match_str = "OK" if entry.get("match") else "MISMATCH"
                lines.append(
                    f"    {kind:10}  tsv={entry.get('tsv', '?'):5}  "
                    f"graph={entry.get('graph', '?'):5}  [{match_str}]"
                )
            src = self.reconciliation.get("sources", {})
            lines.append("  Source informational counts:")
            lines.append(f"    nf-core unique tool names : {src.get('nfcore_tool_names', '?')}")
            lines.append(f"    graph Method nodes        : {src.get('graph_methods', '?')}")
            lines.append(
                f"    note: methods are identified case-insensitively by nf-core tool directory; "
                "subcommand modules collapse to one tool — strong-key (bioconda/bio.tools) "
                "overlaps are SAME_AS candidates, not hard merges"
            )
            lines.append(f"    biocontainers JSON files  : {src.get('biocontainers_files', '?')}")
            lines.append(f"    graph Package nodes       : {src.get('graph_packages', '?')}")
            lines.append(f"    bio.tools JSON files      : {src.get('biotools_files', '?')}")
            ff = self.reconciliation.get("fetch_failures", {})
            if ff:
                lines.append("  Connector fetch failures (recorded in snapshot.json — silently absent from the build):")
                for key in ("biocontainers", "biotools"):
                    entry = ff.get(key, {})
                    n = entry.get("n_failed", 0)
                    sample = ", ".join(entry.get("sample", []))
                    suffix = f"  e.g. {sample}" if sample else ""
                    lines.append(f"    {key:14} : {n} failed{suffix}")

        # --- Final gate ---
        lines.append("")
        lines.append(sep)
        if self.ok:
            lines.append("AUDIT RESULT: ALL CHECKS PASSED")
        else:
            failed_count = sum(1 for inv in self.invariants if not inv.ok)
            if not self.duplicate_ids_ok:
                failed_count += 1
            if self.provenance_missing > 0:
                failed_count += 1
            if self.reconciliation is not None:
                edam = self.reconciliation.get("edam", {})
                failed_count += sum(
                    1 for k in ("operation", "data", "format")
                    if not edam.get(k, {}).get("match", True)
                )
            lines.append(f"AUDIT RESULT: {failed_count} CHECK(S) FAILED")
        lines.append(sep)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ontology-term kinds: all node kinds that may be endpoints of IS_A edges.
# Includes EDAM kinds (Operation, Topic, Data, Format) and STATO/OBI kinds.
# ---------------------------------------------------------------------------

_ONTOLOGY_TERM_KINDS: frozenset[str] = frozenset({
    "Operation",
    "Topic",
    "Data",
    "Format",
    "StatisticalMethod",
    "Assumption",
    "Diagnostic",
    "Assay",
    "Protocol",
    "StudyDesign",
    "Material",
    "Instrument",
})

# ---------------------------------------------------------------------------
# EDAM kind prefixes (local name → tsv key)
# ---------------------------------------------------------------------------

# Topic intentionally excluded: the Topic layer was removed, so EDAM topic rows
# are not ingested and must not be reconciled against the graph.
_EDAM_PREFIXES: dict[str, str] = {
    "operation_": "operation",
    "data_": "data",
    "format_": "format",
}

_EDAM_KINDS_GRAPH: dict[str, str] = {
    "operation": "Operation",
    "data": "Data",
    "format": "Format",
}

# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------


def audit_graph(conn, *, snapshot_dir: Path | None = None) -> AuditResult:
    """Run all correctness checks and return an :class:`AuditResult`.

    Parameters
    ----------
    conn:
        An open ``kuzu.Connection`` to the methods graph database.
    snapshot_dir:
        When provided, reconciliation checks compare snapshot TSV/JSON files
        against graph node counts.  No network calls are made.
    """

    def _q1(cypher: str, params: dict | None = None) -> Any:
        """Execute a Cypher query and return the first cell of the first row."""
        rows = list(conn.execute(cypher, parameters=params or {}))
        return rows[0][0]

    def _qall(cypher: str, params: dict | None = None) -> list:
        return list(conn.execute(cypher, parameters=params or {}))

    # ------------------------------------------------------------------
    # 1. Node counts / duplicate ids
    # ------------------------------------------------------------------
    node_count: int = _q1("MATCH (n:Entity) RETURN count(n)")
    distinct_ids: int = _q1("MATCH (n:Entity) RETURN count(DISTINCT n.id)")
    duplicate_ids_ok: bool = (node_count == distinct_ids)

    # ------------------------------------------------------------------
    # 2. Missing provenance
    # ------------------------------------------------------------------
    # NOTE: the loader always writes a string ``source`` (never NULL), so the
    # ``IS NULL`` half is vacuous on any graph it builds; the ``source=''`` half
    # does the real work. The NULL clause is kept as a guard against graphs
    # written by other paths.
    provenance_missing: int = _q1(
        "MATCH (n:Entity) WHERE n.source IS NULL OR n.source='' RETURN count(n)"
    )

    # ------------------------------------------------------------------
    # 3. Schema invariants
    # ------------------------------------------------------------------
    _invariant_specs: list[tuple[str, str]] = [
        (
            "PERFORMS: Method→Operation",
            "MATCH (a)-[r:Rel{kind:'PERFORMS'}]->(b) "
            "WHERE NOT (a.kind='Method' AND b.kind='Operation') RETURN count(*)",
        ),
        (
            "PACKAGED_AS: Method→Container",
            "MATCH (a)-[r:Rel{kind:'PACKAGED_AS'}]->(b) "
            "WHERE NOT (a.kind='Method' AND b.kind='Container') RETURN count(*)",
        ),
        (
            "WRAPS: Module→Method or Skill→Method",
            "MATCH (a)-[r:Rel{kind:'WRAPS'}]->(b) "
            "WHERE NOT ((a.kind='Module' OR a.kind='Skill') AND b.kind='Method') RETURN count(*)",
        ),
        (
            "INPUT/OUTPUT: Method→(Data|Format)",
            "MATCH (a)-[r:Rel]->(b) WHERE r.kind IN ['INPUT','OUTPUT'] "
            "AND NOT (a.kind='Method' AND b.kind IN ['Data','Format']) RETURN count(*)",
        ),
        (
            "FROM_PACKAGE: Container→Package",
            "MATCH (a)-[r:Rel{kind:'FROM_PACKAGE'}]->(b) "
            "WHERE NOT (a.kind='Container' AND b.kind='Package') RETURN count(*)",
        ),
        (
            # IS_A endpoints may legitimately differ in kind: STATO/OBI cross-link
            # into ontology classes of other kinds, and an external ontology may
            # carry cross-branch subClassOf edges.  So we must NOT require both
            # endpoints to share the same kind.  The invariant only rejects IS_A
            # edges whose endpoints are not ontology classes at all (e.g. Method or
            # Container nodes as src/dst) — those would be a genuine modelling error.
            #
            # The allowed kinds include all EDAM kinds AND STATO/OBI kinds
            # (StatisticalMethod, Assay, Protocol, StudyDesign, Instrument, Material,
            # Assumption, Diagnostic).
            #
            # NOTE: on the production build path this can never fail — the only
            # IS_A producers (connectors/edam.py, connectors/ontology.py) emit edges
            # only when both endpoints are classified ontology nodes. It is
            # defense-in-depth against hand-edited graphs and future IS_A producers,
            # and is exercised by tests (test_audit_isa_non_edam_endpoint_is_violation),
            # not by real data.
            "IS_A: ontology class→ontology class",
            "MATCH (a)-[r:Rel{kind:'IS_A'}]->(b) "
            f"WHERE NOT (a.kind IN {sorted(_ONTOLOGY_TERM_KINDS)!r} "
            f"AND b.kind IN {sorted(_ONTOLOGY_TERM_KINDS)!r}) "
            "RETURN count(*)",
        ),
        (
            # Curated cross-links must run strictly Method→StatisticalMethod.
            # A mistyped endpoint (e.g. a dangling target promoted to some other
            # kind, or a non-Method source) is a genuine modelling error.
            "USES_STATISTICAL_METHOD: Method→StatisticalMethod",
            "MATCH (a)-[r:Rel{kind:'USES_STATISTICAL_METHOD'}]->(b) "
            "WHERE NOT (a.kind='Method' AND b.kind='StatisticalMethod') "
            "RETURN count(*)",
        ),
        (
            # Assumptions attach to the statistical method, not the tool.
            "REQUIRES_ASSUMPTION: StatisticalMethod→Assumption",
            "MATCH (a)-[r:Rel{kind:'REQUIRES_ASSUMPTION'}]->(b) "
            "WHERE NOT (a.kind='StatisticalMethod' AND b.kind='Assumption') "
            "RETURN count(*)",
        ),
        (
            # Applicable statistics are normalized onto the operation, not the tool.
            "AMENABLE_TO: Operation→StatisticalMethod",
            "MATCH (a)-[r:Rel{kind:'AMENABLE_TO'}]->(b) "
            "WHERE NOT (a.kind='Operation' AND b.kind='StatisticalMethod') "
            "RETURN count(*)",
        ),
        (
            # Diagnostics check assumptions: the test/plot/procedure that evaluates
            # whether the data meets an assumption attaches to the Assumption.
            "CHECKED_BY: Assumption→Diagnostic",
            "MATCH (a)-[r:Rel{kind:'CHECKED_BY'}]->(b) "
            "WHERE NOT (a.kind='Assumption' AND b.kind='Diagnostic') "
            "RETURN count(*)",
        ),
        (
            # The runnable recipe attaches to the Module it was extracted from.
            "RUNS_AS: Module→ExecutionSpec",
            "MATCH (a)-[r:Rel{kind:'RUNS_AS'}]->(b) "
            "WHERE NOT (a.kind='Module' AND b.kind='ExecutionSpec') "
            "RETURN count(*)",
        ),
        (
            "HAS_MODULE: Pipeline→Module",
            "MATCH (a)-[r:Rel{kind:'HAS_MODULE'}]->(b) "
            "WHERE NOT (a.kind='Pipeline' AND b.kind='Module') RETURN count(*)",
        ),
        (
            "HAS_MODALITY: Pipeline→Modality",
            "MATCH (a)-[r:Rel{kind:'HAS_MODALITY'}]->(b) "
            "WHERE NOT (a.kind='Pipeline' AND b.kind='Modality') RETURN count(*)",
        ),
        (
            # Curated assay->tool bridge runs strictly Assay→Method.
            "ANALYZED_BY: Assay→Method",
            "MATCH (a)-[r:Rel{kind:'ANALYZED_BY'}]->(b) "
            "WHERE NOT (a.kind='Assay' AND b.kind='Method') RETURN count(*)",
        ),
        (
            "DOWNSTREAM_OF: no self-loops",
            "MATCH (a)-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b) "
            "WHERE a.id = b.id RETURN count(*)",
        ),
        (
            "Pipeline: has >=1 HAS_MODULE",
            "MATCH (p:Entity{kind:'Pipeline'}) "
            "WHERE NOT EXISTS { MATCH (p)-[:Rel{kind:'HAS_MODULE'}]->() } "
            "RETURN count(*)",
        ),
        (
            # Endpoint-kind soundness only. The full I/O-overlap soundness check
            # (OUTPUT(A) ∩ INPUT(B) ≠ ∅) is trivially true under Option-2 inference,
            # so it is deferred to Option 3.
            "DOWNSTREAM_OF: endpoints are Method/Module",
            "MATCH (a)-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b) "
            "WHERE NOT (a.kind IN ['Method','Module'] AND b.kind IN ['Method','Module']) "
            "RETURN count(*)",
        ),
    ]

    invariants: list[Invariant] = []
    for inv_name, inv_cypher in _invariant_specs:
        violations = _q1(inv_cypher)
        invariants.append(Invariant(name=inv_name, violations=violations, ok=(violations == 0)))

    # Grounding invariants (computed in Python — evidence lives in the edge's JSON
    # ``properties``, which Cypher can't introspect).  Every curated cross-link
    # edge MUST carry an ``evidence`` token whose prefix is allowed for that edge
    # kind.  This makes an ungrounded OR loosely-grounded curated link (e.g. a
    # statistical-method link cited only by a bare URL, or any edge with a free-
    # text token) structurally impossible to pass the audit.
    #
    #   USES_STATISTICAL_METHOD : doi: | pmid:  (a primary publication only)
    #   REQUIRES_ASSUMPTION     : doi: | pmid: | url: | isbn: | stato:
    #     (assumptions are also groundable in textbooks / authoritative URLs /
    #     the statistical-method's own STATO definition)
    def _bad_evidence_count(edge_kind: str, allowed_prefixes: tuple[str, ...]) -> int:
        rows = _qall(f"MATCH ()-[r:Rel{{kind:'{edge_kind}'}}]->() RETURN r.properties")
        n = 0
        for row in rows:
            try:
                props = json.loads(row[0] or "{}")
            except (json.JSONDecodeError, TypeError):
                props = {}
            evidence = str(props.get("evidence", "")).strip().lower()
            if not evidence.startswith(allowed_prefixes):
                n += 1
        return n

    for edge_kind, prefixes, label in (
        ("USES_STATISTICAL_METHOD", ("doi:", "pmid:"),
         "USES_STATISTICAL_METHOD: grounded (doi:/pmid: evidence)"),
        ("REQUIRES_ASSUMPTION", ("doi:", "pmid:", "url:", "isbn:", "stato:"),
         "REQUIRES_ASSUMPTION: grounded (doi:/pmid:/url:/isbn:/stato: evidence)"),
        ("AMENABLE_TO", ("doi:", "pmid:"),
         "AMENABLE_TO: grounded (doi:/pmid: evidence)"),
        ("CHECKED_BY", ("doi:", "pmid:", "url:", "isbn:"),
         "CHECKED_BY: grounded (doi:/pmid:/url:/isbn: evidence)"),
        ("ANALYZED_BY", ("doi:", "pmid:"),
         "ANALYZED_BY: grounded (doi:/pmid: evidence)"),
    ):
        bad = _bad_evidence_count(edge_kind, prefixes)
        invariants.append(Invariant(name=label, violations=bad, ok=(bad == 0)))

    # Curated-link integrity (defense-in-depth against a SILENT drop): for each
    # curated cross-link layer, every shipped link whose BOTH endpoints exist in the
    # graph with the correct kinds MUST have produced its edge.  A link with an absent
    # endpoint is a legitimate skip (e.g. a method not in this build) and is NOT
    # counted, so this is safe on partial builds; but a builder regression that drops a
    # resolvable link (e.g. an off-by-one in dedup) becomes a hard audit failure instead
    # of a silently lower coverage number.
    def _resolvable_links_missing() -> int:
        from methods_graph.crosslinks import load_crosslinks
        from methods_graph.crosslinks.amenable import load_amenable
        from methods_graph.crosslinks.assay_methods import load_assay_methods

        kind_by_id = {r[0]: r[1] for r in _qall("MATCH (n:Entity) RETURN n.id, n.kind")}

        def _edges(kind: str) -> set:
            return {(r[0], r[1]) for r in
                    _qall(f"MATCH (a)-[r:Rel{{kind:'{kind}'}}]->(b) RETURN a.id, b.id")}

        specs: list[tuple[list[tuple[str, str]], str, str, str]] = [
            ([(l.method_id, l.statistical_method_id) for l in load_crosslinks()],
             "Method", "StatisticalMethod", "USES_STATISTICAL_METHOD"),
            ([(l.operation_id, l.statistical_method_id) for l in load_amenable()],
             "Operation", "StatisticalMethod", "AMENABLE_TO"),
            ([(l.assay_id, l.method_id) for l in load_assay_methods()],
             "Assay", "Method", "ANALYZED_BY"),
        ]
        missing = 0
        for pairs, src_kind, dst_kind, ekind in specs:
            present = _edges(ekind)
            for src, dst in pairs:
                if (kind_by_id.get(src) == src_kind and kind_by_id.get(dst) == dst_kind
                        and (src, dst) not in present):
                    missing += 1
        return missing

    try:
        _missing = _resolvable_links_missing()
        invariants.append(Invariant(
            name="curated links: every resolvable link is emitted (no silent drop)",
            violations=_missing, ok=(_missing == 0)))
    except Exception:  # noqa: BLE001
        # A malformed/unreadable curated YAML (ValueError) or a renamed loader
        # (ImportError) must FAIL the gate loudly — recording a failed invariant —
        # rather than silently dropping the check, which would let a curator
        # regression pass the audit as if the integrity check had run.
        invariants.append(Invariant(
            name="curated links: every resolvable link is emitted (no silent drop)",
            violations=1, ok=False))

    # ExecutionSpec content — the runnable recipe MUST carry a container IMAGE; a spec
    # with no image is not runnable.  A Singularity/Apptainer image (e.g. a Seqera
    # community blob URL) is just as runnable as a Docker image, so a spec that pins
    # ONLY a singularity image is fine — only a spec with NEITHER is a violation.
    # (The connector now declines to emit a spec for a module with no image at all,
    # so on the production build this is 0; the check is defense-in-depth.)
    def _execspec_without_container() -> int:
        rows = _qall("MATCH (n:Entity {kind:'ExecutionSpec'}) RETURN n.properties")
        n = 0
        for row in rows:
            try:
                props = json.loads(row[0] or "{}")
            except (json.JSONDecodeError, TypeError):
                props = {}
            docker = str(props.get("container", "") or "").strip()
            singularity = str(props.get("container_singularity", "") or "").strip()
            if not docker and not singularity:
                n += 1
        return n

    _no_ctr = _execspec_without_container()
    invariants.append(Invariant(name="ExecutionSpec: has a container",
                                violations=_no_ctr, ok=(_no_ctr == 0)))

    # DOWNSTREAM_OF attestation consistency — JSON properties, so computed in
    # Python (Cypher can't introspect the blob).  attestations must equal the
    # length of a non-empty, sorted, deduped pipelines list.
    def _bad_attestation_count() -> int:
        rows = _qall("MATCH ()-[r:Rel{kind:'DOWNSTREAM_OF'}]->() RETURN r.properties")
        n = 0
        for row in rows:
            try:
                props = json.loads(row[0] or "{}")
            except (json.JSONDecodeError, TypeError):
                props = {}
            pipes = props.get("pipelines", [])
            if (not isinstance(pipes, list) or not pipes
                    or pipes != sorted(set(pipes))
                    or props.get("attestations") != len(pipes)):
                n += 1
        return n

    _att_bad = _bad_attestation_count()
    invariants.append(Invariant(
        name="DOWNSTREAM_OF: attestation consistent (attestations==len(pipelines))",
        violations=_att_bad, ok=(_att_bad == 0)))

    # DOWNSTREAM_OF acyclicity — the GROUND-TRUTH (nextflow_dsl2) ordering layer
    # must be a DAG so the planner can trust step direction.  Scoped to
    # derivation=="nextflow_dsl2": the io_inferred fallback is a permissive,
    # intentionally-bidirectional candidate graph and is exempt.  Computed in
    # Python (Cypher can't introspect the JSON ``derivation``); violations = count
    # of nodes left in cycles (0 == acyclic) via Kahn topological elimination.
    def _downstream_cycle_violations() -> int:
        rows = _qall("MATCH (a)-[r:Rel{kind:'DOWNSTREAM_OF'}]->(b) "
                     "RETURN a.id, b.id, r.properties")
        adj: dict[str, list[str]] = defaultdict(list)
        indeg: dict[str, int] = defaultdict(int)
        nodes: set[str] = set()
        for a_id, b_id, props_str in rows:
            try:
                props = json.loads(props_str or "{}")
            except (json.JSONDecodeError, TypeError):
                props = {}
            if props.get("derivation") != "nextflow_dsl2":
                continue
            adj[a_id].append(b_id)
            indeg[b_id] += 1
            nodes.add(a_id)
            nodes.add(b_id)
        q = deque(n for n in nodes if indeg[n] == 0)
        removed = 0
        while q:
            u = q.popleft()
            removed += 1
            for w in adj[u]:
                indeg[w] -= 1
                if indeg[w] == 0:
                    q.append(w)
        return len(nodes) - removed

    _cyc_bad = _downstream_cycle_violations()
    invariants.append(Invariant(
        name="DOWNSTREAM_OF: acyclic (nextflow_dsl2 ground-truth)",
        violations=_cyc_bad, ok=(_cyc_bad == 0)))

    # ------------------------------------------------------------------
    # 4. SAME_AS candidates
    # ------------------------------------------------------------------
    total_same_as: int = _q1("MATCH ()-[r:Rel{kind:'SAME_AS'}]->() RETURN count(r)")
    by_basis: dict[str, int] = {}
    if total_same_as > 0:
        same_as_rows = _qall(
            "MATCH ()-[r:Rel{kind:'SAME_AS'}]->() RETURN r.properties"
        )
        for row in same_as_rows:
            props_str = row[0] or "{}"
            try:
                props = json.loads(props_str)
            except (json.JSONDecodeError, TypeError):
                props = {}
            basis = props.get("basis", "unknown")
            by_basis[basis] = by_basis.get(basis, 0) + 1
    same_as: dict = {"total": total_same_as, "by_basis": by_basis}

    # ------------------------------------------------------------------
    # 5. Coverage
    # ------------------------------------------------------------------
    methods_total: int = _q1("MATCH (m:Entity{kind:'Method'}) RETURN count(m)")

    def _pct(n: int) -> float:
        if methods_total == 0:
            return 0.0
        return round(100 * n / methods_total, 1)

    with_biotools_id: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE m.biotools_id IS NOT NULL AND m.biotools_id <> '' RETURN count(m)"
    )
    with_bioconda_pkg: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE m.bioconda_pkg IS NOT NULL AND m.bioconda_pkg <> '' RETURN count(m)"
    )
    with_container: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[:Rel{kind:'PACKAGED_AS'}]->(:Entity) } RETURN count(m)"
    )
    with_edam_operation: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[:Rel{kind:'PERFORMS'}]->(:Entity) } RETURN count(m)"
    )
    with_io_contract: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[r:Rel]->(:Entity) WHERE r.kind IN ['INPUT','OUTPUT'] } "
        "RETURN count(m)"
    )
    with_statistical_method: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[:Rel{kind:'USES_STATISTICAL_METHOD'}]->(:Entity) } "
        "RETURN count(m)"
    )
    # Methods that inherit a statistical assumption transitively:
    # Method -USES_STATISTICAL_METHOD-> StatisticalMethod -REQUIRES_ASSUMPTION-> Assumption
    with_inherited_assumption: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[:Rel{kind:'USES_STATISTICAL_METHOD'}]->"
        "(:Entity{kind:'StatisticalMethod'})-[:Rel{kind:'REQUIRES_ASSUMPTION'}]->"
        "(:Entity{kind:'Assumption'}) } RETURN count(m)"
    )
    # Methods with a COMPLETE assumption→diagnostic chain — the trustworthiness
    # layer the evaluability gate relies on.  A method reaches a checking diagnostic
    # along EITHER grounded path:
    #   * tool-internal:    Method -USES_STATISTICAL_METHOD-> Stat -REQUIRES-> Assum -CHECKED_BY-> Diag
    #   * operation-mediated: Method -PERFORMS-> Operation -AMENABLE_TO-> Stat -REQUIRES-> Assum -CHECKED_BY-> Diag
    # The operation-mediated path is what SCALES (one curated operation lights up every
    # tool that performs it), so it must be counted; P5's method_preconditions traverses
    # both, and this metric mirrors that contract.
    _USES_CHAIN = (
        "EXISTS { MATCH (m)-[:Rel{kind:'USES_STATISTICAL_METHOD'}]->"
        "(:Entity{kind:'StatisticalMethod'})-[:Rel{kind:'REQUIRES_ASSUMPTION'}]->"
        "(:Entity{kind:'Assumption'})-[:Rel{kind:'CHECKED_BY'}]->(:Entity{kind:'Diagnostic'}) }"
    )
    _AMENABLE_CHAIN = (
        "EXISTS { MATCH (m)-[:Rel{kind:'PERFORMS'}]->(:Entity{kind:'Operation'})"
        "-[:Rel{kind:'AMENABLE_TO'}]->(:Entity{kind:'StatisticalMethod'})"
        "-[:Rel{kind:'REQUIRES_ASSUMPTION'}]->(:Entity{kind:'Assumption'})"
        "-[:Rel{kind:'CHECKED_BY'}]->(:Entity{kind:'Diagnostic'}) }"
    )
    with_checked_assumption: int = _q1(
        f"MATCH (m:Entity{{kind:'Method'}}) WHERE {_USES_CHAIN} OR {_AMENABLE_CHAIN} "
        "RETURN count(m)"
    )
    # Breakdown by path (informational): how many reach it via the scalable
    # operation-mediated route (may overlap with the tool-internal route).
    with_checked_via_operation: int = _q1(
        f"MATCH (m:Entity{{kind:'Method'}}) WHERE {_AMENABLE_CHAIN} RETURN count(m)"
    )
    # The "evaluable method set" — methods carrying ANY grounded statistical-method
    # path (a USES_STATISTICAL_METHOD link OR an operation-mediated AMENABLE_TO link).
    # This is the correct denominator for the complete-chain fraction: with_checked_
    # assumption is a true SUBSET of it (a method can only reach a diagnostic along a
    # path that first reaches a statistical method), so the percentage cannot exceed
    # 100%.  Using with_statistical_method (USES-only) here was a bug: the numerator
    # counts both paths, so the operation-path methods inflated it past 100%.
    with_any_stat_path: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) WHERE "
        "EXISTS { MATCH (m)-[:Rel{kind:'USES_STATISTICAL_METHOD'}]->"
        "(:Entity{kind:'StatisticalMethod'}) } "
        "OR EXISTS { MATCH (m)-[:Rel{kind:'PERFORMS'}]->(:Entity{kind:'Operation'})"
        "-[:Rel{kind:'AMENABLE_TO'}]->(:Entity{kind:'StatisticalMethod'}) } "
        "RETURN count(m)"
    )

    def _pct_of(n: int, denom: int) -> float:
        return round(100 * n / denom, 1) if denom else 0.0

    # ------------------------------------------------------------------
    # Ontology-node counts (informational; one entry per kind present).
    # ------------------------------------------------------------------
    ontology_nodes: dict[str, int] = {}
    for kind_str in sorted(_ONTOLOGY_TERM_KINDS):
        count = _q1(f"MATCH (n:Entity{{kind:'{kind_str}'}}) RETURN count(n)")
        if count > 0:
            ontology_nodes[kind_str] = count

    coverage: dict = {
        "methods_total": methods_total,
        "with_biotools_id": {"count": with_biotools_id, "pct": _pct(with_biotools_id)},
        "with_bioconda_pkg": {"count": with_bioconda_pkg, "pct": _pct(with_bioconda_pkg)},
        "with_container": {"count": with_container, "pct": _pct(with_container)},
        "with_edam_operation": {"count": with_edam_operation, "pct": _pct(with_edam_operation)},
        "with_io_contract": {"count": with_io_contract, "pct": _pct(with_io_contract)},
        "with_statistical_method": {
            "count": with_statistical_method, "pct": _pct(with_statistical_method),
        },
        "with_inherited_assumption": {
            "count": with_inherited_assumption, "pct": _pct(with_inherited_assumption),
        },
        # Complete assumption→diagnostic chain: as a fraction of ALL methods, and of
        # the "evaluable method set" (methods carrying ANY grounded statistical-method
        # path — a USES link or an operation-mediated AMENABLE_TO link) — the meaningful
        # denominator for tracking the P1 gap over time.
        "with_checked_assumption": {
            "count": with_checked_assumption, "pct": _pct(with_checked_assumption),
        },
        "with_checked_via_operation": {
            "count": with_checked_via_operation, "pct": _pct(with_checked_via_operation),
        },
        "used_method_set": {
            "count": with_any_stat_path,
            "with_complete_chain": with_checked_assumption,
            "pct": _pct_of(with_checked_assumption, with_any_stat_path),
        },
        "ontology_nodes": ontology_nodes,
    }

    # ------------------------------------------------------------------
    # 6. Reconciliation (optional)
    # ------------------------------------------------------------------
    reconciliation: dict | None = None
    if snapshot_dir is not None:
        snapshot_dir = Path(snapshot_dir)
        reconciliation = _run_reconciliation(conn, _q1, _qall, snapshot_dir)

    # ------------------------------------------------------------------
    # 7. Overall gate
    # ------------------------------------------------------------------
    ok = (
        all(inv.ok for inv in invariants)
        and duplicate_ids_ok
        and provenance_missing == 0
    )
    if reconciliation is not None:
        edam_section = reconciliation.get("edam", {})
        if not all(
            edam_section.get(k, {}).get("match", True)
            for k in ("operation", "data", "format")
        ):
            ok = False

    return AuditResult(
        node_count=node_count,
        distinct_ids=distinct_ids,
        duplicate_ids_ok=duplicate_ids_ok,
        provenance_missing=provenance_missing,
        invariants=invariants,
        same_as=same_as,
        coverage=coverage,
        reconciliation=reconciliation,
        ok=ok,
    )


# ---------------------------------------------------------------------------
# Internal reconciliation helper
# ---------------------------------------------------------------------------


def _run_reconciliation(conn, _q1, _qall, snapshot_dir: Path) -> dict:
    """Compare snapshot source files against graph node counts."""
    # --- EDAM ---
    edam_tsv = snapshot_dir / "EDAM.tsv"
    src_edam: dict[str, int] = {k: 0 for k in _EDAM_PREFIXES.values()}
    if edam_tsv.exists():
        rows = list(
            csv.DictReader(io.StringIO(edam_tsv.read_text()), delimiter="\t")
        )
        for r in rows:
            if (r.get("Obsolete") or "").strip().upper() == "TRUE":
                continue
            loc = r.get("Class ID", "").rsplit("/", 1)[-1]
            for prefix, kind_key in _EDAM_PREFIXES.items():
                if loc.startswith(prefix):
                    src_edam[kind_key] += 1
                    break

    edam_results: dict[str, dict] = {}
    for kind_key, graph_kind in _EDAM_KINDS_GRAPH.items():
        graph_count = _q1(f"MATCH (n:Entity{{kind:'{graph_kind}'}}) RETURN count(n)")
        tsv_count = src_edam[kind_key]
        edam_results[kind_key] = {
            "tsv": tsv_count,
            "graph": graph_count,
            "match": tsv_count == graph_count,
        }

    # --- nf-core tool count ---
    nfcore_path = snapshot_dir / "modules" / "modules" / "nf-core"
    nfcore_tool_names: int = 0
    if nfcore_path.exists():
        try:
            import yaml  # optional dep — only needed for reconciliation
            tool_set: set[str] = set()
            for mp in nfcore_path.rglob("meta.yml"):
                try:
                    meta = yaml.safe_load(mp.read_text()) or {}
                except Exception:
                    continue
                for t in (meta.get("tools") or []):
                    if isinstance(t, dict) and t:
                        tool_set.add(next(iter(t)).lower())
            nfcore_tool_names = len(tool_set)
        except ImportError:
            nfcore_tool_names = -1  # yaml not available

    graph_methods = _q1("MATCH (m:Entity{kind:'Method'}) RETURN count(m)")

    # --- biocontainers files vs Package nodes ---
    bc_dir = snapshot_dir / "biocontainers"
    biocontainers_files = len(list(bc_dir.glob("*.json"))) if bc_dir.exists() else 0
    graph_packages = _q1("MATCH (n:Entity{kind:'Package'}) RETURN count(n)")

    # --- bio.tools files ---
    bt_dir = snapshot_dir / "biotools"
    biotools_files = len(list(bt_dir.glob("*.json"))) if bt_dir.exists() else 0

    # --- connector fetch failures (from the snapshot.json manifest) ---
    # The fetch step records tools it could NOT download (biocontainers/bio.tools);
    # the build then silently lacks those records.  Surfacing the failure counts here
    # quantifies that coverage gap and tracks it over time.
    fetch_failures: dict[str, dict] = {}
    snap_json = snapshot_dir / "snapshot.json"
    if snap_json.exists():
        try:
            manifest = json.loads(snap_json.read_text())
        except (json.JSONDecodeError, OSError):
            manifest = None
        # Only populate from a well-formed manifest; an unreadable/corrupt snapshot.json
        # leaves fetch_failures empty rather than fabricating zero-failure entries.
        msrc = manifest.get("sources", {}) if isinstance(manifest, dict) else {}
        if isinstance(msrc, dict):
            for key in ("biocontainers", "biotools"):
                entry = msrc.get(key)
                if not isinstance(entry, dict):
                    continue
                failed = entry.get("failed") or []
                fetch_failures[key] = {
                    "n_failed": int(entry.get("n_failed", len(failed)) or 0),
                    "sample": sorted(failed)[:10],
                }

    return {
        "edam": edam_results,
        "sources": {
            "nfcore_tool_names": nfcore_tool_names,
            "graph_methods": graph_methods,
            "biocontainers_files": biocontainers_files,
            "graph_packages": graph_packages,
            "biotools_files": biotools_files,
        },
        "fetch_failures": fetch_failures,
    }
