"""Declarative, reproducible methods-graph ingestion.

A single manifest pins every input — the shared source snapshots AND the pipelines
(``name`` @ ``revision`` + NXF version) — so a build can never *silently* drop a
source.  ``mg ingest`` fetches the declared pipelines, resolves every declared
shared source (failing loudly if any is missing), builds, gates on the audit, and
writes a lock recording exactly what went in.

Shared sources use the standard ``mg fetch`` layout by default; a per-source path
override is allowed.  Method nodes + DAG wiring come from each pipeline's *own*
vendored modules (version-matched), so ``nfcore_modules`` is not a shared source.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Shared source keys and their default path under the snapshot dir (the layout
# `mg fetch` writes).  A manifest may override any path; a key it does not list
# is simply not loaded.
_DEFAULT_LAYOUT: dict[str, str] = {
    "edam": "EDAM.tsv",
    "biocontainers": "biocontainers",
    "biotools": "biotools",
    "stato": "stato.owl",
    "obi": "obi.owl",
}


@dataclass(frozen=True)
class PipelineSpec:
    """One nf-core pipeline to ingest, pinned to a revision (and optional NXF version)."""
    name: str
    revision: str
    nxf_ver: str | None = None


@dataclass(frozen=True)
class IngestSpec:
    """A parsed ingestion manifest."""
    base_dir: Path                  # the manifest's directory (resolves relative paths)
    snapshot_dir: str               # shared-source snapshot dir (rel to base_dir, or absolute)
    sources: dict[str, str | None]  # declared shared sources: key -> path override (None = default)
    pipelines: tuple[PipelineSpec, ...]


def load_manifest(path: Path | str) -> IngestSpec:
    """Parse and validate an ingestion manifest.

    Raises ``ValueError`` on an unknown source key or a pipeline missing
    ``name``/``revision`` — a malformed manifest fails loudly, never half-loads.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"ingest: {path} must be a mapping")

    snapshot_dir = str(raw.get("snapshot_dir", "") or "").strip()

    raw_sources = raw.get("sources") or {}
    if not isinstance(raw_sources, dict):
        raise ValueError("ingest: 'sources' must be a mapping of source-key -> path|null")
    sources: dict[str, str | None] = {}
    for key, val in raw_sources.items():
        if key not in _DEFAULT_LAYOUT:
            raise ValueError(
                f"ingest: unknown source key {key!r}; allowed: {sorted(_DEFAULT_LAYOUT)}"
            )
        sources[key] = (str(val).strip() if val else None)

    raw_pipes = raw.get("pipelines") or []
    if not isinstance(raw_pipes, list):
        raise ValueError("ingest: 'pipelines' must be a list")
    pipelines: list[PipelineSpec] = []
    for i, p in enumerate(raw_pipes):
        if not isinstance(p, dict):
            raise ValueError(f"ingest: pipeline #{i} must be a mapping")
        name = str(p.get("name", "") or "").strip()
        revision = str(p.get("revision", "") or "").strip()
        if not name:
            raise ValueError(f"ingest: pipeline #{i} is missing 'name'")
        if not revision:
            raise ValueError(f"ingest: pipeline {name!r} is missing 'revision' (pin it)")
        nxf = p.get("nxf_ver")
        pipelines.append(PipelineSpec(name, revision, str(nxf).strip() if nxf else None))

    return IngestSpec(
        base_dir=path.parent,
        snapshot_dir=snapshot_dir,
        sources=sources,
        pipelines=tuple(pipelines),
    )


def _snapshot_root(spec: IngestSpec) -> Path:
    p = Path(spec.snapshot_dir)
    return p if p.is_absolute() else spec.base_dir / p


def resolve_sources(spec: IngestSpec) -> dict[str, Path]:
    """Resolve every declared shared source to an absolute path.

    Each declared source must exist on disk.  If ANY declared source is missing,
    raise ``FileNotFoundError`` listing *all* of them — so the build never proceeds
    having silently dropped a layer.
    """
    root = _snapshot_root(spec)
    resolved: dict[str, Path] = {}
    missing: list[str] = []
    for key, override in spec.sources.items():
        rel = override or _DEFAULT_LAYOUT[key]
        p = (root / rel)
        if p.exists():
            resolved[key] = p
        else:
            missing.append(f"{key}: {p}")
    if missing:
        raise FileNotFoundError(
            "ingest: declared source(s) missing (a build must not silently drop a "
            "layer):\n  " + "\n  ".join(missing)
        )
    return resolved
