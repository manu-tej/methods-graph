# Data Sources and Attribution

- **What this is:** every upstream source the graph and Biolean read, its license, how it is fetched, and what the repo commits.
- **Status, 2026-09-22:** GO/GOA/ECO (Biolean) and the BioClaw skill library added. Graph-source licenses were last checked 2026-07-02.
- **Read next:** [`docs/README.md`](README.md) for the docs index; [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for how each source flows into the build.

This repo builds a local graph from public bioinformatics method metadata and curated
crosslinks. Biolean, a separate subsystem, reads the Gene Ontology and human GO
annotations. Verify upstream licenses again before publishing a release or vendoring
source snapshots. Rows marked "verify" were not confirmed from a primary statement on
2026-09-22.

## Current Repo State

Committed source/provenance artifacts:

- `data/methods.lock.json` records the build command, graph counts, coverage, the graph
  hash from a local rebuild, and **partial** source pins. EDAM has a sha256 and
  Last-Modified. STATO and OBI have a sha256 and a release PURL. nf-core/modules has a
  commit (`d13eeb9f`). The `biocontainers` and `biotools` entries are empty (`{}`), and the
  BioClaw skill library is not recorded at all (`data/methods.lock.json:73-91`). It is
  provenance metadata, not a database dump.
- `tests/fixtures/ontology/obi_mini.owl` and `tests/fixtures/ontology/stato_mini.owl`
  are reduced test fixtures used to exercise ontology parsing. They are not full
  ontology redistributions.
- nf-core fixture `meta.yml` / `environment.yml` files under `tests/fixtures/` are
  small parser fixtures, not a vendored modules snapshot.
- `tests/fixtures/biolean/go-mini.obo`, `goa-mini.gaf`, `eco-mini.txt` and
  `golden_verdict.json` are hand-written fixtures in the upstream file formats, with
  synthetic content (terms named `A`, `B`, `C`…, subjects such as `UniProtKB:P00008`).
  They are not extracts of GO, GOA or ECO.

Local-only source caches (all gitignored):

- `snapshots/` holds the graph sources (`EDAM.tsv`, `modules/`, `biocontainers/`,
  `biotools/`, `stato.owl`, `obi.owl`, `skills/bioclaw/`, and `snapshot.json`, written by
  `mg fetch` and covering only what `mg fetch` downloads). It also holds `go/` (Biolean).
  These are rebuild inputs and cache, not public-release artifacts.
- `snapshots/go/` currently has **no** `snapshot.json`: it was not produced by
  `mg biolean fetch`. Its OBO is `data-version: releases/2026-07-26`, while the GAF header
  names `go-version .../releases/2026-04-27`. The frozen `biolean-bench/` items and the
  2026-09-22 result files were built on this exact pair. Whether to re-fetch a pinned pair
  (which strands those items and results) is an open decision; see
  [`docs/BACKLOG.md`](BACKLOG.md).
- Build outputs: `data/methods.kuzu` (a single file under kuzu 0.11.3) and its Parquet
  staging directory `data/methods.kuzu.staging/`. `.gitignore` also still lists
  `data/staging/` and `data/canonical/`, which no current code writes.
- `biolean-bench/` (Biolean's frozen items, manifest and modal prior) is gitignored too.

## Sources and licenses

| Source | Use in this repo | Upstream license / attribution note |
|---|---|---|
| EDAM Ontology | Operations, data types and formats. `Topic_` rows are not ingested (`connectors/edam.py:9-12`). | EDAM states CC BY-SA 4.0 on `edamontology.org`; cite EDAM and preserve attribution. |
| nf-core | Pipeline/module metadata and workflow context | nf-core states that nf-core pipeline code is MIT licensed; preserve copyright/license notices for any copied code or metadata. |
| BioContainers | Container/tool metadata | BioContainers registry/web repositories are Apache-2.0; verify license for any specific copied metadata or container recipe. |
| bio.tools | Tool registry metadata | bio.tools states registry content is CC BY 4.0; preserve attribution when reusing metadata. |
| STATO | Statistical method ontology terms | STATO GitHub/OLS pages state Creative Commons Attribution / CC BY 3.0; preserve attribution. |
| OBI | Assay/protocol ontology terms | OBI paper describes OBI as publicly available under CC BY 3.0; preserve attribution. |
| BioClaw skill library (`Runchuan-BU/BioClaw`, `container/skills/`) | `Skill` nodes: 28 parsed of 39 `SKILL.md` files; 11 have no YAML frontmatter at all (so no `name`) and are skipped uncounted | **Verify.** The local snapshot carries no license file. |
| Gene Ontology, `go-basic.obo` | Biolean only: terms, `is_a`, `part_of`, alt_ids, obsoletion. Not part of the graph. | CC BY 4.0. Stated in the file header (`property_value: terms:license http://creativecommons.org/licenses/by/4.0/`). Cite GO and preserve attribution. |
| GO annotations, human GOA (`goa_human.gaf.gz`) | Biolean only: the axioms (906,445 GAF rows). Not part of the graph. | CC BY 4.0 per the GO Consortium's citation policy. The GAF header carries no license line (**verify** before redistributing). |
| ECO `gaf-eco-mapping.txt` | Biolean only: GAF evidence code → ECO class (26 default mappings) | **Verify.** The file states no license. The ECO project distributes the ontology under CC0 1.0; not confirmed for this file on 2026-09-22. |

## How each source is fetched

`mg` below is `.venv/bin/python -m methods_graph.cli`; no `mg` script is installed (see
[`CLAUDE.md`](../CLAUDE.md)). Both fetch commands need network.

| Source | Command | URL (`src/methods_graph/fetch.py`) | Pinned? |
|---|---|---|---|
| EDAM | `mg fetch --dest snapshots` | `https://edamontology.org/EDAM.tsv` (:294) | No: moving URL. The lock records the sha256 after the fact. |
| nf-core/modules | `mg fetch` | `git clone --depth 1 https://github.com/nf-core/modules.git` (:339) | No: default branch, no ref, and an existing clone is reused without updating. The lock records the commit. |
| BioContainers | `mg fetch` | `https://api.biocontainers.pro/ga4gh/trs/v2/tools` (:514), live | No (`{}` in the lock) |
| bio.tools | `mg fetch` | `https://bio.tools/api/tool` (:581), live | No (`{}` in the lock) |
| STATO | `mg fetch` | `http://purl.obolibrary.org/obo/stato.owl` (:657) | No: "latest" PURL. The lock records the sha256 and the resolved release. |
| OBI | `mg fetch` | `http://purl.obolibrary.org/obo/obi.owl` (:697) | No: "latest" PURL. The lock records the sha256 and the resolved release. |
| BioClaw skills | none | copied by hand into `snapshots/skills/bioclaw/` | No. `mg rebuild` reads it without an existence check. A missing directory builds 0 `Skill` nodes and a different graph hash. |
| human GOA | `mg biolean fetch --out snapshots/go` | `http://geneontology.org/gene-associations/goa_human.gaf.gz` (:738) | No: always the current file, so frozen Biolean items cannot be rebuilt once GOA moves unless `snapshots/go/` is kept. |
| GO `go-basic.obo` | `mg biolean fetch` | `http://purl.obolibrary.org/obo/go/releases/<release>/go-basic.obo` (:749), `<release>` read from the GAF header's `go-version` | Yes, to the GAF's release. If the GAF names none, it falls back to the moving `go/go-basic.obo` PURL (:739) and records release `""` without an error. |
| ECO mapping | `mg biolean fetch` | `http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt` (:740) | No: moving PURL |

`mg biolean fetch` downloads the GAF first, then the OBO at the release the GAF names, then
the ECO mapping. It writes `snapshots/go/snapshot.json` with the URL, sha256, version and
fetch time for each file (`fetch.py:828-839`). The three files total about 47 MB.

## Source Links

- EDAM: https://edamontology.org/
- nf-core license requirement: https://nf-co.re/docs/specifications/pipelines/requirements/mit_license
- BioContainers registry: https://github.com/BioContainers/registry
- BioContainers containers: https://github.com/BioContainers/containers
- bio.tools home/about: https://bio.tools/home
- STATO GitHub: https://github.com/ISA-tools/stato
- STATO OLS: https://www.ebi.ac.uk/ols4/ontologies/stato
- OBI home: https://obi-ontology.org/
- OBI paper: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0154556
- BioClaw: https://github.com/Runchuan-BU/BioClaw
- Gene Ontology citation and license policy: https://geneontology.org/docs/go-citation-policy/
- GO annotation downloads: https://current.geneontology.org/products/pages/downloads.html
- ECO: https://www.evidenceontology.org/ and https://github.com/evidenceontology/evidenceontology

## Publication Rule

Prefer fetching public sources from their upstream locations during reproducible builds.
Do not commit downloaded source archives, PDFs, database dumps, or third-party snapshots
unless the file is deliberately versioned, redistributable, and documented here.
