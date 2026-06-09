# Methods Master Graph (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `methods_graph` standalone Python package that ingests EDAM + nf-core + BioContainers into an embedded Kùzu graph, extracts seed subgraphs, and exposes a `MethodsGraphProvider` mapping graph nodes to quration's `AnalysisMethod`.

**Architecture:** Staging → Resolve → Load pipeline. Pure connectors normalize each source to staging Parquet; a deterministic resolver merges them into canonical node/edge tables; a loader builds a Kùzu DB idempotently; an extract layer does k-hop/typed traversal; a single provider module is the only quration-aware code.

**Tech Stack:** Python 3.10+, kuzu, polars (Parquet I/O), pyyaml, networkx, pytest. quration is an optional dependency used only by the provider.

---

## File Structure

```
src/methods_graph/
  __init__.py
  types.py                  # staging + canonical record dataclasses, enums
  connectors/
    __init__.py
    edam.py                 # EDAM TSV → Operation/Topic/Data/Format + IS_A staging
    nfcore.py               # meta.yml + environment.yml → Pipeline/Module/Method + edges
    biocontainers.py        # BioContainers API json → Container/Package staging
  resolve/
    __init__.py
    resolver.py             # staging → canonical Method nodes + SAME_AS candidates
  graph/
    __init__.py
    schema.py               # DDL strings: CREATE NODE/REL TABLE
    loader.py               # build Kùzu DB from canonical Parquet (idempotent)
  extract/
    __init__.py
    seed.py                 # k-hop + method-neighborhood Cypher templates
    adapters.py             # to_networkx, to_rag_text
  provider/
    __init__.py
    quration_provider.py    # MethodsGraphProvider → AnalysisMethod mapping
  cli.py                    # build · resolve · load · query
tests/
  fixtures/                 # recorded source samples (committed)
  test_edam.py
  test_nfcore.py
  test_biocontainers.py
  test_resolver.py
  test_loader.py
  test_extract.py
  test_provider.py
  test_integration.py
data/                       # gitignored: staging/, canonical/, methods.kuzu
```

---

## Task 0: Package scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/methods_graph/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "methods-graph"
version = "0.1.0"
description = "Bioinformatics methods master graph (EDAM + nf-core + BioContainers) on Kuzu"
requires-python = ">=3.10"
dependencies = [
    "kuzu>=0.6",
    "polars>=1.0",
    "pyyaml>=6.0",
    "networkx>=3.0",
]

[project.optional-dependencies]
quration = ["quration"]
dev = ["pytest>=8.0"]

[project.scripts]
methods-graph = "methods_graph.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package + test init files**

```python
# src/methods_graph/__init__.py
"""Bioinformatics methods master graph."""
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 3: Install and verify import**

Run: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && python -c "import methods_graph; import kuzu; print(methods_graph.__version__)"`
Expected: prints `0.1.0` with no import errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/methods_graph/__init__.py tests/__init__.py
git commit -m "chore: scaffold methods_graph package"
```

---

## Task 1: Core record types

The staging and canonical layers exchange typed records. Define them once.

**Files:**
- Create: `src/methods_graph/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_types.py
from methods_graph.types import MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance


def test_method_record_roundtrips_to_dict():
    prov = Provenance(source="nfcore", source_url="https://x", ingested_at="2026-06-08")
    rec = MethodRecord(
        id="m:salmon",
        name="salmon",
        kind=NodeKind.METHOD,
        bioconda_pkg="salmon",
        biotools_id="salmon",
        properties={"version": "1.10.0"},
        provenance=prov,
    )
    d = rec.to_row()
    assert d["id"] == "m:salmon"
    assert d["bioconda_pkg"] == "salmon"
    assert d["source"] == "nfcore"


def test_edge_record_to_row():
    prov = Provenance(source="edam", source_url="https://edam", ingested_at="2026-06-08")
    e = EdgeRecord(from_id="m:salmon", to_id="op:quant",
                   kind=EdgeKind.PERFORMS, properties={}, provenance=prov)
    row = e.to_row()
    assert row["from_id"] == "m:salmon"
    assert row["to_id"] == "op:quant"
    assert row["kind"] == "PERFORMS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.types'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/types.py
"""Shared record types for staging and canonical layers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(str, Enum):
    METHOD = "Method"
    PIPELINE = "Pipeline"
    MODULE = "Module"
    CONTAINER = "Container"
    PACKAGE = "Package"
    OPERATION = "Operation"
    TOPIC = "Topic"
    DATA = "Data"
    FORMAT = "Format"
    PAPER = "Paper"


class EdgeKind(str, Enum):
    HAS_MODULE = "HAS_MODULE"
    WRAPS = "WRAPS"
    DOWNSTREAM_OF = "DOWNSTREAM_OF"
    PACKAGED_AS = "PACKAGED_AS"
    FROM_PACKAGE = "FROM_PACKAGE"
    PERFORMS = "PERFORMS"
    HAS_TOPIC = "HAS_TOPIC"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    HAS_FORMAT = "HAS_FORMAT"
    IS_A = "IS_A"
    CITES = "CITES"
    SAME_AS = "SAME_AS"


@dataclass(frozen=True)
class Provenance:
    source: str          # "edam" | "nfcore" | "biocontainers"
    source_url: str
    ingested_at: str     # ISO date, passed in (never call datetime.now in pure code)


@dataclass
class NodeRecord:
    id: str
    name: str
    kind: NodeKind
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def to_row(self) -> dict[str, Any]:
        row = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "properties": json.dumps(self.properties, sort_keys=True),
        }
        if self.provenance:
            row.update(source=self.provenance.source,
                       source_url=self.provenance.source_url,
                       ingested_at=self.provenance.ingested_at)
        return row


@dataclass
class MethodRecord(NodeRecord):
    """A Method node carries the extra join keys used by the resolver."""
    bioconda_pkg: str | None = None
    biotools_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        row = super().to_row()
        row["bioconda_pkg"] = self.bioconda_pkg or ""
        row["biotools_id"] = self.biotools_id or ""
        return row


@dataclass
class EdgeRecord:
    from_id: str
    to_id: str
    kind: EdgeKind
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def to_row(self) -> dict[str, Any]:
        row = {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "kind": self.kind.value,
            "properties": json.dumps(self.properties, sort_keys=True),
        }
        if self.provenance:
            row.update(source=self.provenance.source,
                       source_url=self.provenance.source_url,
                       ingested_at=self.provenance.ingested_at)
        return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_types.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/types.py tests/test_types.py
git commit -m "feat: add core node/edge record types"
```

---

## Task 2: EDAM connector

EDAM ships a flat TSV (columns include `Class ID`, `Preferred Label`, `Parents`, `Obsolete`).
We parse operations/topics/data/formats and `IS_A` edges from the `Parents` column.

**Files:**
- Create: `src/methods_graph/connectors/__init__.py` (empty)
- Create: `src/methods_graph/connectors/edam.py`
- Create: `tests/fixtures/edam_sample.tsv`
- Test: `tests/test_edam.py`

- [ ] **Step 1: Create the fixture**

```tsv
Class ID	Preferred Label	Parents	Obsolete
http://edamontology.org/operation_3798	Read summarisation	http://edamontology.org/operation_2495	FALSE
http://edamontology.org/operation_2495	Gene expression analysis		FALSE
http://edamontology.org/topic_3170	RNA-Seq		FALSE
http://edamontology.org/data_3494	DNA sequence		FALSE
http://edamontology.org/format_1930	FASTQ		FALSE
http://edamontology.org/operation_0000	Obsolete thing		TRUE
```

(Use real tab characters between columns.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_edam.py
from pathlib import Path
from methods_graph.connectors.edam import parse_edam
from methods_graph.types import NodeKind, EdgeKind

FIXTURE = Path(__file__).parent / "fixtures" / "edam_sample.tsv"


def test_parse_edam_extracts_typed_nodes():
    nodes, edges = parse_edam(FIXTURE, ingested_at="2026-06-08")
    by_kind = {n.kind for n in nodes}
    assert NodeKind.OPERATION in by_kind
    assert NodeKind.TOPIC in by_kind
    assert NodeKind.DATA in by_kind
    assert NodeKind.FORMAT in by_kind


def test_parse_edam_skips_obsolete():
    nodes, _ = parse_edam(FIXTURE, ingested_at="2026-06-08")
    assert all("operation_0000" not in n.id for n in nodes)


def test_parse_edam_builds_is_a_edges():
    _, edges = parse_edam(FIXTURE, ingested_at="2026-06-08")
    is_a = [e for e in edges if e.kind == EdgeKind.IS_A]
    assert any(e.from_id.endswith("operation_3798") and e.to_id.endswith("operation_2495")
               for e in is_a)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_edam.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.connectors.edam'`

- [ ] **Step 4: Write minimal implementation**

```python
# src/methods_graph/connectors/__init__.py
```

```python
# src/methods_graph/connectors/edam.py
"""Parse the EDAM ontology TSV into typed nodes + IS_A edges."""
from __future__ import annotations

import csv
from pathlib import Path

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance

_PREFIX_TO_KIND = {
    "operation_": NodeKind.OPERATION,
    "topic_": NodeKind.TOPIC,
    "data_": NodeKind.DATA,
    "format_": NodeKind.FORMAT,
}
_KIND_TO_IDPREFIX = {
    NodeKind.OPERATION: "op:",
    NodeKind.TOPIC: "topic:",
    NodeKind.DATA: "data:",
    NodeKind.FORMAT: "fmt:",
}


def _classify(class_uri: str) -> tuple[NodeKind, str] | None:
    local = class_uri.rsplit("/", 1)[-1]
    for prefix, kind in _PREFIX_TO_KIND.items():
        if local.startswith(prefix):
            return kind, _KIND_TO_IDPREFIX[kind] + local
    return None


def parse_edam(tsv_path: Path, *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    prov = Provenance("edam", "http://edamontology.org", ingested_at)
    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    id_by_uri: dict[str, str] = {}

    with tsv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))

    # First pass: nodes + URI→id map (skip obsolete).
    kept: list[dict] = []
    for row in rows:
        if (row.get("Obsolete") or "").strip().upper() == "TRUE":
            continue
        cls = _classify(row["Class ID"])
        if cls is None:
            continue
        kind, node_id = cls
        id_by_uri[row["Class ID"]] = node_id
        nodes.append(NodeRecord(id=node_id, name=row["Preferred Label"].strip(),
                                kind=kind, properties={"uri": row["Class ID"]},
                                provenance=prov))
        kept.append(row)

    # Second pass: IS_A edges from Parents (space-separated URIs).
    for row in kept:
        child = id_by_uri[row["Class ID"]]
        for parent_uri in (row.get("Parents") or "").split():
            parent = id_by_uri.get(parent_uri)
            if parent:
                edges.append(EdgeRecord(child, parent, EdgeKind.IS_A, {}, prov))
    return nodes, edges
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_edam.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/connectors/ tests/test_edam.py tests/fixtures/edam_sample.tsv
git commit -m "feat: add EDAM connector"
```

---

## Task 3: nf-core connector

nf-core modules live as directories containing `meta.yml` (name, tools with bio.tools/EDAM
refs, input/output) and `environment.yml` (bioconda channel deps). We parse one module dir
into a `Method` node (the WRAPS target), `PERFORMS`/`HAS_TOPIC` edges to EDAM, and capture
the bioconda package as a join key.

**Files:**
- Create: `src/methods_graph/connectors/nfcore.py`
- Create: `tests/fixtures/nfcore/salmon_quant/meta.yml`
- Create: `tests/fixtures/nfcore/salmon_quant/environment.yml`
- Test: `tests/test_nfcore.py`

- [ ] **Step 1: Create fixtures**

```yaml
# tests/fixtures/nfcore/salmon_quant/meta.yml
name: salmon_quant
description: Quantify expression with Salmon
tools:
  - salmon:
      description: Selective alignment and quantification
      homepage: https://salmon.readthedocs.io
      identifier: biotools:salmon
      args_id: "$args"
      edam_operations:
        - "operation_3798"
      edam_topics:
        - "topic_3170"
input:
  - reads:
      type: file
      pattern: "*.fastq.gz"
output:
  - quant:
      type: file
      pattern: "*.sf"
```

```yaml
# tests/fixtures/nfcore/salmon_quant/environment.yml
name: salmon_quant
channels:
  - conda-forge
  - bioconda
dependencies:
  - "bioconda::salmon=1.10.0"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_nfcore.py
from pathlib import Path
from methods_graph.connectors.nfcore import parse_module
from methods_graph.types import NodeKind, EdgeKind

MODULE = Path(__file__).parent / "fixtures" / "nfcore" / "salmon_quant"


def test_parse_module_creates_method_with_join_keys():
    nodes, _ = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    assert method.name == "salmon"
    assert method.bioconda_pkg == "salmon"
    assert method.biotools_id == "salmon"
    assert method.properties["version"] == "1.10.0"


def test_parse_module_links_to_edam():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    method = next(n for n in nodes if n.kind == NodeKind.METHOD)
    performs = [e for e in edges if e.kind == EdgeKind.PERFORMS]
    has_topic = [e for e in edges if e.kind == EdgeKind.HAS_TOPIC]
    assert any(e.from_id == method.id and e.to_id == "op:operation_3798" for e in performs)
    assert any(e.from_id == method.id and e.to_id == "topic:topic_3170" for e in has_topic)


def test_parse_module_emits_module_and_wraps_edge():
    nodes, edges = parse_module(MODULE, ingested_at="2026-06-08")
    module = next(n for n in nodes if n.kind == NodeKind.MODULE)
    assert module.name == "salmon_quant"
    assert any(e.kind == EdgeKind.WRAPS and e.from_id == module.id for e in edges)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_nfcore.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.connectors.nfcore'`

- [ ] **Step 4: Write minimal implementation**

```python
# src/methods_graph/connectors/nfcore.py
"""Parse an nf-core module directory into Module + Method nodes and edges."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_DEP_RE = re.compile(r"(?:(?P<chan>[\w-]+)::)?(?P<pkg>[\w.-]+)=(?P<ver>[\w.+-]+)")


def _bioconda_dep(env_path: Path) -> tuple[str | None, str | None]:
    if not env_path.exists():
        return None, None
    env = yaml.safe_load(env_path.read_text()) or {}
    for dep in env.get("dependencies", []):
        if not isinstance(dep, str):
            continue
        m = _DEP_RE.match(dep)
        if m and (m.group("chan") in (None, "bioconda")):
            return m.group("pkg"), m.group("ver")
    return None, None


def parse_module(module_dir: Path, *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    prov = Provenance("nfcore", f"https://github.com/nf-core/modules/tree/master/{module_dir.name}",
                      ingested_at)
    meta = yaml.safe_load((module_dir / "meta.yml").read_text()) or {}
    module_name = meta.get("name", module_dir.name)
    pkg, ver = _bioconda_dep(module_dir / "environment.yml")

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    module_id = f"mod:{module_name}"
    nodes.append(NodeRecord(module_id, module_name, NodeKind.MODULE,
                            {"description": meta.get("description", "")}, prov))

    # First tool entry is the primary wrapped method.
    tools = meta.get("tools") or []
    if tools:
        tool_name, tool_meta = next(iter(tools[0].items()))
        biotools_id = (tool_meta.get("identifier") or "").replace("biotools:", "") or None
        method_id = f"m:{tool_name}"
        nodes.append(MethodRecord(
            id=method_id, name=tool_name, kind=NodeKind.METHOD,
            properties={
                "description": tool_meta.get("description", ""),
                "homepage": tool_meta.get("homepage", ""),
                "version": ver or "",
                "implementation_type": "nextflow",
            },
            provenance=prov, bioconda_pkg=pkg, biotools_id=biotools_id,
        ))
        edges.append(EdgeRecord(module_id, method_id, EdgeKind.WRAPS, {}, prov))
        for op in tool_meta.get("edam_operations", []):
            edges.append(EdgeRecord(method_id, f"op:{op}", EdgeKind.PERFORMS, {}, prov))
        for tp in tool_meta.get("edam_topics", []):
            edges.append(EdgeRecord(method_id, f"topic:{tp}", EdgeKind.HAS_TOPIC, {}, prov))

    return nodes, edges
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_nfcore.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/connectors/nfcore.py tests/test_nfcore.py tests/fixtures/nfcore/
git commit -m "feat: add nf-core module connector"
```

---

## Task 4: BioContainers connector

The BioContainers API returns JSON per tool: a name, and versions with container image URIs.
We map the tool to a bioconda `Package`, each version to a `Container`, and link
`Container -[:FROM_PACKAGE]-> Package`. The package name is the resolver join key.

**Files:**
- Create: `src/methods_graph/connectors/biocontainers.py`
- Create: `tests/fixtures/biocontainers_salmon.json`
- Test: `tests/test_biocontainers.py`

- [ ] **Step 1: Create the fixture**

```json
{
  "name": "salmon",
  "versions": [
    {
      "meta_version": "1.10.0",
      "images": [
        {"image_name": "quay.io/biocontainers/salmon:1.10.0--h7e5ed60_0",
         "registry": "quay.io"}
      ]
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_biocontainers.py
import json
from pathlib import Path
from methods_graph.connectors.biocontainers import parse_biocontainer
from methods_graph.types import NodeKind, EdgeKind

FIXTURE = Path(__file__).parent / "fixtures" / "biocontainers_salmon.json"


def test_parse_biocontainer_emits_package_and_container():
    data = json.loads(FIXTURE.read_text())
    nodes, edges = parse_biocontainer(data, ingested_at="2026-06-08")
    pkg = next(n for n in nodes if n.kind == NodeKind.PACKAGE)
    container = next(n for n in nodes if n.kind == NodeKind.CONTAINER)
    assert pkg.name == "salmon"
    assert "salmon:1.10.0" in container.properties["image_name"]


def test_container_links_to_package():
    data = json.loads(FIXTURE.read_text())
    nodes, edges = parse_biocontainer(data, ingested_at="2026-06-08")
    assert any(e.kind == EdgeKind.FROM_PACKAGE for e in edges)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_biocontainers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write minimal implementation**

```python
# src/methods_graph/connectors/biocontainers.py
"""Parse a BioContainers API tool record into Package + Container nodes."""
from __future__ import annotations

from typing import Any

from methods_graph.types import (EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance)


def parse_biocontainer(data: dict[str, Any], *, ingested_at: str) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    name = data["name"]
    prov = Provenance("biocontainers", f"https://biocontainers.pro/tools/{name}", ingested_at)
    pkg_id = f"pkg:{name}"
    nodes: list[NodeRecord] = [NodeRecord(pkg_id, name, NodeKind.PACKAGE,
                                          {"channel": "bioconda"}, prov)]
    edges: list[EdgeRecord] = []

    for version in data.get("versions", []):
        ver = version.get("meta_version", "")
        for img in version.get("images", []):
            image_name = img["image_name"]
            container_id = f"ctr:{image_name}"
            nodes.append(NodeRecord(container_id, image_name, NodeKind.CONTAINER,
                                    {"image_name": image_name,
                                     "registry": img.get("registry", ""),
                                     "version": ver}, prov))
            edges.append(EdgeRecord(container_id, pkg_id, EdgeKind.FROM_PACKAGE, {}, prov))
    return nodes, edges
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_biocontainers.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/connectors/biocontainers.py tests/test_biocontainers.py tests/fixtures/biocontainers_salmon.json
git commit -m "feat: add BioContainers connector"
```

---

## Task 5: Resolver (deterministic merge)

Merge per-source nodes into canonical nodes. Methods sharing a `bioconda_pkg` or `biotools_id`
become one canonical `Method` (deduped, properties merged). It also links each `Method` to its
`Container` via `PACKAGED_AS` by matching `Method.bioconda_pkg` to a `Package` name, and emits
`SAME_AS` *candidate* edges for name-only matches (never hard-merged).

**Files:**
- Create: `src/methods_graph/resolve/__init__.py` (empty)
- Create: `src/methods_graph/resolve/resolver.py`
- Test: `tests/test_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolver.py
from methods_graph.types import MethodRecord, NodeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.resolve.resolver import resolve

P = Provenance("test", "x", "2026-06-08")


def _method(id, name, pkg=None, bt=None):
    return MethodRecord(id=id, name=name, kind=NodeKind.METHOD, properties={},
                        provenance=P, bioconda_pkg=pkg, biotools_id=bt)


def test_methods_merge_on_bioconda_pkg():
    a = _method("m:salmon", "salmon", pkg="salmon", bt="salmon")
    b = _method("m:salmon-dup", "Salmon", pkg="salmon")
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) == 1


def test_resolver_links_method_to_package_via_packaged_as():
    method = _method("m:salmon", "salmon", pkg="salmon")
    pkg = NodeRecord("pkg:salmon", "salmon", NodeKind.PACKAGE, {}, P)
    nodes, edges = resolve(method_nodes=[method], other_nodes=[pkg], src_edges=[])
    assert any(e.kind == EdgeKind.PACKAGED_AS and e.to_id == "ctr-or-pkg" or
               (e.kind == EdgeKind.PACKAGED_AS) for e in edges)
    # Method links toward its package's containers; with no container we link to the package.
    assert any(e.kind == EdgeKind.PACKAGED_AS and e.from_id == "m:salmon" for e in edges)


def test_name_only_match_becomes_same_as_candidate():
    a = _method("m:bwa", "bwa", pkg="bwa")
    b = _method("m:bwa-tooluniverse", "bwa")   # no pkg/biotools id, name only
    nodes, edges = resolve(method_nodes=[a, b], other_nodes=[], src_edges=[])
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    same_as = [e for e in edges if e.kind == EdgeKind.SAME_AS]
    assert len(methods) == 2            # NOT hard-merged
    assert len(same_as) == 1
    assert 0.0 < same_as[0].properties["confidence"] < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.resolve.resolver'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/resolve/__init__.py
```

```python
# src/methods_graph/resolve/resolver.py
"""Deterministic entity resolution: merge methods on join keys; emit SAME_AS candidates."""
from __future__ import annotations

from methods_graph.types import (EdgeKind, EdgeRecord, MethodRecord, NodeKind,
                                  NodeRecord, Provenance)

_RESOLVER_PROV = Provenance("resolver", "internal", "")


def _merge_key(m: MethodRecord) -> str | None:
    if m.bioconda_pkg:
        return f"pkg::{m.bioconda_pkg.lower()}"
    if m.biotools_id:
        return f"bt::{m.biotools_id.lower()}"
    return None


def _merge_into(canon: MethodRecord, other: MethodRecord) -> None:
    for k, v in other.properties.items():
        canon.properties.setdefault(k, v)
    canon.bioconda_pkg = canon.bioconda_pkg or other.bioconda_pkg
    canon.biotools_id = canon.biotools_id or other.biotools_id


def resolve(*, method_nodes: list[MethodRecord], other_nodes: list[NodeRecord],
            src_edges: list[EdgeRecord]) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    canon_by_key: dict[str, MethodRecord] = {}
    keyless: list[MethodRecord] = []
    id_remap: dict[str, str] = {}     # original method id -> canonical id

    for m in method_nodes:
        key = _merge_key(m)
        if key is None:
            keyless.append(m)
            continue
        if key in canon_by_key:
            _merge_into(canon_by_key[key], m)
            id_remap[m.id] = canon_by_key[key].id
        else:
            canon_by_key[key] = m
            id_remap[m.id] = m.id

    canonical_methods = list(canon_by_key.values())
    edges: list[EdgeRecord] = []

    # Name-only matches → SAME_AS candidates (never hard-merged).
    by_name: dict[str, MethodRecord] = {m.name.lower(): m for m in canonical_methods}
    for m in keyless:
        id_remap[m.id] = m.id
        canonical_methods.append(m)
        match = by_name.get(m.name.lower())
        if match and match.id != m.id:
            edges.append(EdgeRecord(m.id, match.id, EdgeKind.SAME_AS,
                                    {"confidence": 0.5, "basis": "name"}, _RESOLVER_PROV))

    # Remap and dedupe source edges against merged ids.
    seen: set[tuple] = set()
    for e in src_edges:
        f = id_remap.get(e.from_id, e.from_id)
        t = id_remap.get(e.to_id, e.to_id)
        sig = (f, t, e.kind.value)
        if sig in seen:
            continue
        seen.add(sig)
        edges.append(EdgeRecord(f, t, e.kind, e.properties, e.provenance))

    # Method -[:PACKAGED_AS]-> Container (or Package if no container) via bioconda pkg.
    pkg_by_name = {n.name.lower(): n for n in other_nodes if n.kind == NodeKind.PACKAGE}
    containers_by_pkg: dict[str, list[NodeRecord]] = {}
    for e in src_edges:
        if e.kind == EdgeKind.FROM_PACKAGE:
            containers_by_pkg.setdefault(e.to_id, []).append(e.from_id)
    for m in canonical_methods:
        if not m.bioconda_pkg:
            continue
        pkg = pkg_by_name.get(m.bioconda_pkg.lower())
        if not pkg:
            continue
        ctrs = containers_by_pkg.get(pkg.id)
        targets = ctrs if ctrs else [pkg.id]
        for tgt in targets:
            edges.append(EdgeRecord(m.id, tgt, EdgeKind.PACKAGED_AS, {}, _RESOLVER_PROV))

    return canonical_methods + list(other_nodes), edges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_resolver.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/resolve/ tests/test_resolver.py
git commit -m "feat: add deterministic resolver with SAME_AS candidates"
```

---

## Task 6: Graph schema + loader

Kùzu uses one node table per primary-key shape and one rel table per (FROM, TO) pair. To keep
the schema small we use a single `Entity` node table keyed by `id` with a `kind` discriminator,
and a single `Rel` rel table (`FROM Entity TO Entity`) with a `kind` property. The loader writes
canonical nodes/edges to Parquet, then `COPY ... FROM` into a fresh DB (idempotent rebuild).

> Verify against pinned kuzu version during this task: single-table `CREATE NODE TABLE
> Entity(...)` + `CREATE REL TABLE Rel(FROM Entity TO Entity, ...)` and `COPY FROM` Parquet
> column-order semantics (first two rel columns are FROM/TO keys).

**Files:**
- Create: `src/methods_graph/graph/__init__.py` (empty)
- Create: `src/methods_graph/graph/schema.py`
- Create: `src/methods_graph/graph/loader.py`
- Test: `tests/test_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loader.py
import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph

P = Provenance("test", "x", "2026-06-08")


def test_build_graph_loads_nodes_and_edges(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"version": "1.10.0"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
    ]
    edges = [EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P)]
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    res = conn.execute("MATCH (m:Entity {kind:'Method'})-[r:Rel]->(o:Entity) "
                       "RETURN m.id, r.kind, o.id")
    rows = [row for row in res]
    assert ["m:salmon", "PERFORMS", "op:operation_3798"] in rows


def test_build_graph_is_idempotent(tmp_path):
    nodes = [NodeRecord("op:x", "X", NodeKind.OPERATION, {}, P)]
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")   # rebuild, no error
    conn = kuzu.Connection(kuzu.Database(str(db_path)))
    count = [r for r in conn.execute("MATCH (n:Entity) RETURN count(n)")][0][0]
    assert count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.graph.loader'`

- [ ] **Step 3: Write the schema module**

```python
# src/methods_graph/graph/__init__.py
```

```python
# src/methods_graph/graph/schema.py
"""Kùzu DDL. Single Entity node table + single Rel rel table with kind discriminators."""

NODE_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Entity(
    id STRING PRIMARY KEY,
    name STRING,
    kind STRING,
    properties STRING,
    bioconda_pkg STRING,
    biotools_id STRING,
    source STRING,
    source_url STRING,
    ingested_at STRING
)
"""

REL_TABLE = """
CREATE REL TABLE IF NOT EXISTS Rel(
    FROM Entity TO Entity,
    kind STRING,
    properties STRING,
    source STRING,
    source_url STRING,
    ingested_at STRING
)
"""

# Column order MUST match the Parquet files written by the loader.
NODE_COLUMNS = ["id", "name", "kind", "properties", "bioconda_pkg", "biotools_id",
                "source", "source_url", "ingested_at"]
REL_COLUMNS = ["from_id", "to_id", "kind", "properties", "source", "source_url", "ingested_at"]
```

- [ ] **Step 4: Write the loader**

```python
# src/methods_graph/graph/loader.py
"""Build a fresh Kùzu DB from canonical node/edge records via Parquet COPY."""
from __future__ import annotations

import shutil
from pathlib import Path

import kuzu
import polars as pl

from methods_graph.graph import schema
from methods_graph.types import EdgeRecord, MethodRecord, NodeRecord


def _node_row(n: NodeRecord) -> dict:
    row = n.to_row()
    row.setdefault("bioconda_pkg", n.bioconda_pkg if isinstance(n, MethodRecord) else "")
    row.setdefault("biotools_id", n.biotools_id if isinstance(n, MethodRecord) else "")
    row.setdefault("source", "")
    row.setdefault("source_url", "")
    row.setdefault("ingested_at", "")
    return {c: row.get(c, "") for c in schema.NODE_COLUMNS}


def _edge_row(e: EdgeRecord) -> dict:
    row = e.to_row()
    row.setdefault("source", "")
    row.setdefault("source_url", "")
    row.setdefault("ingested_at", "")
    return {c: row.get(c, "") for c in schema.REL_COLUMNS}


def build_graph(nodes: list[NodeRecord], edges: list[EdgeRecord],
                db_path: Path, *, staging_dir: Path) -> None:
    db_path = Path(db_path)
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Idempotent: drop any prior DB so a rebuild yields an identical graph.
    if db_path.exists():
        shutil.rmtree(db_path) if db_path.is_dir() else db_path.unlink()

    nodes_pq = staging_dir / "nodes.parquet"
    edges_pq = staging_dir / "edges.parquet"
    pl.DataFrame([_node_row(n) for n in nodes],
                 schema=schema.NODE_COLUMNS).write_parquet(nodes_pq)
    pl.DataFrame([_edge_row(e) for e in edges] or
                 [{c: None for c in schema.REL_COLUMNS}],
                 schema=schema.REL_COLUMNS).write_parquet(edges_pq)

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    conn.execute(schema.NODE_TABLE)
    conn.execute(schema.REL_TABLE)
    conn.execute(f'COPY Entity FROM "{nodes_pq.as_posix()}"')
    if edges:
        conn.execute(f'COPY Rel FROM "{edges_pq.as_posix()}"')
    conn.close()
    db.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_loader.py -v`
Expected: PASS (2 tests). If `COPY` rejects the empty-edge sentinel row, guard the `COPY Rel`
behind `if edges:` (already done) and skip writing the sentinel — adjust to write the edges
Parquet only when `edges` is non-empty.

- [ ] **Step 6: Commit**

```bash
git add src/methods_graph/graph/ tests/test_loader.py
git commit -m "feat: add Kuzu schema and idempotent loader"
```

---

## Task 7: Seed-subgraph extraction

A `Subgraph` is a pair of node/edge dict lists. `seed()` does a bounded variable-length traversal
from seed ids; `method_neighborhood()` returns the exact 1-hop slice needed to build an
`AnalysisMethod`.

**Files:**
- Create: `src/methods_graph/extract/__init__.py` (empty)
- Create: `src/methods_graph/extract/seed.py`
- Test: `tests/test_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.extract.seed import Subgraph, seed, method_neighborhood

P = Provenance("test", "x", "2026-06-08")


@pytest.fixture
def conn(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD, {"version": "1.10.0"}, P,
                     bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_3170", "RNA-Seq", NodeKind.TOPIC, {}, P),
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/salmon:1.10.0"}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "topic:topic_3170", EdgeKind.HAS_TOPIC, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P),
    ]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db_path)))


def test_seed_one_hop_returns_neighbors(conn):
    sg = seed(conn, ["m:salmon"], k_hops=1)
    ids = {n["id"] for n in sg.nodes}
    assert {"m:salmon", "op:operation_3798", "topic:topic_3170", "ctr:salmon"} <= ids


def test_method_neighborhood_groups_by_edge_kind(conn):
    nb = method_neighborhood(conn, "m:salmon")
    assert nb["method"]["name"] == "salmon"
    assert any(o["id"] == "op:operation_3798" for o in nb["operations"])
    assert any(t["id"] == "topic:topic_3170" for t in nb["topics"])
    assert any(c["id"] == "ctr:salmon" for c in nb["containers"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.extract.seed'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/extract/__init__.py
```

```python
# src/methods_graph/extract/seed.py
"""Seed-subgraph extraction over the Kùzu methods graph."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import kuzu


@dataclass
class Subgraph:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def _node_dict(node) -> dict[str, Any]:
    props = node.get("properties") or "{}"
    return {"id": node["id"], "name": node["name"], "kind": node["kind"],
            "properties": json.loads(props) if isinstance(props, str) else {}}


def seed(conn: kuzu.Connection, seed_ids: list[str], *, k_hops: int = 1) -> Subgraph:
    """Bounded undirected expansion from seed nodes out to k hops."""
    query = (
        "MATCH (s:Entity)-[r:Rel*1..%d]-(n:Entity) "
        "WHERE list_contains($seeds, s.id) "
        "RETURN DISTINCT n.id, n.name, n.kind, n.properties" % max(1, k_hops)
    )
    sg = Subgraph()
    seen: set[str] = set()
    # Include the seeds themselves.
    seed_res = conn.execute("MATCH (s:Entity) WHERE list_contains($seeds, s.id) "
                            "RETURN s.id, s.name, s.kind, s.properties",
                            parameters={"seeds": seed_ids})
    for row in seed_res:
        nid = row[0]
        if nid not in seen:
            seen.add(nid)
            sg.nodes.append(_node_dict({"id": row[0], "name": row[1],
                                        "kind": row[2], "properties": row[3]}))
    res = conn.execute(query, parameters={"seeds": seed_ids})
    for row in res:
        nid = row[0]
        if nid not in seen:
            seen.add(nid)
            sg.nodes.append(_node_dict({"id": row[0], "name": row[1],
                                        "kind": row[2], "properties": row[3]}))
    # Collect edges among the gathered nodes.
    node_ids = list(seen)
    edge_res = conn.execute(
        "MATCH (a:Entity)-[r:Rel]->(b:Entity) "
        "WHERE list_contains($ids, a.id) AND list_contains($ids, b.id) "
        "RETURN a.id, b.id, r.kind", parameters={"ids": node_ids})
    for row in edge_res:
        sg.edges.append({"from": row[0], "to": row[1], "kind": row[2]})
    return sg


def method_neighborhood(conn: kuzu.Connection, method_id: str) -> dict[str, Any]:
    """Return the 1-hop slice needed to materialize one AnalysisMethod."""
    method_res = [r for r in conn.execute(
        "MATCH (m:Entity {id:$id}) RETURN m.id, m.name, m.kind, m.properties, "
        "m.bioconda_pkg, m.biotools_id", parameters={"id": method_id})]
    if not method_res:
        raise KeyError(method_id)
    r = method_res[0]
    method = {"id": r[0], "name": r[1], "kind": r[2],
              "properties": json.loads(r[3] or "{}"),
              "bioconda_pkg": r[4], "biotools_id": r[5]}

    buckets = {"operations": "PERFORMS", "topics": "HAS_TOPIC", "containers": "PACKAGED_AS"}
    out: dict[str, Any] = {"method": method}
    for key, edge_kind in buckets.items():
        rows = conn.execute(
            "MATCH (m:Entity {id:$id})-[r:Rel {kind:$k}]->(o:Entity) "
            "RETURN o.id, o.name, o.kind, o.properties",
            parameters={"id": method_id, "k": edge_kind})
        out[key] = [_node_dict({"id": x[0], "name": x[1], "kind": x[2], "properties": x[3]})
                    for x in rows]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_extract.py -v`
Expected: PASS (2 tests). If `r:Rel*1..k` variable-length syntax differs in the pinned kuzu
version, consult context7 (`/kuzudb/docs`, query "variable length relationship recursive
MATCH syntax") and adjust the bound syntax; the test assertions stay the same.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/extract/seed.py tests/test_extract.py
git commit -m "feat: add seed-subgraph extraction"
```

---

## Task 8: Adapters (networkx + rag_text)

**Files:**
- Create: `src/methods_graph/extract/adapters.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adapters.py
import networkx as nx
from methods_graph.extract.seed import Subgraph
from methods_graph.extract.adapters import to_networkx, to_rag_text


def _sg():
    sg = Subgraph()
    sg.nodes = [
        {"id": "m:salmon", "name": "salmon", "kind": "Method", "properties": {"version": "1.10.0"}},
        {"id": "op:3798", "name": "Read summarisation", "kind": "Operation", "properties": {}},
    ]
    sg.edges = [{"from": "m:salmon", "to": "op:3798", "kind": "PERFORMS"}]
    return sg


def test_to_networkx_builds_digraph():
    g = to_networkx(_sg())
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == 2
    assert g.nodes["m:salmon"]["kind"] == "Method"
    assert g.edges["m:salmon", "op:3798"]["kind"] == "PERFORMS"


def test_to_rag_text_mentions_method_and_relations():
    txt = to_rag_text(_sg())
    assert "salmon" in txt
    assert "Read summarisation" in txt
    assert "PERFORMS" in txt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/extract/adapters.py
"""Export a Subgraph to NetworkX or to RAG-grounding text."""
from __future__ import annotations

import networkx as nx

from methods_graph.extract.seed import Subgraph


def to_networkx(sg: Subgraph) -> nx.DiGraph:
    g = nx.DiGraph()
    for n in sg.nodes:
        g.add_node(n["id"], name=n["name"], kind=n["kind"], **n.get("properties", {}))
    for e in sg.edges:
        g.add_edge(e["from"], e["to"], kind=e["kind"])
    return g


def to_rag_text(sg: Subgraph) -> str:
    """Render a subgraph as a structured markdown block for LLM grounding."""
    by_id = {n["id"]: n for n in sg.nodes}
    lines: list[str] = ["# Method subgraph", "", "## Entities"]
    for n in sg.nodes:
        props = ", ".join(f"{k}={v}" for k, v in n.get("properties", {}).items() if v)
        suffix = f" ({props})" if props else ""
        lines.append(f"- [{n['kind']}] {n['name']}{suffix}")
    lines += ["", "## Relationships"]
    for e in sg.edges:
        src = by_id.get(e["from"], {}).get("name", e["from"])
        dst = by_id.get(e["to"], {}).get("name", e["to"])
        lines.append(f"- {src} —{e['kind']}→ {dst}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapters.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/extract/adapters.py tests/test_adapters.py
git commit -m "feat: add networkx and rag-text adapters"
```

---

## Task 9: MethodsGraphProvider

The provider is the only quration-aware module. To avoid a hard dependency it maps a method
neighborhood to a plain dict matching the `AnalysisMethod` field names; a helper builds the real
Pydantic object only if quration is importable. MVP implements `get_methods` and
`retrieve_context`; `score_method` returns a neutral 0.0 (Phase 2).

**Files:**
- Create: `src/methods_graph/provider/__init__.py` (empty)
- Create: `src/methods_graph/provider/quration_provider.py`
- Test: `tests/test_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider.py
import kuzu
import pytest
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider

P = Provenance("test", "x", "2026-06-08")


@pytest.fixture
def db_path(tmp_path):
    nodes = [
        MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                     {"version": "1.10.0", "description": "quant", "implementation_type": "nextflow"},
                     P, bioconda_pkg="salmon", biotools_id="salmon"),
        NodeRecord("op:operation_3798", "Read summarisation", NodeKind.OPERATION, {}, P),
        NodeRecord("topic:topic_3170", "RNA-Seq", NodeKind.TOPIC, {}, P),
        NodeRecord("ctr:salmon", "quay.io/biocontainers/salmon:1.10.0", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/salmon:1.10.0"}, P),
    ]
    edges = [
        EdgeRecord("m:salmon", "op:operation_3798", EdgeKind.PERFORMS, {}, P),
        EdgeRecord("m:salmon", "topic:topic_3170", EdgeKind.HAS_TOPIC, {}, P),
        EdgeRecord("m:salmon", "ctr:salmon", EdgeKind.PACKAGED_AS, {}, P),
    ]
    path = tmp_path / "m.kuzu"
    build_graph(nodes, edges, path, staging_dir=tmp_path / "stg")
    return path


def test_get_methods_returns_method_dicts(db_path):
    provider = KuzuMethodsGraphProvider(db_path)
    methods = provider.get_methods()
    salmon = next(m for m in methods if m["name"] == "salmon")
    assert salmon["id"] == "m:salmon"
    assert salmon["implementation_type"] == "nextflow"
    assert "RNA-Seq" in salmon["tags"]
    assert salmon["compute_requirements"]["container_image"].endswith("salmon:1.10.0")


def test_retrieve_context_grounds_on_keywords(db_path):
    provider = KuzuMethodsGraphProvider(db_path)
    ctx = provider.retrieve_context_for_keywords(["salmon"])
    assert "salmon" in ctx
    assert "Read summarisation" in ctx


def test_score_method_is_neutral_in_mvp(db_path):
    provider = KuzuMethodsGraphProvider(db_path)
    assert provider.score_method("m:salmon", keywords=["salmon"]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.provider.quration_provider'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/provider/__init__.py
```

```python
# src/methods_graph/provider/quration_provider.py
"""MethodsGraphProvider: map the methods graph to quration's broker types.

This is the only quration-aware module. It produces AnalysisMethod-shaped dicts so the graph
package has no hard dependency on quration; build_analysis_method() upgrades a dict to a real
quration Pydantic object when quration is installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import kuzu

from methods_graph.extract.adapters import to_rag_text
from methods_graph.extract.seed import seed, method_neighborhood


def _neighborhood_to_method_dict(nb: dict[str, Any]) -> dict[str, Any]:
    m = nb["method"]
    props = m.get("properties", {})
    tags = [o["name"] for o in nb["operations"]] + [t["name"] for t in nb["topics"]]
    containers = nb["containers"]
    compute = {}
    if containers:
        compute["container_image"] = containers[0]["properties"].get(
            "image_name", containers[0]["name"])
    return {
        "id": m["id"],
        "name": m["name"],
        "description": props.get("description", ""),
        "implementation_type": props.get("implementation_type", "tool"),
        "version": props.get("version", ""),
        "repository_url": props.get("homepage") or None,
        "tags": tags,
        "supported_modalities": [t["name"] for t in nb["topics"]],
        "compute_requirements": compute,
        "status": "active",
        "publications": [],
    }


class KuzuMethodsGraphProvider:
    def __init__(self, db_path: Path):
        self._conn = kuzu.Connection(kuzu.Database(str(db_path)))

    def _all_method_ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "MATCH (m:Entity {kind:'Method'}) RETURN m.id")]

    def get_methods(self) -> list[dict[str, Any]]:
        out = []
        for mid in self._all_method_ids():
            out.append(_neighborhood_to_method_dict(method_neighborhood(self._conn, mid)))
        return out

    def retrieve_context_for_keywords(self, keywords: list[str], *, k_hops: int = 1) -> str:
        seeds = self._method_ids_matching(keywords)
        if not seeds:
            return ""
        return to_rag_text(seed(self._conn, seeds, k_hops=k_hops))

    def _method_ids_matching(self, keywords: list[str]) -> list[str]:
        ids: list[str] = []
        for kw in keywords:
            rows = self._conn.execute(
                "MATCH (m:Entity {kind:'Method'}) WHERE contains(lower(m.name), lower($kw)) "
                "RETURN m.id", parameters={"kw": kw})
            ids.extend(r[0] for r in rows)
        return list(dict.fromkeys(ids))

    def score_method(self, method_id: str, *, keywords: list[str]) -> float:
        # Phase 2: graph/EDAM-overlap scoring. MVP returns neutral.
        return 0.0


def build_analysis_method(method_dict: dict[str, Any]):
    """Upgrade a method dict to a quration AnalysisMethod if quration is installed."""
    try:
        from quration.broker.models import AnalysisMethod   # type: ignore
    except ImportError as e:                                 # pragma: no cover
        raise RuntimeError("quration is not installed; install methods-graph[quration]") from e
    return AnalysisMethod(**method_dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_provider.py -v`
Expected: PASS (3 tests). The kuzu string function may be `contains()` or `CONTAINS`
operator depending on the pinned version — if the keyword query errors, switch to
`WHERE lower(m.name) CONTAINS lower($kw)` and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/provider/ tests/test_provider.py
git commit -m "feat: add KuzuMethodsGraphProvider"
```

---

## Task 10: CLI

Wire the stages into a CLI: `build` (run connectors over a sources dir → staging),
`resolve` (staging → canonical), `load` (canonical → Kùzu), `query` (run a seed + print RAG text).

**Files:**
- Create: `src/methods_graph/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path
from methods_graph.cli import cmd_query
from methods_graph.types import MethodRecord, NodeKind, Provenance
from methods_graph.graph.loader import build_graph

P = Provenance("test", "x", "2026-06-08")


def test_cmd_query_prints_rag_text(tmp_path, capsys):
    nodes = [MethodRecord("m:salmon", "salmon", NodeKind.METHOD,
                          {"version": "1.10.0"}, P, bioconda_pkg="salmon")]
    db_path = tmp_path / "m.kuzu"
    build_graph(nodes, [], db_path, staging_dir=tmp_path / "stg")
    cmd_query(db_path=db_path, keywords=["salmon"], k_hops=1)
    out = capsys.readouterr().out
    assert "salmon" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'methods_graph.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/methods_graph/cli.py
"""Command-line entry points for the methods graph pipeline."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider


def _today() -> str:
    return _dt.date.today().isoformat()


def cmd_query(*, db_path: Path, keywords: list[str], k_hops: int) -> None:
    provider = KuzuMethodsGraphProvider(db_path)
    print(provider.retrieve_context_for_keywords(keywords, k_hops=k_hops))


def cmd_methods(*, db_path: Path) -> None:
    provider = KuzuMethodsGraphProvider(db_path)
    print(json.dumps(provider.get_methods(), indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="methods-graph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="seed a subgraph by keyword and print RAG text")
    q.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))
    q.add_argument("--keyword", action="append", dest="keywords", required=True)
    q.add_argument("--hops", type=int, default=1)

    m = sub.add_parser("methods", help="dump all methods as AnalysisMethod-shaped JSON")
    m.add_argument("--db", type=Path, default=Path("data/methods.kuzu"))

    args = parser.parse_args(argv)
    if args.cmd == "query":
        cmd_query(db_path=args.db, keywords=args.keywords, k_hops=args.hops)
    elif args.cmd == "methods":
        cmd_methods(db_path=args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> `build` and `resolve` subcommands that walk a real sources directory are added once the
> directory layout of downloaded EDAM/nf-core/BioContainers snapshots is fixed. The
> integration test (Task 11) exercises the full connector→resolver→loader path directly, so
> CLI wiring for those stages is deferred until a real snapshot dir exists. Note this gap in
> the commit message rather than leaving a silent stub.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/methods_graph/cli.py tests/test_cli.py
git commit -m "feat: add query/methods CLI (build/resolve deferred to real snapshot dir)"
```

---

## Task 11: End-to-end integration test

Exercise the whole pipeline on fixtures: connectors → resolver → loader → provider.

**Files:**
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration.py
import json
from pathlib import Path

from methods_graph.connectors.edam import parse_edam
from methods_graph.connectors.nfcore import parse_module
from methods_graph.connectors.biocontainers import parse_biocontainer
from methods_graph.resolve.resolver import resolve
from methods_graph.graph.loader import build_graph
from methods_graph.provider.quration_provider import KuzuMethodsGraphProvider
from methods_graph.types import NodeKind, MethodRecord

FX = Path(__file__).parent / "fixtures"


def test_full_pipeline_salmon(tmp_path):
    edam_nodes, edam_edges = parse_edam(FX / "edam_sample.tsv", ingested_at="2026-06-08")
    nf_nodes, nf_edges = parse_module(FX / "nfcore" / "salmon_quant", ingested_at="2026-06-08")
    bc_nodes, bc_edges = parse_biocontainer(
        json.loads((FX / "biocontainers_salmon.json").read_text()), ingested_at="2026-06-08")

    method_nodes = [n for n in nf_nodes if isinstance(n, MethodRecord)]
    other_nodes = ([n for n in nf_nodes if not isinstance(n, MethodRecord)]
                   + edam_nodes + bc_nodes)
    src_edges = nf_edges + edam_edges + bc_edges

    nodes, edges = resolve(method_nodes=method_nodes, other_nodes=other_nodes, src_edges=src_edges)

    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")

    provider = KuzuMethodsGraphProvider(db_path)
    methods = provider.get_methods()
    salmon = next(m for m in methods if m["name"] == "salmon")

    # End-to-end assertions spanning all three sources:
    assert "RNA-Seq" in salmon["tags"]                                 # EDAM topic via nf-core ref
    assert salmon["compute_requirements"]["container_image"].endswith("salmon:1.10.0")  # BioContainers
    ctx = provider.retrieve_context_for_keywords(["salmon"])
    assert "Read summarisation" in ctx                                 # EDAM operation in RAG text


def test_pipeline_is_rebuildable(tmp_path):
    nf_nodes, nf_edges = parse_module(FX / "nfcore" / "salmon_quant", ingested_at="2026-06-08")
    method_nodes = [n for n in nf_nodes if isinstance(n, MethodRecord)]
    other = [n for n in nf_nodes if not isinstance(n, MethodRecord)]
    nodes, edges = resolve(method_nodes=method_nodes, other_nodes=other, src_edges=nf_edges)
    db_path = tmp_path / "methods.kuzu"
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")
    build_graph(nodes, edges, db_path, staging_dir=tmp_path / "stg")  # rebuild must not error
    provider = KuzuMethodsGraphProvider(db_path)
    assert any(m["name"] == "salmon" for m in provider.get_methods())
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -v`
Expected: ALL tests pass (Tasks 1–11).

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end pipeline integration test"
```

---

## Self-Review Notes (resolved)

- **Spec coverage:** Sources (T2–T4), staging→resolve→load (T5–T6), deterministic ER + SAME_AS
  candidates (T5), k-hop + method-neighborhood extraction (T7), RAG + networkx adapters (T8),
  provider with `get_methods`+`retrieve_context` (T9), CLI (T10), rebuildable + offline-tested
  pipeline (T11). `score_method` is a neutral stub per the Phase-2 cut line.
- **Deferred (Phase 2, per spec):** ToolUniverse connector, embedding/LLM resolution, `to_pyg`,
  graph scoring, quration broker wiring + benchmark metric. These are intentionally out of this
  plan.
- **Known integration risk flagged inline:** kuzu version-specific syntax (`COPY` empty rels,
  variable-length path bound, `CONTAINS`) — each task that touches it has a verify-and-adjust
  note pointing at context7 `/kuzudb/docs`.
- **Source-snapshot CLI gap:** `build`/`resolve` over a real downloaded-snapshot directory is
  deferred until that directory's layout is fixed; called out in T10 rather than stubbed silently.
