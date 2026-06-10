"""Correctness audit: reconcile a built graph against its source snapshot + check invariants.

This is how we answer "is the generated KG correct?" with evidence rather than assertion.
It does three things:

  PART 1  RECONCILIATION  — source counts vs graph counts (catches silent drops/loss)
  PART 2  INVARIANTS      — schema integrity (edges connect the right node kinds; PKs unique;
                            every node has provenance)
  PART 3  GROUND TRUTH    — spot-check one method's edges against the raw source files

Usage:
    python examples/kg_audit.py --snapshot ./snapshot --db methods.kuzu [--method m:salmon]

It exits non-zero if any invariant fails, so it can serve as a CI correctness gate.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import sys
from pathlib import Path

import kuzu
import yaml


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit a built methods graph against its sources")
    ap.add_argument("--snapshot", type=Path, required=True, help="snapshot dir (EDAM.tsv, modules/, biocontainers/, biotools/)")
    ap.add_argument("--db", type=Path, required=True, help="built Kùzu database path")
    ap.add_argument("--method", default="m:salmon", help="method id for the ground-truth spot check")
    args = ap.parse_args()

    snap = args.snapshot
    conn = kuzu.Connection(kuzu.Database(str(args.db)))
    def q(s, p=None): return [r for r in conn.execute(s, parameters=p or {})]
    def n1(s, p=None): return q(s, p)[0][0]

    failures = 0

    print("=" * 70 + "\nPART 1 — RECONCILIATION (source vs graph)\n" + "=" * 70)

    # EDAM: non-obsolete classes by kind (TSV) must equal graph node counts exactly.
    rows = list(csv.DictReader(io.StringIO((snap / "EDAM.tsv").read_text()), delimiter="\t"))
    src_edam = {"operation": 0, "topic": 0, "data": 0, "format": 0}
    for r in rows:
        if (r.get("Obsolete") or "").strip().upper() == "TRUE":
            continue
        loc = r["Class ID"].rsplit("/", 1)[-1]
        for p in src_edam:
            if loc.startswith(p + "_"):
                src_edam[p] += 1
    print("EDAM non-obsolete classes (TSV) vs graph nodes — must match EXACTLY:")
    for k, K in [("operation", "Operation"), ("topic", "Topic"), ("data", "Data"), ("format", "Format")]:
        g = n1(f"MATCH (n:Entity{{kind:'{K}'}}) RETURN count(n)")
        ok = src_edam[k] == g
        failures += not ok
        print(f"  {k:10} TSV={src_edam[k]:5}  graph={g:5}  [{'OK' if ok else 'MISMATCH'}]")

    tool_names = set()
    for mp in (snap / "modules/modules/nf-core").rglob("meta.yml"):
        try:
            meta = yaml.safe_load(mp.read_text()) or {}
        except Exception:
            continue
        for t in (meta.get("tools") or []):
            if isinstance(t, dict) and t:
                tool_names.add(next(iter(t)).lower())
    g_methods = n1("MATCH (m:Entity{kind:'Method'}) RETURN count(m)")
    print(f"\nnf-core unique tool names={len(tool_names)}  graph methods={g_methods} "
          f"(diff {len(tool_names) - g_methods} merged by shared bioconda/bio.tools id — verify no over-merge)")

    print("\n" + "=" * 70 + "\nPART 2 — INVARIANTS (schema integrity)\n" + "=" * 70)
    invariants = [
        ("PERFORMS    Method->Operation", "MATCH (a)-[r:Rel{kind:'PERFORMS'}]->(b) WHERE NOT (a.kind='Method' AND b.kind='Operation') RETURN count(*)"),
        ("HAS_TOPIC   Method->Topic", "MATCH (a)-[r:Rel{kind:'HAS_TOPIC'}]->(b) WHERE NOT (a.kind='Method' AND b.kind='Topic') RETURN count(*)"),
        ("PACKAGED_AS Method->Container", "MATCH (a)-[r:Rel{kind:'PACKAGED_AS'}]->(b) WHERE NOT (a.kind='Method' AND b.kind='Container') RETURN count(*)"),
        ("WRAPS       Module->Method", "MATCH (a)-[r:Rel{kind:'WRAPS'}]->(b) WHERE NOT (a.kind='Module' AND b.kind='Method') RETURN count(*)"),
        ("INPUT/OUTPUT Method->Data|Format", "MATCH (a)-[r:Rel]->(b) WHERE r.kind IN ['INPUT','OUTPUT'] AND NOT (a.kind='Method' AND b.kind IN ['Data','Format']) RETURN count(*)"),
        ("FROM_PACKAGE Container->Package", "MATCH (a)-[r:Rel{kind:'FROM_PACKAGE'}]->(b) WHERE NOT (a.kind='Container' AND b.kind='Package') RETURN count(*)"),
    ]
    for label, query in invariants:
        bad = n1(query)
        failures += bool(bad)
        print(f"  [{'PASS' if bad == 0 else 'FAIL ' + str(bad)}] {label}")
    no_src = n1("MATCH (n:Entity) WHERE n.source IS NULL OR n.source='' RETURN count(n)")
    failures += bool(no_src)
    print(f"  [{'PASS' if no_src == 0 else 'FAIL'}] every node carries a provenance source (missing={no_src})")
    total, distinct = n1("MATCH (n:Entity) RETURN count(n)"), n1("MATCH (n:Entity) RETURN count(DISTINCT n.id)")
    failures += total != distinct
    print(f"  [{'PASS' if total == distinct else 'FAIL'}] node ids unique ({total} nodes / {distinct} ids)")

    print("\n" + "=" * 70 + f"\nPART 3 — GROUND TRUTH SPOT CHECK ({args.method})\n" + "=" * 70)
    g_ops = sorted(r[0] for r in q("MATCH (m:Entity{id:$id})-[:Rel{kind:'PERFORMS'}]->(o) RETURN o.id", {"id": args.method}))
    name = (args.method.split(":", 1)[-1]).lower()
    src_ops = None
    for f in glob.glob(str(snap / "biotools/*.json")):
        try:
            rec = json.load(open(f))
        except Exception:
            continue
        if (rec.get("biotoolsID") or "").lower() == name:
            src_ops = sorted({"op:" + o["uri"].rsplit("/", 1)[-1]
                              for b in (rec.get("function") or []) for o in (b.get("operation") or [])})
            break
    print(f"  graph PERFORMS : {g_ops}")
    print(f"  bio.tools src  : {src_ops}")
    if src_ops is not None:
        subset = set(g_ops) <= set(src_ops)
        failures += not subset
        print(f"  [{'PASS' if subset else 'FAIL'}] graph ops are a faithful subset of source "
              f"(dropped = EDAM ids absent from the snapshot: {sorted(set(src_ops) - set(g_ops))})")

    print("\n" + "=" * 70)
    print(f"AUDIT RESULT: {'ALL CHECKS PASSED' if failures == 0 else str(failures) + ' CHECK(S) FAILED'}")
    print("=" * 70)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
