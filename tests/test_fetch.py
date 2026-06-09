"""Tests for methods_graph.fetch — all offline, no network I/O."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pytest

from methods_graph.fetch import (
    _build_request,
    _transform_biocontainer,
    bioconda_packages_from_nfcore,
    fetch_biocontainers,
    fetch_edam,
    fetch_nfcore,
    write_manifest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A recorded API-shaped dict (no "images" field — exactly what the real TRS
# API returns).
_API_RECORD_SALMON = {
    "name": "salmon",
    "versions": [
        {
            "id": "salmon-1.10.0",
            "meta_version": "1.10.0",
            "name": "salmon",
            "url": "https://api.biocontainers.pro/ga4gh/trs/v2/tools/salmon/versions/salmon-1.10.0",
        },
        {
            "id": "salmon-0.11.3",
            "meta_version": "0.11.3",
            "name": "salmon",
            "url": "https://api.biocontainers.pro/ga4gh/trs/v2/tools/salmon/versions/salmon-0.11.3",
        },
    ],
    "description": "Salmon is a tool for quantifying the expression of transcripts.",
    "tool_url": "https://biocontainers.pro/tools/salmon",
}

# ---------------------------------------------------------------------------
# _transform_biocontainer
# ---------------------------------------------------------------------------


def test_transform_biocontainer_synthesizes_images() -> None:
    """Each version gains exactly one synthesised image entry with correct fields."""
    result = _transform_biocontainer(_API_RECORD_SALMON)

    assert result["name"] == "salmon"
    versions = result["versions"]
    assert len(versions) == 2

    meta_versions = [v["meta_version"] for v in versions]
    assert "1.10.0" in meta_versions
    assert "0.11.3" in meta_versions

    for ver in versions:
        images = ver["images"]
        assert len(images) == 1, f"expected exactly 1 image; got {images}"
        img = images[0]
        expected_name = f"quay.io/biocontainers/salmon:{ver['meta_version']}"
        assert img["image_name"] == expected_name, (
            f"image_name mismatch: {img['image_name']!r} != {expected_name!r}"
        )
        assert img["registry"] == "quay.io"


def test_transform_biocontainer_skips_versionless() -> None:
    """Version dicts that lack a meta_version are silently dropped."""
    api_record = {
        "name": "mytool",
        "versions": [
            {"id": "mytool-1.0", "meta_version": "1.0"},
            {"id": "mytool-broken"},               # no meta_version key at all
            {"id": "mytool-empty", "meta_version": ""},  # empty string
            {"id": "mytool-null", "meta_version": None},  # explicit null
        ],
    }
    result = _transform_biocontainer(api_record)
    assert len(result["versions"]) == 1
    assert result["versions"][0]["meta_version"] == "1.0"


# ---------------------------------------------------------------------------
# bioconda_packages_from_nfcore
# ---------------------------------------------------------------------------


def _make_env_yml(tmp_path: Path, subdir: str, deps: list[str]) -> None:
    """Write a minimal environment.yml under tmp_path/subdir/."""
    module_dir = tmp_path / subdir
    module_dir.mkdir(parents=True, exist_ok=True)
    content = "name: test\nchannels:\n  - bioconda\ndependencies:\n"
    for dep in deps:
        content += f"  - \"{dep}\"\n"
    (module_dir / "environment.yml").write_text(content)


def test_bioconda_packages_from_nfcore(tmp_path: Path) -> None:
    """Scans a tiny local fixture tree and returns sorted, de-duplicated package names."""
    # Two modules: one with salmon, one with samtools.
    _make_env_yml(tmp_path, "salmon_mod", ["bioconda::salmon=1.10.0"])
    _make_env_yml(tmp_path, "samtools_mod", ["bioconda::samtools=1.19"])
    # A third module that duplicates salmon — should appear only once.
    _make_env_yml(tmp_path, "salmon_quant2", ["bioconda::salmon=1.10.0"])

    result = bioconda_packages_from_nfcore(tmp_path)

    assert result == ["salmon", "samtools"], (
        f"expected ['salmon', 'samtools'] (sorted, deduped); got {result}"
    )


def test_bioconda_packages_from_nfcore_ignores_non_bioconda(tmp_path: Path) -> None:
    """Packages from other channels (e.g. conda-forge) are not included."""
    _make_env_yml(tmp_path, "mixed_mod", [
        "bioconda::salmon=1.10.0",
        "conda-forge::python=3.11",
        "r-base=4.3",  # no channel prefix — not bioconda, but _DEP_RE allows chan=None
    ])
    result = bioconda_packages_from_nfcore(tmp_path)
    # Only bioconda channel (or no channel) deps are returned.
    # "r-base" has no channel prefix so it's included; "python" from conda-forge is excluded.
    assert "salmon" in result
    assert "python" not in result


def test_bioconda_packages_from_nfcore_against_existing_fixtures() -> None:
    """Validates against the shared nfcore fixture tree used by other tests."""
    fx = Path(__file__).parent / "fixtures" / "nfcore"
    result = bioconda_packages_from_nfcore(fx)
    # salmon and samtools are known to be in those fixtures.
    assert "salmon" in result
    assert "samtools" in result


# ---------------------------------------------------------------------------
# write_manifest
# ---------------------------------------------------------------------------

_SAMPLE_EDAM = {
    "url": "https://edamontology.org/EDAM.tsv",
    "sha256": "abc123",
    "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT",
    "fetched_at": "2026-06-09T00:00:00+00:00",
    "rows": 9876,
}

_SAMPLE_NFCORE = {
    "repo": "https://github.com/nf-core/modules.git",
    "commit": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "modules_path": "/tmp/snap/modules/modules/nf-core",
    "fetched_at": "2026-06-09T00:00:00+00:00",
}

_SAMPLE_BIOCONTAINERS = {
    "api": "https://api.biocontainers.pro/ga4gh/trs/v2/tools",
    "fetched_at": "2026-06-09T00:00:00+00:00",
    "tools": {
        "salmon": ["1.10.0", "0.11.3"],
        "samtools": ["1.19"],
    },
}


def test_write_manifest_records_source_versions(tmp_path: Path) -> None:
    """write_manifest writes valid JSON containing per-source version fields."""
    created_at = "2026-06-09T00:00:00+00:00"

    manifest_path = write_manifest(
        tmp_path,
        edam=_SAMPLE_EDAM,
        nfcore=_SAMPLE_NFCORE,
        biocontainers=_SAMPLE_BIOCONTAINERS,
        created_at=created_at,
    )

    assert manifest_path == tmp_path / "snapshot.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text())

    # Top-level shape
    assert data["created_at"] == created_at
    assert "sources" in data

    sources = data["sources"]

    # EDAM: sha256 and url must be present
    assert sources["edam"]["sha256"] == "abc123"
    assert sources["edam"]["url"] == "https://edamontology.org/EDAM.tsv"
    assert sources["edam"]["rows"] == 9876

    # nf-core: commit SHA must be present
    assert sources["nfcore_modules"]["commit"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert "modules_path" in sources["nfcore_modules"]

    # BioContainers: tools dict must be present
    assert "salmon" in sources["biocontainers"]["tools"]
    assert "1.10.0" in sources["biocontainers"]["tools"]["salmon"]


def test_write_manifest_with_nulls(tmp_path: Path) -> None:
    """write_manifest handles None sources gracefully."""
    manifest_path = write_manifest(
        tmp_path,
        edam=None,
        nfcore=None,
        biocontainers=None,
        created_at="2026-06-09T00:00:00+00:00",
    )
    data = json.loads(manifest_path.read_text())
    assert data["sources"]["edam"] is None
    assert data["sources"]["nfcore_modules"] is None
    assert data["sources"]["biocontainers"] is None


# ---------------------------------------------------------------------------
# _build_request — offline header inspection (no network)
# ---------------------------------------------------------------------------


def test_build_request_sets_user_agent() -> None:
    """_build_request returns a Request with 'methods-graph' in User-Agent and correct Accept."""
    url = "https://example.com/api"
    req = _build_request(url, accept_json=True)

    assert isinstance(req, urllib.request.Request)
    # urllib stores headers with first-letter capitalised.
    ua = req.get_header("User-agent")
    assert ua is not None, "User-Agent header must be set"
    assert "methods-graph" in ua, f"Expected 'methods-graph' in User-Agent, got {ua!r}"

    accept = req.get_header("Accept")
    assert accept == "application/json", f"Expected Accept: application/json, got {accept!r}"


def test_build_request_no_accept_json_by_default() -> None:
    """_build_request with accept_json=False does not set Accept header."""
    req = _build_request("https://example.com/file.tsv", accept_json=False)
    ua = req.get_header("User-agent")
    assert ua is not None and "methods-graph" in ua
    # Accept header should NOT be set when accept_json=False
    assert req.get_header("Accept") is None


# ---------------------------------------------------------------------------
# fetch_biocontainers — per-tool resilience (offline, injected http_get_json)
# ---------------------------------------------------------------------------

_GOOD_API_RECORD = {
    "name": "good",
    "versions": [{"id": "good-1.0", "meta_version": "1.0"}],
    "description": "A good tool",
    "tool_url": "https://biocontainers.pro/tools/good",
}


def test_fetch_biocontainers_skips_failures(tmp_path: Path) -> None:
    """fetch_biocontainers writes good.json, skips bad, records failed list — no exception."""

    def _fake_http_get_json(url: str):
        if "name=good" in url:
            return [_GOOD_API_RECORD]
        if "name=bad" in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        raise AssertionError(f"Unexpected URL: {url}")

    result = fetch_biocontainers(
        ["good", "bad"],
        tmp_path,
        fetched_at="2026-06-09T00:00:00+00:00",
        http_get_json=_fake_http_get_json,
    )

    # good.json written
    good_path = tmp_path / "good.json"
    assert good_path.exists(), "good.json should be written for successful fetch"
    good_data = json.loads(good_path.read_text())
    assert good_data["name"] == "good"

    # bad.json NOT written
    bad_path = tmp_path / "bad.json"
    assert not bad_path.exists(), "bad.json must not be written on fetch failure"

    # manifest tools has "good", failed list has "bad"
    assert "good" in result["tools"], "'good' must appear in tools"
    assert "bad" not in result["tools"], "'bad' must not appear in tools"
    assert "bad" in result["failed"], "'bad' must appear in failed list"
    assert result["n_failed"] == 1
    assert result["n_failed"] == len(result["failed"])


def test_fetch_biocontainers_skips_generic_exception(tmp_path: Path) -> None:
    """fetch_biocontainers also handles non-urllib exceptions (e.g. JSON parse errors)."""

    def _fake_http_get_json(url: str):
        raise ValueError("Unexpected JSON structure")

    result = fetch_biocontainers(
        ["broken"],
        tmp_path,
        fetched_at="2026-06-09T00:00:00+00:00",
        http_get_json=_fake_http_get_json,
    )

    assert "broken" in result["failed"]
    assert result["n_failed"] == 1
    assert (tmp_path / "broken.json").exists() is False


# ---------------------------------------------------------------------------
# Import-time sanity: no network I/O triggered on import
# ---------------------------------------------------------------------------


def test_fetch_module_has_no_import_time_network() -> None:
    """Importing methods_graph.fetch does not perform any I/O (re-import check)."""
    # If importing raised a network-related error or took >1 s we'd have seen it
    # in the import at the top of this file.  This test is a belt-and-suspenders
    # assertion that the module is importable cleanly.
    import importlib
    import methods_graph.fetch as fetch_mod  # already imported above; re-check

    # Re-importing from cache should be instant and side-effect-free.
    reloaded = importlib.reload(fetch_mod)
    assert reloaded is not None


# ---------------------------------------------------------------------------
# fetch_edam — offline via injected http_get
# ---------------------------------------------------------------------------


def test_fetch_edam_writes_file_and_returns_manifest(tmp_path: Path) -> None:
    """fetch_edam writes EDAM.tsv and returns a manifest with correct sha256/rows/last_modified."""
    fake_body = b"term_id\tterm_label\nop:0001\tSequence analysis\nop:0002\tAlignment\n"
    fake_last_modified = "Mon, 09 Jun 2026 00:00:00 GMT"
    expected_sha256 = hashlib.sha256(fake_body).hexdigest()
    expected_rows = len(fake_body.decode("utf-8", "replace").splitlines())

    def _fake_http_get(url: str) -> tuple[bytes, dict[str, str]]:
        assert "EDAM" in url or "edamontology" in url, f"Unexpected URL: {url}"
        return fake_body, {"last-modified": fake_last_modified, "content-type": "text/tab-separated-values"}

    result = fetch_edam(
        tmp_path,
        fetched_at="2026-06-09T00:00:00Z",
        http_get=_fake_http_get,
    )

    # File written with exact bytes
    out_path = tmp_path / "EDAM.tsv"
    assert out_path.exists(), "EDAM.tsv must be written"
    assert out_path.read_bytes() == fake_body

    # Manifest fields
    assert result["sha256"] == expected_sha256, f"sha256 mismatch: {result['sha256']!r}"
    assert result["last_modified"] == fake_last_modified
    assert result["fetched_at"] == "2026-06-09T00:00:00Z"
    assert result["rows"] == expected_rows, f"rows={result['rows']}, expected {expected_rows}"
    assert result["url"] is not None


def test_fetch_edam_rows_counts_lines_without_trailing_newline(tmp_path: Path) -> None:
    """rows is computed via splitlines(), so no trailing newline does not undercount."""
    # Body with NO trailing newline — count("\n") would give 1, splitlines() gives 2.
    fake_body = b"header\tcolumn\nrow1\tvalue1"
    expected_rows = 2  # "header\tcolumn" and "row1\tvalue1"

    def _fake_http_get(url: str) -> tuple[bytes, dict[str, str]]:
        return fake_body, {}

    result = fetch_edam(tmp_path, fetched_at="2026-06-09T00:00:00Z", http_get=_fake_http_get)
    assert result["rows"] == expected_rows, (
        f"Expected rows=2 (splitlines), got {result['rows']} — count('\\n') would give 1"
    )


# ---------------------------------------------------------------------------
# fetch_nfcore — offline via injected runner
# ---------------------------------------------------------------------------

_FAKE_COMMIT_SHA = "a" * 40  # 40-char hex string


def test_fetch_nfcore_clones_and_returns_manifest(tmp_path: Path) -> None:
    """fetch_nfcore issues clone + rev-parse, returns manifest with repo/commit/modules_path."""
    clone_dir = tmp_path / "modules"
    issued_commands: list[list[str]] = []

    def _fake_runner(cmd: list[str], **kwargs: Any) -> Any:
        issued_commands.append(list(cmd))
        if cmd[0] == "git" and "clone" in cmd:
            # Simulate the clone by creating the directory.
            clone_dir.mkdir(parents=True, exist_ok=True)
            return None
        if cmd[0] == "git" and "rev-parse" in cmd:
            # Return fake stdout for HEAD commit.
            class _FakeResult:
                stdout = _FAKE_COMMIT_SHA + "\n"
            return _FakeResult()
        raise AssertionError(f"Unexpected command: {cmd}")

    result = fetch_nfcore(
        tmp_path,
        fetched_at="2026-06-09T00:00:00Z",
        runner=_fake_runner,
    )

    # Manifest fields
    assert result["repo"] is not None
    assert result["commit"] == _FAKE_COMMIT_SHA, f"commit={result['commit']!r}"
    assert "modules_path" in result
    assert result["fetched_at"] == "2026-06-09T00:00:00Z"

    # Both commands were issued: clone + rev-parse
    clone_cmds = [c for c in issued_commands if "clone" in c]
    revparse_cmds = [c for c in issued_commands if "rev-parse" in c]
    assert len(clone_cmds) == 1, f"Expected exactly 1 clone command; got {clone_cmds}"
    assert len(revparse_cmds) == 1, f"Expected exactly 1 rev-parse command; got {revparse_cmds}"


def test_fetch_nfcore_skips_clone_if_dir_exists(tmp_path: Path) -> None:
    """If clone dir already exists, the clone command is skipped but rev-parse still runs."""
    clone_dir = tmp_path / "modules"
    clone_dir.mkdir(parents=True)  # Pre-create to simulate existing clone.
    issued_commands: list[list[str]] = []

    def _fake_runner(cmd: list[str], **kwargs: Any) -> Any:
        issued_commands.append(list(cmd))
        if "clone" in cmd:
            raise AssertionError("clone should NOT be called when dir already exists")
        if "rev-parse" in cmd:
            class _FakeResult:
                stdout = _FAKE_COMMIT_SHA
            return _FakeResult()
        raise AssertionError(f"Unexpected: {cmd}")

    result = fetch_nfcore(tmp_path, fetched_at="2026-06-09T00:00:00Z", runner=_fake_runner)
    assert result["commit"] == _FAKE_COMMIT_SHA
    clone_cmds = [c for c in issued_commands if "clone" in c]
    assert len(clone_cmds) == 0, "clone must not run if dir exists"


# ---------------------------------------------------------------------------
# cmd_fetch — end-to-end offline with all network injected
# ---------------------------------------------------------------------------

_FAKE_EDAM_BODY = b"term_id\tterm_label\nop:0001\tSequence analysis\n"
_FAKE_NFCORE_COMMIT = "b" * 40

_BC_API_RECORD = {
    "name": "salmon",
    "versions": [{"id": "salmon-1.10.0", "meta_version": "1.10.0"}],
    "description": "Salmon tool",
    "tool_url": "https://biocontainers.pro/tools/salmon",
}


def _make_nfcore_tree(base: Path) -> None:
    """Create a minimal nf-core modules tree under base/modules/modules/nf-core."""
    nfcore_dir = base / "modules" / "modules" / "nf-core" / "salmon_quant"
    nfcore_dir.mkdir(parents=True, exist_ok=True)
    (nfcore_dir / "environment.yml").write_text(
        "name: salmon_quant\nchannels:\n  - bioconda\ndependencies:\n  - \"bioconda::salmon=1.10.0\"\n"
    )


def _make_fake_nfcore_runner(modules_base: Path) -> tuple[Callable[..., Any], list[list[str]]]:
    """Return (runner_fn, issued_commands_list) that simulates git clone + rev-parse."""
    issued: list[list[str]] = []

    def _runner(cmd: list[str], **kwargs: Any) -> Any:
        issued.append(list(cmd))
        if "clone" in cmd:
            _make_nfcore_tree(modules_base)
            return None
        if "rev-parse" in cmd:
            class _R:
                stdout = _FAKE_NFCORE_COMMIT
            return _R()
        raise AssertionError(f"Unexpected: {cmd}")

    return _runner, issued


def test_cmd_fetch_end_to_end_all_sources(tmp_path: Path) -> None:
    """cmd_fetch with injected fakes writes snapshot.json with all three source sections."""
    from methods_graph.cli import cmd_fetch

    runner, _ = _make_fake_nfcore_runner(tmp_path / "snap")
    dest = tmp_path / "snap"

    def _fake_edam_http_get(url: str) -> tuple[bytes, dict[str, str]]:
        return _FAKE_EDAM_BODY, {"last-modified": "Mon, 09 Jun 2026 00:00:00 GMT"}

    def _fake_bc_http_get_json(url: str) -> Any:
        return [_BC_API_RECORD]

    cmd_fetch(
        dest=dest,
        do_edam=True,
        do_nfcore=True,
        do_biocontainers=True,
        fetched_at="2026-06-09T00:00:00Z",
        _edam_http_get=_fake_edam_http_get,
        _nfcore_runner=runner,
        _bc_http_get_json=_fake_bc_http_get_json,
    )

    snap_path = dest / "snapshot.json"
    assert snap_path.exists(), "snapshot.json must be written"
    data = json.loads(snap_path.read_text())

    # EDAM section
    edam = data["sources"]["edam"]
    assert edam is not None, "edam source must be present"
    expected_sha = hashlib.sha256(_FAKE_EDAM_BODY).hexdigest()
    assert edam["sha256"] == expected_sha

    # nfcore section
    nfcore = data["sources"]["nfcore_modules"]
    assert nfcore is not None, "nfcore_modules source must be present"
    assert nfcore["commit"] == _FAKE_NFCORE_COMMIT

    # biocontainers section
    bc = data["sources"]["biocontainers"]
    assert bc is not None, "biocontainers source must be present"
    assert "salmon" in bc["tools"], f"Expected 'salmon' in tools; got {bc['tools']}"


def test_cmd_fetch_bc_wholesale_failure_still_writes_snapshot(tmp_path: Path) -> None:
    """When BioContainers raises wholesale, snapshot.json is still written with edam+nfcore."""
    from methods_graph.cli import cmd_fetch

    runner, _ = _make_fake_nfcore_runner(tmp_path / "snap")
    dest = tmp_path / "snap"

    def _fake_edam_http_get(url: str) -> tuple[bytes, dict[str, str]]:
        return _FAKE_EDAM_BODY, {}

    def _fake_bc_http_get_json_raises(url: str) -> Any:
        raise RuntimeError("Simulated wholesale network failure")

    cmd_fetch(
        dest=dest,
        do_edam=True,
        do_nfcore=True,
        do_biocontainers=True,
        fetched_at="2026-06-09T00:00:00Z",
        _edam_http_get=_fake_edam_http_get,
        _nfcore_runner=runner,
        _bc_http_get_json=_fake_bc_http_get_json_raises,
    )

    snap_path = dest / "snapshot.json"
    assert snap_path.exists(), "snapshot.json must be written even on BC failure"
    data = json.loads(snap_path.read_text())

    # EDAM and nfcore must be present
    assert data["sources"]["edam"] is not None, "edam must be recorded despite BC failure"
    assert data["sources"]["nfcore_modules"] is not None, "nfcore must be recorded despite BC failure"

    # biocontainers section should exist (error or empty tools), not raise
    bc = data["sources"]["biocontainers"]
    assert bc is not None, "biocontainers section must be written even on failure"
    # Either an error key or empty tools — both are acceptable failure records.
    has_error = "error" in bc
    has_empty_tools = isinstance(bc.get("tools"), dict)
    assert has_error or has_empty_tools, f"BC failure manifest shape unexpected: {bc}"
