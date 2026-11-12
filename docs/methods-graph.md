# Methods graph and guardrail

**What this is:** the Kuzu methods graph (`data/methods.kuzu`) and the guardrail built on it, as they exist in code and data. Unless marked otherwise, every number was re-measured against the built DB or the code on 2026-09-22.
**Status (2026-09-22):** it works, it is tested, and it is frozen. The DB was built 2026-06-19. The lock last changed 2026-07-10 (`b791d69`), and no guardrail file has changed since `430300a` (2026-07-31). The guardrail is narrow: 806 of 905 methods are `NOT_EVALUABLE`, and exactly one method (`m:deseq2`) can be blocked.
**Read next:** [method-sequencing-benchmark.md](method-sequencing-benchmark.md) (the graph's current job is to be that benchmark's scoring oracle), [BACKLOG.md](BACKLOG.md) (what to fix), [HISTORY.md](HISTORY.md) (why work moved away from the guardrail).

> `mg` in this doc means `alias mg='.venv/bin/python -m methods_graph.cli'` (or
> `.venv/bin/methods-graph`). A bare `mg` on macOS runs `/usr/bin/mg`, an unrelated text
> editor. Agents: shell state does not persist between tool calls, so call
> `.venv/bin/methods-graph` directly. Run every command from the repo root.
>
> Tags: **[DB]** needs `data/methods.kuzu`. **[snap]** needs the graph sources under
> `snapshots/` (`EDAM.tsv`, `modules/`, `biocontainers/`, `biotools/`, `stato.owl`,
> `obi.owl`, `skills/bioclaw/`, `snapshot.json`), all gitignored. **[net]** needs network.
> Nothing in this doc makes paid model calls. "Survey" means the 2026-09-22 fact-gathering pass behind these docs; its scratch scripts are not in the repo.

## Summary

| # | Statement | Kind |
|---|---|---|
| 1 | One Kuzu 0.11.3 file: 19,425 nodes, 32,757 edges, 905 methods. Its hash equals the committed lock, and a rebuild from the local `snapshots/` reproduces it exactly. The hash computation itself sometimes gives a different result (R11, §5). | fact |
| 2 | Coverage is thin where it matters. 415/905 methods have an EDAM operation. 49/905 have typed input Data and 39/905 typed output Data. 7,744 of the 7,880 I/O edges point at Format, not Data. | fact |
| 3 | The committed graph comes from `mg rebuild`, which never loads pipelines. It has 0 Pipeline, DOWNSTREAM_OF, ExecutionSpec and Modality entries, so `suggest` and the modality layer do nothing on it. | fact |
| 4 | The guardrail gates exactly one thing: `m:deseq2` with `replicates_per_group >= 3`. | fact |
| 5 | Keyword resolution silently picks the wrong tool for common names (`salmon` gives `m:biohansel`, `STAR` gives `m:ea-utils`). | fact (defect) |
| 6 | Reproducibility holds only for the snapshots already on this disk. A fresh `mg fetch` cannot reproduce the lock, because the skill library is never fetched. | fact |
| 7 | Work moved from the guardrail to the sequencing benchmark after a corpus evaluation measured 0% recall. That evaluation is recorded outside the repo. | owner decision |
| 8 | Keep, fix or retire the guardrail? | open question ([BACKLOG.md](BACKLOG.md)) |

---

## 1. What it is

- **The graph** is a bioinformatics methods catalog. It joins EDAM (operations, data, formats), nf-core modules, BioContainers, bio.tools, STATO and OBI, plus hand-curated YAML in `src/methods_graph/crosslinks/`. It is stored in one Kuzu database file (`data/methods.kuzu`, 11.6 MB).
- **The evaluability layer** is the curated part: StatisticalMethod, Assumption and Diagnostic nodes. It records which statistical assumptions a method relies on and how to check them.
- **The guardrail** (`src/methods_graph/guardrail.py`) turns that layer, plus integer dataset facts you supply, into a verdict for one method, one skill or a linear chain of methods.
- **Who consumes it:**
  - Fact: `bench/oracle.py` reads the graph to score the [sequencing benchmark](method-sequencing-benchmark.md).
  - Fact: `provider/quration_provider.py` exposes the graph to quration, the original Dogma package/API namespace. quration is not installed here, so that path is untested locally.
  - Open question: is quration/Dogma still a live consumer?

### Where each piece lives

| Path | Role |
|---|---|
| `src/methods_graph/connectors/` | source parsers (EDAM, nf-core modules and pipelines, BioContainers, bio.tools, STATO/OBI, skills) |
| `src/methods_graph/resolve/resolver.py` | union-find on `m:<lowercased name>`, plus SAME_AS candidates |
| `src/methods_graph/crosslinks/*.yaml` | curated PERFORMS, Data I/O, statistics, assumptions, diagnostics, modalities |
| `src/methods_graph/graph/` | Kuzu DDL (`schema.py`) and the Parquet loader (`loader.py`) |
| `src/methods_graph/audit.py` | 26 schema invariants, provenance, id uniqueness, coverage |
| `src/methods_graph/pipeline.py` | `compute_graph_hash`, lock read/write, snapshot verify |
| `src/methods_graph/extract/seed.py` | `method_neighborhood`, `method_preconditions`, the fuzzy `method_ids_matching` |
| `src/methods_graph/guardrail.py` | the verdict engine (pure) plus chain evaluation |
| `src/methods_graph/rules.py` | the same contract read straight from YAML, with no DB (used path only) |
| `src/methods_graph/hook.py` | Claude Code PreToolUse adapter over `rules.py` (not wired anywhere) |
| `src/methods_graph/explain.py`, `planner.py` | `mg explain`, `mg suggest` |
| `src/methods_graph/provider/quration_provider.py` | `KuzuMethodsGraphProvider` |

---

## 2. Schema and what is in the built DB

**Storage (fact):** there is one node table `Entity` and one rel table `Rel` (`src/methods_graph/graph/schema.py:3-26`). A node's or edge's type is a string column `kind`, and its properties are a JSON string. `CALL show_tables()` lists only these two tables.

**Declared vs built (fact):** `types.py` declares 21 node kinds and 20 edge kinds. The built DB has 16 node kinds and 13 edge kinds.
- No code emits Topic, Paper, CITES, HAS_FORMAT or HAS_TOPIC. The EDAM Topic layer was removed (`connectors/edam.py:9-12`).
- Pipeline, ExecutionSpec, Modality, HAS_MODULE, DOWNSTREAM_OF, RUNS_AS and HAS_MODALITY exist in code but only on the `ingest` path (§3).

### Node kinds in `data/methods.kuzu`

Source: `MATCH (n:Entity) RETURN n.kind, count(*) ORDER BY n.kind` (read-only, 2026-09-22).

| Kind | Count | Id prefix | Comes from |
|---|---:|---|---|
| Container | 9,139 | `ctr:` | BioContainers |
| Format | 2,100 | `fmt:` | 612 EDAM, plus 1,488 synthetic `fmt:pat:<ext>` made from nf-core glob patterns |
| Module | 2,038 | `mod:` | nf-core: 1,920 modules + 120 subworkflows (2 share a name with a module) |
| Assay | 1,795 | `obo:` | OBI |
| Data | 949 | `data:` | EDAM |
| Method | 905 | `m:` | nf-core tools, after resolution |
| Package | 804 | `pkg:` | BioContainers |
| Instrument | 607 | `obo:` | OBI |
| Operation | 537 | `op:` | EDAM |
| StatisticalMethod | 207 | `obo:` (203), `stat:` (4) | STATO, curated |
| Material | 157 | `obo:` | OBI |
| StudyDesign | 101 | `obo:` | OBI |
| Assumption | 29 | `assum:` | curated YAML (not STATO) |
| Skill | 28 | `skill:` | BioClaw snapshot |
| Diagnostic | 23 | `diag:` | curated YAML |
| Protocol | 6 | `obo:` | OBI |
| Pipeline, ExecutionSpec, Modality, Topic, Paper | 0 | | not produced by `rebuild` |
| **Total** | **19,425** | | equals `data/methods.lock.json:11` |

### Edge kinds

Source: `MATCH ()-[r:Rel]->() RETURN r.kind, count(*)`. Every endpoint and source split below was re-queried on 2026-09-22 (read-only).

| Edge | From → to | Count | Notes |
|---|---|---:|---|
| FROM_PACKAGE | Container → Package | 9,139 | |
| PACKAGED_AS | Method → Container | 7,684 | 646/905 methods have one |
| IS_A | ontology → same ontology | 4,988 | EDAM 1,179, OBI 3,502, STATO 307 |
| INPUT | Method → Format / Data | 3,945 | 3,868 Format, 77 Data |
| OUTPUT | Method → Format / Data | 3,935 | 3,876 Format, 59 Data |
| WRAPS | Module → Method / Skill → Method | 1,987 | 1,981 from 1,921 modules, 6 from skills |
| PERFORMS | Method → Operation | 920 | 898 from bio.tools, 22 curated |
| REQUIRES_ASSUMPTION | StatisticalMethod → Assumption | 52 | curated |
| AMENABLE_TO | Operation → StatisticalMethod | 49 | curated, on 16 operations |
| CHECKED_BY | Assumption → Diagnostic | 33 | curated |
| USES_STATISTICAL_METHOD | Method → StatisticalMethod | 18 | curated, 12 methods |
| SAME_AS | Method → Method | 5 | resolver, all by shared `biotools_id` |
| ANALYZED_BY | Assay → Method | 2 | curated |
| HAS_MODULE, DOWNSTREAM_OF, RUNS_AS, HAS_MODALITY, HAS_TOPIC, HAS_FORMAT, CITES | | 0 | |
| **Total** | | **32,757** | equals `data/methods.lock.json:10` |

### Identifiers

[../CLAUDE.md](../CLAUDE.md) has the full trap list. In short:
- `m:` + the lowercased method name is exact for all 905 methods, with no collisions.
- `mod:` + the module's `meta.yml` `name` is the module id, never the directory leaf.
- 1,921 of the 2,038 Module nodes WRAP a Method. **All 117 that do not are nf-core subworkflows**, because `rebuild` also ingests the `subworkflows/` tree. Every one of the 1,920 real modules wraps at least one Method.

### Modelling quirks in the built graph (fact; neither audit nor tests catch them)

| Quirk | Evidence | Effect |
|---|---|---|
| A single-tool module is named after its first path segment, so subcommands collapse into one Method | `cli.py:172`, `connectors/nfcore.py:413-420` | `m:gatk4` is wrapped by 65 modules, `m:sentieon` by 22, and `m:custom` by 22 unrelated scripts |
| `m:sentieon` carries `biotools_id: rsem` | `snapshots/modules/modules/nf-core/sentieon/rsemcalculateexpression/meta.yml:16` | wrong `SAME_AS m:rsem → m:sentieon`; sentieon's only operation is RNA-Seq quantification |
| The resolver keeps one member's properties per method | `resolve/resolver.py:179-192` | `m:star` has `tool_label: starsolo` |
| A multi-tool `meta.yml` becomes several WRAPS edges | query on `mod:homer_maketagdirectory` | that module "wraps" `m:deseq2`, `m:edger`, `m:homer` and `m:samtools`, which affects every `mod:`→`m:` projection, the benchmark's included |
| The LinkML schema lags the code | `src/methods_graph/schema/methods_graph.yaml` | no ExecutionSpec, Modality or Skill classes. It is not the source of the Kuzu DDL. |
| The KGX export writes raw kind strings, not biolink terms, and drops properties | `kgx.py:63-104` | `export-kgx` output is not biolink-valid |

---

## 3. Two build paths make two different graphs

Both paths call the same `cmd_build` (`cli.py:70`), with different inputs.

| | `mg rebuild` (= `make rebuild`) | `mg ingest --manifest <yaml>` |
|---|---|---|
| Needs | [snap], `rdflib` (the `dev`/`ontology` extra, not a base dependency) | [net], Nextflow, Java, shared snapshots |
| nf-core input | the whole `snapshots/modules` clone, subworkflows included | each pipeline's own vendored modules, version-matched |
| `--nfcore-pipelines` | **never passed** (`cli.py:826-837`) | passed |
| Pipeline, HAS_MODULE | no | yes |
| DOWNSTREAM_OF | no | yes when `wiring: true` (the default; `ingest.example.yaml`). No for `catalog.ingest.yaml`, which sets `wiring: false`. |
| ExecutionSpec, RUNS_AS | no | yes |
| Modality, HAS_MODALITY | no. All 97 curated pipeline→modality mappings are skipped. | yes, for pipelines present |
| Skill nodes | yes, 28 from `snapshots/skills/bioclaw` | **no**: ingest has no skills source (`ingest.py:23-29`) |
| Lock written | `data/methods.lock.json` (committed) | `<dest>/ingest.lock.json` |
| Exists in this checkout | yes: `data/methods.kuzu`, built 2026-06-19 | no. `data/catalog.kuzu`, the target named in `catalog.ingest.yaml`, is absent. |

- Fact: the 97 skipped modality mappings are logged only at INFO level (`cli.py:527`), so default CLI output does not show them. Verified with a scratch rebuild at INFO level: `modalities: skipped 97 (pipeline not present)`.
- Fact: `catalog.ingest.yaml` pins 96 pipelines. `ingest.example.yaml` pins one (rnaseq 3.14.0, `nxf_ver: "23.10.0"`).
- Unverified (needs [net]): the owner's notes say that an old `NXF_VER` pin breaks the locally installed Nextflow 26.04.3 launcher and silently falls back to I/O-inferred wiring.
- Open question: which DB is canonical? The owner's notes mention a "production DB (21,273 nodes) built via mg ingest", but no such DB exists here. `bench-runs/2026-08-08-pilot/ingest.lock.json` shows that an ingest ran for the benchmark pilot. That lock names its DB as a session scratch path (`/private/tmp/claude-501/…/scratchpad/scale.kuzu`) that no longer exists, and records a failed audit (`invariants_passed: 25` of 26, `ok: false`; 16,465 nodes, 12 Pipeline nodes).

### Build order inside `cmd_build`

connectors → `merge_downstream_of` → resolver → bio.tools PERFORMS enrichment → curated PERFORMS add/remove → curated Data I/O → skills → execution specs (only when pipelines are passed) → curated statistics layer (USES, REQUIRES_ASSUMPTION, AMENABLE_TO, CHECKED_BY, ANALYZED_BY) → modalities → Parquet → Kuzu `COPY`. `rebuild` then runs the audit gate, computes the hash and writes the lock.

The build summary line from the 2026-09-22 scratch rebuild ties the edge counts together:

```
Built graph: 905 methods, 19425 nodes, 32757 edges loaded (45 dangling dropped), 916 bio.tools edges added,
2925 ontology nodes, 18 stat-method links, 52 assumption links, 49 amenable-stat links, curated PERFORMS (+22/-10),
74 data-typed I/O edges, 23 diagnostics, 2 assay->method links -> ...
```

For example, the 916 bio.tools PERFORMS edges, minus 8 dangling and minus 10 curated removals, give the 898 in the DB.

---

## 4. Coverage, with denominators

The denominator is 905 methods unless stated. Sources: `mg audit --db data/methods.kuzu` coverage block (= `data/methods.lock.json:13-69`), plus read-only queries for the Data rows.

| Attribute | Methods | % of 905 |
|---|---:|---:|
| any INPUT/OUTPUT edge (`with_io_contract`, almost all to Format) | 901 | 99.6 |
| `bioconda_pkg` | 745 | 82.3 |
| container (PACKAGED_AS) | 646 | 71.4 |
| `biotools_id` | 450 | 49.7 |
| EDAM operation (PERFORMS) | 415 | 45.9 |
| any assumption with a diagnostic (`with_checked_assumption`) | 99 | 10.9 |
| … through an operation, the amenable path (`with_checked_via_operation`) | 94 | 10.4 |
| typed input **Data** | 49 | 5.4 |
| typed output **Data** | 39 | 4.3 |
| USES_STATISTICAL_METHOD, the used path (`with_statistical_method`) | 12 | 1.3 |
| can reach `FACTS_REQUIRED` or `BLOCKED` in the guardrail | 1 | 0.1 |

Edge-level I/O: 7,880 INPUT+OUTPUT edges, of which 7,744 point at Format and 136 at Data. Chain handoffs and the benchmark oracle read **Data only** (`guardrail.py:264-266`, `bench/oracle.py:116-122`), so the usable I/O coverage is 136 edges, not 7,880.

Of the 99 methods with any assumption, 87 have it only through the amenable path, 5 only through the used path, and 7 through both.

---

## 5. Reproducibility

### What `rebuild --check` proves (fact)

- It proves that **the current code plus the `snapshots/` on this disk** reproduce the committed `graph_hash` (`sha256:c6940e39…`, `data/methods.lock.json:70`). Re-checked on 2026-09-22: exit 0, about 14 s wall time.
- The hash covers each node's `id, name, kind, properties, bioconda_pkg, biotools_id` and each edge's `from, to, kind, properties`. It excludes `source`, `source_url` and `ingested_at` (`pipeline.py:16-28`).
- Before building, `verify` checks 4 pins: the sha256 of EDAM, STATO and OBI, and the git commit of `nfcore_modules`. It skips 3 sources (biocontainers, biotools, and nfcore_pipelines, which is null). Skills are not in `snapshot.json` at all.

Safe recipe [snap]. It builds into `/tmp` and compares against a copy of the lock. `make rebuild-check` instead **overwrites `data/methods.kuzu`**, leaving only the lock alone (`Makefile:19-20`).

```bash
rm -rf /tmp/mg-rebuild && mkdir -p /tmp/mg-rebuild && cp data/methods.lock.json /tmp/mg-rebuild/ \
  && mg rebuild --db /tmp/mg-rebuild/methods.kuzu --snapshots snapshots --check
```

```
build_graph: dropped 45 dangling edge(s) whose endpoints are not in the node set
verify: 4 pinned source(s) match snapshot.json (edam, nfcore_modules, obi, stato); 3 unhashed source(s) skipped
Built graph: 905 methods, 19425 nodes, 32757 edges loaded (45 dangling dropped), ...
--check: graph hash matches committed lock (sha256:c6940e39883fb7aa...)
```

No CLI command checks the existing DB against the lock without a rebuild. This one-liner does it [DB]:

```bash
.venv/bin/python -c "import kuzu; from methods_graph.pipeline import compute_graph_hash; c=kuzu.Connection(kuzu.Database('data/methods.kuzu', read_only=True)); print(compute_graph_hash(c))"
```

Caveat (R11): on the unchanged DB this printed a different hash in some runs. Rerun it before you conclude that the DB differs from the lock.

### Every known gap

The R numbers here are local to this doc; [BACKLOG.md](BACKLOG.md) uses its own IDs. R1, R2, R3 → BACKLOG M2; R4 → M1; R5, R6 → M7; R7 → M6; R8 → M9; R9 → M8; R10 → R9 (a `CLAUDE.md` wording item); R11 → M21.

| # | Gap | Evidence | Consequence |
|---|---|---|---|
| R1 | `fetch` replays none of the lock's pins. nf-core/modules is shallow-cloned at the default branch with no ref, and an existing clone is reused untouched. | `fetch.py:366-372` | a fresh fetch builds from whatever upstream HEAD is |
| R2 | EDAM, STATO and OBI come from unversioned "latest" URLs. The lock records a sha256 for each, plus a version IRI for STATO and OBI and a Last-Modified date for EDAM (`data/methods.lock.json:76-90`), but fetch ignores all of them. | `fetch.py:294, 657, 697` | these can drift silently too |
| R3 | BioContainers and bio.tools are live APIs. The lock has `{}` for both. | `data/methods.lock.json:74-75` | unpinned: 809 BioContainers records (20 failed) and 420 bio.tools records (30 failed) in the 2026-06-18 snapshot |
| R4 | **The skill library is never fetched.** `rebuild` passes `snapshots/skills/bioclaw` without the existence check the other sources get. A missing directory silently gives 0 Skill nodes. | `cli.py:833` vs `cli.py:113-127`. Re-run 2026-09-22 without skills: `19397 nodes, 32751 edges`, `--check: graph hash MISMATCH`, exit 1, and no warning. | the weekly CI drift step (fresh fetch, then `rebuild --check`) **cannot pass even if upstream never moves**. CI's determinism step still passes, because both of its builds lack skills. |
| R5 | 45 dangling edges are dropped on every build: 14 nf-core INPUT, 23 nf-core OUTPUT and 8 bio.tools PERFORMS. They point at 23 distinct EDAM ids that are not graph nodes. 17 are absent from the 2023-05-08 EDAM snapshot, 2 of them malformed (`fmt:format_25722`, `fmt:format_3752:latest`). The other 6 (1 Data, 5 Operation) are marked obsolete there, and the EDAM connector skips obsolete terms (`connectors/edam.py:52-55`). | `graph/loader.py:59-67`; re-run 2026-09-22 with the loader patched to list the dropped edges | counted only in a WARNING and the summary line, not in the lock or the audit. This arguably breaks "nothing dropped silently". |
| R6 | 11 of 39 BioClaw `SKILL.md` files have no YAML frontmatter, so no `name`, and are skipped with no count or log | `connectors/skills.py:66-69` | 28 Skill nodes, not 39 |
| R7 | `mg audit --snapshot snapshots` exits 1 on a Format mismatch: EDAM has 612 Format terms, the graph has 2,100 Format nodes (the 1,488 `fmt:pat:` nodes are the difference) | `audit.py:793` counts every Format node. The rebuild and ingest gates call `audit_graph(conn)` without a snapshot (`cli.py:656, 842`). | never gates anything, but it is a permanently red check |
| R8 | `mg fetch` rewrites `snapshot.json` wholesale. A `--no-<source>` run writes `<source>: null` and loses that pin. | `fetch.py:236-251` | partial re-fetches erase pins |
| R9 | No end-to-end test of `rebuild` or `--check` exists. `tests/test_cli_rebuild.py` has only two `--diff-only` tests. | `grep -n 'def test' tests/test_cli_rebuild.py` | the only enforcement is the weekly CI job, which starts from a fresh fetch and so hits R4 |
| R10 | `mg audit` reads the existing DB. It does not see code or YAML changes until you rebuild. | `cli.py:712` | CLAUDE.md's "run `mg audit` after touching connectors" checks the old graph unless you rebuild first |
| R11 | **The graph hash is not stable run to run.** `compute_graph_hash` relies on Kuzu's `ORDER BY`, which sometimes returned the edge rows out of order. The rows were the same 32,757, but one block was misplaced (`m:windowmasker` followed by `m:2fast2q`). | `pipeline.py:24-28, 49-54`. On 2026-09-22 the unchanged `data/methods.kuzu` hashed to something other than `sha256:c6940e39…` (for example `sha256:e303b738…`) in 6 of 92 runs of this function. Kuzu 0.11.3, macOS, 10 cores. | the one-liner above, `rebuild --check` and CI's determinism step all call this function, so each can report a false mismatch. A rerun usually clears it. Fix tracked as [BACKLOG.md](BACKLOG.md) M21. |

Audit caveat (fact): plain `mg audit` passes all 26 invariants, but 9 of them pass vacuously because this graph has none of the edges they check: RUNS_AS, HAS_MODULE, HAS_MODALITY, "Pipeline has ≥1 HAS_MODULE", "ExecutionSpec has a container", and four DOWNSTREAM_OF checks.

The weekly `rebuild-verify` CI job (`.github/workflows/ci.yml`) is described in [ARCHITECTURE.md](ARCHITECTURE.md). Its comment block names R1 and R3 but not R2 or R4.

---

## 6. The guardrail

### 6.1 Verdicts and exit codes (fact)

| Status | Exit | Meaning | Source |
|---|---:|---|---|
| `EVALUABLE` | 0 | every gate passed or needs only manual review | `guardrail.py:23`, `cli.py:1164-1165` |
| `BLOCKED` | 3 | a pre-run gate FAILed | |
| `NOT_EVALUABLE` | 4 | no assumptions for this method, unknown id, or no keyword match | |
| `FACTS_REQUIRED` | 5 | a gate exists but its fact was not supplied. Fail-closed since `8477b28`. | |
| (argparse error) | 2 | | |

Per-gate results are `PASS`, `FAIL`, `INSUFFICIENT_INFO` and `REQUIRES_REVIEW`. The status is `BLOCKED` if any gate FAILs, else `FACTS_REQUIRED` if any is INSUFFICIENT_INFO, else `EVALUABLE` (`guardrail.py:168-171`). `REQUIRES_REVIEW` and post-run checks never change the status.

### 6.2 Where a method's contract comes from: used and amenable paths

A contract is the method's `method_preconditions`: its assumptions, diagnostics and thresholds. It reaches a method along two paths:

| Path | Graph walk | Methods reached | Can gate? |
|---|---|---:|---|
| **used** | Method -USES_STATISTICAL_METHOD→ Stat -REQUIRES_ASSUMPTION→ Assumption -CHECKED_BY→ Diagnostic | 12 | yes, when a pre-run diagnostic carries a numeric threshold scoped to that assumption |
| **amenable** | Method -PERFORMS→ Operation -AMENABLE_TO→ Stat → … | 94 | **never**: it becomes `REQUIRES_REVIEW`, even with a threshold (`guardrail.py:96-100`) |

- Decision (in code and commit `8477b28`, merged in `529ffc5`): AMENABLE_TO records statistics that can run *downstream* of a tool's output, so it must never gate the tool. Before this fix, the pre-fix code at `849a071` BLOCKed 23 methods under starved facts on this same DB, including salmon, kallisto, cellbender and trust4. The fix also made a diagnostic's threshold attach only to its `applies_to_assumption` (`extract/seed.py:338-353`). The 23 → 1 figure was re-run on 2026-09-22: `849a071`'s `src/` (extracted with `git archive`) against this DB.
- There are two contract readers:
  - **Graph path:** `extract/seed.py::method_preconditions`, behind `KuzuMethodsGraphProvider`. It follows both paths and needs [DB].
  - **Portable path:** `rules.py`. It reads three crosslinks YAMLs directly, follows the used path only, needs no DB, and knows exactly 12 methods (anota2seq, deseq2, edger, gsea, kallisto, limma, maxquant, plink, plink2, sageproteomics, salmon, scanpy). It raises `KeyError` for anything else.

### 6.3 What actually gates: exactly one method

- The curation has two numeric floors: `min_replicates_per_group: 3` on `diag:sample_size_power_check` (scoped to `asymptotic_normality`, `crosslinks/assumption_diagnostics.yaml:34-42`) and `min_peptides_per_protein: 2` (`:163-164`).
- Only the replicate floor reaches any method on the used path, and only one method: `m:deseq2`, through Wald test → asymptotic normality. The peptide floor reaches methods only on the amenable path, so it never gates.
- The engine also supports presence predicates (`requires: {fact: true}`, `guardrail.py:123-143`), but nothing curates them. `rules.py:36-38` says "not yet curated", and `--fact` accepts only integers ≥ 1 (`cli.py:1531-1546`), so a false value cannot be passed from the CLI.
- `tests/test_guardrail_precision.py:60` pins `GATEABLE = {"m:deseq2"}`. That test is DB-gated, so CI skips it.

### 6.4 Reach over all 905 methods [DB]

Source: every method id through `provider.method_preconditions` and `evaluate_preconditions`, re-run 2026-09-22 (scratch script; the survey's independent tally agrees).

| Facts supplied | EVALUABLE | FACTS_REQUIRED | BLOCKED | NOT_EVALUABLE |
|---|---:|---:|---:|---:|
| none | 98 | 1 (`m:deseq2`) | 0 | 806 |
| starved (`replicates_per_group=1`, `peptides_per_protein=1`) | 98 | 0 | 1 (`m:deseq2`) | 806 |
| pre-fix code at `849a071`, starved (re-run 2026-09-22) | 76 | n/a | 23 | 806 |

`m:limma` and `m:edger` are EVALUABLE at `replicates_per_group=1`. `m:limma`'s only replicate floor is on the amenable path. `m:edger` has no replicate floor on either path (`mg explain --method m:edger`). Fact: closing this needs curated USES links, not code (`hook.py:33-40` records why they were removed from the hook). Open question: curate them?

### 6.5 Walkthrough with real output [DB]

```bash
mg guardrail --method m:deseq2                                # exit 5
```

```
FACTS_REQUIRED  (m:deseq2)
  facts needed: replicates_per_group (pass via --fact key=value)
  [INSUFFICIENT_INFO] asymptotic (large-sample) normality — replicates_per_group supplied=None >= 3?
  [REQUIRES_REVIEW] independence of observations — manual check
  [REQUIRES_REVIEW] large variance corresponds to structure — manual check
  [POST-RUN] homoscedasticity (homogeneity of variance) — run: diag:levene_test, diag:residual_vs_fitted_plot
  [POST-RUN] independence or positive regression dependence (PRDS) — run: diag:pvalue_histogram
  [POST-RUN] linearity — run: diag:residual_vs_fitted_plot, diag:scatter_plot
  [POST-RUN] normality — run: diag:qq_plot, diag:shapiro_wilk
```

| Command | First line | Exit |
|---|---|---:|
| `mg guardrail --method m:deseq2 --fact replicates_per_group=2` | `BLOCKED  (m:deseq2)` with `[FAIL] … supplied=2 >= 3?` | 3 |
| `mg guardrail --method m:deseq2 --fact replicates_per_group=3` | `EVALUABLE  (m:deseq2)` with `[PASS] …` | 0 |
| `mg guardrail --method m:limma --fact replicates_per_group=1` | `EVALUABLE  (m:limma)`, all gates `[REQUIRES_REVIEW]` | 0 |
| `mg guardrail --method m:star` | `NOT_EVALUABLE  (m:star)`, `refusal: no evaluability coverage for this method` | 4 |
| `mg guardrail --analysis salmon` | `EVALUABLE  (m:biohansel)`, **the wrong tool** (defect G1) | 0 |
| `mg guardrail --analysis STAR` | `NOT_EVALUABLE  (m:ea-utils)`, **the wrong tool** | 4 |

Add `--json` for the full verdict. Use `m:` ids. Do not pass keywords.

### 6.6 `guardrail-chain`, and why most chains are UNKNOWN or NOT_EVALUABLE [DB]

- Each step is evaluated alone, and the dataset facts apply to every step.
- Handoffs compare **consecutive** steps only (`zip`, `guardrail.py:303`), on **Data** nodes only.
  - `VALID`: a Data id is shared.
  - `BROKEN`: both sides have Data I/O, but none is shared.
  - `UNKNOWN`: either side lacks Data I/O. UNKNOWN never blocks.
- Chain precedence: `BLOCKED` (any step BLOCKED or any handoff BROKEN) > `NOT_EVALUABLE` > `FACTS_REQUIRED` > `EVALUABLE` (`guardrail.py:307-319`).

Why UNKNOWN dominates (fact, measured 2026-09-22):
- I/O lookup is **skipped for any NOT_EVALUABLE step** (`guardrail.py:295`). 42 methods have curated Data I/O but no assumptions, among them `m:star`, `m:fastqc`, `m:hisat2`, `m:bwa` and `m:samtools`. Their handoffs are always UNKNOWN.
- A handoff can be VALID or BROKEN only when the producer is one of **12** methods (evaluable with output Data) and the consumer one of **15** (evaluable with input Data).

| Chain | Result | Exit |
|---|---|---:|
| `--step m:fastqc --step m:star --step m:subread --step m:deseq2 --fact replicates_per_group=3` (featureCounts ships in `m:subread`; `m:featurecounts` is not a node) | `CHAIN: NOT_EVALUABLE`, 3 UNKNOWN handoffs | 4 |
| `--step m:fastqc --step m:star --step m:salmon --step m:deseq2` (the example in the root README as committed at HEAD) | `CHAIN: NOT_EVALUABLE` | 4 |
| `--step m:salmon --step m:tximeta --step m:deseq2 --fact replicates_per_group=3` | `CHAIN: EVALUABLE`, both handoffs `VALID via data:data_3917` | 0 |
| same, no facts | `CHAIN: FACTS_REQUIRED` | 5 |
| `--step m:tximeta --step m:salmon` | `CHAIN: BLOCKED` (BROKEN handoff) | 3 |
| `--step salmon --step tximeta --step deseq2 --fact replicates_per_group=3` (keywords) | `CHAIN: EVALUABLE`, with step 1 resolved to **`m:biohansel`** | 0 |

The sequencing benchmark switched to reachability instead of consecutive pairs for exactly this reason. The chain evaluator was never updated to match (`bench/score.py:222-248` vs `guardrail.py:303`). The design specs record the chain evaluator as linear-only; those specs live only on the `master` branch (§9).

### 6.7 `explain` [DB]

```bash
mg explain --method m:deseq2      # exit 0; 10 grounded assumptions
mg explain --method m:bogus       # "unknown method: m:bogus", exit 4
```

- Each trace prints the assumption, its `via` (a statistical method or an operation), the `source` (`used` or `amenable`), the evidence token and the source YAML.
- Defect G5: it prints thresholds on amenable assumptions without saying they do not gate. For example, `m:limma` shows `[pre_run {'min_replicates_per_group': 3}] … (source=amenable)`, yet limma is EVALUABLE at n=1.

### 6.8 Skills [DB]

```bash
mg skills --coverage
```

```
{ "skills": 28, "wired_to_method": 6, "guardrail_evaluable": 3, "honest_gaps": 25 }
```

- 28 `skill:bioclaw/<name>` nodes come from `snapshots/skills/bioclaw`. The snapshot has 39 `SKILL.md` files, and 11 are skipped without a count (R6).
- Decision (in code, `connectors/skills.py:24-32, 151-159`): only **declared** tools (`primary_tool` plus frontmatter dependencies) create a Skill -WRAPS→ Method edge. Tools mined from prose go in the `context_tools` property and never gate.
- The 6 wired skills: atac-seq → `m:macs3`, chip-seq → `m:macs3`, differential-expression → `m:deseq2`, metagenomics → `m:kraken2`, proteomics → `m:openms`, scrna-preprocessing-clustering → `m:scanpy`.
- A skill's verdict max-merges its wrapped methods' contracts by (assumption id, source) (`guardrail.py:179-225`):
  - `mg guardrail --skill skill:bioclaw/differential-expression --fact replicates_per_group=2` gives `BLOCKED`, exit 3.
  - `--skill skill:bioclaw/cell-annotation` gives `NOT_EVALUABLE` ("skill wraps no evaluable method"), exit 4.
- Not pinned anywhere (R4). `rebuild` hardcodes `bioclaw`. No K-Dense snapshot exists.

### 6.9 `suggest` (planner): inert on this DB [DB]

- `planner.py` ranks next steps by how many pipelines attest a DOWNSTREAM_OF edge, and entry steps by how many pipelines start with a module. This DB has 0 Pipeline nodes and 0 DOWNSTREAM_OF edges, so:
  - `mg suggest --have mod:salmon_quant` prints `[]`.
  - `mg suggest --have data:data_3917 --limit 3` returns entries all ranked `{"kind": "entry", "count": 0}`, with `why: "0 pipeline(s) start with …"`. With every count at 0, the order is by module id in byte order, so `mod:SCANPY_HASHSOLO` comes first (`planner.py:120`).
- Open question: is the planner still wanted? It needs an ingest-built DB (§3).

### 6.10 `hook.py`: written, not wired

- It is a Claude Code PreToolUse adapter. On a `Bash` command it detects `m:deseq2` (regex `deseq2?` with alphanumeric boundaries, `hook.py:41-44`). Then it counts the smallest experimental arm from a samplesheet at the workspace root or one directory down, skipping `test/`, `tests/` and `fixtures/`, and runs the **rules.py** contract.
- It denies on `BLOCKED`, asks on `FACTS_REQUIRED` (no samplesheet found), and is otherwise silent. It needs no DB.
- Fact: not wired. `.claude/` is gitignored, and the local `.claude/settings.local.json` holds only permissions. The docstring's command `python -m methods_graph.hook` (`hook.py:6`) assumes a `python` that is not on PATH; use `.venv/bin/python`.

Exercise it by hand (no DB):

```bash
W=$(mktemp -d) && printf 'sample,condition\na,ctrl\nb,ctrl\nc,trt\nd,trt\n' > "$W/samplesheet.csv"
printf '{"tool_name":"Bash","tool_input":{"command":"ls results/deseq2/"},"cwd":"%s"}' "$W" \
  | .venv/bin/python -m methods_graph.hook
```

```
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
 "methods-graph: BLOCKED for m:deseq2\n  observed replicates_per_group=2 (read from samplesheet)\n  [FAIL] asymptotic
 (large-sample) normality \u2014 needs replicates_per_group >= 3, got 2\n      basis: doi:10.1261/rna.053959.115"}}
```

That is a false deny: `ls` runs nothing (defect G2).

### 6.11 Provider and quration

- `KuzuMethodsGraphProvider` exposes `resolve_method_ids`, `neighborhood`, `method_preconditions`, `skill_wraps_method_ids`, `resolve_skill_ids`, `skill_preconditions`, `get_methods` and `retrieve_context`.
- `resolve_method_ids` is the fuzzy resolver. Its docstring says quration takes `ids[0]`, so quration inherits defect G1.
- `get_methods()` always emits `category='custom'` and `supported_modalities=[]` (`quration_provider.py:20-23, 91, 99`). The `build_analysis_method` docstring (`:247`) claims otherwise.
- quration is not installed, so `tests/test_provider.py:174` always skips.
- `examples/causal_evaluability_demo.py` runs self-contained. Its "GUARDRAIL" section is the workflow validator (`workflow/validator.py`), not `guardrail.py`.

---

## 7. Known defects

All are facts, verified on 2026-09-22 unless marked "survey". None is fixed. Priorities live in [BACKLOG.md](BACKLOG.md). The G numbers here are local to this doc and differ from BACKLOG's: G1 → BACKLOG G3; G2 → G10; G3 → G5; G4 → G11; G5 → G6; G6 → G4; G7 → G15; G8 → G9; G9 → G7.

### Guardrail

| # | Defect | Evidence | Effect |
|---|---|---|---|
| G1 | **Fuzzy keyword resolution takes `ids[0]` silently.** `--analysis` and chain steps without `m:` go through `method_ids_matching`, a substring match on name **or properties JSON**, ordered by id. | `guardrail.py:269-273, 357-360`; `extract/seed.py:86-111`. `salmon` matches biohansel's "Subtype *Salmon*ella…" description and sorts first. `STAR` matches ea-utils' "*star*t/stop codons". | a verdict for the wrong tool, reported as EVALUABLE. [../CLAUDE.md](../CLAUDE.md) forbids this resolver for normalization. `bench/normalize.py` has the exact `m:<lower(name)>` lookup. |
| G2 | **The hook false-denies any command that mentions DESeq2.** `ls results/deseq2/` and `grep -n DESeq2 README.md` are denied when a 2-per-arm samplesheet exists, and "ask" when none exists. `pip install pydeseq2` is silent. | reproduced above; `hook.py:15-16` claims it "can never block unrelated work". No test in `tests/test_hook.py` covers it. | blocks harmless work if the hook is ever wired |
| G3 | **The graph and rules paths cite different evidence for the same gate.** `mg guardrail` cites `url:https://www.statlect.com/fundamentals-of-statistics/Wald-test` (the assumption link). `rules.py` and the hook cite `doi:10.1261/rna.053959.115` (the threshold's `ref`). | `mg guardrail --method m:deseq2 --fact replicates_per_group=2 --json`; `rules.py:20-24, 165-167`; `extract/seed.py:317-321` | the parity test (`tests/test_rules.py:155-177`) compares status only, so this is invisible to it |
| G4 | **"facts needed" prints even when the fact was supplied.** `required_facts` lists the facts a gate needs, not the missing ones. | `cli.py:1554-1556`; the §6.5 `--fact replicates_per_group=2` (BLOCKED) and `=3` (EVALUABLE) runs both print `facts needed: replicates_per_group` | misleads a reader into thinking the fact was not received |
| G5 | `explain` shows amenable-path thresholds with no "does not gate" marker | `explain.py:57-67, 80-85`; `mg explain --method m:limma` | overstates what is enforced |
| G6 | Chain handoffs use consecutive pairs and skip NOT_EVALUABLE steps' I/O | `guardrail.py:295, 303` | most real chains give UNKNOWN or NOT_EVALUABLE (§6.6) |
| G7 | The `guardrail` help text and a test docstring list 3 verdicts, not 4 | `mg --help` describes `guardrail` as "-> verdict (EVALUABLE / BLOCKED / NOT_EVALUABLE)"; `tests/test_cli_guardrail.py:4` | exit 5 is undocumented at the point of use |
| G8 | `--fact` accepts only integers ≥ 1 | `cli.py:1531-1546` | presence predicates cannot be supplied as false |
| G9 | Determinism gaps: `seed()` and `provider._all_method_ids` run Cypher without `ORDER BY`. `guardrail --json`, `guardrail-chain --json`, `suggest` and `skills --coverage` write JSON without `sort_keys`. | `extract/seed.py:48-79`; `quration_provider.py:128-129`; `cli.py:67, 1158, 1576, 1603` | violates the invariant in [../CLAUDE.md](../CLAUDE.md) |

### Graph and build

The graph-and-build defects are R1–R11 in §5 and the modelling quirks in §2.

---

## 8. Tests and what CI actually enforces

| Scope | With DB (local) | Without DB (what CI sees) |
|---|---|---|
| Full suite (1,014 tests, 71 files) | 1013 passed, 1 skipped (quration) | 981 passed, 33 skipped |
| Guardrail area, 9 files (`test_cli_guardrail`, `test_provider`, `test_guardrail_precision`, `test_explain`, `test_rules`, `test_skills_connector`, `test_guardrail`, `test_hook`, `test_planner`) | 146 passed, 1 skipped (quration) | **118 passed, 29 skipped** |

- Both guardrail-area rows were re-run on 2026-09-22. The "without DB" run used a scratch cwd with `--rootdir` pointing at the repo. The full-suite rows are the canonical figures in [README.md](README.md).
- **Skipped in CI:** all of `test_cli_guardrail.py` (10), 7 DB tests in `test_provider.py`, all of `test_guardrail_precision.py` (4, including the `GATEABLE = {"m:deseq2"}` pin), `test_explain.py` (3), the rules-vs-graph parity test (3), and 1 in `test_skills_connector.py`. CI enforces none of these.
- **Not tested anywhere:** `rebuild` end to end (R9), the hook's mention-only false deny (G2), evidence parity between paths (G3), and the 11 skipped SKILL.md files (R6).
- CI runs `pytest -q` on Python 3.12. The local venv is 3.14.6. See [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 9. How it got here, briefly

Full timeline in [HISTORY.md](HISTORY.md).

| Date | Commit | Event |
|---|---|---|
| 2026-06-08 … 06-19 | local `master` | graph, AMENABLE_TO layer, guardrail CLI (`64a207e`), chain (`8678b57`), skills (`a84afa8..1db3a13`), `explain` (`067f7e9`). The DB was built 2026-06-19. |
| 2026-07-10 | `b791d69` | public-release squash; `main` starts here. Lock and crosslinks are unchanged since then. |
| 2026-07-30 | `8477b28` | precision fix (blockable 23 → 1), `FACTS_REQUIRED`, `rules.py`, `hook.py`, benchmark spec |
| 2026-07-31 | `430300a`, `529ffc5` | hook/rules fixes; merge "guardrail hardening + benchmark gold build". This is the last guardrail change. |

- Owner decision, recorded outside the repo and not reproducible here: a corpus evaluation found 0% guardrail recall on expert-labelled enrichment-analysis failures. The owner's notes point to the Ziemann lab's SurveyEnrichmentMethods data. The failures were things like a wrong background gene set or missing multiple-testing correction, which no `min_<x> >= n` gate can express. The owner kept the graph, as the benchmark's scoring oracle, rather than delete it.
  - The only in-repo trace is a test comment, `tests/test_guardrail.py:346-351`.
  - See [decisions/README.md](decisions/README.md).
- Fact: `main` and the local `master` branch share no history. The June design specs for the graph, reproducible pipeline, guardrail CLI, chain evaluator, skills and planner exist **only on `master`**, whose upstream is gone. `connectors/skills.py:3` cites one of them by a path that does not exist on `main`.

---

## 10. Open questions

Each is listed with its owner-facing framing in [BACKLOG.md](BACKLOG.md) or [decisions/README.md](decisions/README.md). None is settled.

1. **Keep, fix or retire the guardrail?** It gates one method. The root README still calls the repo Dogma's "guardrail substrate" and "methodological leash" (`README.md:3-10`).
2. **Which DB is canonical?** The `rebuild` graph (committed lock, no pipeline layer) or an `ingest` graph (pipeline layer, no skills, none present)?
3. **Skills:** add a pinned fetch plus an existence guard, or drop skills from `rebuild`? Until then, R4 keeps the CI drift step red.
4. **Keyword resolution (G1):** switch to the exact `m:` lookup from `bench/normalize.py`, or refuse ambiguous input?
5. **limma/edgeR:** curate used-path USES links so they get a replicate floor?
6. **Presence predicates:** curate `requires` gates, which could express the real enrichment failure modes, and let `--fact` take false?
7. **Format audit (R7):** count only `fmt:format_` nodes, or accept a permanently failing `--snapshot` audit?
8. **Subworkflows:** keep ingesting `subworkflows/` as Module nodes (the 117 non-wrapping modules), or point `rebuild` at `modules/nf-core` only?
9. **Directory collapse:** split `m:gatk4`, `m:custom` and `m:sentieon`, and fix the wrong `rsem` SAME_AS?
10. **Dangling edges (R5):** record the 45 in the lock or audit output?
11. **Enforcement in CI:** commit a small fixture graph so the precision pin and parity tests run in CI?
12. **The `master` branch:** port the June specs to `main`, or archive the branch?
