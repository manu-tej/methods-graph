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
# inline script body: the first heredoc (""" or ''') after `script:`
_SCRIPT_BODY = re.compile(r'\bscript\s*:.*?"""(.*?)"""', re.DOTALL)
_SCRIPT_BODY_SQ = re.compile(r"\bscript\s*:.*?'''(.*?)'''", re.DOTALL)
_INPUT_BLOCK = re.compile(
    r"\binput\s*:(.*?)(?:\boutput\s*:|\bwhen\s*:|\bscript\s*:|\bexec\s*:|\bshell\s*:|$)", re.DOTALL)
_OUTPUT_BLOCK = re.compile(
    r"\boutput\s*:(.*?)(?:\bwhen\s*:|\bscript\s*:|\bexec\s*:|\bshell\s*:|$)", re.DOTALL)
_IO_NAME = re.compile(r"(?:path|val)\(\s*(\w+)")
_EMIT = re.compile(r"emit:\s*(\w+)")


def _image_like(s: str) -> bool:
    """A real container ref has a registry path or URL (contains '/').  This excludes
    the ternary CONDITION tokens ('singularity', 'apptainer', 'true', …) that share the
    quotes but are not images."""
    return "/" in s


def parse_container(text: str) -> dict | None:
    """Return {'docker': str|None, 'singularity': str|None} or None if no directive.

    Handles the nf-core singularity/docker ternary (``container "${ <cond> ? '<sing>' :
    '<docker>' }"``) and the plain single-image form.  Classification is by the image
    string itself, NOT by the ternary condition: the singularity image is the one served
    over ``http(s)`` (a download URL — galaxyproject ``depot`` *or* the Seqera-community
    ``...seqera.io/.../data`` blob), the docker image is the bare registry path.  The
    old code matched the substring "singularity", which captured the literal condition
    token and dropped the real Seqera blob URL.
    """
    m = _CONTAINER_DQ.search(text)
    if m:
        body = m.group(1)
        imgs = [q for q in _QUOTED.findall(body) if _image_like(q)]
        if imgs:
            singularity = next((q for q in imgs if q.startswith("http")), None)
            docker = next((q for q in imgs if not q.startswith("http")), None)
            if docker is None and singularity is None:
                docker = imgs[-1]
            return {"docker": docker, "singularity": singularity}
        val = body.strip()
        if val and "$" not in val:                 # double-quoted plain image, no ${}
            return {"docker": val, "singularity": None}
    m = _CONTAINER_SQ.search(text)
    if m and m.group(1).strip():
        return {"docker": m.group(1).strip(), "singularity": None}
    return None


def parse_command(text: str) -> dict:
    """Return {'kind': 'template'|'script'|'unknown', 'ref': <template file or script body>|None}.

    For ``template '<file>'`` modules, ref is the template filename.  For inline
    ``script:`` modules, ref is the heredoc command body (the actual recipe), so the
    spec is runnable rather than a bare {kind:script, ref:null} stub.
    """
    t = _TEMPLATE.search(text)
    if t:
        return {"kind": "template", "ref": t.group(1)}
    body = _SCRIPT_BODY.search(text) or _SCRIPT_BODY_SQ.search(text)
    if body:
        return {"kind": "script", "ref": body.group(1).strip() or None}
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
    sorted path order; the first occurrence of a shared module supplies the primary
    recipe.  A module vendored at DIFFERENT containers across pipelines (e.g. multiqc
    pinned per-pipeline) records every distinct image in ``container_variants`` so a
    version is never silently dropped.
    """
    prov = Provenance("nfcore_execution", "", ingested_at)
    report = ExecutionReport()
    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    mod_dirs: list[Path] = []
    for root in pipeline_roots:
        for main_nf in Path(root).rglob("main.nf"):
            if "modules/nf-core" in main_nf.as_posix():
                mod_dirs.append(main_nf.parent)

    # Pass 1: collect the primary (first path-sorted) spec per module + every distinct
    # container it is vendored with across pipelines.
    primary: dict[str, dict] = {}
    variants: dict[str, list[str]] = {}
    for mod_dir in sorted(set(mod_dirs), key=lambda p: p.as_posix()):
        spec = extract_module_execution(mod_dir)
        if spec is None:
            continue
        mod_id = f"mod:{spec['module']}"
        primary.setdefault(mod_id, spec)
        c = spec.get("container")
        if c and c not in variants.setdefault(mod_id, []):
            variants[mod_id].append(c)

    # Pass 2: emit grounded ExecutionSpec + RUNS_AS.
    for mod_id in sorted(primary):
        if mod_id not in existing_node_ids:
            report.skipped.append((mod_id, "module_missing"))
            continue
        spec = primary[mod_id]
        # A spec with NO container image (neither docker nor singularity) is not a
        # runnable recipe — e.g. nf-core's `dragen` module, which ships no container
        # because DRAGEN runs on dedicated FPGA hardware.  Don't mint a misleading
        # "runnable" ExecutionSpec for it (the Module node still exists); record the skip.
        if not (str(spec.get("container") or "").strip()
                or str(spec.get("container_singularity") or "").strip()):
            report.skipped.append((mod_id, "no_container_image"))
            continue
        exec_id = f"exec:{spec['module']}"
        props = {k: v for k, v in spec.items() if k != "module"}
        if len(variants.get(mod_id, [])) > 1:
            props["container_variants"] = variants[mod_id]
        nodes.append(NodeRecord(exec_id, spec["module"], NodeKind.EXECUTION_SPEC, props, prov))
        edges.append(EdgeRecord(mod_id, exec_id, EdgeKind.RUNS_AS, {"basis": "nfcore_main_nf"}, prov))
        report.specs += 1
    return nodes, edges, report
