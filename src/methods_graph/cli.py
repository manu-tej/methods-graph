"""Command-line entry points for the methods graph pipeline.

Implemented subcommands:
  query      -- seed a subgraph by keyword and print RAG text
  methods    -- dump all methods as AnalysisMethod-shaped JSON
  build      -- build the Kùzu DB from local source snapshots (connectors → resolver → loader)
                optionally enriched with bio.tools EDAM operations via --biotools <dir>
  fetch      -- download real source snapshots (EDAM, nf-core/modules, BioContainers)
                and record a versioned snapshot.json manifest for seamless upgrades
  ingest     -- reproducible build from a declarative manifest: fetch the pinned
                pipelines, resolve declared shared sources (fail loudly if any is
                missing), build, gate on the audit, and write an ingest.lock.json
  audit      -- run correctness checks (schema invariants, provenance, dup ids, coverage)
                against a built Kùzu DB; exits 0 if all checks pass, 1 otherwise
  export-kgx -- export the graph to KGX TSV format (nodes.tsv + edges.tsv) for
                interoperability with other Knowledge Graph tools

Deferred subcommands:
  resolve  -- enrich method nodes with pipeline-DAG ordering and external-registry
              enrichment (bio.tools cross-linking etc.)  (Phase 2)
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

_log = logging.getLogger(__name__)


def cmd_query(*, db_path: Path, keywords: list[str], k_hops: int) -> None:
    """Print RAG text for the subgraph seeded by the given keywords."""
    with KuzuMethodsGraphProvider(db_path) as provider:
        print(provider.retrieve_context_for_keywords(keywords, k_hops=k_hops))


def cmd_methods(*, db_path: Path) -> None:
    """Dump all methods as AnalysisMethod-shaped JSON to stdout."""
    with KuzuMethodsGraphProvider(db_path) as provider:
        print(json.dumps(provider.get_methods(), indent=2))


def cmd_suggest(*, db_path: Path, have: list[str], limit: int) -> None:
    """Print attestation-ranked next-step suggestions for the given frontier as JSON."""
    import kuzu
    from methods_graph.planner import expand

    db = conn = None
    try:
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        suggestions = expand(conn, have, limit=limit)
    finally:
        if conn is not None:
            conn.close()
        if db is not None:
            db.close()
    print(json.dumps([s.to_dict() for s in suggestions], indent=2))


def cmd_build(
    *,
    edam: Path | None,
    nfcore_modules: Path | None,
    biocontainers: Path | None,
    nfcore_pipelines: Path | None = None,
    biotools: Path | None = None,
    stato: Path | None = None,
    obi: Path | None = None,
    db_path: Path,
    staging_dir: Path,
    ingested_at: str,
) -> None:
    """Build a Kùzu graph from local source snapshots: connectors → resolver → loader.

    Optional ``--biotools <dir>`` enriches each Method whose biotoolsID matches a
    bio.tools JSON record with PERFORMS (operation) edges.

    Optional ``--stato <path>`` and ``--obi <path>`` load STATO/OBI OWL ontology
    files into StatisticalMethod, Assay, Protocol, StudyDesign, Instrument, and
    Material nodes with IS_A edges.
    """
    # Grouped here for readability (build is the only subcommand that needs these).
    from methods_graph.connectors.edam import parse_edam
    from methods_graph.connectors.nfcore import parse_module
    from methods_graph.connectors.nfcore_pipeline import parse_pipeline
    from methods_graph.connectors.biocontainers import parse_biocontainer
    from methods_graph.connectors.biotools import load_biotools_edam
    from methods_graph.connectors.ontology import parse_stato, parse_obi
    from methods_graph.resolve.resolver import resolve
    from methods_graph.pipeline_merge import merge_downstream_of
    from methods_graph.graph.loader import build_graph
    from methods_graph.types import EdgeKind, EdgeRecord, MethodRecord, NodeKind, Provenance

    all_nodes: list = []
    all_edges: list = []

    # --- guard: fail loudly on non-existent source paths ---
    if edam is not None and not Path(edam).exists():
        raise FileNotFoundError(f"--edam path does not exist: {edam}")
    if nfcore_modules is not None and not Path(nfcore_modules).exists():
        raise FileNotFoundError(f"--nfcore-modules path does not exist: {nfcore_modules}")
    if nfcore_pipelines is not None and not Path(nfcore_pipelines).exists():
        raise FileNotFoundError(f"--nfcore-pipelines path does not exist: {nfcore_pipelines}")
    if biocontainers is not None and not Path(biocontainers).exists():
        raise FileNotFoundError(f"--biocontainers path does not exist: {biocontainers}")
    if biotools is not None and not Path(biotools).exists():
        raise FileNotFoundError(f"--biotools path does not exist: {biotools}")
    if stato is not None and not Path(stato).exists():
        raise FileNotFoundError(f"--stato path does not exist: {stato}")
    if obi is not None and not Path(obi).exists():
        raise FileNotFoundError(f"--obi path does not exist: {obi}")

    # --- EDAM ---
    if edam is not None:
        nodes, edges = parse_edam(edam, ingested_at=ingested_at)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    # --- nf-core modules ---
    # Discover recursively: any directory that directly contains a meta.yml is a module dir.
    # Sorted for deterministic, reproducible builds. De-duplicated via dict-keyed set.
    if nfcore_modules is not None:
        seen_dirs: set[Path] = set()
        for meta_file in sorted(Path(nfcore_modules).rglob("meta.yml")):
            module_dir = meta_file.parent
            if module_dir in seen_dirs:
                continue
            seen_dirs.add(module_dir)
            # Derive the authoritative tool identity from the first path
            # component relative to the modules root.  Real nf-core modules
            # live at ``<tool>/<subcommand>/meta.yml`` (depth ≥ 2), so
            # ``rel.parts[0]`` is unambiguously the tool name.  For example:
            #   bcftools/sort/meta.yml  → tool_id = "bcftools"
            #   bcftools/view/meta.yml  → tool_id = "bcftools"
            # This prevents generic subcommand keys such as ``sort`` or
            # ``view`` from creating separate, colliding method ids when
            # multiple tools share the same sub-command name.
            # For single-level paths (``<tool>/meta.yml``, depth = 1) no
            # override is needed: the directory IS the tool and the meta.yml
            # tool key already matches it.
            rel = meta_file.relative_to(nfcore_modules)
            # Anchor the tool name on the 'nf-core' path segment when present, so
            # nfcore_modules may point at a TREE of pipeline checkouts (ingest):
            #   <pipeline>/modules/nf-core/<tool>/[<subcommand>/]meta.yml
            # Otherwise nfcore_modules IS the modules root: <tool>/[<sub>/]meta.yml.
            parts = rel.parts
            if "nf-core" in parts:
                j = len(parts) - 1 - parts[::-1].index("nf-core")
                after = parts[j + 1:-1]   # components between 'nf-core' and 'meta.yml'
            else:
                after = parts[:-1]        # strip trailing 'meta.yml'
            # A nested (subcommand) module is <tool>/<subcommand> → override the
            # generic meta key with the directory-derived tool; a flat <tool> dir
            # already matches its meta key, so no override (None).
            tool_id = after[0] if len(after) >= 2 else None
            nodes, edges = parse_module(module_dir, ingested_at=ingested_at,
                                        tool_id=tool_id)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    # --- biocontainers ---
    if biocontainers is not None:
        for json_path in sorted(Path(biocontainers).glob("*.json")):
            data = json.loads(json_path.read_text())
            nodes, edges = parse_biocontainer(data, ingested_at=ingested_at)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    # --- nf-core pipelines ---
    # A pipeline root is a dir with modules.json AND a modules/nf-core/ tree;
    # rglob is unanchored, so skip nested/decoy modules.json files.
    if nfcore_pipelines is not None:
        for mj in sorted(Path(nfcore_pipelines).rglob("modules.json")):
            if not (mj.parent / "modules" / "nf-core").is_dir():
                continue
            nodes, edges = parse_pipeline(mj.parent, ingested_at=ingested_at)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    # --- STATO ---
    if stato is not None:
        stato_nodes, stato_edges = parse_stato(Path(stato), ingested_at=ingested_at)
        all_nodes.extend(stato_nodes)
        all_edges.extend(stato_edges)

    # --- OBI ---
    if obi is not None:
        obi_nodes, obi_edges = parse_obi(Path(obi), ingested_at=ingested_at)
        all_nodes.extend(obi_nodes)
        all_edges.extend(obi_edges)

    # --- partition method vs other nodes ---
    method_nodes = [n for n in all_nodes if isinstance(n, MethodRecord)]
    other_nodes = [n for n in all_nodes if not isinstance(n, MethodRecord)]

    # --- warn on empty build ---
    if not all_nodes:
        _log.warning("build produced an empty graph; no sources resolved to any nodes")

    # Accumulate DOWNSTREAM_OF attestations BEFORE resolve.  resolve() dedupes
    # edges by (from,to,kind) keeping only the first edge's properties, which
    # would drop the per-pipeline metadata of duplicate cross-pipeline orderings.
    # DOWNSTREAM_OF endpoints are module ids (mod:<name>), which resolve does not
    # remap, so pre-resolve keys are final.  (If method-level DOWNSTREAM_OF is ever
    # added, this must move after resolve AND resolve must preserve duplicate
    # DOWNSTREAM_OF metadata.)
    all_edges = merge_downstream_of(all_edges)

    # --- resolve ---
    resolved_nodes, resolved_edges = resolve(
        method_nodes=method_nodes,
        other_nodes=other_nodes,
        src_edges=all_edges,
        ingested_at=ingested_at,
    )

    # --- bio.tools EDAM enrichment (post-resolve, pre-load) ---
    bt_edges_added = 0
    if biotools is not None:
        bt_map = load_biotools_edam(Path(biotools))
        bt_prov = Provenance("biotools", "https://bio.tools", ingested_at)
        # Build a set of existing (from_id, to_id, kind) triples for deduplication.
        existing_edge_keys: set[tuple[str, str, str]] = {
            (e.from_id, e.to_id, e.kind.value) for e in resolved_edges
        }
        extra_edges: list[EdgeRecord] = []
        for node in resolved_nodes:
            if not isinstance(node, MethodRecord):
                continue
            bt_id = (node.biotools_id or "").strip().lower()
            if not bt_id or bt_id not in bt_map:
                continue
            info = bt_map[bt_id]
            for op_id in info["operations"]:
                key = (node.id, op_id, EdgeKind.PERFORMS.value)
                if key not in existing_edge_keys:
                    extra_edges.append(EdgeRecord(node.id, op_id, EdgeKind.PERFORMS, {}, bt_prov))
                    existing_edge_keys.add(key)
        resolved_edges = list(resolved_edges) + extra_edges
        bt_edges_added = len(extra_edges)
        if bt_edges_added:
            _log.info("bio.tools enrichment: added %d PERFORMS edges", bt_edges_added)

    # --- curated module-context operation corrections + backfill (review I2 + I1) ---
    # bio.tools tags the *tool*; nf-core uses a specific *subcommand*, so some
    # tool-level PERFORMS edges are wrong (removed here) and utility tools are
    # missing (backfilled here).  Runs AFTER bio.tools enrichment so removes can
    # delete bio.tools edges; adds emit only when both endpoints exist.
    from methods_graph.crosslinks.method_operations import build_operation_edits

    mo_add, mo_remove, mo_report = build_operation_edits(resolved_nodes, ingested_at=ingested_at)
    _before_mo = len(resolved_edges)
    if mo_remove:
        resolved_edges = [
            e for e in resolved_edges
            if (e.from_id, e.to_id, e.kind.value) not in mo_remove
        ]
    mo_removed = _before_mo - len(resolved_edges)
    mo_existing = {(e.from_id, e.to_id, e.kind.value) for e in resolved_edges}
    new_mo = [e for e in mo_add if (e.from_id, e.to_id, e.kind.value) not in mo_existing]
    resolved_edges = list(resolved_edges) + new_mo
    mo_edges_added = len(new_mo)
    if mo_report.skipped:
        _log.info("method-operations: skipped %d add(s) (no matching node in this build): %s",
                  len(mo_report.skipped), mo_report.skipped)
    if mo_removed or mo_edges_added:
        _log.info("method-operations: removed %d wrong PERFORMS edge(s), added %d curated PERFORMS edge(s)",
                  mo_removed, mo_edges_added)

    # --- curated Method→StatisticalMethod cross-links (post-resolve, pre-load) ---
    # Only runs when StatisticalMethod nodes are present (i.e. STATO/OBI loaded);
    # otherwise the targets cannot exist and the step is a no-op.  The builder
    # emits an edge only when BOTH endpoints resolve to the right kinds, so it
    # never creates a dangling/mistyped link; skipped links are logged, not
    # silently dropped.
    xl_edges_added = 0
    amenable_edges_added = 0
    has_stat_method = any(n.kind == NodeKind.STATISTICAL_METHOD for n in resolved_nodes)
    if has_stat_method:
        from methods_graph.crosslinks import build_crosslink_edges

        xl_edges, xl_report = build_crosslink_edges(resolved_nodes, ingested_at=ingested_at)
        existing_keys: set[tuple[str, str, str]] = {
            (e.from_id, e.to_id, e.kind.value) for e in resolved_edges
        }
        # Mirror the bio.tools dedup: grow the key set as we accept edges so a
        # future multi-entry map can never inject a duplicate triple.
        new_xl: list[EdgeRecord] = []
        for e in xl_edges:
            key = (e.from_id, e.to_id, e.kind.value)
            if key not in existing_keys:
                new_xl.append(e)
                existing_keys.add(key)
        resolved_edges = list(resolved_edges) + new_xl
        xl_edges_added = len(new_xl)
        if xl_report.skipped:
            _log.info(
                "crosslinks: skipped %d ungrounded/unmatched link(s): %s",
                len(xl_report.skipped), xl_report.skipped,
            )
        for w in xl_report.warnings:
            _log.warning("crosslinks: %s", w)
        if xl_edges_added:
            _log.info("crosslinks: added %d USES_STATISTICAL_METHOD edges", xl_edges_added)

        # Statistical-method assumptions: mint Assumption nodes + grounded
        # REQUIRES_ASSUMPTION edges (StatisticalMethod→Assumption).  Methods
        # inherit these transitively via USES_STATISTICAL_METHOD.
        from methods_graph.crosslinks.assumptions import build_assumption_records

        a_nodes, a_edges, a_report = build_assumption_records(
            resolved_nodes, ingested_at=ingested_at
        )
        existing_node_ids = {n.id for n in resolved_nodes}
        new_a_nodes = [n for n in a_nodes if n.id not in existing_node_ids]
        resolved_nodes = list(resolved_nodes) + new_a_nodes
        new_a_edges: list[EdgeRecord] = []
        for e in a_edges:
            key = (e.from_id, e.to_id, e.kind.value)
            if key not in existing_keys:
                new_a_edges.append(e)
                existing_keys.add(key)
        resolved_edges = list(resolved_edges) + new_a_edges
        assum_edges_added = len(new_a_edges)
        if a_report.skipped:
            _log.info(
                "assumptions: skipped %d unmatched edge(s): %s",
                len(a_report.skipped), a_report.skipped,
            )
        if assum_edges_added:
            _log.info(
                "assumptions: minted %d Assumption nodes, added %d REQUIRES_ASSUMPTION edges",
                len(new_a_nodes), assum_edges_added,
            )

        # Applicable statistics: grounded Operation→StatisticalMethod AMENABLE_TO
        # edges (what statistics you can run ON a step's results).  A Method becomes
        # amenable transitively via PERFORMS.  No-op unless Operation nodes exist.
        from methods_graph.crosslinks.amenable import build_amenable_edges

        am_edges, am_report = build_amenable_edges(resolved_nodes, ingested_at=ingested_at)
        new_am: list[EdgeRecord] = []
        for e in am_edges:
            key = (e.from_id, e.to_id, e.kind.value)
            if key not in existing_keys:
                new_am.append(e)
                existing_keys.add(key)
        resolved_edges = list(resolved_edges) + new_am
        amenable_edges_added = len(new_am)
        if am_report.skipped:
            _log.info(
                "amenable: skipped %d unmatched link(s): %s",
                len(am_report.skipped), am_report.skipped,
            )
        for w in am_report.warnings:
            _log.warning("amenable: %s", w)
        if amenable_edges_added:
            _log.info("amenable: added %d AMENABLE_TO edges", amenable_edges_added)
    else:
        assum_edges_added = 0

    # --- load ---
    summary = build_graph(resolved_nodes, resolved_edges, db_path, staging_dir=staging_dir)

    # --- summary ---

    n_methods = sum(1 for n in resolved_nodes if isinstance(n, MethodRecord))
    bt_suffix = f", {bt_edges_added} bio.tools edges added" if biotools is not None else ""

    _ONTOLOGY_KINDS = {
        NodeKind.STATISTICAL_METHOD, NodeKind.ASSAY, NodeKind.PROTOCOL,
        NodeKind.STUDY_DESIGN, NodeKind.INSTRUMENT, NodeKind.MATERIAL,
        NodeKind.ASSUMPTION, NodeKind.DIAGNOSTIC,
    }
    n_onto = sum(1 for n in resolved_nodes if n.kind in _ONTOLOGY_KINDS)
    onto_suffix = f", {n_onto} ontology nodes" if (stato is not None or obi is not None) else ""
    xl_suffix = (
        f", {xl_edges_added} stat-method links, {assum_edges_added} assumption links"
        f", {amenable_edges_added} amenable-stat links"
        if has_stat_method else ""
    )
    n_pipes = sum(1 for n in resolved_nodes if n.kind == NodeKind.PIPELINE)
    pipe_suffix = f", {n_pipes} pipelines" if nfcore_pipelines is not None else ""
    mo_suffix = (
        f", curated PERFORMS (+{mo_edges_added}/-{mo_removed})"
        if (mo_edges_added or mo_removed) else ""
    )

    print(
        f"Built graph: {n_methods} methods, {summary['nodes']} nodes, "
        f"{summary['edges_loaded']} edges loaded "
        f"({summary['edges_dropped']} dangling dropped){pipe_suffix}{bt_suffix}{onto_suffix}{xl_suffix}{mo_suffix} -> {db_path}"
    )


def cmd_ingest(
    *,
    manifest_path: Path,
    dest: Path,
    db_path: Path,
    staging_dir: Path,
    ingested_at: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict:
    """Reproducible, declarative ingest: fetch declared pipelines, resolve declared
    shared sources (fail loudly if any is missing), build, gate on the audit, and
    write an ``ingest.lock.json`` recording exactly what went in.

    Method nodes + DAG wiring come from each pipeline's OWN vendored modules
    (version-matched), so ``nfcore_modules``/``nfcore_pipelines`` both point at the
    fetched pipelines tree.  The audit runs as a HARD gate: a graph that fails any
    invariant raises (the lock is still written, recording the failure).
    """
    import hashlib

    import kuzu

    from methods_graph.audit import audit_graph
    from methods_graph.fetch import fetch_nfcore_pipeline
    from methods_graph.ingest import load_manifest, resolve_sources

    dest = Path(dest)
    spec = load_manifest(manifest_path)

    # 1. Resolve shared sources FIRST — cheap, no network; fails loudly listing
    #    every declared-but-missing source so a build never silently drops a layer.
    sources = resolve_sources(spec)

    # 2. Fetch each declared pipeline (clone@revision + ground-truth DAG, NXF pinned).
    dest.mkdir(parents=True, exist_ok=True)
    pipeline_manifests: list[dict] = []
    for p in spec.pipelines:
        pm = fetch_nfcore_pipeline(p.name, dest, revision=p.revision, nxf_ver=p.nxf_ver,
                                   fetched_at=ingested_at, runner=runner)
        pipeline_manifests.append(pm)
        _log.info("ingest: fetched %s@%s commit=%s dag=%s",
                  p.name, p.revision, (pm["commit"] or "")[:12], pm["dag"])

    pipelines_root = dest / "pipelines"
    have_pipelines = bool(spec.pipelines)

    # 3. Build from the resolved shared sources + the pipelines' vendored modules.
    cmd_build(
        edam=sources.get("edam"),
        nfcore_modules=pipelines_root if have_pipelines else None,
        nfcore_pipelines=pipelines_root if have_pipelines else None,
        biocontainers=sources.get("biocontainers"),
        biotools=sources.get("biotools"),
        stato=sources.get("stato"),
        obi=sources.get("obi"),
        db_path=db_path,
        staging_dir=staging_dir,
        ingested_at=ingested_at,
    )

    # 4. Audit gate.
    db = conn = None
    try:
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        audit = audit_graph(conn)
    finally:
        if conn is not None:
            conn.close()
        if db is not None:
            db.close()

    # 5. Lock — record exactly what went in (written even on audit failure).
    def _digest(p: Path) -> str:
        p = Path(p)
        if p.is_file():
            return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        return "dir"

    lock = {
        "ingested_at": ingested_at,
        "manifest": str(Path(manifest_path)),
        "db": str(db_path),
        "pipelines": pipeline_manifests,
        "sources": {k: {"path": str(v), "digest": _digest(v)} for k, v in sources.items()},
        "audit": {
            "ok": audit.ok,
            "node_count": audit.node_count,
            "invariants_total": len(audit.invariants),
            "invariants_passed": sum(1 for i in audit.invariants if i.ok),
        },
    }
    lock_path = dest / "ingest.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True))

    if not audit.ok:
        failing = [i.name for i in audit.invariants if not i.ok]
        raise RuntimeError(f"ingest: audit FAILED {failing}; lock written to {lock_path}")

    print(
        f"Ingested {len(spec.pipelines)} pipeline(s): {audit.node_count} nodes, "
        f"audit OK ({lock['audit']['invariants_passed']}/{lock['audit']['invariants_total']}) "
        f"-> {db_path}  (lock: {lock_path})"
    )
    return lock


def cmd_audit(*, db_path: Path, snapshot_dir: Path | None, as_json: bool) -> int:
    """Run KG correctness checks and print a report.

    Returns 0 if all checks pass, 1 if any check fails.
    """
    from methods_graph.audit import audit_graph

    db = None
    conn = None
    try:
        import kuzu
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        result = audit_graph(conn, snapshot_dir=snapshot_dir)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    if as_json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(result.to_text())

    return 0 if result.ok else 1


def cmd_fetch(
    *,
    dest: Path,
    do_edam: bool,
    do_nfcore: bool,
    do_biocontainers: bool,
    do_biotools: bool = True,
    do_stato: bool = True,
    do_obi: bool = True,
    fetched_at: str,
    # Injectable network seams (default to real stdlib helpers; override in tests).
    _edam_http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
    _nfcore_runner: Callable[..., Any] | None = None,
    _bc_http_get_json: Callable[[str], Any] | None = None,
    _biotools_http_get_json: Callable[[str], Any] | None = None,
    _stato_http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
    _obi_http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
) -> None:
    """Download source snapshots and write a snapshot.json manifest.

    Order of operations:
      1. Fetch EDAM TSV (if --no-edam not set).
      2. Shallow-clone nf-core/modules (if --no-nfcore not set).
      3. Derive bioconda package names from the cloned modules tree.
      4. Fetch BioContainers records for those packages (if --no-biocontainers not set).
      5. Derive bio.tools IDs from the cloned modules tree.
      6. Fetch bio.tools records for those IDs (if --no-biotools not set).
      7. Fetch STATO OWL (if --no-stato not set).
      8. Fetch OBI OWL (if --no-obi not set).
      9. Write snapshot.json manifest.

    The ``_edam_http_get``, ``_nfcore_runner``, ``_bc_http_get_json``,
    ``_biotools_http_get_json``, ``_stato_http_get``, and ``_obi_http_get``
    parameters are optional injectable seams for unit testing.  When *None*
    (the default used by ``main()``), the real stdlib helpers are used.  Do
    not pass these from the CLI; they exist solely to make the function
    testable without a network.
    """
    from methods_graph.fetch import (
        bioconda_packages_from_nfcore,
        biotools_ids_from_nfcore,
        fetch_biocontainers,
        fetch_biotools,
        fetch_edam,
        fetch_nfcore,
        fetch_stato,
        fetch_obi,
        write_manifest,
        _stdlib_http_get,
        _stdlib_http_get_json,
    )

    # Resolve injectable seams to defaults if not provided.
    edam_http_get = _edam_http_get if _edam_http_get is not None else _stdlib_http_get
    nfcore_runner = _nfcore_runner if _nfcore_runner is not None else subprocess.run
    bc_http_get_json = _bc_http_get_json if _bc_http_get_json is not None else _stdlib_http_get_json
    bt_http_get_json = _biotools_http_get_json if _biotools_http_get_json is not None else _stdlib_http_get_json
    stato_http_get = _stato_http_get if _stato_http_get is not None else _stdlib_http_get
    obi_http_get = _obi_http_get if _obi_http_get is not None else _stdlib_http_get

    dest.mkdir(parents=True, exist_ok=True)

    edam_manifest: dict | None = None
    nfcore_manifest: dict | None = None
    biocontainers_manifest: dict | None = None
    biotools_manifest: dict | None = None
    stato_manifest: dict | None = None
    obi_manifest: dict | None = None

    # --- EDAM ---
    if do_edam:
        print("Fetching EDAM ontology TSV …")
        edam_manifest = fetch_edam(dest, fetched_at=fetched_at, http_get=edam_http_get)
        print(f"  EDAM: {edam_manifest['rows']} rows, sha256={edam_manifest['sha256'][:12]}…")

    # --- nf-core/modules clone ---
    if do_nfcore:
        print("Cloning nf-core/modules (shallow) …")
        nfcore_manifest = fetch_nfcore(dest, fetched_at=fetched_at, runner=nfcore_runner)
        print(f"  nf-core: commit {nfcore_manifest['commit'][:12]}…")

    # Determine the modules path (used by both BioContainers and bio.tools steps).
    if nfcore_manifest is not None:
        modules_path = Path(nfcore_manifest["modules_path"])
    else:
        # Best-effort: look for an existing clone under dest.
        modules_path = dest / "modules" / "modules" / "nf-core"

    # --- BioContainers ---
    if do_biocontainers:
        if modules_path.exists():
            pkg_names = bioconda_packages_from_nfcore(modules_path)
            print(f"  Derived {len(pkg_names)} bioconda package names from nf-core modules.")
        else:
            pkg_names = []
            _log.warning(
                "No nf-core modules path found at %s; skipping BioContainers fetch.", modules_path
            )

        if pkg_names:
            print(f"Fetching BioContainers records for {len(pkg_names)} tools …")
            bc_dir = dest / "biocontainers"
            try:
                biocontainers_manifest = fetch_biocontainers(
                    pkg_names, bc_dir, fetched_at=fetched_at, http_get_json=bc_http_get_json
                )
            except Exception as exc:
                # Wholesale failure (e.g. network down before first iteration).
                # Record partial progress so edam + nfcore are not lost.
                _log.error("BioContainers fetch raised unexpectedly: %s", exc)
                biocontainers_manifest = {
                    "api": "https://api.biocontainers.pro/ga4gh/trs/v2/tools",
                    "fetched_at": fetched_at,
                    "tools": {},
                    "failed": list(pkg_names),
                    "n_failed": len(pkg_names),
                    "error": str(exc),
                }
            n_ok = len(biocontainers_manifest.get("tools", {}))
            n_fail = biocontainers_manifest.get("n_failed", 0)
            print(f"  BioContainers: {n_ok} tools fetched, {n_fail} failed.")
        else:
            print("  BioContainers: no package names — skipping.")

    # --- bio.tools ---
    if do_biotools:
        if modules_path.exists():
            bt_ids = biotools_ids_from_nfcore(modules_path)
            print(f"  Derived {len(bt_ids)} bio.tools IDs from nf-core modules.")
        else:
            bt_ids = []
            _log.warning(
                "No nf-core modules path found at %s; skipping bio.tools fetch.", modules_path
            )

        if bt_ids:
            print(f"Fetching bio.tools records for {len(bt_ids)} tools …")
            biotools_dir = dest / "biotools"
            try:
                biotools_manifest = fetch_biotools(
                    bt_ids, biotools_dir, fetched_at=fetched_at, http_get_json=bt_http_get_json
                )
            except Exception as exc:
                # Wholesale failure — record it so other sources are not lost.
                _log.error("bio.tools fetch raised unexpectedly: %s", exc)
                biotools_manifest = {
                    "api": "https://bio.tools/api/tool",
                    "fetched_at": fetched_at,
                    "n_tools": 0,
                    "failed": list(bt_ids),
                    "n_failed": len(bt_ids),
                    "error": str(exc),
                }
            n_bt_ok = biotools_manifest.get("n_tools", 0)
            n_bt_fail = biotools_manifest.get("n_failed", 0)
            print(f"  bio.tools: {n_bt_ok} tools fetched, {n_bt_fail} failed.")
        else:
            print("  bio.tools: no IDs — skipping.")

    # --- STATO ---
    if do_stato:
        print("Fetching STATO OWL …")
        try:
            stato_manifest = fetch_stato(dest, fetched_at=fetched_at, http_get=stato_http_get)
            ver = stato_manifest.get("version") or "?"
            print(f"  STATO: sha256={stato_manifest['sha256'][:12]}… version={ver}")
        except Exception as exc:
            _log.error("STATO fetch raised unexpectedly: %s", exc)
            stato_manifest = {
                "url": "http://purl.obolibrary.org/obo/stato.owl",
                "fetched_at": fetched_at,
                "sha256": "",
                "version": "",
                "error": str(exc),
            }

    # --- OBI ---
    if do_obi:
        print("Fetching OBI OWL …")
        try:
            obi_manifest = fetch_obi(dest, fetched_at=fetched_at, http_get=obi_http_get)
            ver = obi_manifest.get("version") or "?"
            print(f"  OBI: sha256={obi_manifest['sha256'][:12]}… version={ver}")
        except Exception as exc:
            _log.error("OBI fetch raised unexpectedly: %s", exc)
            obi_manifest = {
                "url": "http://purl.obolibrary.org/obo/obi.owl",
                "fetched_at": fetched_at,
                "sha256": "",
                "version": "",
                "error": str(exc),
            }

    # --- Manifest (always written, even on partial failures) ---
    manifest_path = write_manifest(
        dest,
        edam=edam_manifest,
        nfcore=nfcore_manifest,
        biocontainers=biocontainers_manifest,
        biotools=biotools_manifest,
        stato=stato_manifest,
        obi=obi_manifest,
        created_at=fetched_at,
    )
    print(f"Manifest written: {manifest_path}")


def cmd_export_kgx(*, db_path: Path, out_dir: Path) -> None:
    """Export the Kùzu graph to KGX TSV format (nodes.tsv + edges.tsv)."""
    import kuzu

    from methods_graph.kgx import export_kgx

    db = None
    conn = None
    try:
        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        node_count, edge_count = export_kgx(conn, out_dir)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    print(
        f"Exported KGX: {node_count} nodes, {edge_count} edges"
        f" -> {out_dir}/{{nodes,edges}}.tsv"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="methods-graph",
        description="Methods graph pipeline CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="seed a subgraph by keyword and print RAG text")
    q.add_argument("--db", type=Path, default=Path("data/methods.kuzu"),
                   help="path to the Kùzu database directory")
    q.add_argument("--keyword", action="append", dest="keywords", required=True,
                   metavar="KEYWORD",
                   help="keyword to seed the subgraph (repeatable)")
    q.add_argument("--hops", type=int, default=1,
                   help="number of hops for neighbourhood expansion (default: 1)")

    m = sub.add_parser("methods", help="dump all methods as AnalysisMethod-shaped JSON")
    m.add_argument("--db", type=Path, default=Path("data/methods.kuzu"),
                   help="path to the Kùzu database directory")

    sg = sub.add_parser("suggest",
                        help="suggest attestation-ranked next analysis steps from a frontier")
    sg.add_argument("--db", type=Path, default=Path("data/methods.kuzu"),
                    help="path to the Kùzu database directory")
    sg.add_argument("--have", action="append", dest="have", required=True, metavar="ID",
                    help="a node id you have: a Module step id or EDAM Format/Data id (repeatable)")
    sg.add_argument("--limit", type=int, default=10, help="max suggestions (default: 10)")

    b = sub.add_parser(
        "build",
        help="build the Kùzu DB from local source snapshots (connectors → resolver → loader)",
    )
    b.add_argument("--edam", type=Path, default=None,
                   help="path to EDAM TSV snapshot (optional)")
    b.add_argument("--nfcore-modules", type=Path, default=None, dest="nfcore_modules",
                   help="path to directory of nf-core module subdirectories (optional)")
    b.add_argument("--nfcore-pipelines", type=Path, default=None, dest="nfcore_pipelines",
                   help="path to a directory tree of nf-core pipeline checkouts (optional)")
    b.add_argument("--biocontainers", type=Path, default=None,
                   help="path to directory of biocontainers JSON files (optional)")
    b.add_argument("--biotools", type=Path, default=None,
                   help="path to directory of bio.tools API JSON files for EDAM enrichment (optional)")
    b.add_argument("--stato", type=Path, default=None,
                   help="path to a STATO OWL file for StatisticalMethod nodes (optional)")
    b.add_argument("--obi", type=Path, default=None,
                   help="path to an OBI OWL file for Assay/Protocol/etc. nodes (optional)")
    b.add_argument("--db", type=Path, required=True,
                   help="path to output Kùzu database directory")
    b.add_argument("--staging", type=Path, default=None,
                   help="path to staging directory (default: <db>.staging)")
    b.add_argument("--ingested-at", type=str, default=None, dest="ingested_at",
                   help="ISO date string for provenance (default: today)")

    ing = sub.add_parser(
        "ingest",
        help="reproducible build from a declarative manifest "
             "(fetch pipelines -> build -> audit gate -> lock)",
    )
    ing.add_argument("--manifest", type=Path, required=True, dest="manifest_path",
                     help="path to the ingestion manifest (YAML)")
    ing.add_argument("--dest", type=Path, required=True,
                     help="work dir for pipeline clones + the ingest.lock.json")
    ing.add_argument("--db", type=Path, required=True,
                     help="path to output Kùzu database directory")
    ing.add_argument("--staging", type=Path, default=None,
                     help="path to staging directory (default: <db>.staging)")
    ing.add_argument("--ingested-at", type=str, default=None, dest="ingested_at",
                     help="ISO date string for provenance (default: today)")

    au = sub.add_parser(
        "audit",
        help="run correctness checks against a built Kùzu DB; exits 1 if any check fails",
    )
    au.add_argument("--db", type=Path, required=True,
                    help="path to the built Kùzu database directory")
    au.add_argument("--snapshot", type=Path, default=None, dest="snapshot_dir",
                    help="path to snapshot dir (EDAM.tsv, modules/, biocontainers/, biotools/) "
                         "for reconciliation checks (optional)")
    au.add_argument("--json", action="store_true", dest="as_json",
                    help="emit JSON instead of human-readable text")

    f = sub.add_parser(
        "fetch",
        help="download source snapshots (EDAM, nf-core/modules, BioContainers) and write a manifest",
    )
    f.add_argument(
        "--dest", type=Path, required=True,
        help="destination directory for downloaded snapshots and snapshot.json",
    )
    f.add_argument(
        "--no-edam", action="store_false", dest="do_edam",
        help="skip fetching the EDAM TSV",
    )
    f.add_argument(
        "--no-nfcore", action="store_false", dest="do_nfcore",
        help="skip cloning nf-core/modules",
    )
    f.add_argument(
        "--no-biocontainers", action="store_false", dest="do_biocontainers",
        help="skip fetching BioContainers tool records",
    )
    f.add_argument(
        "--no-biotools", action="store_false", dest="do_biotools",
        help="skip fetching bio.tools tool records",
    )
    f.add_argument(
        "--no-stato", action="store_false", dest="do_stato",
        help="skip fetching the STATO OWL ontology",
    )
    f.add_argument(
        "--no-obi", action="store_false", dest="do_obi",
        help="skip fetching the OBI OWL ontology",
    )

    kgx = sub.add_parser(
        "export-kgx",
        help="export the graph to KGX TSV format (nodes.tsv + edges.tsv)",
    )
    kgx.add_argument("--db", type=Path, required=True,
                     help="path to the built Kùzu database directory")
    kgx.add_argument("--out", type=Path, required=True, dest="out_dir",
                     help="output directory for nodes.tsv and edges.tsv")

    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return cmd_audit(
            db_path=args.db,
            snapshot_dir=args.snapshot_dir,
            as_json=args.as_json,
        )
    elif args.cmd == "query":
        cmd_query(db_path=args.db, keywords=args.keywords, k_hops=args.hops)
    elif args.cmd == "methods":
        cmd_methods(db_path=args.db)
    elif args.cmd == "suggest":
        cmd_suggest(db_path=args.db, have=args.have, limit=args.limit)
    elif args.cmd == "build":
        ingested_at = args.ingested_at or datetime.date.today().isoformat()
        staging_dir = args.staging if args.staging is not None else Path(str(args.db) + ".staging")
        cmd_build(
            edam=args.edam,
            nfcore_modules=args.nfcore_modules,
            biocontainers=args.biocontainers,
            nfcore_pipelines=args.nfcore_pipelines,
            biotools=args.biotools,
            stato=args.stato,
            obi=args.obi,
            db_path=args.db,
            staging_dir=staging_dir,
            ingested_at=ingested_at,
        )
    elif args.cmd == "ingest":
        ingested_at = args.ingested_at or datetime.date.today().isoformat()
        staging_dir = args.staging if args.staging is not None else Path(str(args.db) + ".staging")
        cmd_ingest(
            manifest_path=args.manifest_path,
            dest=args.dest,
            db_path=args.db,
            staging_dir=staging_dir,
            ingested_at=ingested_at,
        )
    elif args.cmd == "fetch":
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cmd_fetch(
            dest=args.dest,
            do_edam=args.do_edam,
            do_nfcore=args.do_nfcore,
            do_biocontainers=args.do_biocontainers,
            do_biotools=args.do_biotools,
            do_stato=args.do_stato,
            do_obi=args.do_obi,
            fetched_at=fetched_at,
        )
    elif args.cmd == "export-kgx":
        cmd_export_kgx(db_path=args.db, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
