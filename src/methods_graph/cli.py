"""Command-line entry points for the methods graph pipeline.

Implemented subcommands:
  query      -- seed a subgraph by keyword and print RAG text
  methods    -- dump all methods as AnalysisMethod-shaped JSON
  build      -- build the Kùzu DB from local source snapshots (connectors → resolver → loader)
                optionally enriched with bio.tools EDAM operations/topics via --biotools <dir>
  fetch      -- download real source snapshots (EDAM, nf-core/modules, BioContainers)
                and record a versioned snapshot.json manifest for seamless upgrades
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


def cmd_build(
    *,
    edam: Path | None,
    nfcore_modules: Path | None,
    biocontainers: Path | None,
    biotools: Path | None = None,
    db_path: Path,
    staging_dir: Path,
    ingested_at: str,
) -> None:
    """Build a Kùzu graph from local source snapshots: connectors → resolver → loader.

    Optional ``--biotools <dir>`` enriches each Method whose biotoolsID matches a
    bio.tools JSON record with PERFORMS (operation) and HAS_TOPIC edges.
    """
    # Grouped here for readability (build is the only subcommand that needs these).
    from methods_graph.connectors.edam import parse_edam
    from methods_graph.connectors.nfcore import parse_module
    from methods_graph.connectors.biocontainers import parse_biocontainer
    from methods_graph.connectors.biotools import load_biotools_edam
    from methods_graph.resolve.resolver import resolve
    from methods_graph.graph.loader import build_graph
    from methods_graph.types import EdgeKind, EdgeRecord, MethodRecord, Provenance

    all_nodes: list = []
    all_edges: list = []

    # --- guard: fail loudly on non-existent source paths ---
    if edam is not None and not Path(edam).exists():
        raise FileNotFoundError(f"--edam path does not exist: {edam}")
    if nfcore_modules is not None and not Path(nfcore_modules).exists():
        raise FileNotFoundError(f"--nfcore-modules path does not exist: {nfcore_modules}")
    if biocontainers is not None and not Path(biocontainers).exists():
        raise FileNotFoundError(f"--biocontainers path does not exist: {biocontainers}")
    if biotools is not None and not Path(biotools).exists():
        raise FileNotFoundError(f"--biotools path does not exist: {biotools}")

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
            # rel.parts includes 'meta.yml' at the end; a nested module has
            # at least ['<tool>', '<subcommand>', 'meta.yml'] → len >= 3.
            tool_id = rel.parts[0] if len(rel.parts) >= 3 else None
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

    # --- partition method vs other nodes ---
    method_nodes = [n for n in all_nodes if isinstance(n, MethodRecord)]
    other_nodes = [n for n in all_nodes if not isinstance(n, MethodRecord)]

    # --- warn on empty build ---
    if not all_nodes:
        _log.warning("build produced an empty graph; no sources resolved to any nodes")

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
            for topic_id in info["topics"]:
                key = (node.id, topic_id, EdgeKind.HAS_TOPIC.value)
                if key not in existing_edge_keys:
                    extra_edges.append(EdgeRecord(node.id, topic_id, EdgeKind.HAS_TOPIC, {}, bt_prov))
                    existing_edge_keys.add(key)
        resolved_edges = list(resolved_edges) + extra_edges
        bt_edges_added = len(extra_edges)
        if bt_edges_added:
            _log.info("bio.tools enrichment: added %d PERFORMS/HAS_TOPIC edges", bt_edges_added)

    # --- load ---
    summary = build_graph(resolved_nodes, resolved_edges, db_path, staging_dir=staging_dir)

    # --- summary ---
    n_methods = sum(1 for n in resolved_nodes if isinstance(n, MethodRecord))
    bt_suffix = f", {bt_edges_added} bio.tools edges added" if biotools is not None else ""
    print(
        f"Built graph: {n_methods} methods, {summary['nodes']} nodes, "
        f"{summary['edges_loaded']} edges loaded "
        f"({summary['edges_dropped']} dangling dropped){bt_suffix} -> {db_path}"
    )


def cmd_audit(*, db_path: Path, snapshot_dir: Path | None, as_json: bool) -> int:
    """Run KG correctness checks and print a report.

    Returns 0 if all checks pass, 1 if any check fails.
    """
    from methods_graph.audit import audit_graph

    db = None
    conn = None
    try:
        import kuzu
        db = kuzu.Database(str(db_path))
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
    fetched_at: str,
    # Injectable network seams (default to real stdlib helpers; override in tests).
    _edam_http_get: Callable[[str], tuple[bytes, dict[str, str]]] | None = None,
    _nfcore_runner: Callable[..., Any] | None = None,
    _bc_http_get_json: Callable[[str], Any] | None = None,
    _biotools_http_get_json: Callable[[str], Any] | None = None,
) -> None:
    """Download source snapshots and write a snapshot.json manifest.

    Order of operations:
      1. Fetch EDAM TSV (if --no-edam not set).
      2. Shallow-clone nf-core/modules (if --no-nfcore not set).
      3. Derive bioconda package names from the cloned modules tree.
      4. Fetch BioContainers records for those packages (if --no-biocontainers not set).
      5. Derive bio.tools IDs from the cloned modules tree.
      6. Fetch bio.tools records for those IDs (if --no-biotools not set).
      7. Write snapshot.json manifest.

    The ``_edam_http_get``, ``_nfcore_runner``, ``_bc_http_get_json``, and
    ``_biotools_http_get_json`` parameters are optional injectable seams for unit
    testing.  When *None* (the default used by ``main()``), the real stdlib helpers
    are used.  Do not pass these from the CLI; they exist solely to make the
    function testable without a network.
    """
    from methods_graph.fetch import (
        bioconda_packages_from_nfcore,
        biotools_ids_from_nfcore,
        fetch_biocontainers,
        fetch_biotools,
        fetch_edam,
        fetch_nfcore,
        write_manifest,
        _stdlib_http_get,
        _stdlib_http_get_json,
    )

    # Resolve injectable seams to defaults if not provided.
    edam_http_get = _edam_http_get if _edam_http_get is not None else _stdlib_http_get
    nfcore_runner = _nfcore_runner if _nfcore_runner is not None else subprocess.run
    bc_http_get_json = _bc_http_get_json if _bc_http_get_json is not None else _stdlib_http_get_json
    bt_http_get_json = _biotools_http_get_json if _biotools_http_get_json is not None else _stdlib_http_get_json

    dest.mkdir(parents=True, exist_ok=True)

    edam_manifest: dict | None = None
    nfcore_manifest: dict | None = None
    biocontainers_manifest: dict | None = None
    biotools_manifest: dict | None = None

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

    # --- Manifest (always written, even on partial failures) ---
    manifest_path = write_manifest(
        dest,
        edam=edam_manifest,
        nfcore=nfcore_manifest,
        biocontainers=biocontainers_manifest,
        biotools=biotools_manifest,
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
        db = kuzu.Database(str(db_path))
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

    b = sub.add_parser(
        "build",
        help="build the Kùzu DB from local source snapshots (connectors → resolver → loader)",
    )
    b.add_argument("--edam", type=Path, default=None,
                   help="path to EDAM TSV snapshot (optional)")
    b.add_argument("--nfcore-modules", type=Path, default=None, dest="nfcore_modules",
                   help="path to directory of nf-core module subdirectories (optional)")
    b.add_argument("--biocontainers", type=Path, default=None,
                   help="path to directory of biocontainers JSON files (optional)")
    b.add_argument("--biotools", type=Path, default=None,
                   help="path to directory of bio.tools API JSON files for EDAM enrichment (optional)")
    b.add_argument("--db", type=Path, required=True,
                   help="path to output Kùzu database directory")
    b.add_argument("--staging", type=Path, default=None,
                   help="path to staging directory (default: <db>.staging)")
    b.add_argument("--ingested-at", type=str, default=None, dest="ingested_at",
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
    elif args.cmd == "build":
        ingested_at = args.ingested_at or datetime.date.today().isoformat()
        staging_dir = args.staging if args.staging is not None else Path(str(args.db) + ".staging")
        cmd_build(
            edam=args.edam,
            nfcore_modules=args.nfcore_modules,
            biocontainers=args.biocontainers,
            biotools=args.biotools,
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
            fetched_at=fetched_at,
        )
    elif args.cmd == "export-kgx":
        cmd_export_kgx(db_path=args.db, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
