"""Command-line entry points for the methods graph pipeline.

Implemented subcommands:
  query    -- seed a subgraph by keyword and print RAG text
  methods  -- dump all methods as AnalysisMethod-shaped JSON
  build    -- build the Kùzu DB from local source snapshots (connectors → resolver → loader)
  fetch    -- download real source snapshots (EDAM, nf-core/modules, BioContainers)
              and record a versioned snapshot.json manifest for seamless upgrades

Deferred subcommands:
  resolve  -- enrich method nodes with pipeline-DAG ordering and external-registry
              enrichment (bio.tools cross-linking etc.)  (Phase 2)
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

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
    db_path: Path,
    staging_dir: Path,
    ingested_at: str,
) -> None:
    """Build a Kùzu graph from local source snapshots: connectors → resolver → loader."""
    # Grouped here for readability (build is the only subcommand that needs these).
    from methods_graph.connectors.edam import parse_edam
    from methods_graph.connectors.nfcore import parse_module
    from methods_graph.connectors.biocontainers import parse_biocontainer
    from methods_graph.resolve.resolver import resolve
    from methods_graph.graph.loader import build_graph
    from methods_graph.types import MethodRecord

    all_nodes: list = []
    all_edges: list = []

    # --- guard: fail loudly on non-existent source paths ---
    if edam is not None and not Path(edam).exists():
        raise FileNotFoundError(f"--edam path does not exist: {edam}")
    if nfcore_modules is not None and not Path(nfcore_modules).exists():
        raise FileNotFoundError(f"--nfcore-modules path does not exist: {nfcore_modules}")
    if biocontainers is not None and not Path(biocontainers).exists():
        raise FileNotFoundError(f"--biocontainers path does not exist: {biocontainers}")

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
            nodes, edges = parse_module(module_dir, ingested_at=ingested_at)
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

    # --- load ---
    summary = build_graph(resolved_nodes, resolved_edges, db_path, staging_dir=staging_dir)

    # --- summary ---
    n_methods = sum(1 for n in resolved_nodes if isinstance(n, MethodRecord))
    print(
        f"Built graph: {n_methods} methods, {summary['nodes']} nodes, "
        f"{summary['edges_loaded']} edges loaded "
        f"({summary['edges_dropped']} dangling dropped) -> {db_path}"
    )


def cmd_fetch(
    *,
    dest: Path,
    do_edam: bool,
    do_nfcore: bool,
    do_biocontainers: bool,
    fetched_at: str,
) -> None:
    """Download source snapshots and write a snapshot.json manifest.

    Order of operations:
      1. Fetch EDAM TSV (if --no-edam not set).
      2. Shallow-clone nf-core/modules (if --no-nfcore not set).
      3. Derive bioconda package names from the cloned modules tree.
      4. Fetch BioContainers records for those packages (if --no-biocontainers not set).
      5. Write snapshot.json manifest.
    """
    from methods_graph.fetch import (
        bioconda_packages_from_nfcore,
        fetch_biocontainers,
        fetch_edam,
        fetch_nfcore,
        write_manifest,
    )

    dest.mkdir(parents=True, exist_ok=True)

    edam_manifest: dict | None = None
    nfcore_manifest: dict | None = None
    biocontainers_manifest: dict | None = None

    # --- EDAM ---
    if do_edam:
        print("Fetching EDAM ontology TSV …")
        edam_manifest = fetch_edam(dest, fetched_at=fetched_at)
        print(f"  EDAM: {edam_manifest['rows']} rows, sha256={edam_manifest['sha256'][:12]}…")

    # --- nf-core/modules clone ---
    if do_nfcore:
        print("Cloning nf-core/modules (shallow) …")
        nfcore_manifest = fetch_nfcore(dest, fetched_at=fetched_at)
        print(f"  nf-core: commit {nfcore_manifest['commit'][:12]}…")

    # --- BioContainers ---
    if do_biocontainers:
        # Derive package names from the cloned modules tree (or dest_dir if
        # nfcore was not fetched this run but a previous clone exists).
        if nfcore_manifest is not None:
            modules_path = Path(nfcore_manifest["modules_path"])
        else:
            # Best-effort: look for an existing clone under dest.
            modules_path = dest / "modules" / "modules" / "nf-core"

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
                    pkg_names, bc_dir, fetched_at=fetched_at
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

    # --- Manifest (always written, even on partial failures) ---
    manifest_path = write_manifest(
        dest,
        edam=edam_manifest,
        nfcore=nfcore_manifest,
        biocontainers=biocontainers_manifest,
        created_at=fetched_at,
    )
    print(f"Manifest written: {manifest_path}")


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
    b.add_argument("--db", type=Path, required=True,
                   help="path to output Kùzu database directory")
    b.add_argument("--staging", type=Path, default=None,
                   help="path to staging directory (default: <db>.staging)")
    b.add_argument("--ingested-at", type=str, default=None, dest="ingested_at",
                   help="ISO date string for provenance (default: today)")

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

    args = parser.parse_args(argv)
    if args.cmd == "query":
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
            fetched_at=fetched_at,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
