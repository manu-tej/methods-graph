"""Snapshot-fetch module: download real source files and record a versioned manifest.

This module provides two kinds of callables:

  PURE functions  (clock/network-free, deterministic, fully unit-tested):
    _transform_biocontainer   -- map live BioContainers API record to our shape
    bioconda_packages_from_nfcore -- scan cloned modules tree for dep names
    biotools_ids_from_nfcore  -- scan cloned modules tree for bio.tools ids
    write_manifest            -- write snapshot.json to dest_dir

  NETWORK wrappers (thin I/O, accept injectable callables for testing in principle,
                    but no live-network tests are included in the test suite):
    fetch_edam           -- download EDAM.tsv
    fetch_nfcore         -- shallow-clone nf-core/modules
    fetch_biocontainers  -- download per-tool JSON via BioContainers TRS API
    fetch_biotools       -- download per-tool JSON via bio.tools API

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
import logging
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

_log = logging.getLogger(__name__)

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


_BIOTOOLS_PREFIX = "biotools:"


def biotools_ids_from_nfcore(modules_root: Path) -> list[str]:
    """Scan a cloned nf-core modules tree and return sorted, de-duplicated bio.tools IDs.

    Each ``meta.yml`` found anywhere under *modules_root* is parsed.  For every
    ``tools[]`` entry, the ``identifier`` value is inspected; identifiers of the
    form ``biotools:<id>`` yield ``<id>`` as the result.  Identifiers without the
    ``biotools:`` prefix (including empty strings) are silently skipped.

    A tool entry is a single-key dict ``{toolname: {identifier: "biotools:salmon", ...}}``.

    Args:
        modules_root: Root of a cloned nf-core modules tree.

    Returns:
        Sorted, de-duplicated list of bio.tools IDs referenced across all modules.
    """
    ids: set[str] = set()
    for meta_path in modules_root.rglob("meta.yml"):
        try:
            meta = yaml.safe_load(meta_path.read_text()) or {}
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue
        for tool_entry in meta.get("tools") or []:
            if not isinstance(tool_entry, dict):
                continue
            # Each entry is {toolname: {identifier: ..., ...}}
            for _toolname, tool_info in tool_entry.items():
                if not isinstance(tool_info, dict):
                    continue
                identifier = tool_info.get("identifier") or ""
                if not isinstance(identifier, str):
                    continue
                if identifier.startswith(_BIOTOOLS_PREFIX):
                    bt_id = identifier[len(_BIOTOOLS_PREFIX):]
                    if bt_id:
                        ids.add(bt_id)
    return sorted(ids)


def write_manifest(
    dest_dir: Path,
    *,
    edam: dict[str, Any] | None,
    nfcore: dict[str, Any] | None,
    biocontainers: dict[str, Any] | None,
    biotools: dict[str, Any] | None = None,
    stato: dict[str, Any] | None = None,
    obi: dict[str, Any] | None = None,
    nfcore_pipelines: dict[str, Any] | None = None,
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
            "nfcore_pipelines": <nfcore pipelines manifest dict> | null,
            "biocontainers":    <biocontainers manifest dict> | null,
            "biotools":         <biotools manifest dict> | null,
            "stato":            <stato manifest dict> | null,
            "obi":              <obi manifest dict> | null
          }
        }

    Args:
        dest_dir:      Directory to write ``snapshot.json`` into (must exist).
        edam:          Return value of ``fetch_edam``, or ``None``.
        nfcore:        Return value of ``fetch_nfcore``, or ``None``.
        nfcore_pipelines: Mapping of pipeline name to ``fetch_nfcore_pipeline``
                       return value, or ``None``.
        biocontainers: Return value of ``fetch_biocontainers``, or ``None``.
        biotools:      Return value of ``fetch_biotools``, or ``None``.
        stato:         Return value of ``fetch_stato``, or ``None``.
        obi:           Return value of ``fetch_obi``, or ``None``.
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
            "nfcore_pipelines": nfcore_pipelines,
            "biocontainers": biocontainers,
            "biotools": biotools,
            "stato": stato,
            "obi": obi,
        },
    }
    out_path = dest_dir / "snapshot.json"
    out_path.write_text(json.dumps(manifest, indent=2))
    return out_path


# ---------------------------------------------------------------------------
# Network wrappers
# ---------------------------------------------------------------------------

_UA = "methods-graph/0.1 (+https://github.com/manu-tej/methods-graph)"


def _build_request(url: str, *, accept_json: bool = False) -> urllib.request.Request:
    """Build a :class:`urllib.request.Request` with an explicit User-Agent header.

    Using an explicit User-Agent avoids 403 responses from servers that block
    the default ``Python-urllib/3.x`` agent (e.g. api.biocontainers.pro).

    Args:
        url:         The URL to request.
        accept_json: When *True*, an ``Accept: application/json`` header is also
                     added.  Use for API endpoints that return JSON.

    Returns:
        A :class:`urllib.request.Request` ready to be passed to
        ``urllib.request.urlopen``.  The request is NOT opened here, so this
        helper can be unit-tested without any network I/O.
    """
    headers: dict[str, str] = {"User-Agent": _UA}
    if accept_json:
        headers["Accept"] = "application/json"
    return urllib.request.Request(url, headers=headers)


def _stdlib_http_get(url: str) -> tuple[bytes, dict[str, str]]:
    """Download *url* and return (body_bytes, response_headers)."""
    req = _build_request(url, accept_json=False)
    with urllib.request.urlopen(req) as resp:
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
    rows = len(body.decode("utf-8", "replace").splitlines())
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


_INCLUDE_CFG = re.compile(r"includeConfig\s+'([^']+)'")
_NF_VERSION = re.compile(r"nextflowVersion\s*=\s*'[^0-9]*(\d+\.\d+\.\d+)")


def _stub_missing_includes(clone_dir: Path) -> list[Path]:
    """Touch any ``includeConfig`` targets that don't exist on disk.

    Nextflow's strict config parser ERRORS (not warns) on an include of a missing
    file — e.g. an unused ``aws_batch`` profile's config that the pipeline ships
    conditionally.  Stubbing the missing targets lets ``-preview`` parse; the
    profile is not activated by ``-profile test`` so the empty stub is inert.
    Returns the stubs created (for logging)."""
    stubbed: list[Path] = []
    cfgs = list(clone_dir.glob("*.config")) + list((clone_dir / "conf").glob("*.config"))
    for cfg in cfgs:
        try:
            text = cfg.read_text(errors="ignore")
        except OSError:
            continue
        for rel in _INCLUDE_CFG.findall(text):
            target = cfg.parent / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("// stubbed by methods-graph fetch (missing optional include)\n")
                stubbed.append(target)
    return stubbed


def _generate_pipeline_dag(clone_dir: Path, launch_dir: Path, name: str,
                           runner: Callable[..., Any], nxf_ver: str | None = None) -> bool:
    """Cache ``<clone>/dag.mmd`` via ``nextflow -preview -with-dag`` (zero tasks).

    Robustness ladder for the real-world nf-core/Nextflow friction:
    stub missing includes, then try the default (v2) parser and fall back to the
    legacy (v1) parser for pre-v2 pipelines.  Pins ``NXF_VER`` when *nxf_ver* is
    given (a pipeline release often needs a matching Nextflow version).
    Best-effort: returns False (build falls back to I/O-overlap) if Nextflow is
    absent or every attempt fails.  A real DAG contains edges (``-->``); an
    empty header file from a failed run does not."""
    import os

    dag_path = clone_dir / "dag.mmd"
    launch_dir.mkdir(parents=True, exist_ok=True)
    _stub_missing_includes(clone_dir)
    base_env = dict(os.environ)
    if nxf_ver:
        base_env["NXF_VER"] = nxf_ver

    cmd = ["nextflow", "run", str(clone_dir), "-profile", "test",
           "--outdir", str(launch_dir / "out"), "-preview", "-with-dag", str(dag_path)]
    for parser in (None, "v1"):          # v2 (default) first, legacy fallback second
        env = dict(base_env)
        if parser:
            env["NXF_SYNTAX_PARSER"] = parser
        try:
            if dag_path.exists():
                dag_path.unlink()
            runner(cmd, check=True, cwd=str(launch_dir), env=env)
            if dag_path.exists() and "-->" in dag_path.read_text(errors="ignore"):
                return True
        except Exception as exc:   # noqa: BLE001 - nextflow optional; degrade gracefully
            _log.warning("nextflow preview (parser=%s) failed for %s: %s",
                         parser or "v2", name, exc)
    return False


def fetch_nfcore_pipeline(
    name: str,
    dest_dir: Path,
    *,
    revision: str,
    fetched_at: str,
    nxf_ver: str | None = None,
    with_dag: bool = True,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Shallow-clone nf-core/<name> at *revision* into <dest>/pipelines/<name>.

    Reuses fetch_nfcore's pattern (injectable runner, reuse-existing-clone,
    rev-parse HEAD) and returns a {repo, commit, revision, nxf_ver, path, dag,
    fetched_at} manifest.  When *nxf_ver* is given it is pinned (NXF_VER) for the
    DAG-preview run — a pipeline release often needs a matching Nextflow version."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    clone_dir = dest_dir / "pipelines" / name
    repo = f"https://github.com/nf-core/{name}.git"
    if not clone_dir.exists():
        runner(["git", "clone", "--depth", "1", "--branch", revision, repo,
                str(clone_dir)], check=True)
    result = runner(["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
                    capture_output=True, text=True, check=True)

    # Ground-truth wiring: Nextflow preview BUILDS the channel DAG and runs ZERO
    # tasks (no containers, no data).  Cached as <clone>/dag.mmd for the offline
    # build to parse (derivation="nextflow_dsl2").  Best-effort: stubs missing
    # includes + falls back to the legacy parser; if Nextflow is absent or every
    # attempt fails, the build falls back to Option-2 I/O-overlap.
    # `with_dag=False` (bulk catalog import): skip the Nextflow preview entirely —
    # running it across the whole nf-core catalog is infeasible, and the registry +
    # execution-spec layers don't need the DAG.
    dag_ok = (with_dag and
              _generate_pipeline_dag(clone_dir, dest_dir / "_preview" / name, name,
                                     runner, nxf_ver=nxf_ver))
    return {
        "repo": repo,
        "commit": result.stdout.strip(),
        "revision": revision,
        "nxf_ver": nxf_ver,
        "path": str(clone_dir),
        "dag": "dag.mmd" if dag_ok else None,
        "fetched_at": fetched_at,
    }


def _stdlib_http_get_json(url: str) -> Any:
    """GET *url* and parse the response body as JSON."""
    req = _build_request(url, accept_json=True)
    with urllib.request.urlopen(req) as resp:
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
    failed: list[str] = []
    for name in sorted(names):
        url = f"{api_base}?name={name}&limit=1"
        try:
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
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            _log.warning("BioContainers fetch failed for %r: %s", name, exc)
            failed.append(name)
        except Exception as exc:  # JSON parse errors, unexpected API shapes, etc.
            _log.warning("BioContainers unexpected error for %r: %s", name, exc)
            failed.append(name)
    return {
        "api": api_base,
        "fetched_at": fetched_at,
        "tools": tools_versions,
        "failed": failed,
        "n_failed": len(failed),
    }


def fetch_biotools(
    ids: list[str],
    dest_dir: Path,
    *,
    fetched_at: str,
    api_base: str = "https://bio.tools/api/tool",
    http_get_json: Callable[[str], Any] = _stdlib_http_get_json,
) -> dict[str, Any]:
    """Fetch bio.tools API records for *ids* and return a manifest entry.

    For each id in *ids* (iterated in sorted order), the bio.tools API is called::

        GET <api_base>/<id>/?format=json

    The returned JSON object (a single record, not a list) is written as-is to
    ``<dest_dir>/<id>.json``.  Per-tool failures are logged as warnings and
    recorded in the manifest; they never abort the overall fetch.

    Args:
        ids:           Iterable of bio.tools IDs to fetch.
        dest_dir:      Destination directory for the per-tool JSON files.
        fetched_at:    ISO-8601 UTC timestamp injected by the caller.
        api_base:      bio.tools API base URL.
        http_get_json: Injectable JSON fetcher (uses ``_build_request`` internally
                       for the User-Agent header in the real implementation).

    Returns:
        Manifest entry dict::
            {
              "api":       str,
              "fetched_at": str,
              "n_tools":   int,   # number of files successfully written
              "failed":    list[str],
              "n_failed":  int
            }
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    n_written = 0
    for bt_id in sorted(ids):
        url = f"{api_base}/{bt_id}/?format=json"
        try:
            record = http_get_json(url)
            out_path = dest_dir / f"{bt_id}.json"
            out_path.write_text(json.dumps(record, indent=2))
            n_written += 1
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            _log.warning("bio.tools fetch failed for %r: %s", bt_id, exc)
            failed.append(bt_id)
        except Exception as exc:  # JSON parse errors, unexpected API shapes, etc.
            _log.warning("bio.tools unexpected error for %r: %s", bt_id, exc)
            failed.append(bt_id)
    return {
        "api": api_base,
        "fetched_at": fetched_at,
        "n_tools": n_written,
        "failed": failed,
        "n_failed": len(failed),
    }


# ---------------------------------------------------------------------------
# OWL ontology fetchers (STATO + OBI)
# ---------------------------------------------------------------------------

_VERSION_IRI_RE = re.compile(
    r'versionIRI\s+rdf:resource\s*=\s*"([^"]+)"',
    re.DOTALL,
)


def _extract_version_iri(body: bytes) -> str:
    """Extract the versionIRI value from OWL/RDF-XML bytes, or return ''."""
    text = body.decode("utf-8", "replace")
    m = _VERSION_IRI_RE.search(text)
    return m.group(1) if m else ""


def fetch_stato(
    dest_dir: Path,
    *,
    url: str = "http://purl.obolibrary.org/obo/stato.owl",
    fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] = _stdlib_http_get,
) -> dict[str, Any]:
    """Download the STATO OWL file and return a manifest entry.

    Args:
        dest_dir:   Destination directory; the file is written as
                    ``<dest_dir>/stato.owl``.
        url:        URL to download from (default: the official STATO OWL).
        fetched_at: ISO-8601 UTC timestamp injected by the caller.
        http_get:   Injectable HTTP getter for testing.  Signature:
                    ``(url: str) -> (bytes, dict[str, str])``.

    Returns:
        Manifest entry dict::
            {
              "url":        str,
              "sha256":     str,
              "version":    str,  # versionIRI value or ""
              "fetched_at": str
            }
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, _headers = http_get(url)
    dest_path = dest_dir / "stato.owl"
    dest_path.write_bytes(body)
    sha256 = hashlib.sha256(body).hexdigest()
    version = _extract_version_iri(body)
    return {
        "url": url,
        "sha256": sha256,
        "version": version,
        "fetched_at": fetched_at,
    }


def fetch_obi(
    dest_dir: Path,
    *,
    url: str = "http://purl.obolibrary.org/obo/obi.owl",
    fetched_at: str,
    http_get: Callable[[str], tuple[bytes, dict[str, str]]] = _stdlib_http_get,
) -> dict[str, Any]:
    """Download the OBI OWL file and return a manifest entry.

    Args:
        dest_dir:   Destination directory; the file is written as
                    ``<dest_dir>/obi.owl``.
        url:        URL to download from (default: the official OBI OWL).
        fetched_at: ISO-8601 UTC timestamp injected by the caller.
        http_get:   Injectable HTTP getter for testing.  Signature:
                    ``(url: str) -> (bytes, dict[str, str])``.

    Returns:
        Manifest entry dict::
            {
              "url":        str,
              "sha256":     str,
              "version":    str,  # versionIRI value or ""
              "fetched_at": str
            }
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    body, _headers = http_get(url)
    dest_path = dest_dir / "obi.owl"
    dest_path.write_bytes(body)
    sha256 = hashlib.sha256(body).hexdigest()
    version = _extract_version_iri(body)
    return {
        "url": url,
        "sha256": sha256,
        "version": version,
        "fetched_at": fetched_at,
    }
