# Data Sources and Attribution

Last checked: 2026-07-02.

This repo builds a local graph from public bioinformatics method metadata and curated
crosslinks. Verify upstream licenses again before publishing a release or vendoring
source snapshots.

## Current Repo State

Committed source/provenance artifacts:

- `data/methods.lock.json` records source pins, snapshot hashes, graph counts, and
  the graph hash from a local rebuild. It is provenance metadata, not a database dump.
- `tests/fixtures/ontology/obi_mini.owl` and `tests/fixtures/ontology/stato_mini.owl`
  are reduced test fixtures used to exercise ontology parsing. They are not full
  ontology redistributions.
- nf-core fixture `meta.yml` / `environment.yml` files under `tests/fixtures/` are
  small parser fixtures, not a vendored modules snapshot.

Local-only source caches:

- `snapshots/` is gitignored. Current local files such as `snapshots/obi.owl` and
  `snapshots/stato.owl` are rebuild inputs/cache, not public-release artifacts.
- `data/staging/`, `data/canonical/`, and local Kuzu database directories are
  generated build outputs and stay ignored.

| Source | Use in this repo | Upstream license / attribution note |
|---|---|---|
| EDAM Ontology | Operations, data types, formats, and topic vocabulary | EDAM states CC BY-SA 4.0 on `edamontology.org`; cite EDAM and preserve attribution. |
| nf-core | Pipeline/module metadata and workflow context | nf-core states that nf-core pipeline code is MIT licensed; preserve copyright/license notices for any copied code or metadata. |
| BioContainers | Container/tool metadata | BioContainers registry/web repositories are Apache-2.0; verify license for any specific copied metadata or container recipe. |
| bio.tools | Tool registry metadata | bio.tools states registry content is CC BY 4.0; preserve attribution when reusing metadata. |
| STATO | Statistical method ontology terms | STATO GitHub/OLS pages state Creative Commons Attribution / CC BY 3.0; preserve attribution. |
| OBI | Assay/protocol ontology terms | OBI paper describes OBI as publicly available under CC BY 3.0; preserve attribution. |

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

## Publication Rule

Prefer fetching public sources from their upstream locations during reproducible builds.
Do not commit downloaded source archives, PDFs, database dumps, or third-party snapshots
unless the file is deliberately versioned, redistributable, and documented here.
