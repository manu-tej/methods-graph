"""Over-merge audit: replay the resolver's id-only grouping over real nf-core records and report
every group where two DIFFERENT tool names collapsed into one method, with the strong key
that bridged them. Use it to catch entity-resolution over-merge.

    python examples/merge_audit.py --nfcore <snapshot>/modules/modules/nf-core

It mirrors `methods-graph build`'s identity derivation (single-tool modules take the
nf-core tool-directory id), so the groups it reports match the built graph.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from methods_graph.connectors.nfcore import parse_module
from methods_graph.types import MethodRecord
from methods_graph.resolve.resolver import _UnionFind


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nfcore", type=Path, required=True, help="path to modules/nf-core dir")
    args = ap.parse_args()
    root = args.nfcore

    methods: list[MethodRecord] = []
    for mp in sorted(root.rglob("meta.yml")):
        rel = mp.relative_to(root)
        tool_id = rel.parts[0] if len(rel.parts) >= 3 else None   # mirror cmd_build
        nodes, _ = parse_module(mp.parent, ingested_at="audit", tool_id=tool_id)
        methods += [n for n in nodes if isinstance(n, MethodRecord)]

    uf = _UnionFind(len(methods))
    key_to_idx: dict[str, int] = {}
    for i, m in enumerate(methods):
        for key in [f"id::{m.id}"]:  # resolver now hard-merges by id ONLY
            if key in key_to_idx:
                uf.union(i, key_to_idx[key])
            else:
                key_to_idx[key] = i

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(methods)):
        groups[uf.find(i)].append(i)

    multi = []
    absorbed = 0
    for members in groups.values():
        names = sorted({methods[i].name.lower() for i in members})
        if len(names) > 1:
            keys = ['id-only union']
            multi.append((min(methods[i].id for i in members), names, keys))
            absorbed += len(names) - 1

    print(f"method records      : {len(methods)}")
    print(f"canonical methods   : {len(groups)}")
    print(f"multi-name merges   : {len(multi)}   absorbed names : {absorbed}")
    print("=" * 72)
    for canon, names, keys in sorted(multi):
        print(f"{canon:24} names={names}")
        print(f"{'':24} bridged_by={keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
