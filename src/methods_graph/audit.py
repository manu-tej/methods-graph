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
                    "with_edam_operation", "with_topic", "with_io_contract"):
            v = cov.get(key, {})
            lines.append(f"  {key}: {v.get('count', 0)} ({v.get('pct', 0.0)}%)")

        # --- Reconciliation (optional) ---
        if self.reconciliation is not None:
            lines.append("")
            lines.append(sep)
            lines.append("RECONCILIATION (source vs graph)")
            lines.append(sep)
            edam = self.reconciliation.get("edam", {})
            lines.append("  EDAM non-obsolete classes vs graph nodes (must match exactly):")
            for kind in ("operation", "topic", "data", "format"):
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
                    1 for k in ("operation", "topic", "data", "format")
                    if not edam.get(k, {}).get("match", True)
                )
            lines.append(f"AUDIT RESULT: {failed_count} CHECK(S) FAILED")
        lines.append(sep)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# EDAM kind prefixes (local name → tsv key)
# ---------------------------------------------------------------------------

_EDAM_PREFIXES: dict[str, str] = {
    "operation_": "operation",
    "topic_": "topic",
    "data_": "data",
    "format_": "format",
}

_EDAM_KINDS_GRAPH: dict[str, str] = {
    "operation": "Operation",
    "topic": "Topic",
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
            "HAS_TOPIC: Method→Topic",
            "MATCH (a)-[r:Rel{kind:'HAS_TOPIC'}]->(b) "
            "WHERE NOT (a.kind='Method' AND b.kind='Topic') RETURN count(*)",
        ),
        (
            "PACKAGED_AS: Method→Container",
            "MATCH (a)-[r:Rel{kind:'PACKAGED_AS'}]->(b) "
            "WHERE NOT (a.kind='Method' AND b.kind='Container') RETURN count(*)",
        ),
        (
            "WRAPS: Module→Method",
            "MATCH (a)-[r:Rel{kind:'WRAPS'}]->(b) "
            "WHERE NOT (a.kind='Module' AND b.kind='Method') RETURN count(*)",
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
            # EDAM itself contains a small number of cross-branch subClassOf edges
            # (e.g. operation_3923 Genome-resequencing → topic_3168 Sequencing).
            # Our graph faithfully represents those, so we must NOT require both
            # endpoints to share the same kind.  The invariant only rejects IS_A
            # edges whose endpoints are not EDAM classes at all (e.g. Method or
            # Container nodes as src/dst) — those would be a genuine modelling error.
            "IS_A: EDAM class→EDAM class",
            "MATCH (a)-[r:Rel{kind:'IS_A'}]->(b) "
            "WHERE NOT (a.kind IN ['Operation','Topic','Data','Format'] "
            "AND b.kind IN ['Operation','Topic','Data','Format']) "
            "RETURN count(*)",
        ),
    ]

    invariants: list[Invariant] = []
    for inv_name, inv_cypher in _invariant_specs:
        violations = _q1(inv_cypher)
        invariants.append(Invariant(name=inv_name, violations=violations, ok=(violations == 0)))

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
    with_topic: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[:Rel{kind:'HAS_TOPIC'}]->(:Entity) } RETURN count(m)"
    )
    with_io_contract: int = _q1(
        "MATCH (m:Entity{kind:'Method'}) "
        "WHERE EXISTS { MATCH (m)-[r:Rel]->(:Entity) WHERE r.kind IN ['INPUT','OUTPUT'] } "
        "RETURN count(m)"
    )

    coverage: dict = {
        "methods_total": methods_total,
        "with_biotools_id": {"count": with_biotools_id, "pct": _pct(with_biotools_id)},
        "with_bioconda_pkg": {"count": with_bioconda_pkg, "pct": _pct(with_bioconda_pkg)},
        "with_container": {"count": with_container, "pct": _pct(with_container)},
        "with_edam_operation": {"count": with_edam_operation, "pct": _pct(with_edam_operation)},
        "with_topic": {"count": with_topic, "pct": _pct(with_topic)},
        "with_io_contract": {"count": with_io_contract, "pct": _pct(with_io_contract)},
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
            for k in ("operation", "topic", "data", "format")
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

    return {
        "edam": edam_results,
        "sources": {
            "nfcore_tool_names": nfcore_tool_names,
            "graph_methods": graph_methods,
            "biocontainers_files": biocontainers_files,
            "graph_packages": graph_packages,
            "biotools_files": biotools_files,
        },
    }
