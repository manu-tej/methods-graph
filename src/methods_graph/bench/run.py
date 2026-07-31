"""Walk a directory of nf-core clones and emit the frozen benchmark item set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from methods_graph.bench.build import build_manifest, make_items
from methods_graph.bench.gold import gold_sequence
from methods_graph.connectors.nfcore_pipeline import (
    module_paths_from_modules_json, process_to_modid)


def _module_map(pipeline_dir: Path) -> dict[str, str]:
    modules_json = json.loads((pipeline_dir / "modules.json").read_text())
    rel_paths = module_paths_from_modules_json(modules_json)
    path_to_modid = {path: f"mod:{path.split('/')[-1]}" for path in rel_paths}
    return process_to_modid(pipeline_dir, path_to_modid)


def build_from_clones(
    pipelines_dir: Path, out_dir: Path, *, goals: dict[str, str],
) -> dict[str, Any]:
    """Build items for every clone under *pipelines_dir*; write items + manifest."""
    if not pipelines_dir.exists():
        raise FileNotFoundError(f"--pipelines path does not exist: {pipelines_dir}")

    items_dir, gold_dir = out_dir / "items", out_dir / "gold"
    items_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for pipeline_dir in sorted(p for p in pipelines_dir.iterdir() if p.is_dir()):
        name = pipeline_dir.name
        revision = "unknown"
        dag_path = pipeline_dir / "dag.mmd"
        if not dag_path.exists():
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": "no dag.mmd produced by nextflow -preview"})
            continue

        text = dag_path.read_text()
        try:
            sequence = gold_sequence(text, _module_map(pipeline_dir))
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": f"could not read pipeline metadata: "
                                       f"{type(exc).__name__}: {exc}"})
            continue

        if len(sequence) < 2:
            outcomes.append({"pipeline": name, "revision": revision,
                             "status": "dropped", "n_items": 0,
                             "reason": f"gold sequence too short ({len(sequence)} steps)"})
            continue

        items = make_items(
            pipeline=name, revision=revision, nxf_ver="unknown",
            dag_sha256=hashlib.sha256(text.encode()).hexdigest(),
            goal=goals.get(name, name), sequence=sequence,
            derivation="nextflow_dsl2",
        )
        (items_dir / f"{name}.json").write_text(json.dumps(items, indent=2, sort_keys=True))
        outcomes.append({"pipeline": name, "revision": revision, "status": "used",
                         "reason": None, "n_items": len(items)})

    manifest = build_manifest(outcomes)
    (gold_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
