"""Tests for the declarative, reproducible ingestion manifest + resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from methods_graph.ingest import (
    IngestSpec, PipelineSpec, load_manifest, resolve_sources,
)


def _write(p: Path, text: str) -> Path:
    p.write_text(text)
    return p


# --- manifest parsing ---


def test_load_manifest_parses_sources_and_pipelines(tmp_path):
    m = _write(tmp_path / "ingest.yaml",
               "snapshot_dir: snap\n"
               "sources:\n  edam: EDAM.tsv\n  stato:\n"
               "pipelines:\n"
               "  - {name: rnaseq, revision: '3.14.0', nxf_ver: '23.10.0'}\n"
               "  - {name: sarek, revision: '3.4.0'}\n")
    spec = load_manifest(m)
    assert spec.snapshot_dir == "snap"
    assert spec.base_dir == tmp_path
    assert spec.sources == {"edam": "EDAM.tsv", "stato": None}
    assert spec.pipelines == (
        PipelineSpec("rnaseq", "3.14.0", "23.10.0"),
        PipelineSpec("sarek", "3.4.0", None),
    )


def test_load_manifest_rejects_unknown_source_key(tmp_path):
    m = _write(tmp_path / "i.yaml",
               "snapshot_dir: s\nsources:\n  bogus: x\npipelines: []\n")
    with pytest.raises(ValueError, match="unknown source"):
        load_manifest(m)


def test_load_manifest_rejects_pipeline_without_revision(tmp_path):
    m = _write(tmp_path / "i.yaml",
               "snapshot_dir: s\nsources: {}\npipelines:\n  - {name: rnaseq}\n")
    with pytest.raises(ValueError, match="revision"):
        load_manifest(m)


# --- source resolution (the no-silent-drop guarantee) ---


def test_resolve_sources_uses_default_layout_and_overrides(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "EDAM.tsv").write_text("x")
    (snap / "biotools").mkdir()
    spec = IngestSpec(base_dir=tmp_path, snapshot_dir="snap",
                      sources={"edam": "EDAM.tsv", "biotools": None}, pipelines=())
    resolved = resolve_sources(spec)
    assert resolved["edam"] == snap / "EDAM.tsv"
    assert resolved["biotools"] == snap / "biotools"  # None -> default layout


def test_resolve_sources_raises_listing_all_missing(tmp_path):
    spec = IngestSpec(base_dir=tmp_path, snapshot_dir="snap",
                      sources={"edam": None, "stato": None}, pipelines=())
    with pytest.raises(FileNotFoundError) as ei:
        resolve_sources(spec)
    msg = str(ei.value)
    # ALL declared-but-missing sources are listed (a build never silently drops one)
    assert "edam" in msg and "stato" in msg


def test_resolve_sources_absolute_snapshot_dir(tmp_path):
    snap = tmp_path / "abs_snap"
    snap.mkdir()
    (snap / "obi.owl").write_text("x")
    spec = IngestSpec(base_dir=Path("/nonexistent"), snapshot_dir=str(snap),
                      sources={"obi": None}, pipelines=())
    resolved = resolve_sources(spec)
    assert resolved["obi"] == snap / "obi.owl"


# --- cmd_ingest orchestrator (fetch -> resolve -> build -> audit gate -> lock) ---

import json
import shutil

from methods_graph.cli import cmd_ingest

_FX = Path(__file__).parent / "fixtures"
_MINI = _FX / "nfcore_pipeline" / "mini"


class _R:
    def __init__(self, stdout=""):
        self.stdout = stdout


def _ingest_runner():
    """Fake subprocess runner: 'clones' the mini fixture and writes a preview DAG."""
    def runner(cmd, **kw):
        if cmd[:2] == ["git", "clone"]:
            dst = Path(cmd[-1])
            shutil.copytree(_MINI, dst)
            (dst / "workflows").mkdir(exist_ok=True)
            (dst / "workflows" / "main.nf").write_text(
                "include { FASTQC } from '../modules/nf-core/fastqc'\n"
                "include { SALMON } from '../modules/nf-core/salmon'\n")
            return _R()
        if "rev-parse" in cmd:
            return _R("abc123def456\n")
        if cmd and cmd[0] == "nextflow":
            Path(cmd[cmd.index("-with-dag") + 1]).write_text(
                'flowchart TB\n v0(["FASTQC"])\n v1["c"]\n v2(["SALMON"])\n'
                ' v0 --> v1\n v1 --> v2\n')
            return _R()
        return _R()
    return runner


def test_cmd_ingest_end_to_end(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    shutil.copy(_FX / "edam_sample.tsv", snap / "EDAM.tsv")
    manifest = tmp_path / "ingest.yaml"
    manifest.write_text(
        "snapshot_dir: snap\n"
        "sources:\n  edam: EDAM.tsv\n"
        "pipelines:\n  - {name: mini, revision: '1.0.0', nxf_ver: '23.10.0'}\n")
    dest = tmp_path / "work"

    lock = cmd_ingest(manifest_path=manifest, dest=dest, db_path=tmp_path / "m.kuzu",
                      staging_dir=tmp_path / "stg", ingested_at="2026-06-16",
                      runner=_ingest_runner())

    assert lock["audit"]["ok"] is True
    p0 = lock["pipelines"][0]
    assert p0["commit"] == "abc123def456" and p0["nxf_ver"] == "23.10.0"
    assert p0["dag"] == "dag.mmd"
    # lock persisted to disk + records the resolved source
    saved = json.loads((dest / "ingest.lock.json").read_text())
    assert saved["audit"]["ok"] is True
    assert "edam" in saved["sources"]
    # the build actually produced the vendored-tool methods
    from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
    with KuzuMethodsGraphProvider(tmp_path / "m.kuzu") as p:
        ids = {m["id"] for m in p.get_methods()}
    assert {"m:fastqc", "m:salmon"} <= ids


def test_cmd_ingest_fails_fast_on_missing_source(tmp_path):
    # declares stato but the snapshot lacks it -> raises BEFORE any clone/build
    manifest = tmp_path / "ingest.yaml"
    manifest.write_text("snapshot_dir: snap\nsources:\n  stato:\npipelines: []\n")
    (tmp_path / "snap").mkdir()
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return _R()

    with pytest.raises(FileNotFoundError, match="stato"):
        cmd_ingest(manifest_path=manifest, dest=tmp_path / "work",
                   db_path=tmp_path / "m.kuzu", staging_dir=tmp_path / "stg",
                   ingested_at="2026-06-16", runner=runner)
    assert calls == []                       # nothing fetched
    assert not (tmp_path / "m.kuzu").exists()  # nothing built
