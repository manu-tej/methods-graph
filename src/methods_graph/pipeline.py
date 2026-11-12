"""Reproducible-build pipeline helpers: a content fingerprint of the graph, snapshot
checksum verification, the build lock, and a coverage diff between builds.

All functions here are deterministic and free of hidden I/O (they read only the paths /
connection they are handed), so the reproducibility logic is unit-testable in isolation.
The CLI orchestrator (`cmd_rebuild`) wires them to the real build + audit.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

# Provenance columns are EXCLUDED from the content hash: `ingested_at` is a build-time
# stamp (would change the hash every day), and `source`/`source_url` are where-it-came-from
# metadata, not graph content. The hash reflects structure + curation only.
_NODE_QUERY = (
    "MATCH (n:Entity) "
    "RETURN n.id, n.name, n.kind, n.properties, n.bioconda_pkg, n.biotools_id "
    "ORDER BY n.id"
)
_EDGE_QUERY = (
    "MATCH (a:Entity)-[r:Rel]->(b:Entity) "
    "RETURN a.id, b.id, r.kind, r.properties "
    "ORDER BY a.id, b.id, r.kind, r.properties"
)

# snapshot.json source key -> the file under snapshots/ whose sha256 it pins.
_SHA256_FILES = {"edam": "EDAM.tsv", "stato": "stato.owl", "obi": "obi.owl"}


def compute_graph_hash(conn: Any) -> str:
    """A deterministic ``sha256:<hex>`` fingerprint of the graph's CONTENT.

    Stable across rebuilds from the same pinned sources and independent of build date
    (the ``ingested_at`` provenance stamp is not included) and of insertion order (rows
    are sorted). Two graphs hash equal iff their node/edge content is identical.
    """
    h = hashlib.sha256()
    node_lines: list[str] = []
    nres = conn.execute(_NODE_QUERY)
    while nres.has_next():
        nid, name, kind, props, bioconda, biotools = nres.get_next()
        node_lines.append(f"{nid}|{name}|{kind}|{props}|{bioconda}|{biotools}")
    h.update("\n".join(node_lines).encode("utf-8"))
    h.update(b"\n==EDGES==\n")
    edge_lines: list[str] = []
    eres = conn.execute(_EDGE_QUERY)
    while eres.has_next():
        a_id, b_id, kind, props = eres.get_next()
        edge_lines.append(f"{a_id}|{b_id}|{kind}|{props}")
    h.update("\n".join(edge_lines).encode("utf-8"))
    return "sha256:" + h.hexdigest()


def verifiable_sources(snapshot_json: dict[str, Any]) -> list[str]:
    """The snapshot.json sources that carry a verifiable pin (a file sha256 or a git commit).

    These are exactly the sources :func:`verify_snapshots` actually checks; the rest
    (biocontainers/biotools record tool lists, not a file hash) are not checksum-verifiable.
    """
    sources = snapshot_json.get("sources") or {}
    out = [k for k in _SHA256_FILES
           if isinstance(sources.get(k), dict) and "sha256" in sources[k]]
    nm = sources.get("nfcore_modules")
    if isinstance(nm, dict) and "commit" in nm:
        out.append("nfcore_modules")
    return sorted(out)


def verify_snapshots(
    snapshot_json: dict[str, Any], snapshots_dir: Path
) -> list[tuple[str, str, str]]:
    """Re-verify each pinned source against ``snapshot.json``.

    Returns ``(source, expected, actual)`` for every source that drifted; an empty list
    means the snapshots match their recorded pins. Sources without a recorded pin (e.g.
    biocontainers/biotools, which record tool lists rather than a file hash) are skipped.
    """
    mismatches: list[tuple[str, str, str]] = []
    sources = snapshot_json.get("sources") or {}

    for key, filename in _SHA256_FILES.items():
        src = sources.get(key)
        if not isinstance(src, dict) or "sha256" not in src:
            continue
        path = snapshots_dir / filename
        if not path.exists():
            mismatches.append((key, src["sha256"], "MISSING"))
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != src["sha256"]:
            mismatches.append((key, src["sha256"], actual))

    modules = sources.get("nfcore_modules")
    if isinstance(modules, dict) and "commit" in modules:
        mdir = snapshots_dir / "modules"
        try:
            actual = subprocess.run(
                ["git", "-C", str(mdir), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            actual = "MISSING"
        if actual != modules["commit"]:
            mismatches.append(("nfcore_modules", modules["commit"], actual))

    return mismatches


# Pin fields worth carrying from snapshot.json into the lock (omit volatile/bulky ones
# like fetched_at, tool lists, urls).
_PIN_FIELDS = ("sha256", "commit", "version", "last_modified")


def build_lock(
    *,
    snapshot_json: dict[str, Any],
    ingested_at: str,
    counts: dict[str, int],
    coverage: dict[str, Any],
    graph_hash: str,
    flags: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the committed build lock — the reproducibility contract."""
    sources: dict[str, dict[str, Any]] = {}
    for key, val in (snapshot_json.get("sources") or {}).items():
        if not isinstance(val, dict):
            continue
        pin = {f: val[f] for f in _PIN_FIELDS if f in val}
        sources[key] = pin
    return {
        "schema": 1,
        "ingested_at": ingested_at,
        "sources": sources,
        "build": {"command": "mg rebuild", "flags": flags},
        "graph_hash": graph_hash,
        "counts": counts,
        "coverage": coverage,
    }


def write_lock(path: Path, lock: dict[str, Any]) -> None:
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_lock(path: Path) -> dict[str, Any] | None:
    """Load a lock file, or ``None`` if it does not exist / is unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _flatten_numbers(d: dict[str, Any] | None, prefix: str) -> dict[str, float]:
    """Flatten nested dicts to dotted keys, keeping only numeric (non-bool) leaves."""
    out: dict[str, float] = {}
    for key, val in (d or {}).items():
        dotted = f"{prefix}{key}"
        if isinstance(val, dict):
            out.update(_flatten_numbers(val, dotted + "."))
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            out[dotted] = val
    return out


def diff_coverage(
    old_lock: dict[str, Any] | None, new_lock: dict[str, Any]
) -> list[tuple[str, object, object]]:
    """Numeric deltas between two locks' ``counts`` + ``coverage`` blocks.

    Returns sorted ``(field, old, new)`` for every changed numeric field. ``old_lock=None``
    (first build, no baseline) returns an empty list.
    """
    if old_lock is None:
        return []
    old = {**_flatten_numbers(old_lock.get("counts"), "counts."),
           **_flatten_numbers(old_lock.get("coverage"), "coverage.")}
    new = {**_flatten_numbers(new_lock.get("counts"), "counts."),
           **_flatten_numbers(new_lock.get("coverage"), "coverage.")}
    keys = sorted(set(old) | set(new))
    return [(k, old.get(k), new.get(k)) for k in keys if old.get(k) != new.get(k)]
