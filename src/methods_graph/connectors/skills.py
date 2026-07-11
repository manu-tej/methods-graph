"""Ingest external bioinformatics agent-skill libraries (BioClaw, K-Dense, ...) as
Skill nodes wired to the graph's Method/Operation nodes. See
docs/superpowers/specs/2026-06-19-skill-library-integration-design.md.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance


@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str
    source: str
    description: str = ""
    primary_tool: str = ""
    # DECLARED tools (primary_tool + frontmatter dependencies). These ALONE mint
    # gating Skill-[WRAPS]->Method edges, so a skill only inherits the evaluability
    # of methods it actually declares.
    tools: tuple[str, ...] = ()
    # Tools merely MENTIONED in prose (the commands file). Informational only — they
    # never mint a WRAPS edge, so a substrate tool used for I/O (e.g. scanpy read/plot
    # inside a CellTypist annotation skill) can't make the skill inherit that tool's
    # gates. Promote a context tool to a declared dependency via curation if warranted.
    context_tools: tuple[str, ...] = ()
    domain: str = ""


# Frontmatter is the first ``---``-fenced block. Match up to the first line that is
# exactly ``---`` (the closing fence) so a ``---`` inside a quoted value — or a Markdown
# horizontal rule in the body — can neither truncate the parse nor crash the scanner.
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def _split_frontmatter(text: str) -> dict | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        # A malformed SKILL.md is skipped (the None contract), never aborting the batch.
        return None
    return fm if isinstance(fm, dict) else None


# Known tool tokens worth mining from prose commands files (extend via curated wiring).
_TOOL_TOKEN = re.compile(r"\b(bcftools|samtools|salmon|kallisto|star|hisat2|kraken2|"
                         r"scanpy|pydeseq2|deseq2|edger|limma|openms|pyopenms|gatk|vep|"
                         r"bwa|bowtie2|featurecounts|fastqc|multiqc|blastn|blastp)\b",
                         re.IGNORECASE)


def load_skill_library(root: Path, *, source: str) -> list[SkillRecord]:
    """Parse every <root>/*/SKILL.md into SkillRecords, enriching tools from a sibling
    commands_and_thresholds.md when present. Deterministic (sorted by id)."""
    out: list[SkillRecord] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        rec = parse_skill_md(skill_md.read_text(encoding="utf-8"), source=source)
        if rec is None:
            continue
        cmds = skill_md.parent / "commands_and_thresholds.md"
        extra: list[str] = []
        if cmds.exists():
            for m in _TOOL_TOKEN.findall(cmds.read_text(encoding="utf-8")):
                if m not in extra:
                    extra.append(m)
        # Prose-mined tokens are CONTEXT, not declared dependencies: keep them out of
        # `tools` so they never mint a gating WRAPS edge (see SkillRecord.context_tools).
        ctx = tuple(t for t in extra if t not in rec.tools)
        if ctx:
            rec = dataclasses.replace(rec, context_tools=ctx)
        out.append(rec)
    return sorted(out, key=lambda r: r.id)


def parse_skill_md(text: str, *, source: str) -> SkillRecord | None:
    """Parse one SKILL.md's frontmatter into a SkillRecord (None if it has no name)."""
    fm = _split_frontmatter(text)
    if not fm:
        return None
    raw_name = fm.get("name")
    name = str(raw_name).strip() if raw_name is not None else ""
    if not name:                               # missing, empty, or explicit-null name
        return None
    raw_primary = fm.get("primary_tool")
    primary = str(raw_primary).strip() if raw_primary is not None else ""
    # primary_tool may be a comma-separated list (e.g. "scipy, matplotlib, typst").
    primary_tools = [p.strip() for p in primary.split(",") if p.strip()]
    deps = fm.get("dependencies") or []
    dep_tools = [re.split(r"[<>=!~;\[ ]", str(d).strip())[0].strip() for d in deps
                 if isinstance(d, str)]
    tools = tuple(dict.fromkeys([t for t in [*primary_tools, *dep_tools] if t]))
    return SkillRecord(
        id=f"skill:{source}/{name}",
        name=name,
        source=source,
        description=str(fm.get("description", "") or "").strip(),
        primary_tool=primary,
        tools=tools,
        domain=str(fm.get("domain", "") or "").strip(),
    )


def aliases_path() -> Path:
    return Path(__file__).with_name("skill_aliases.yaml")


def load_aliases(path: Path | None = None) -> dict[str, str]:
    raw = yaml.safe_load((path or aliases_path()).read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


@dataclass
class SkillReport:
    skills: int = 0
    wraps: int = 0
    unwired: list[str] = field(default_factory=list)   # skill ids with no WRAPS edge


def build_skill_records(
    nodes: list[NodeRecord], records: list[SkillRecord], *,
    ingested_at: str, aliases: dict[str, str] | None = None,
) -> tuple[list[NodeRecord], list[EdgeRecord], "SkillReport"]:
    """Mint Skill nodes + grounded Skill-[WRAPS]->Method edges. A WRAPS edge is emitted
    only when a tool resolves (alias map, else lowercased Method name) to an existing
    Method node; skills that resolve nothing are recorded in report.unwired."""
    aliases = load_aliases() if aliases is None else aliases
    method_by_name: dict[str, str] = {
        n.name.lower(): n.id for n in nodes if n.kind == NodeKind.METHOD}
    method_ids = {n.id for n in nodes if n.kind == NodeKind.METHOD}
    prov = Provenance("skills", "", ingested_at)

    skill_nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    report = SkillReport()
    for rec in sorted(records, key=lambda r: r.id):
        skill_nodes.append(NodeRecord(
            rec.id, rec.name, NodeKind.SKILL,
            {"source": rec.source, "description": rec.description,
             "primary_tool": rec.primary_tool, "domain": rec.domain,
             "context_tools": list(rec.context_tools)}, prov))
        wired: set[str] = set()
        # Only DECLARED tools mint WRAPS edges; prose-mined context_tools are recorded on
        # the node (above) but never gate a verdict, so a skill cannot inherit the
        # evaluability of a tool it merely mentions.
        for tool in rec.tools:
            mid = aliases.get(tool.lower()) or method_by_name.get(tool.lower())
            if mid and mid in method_ids and mid not in wired:
                wired.add(mid)
                edges.append(EdgeRecord(rec.id, mid, EdgeKind.WRAPS,
                                        {"tool": tool, "via": "declared"}, prov))
        if not wired:
            report.unwired.append(rec.id)
    report.skills = len(skill_nodes)
    report.wraps = len(edges)
    return skill_nodes, sorted(edges, key=lambda e: (e.from_id, e.to_id)), report
