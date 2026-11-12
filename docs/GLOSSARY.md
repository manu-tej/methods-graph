# Glossary

**What this is:** the terms and acronyms used in the repo and these docs, A to Z, each with where it lives in code.
**Status:** as of 2026-09-22 (local `main` at `6b28222`). Every code location below was checked against that commit; line references into README.md and `docs/superpowers/specs/` are to the 2026-09-22 working tree, which revises those files. Line numbers drift, so trust the file and symbol name over the number.
**Read next:** [README.md](README.md) for the reading order, [STATUS.md](STATUS.md) for where things stand, [ARCHITECTURE.md](ARCHITECTURE.md) for how the parts connect.

## How to read this page

- **Code locations** are relative to `src/methods_graph/`, unless they start with `tests/`, `data/` or `docs/`, or name a repo-root file (`README.md`, `CLAUDE.md`, `pyproject.toml`, `Makefile`).
- **Graph counts** come from `data/methods.kuzu` (built 2026-06-19; its hash matches `data/methods.lock.json`), queried read-only on 2026-09-22.
- **Labels.** **Open question** means the owner has not decided. **Owner decision** means the owner settled it, and the source is given. Everything else is fact, checked in code or data.
- **`mg`** is shorthand for this repo's CLI. It is not installed. Define it before running anything (see [mg](#m)).
- **Command tags**, as defined in [README.md](README.md#running-the-cli): **[DB]** needs `data/methods.kuzu`. **[GO]** needs `snapshots/go/`. **[items]** needs `biolean-bench/`. **[net]** needs network access. **[paid]** makes paid model calls.

### Words with two meanings

| Word | Meaning 1 | Meaning 2 |
|---|---|---|
| `BROKEN`, `UNKNOWN`, `VALID` | guardrail-chain handoff between consecutive steps | sequencing-benchmark validity, which uses reachability |
| gold, `modal:`, `random:` | sequencing benchmark (`bench/`) | Biolean benchmark (`biolean/bench/`) |
| `part_of` | a GO relation between terms, and a Biolean rule | a GAF qualifier for cellular-component annotations |
| `is_a` / `IS_A` | a GO relation, and a Biolean rule | a graph edge for the EDAM, STATO and OBI hierarchies |
| Plan 1, Plan 2 | sequencing-benchmark plans (2026-07-30/31) | Biolean plans (2026-09-21/22) |
| live cut | Biolean `--since` (built, never used) | sequencing-benchmark Plan 3 (never written) |
| `obo:` / OBO | graph node-id prefix for STATO and OBI terms | the ontology file format that `go-basic.obo` uses |

### Identifier prefixes

Graph node ids (counts are nodes in `data/methods.kuzu`):

| Prefix | Node kind | Rule | Count | Minted in |
|---|---|---|---|---|
| `m:` | Method | `m:` + the method node's lowercased name, e.g. `m:star`. Exact and total, with no collisions. Normalize free text by lookup (`bench/normalize.py:59`). Never use the fuzzy `resolve_method_ids()`: it returns `m:ea-utils` for `STAR`. | 905 | `connectors/nfcore.py:420,432` |
| `mod:` | Module | `mod:` + the `name` field of the module's `meta.yml`, never the directory leaf: `star/align` is `mod:star_align`. Subworkflows are Module nodes too; 12 of the 120 have upper-case names, e.g. `mod:BAM_IMPUTE_QUILT`. | 2,038 | `connectors/nfcore.py:334`; join key `iter_module_metas`, `connectors/nfcore_pipeline.py:52` |
| `op:` | EDAM Operation | `op:operation_NNNN` | 537 | `connectors/edam.py` |
| `data:` | EDAM Data | `data:data_NNNN` | 949 | `connectors/edam.py` |
| `fmt:` | EDAM Format | `fmt:format_NNNN`. 1,488 of the 2,100 are synthetic `fmt:pat:<ext>` nodes minted from nf-core glob patterns. | 2,100 | `connectors/edam.py`; `connectors/nfcore.py:151` |
| `pkg:` / `ctr:` | Package / Container | bioconda package / container image | 804 / 9,139 | `connectors/biocontainers.py` |
| `assum:` / `diag:` | Assumption / Diagnostic | hand-curated | 29 / 23 | `crosslinks/*.yaml` |
| `stat:` / `obo:` | StatisticalMethod | 4 curated `stat:` plus 203 `obo:` from STATO. `obo:` also covers Assay (1,795), Instrument (607), Material (157), StudyDesign (101) and Protocol (6) from OBI. | 207 | `connectors/ontology.py` (`obo:`); `crosslinks/assumptions.py` (`stat:`) |
| `skill:` | Skill | `skill:<source>/<name>`, e.g. `skill:bioclaw/differential-expression` | 28 | `connectors/skills.py:102` |

Biolean identifiers. These are not in the graph. They come from `snapshots/go/`:

| Form | What | Where |
|---|---|---|
| `GO:NNNNNNN` | GO term | `biolean/obo.py` |
| `UniProtKB:<acc>` | subject (gene product). The GAF also has RNAcentral and ComplexPortal subjects. | GAF columns 1–2, `biolean/gaf.py` |
| `NCBITaxon:<n>` | taxon; human is `NCBITaxon:9606` | `biolean/props.py:53-63` |
| `gaf:<16 hex>` | annotation id: the first 16 hex characters of a sha256 over the row's raw columns | `biolean/gaf.py:22-25` |

## A

- **adapter.** A contestant in either benchmark is a function `(prompt: str) -> str`. `get_adapter` parses the spec string: `claude:<model>` (the local `claude` CLI, default `claude-opus-5`, [paid]), `openai:<model>` (default `gpt-4o`, temperature 0, [paid]) and `static:<path>` (canned replies from a JSON file). The baselines are resolved separately. A failing call raises `AdapterError`, which becomes an error row, and the run continues. *Where:* `bench/adapters.py:21,55,103,134`.
- **alt_id.** A secondary GO id that was merged into a primary term. The GAF loader rewrites alt ids to the primary, and the elaborator rewrites them in derivations (`ALT_ID_RESOLVED`). So the kernel's `ALT_ID_IN_KERNEL` code only fires when `kernel.check()` is called directly. *Where:* `biolean/gaf.py:78-86` (loader), `biolean/elaborate.py:38` (elaborator), `biolean/kernel.py:212-215` (`ALT_ID_IN_KERNEL`).
- **AMENABLE_TO.** A curated edge from an Operation to a StatisticalMethod, meaning "statistics you can run on this operation's output". There are 49 edges. It never gates a tool: see [used path vs amenable path](#u). *Where:* `types.py:72`, `crosslinks/operation_amenable_statistics.yaml`.
- **aspect.** GO's three namespaces: F = `molecular_function`, P = `biological_process`, C = `cellular_component`. Each GAF qualifier is legal for exactly one aspect; otherwise the kernel reports `QUALIFIER_ASPECT_MISMATCH`. An `is_a`/`part_of` step may not cross namespaces (`NAMESPACE_CROSSED`). *Where:* `biolean/props.py:14-35`.
- **audit.** `mg audit --db data/methods.kuzu` [DB], also `make audit`, runs the graph invariant checks (typed endpoints, grounding, id uniqueness, coverage). It passes on 2026-09-22. Adding `--snapshot snapshots` makes it exit 1 on a known Format mismatch: 612 formats in EDAM vs 2,100 Format nodes in the graph, because of `fmt:pat:`. That is not a regression. `mg rebuild` runs the audit (without a snapshot) as a gate and will not write the lock if it fails. *Where:* `audit.py:235` (`audit_graph`), `cli.py:712`.
- **axiom.** A Biolean rule with no premises. It cites GAF rows that match the step's conclusion exactly on (subject, qualifier, term, taxon, negated), optionally filtered by `code` and `reference`. If no row survives, the kernel reports `AXIOM_NOT_FOUND`. *Where:* `biolean/kernel.py:281` (`_apply_axiom`).

## B

- **baselines.** Fixed contestants that bracket a model's score. Both benchmarks have `gold:`, `modal:` and `random:<seed>`, but each benchmark defines them differently. Biolean refuses a baseline on the wrong track (exit 2).

| Spec | Sequencing benchmark (`bench/baselines.py`) | Biolean (`biolean/bench/baselines.py`) |
|---|---|---|
| `gold:` | Answers each item with its own gold. It is the ceiling and must score 1.0; the CI gate runs this on fixture items only. (`:31`) | The mechanical prover over the item's masked store. It is the prove-track ceiling: 500/500. (`:94`) |
| `modal:` | Always answers the most common gold sequence, with ties going to the lexicographically smallest. Every pilot sequence is unique, so on the pilot it always answers viralrecon's gold. (`:51`) | The gene-blind prior: the descendant most often annotated for the item's (qualifier, goal term) across other items, [leave-subject-out](#l), plus the shortest path up. Scores 264/500 (0.528). (`:121`) |
| `random:<seed>` | *k* methods drawn uniformly from the catalog. (`:67`) | A seeded random visible start under the item's qualifier, then 1–4 random upward hops. `random:0` scores 26/500 (0.052). (`:101`) |
| `template:` | none | Hypothesize track only: a constant `sorry` root with method `m:deseq2` and inputs `["GEO:GSE0"]`. It scores 1.0 on every hypothesize rate. (`:137`) |

- **BioContainers.** A registry of Docker and Singularity images for bioconda packages. It supplies the Package (`pkg:`, 804) and Container (`ctr:`, 9,139) nodes. 646 of 905 methods have a container (`data/methods.lock.json`, `with_container`). The API is live and the lock does not pin it. *Where:* `connectors/biocontainers.py`.
- **bio.tools.** ELIXIR's registry of bioinformatics tools, annotated with EDAM terms. It is used for build-time enrichment from `snapshots/biotools/` and supplies 898 of the 920 `PERFORMS` edges, joined on the `biotools:` identifier in a module's `meta.yml`. Newer nf-core modules often lack that identifier, so their methods get no operation unless someone curates one. *Where:* `connectors/biotools.py`.
- **BLOCKED.** See [guardrail verdicts](#g).
- **BROKEN.** Two meanings.
  - **Guardrail chain:** two consecutive steps both have curated Data I/O but share none, so the whole chain is `BLOCKED`. *Where:* `guardrail.py:245,249` (`classify_handoff`).
  - **Sequencing-benchmark validity:** a step's input is net-produced only by a *later* step, i.e. consumed before it is produced. *Where:* `bench/score.py:189-237`.

## C

- **closed-book.** The contestant sees only the prompt: no tools, no files, no repo context. The `claude:` adapter enforces this with `claude -p <prompt> --model <m> --tools "" --safe-mode --strict-mcp-config`, run in a fresh empty temp directory. `fcac341` added `--tools ""` and the temp directory (merged in `b0f80c4`); `128a8c6` added `--safe-mode` and `--strict-mcp-config` (merged as `894072d`). Both are dated 2026-09-22.
  - Not closed-book: the Sonnet run in the 2026-08-08 sequencing [pilot](#p), which predates the fix.
  - The prompt is closed-book but the model can still try to use tools: 3 of Opus 5's 500 Biolean replies were attempted tool calls, scored `UNPARSED`.
  - `claude:` has no temperature control. `openai:` uses temperature 0.
  - *Where:* `bench/adapters.py:55-88`.
- **complete chain.** A method with at least one assumption that has a checking diagnostic, i.e. a path ending in `REQUIRES_ASSUMPTION` → `CHECKED_BY`. That is 99 of 905 methods (`with_checked_assumption`). 94 of those reach their assumption through the amenable path (`with_checked_via_operation`). Only 12 have a used-path statistical method (`with_statistical_method`). *Where:* `data/methods.lock.json:41-48,65-68`.
- **conflicts.** A verdict-neutral list in a Biolean verdict. It holds annotations of the opposite polarity to a step's conclusion, at the same term or along the `is_a`/`part_of` closure: NOT rows at or above a positive conclusion, and positive rows at or below a negated one. Conflicts never change ACCEPTED or REJECTED, so a claim and its NOT form can both be ACCEPTED. *Where:* `biolean/kernel.py:357`.
- **coverage.** In this repo, the denominator a number is true over. Every metric ships with one (CLAUDE.md).
  - `mg bench coverage --items <dir>` [DB] reports how much of a sequencing item set the oracle can resolve and classify.
  - `mg biolean bench coverage` [items] prints the build manifest's denominators.
  - The audit's coverage block is written into the lock.
  - Sequencing validity has its own `coverage` field.
- **crosslinks.** Hand-curated YAML that adds the statistics layer, with an evidence token (DOI, PMID or URL) on every link. The files cover method → statistical method, statistical method → assumption, operation → statistic (`AMENABLE_TO`), assumption → diagnostic, assay → method (`ANALYZED_BY`), curated `PERFORMS`, Data I/O and modalities. Unchanged since `b791d69` (2026-07-10). An edit reaches the graph, and so `mg guardrail`, only after `mg rebuild`; the [rules engine](#r) and `hook.py` read the YAML directly, so it reaches them at once. *Where:* `crosslinks/`.

## D

- **DAG** (directed acyclic graph). Two uses:
  - GO's term graph, which Biolean climbs upward over `is_a`/`part_of`.
  - An nf-core pipeline's process graph, captured by `nextflow run <clone> -profile test --outdir <launch>/out -preview -with-dag <clone>/dag.mmd` (`fetch.py:437-438`) and parsed by `connectors/nextflow_dag.py`. This is the sequencing benchmark's gold: gold edges are the DAG's module-level (`mod:`) edges with bookkeeping steps removed (`bench/gold.py:79`), projected to `m:` ids only at scoring time, and the gold sequence is a topological order (`bench/gold.py:63`). The committed DB holds no pipeline DAGs (0 `DOWNSTREAM_OF` edges).
- **depth, gold_depth.** Biolean prove track.
  - `depth` is the number of propagation steps on the used chain of an accepted reply, and `None` otherwise. *Where:* `biolean/bench/score.py:103`.
  - `gold_depth` is the gold derivation's step count minus 1. *Where:* `biolean/bench/items.py:206`.
  - Summaries bucket depth as 1, 2, 3 and 4+ (`biolean/bench/score.py:197`). The 500 prove items split 315 / 124 / 47 / 14.
- **derivation.** The JSON document a Biolean prover submits: `{"biolean": "0.1", "goal": <Prop>, "steps": [...], "root": <step id>}`.
  - Every step has `id`, `rule` and `conclusion` (a Prop). `premises` (earlier step ids) is required for `is_a`/`part_of` and optional, defaulting to empty, for `axiom`/`sorry`.
  - `axiom` may add `code` and `reference`. `is_a` and `part_of` need `edge: [child, parent]`. `sorry` needs `provenance`.
  - `mg biolean prove` prints one. The format is in [biolean/README.md](biolean/README.md).
  - *Where:* `biolean/kernel.py:19-29,387`; example emitter `biolean/tactics.py:107-154`.
- **Dogma.** The AI-scientist platform (github.com/manu-tej/dogma). README.md presents this repo as Dogma's "method-validity and guardrail substrate". That positioning came in `849a071` (2026-07-12), before the benchmark and Biolean work. No Dogma code is in this repo. *Where:* README.md, opening paragraphs and "Role in Dogma" section.

## E

- **ECO** (Evidence & Conclusion Ontology). `gaf-eco-mapping.txt` maps each GAF evidence code to an ECO id. Only `Default` rows are read (26 in the local file). The ECO id is stored on each annotation; the kernel does not reason over it. *Where:* `biolean/eco.py`.
- **EDAM.** An ontology of bioinformatics concepts: Operation (what a tool does), Data (what kind of information), Format (the file format) and Topic.
  - Loaded from `snapshots/EDAM.tsv` as `op:`, `data:` and `fmt:` nodes plus `IS_A` edges. Topic is declared but not loaded.
  - EDAM is the join vocabulary for `PERFORMS`, `INPUT`/`OUTPUT` and the benchmark's equivalence relation.
  - Coverage caveat: of 7,880 `INPUT`/`OUTPUT` edges, 7,744 point to Format and only 136 to Data. Handoff and validity checks use Data only.
  - *Where:* `connectors/edam.py`.
- **elaborator.** Rewrites identifiers before the kernel sees them. It works by lookup only and reports every rewrite: `SYMBOL_RESOLVED` (gene symbol to subject id), `SYMBOL_AMBIGUOUS` (left unchanged), `ALT_ID_RESOLVED` and `TAXON_NORMALIZED`. It never rewrites obsolete terms. `elaborate_and_check` attaches the report as `verdict["elaboration"]`. *Where:* `biolean/elaborate.py:69,90`.
- **equivalence class.** When two different methods count as the same answer. `same_class` is identity, or a shared EDAM operation outside a two-operation denylist (`op:operation_0236`, `op:operation_2495`) *and* a shared input Data type.
  - The relation is not transitive, so it is not a true partition; "class" is a misnomer.
  - On the real graph it is exactly 7 non-identity pairs: bwa~bwamem2, bwa~strobealign, deseq2~limma, fastp~fastqc, hisat2~star, kraken2~metabuli and rsem~salmon.
  - The test that pins those pairs is DB-gated, so CI does not enforce it.
  - *Where:* `bench/score.py:29-37,47`; `tests/test_bench_score.py:562-574`.
- **error codes (Biolean).** 21 kernel codes, from `MALFORMED` to `SORRY_NEGATED`. The scorer adds `UNPARSED`. The most common in the Opus 5 run are `EDGE_NOT_FOUND` (the store has no such direct edge) and `AXIOM_NOT_FOUND` (no GAF row matches). Each error has six keys: step, code, message, expected, actual, suggestions. *Where:* `biolean/errors.py:8-52`; meanings in [biolean/README.md](biolean/README.md).
- **EVALUABLE.** See [guardrail verdicts](#g).
- **evidence code, evidence class.**
  - An evidence code is GAF column 7: what supports an annotation, e.g. IDA (direct assay), IMP (mutant phenotype), TAS (traceable author statement), IEA (electronic).
  - Biolean groups codes into 7 classes: experimental, high_throughput, phylogenetic, computational, author_statement, curatorial and electronic. Codes are types, never weights (owner decision, spec §0.3, `docs/superpowers/specs/2026-09-21-biolean-design.md:43-44`).
  - The benchmark population keeps experimental and high_throughput rows only.
  - *Where:* `biolean/props.py:37-48`.
- **explain.** `mg explain --method m:<x>` [DB] prints why a method has the evaluability it has: assumption, then `via` (the statistical method or operation it is inherited through), then evidence (DOI or PMID), then the source YAML file. It prints amenable-path thresholds without saying they do not gate. *Where:* `explain.py`, `cli.py:883`.

## F

- **FACTS_REQUIRED.** See [guardrail verdicts](#g).
- **FactStore.** A Protocol for what the Biolean kernel and tactics need from the facts: `term`, `primary_id`, `parents`, `children`, `annotations`, `matching`, `subject_for_symbol`, `subject_exists` and `subjects`. `StaticFactStore` is the dict-backed implementation. `load_store` fills it from `snapshots/go/` in about 13–16 s on every CLI call that loads the store; there is no cache. *Where:* `biolean/store.py:18,36,147`.
- **fetch.** There are two fetchers, and neither can re-fetch a recorded version: `mg fetch` ignores the lock's pins, and `mg biolean fetch` always takes the current GOA.
  - `mg fetch --dest snapshots` [net] downloads the graph sources and writes `snapshots/snapshot.json`. It clones nf-core at HEAD. EDAM, STATO and OBI come from "latest" URLs, and BioContainers and bio.tools from live APIs. It never fetches the BioClaw skills.
  - `mg biolean fetch --out snapshots/go` [net] downloads the current GOA, then the GO release that GOA's header names, then the ECO mapping, and writes `snapshot.json`.
  - *Where:* `cli.py:905`; `fetch.py:291-735,828`.

## G

- **GAF** (GO Annotation File), format 2.2. 17 tab-separated columns, including subject, symbol, qualifier, GO id, reference, evidence code, aspect, taxon, date and assigned_by. The parser applies its filters in a fixed order and counts every dropped row. *Where:* `biolean/gaf.py`.
- **GO** (Gene Ontology). Terms (`GO:NNNNNNN`) in three [aspects](#a), linked by `is_a`, `part_of` and the regulates relations. Biolean loads `go-basic.obo`. The local load has 48,340 terms (10,248 obsolete) and 71,496 edges. Source: the `load_report` that every store-loading `mg biolean` command (`check`, `prove`, `goals`, `bench build|run|score`) prints on stderr [GO].
- **GOA** (Gene Ontology Annotation, EMBL-EBI). Annotations of gene products to GO terms. Biolean uses the human file `goa_human.gaf.gz`. The local load has 906,445 rows, which give 906,422 annotations after 23 duplicates are dropped (same `load_report`). *Where:* `fetch.py:738` (URL).
- **goal, goal_match, goal_rewritten.** Biolean benchmark row fields.
  - The goal is the Prop a derivation claims to prove.
  - `goal_match` says whether the elaborated conclusion of the step named by `root` equals the item's Prop. It is `None` when the reply is unparsed or `root` names no step.
  - `goal_rewritten` says whether the reply's own stated goal differs from the item's. It is also `True` when that goal is missing or malformed.
  - *Where:* `biolean/bench/score.py:61-64,93-96`.
- **gold.** Two meanings.
  - **Sequencing benchmark:** the module order and DAG edges from an nf-core pipeline's Nextflow DAG, projected to `m:` ids. Processes from local, non-nf-core modules are dropped without a count. *Where:* `bench/gold.py`.
  - **Biolean:** the prover's shortest derivation for a prove item under that item's mask, stored as `item["gold"]`. *Where:* `biolean/bench/items.py:200-207`.
  - Both benchmarks also have a `gold:` [baseline](#b).
- **guardrail.** `mg guardrail --method m:<x> [--fact key=N]` [DB] checks a method's curated preconditions (assumptions, diagnostics, thresholds) against integer dataset facts. `mg guardrail-chain --step ...` does the same for a linear list of steps plus their Data handoffs.
  - Status: frozen since `430300a` (2026-07-31), and narrow. Exactly one method, `m:deseq2`, can reach `BLOCKED`. The test that pins this is DB-gated, so CI does not enforce it.
  - `--analysis` keywords and chain steps written without `m:` take the first fuzzy match (for example, `salmon` resolves to `m:biohansel`).
  - *Where:* `guardrail.py`; `tests/test_guardrail_precision.py:60`.
- **guardrail verdicts.**

| Verdict | Exit code | Meaning |
|---|---|---|
| `EVALUABLE` | 0 | The method has curated assumptions, and no gate failed or lacks a fact. This includes methods whose only gates are `REQUIRES_REVIEW`: `m:limma` is EVALUABLE at `replicates_per_group=1`. |
| `BLOCKED` | 3 | A supplied fact is below a used-path threshold (a `FAIL` gate), or a chain handoff is `BROKEN`. |
| `NOT_EVALUABLE` | 4 | The method has no curated assumptions. This is a coverage gap, not a pass. |
| `FACTS_REQUIRED` | 5 | A numeric gate exists but its fact was not supplied. Fail-closed; added in `8477b28` (2026-07-30). |

  - Per-gate results are `PASS`, `FAIL`, `INSUFFICIENT_INFO` and `REQUIRES_REVIEW`.
  - A chain takes the first that applies: `BLOCKED`, then `NOT_EVALUABLE`, then `FACTS_REQUIRED`, then `EVALUABLE`.
  - *Where:* `guardrail.py:23-36,69-71,168-171,276-321`; exit codes `cli.py:1164-1165`.

## H

- **handoff.** The guardrail-chain check between consecutive steps: does step N's Data output feed step N+1's Data input? The result is `VALID`, `BROKEN` or `UNKNOWN`. Only Data nodes are compared; Format joins are excluded because they produce false handoffs. *Where:* `guardrail.py:244-261`.
- **hide_exact, hide_subtree.** The two Biolean masks.
  - `hide_exact` (prove track) hides every non-negated row at (subject, qualifier, term, taxon), whatever the evidence code, so that a second row at the same triple cannot leak the answer.
  - `hide_subtree` (hypothesize track) hides the same key at the term and at every `is_a`/`part_of` descendant, so the fact cannot be re-derived.
  - *Where:* `biolean/bench/items.py:100,106`.
- **hit, hit_with_sorry.** Biolean prove-track scores.
  - `hit` means accepted, and `goal_match` is `True`, and no `sorry` is used.
  - `hit_with_sorry` is the same except at least one used `sorry`. It is counted separately and is never a hit (Opus 5: 12 of 500).
  - *Where:* `biolean/bench/score.py:97-98`.
- **hook.** A Claude Code PreToolUse adapter. It denies shell commands that mention DESeq2 when a samplesheet (at the workspace root or one directory down) shows fewer than 3 replicates per group, and asks when it cannot read one. It detects no other method. It is not wired into any settings file, and README.md does not mention it. *Where:* `hook.py`.
- **hypothesize.** See [tracks](#t).

## I

- **ingest.** `mg ingest --manifest <yaml> --dest <dir> --db <db>` builds a different graph from per-pipeline vendored modules. It adds Pipeline, `HAS_MODULE`, `DOWNSTREAM_OF`, ExecutionSpec and Modality, loads no skills, and writes `<dest>/ingest.lock.json` rather than `data/methods.lock.json`. No ingest-built DB exists in this checkout. *Where:* `cli.py:572`, `ingest.py`.
- **is_a.** Two meanings.
  - A GO relation (the child term is a subtype of the parent), and a Biolean rule with one premise. The rule lifts the premise's conclusion from `edge[0]` to `edge[1]`, and only when the store holds that exact direct edge (see [strict](#s)). Propagation follows `is_a` and `part_of` only, stays within one namespace, and needs a live parent. *Where:* `biolean/props.py:51`; `biolean/kernel.py:63` (`propagating_parents`), `:300` (`_apply_propagation`).
  - In the methods graph, `IS_A` edges (4,988) carry the EDAM, STATO and OBI hierarchies.
- **items.** The frozen questions a benchmark asks.
  - **Sequencing:** built by `mg bench build` from local pipeline clones that already hold a `dag.mmd`; making those clones needs Nextflow, Java and network [net]. None are in git. The only set is the untracked [pilot](#p) at `bench-runs/2026-08-08-pilot/items/`.
  - **Biolean:** `biolean-bench/items/{prove,hypothesize}.json`, plus `manifest.json` and `modal.json`, built by `mg biolean bench build` [GO] in about 40 s. 500 per track, seed 0. The directory is gitignored.
- **items_manifest.** The `{release, since}` pair from a Biolean item set's `manifest.json`, copied onto every results row. `bench score` refuses (exit 2) a results file whose rows carry more than one distinct `items_manifest`; `--resume` refuses one whose rows' `items_manifest` differs from the current items'. *Where:* `biolean/bench/run.py:20`.

## K

- **kernel.** Biolean's checker, `check(derivation, store)`. It validates structure and identifiers, applies one of four rules per step (`axiom`, `is_a`, `part_of`, `sorry`) and checks the root. It returns a plain dict: `ACCEPTED` if and only if the error list is empty, otherwise `REJECTED`, together with errors, axioms, sorries and conflicts. It resolves no identifiers itself; the elaborator does that first. 518 lines. *Where:* `biolean/kernel.py:19-20,387`.
- **Kuzu** (Kùzu). An embedded graph database, pinned to `kuzu==0.11.3` (pyproject.toml:10). `data/methods.kuzu` has one node table, `Entity`, and one relationship table, `Rel`, each typed by a `kind` string column. The file is a gitignored build artifact, regenerated by `mg rebuild`. Open it read-only for queries. *Where:* `graph/schema.py`.

## L

- **leave-subject-out.** Biolean's `modal:` baseline subtracts the item's own subject's visible descendants from the prior's counts before choosing, so the prior never uses the gene under test. `modal.json` is fitted over every prove-eligible item, before the live cut and before sampling. The spec calls the whole benchmark "leave-one-out". *Where:* `biolean/bench/baselines.py:121-133`; `biolean/bench/items.py:267`.
- **live cut, `--since`.** Keep only facts newer than a model's training data, to limit contamination.
  - **Biolean:** `mg biolean bench build --since YYYY-MM-DD` [GO] keeps an item only if its `cut_date` is on or after that date. `cut_date` is the earliest date among the item's hidden rows, across every evidence code. No since-cut item set has been built: the current manifest has `"since": null`. *Where:* `biolean/bench/items.py:251`.
  - **Sequencing:** live cuts were spec §3b and meant for Plan 3, which was never written. No code exists.
- **lock.** `data/methods.lock.json`, the only tracked build artifact. It records source pins, node and edge counts, the coverage block and `graph_hash`. `graph_hash` is a sha256 over node id, name, kind, properties, bioconda_pkg, biotools_id and every edge; it leaves out source, source_url and ingested_at. Its computation trusts Kuzu's `ORDER BY`, which occasionally returns edges out of order, so a single mismatch needs a rerun ([BACKLOG.md](BACKLOG.md) M21). `mg rebuild` writes the lock. The pins describe a build; `mg fetch` does not replay them. *Where:* `pipeline.py:34,118`; `data/methods.lock.json:70`.

## M

- **MaskedFactStore.** A view over a FactStore that hides a set of annotation ids and nothing else. The Biolean benchmark checks every reply against `MaskedFactStore(store, item.hidden)`. *Where:* `biolean/store.py:105`.
- **master (branch).** A local branch that holds the 165 pre-release commits (2026-06-08 to 2026-06-19) and the June design specs for the graph, guardrail, skills and reproducible pipeline. It shares no history with `main`, which starts at the public-release squash `b791d69` (2026-07-10). Its upstream is gone, so this branch is the only copy. **Open question:** how to archive it (see [BACKLOG.md](BACKLOG.md)).
- **McNemar test** (exact). A paired test over the items where exactly one of two contestants hits. It compares Opus 5 with `modal:` on the same 500 prove items: p = 1.7e-5 under the strict kernel (Opus below modal), 0.76 under relation-aware, 0.077 under relation-blind, and 0.0015 on the biology-only score (Opus above modal). It is not implemented in the repo; the p-values come from the analysis behind [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md).
- **mg.** The shorthand these docs use for the CLI. It is not installed. The console script is `methods-graph` (pyproject.toml:25), and a bare `mg` on macOS runs `/usr/bin/mg`, an unrelated text editor. From the repo root, define it with `alias mg='.venv/bin/python -m methods_graph.cli'` or `alias mg='.venv/bin/methods-graph'`. Agents, whose shell state does not persist between calls, should call `.venv/bin/methods-graph` directly.
- **modal.** See [baselines](#b) and [leave-subject-out](#l).

## N

- **negated, NOT.** A GAF row with a `NOT|` qualifier prefix asserts that the gene product does *not* have the function, process or location. In a Prop this is `negated: true`.
  - An axiom can conclude a NOT.
  - A NOT premise never propagates (`NEGATED_PREMISE`).
  - A `sorry` cannot conclude one (`SORRY_NEGATED`).
  - The benchmark population drops negated rows.
  - *Where:* `biolean/kernel.py:300-356`.
- **next-step (metric).** For each `next_step` item, whether the gold next method (or an equivalent) is the model's first choice (top-1) or among its first 3 (top-3).
  - Results are bucketed by how many steps were already given: 0, 1–2, 3–5 and 6+.
  - The headline is the mean over the buckets, skipping bucket 0, which is nearly always a QC tool. A pooled rate is also reported.
  - *Where:* `bench/score.py:266-322`.
- **next_step, whole_pipeline.** The two sequencing task types.
  - `whole_pipeline` asks for the full ordered tool list for a goal.
  - `next_step` gives the steps done so far and asks for up to 3 candidates for the next one.
  - Positions whose answer is already in the prompt are withheld.
  - *Where:* `bench/build.py:60,70,78`.
- **nf-core module, pipeline, subworkflow.**
  - **Module:** one wrapped tool invocation in nf-core/modules (`modules/nf-core/<tool>[/<sub>]/`, with `main.nf` and `meta.yml`). In the graph it is a Module node, `mod:<meta.yml name>`, with `WRAPS` edges to the Method(s) its `meta.yml` lists. The snapshot is nf-core/modules at `d13eeb9f`, fetched 2026-06-18. *Where:* `connectors/nfcore.py`.
  - **Pipeline:** a full nf-core workflow such as nf-core/rnaseq, and the sequencing benchmark's gold source. The graph can hold Pipeline nodes (`connectors/nfcore_pipeline.py`, via `mg ingest`), but the committed DB has none, because `mg rebuild` never passes pipelines.
  - **Subworkflow:** a reusable chain of modules (`subworkflows/nf-core/`). `mg rebuild` loads subworkflows as Module nodes too. Every one of the 117 Module nodes without a `WRAPS` edge is a subworkflow (checked 2026-09-22 against the snapshot's 120 subworkflow `meta.yml` files; the other 3 subworkflow ids do carry `WRAPS` edges).
- **NOT_EVALUABLE.** See [guardrail verdicts](#g).
- **NXF_VER.** An environment variable that makes the Nextflow launcher run a specific Nextflow version. The DAG preview sets it when a pipeline entry gives `nxf_ver`. The 2026-08-08 pilot pinned nothing; its items record `nxf_ver: "unknown"`. **Open question:** the pinning policy. README.md and CLAUDE.md at `6b28222` said to pin per release, and `ingest.example.yaml:29` pins 23.10.0; their 2026-09-22 revisions call the policy open. The owner's notes record that pinning 23.10.0 broke the locally installed Nextflow 26.04.3; that was not re-tested on 2026-09-22 because it needs network. *Where:* `fetch.py:417-452`.

## O

- **OBI** (Ontology for Biomedical Investigations, OWL). `parse_obi` mints Assay, Protocol, StudyDesign, Instrument and Material nodes with `obo:` ids. They are mostly unconnected to the methods layer: only 2 `ANALYZED_BY` edges link an assay to a method. *Where:* `connectors/ontology.py`.
- **OBO.** The OBO flat-file ontology format. Biolean reads `go-basic.obo`: `[Term]` stanzas only, keeping `is_a` and `relationship:` lines. The regulates relations are loaded but never propagate. `obo:` is also a graph id prefix (see [identifier prefixes](#identifier-prefixes)). *Where:* `biolean/obo.py`.
- **obsolete term.** A GO term flagged `is_obsolete`, kept together with its `replaced_by` and `consider` pointers.
  - The local OBO has 10,248 obsolete terms, and none of them has an edge.
  - The kernel rejects any obsolete id (`OBSOLETE_TERM`), even when a GAF row exists at it. The elaborator never rewrites one.
  - 162 of the 906,445 local GAF rows point at obsolete terms, because the GO/GOA pair on disk is release-skewed.
  - *Where:* `biolean/kernel.py:209-222`.
- **oracle.** The sequencing scorer's view of the graph: seven questions (`has_method`, `method_for_module`, `operations`, `inputs`, `outputs`, `method_ids`, `multi_wrapped`). `KuzuOracle` opens `data/methods.kuzu` read-only. `StaticOracle` holds all the logic, so tests need no DB. `oracle.py` is the only benchmark file that knows a database exists. The graph scores the answers; it is not a contestant. *Where:* `bench/oracle.py:18,30,80`.

## P

- **part_of.** Two meanings.
  - A GO relation between terms (the child is part of the parent), and a Biolean rule that works like `is_a`. *Where:* `biolean/kernel.py:19-20,300`.
  - A GAF qualifier for cellular-component annotations: the gene product is part of a complex or structure. A derivation whose qualifier is `part_of` can still climb through `is_a` steps, because the qualifier is copied unchanged along the chain. *Where:* `biolean/props.py:25`.
- **PERFORMS.** A Method → EDAM Operation edge. There are 920, covering 415 of 905 methods: 898 come from bio.tools and 22 are curated in `crosslinks/method_operations.yaml`. *Where:* `types.py:48`.
- **Phase A, Phase B.** The Biolean phases (owner decision, spec §0.1, `docs/superpowers/specs/2026-09-21-biolean-design.md:37-39`).
  - **Phase A** is a typed checker for claims over existing ontologies. It is built.
  - **Phase B** is verification of analyses: discharging `sorry` steps against method preconditions through the methods graph. It is not built; there is no `discharge` code.
- **pilot.** `bench-runs/2026-08-08-pilot/` (untracked) is the only run of the sequencing benchmark. It has 156 items (10 `whole_pipeline`, 146 `next_step`) from 10 of 12 nf-core pipelines, run with `gold:`, `modal:`, `random:42` and `claude:sonnet`. The Sonnet run was **not** [closed-book](#c). The pipeline clones it was built from are gone, so the items cannot be rebuilt offline; re-scoring them works. Details: [method-sequencing-benchmark.md](method-sequencing-benchmark.md).
- **Plan 1, Plan 2, Plan 3.** Implementation plans in `docs/superpowers/plans/`. None of their checkboxes were ever ticked.

| Project | Plan 1 | Plan 2 | Plan 3 |
|---|---|---|---|
| Sequencing benchmark | Gold build, merged `529ffc5` (2026-07-31) | Scorer, adapters and runner, merged `59d5111` (2026-07-31) | Live cuts, never written |
| Biolean | Kernel, elaborator, tactics, fetch and CLI, merged `7bc79ef` (2026-09-21) | Two-track benchmark, merged `b0f80c4` (2026-09-22) | none |

- **population.** The Biolean benchmark's eligible facts: GAF rows that pass 7 ordered filters, collapsed to (subject, qualifier, term, taxon) triples.
  - **Filters:** not negated; one of 5 qualifiers; experimental or high-throughput evidence; object type `protein`; term known, primary and not obsolete.
  - **Current set** (`biolean-bench/manifest.json`): 906,422 rows, of which 453,117 are eligible, giving 131,833 triples.
  - **Prove track:** 32,298 of those triples are eligible. The other 99,535 cannot be re-derived once hidden.
  - *Where:* `biolean/bench/items.py:24-28,55`.
- **Prop.** Biolean's proposition: five fields (subject, qualifier, term, taxon, negated), with exactly those keys and types. Goals, conclusions and claims are all Props. *Where:* `biolean/props.py:117`.
- **prove.** Either the prove [track](#t) or the `prove` [tactic](#t).

## Q

- **qualifier.** GAF column 4: the relation between a gene product and a GO term.
  - 13 are recognized (`enables`, `contributes_to`, `involved_in`, `located_in`, `part_of`, `is_active_in`, `colocalizes_with`, and six `acts_upstream_of*` forms), each legal for one aspect.
  - It is copied unchanged along a Biolean chain.
  - The benchmark population keeps 5: `involved_in`, `enables`, `located_in`, `part_of` and `is_active_in`.
  - *Where:* `biolean/props.py:14-28`; `biolean/bench/items.py:24`.
- **quration.** The package and API namespace of the original Dogma implementation. It survives only at the compatibility boundary: `KuzuMethodsGraphProvider` emits plain dicts, and upgrades them to quration objects if the package is installed. It is not installed here, which accounts for the one skipped test in the local suite (`tests/test_provider.py:174`). *Where:* `provider/quration_provider.py:107`; README.md, "Role in Dogma" section.

## R

- **random.** See [baselines](#b).
- **rebuild, `rebuild --check`.**
  - `mg rebuild` (also `make rebuild`) verifies the snapshot pins, builds offline from `snapshots/` into `--db` (default `data/methods.kuzu`), runs the audit gate, then writes the lock and prints a coverage diff.
  - `--check` runs the same build, then compares the new `graph_hash` with the `methods.lock.json` next to `--db` instead of writing it, and exits 1 on a mismatch. It still overwrites `--db`, so `make rebuild-check` rewrites `data/methods.kuzu`.
  - The weekly CI job runs a fresh fetch followed by `rebuild --check`, and expects drift.
  - *Where:* `cli.py:758-880`; Makefile.
- **relation-aware, relation-blind.** The two candidate transitive edge rules for the Biolean kernel. They were evaluated only in scratch code and are not in the repo.
  - **Relation-blind** accepts an `is_a`/`part_of` step whenever the cited parent is any ancestor of the child in the kernel's existing `ancestors()` closure. The cited relation is ignored.
  - **Relation-aware** also requires the cited rule to match the composed relation of some path. A path of only `is_a` edges is `is_a`; any path containing a `part_of` edge is `part_of`.
  - **Effect:** Opus 5 goes from 205/500 under the strict rule to 269/500 (aware) or 287/500 (blind). `gold:`, `modal:` and `random:0` do not change.
  - **Open question:** see [decisions/2026-09-22-biolean-transitive-edges.md](decisions/2026-09-22-biolean-transitive-edges.md).
- **release identity.** The GO/GOA release a Biolean item set was built from. It is read from the file headers, not from `snapshot.json`: the OBO `data-version`, and the GAF's `!date-generated` and `!go-version`.
  - `bench run` and `bench score` refuse (exit 2) a store whose identity differs from the items'.
  - The current item set was built on a skewed pair: OBO `releases/2026-07-26`, with a GAF built against GO 2026-04-27. That pair was not produced by `mg biolean fetch`.
  - *Where:* `biolean/bench/items.py:138` (`read_release`); `biolean/bench/run.py:189` (`release_mismatch`).
- **rules engine.** A database-free guardrail engine that reads the curated YAML directly and follows only the used path. It knows exactly 12 methods and raises `KeyError` for any other. `hook.py` uses it. *Where:* `rules.py`.

## S

- **selection.** Step-set F1 between the model's methods and gold's, ignoring order. It uses a maximum one-to-one matching under the equivalence relation, trying each method's identity match first. *Where:* `bench/score.py:87` (`match_steps`), `:133`.
- **sequencing.** The fraction of gold DAG edges, with both endpoints matched, whose order the answer respects. It never scores adjacent pairs of the sequence, because parallel branches sit next to each other in any linearization. It is `None` when no edge is scorable. *Where:* `bench/score.py:155`.
- **shortcut edge.** An `is_a`/`part_of` step whose cited parent is a true ancestor of the child but not a direct parent, so it skips one or more intermediate terms. The strict kernel rejects it with `EDGE_NOT_FOUND`. In the Opus 5 run, 106 of the 187 `EDGE_NOT_FOUND` errors were shortcuts, 98 of which skip exactly one intermediate term, and 66 of the 280 rejected items fail on shortcuts alone. Source: [biolean/results-2026-09-22-opus-5.md](biolean/results-2026-09-22-opus-5.md).
- **Skill.** A node for an entry in an external agent-skill library. There are 28, from the BioClaw snapshot at `snapshots/skills/bioclaw/`, which `mg fetch` never fetches. 6 are wired to a Method and 3 are guardrail-evaluable (`mg skills --coverage` [DB]). Only tools a skill *declares* create `WRAPS` edges. Tools mined from its prose go into `context_tools` and never gate. *Where:* `connectors/skills.py`.
- **snapshot.** Local, gitignored copies of upstream sources. A fresh clone has none of them.
  - **Graph sources** in `snapshots/`: `EDAM.tsv`, `modules/` (the nf-core/modules clone), `biocontainers/`, `biotools/`, `stato.owl`, `obi.owl`, `skills/bioclaw/`, and `snapshot.json`, written by `mg fetch` on 2026-06-18.
  - **Biolean sources** in `snapshots/go/`: `go-basic.obo`, `goa_human.gaf.gz` and `gaf-eco-mapping.txt`. There is no `snapshot.json`, and the pair is release-skewed.
- **sorry.** Borrowed from Lean. A Biolean rule with no premises that admits a conclusion without proof, provided it carries `provenance` with exactly `{method: str, inputs: non-empty list of str, parameters: object, claim: str}`.
  - A well-formed, positive `sorry` never causes a rejection. It is counted: `sorry_count` for used sorries, `unused_sorries` for the rest.
  - It cannot conclude a NOT.
  - Checking sorries against method preconditions (Phase B's `discharge`) is not built.
  - *Where:* `biolean/kernel.py:28-29,334`.
- **STATO** (Statistics Ontology, OWL). `parse_stato` turns the descendants of two roots, `OBI_0200000` (data transformation) and `STATO_0000142` (correlation coefficient), into StatisticalMethod nodes with `obo:` ids. Assumptions and diagnostics are curated in `crosslinks/`, not taken from STATO. *Where:* `connectors/ontology.py`.
- **strict (edge rule).** The kernel's current rule: an `is_a`/`part_of` step is accepted only when the store holds that exact direct edge. Under it, Opus 5 scores 205/500 (0.410) and `modal:` 264/500 (0.528) on the same items. **Open question:** whether to keep it (see [relation-aware, relation-blind](#r)). *Where:* `biolean/kernel.py:300-313`.
- **subworkflow.** See [nf-core module, pipeline, subworkflow](#n).
- **suggest.** `mg suggest --have <id>` [DB]: advisory next steps, ranked by how many pipelines attest them. The committed DB has no Pipeline or `DOWNSTREAM_OF` data, so every candidate ranks at 0 and continuations return nothing. *Where:* `planner.py`, `cli.py:52`.

## T

- **tactic.** Borrowed from Lean: an untrusted helper whose output the kernel re-checks.
  - `goals_for` lists everything derivable for a subject (`mg biolean goals`).
  - `applicable` lists the rule applications that would conclude a Prop. It is used only in tests.
  - `prove` is a multi-source breadth-first search for the shortest derivation. It powers `mg biolean prove` and the `gold:` baseline.
  - *Where:* `biolean/tactics.py:45,87,107`.
- **taxon.** An NCBI Taxonomy id in the form `NCBITaxon:<n>`. The kernel requires `^NCBITaxon:\d+$`, and the elaborator normalizes `9606` and `taxon:9606` to that form. Every item in the current Biolean set is human (`NCBITaxon:9606`). *Where:* `biolean/props.py:53-63`.
- **template.** See [baselines](#b).
- **tracks.** The two Biolean benchmark tracks. Summaries always keep them separate.
  - **prove:** the fact is hidden with `hide_exact`, and the gold is the prover's derivation. The score is the hit rate.
  - **hypothesize:** the fact is hidden with `hide_subtree`, so only a `sorry` can conclude it. Until Phase B exists, this track measures format compliance only, and the `template:` baseline saturates it.
  - *Where:* `biolean/bench/items.py:29`; `biolean/bench/score.py:203,230`.
- **trusted.** Code whose bug could make the checker accept a wrong derivation.
  - By convention `biolean/kernel.py` is "the only trusted file" (spec §3, `docs/superpowers/specs/2026-09-21-biolean-design.md:206`; CLAUDE.md as committed at `6b28222`).
  - In fact, importing it also loads `errors`, `props` and `store`, and through `store` also `obo`, `gaf` and `eco` (checked with `sys.modules` on 2026-09-22). No test pins that import boundary.
  - Tactics, the elaborator and the baselines are untrusted: the kernel re-checks their output.

## U

- **UNKNOWN.** Two meanings. Both are common, because only 49 of 905 methods have curated input Data and 39 have output Data.
  - **Guardrail chain:** a step lacks curated Data I/O. It never blocks. *Where:* `guardrail.py:246`.
  - **Sequencing validity:** no other step in the answer produces the step's input, or the step's I/O is uncurated. It is excluded from the denominator and never counted as valid. *Where:* `bench/score.py:203,238`.
- **UNPARSED.** The scorer's code, not the kernel's, for a reply that contains no derivation. `parse_reply` takes the first balanced JSON object that has a `steps`, `root` or `biolean` key; anything else is scored as a miss with `error_codes: ["UNPARSED"]`. Such rows count in `n_unparsed` and stay in the denominator. *Where:* `biolean/bench/render.py:65`; `biolean/bench/score.py:20,87`.
- **used path vs amenable path.** The two ways a method inherits an assumption. Only used-path assumptions gate. Amenable-path assumptions come out as `REQUIRES_REVIEW` even when they carry a threshold. The rules engine follows the used path only.

| Path | Edges | Methods | Meaning |
|---|---|---|---|
| **used** | Method `USES_STATISTICAL_METHOD` → StatisticalMethod `REQUIRES_ASSUMPTION` → Assumption | 12 of 905 | The tool itself runs the test. |
| **amenable** | Method `PERFORMS` → Operation `AMENABLE_TO` → StatisticalMethod → Assumption | 94 of 905 | Statistics you could run downstream of the tool's output. |

  - Method counts are the lock's `with_statistical_method` and `with_checked_via_operation`.
  - *Where:* `extract/seed.py:277,369-371`; `guardrail.py:96-100`; `rules.py`.
- **USES_STATISTICAL_METHOD.** A curated Method → StatisticalMethod edge. There are 18, covering 12 methods. It is the used path. *Where:* `types.py:60`, `crosslinks/method_statistical_methods.yaml`.

## V

- **VALID.** See [BROKEN](#b) and [validity](#v).
- **validity.** A sequencing-benchmark axis, scored per step by reachability over curated Data I/O.
  - A step is `VALID` if an earlier step produces one of its inputs, `BROKEN` if only a later step net-produces it, and `UNKNOWN` otherwise.
  - Score = VALID / (VALID + BROKEN), with a `coverage` field alongside.
  - **Known defect:** fed its own gold, the pilot scores only 0.505 on validity (coverage 0.128), because method-level I/O unions and first-occurrence projection create false `BROKEN` verdicts. Details: [method-sequencing-benchmark.md](method-sequencing-benchmark.md).
  - *Where:* `bench/score.py:189`.

## W

- **whole_pipeline.** See [next_step, whole_pipeline](#n).
- **`--workers`, `--resume`.** Flags on `mg biolean bench run` only; the sequencing `mg bench run` has neither.
  - `--workers N` runs N adapter calls at once. Rows are streamed as they finish, then rewritten in item order at the end.
  - `--resume` keeps a results file's error-free rows and runs only the rest. It refuses (exit 2) a file from another model, another `items_manifest` or another item sample.
  - **Warning:** without `--resume`, `run` truncates `--out`, which can destroy a paid results file.
  - *Where:* `cli.py:1976-1981`; `biolean/bench/run.py:26-169`.
- **WRAPS.** Two sources.
  - Module → Method: 1,981 edges from 1,921 of the 2,038 modules. The 117 without one are all subworkflows. A `meta.yml` that lists several tools wraps several methods. `mod:` → `m:` resolution goes through this edge.
  - Skill → Method: 6 edges, declared tools only.
  - *Where:* `types.py:44`; `connectors/nfcore.py`; `connectors/skills.py`.
