"""Execution-spec layer: extract a module's runnable recipe from its nf-core source.

nf-core modules carry the *exact, version-pinned* runnable recipe in their own files:
  - ``main.nf`` ``container`` directive  -> the pinned image (docker + singularity),
  - ``environment.yml``                  -> the conda package + version,
  - ``main.nf`` ``script:`` / ``template`` -> the command,
  - ``main.nf`` ``input:``/``output:``    -> the typed I/O contract.

This is the ground truth no LLM can fake (e.g. the build hash ``--r41hc247a5b_3``),
and the connector previously dropped it (containers came only from the BioContainers
snapshot, so e.g. deseq2 had no container).  This module reads the recipe directly and
emits, per module, an ``ExecutionSpec`` node + a ``RUNS_AS`` edge (Module -> ExecutionSpec),
grounded: emitted only when the Module node exists.  Pure parsers; no clock/RNG/network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord,
                                 Provenance)

_CONTAINER_DQ = re.compile(r'\bcontainer\s+"([^"]*)"', re.DOTALL)
_CONTAINER_SQ = re.compile(r"\bcontainer\s+'([^']*)'")
_QUOTED = re.compile(r"'([^']+)'")
_TEMPLATE = re.compile(r"\btemplate\s+'([^']+)'")
_SCRIPT = re.compile(r"\bscript\s*:")
_HEREDOC = re.compile(r'"""')
_INPUT_BLOCK = re.compile(
    r"\binput\s*:(.*?)(?:\boutput\s*:|\bwhen\s*:|\bscript\s*:|\bexec\s*:|\bshell\s*:|$)", re.DOTALL)
_OUTPUT_BLOCK = re.compile(
    r"\boutput\s*:(.*?)(?:\bwhen\s*:|\bscript\s*:|\bexec\s*:|\bshell\s*:|$)", re.DOTALL)
_IO_NAME = re.compile(r"(?:path|val)\(\s*(\w+)")
_EMIT = re.compile(r"emit:\s*(\w+)")


def _is_singularity(img: str) -> bool:
    return "singularity" in img or "depot.galaxyproject" in img


def parse_container(text: str) -> dict | None:
    """Return {'docker': str|None, 'singularity': str|None} or None if no directive.

    Handles the nf-core singularity/docker ternary inside a double-quoted ``${...}``
    block, and the plain single-image (single- or double-quoted) form.
    """
    m = _CONTAINER_DQ.search(text)
    if m:
        imgs = _QUOTED.findall(m.group(1))
        if imgs:
            docker = singularity = None
            for img in imgs:
                if _is_singularity(img):
                    singularity = img
                else:
                    docker = img
            if docker is None and singularity is None:
                docker = imgs[-1]
            return {"docker": docker, "singularity": singularity}
        val = m.group(1).strip()
        if val and "$" not in val:                 # double-quoted plain image
            return {"docker": val, "singularity": None}
    m = _CONTAINER_SQ.search(text)
    if m and m.group(1).strip():
        return {"docker": m.group(1).strip(), "singularity": None}
    return None


def parse_command(text: str) -> dict:
    """Return {'kind': 'template'|'script'|'unknown', 'ref': <template file>|None}."""
    t = _TEMPLATE.search(text)
    if t:
        return {"kind": "template", "ref": t.group(1)}
    if _SCRIPT.search(text) or _HEREDOC.search(text):
        return {"kind": "script", "ref": None}
    return {"kind": "unknown", "ref": None}


def _dedup(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def parse_io(text: str) -> dict:
    """Return {'inputs': [decl names], 'outputs': [emit names]} from the I/O blocks."""
    inp = _INPUT_BLOCK.search(text)
    out = _OUTPUT_BLOCK.search(text)
    inputs = _IO_NAME.findall(inp.group(1)) if inp else []
    outputs = _EMIT.findall(out.group(1)) if out else []
    return {"inputs": _dedup(inputs), "outputs": _dedup(outputs)}


def parse_conda(env_yml_text: str) -> list[str]:
    """Return ``pkg=version`` deps from an ``environment.yml`` (channel prefix stripped)."""
    try:
        env = yaml.safe_load(env_yml_text) or {}
    except yaml.YAMLError:
        return []
    out: list[str] = []
    for dep in (env.get("dependencies") or []) if isinstance(env, dict) else []:
        if isinstance(dep, str):
            out.append(dep.split("::")[-1])
    return out


def extract_module_execution(module_dir: Path) -> dict | None:
    """Extract the full execution spec for one module dir, or None if not resolvable.

    Requires ``main.nf`` + a ``meta.yml`` declaring ``name`` (the ``mod:<name>`` join key).
    """
    module_dir = Path(module_dir)
    main_nf = module_dir / "main.nf"
    meta = module_dir / "meta.yml"
    if not main_nf.exists() or not meta.exists():
        return None
    try:
        meta_d = yaml.safe_load(meta.read_text(errors="ignore")) or {}
    except yaml.YAMLError:
        return None
    name = meta_d.get("name") if isinstance(meta_d, dict) else None
    if not (isinstance(name, str) and name):
        return None
    text = main_nf.read_text(errors="ignore")
    container = parse_container(text) or {}
    env_path = module_dir / "environment.yml"
    conda = parse_conda(env_path.read_text(errors="ignore")) if env_path.exists() else []
    io = parse_io(text)
    return {
        "module": name,
        "container": container.get("docker"),
        "container_singularity": container.get("singularity"),
        "conda": conda,
        "command": parse_command(text),
        "inputs": io["inputs"],
        "outputs": io["outputs"],
    }


@dataclass
class ExecutionReport:
    specs: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (mod_id, reason)


def build_execution_records(
    pipeline_roots: list[Path],
    existing_node_ids: set[str],
    *,
    ingested_at: str,
) -> tuple[list[NodeRecord], list[EdgeRecord], ExecutionReport]:
    """Walk vendored nf-core modules under *pipeline_roots* and emit, per module,
    an ``ExecutionSpec`` node + a ``RUNS_AS`` edge (mod:<name> -> exec:<name>).

    Grounded: a recipe is emitted only when its ``mod:<name>`` node already exists
    in *existing_node_ids* (skips are recorded).  Deterministic: modules visited in
    sorted path order; the first occurrence of a shared module wins.
    """
    prov = Provenance("nfcore_execution", "", ingested_at)
    report = ExecutionReport()
    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    seen: set[str] = set()

    mod_dirs: list[Path] = []
    for root in pipeline_roots:
        for main_nf in Path(root).rglob("main.nf"):
            if "modules/nf-core" in main_nf.as_posix():
                mod_dirs.append(main_nf.parent)

    for mod_dir in sorted(set(mod_dirs), key=lambda p: p.as_posix()):
        spec = extract_module_execution(mod_dir)
        if spec is None:
            continue
        mod_id = f"mod:{spec['module']}"
        if mod_id in seen:
            continue
        seen.add(mod_id)
        if mod_id not in existing_node_ids:
            report.skipped.append((mod_id, "module_missing"))
            continue
        exec_id = f"exec:{spec['module']}"
        props = {k: v for k, v in spec.items() if k != "module"}
        nodes.append(NodeRecord(exec_id, spec["module"], NodeKind.EXECUTION_SPEC, props, prov))
        edges.append(EdgeRecord(mod_id, exec_id, EdgeKind.RUNS_AS, {"basis": "nfcore_main_nf"}, prov))
        report.specs += 1
    return nodes, edges, report
