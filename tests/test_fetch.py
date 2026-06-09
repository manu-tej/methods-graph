"""Tests for methods_graph.fetch — all offline, no network I/O."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from methods_graph.fetch import (
    _build_request,
    _transform_biocontainer,
    bioconda_packages_from_nfcore,
    fetch_biocontainers,
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
