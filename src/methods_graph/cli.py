"""Command-line entry points for the methods graph pipeline.

Implemented subcommands:
  query    -- seed a subgraph by keyword and print RAG text
  methods  -- dump all methods as AnalysisMethod-shaped JSON
  build    -- build the Kùzu DB from local source snapshots (connectors → resolver → loader)

Deferred subcommands:
  resolve  -- enrich method nodes from external registries (bioconda, bio.tools, etc.)
              (pipeline-DAG / external-registry enrichment is Phase 2)
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider


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
    # Import building blocks here (not at module level) to keep CLI import cheap
    from methods_graph.connectors.edam import parse_edam
    from methods_graph.connectors.nfcore import parse_module
    from methods_graph.connectors.biocontainers import parse_biocontainer
    from methods_graph.resolve.resolver import resolve
    from methods_graph.graph.loader import build_graph
    from methods_graph.types import MethodRecord

    all_nodes: list = []
    all_edges: list = []

    # --- EDAM ---
    if edam is not None:
        nodes, edges = parse_edam(edam, ingested_at=ingested_at)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    # --- nf-core modules ---
    if nfcore_modules is not None:
        for subdir in sorted(p for p in nfcore_modules.iterdir() if p.is_dir()):
            if not (subdir / "meta.yml").exists():
                continue
            nodes, edges = parse_module(subdir, ingested_at=ingested_at)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    # --- biocontainers ---
    if biocontainers is not None:
        for json_path in sorted(biocontainers.glob("*.json")):
            data = json.loads(json_path.read_text())
            nodes, edges = parse_biocontainer(data, ingested_at=ingested_at)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    # --- partition method vs other nodes ---
    method_nodes = [n for n in all_nodes if isinstance(n, MethodRecord)]
    other_nodes = [n for n in all_nodes if not isinstance(n, MethodRecord)]

    # --- resolve ---
    resolved_nodes, resolved_edges = resolve(
        method_nodes=method_nodes,
        other_nodes=other_nodes,
        src_edges=all_edges,
        ingested_at=ingested_at,
    )

    # --- load ---
    build_graph(resolved_nodes, resolved_edges, db_path, staging_dir=staging_dir)

    # --- summary ---
    n_methods = sum(1 for n in resolved_nodes if isinstance(n, MethodRecord))
    print(
        f"Built graph: {n_methods} methods, {len(resolved_nodes)} nodes, "
        f"{len(resolved_edges)} edges -> {db_path}"
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
    b.add_argument("--db", type=Path, required=True,
                   help="path to output Kùzu database directory")
    b.add_argument("--staging", type=Path, default=None,
                   help="path to staging directory (default: <db>.staging)")
    b.add_argument("--ingested-at", type=str, default=None, dest="ingested_at",
                   help="ISO date string for provenance (default: today)")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
