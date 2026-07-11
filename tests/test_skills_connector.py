from methods_graph.connectors.skills import SkillRecord, parse_skill_md

_DE = """---
name: differential-expression
description: Bulk transcriptomics differential expression.
tool_type: python
primary_tool: PyDESeq2
---
# Differential Expression
"""

def test_parse_extracts_frontmatter_and_primary_tool():
    rec = parse_skill_md(_DE, source="bioclaw")
    assert rec.id == "skill:bioclaw/differential-expression"
    assert rec.name == "differential-expression"
    assert rec.primary_tool == "PyDESeq2"
    assert rec.tools == ("PyDESeq2",)

def test_parse_query_skill_without_primary_tool():
    text = "---\nname: query-uniprot\ndescription: Query UniProt.\n---\n"
    rec = parse_skill_md(text, source="bioclaw")
    assert rec.name == "query-uniprot"
    assert rec.primary_tool == "" and rec.tools == ()

def test_parse_returns_none_without_name():
    assert parse_skill_md("no frontmatter here", source="bioclaw") is None


def test_load_skill_library_walks_dirs(tmp_path):
    from methods_graph.connectors.skills import load_skill_library
    d = tmp_path / "differential-expression"
    d.mkdir()
    (d / "SKILL.md").write_text(_DE)
    (d / "commands_and_thresholds.md").write_text("Run `bcftools` then PyDESeq2.")
    q = tmp_path / "query-uniprot"; q.mkdir()
    (q / "SKILL.md").write_text("---\nname: query-uniprot\ndescription: x\n---\n")
    recs = load_skill_library(tmp_path, source="bioclaw")
    by = {r.name: r for r in recs}
    assert set(by) == {"differential-expression", "query-uniprot"}
    assert "PyDESeq2" in by["differential-expression"].tools
    # A tool mined from the commands file is CONTEXT, not a declared tool: it must not
    # leak into `tools` (which gates WRAPS edges), only into `context_tools`.
    assert "bcftools" in by["differential-expression"].context_tools
    assert "bcftools" not in by["differential-expression"].tools


def test_build_skill_records_wires_resolvable_tools():
    from methods_graph.connectors.skills import build_skill_records, SkillRecord
    from methods_graph.types import NodeKind, NodeRecord, Provenance
    P = Provenance("test", "", "2026-06-19")
    nodes = [NodeRecord("m:deseq2", "deseq2", NodeKind.METHOD, {}, P)]
    recs = [
        SkillRecord("skill:bioclaw/differential-expression", "differential-expression",
                    "bioclaw", primary_tool="PyDESeq2", tools=("PyDESeq2",)),
        SkillRecord("skill:bioclaw/query-uniprot", "query-uniprot", "bioclaw"),
    ]
    skill_nodes, wraps, report = build_skill_records(nodes, recs, ingested_at="2026-06-19")
    assert {n.id for n in skill_nodes} == {"skill:bioclaw/differential-expression",
                                           "skill:bioclaw/query-uniprot"}
    assert all(n.kind == NodeKind.SKILL for n in skill_nodes)
    assert (wraps[0].from_id, wraps[0].to_id, wraps[0].kind.value) == \
           ("skill:bioclaw/differential-expression", "m:deseq2", "WRAPS")
    assert wraps[0].properties.get("via") == "declared"     # gating edge from a declared tool
    assert len(wraps) == 1                                  # query-uniprot wires nothing
    assert "skill:bioclaw/query-uniprot" in report.unwired


def test_prose_mined_tool_does_not_mint_wraps_edge():
    """A tool only MENTIONED in prose (context_tools) must NOT create a WRAPS edge — else a
    skill inherits gates from a substrate tool it doesn't depend on (the cell-annotation /
    scanpy over-wiring bug: CellTypist isn't curated, scanpy is only used for I/O)."""
    from methods_graph.connectors.skills import build_skill_records, SkillRecord
    from methods_graph.types import NodeKind, NodeRecord, Provenance
    P = Provenance("test", "", "2026-06-19")
    nodes = [NodeRecord("m:scanpy", "scanpy", NodeKind.METHOD, {}, P)]
    rec = SkillRecord("skill:bioclaw/cell-annotation", "cell-annotation", "bioclaw",
                      primary_tool="CellTypist", tools=("CellTypist",),
                      context_tools=("scanpy",))
    skill_nodes, wraps, report = build_skill_records(nodes, [rec], ingested_at="2026-06-19")
    assert wraps == []                                      # no edge from a prose mention
    assert "skill:bioclaw/cell-annotation" in report.unwired
    assert skill_nodes[0].properties["context_tools"] == ["scanpy"]  # recorded, not gating


def test_frontmatter_embedded_fence_in_quoted_value_does_not_truncate_or_crash():
    """A '---' inside a quoted value must neither truncate the parse nor crash the scanner."""
    text = '---\nname: t1\ndescription: "a---b"\nprimary_tool: deseq2\n---\n# body\n'
    rec = parse_skill_md(text, source="bioclaw")
    assert rec is not None
    assert rec.name == "t1"
    assert rec.primary_tool == "deseq2"        # not dropped by a naive split("---")
    assert rec.description == "a---b"


def test_malformed_yaml_frontmatter_is_skipped_not_crashed():
    """Unparseable YAML in the fence -> skill skipped (None), never an exception that
    would abort the whole library ingest."""
    text = '---\nname: "unterminated\nprimary_tool: x\n---\n'
    assert parse_skill_md(text, source="bioclaw") is None


def test_null_name_is_skipped_not_minted_as_none():
    """`name:` with a null value must be skipped, not minted as `skill:.../None`."""
    assert parse_skill_md("---\nname:\nprimary_tool: x\n---\n", source="bioclaw") is None


def test_comma_separated_primary_tool_is_split():
    """A comma-list primary_tool (e.g. 'scipy, matplotlib') yields separate tool tokens."""
    text = "---\nname: sec-report\ndescription: d.\nprimary_tool: scipy, matplotlib, typst\n---\n"
    rec = parse_skill_md(text, source="bioclaw")
    assert rec.tools == ("scipy", "matplotlib", "typst")


def test_kdense_skill_extracts_tools_from_dependencies():
    """Version specifiers ~=, <, >= are stripped; exact tool names extracted."""
    text = (
        "---\nname: pydeseq2\ndescription: DE with pydeseq2.\n"
        "dependencies:\n- pydeseq2~=0.4\n- \"numpy<2\"\n- scanpy>=1.9\n---\n"
    )
    from methods_graph.connectors.skills import parse_skill_md
    rec = parse_skill_md(text, source="kdense")
    assert rec.tools == ("pydeseq2", "numpy", "scanpy")


def test_dependency_compound_specifier_is_stripped_to_bare_tool():
    """A compound version range like 'pydeseq2>=0.4,<0.5' must yield the bare tool name
    'pydeseq2' — the comma-joined upper bound must not leak into the tool token."""
    from methods_graph.connectors.skills import parse_skill_md
    text = (
        "---\nname: c\ndescription: d.\n"
        "dependencies:\n- \"pydeseq2>=0.4,<0.5\"\n- \"numpy>=1.20,<2.0\"\n"
        "- \"scanpy~=1.9,!=1.9.3\"\n---\n"
    )
    rec = parse_skill_md(text, source="kdense")
    assert rec.tools == ("pydeseq2", "numpy", "scanpy")


def test_built_db_has_skill_nodes_and_de_wraps_deseq2():
    import pathlib, kuzu
    db = pathlib.Path("data/methods.kuzu")
    if not db.exists():
        import pytest; pytest.skip("built DB artifact not present")
    con = kuzu.Connection(kuzu.Database(str(db), read_only=True))
    r = con.execute("MATCH (s:Entity {kind:'Skill'}) RETURN count(*)")
    assert r.get_next()[0] >= 10
    r = con.execute("MATCH (s:Entity {id:'skill:bioclaw/differential-expression'})"
                    "-[e:Rel {kind:'WRAPS'}]->(m:Entity) RETURN m.id")
    assert r.get_next()[0] == "m:deseq2"
