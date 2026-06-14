"""Parse an nf-core module directory into Module + Method nodes and edges.

Each module's ``meta.yml`` may declare multiple tools under the ``tools:`` key.
``parse_module`` emits one ``Module`` node and one ``Method`` node per tool,
connected by a ``WRAPS`` edge.  All EDAM PERFORMS / HAS_TOPIC edges are also
emitted per tool.  This captures **intra-module composition** — a module that
wraps both ``samtools`` and ``bcftools`` will have two WRAPS edges, one to each
Method.

Pipeline-level DAG gap (Phase 2)
---------------------------------
Intra-module multi-tool composition is now captured via multiple WRAPS edges
from a Module to its Methods.  The PIPELINE-LEVEL DAG — i.e. the
``DOWNSTREAM_OF`` ordering between modules across a pipeline's ``main.nf``
workflow file — is STILL NOT ingested and remains Phase 2.  ``parse_module``
operates on a single module directory and does not read pipeline workflow files.
The ``DOWNSTREAM_OF`` EdgeKind stays declared-but-unemitted.

I/O Ontology edges (INPUT / OUTPUT)
------------------------------------
Real nf-core ``meta.yml`` files carry EDAM URIs on the ``input``/``output``
channel dicts under the ``ontologies`` key rather than on the tool entry.
``parse_module`` walks both sections and emits ``EdgeKind.INPUT`` /
``EdgeKind.OUTPUT`` edges from each wrapped Method to the corresponding EDAM
node.  When a channel declares no ``ontologies`` but does carry a glob
``pattern`` (e.g. ``"*.fastq.gz"``), the connector falls back to mapping that
pattern to a known EDAM format id; unmapped patterns yield a synthetic
``fmt:pat:<ext>`` Format node so the I/O contract is still expressed without a
dangling edge.  For single-tool modules this is exact; for multi-tool modules
the module-level I/O is attributed to every wrapped method — a documented
approximation until per-tool I/O is available in meta.yml.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_DEP_RE = re.compile(r"(?:(?P<chan>[\w-]+)::)?(?P<pkg>[\w.-]+)=(?P<ver>[\w.+-]+)")

# Mapping from EDAM local-name prefix to the graph id prefix used in edam.py.
_EDAM_PREFIX_MAP = {
    "operation_": "op:",
    "topic_": "topic:",
    "data_": "data:",
    "format_": "fmt:",
}

# Glob-suffix → EDAM format id.  Seeded with the common genomics formats
# (spec Q4); anything not here falls back to a synthetic Format node so the
# I/O contract is still expressed.  Keys are lowercased extensions WITHOUT the
# leading '*'.
_PATTERN_TO_FMT: dict[str, str] = {
    ".fastq.gz": "fmt:format_1930", ".fq.gz": "fmt:format_1930",
    ".fastq": "fmt:format_1930", ".fq": "fmt:format_1930",
    ".fasta": "fmt:format_1929", ".fa": "fmt:format_1929", ".fna": "fmt:format_1929",
    ".bam": "fmt:format_2572", ".sam": "fmt:format_2573", ".cram": "fmt:format_3462",
    ".vcf.gz": "fmt:format_3016", ".vcf": "fmt:format_3016", ".bcf": "fmt:format_3020",
    ".bed": "fmt:format_3003", ".gtf": "fmt:format_2306",
    ".gff3": "fmt:format_2305", ".gff": "fmt:format_2305",
    ".bw": "fmt:format_3006", ".bigwig": "fmt:format_3006",
}


def _normalize_pattern_ext(pattern: str) -> str:
    """'*.fastq.gz' → '.fastq.gz' (lowercased, leading glob stripped)."""
    p = pattern.strip().lower()
    star = p.rfind("*")
    if star != -1:
        p = p[star + 1:]
    if not p.startswith("."):
        p = "." + p.lstrip(".")
    return p


def _pattern_to_fmt_id(pattern: str) -> str:
    """Map a glob to a known EDAM fmt: id, else a synthetic 'fmt:pat:<ext>' id.

    Longest matching suffix wins so '.vcf.gz' beats '.gz' (when present).
    """
    ext = _normalize_pattern_ext(pattern)
    for known in sorted(_PATTERN_TO_FMT, key=len, reverse=True):
        if ext.endswith(known):
            return _PATTERN_TO_FMT[known]
    return f"fmt:pat:{ext}"


def _collect_io_patterns(section: Any) -> list[str]:
    """Recursively collect every 'pattern' string in an input/output section.

    Tolerates the same irregular shapes as _collect_ontology_edam_uris
    (list, list-of-lists, channel-dicts).
    """
    patterns: list[str] = []
    if isinstance(section, list):
        for item in section:
            patterns.extend(_collect_io_patterns(item))
    elif isinstance(section, dict):
        pat = section.get("pattern")
        if isinstance(pat, str) and pat:
            patterns.append(pat)
        for k, v in section.items():
            if k != "pattern" and isinstance(v, (dict, list)):
                patterns.extend(_collect_io_patterns(v))
    return patterns


def _collect_ontology_edam_uris(section: Any) -> list[str]:
    """Recursively walk *section* (the raw input or output YAML value) and
    collect every ``edam`` URI string found inside any ``ontologies`` list.

    The nf-core meta.yml shape is deliberately irregular:
    - ``input``/``output`` may be a list of channel-dicts OR a list-of-lists
      (grouped channels, from ``- -`` YAML syntax), or None.
    - Each channel-dict is ``{channel_name: {type: ..., ontologies: [...]}}``.
    - ``ontologies`` items are ``{edam: "<URI>"}`` mappings.

    This function is purely structural — it recurses into all dict values and
    list items, so it tolerates any nesting depth without assumptions.
    Returns a flat list of URI strings; may contain duplicates.
    """
    uris: list[str] = []
    if isinstance(section, list):
        for item in section:
            uris.extend(_collect_ontology_edam_uris(item))
    elif isinstance(section, dict):
        ontologies = section.get("ontologies")
        if isinstance(ontologies, list):
            for entry in ontologies:
                if isinstance(entry, dict):
                    val = entry.get("edam")
                    if isinstance(val, str) and val:
                        uris.append(val)
        # Recurse into all values except 'ontologies' (already consumed above).
        # Skipping the 'ontologies' key prevents spurious collection of edam
        # URIs that are nested *inside* an ontologies entry (e.g. a malformed
        # or future entry like {edam: "URI", ontologies: [{edam: "URI2"}]}).
        for k, v in section.items():
            if k != "ontologies" and isinstance(v, (dict, list)):
                uris.extend(_collect_ontology_edam_uris(v))
    return uris


def _io_module_targets(meta: dict[str, Any], section_key: str) -> set[str]:
    """Return the set of EDAM/synthetic-format target ids for a meta.yml
    section ('input' or 'output').  Pure: returns ids only (no node creation).
    Used by the pipeline connector to infer DOWNSTREAM_OF."""
    raw_uris = _collect_ontology_edam_uris(meta.get(section_key))
    ids = {
        nid for uri in raw_uris
        if (nid := _edam_uri_to_node_id(uri)) is not None
        and (nid.startswith("data:") or nid.startswith("fmt:"))
    }
    for pat in _collect_io_patterns(meta.get(section_key)):
        ids.add(_pattern_to_fmt_id(pat))
    return ids


def _edam_uri_to_node_id(uri: str) -> str | None:
    """Convert a full EDAM URI to a graph node id matching the edam.py scheme.

    Examples::
        http://edamontology.org/format_1930  →  fmt:format_1930
        http://edamontology.org/data_3494    →  data:data_3494
        http://edamontology.org/operation_3798 → op:operation_3798
        http://edamontology.org/topic_3170   →  topic:topic_3170
        <anything unclassifiable>            →  None
    """
    local = uri.rsplit("/", 1)[-1]
    for prefix, id_prefix in _EDAM_PREFIX_MAP.items():
        if local.startswith(prefix):
            return id_prefix + local
    return None


def _bioconda_dep(env_path: Path, prefer_pkg: str | None = None, *,
                  allow_single_fallback: bool = False) -> tuple[str | None, str | None]:
    """Return (pkg, version) for the bioconda dependency in *env_path*.

    Matching rules (in priority order):

    1. If *prefer_pkg* matches a dep's package name (case-insensitive) →
       return that dep immediately.  This ensures each tool gets its own
       package even in a multi-dep environment.yml.
    2. Elif there is exactly ONE bioconda dep AND either no *prefer_pkg* was
       given OR *allow_single_fallback* is True → return it.
       The *allow_single_fallback* flag is set by the caller when the module
       has exactly one valid tool, making it unambiguous to assign the sole
       dep to that tool even when the tool key name differs from the package
       name (e.g. tool key ``fastqc_check``, package ``fastqc``).
    3. Else → return ``(None, None)``.  Multiple deps exist but none matches
       *prefer_pkg*, or this is a multi-tool module and no name match was
       found; refusing to guess avoids mis-assignment.
    """
    if not env_path.exists():
        return None, None
    env = yaml.safe_load(env_path.read_text()) or {}
    bioconda_deps: list[tuple[str, str]] = []
    for dep in env.get("dependencies", []):
        if not isinstance(dep, str):
            continue
        m = _DEP_RE.match(dep)
        if m and (m.group("chan") in (None, "bioconda")):
            pkg, ver = m.group("pkg"), m.group("ver")
            # Rule 1: prefer-match wins immediately.
            if prefer_pkg and pkg.lower() == prefer_pkg.lower():
                return pkg, ver
            bioconda_deps.append((pkg, ver))
    # Rule 2: unambiguous single dep — fires when there is no prefer_pkg at
    # all, OR when the caller explicitly allows the single-tool fallback (i.e.
    # a single-tool module with a single dep, even if names differ).
    if len(bioconda_deps) == 1 and (allow_single_fallback or not prefer_pkg):
        return bioconda_deps[0]
    # Rule 3: ambiguous — don't guess.
    return None, None


def parse_module(
    module_dir: Path,
    *,
    ingested_at: str,
    tool_id: str | None = None,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Parse an nf-core module directory into nodes and edges.

    Parameters
    ----------
    module_dir:
        Path to the module directory containing ``meta.yml`` (and optionally
        ``environment.yml``).
    ingested_at:
        ISO date string used for provenance records.
    tool_id:
        Optional authoritative tool identity derived from the nf-core module
        directory name (e.g. ``"bcftools"`` for
        ``modules/nf-core/bcftools/sort/``).  When provided AND the module has
        exactly one valid tool entry, the Method node id is
        ``m:<tool_id>`` and its name is ``<tool_id>`` — overriding the
        potentially generic meta.yml tool key (e.g. ``"sort"``).  The
        original meta.yml key is preserved in
        ``properties["tool_label"]`` for traceability.  Bioconda lookup still
        uses the authoritative ``tool_id`` as the preferred package name so the
        correct dep is chosen.

        When *tool_id* is ``None`` **or** the module has more than one valid
        tool, the function behaves exactly as before: each tool gets
        ``m:<meta_key>`` as its id (backwards-compatible path).
    """
    prov = Provenance("nfcore", f"https://github.com/nf-core/modules/tree/master/{module_dir.name}",
                      ingested_at)
    meta = yaml.safe_load((module_dir / "meta.yml").read_text()) or {}
    if not isinstance(meta, dict):
        meta = {}
    module_name = meta.get("name", module_dir.name)
    env_path = module_dir / "environment.yml"

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    module_id = f"mod:{module_name}"
    nodes.append(NodeRecord(module_id, module_name, NodeKind.MODULE,
                            {"description": meta.get("description", "")}, prov))

    tools = meta.get("tools") or []

    # Count valid (non-empty dict) tool entries to detect single-tool modules.
    # Note: if the same tool name appears twice, single_tool will be False and
    # only an exact name-match can assign the dep — degenerate but safe.
    valid_tools = [t for t in tools if isinstance(t, dict) and t]
    single_tool = len(valid_tools) == 1

    # Determine whether to apply the tool_id override.  The override only
    # applies when a tool_id was given AND the module has exactly one valid
    # tool entry.  Multi-tool modules keep per-tool meta keys (those are
    # reliable real names) regardless of tool_id.
    apply_tool_id_override = tool_id is not None and single_tool

    # Dedupe: track emitted method ids within this module so that if two tool
    # entries share the same name we emit one Method + one WRAPS.
    emitted_method_ids: set[str] = set()

    # Detect conflicting bio.tools identifiers in the multi-tool path.
    # Distinct tools cannot legitimately share one bio.tools id; a duplicated
    # identifier (e.g. biotools:homer copy-pasted onto samtools/DESeq2 entries)
    # is a source error.  We trust only the entry whose tool name matches the
    # identifier (or none, if no entry matches).  A conflicting id on a
    # mismatched entry is silently dropped to prevent entity-resolution fusion
    # of unrelated tools in the graph.
    #
    # Strategy: first pass — build {identifier_lower: set(tool_names_lower)}.
    # An identifier is "conflicting" if more than one distinct tool name maps
    # to it.  This only matters in the multi-tool path; for single-tool modules
    # there can be no conflict by definition.
    _id_to_tool_names: dict[str, set[str]] = {}
    if not single_tool:
        for _te in valid_tools:
            _tname, _tmeta = next(iter(_te.items()))
            _raw_id = (_tmeta.get("identifier") or "").replace("biotools:", "").lower()
            if _raw_id:
                _id_to_tool_names.setdefault(_raw_id, set()).add(_tname.lower())
    # Set of identifiers that are shared by more than one distinct tool name.
    _conflicting_ids: frozenset[str] = frozenset(
        _id for _id, _names in _id_to_tool_names.items() if len(_names) > 1
    )

    # Collect module-level I/O EDAM node ids from input/output channel ontologies.
    # These are attributed to every wrapped method: exact for single-tool modules;
    # an approximation for multi-tool modules (module-level I/O is ambiguous per tool).
    def _io_targets(section_key: str) -> tuple[list[str], list[NodeRecord]]:
        # Single source of truth for the id set (shared with the pipeline
        # connector via the module-level _io_module_targets helper).
        ids = _io_module_targets(meta, section_key)
        # Build synthetic Format nodes for any 'fmt:pat:' ids (channels that
        # declared a glob pattern with no known EDAM mapping) so the
        # INPUT/OUTPUT edge is not dangling.  Map each synthetic id back to a
        # representative pattern for the node's 'pattern' property.
        synth: list[NodeRecord] = []
        synth_seen: set[str] = set()
        for pat in _collect_io_patterns(meta.get(section_key)):
            fid = _pattern_to_fmt_id(pat)
            if fid.startswith("fmt:pat:") and fid not in synth_seen:
                synth_seen.add(fid)
                synth.append(NodeRecord(fid, fid.split(":", 2)[-1], NodeKind.FORMAT,
                                        {"pattern": pat}, prov))
        return sorted(ids), synth

    input_edam_ids, input_synth = _io_targets("input")
    output_edam_ids, output_synth = _io_targets("output")
    # Synthetic Format nodes are deduped downstream by the resolver (by id).
    nodes.extend(input_synth)
    nodes.extend(output_synth)

    for tool_entry in valid_tools:
        tool_name, tool_meta = next(iter(tool_entry.items()))

        if apply_tool_id_override:
            # Single-tool module with an authoritative directory-derived tool_id:
            # use the directory name as the canonical method name, but keep
            # the original meta key as tool_label for traceability.
            # Method identity is case-insensitive: tool names like DESeq2/deseq2
            # refer to the same tool, so the id is always lowercased.
            effective_name = tool_id  # type: ignore[assignment]
            method_id = f"m:{tool_id.lower()}"
            tool_label: str | None = tool_name  # original meta.yml key (e.g. "sort")
            # Prefer the authoritative tool_id as the bioconda package name so
            # we pick the right dep (e.g. "bcftools" over generic "sort").
            pkg, ver = _bioconda_dep(env_path, prefer_pkg=tool_id,
                                     allow_single_fallback=True)
        else:
            # Original path: use the meta.yml tool key as the method identity.
            # Method identity is case-insensitive: tool names like Comet/comet
            # refer to the same tool, so the id is always lowercased while the
            # display name preserves the original case from meta.yml.
            effective_name = tool_name
            method_id = f"m:{tool_name.lower()}"
            tool_label = None
            # Per-tool bioconda resolution: prefer_pkg=tool_name guarantees the
            # correct package is selected even in multi-dep environment.yml files.
            # allow_single_fallback lets a single-tool module claim the sole dep
            # even when the tool key name differs from the package name.
            pkg, ver = _bioconda_dep(env_path, prefer_pkg=tool_name,
                                     allow_single_fallback=single_tool)

        _raw_biotools_id = (tool_meta.get("identifier") or "").replace("biotools:", "") or None
        # In the multi-tool path: if this identifier is shared by more than one
        # distinct tool name (a copy-paste error), keep it only for the entry
        # whose tool name matches the identifier; otherwise clear it.
        if _raw_biotools_id and _raw_biotools_id.lower() in _conflicting_ids:
            biotools_id = _raw_biotools_id if tool_name.lower() == _raw_biotools_id.lower() else None
        else:
            biotools_id = _raw_biotools_id

        if method_id not in emitted_method_ids:
            emitted_method_ids.add(method_id)
            props: dict[str, Any] = {
                "description": tool_meta.get("description", ""),
                "homepage": tool_meta.get("homepage", ""),
                "version": ver or "",
                "implementation_type": "nextflow",
            }
            if tool_label is not None:
                props["tool_label"] = tool_label
            nodes.append(MethodRecord(
                id=method_id, name=effective_name, kind=NodeKind.METHOD,
                properties=props,
                provenance=prov, bioconda_pkg=pkg, biotools_id=biotools_id,
            ))
            # Keep WRAPS and EDAM edges inside the dedup guard so that a
            # repeated tool name yields exactly one Method + one WRAPS + one
            # set of EDAM edges (no duplicates).
            edges.append(EdgeRecord(module_id, method_id, EdgeKind.WRAPS, {}, prov))
            # edam_operations / edam_topics — supported legacy shape used in some
            # test fixtures and occasionally in real modules.
            for op in tool_meta.get("edam_operations", []):
                edges.append(EdgeRecord(method_id, f"op:{op}", EdgeKind.PERFORMS, {}, prov))
            for tp in tool_meta.get("edam_topics", []):
                edges.append(EdgeRecord(method_id, f"topic:{tp}", EdgeKind.HAS_TOPIC, {}, prov))
            # I/O ontology edges — parsed from input/output channel ontologies.
            for edam_id in input_edam_ids:
                edges.append(EdgeRecord(method_id, edam_id, EdgeKind.INPUT, {}, prov))
            for edam_id in output_edam_ids:
                edges.append(EdgeRecord(method_id, edam_id, EdgeKind.OUTPUT, {}, prov))

    return nodes, edges
