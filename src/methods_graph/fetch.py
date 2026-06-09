"""Snapshot-fetch module: download real source files and record a versioned manifest.

This module provides two kinds of callables:

  PURE functions  (clock/network-free, deterministic, fully unit-tested):
    _transform_biocontainer   -- map live BioContainers API record to our shape
    bioconda_packages_from_nfcore -- scan cloned modules tree for dep names
    write_manifest            -- write snapshot.json to dest_dir

  NETWORK wrappers (thin I/O, accept injectable callables for testing in principle,
                    but no live-network tests are included in the test suite):
    fetch_edam           -- download EDAM.tsv
    fetch_nfcore         -- shallow-clone nf-core/modules
    fetch_biocontainers  -- download per-tool JSON via BioContainers TRS API

Synthesised image tags
----------------------
``_transform_biocontainer`` synthesises a canonical image name of the form::

    quay.io/biocontainers/<name>:<meta_version>

The real upstream image tag appends a build-hash suffix
(e.g. ``--h7e5ed60_0``).  Omitting that suffix is a documented Phase-2
refinement; the canonical tag (without build hash) is sufficient for
provenance tracking and version comparison.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

# Reuse the same dep-parsing regex as the nf-core connector.
_DEP_RE = re.compile(r"(?:(?P<chan>[\w-]+)::)?(?P<pkg>[\w.-]+)=(?P<ver>[\w.+-]+)")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _transform_biocontainer(api_record: dict[str, Any]) -> dict[str, Any]:
    """Map a live BioContainers TRS API record to the shape expected by ``parse_biocontainer``.

    The TRS API returns records whose ``versions`` list items have no ``images``
    field.  This function synthesises one canonical image entry per version::

        image_name = "quay.io/biocontainers/<name>:<meta_version>"

    Versions that lack a ``meta_version`` value are silently skipped.

    Args:
        api_record: A single dict from the TRS API response list, e.g.::
            {
              "name": "salmon",
              "versions": [
                {"id": "salmon-1.10.0", "meta_version": "1.10.0", ...},
                ...
              ],
              "description": "...",
              "tool_url": "..."
            }

    Returns:
        A dict shaped for ``parse_biocontainer``::
            {
              "name": "salmon",
              "versions": [
                {
                  "meta_version": "1.10.0",
                  "images": [
                    {"image_name": "quay.io/biocontainers/salmon:1.10.0",
                     "registry": "quay.io"}
                  ]
                },
                ...
              ]
            }
    """
    name: str = api_record["name"]
    out_versions: list[dict[str, Any]] = []
    for ver in api_record.get("versions", []):
        meta_version = ver.get("meta_version") or ""
        if not meta_version:
            continue
        image_name = f"quay.io/biocontainers/{name}:{meta_version}"
        out_versions.append(
            {
                "meta_version": meta_version,
                "images": [
                    {"image_name": image_name, "registry": "quay.io"}
                ],
            }
        )
    return {"name": name, "versions": out_versions}


def bioconda_packages_from_nfcore(modules_root: Path) -> list[str]:
    """Scan a cloned nf-core modules tree and return sorted, de-duplicated bioconda package names.

    Each ``environment.yml`` found anywhere under *modules_root* is parsed; any
    dependency whose channel is ``bioconda`` (or has no explicit channel) is
    collected.  The result is a sorted, de-duplicated list of package names,
    suitable for targeting a ``fetch_biocontainers`` call.

    Args:
        modules_root: Root of a cloned nf-core modules tree (e.g. the
            ``modules/nf-core`` directory returned by ``fetch_nfcore``).

    Returns:
        Sorted list of bioconda package names referenced across all modules.
    """
    packages: set[str] = set()
    for env_path in modules_root.rglob("environment.yml"):
        try:
            env = yaml.safe_load(env_path.read_text()) or {}
        except Exception:
            continue
        if not isinstance(env, dict):
            continue
        for dep in env.get("dependencies", []):
            if not isinstance(dep, str):
                continue
            m = _DEP_RE.match(dep)
            if m and (m.group("chan") in (None, "bioconda")):
                packages.add(m.group("pkg"))
    return sorted(packages)


def write_manifest(
    dest_dir: Path,
    *,
    edam: dict[str, Any] | None,
    nfcore: dict[str, Any] | None,
    biocontainers: dict[str, Any] | None,
    created_at: str,
) -> Path:
    """Write a ``snapshot.json`` manifest to *dest_dir*.

    The manifest records provenance for each fetched source so that upstream
    changes can be detected and only changed sources re-fetched.

    Schema::

        {
          "created_at": "<ISO-8601 UTC timestamp>",
          "sources": {
            "edam":             <edam manifest dict>  | null,
            "nfcore_modules":   <nfcore manifest dict> | null,
            "biocontainers":    <biocontainers manifest dict> | null
          }
        }

    Args:
        dest_dir:      Directory to write ``snapshot.json`` into (must exist).
        edam:          Return value of ``fetch_edam``, or ``None``.
        nfcore:        Return value of ``fetch_nfcore``, or ``None``.
        biocontainers: Return value of ``fetch_biocontainers``, or ``None``.
        created_at:    ISO-8601 timestamp string (injected by caller; clock
                       is never read inside this function).

    Returns:
        Path to the written ``snapshot.json``.
    """
    manifest = {
        "created_at": created_at,
        "sources": {
            "edam": edam,
            "nfcore_modules": nfcore,
            "biocontainers": biocontainers,
        },
    }
    out_path = dest_dir / "snapshot.json"
    out_path.write_text(json.dumps(manifest, indent=2))
    return out_path


# ---------------------------------------------------------------------------
# Network wrappers
# ---------------------------------------------------------------------------


def _stdlib_http_get(url: str) -> tuple[bytes, dict[str, str]]:
    """Download *url* and return (body_bytes, response_headers)."""
    with urllib.request.urlopen(url) as resp:
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.headers.items()}
    return body, headers


def fetch_edam(
    dest_dir: Path,
    *,
    url: str = "https://edamontology.org/EDAM.tsv",
    fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] = _stdlib_http_get,
) -> dict[str, Any]:
    """Download the EDAM ontology TSV and return a manifest entry.

    Args:
        dest_dir:   Destination directory; the file is written as
                    ``<dest_dir>/EDAM.tsv``.
        url:        URL to download from (default: the official EDAM TSV).
        fetched_at: ISO-8601 UTC timestamp injected by the caller (clock is
                    never read inside this function).
        http_get:   Injectable HTTP getter for testing.  Signature:
                    ``(url: str) -> (bytes, dict[str, str])`` where the second
                    element is a dict of lowercased response headers.

    Returns:
        Manifest entry dict::
            {
              "url":           str,
              "sha256":        str,   # hex digest of the downloaded bytes
              "last_modified": str,   # HTTP Last-Modified header or ""
              "fetched_at":    str,
              "rows":          int    # number of lines in the file
            }
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, headers = http_get(url)
    dest_path = dest_dir / "EDAM.tsv"
    dest_path.write_bytes(body)
    sha256 = hashlib.sha256(body).hexdigest()
    last_modified = headers.get("last-modified", "")
    rows = body.decode("utf-8", errors="replace").count("\n")
    return {
        "url": url,
        "sha256": sha256,
        "last_modified": last_modified,
        "fetched_at": fetched_at,
        "rows": rows,
    }


def fetch_nfcore(
    dest_dir: Path,
    *,
    repo: str = "https://github.com/nf-core/modules.git",
    fetched_at: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Shallow-clone nf-core/modules and return a manifest entry.

    If ``<dest_dir>/modules`` already exists the clone step is skipped (the
    existing clone is re-used as-is).  The commit SHA is always re-read from
    the existing clone so the manifest reflects the actual on-disk state.

    Args:
        dest_dir:   Destination directory.  The repo is cloned into
                    ``<dest_dir>/modules``.
        repo:       Git URL to clone (default: nf-core/modules on GitHub).
        fetched_at: ISO-8601 UTC timestamp injected by the caller.
        runner:     Injectable subprocess runner (default: ``subprocess.run``).
                    Accepts the same positional/keyword arguments.

    Returns:
        Manifest entry dict::
            {
              "repo":         str,
              "commit":       str,   # HEAD commit SHA of the cloned repo
              "modules_path": str,   # absolute path to <clone>/modules/nf-core
              "fetched_at":   str
            }
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    clone_dir = dest_dir / "modules"
    if not clone_dir.exists():
        runner(
            ["git", "clone", "--depth", "1", repo, str(clone_dir)],
            check=True,
        )
    result = runner(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit_sha = result.stdout.strip()
    modules_path = clone_dir / "modules" / "nf-core"
    return {
        "repo": repo,
        "commit": commit_sha,
        "modules_path": str(modules_path),
        "fetched_at": fetched_at,
    }


def _stdlib_http_get_json(url: str) -> Any:
    """GET *url* and parse the response body as JSON."""
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def fetch_biocontainers(
    names: list[str],
    dest_dir: Path,
    *,
    fetched_at: str,
    api_base: str = "https://api.biocontainers.pro/ga4gh/trs/v2/tools",
    http_get_json: Callable[[str], Any] = _stdlib_http_get_json,
) -> dict[str, Any]:
    """Fetch BioContainers TRS records for *names* and return a manifest entry.

    For each name in *names* (iterated in sorted order), the TRS API is called::

        GET <api_base>?name=<name>&limit=1

    The first record in the response list (if any) is transformed via
    ``_transform_biocontainer`` and written to ``<dest_dir>/<name>.json``.

    Args:
        names:        Iterable of bioconda package names to fetch.
        dest_dir:     Destination directory for the per-tool JSON files.
        fetched_at:   ISO-8601 UTC timestamp injected by the caller.
        api_base:     BioContainers TRS API base URL.
        http_get_json: Injectable JSON fetcher.

    Returns:
        Manifest entry dict::
            {
              "api":        str,
              "fetched_at": str,
              "tools": {
                "<name>": ["<meta_version>", ...],
                ...
              }
            }
        Tools that returned no records are omitted from ``"tools"``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    tools_versions: dict[str, list[str]] = {}
    for name in sorted(names):
        url = f"{api_base}?name={name}&limit=1"
        records = http_get_json(url)
        if not records:
            continue
        transformed = _transform_biocontainer(records[0])
        meta_versions = [v["meta_version"] for v in transformed.get("versions", [])]
        if not meta_versions:
            continue
        out_path = dest_dir / f"{name}.json"
        out_path.write_text(json.dumps(transformed, indent=2))
        tools_versions[name] = meta_versions
    return {
        "api": api_base,
        "fetched_at": fetched_at,
        "tools": tools_versions,
    }
