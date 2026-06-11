"""Parse STATO and OBI OWL ontologies into typed ontology-term nodes + IS_A edges.

``rdflib`` is an OPTIONAL dependency; import is lazy.  Install via::

    pip install methods-graph[ontology]

Public API
----------
parse_ontology_owl(owl_path, *, ingested_at, source, source_url, roots)
    Generic OWL ingestion.  ``roots`` maps OBO local-id → NodeKind.

parse_stato(owl_path, *, ingested_at)
    Thin wrapper: STATO root OBI_0200000 → StatisticalMethod.

parse_obi(owl_path, *, ingested_at)
    Thin wrapper: OBI roots → Assay / Protocol / StudyDesign / Instrument / Material.

Classification rules
--------------------
A class is classified to a kind if it IS the root or is a transitive
rdfs:subClassOf descendant of that root.  If a class descends from multiple
roots, the kind is determined by taking the first match when the ``roots`` dict
is iterated in **sorted key order** (i.e. sorted by OBO local-id string).
This guarantees determinism regardless of Python dict insertion order.

Node IDs
--------
Nodes are emitted with the scheme ``obo:<local_id>`` where ``<local_id>`` is
the final path component of the IRI, e.g. ``obo:STATO_0000304``.

Assumption / Diagnostic note
-----------------------------
These two NodeKind values correspond to LinkML concrete classes but are NOT
populated by this module.  STATO scatters assumption/diagnostic terms as leaf
concepts with no single clean ontology root, so there is no root mapping for
them in either parse_stato() or parse_obi().  They remain available in
NodeKind for manual or future-ingestion use.
"""
from __future__ import annotations

from pathlib import Path

from methods_graph.types import EdgeKind, EdgeRecord, NodeKind, NodeRecord, Provenance

# OBO IRI prefix used to expand local-ids like OBI_0000070 to full URIs.
_OBO_BASE = "http://purl.obolibrary.org/obo/"

# Predicates we need (defined here to avoid repeated string literals).
_RDFS_SUBCLASSOF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_OWL_DEPRECATED = "http://www.w3.org/2002/07/owl#deprecated"


def parse_ontology_owl(
    owl_path: Path,
    *,
    ingested_at: str,
    source: str,
    source_url: str,
    roots: dict[str, NodeKind],
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Parse an OWL file and return (nodes, edges) for the classified terms.

    Parameters
    ----------
    owl_path:
        Local path to a self-contained OWL/RDF-XML file.  ``owl:imports`` are
        NOT resolved — the file must be self-contained.
    ingested_at:
        ISO-8601 date string injected by the caller (never call datetime.now
        inside pure connectors).
    source:
        Short source tag, e.g. ``"stato"`` or ``"obi"``.
    source_url:
        Canonical URL of the ontology, e.g.
        ``"http://purl.obolibrary.org/obo/stato.owl"``.
    roots:
        Mapping from OBO local-id (e.g. ``"OBI_0000070"``) to the
        :class:`~methods_graph.types.NodeKind` that should be assigned to that
        root and all its transitive rdfs:subClassOf descendants.
        When a class descends from **multiple** roots the kind is determined by
        taking the first match in **sorted key order** over the root local-ids.
    """
    # --- lazy import ---
    try:
        from rdflib import Graph, URIRef  # type: ignore
        from rdflib.namespace import OWL, RDFS  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "rdflib is required for ontology ingestion; "
            "install methods-graph[ontology]"
        ) from exc

    g = Graph()
    g.parse(str(owl_path))

    # Build IRI → local_id for each root.
    root_iri_to_local: dict[str, str] = {
        _OBO_BASE + local_id: local_id for local_id in roots
    }

    # ------------------------------------------------------------------
    # 1. Collect named-class (URIRef) subClassOf triples — skip blank nodes.
    # ------------------------------------------------------------------
    child_to_parents: dict[str, set[str]] = {}
    for s, _p, o in g.triples((None, RDFS.subClassOf, None)):
        if not (isinstance(s, URIRef) and isinstance(o, URIRef)):
            continue
        child_iri = str(s)
        parent_iri = str(o)
        child_to_parents.setdefault(child_iri, set()).add(parent_iri)

    # ------------------------------------------------------------------
    # 2. Collect deprecated IRIs (owl:deprecated true).
    # ------------------------------------------------------------------
    deprecated_iris: set[str] = set()
    for s, _p, o in g.triples((None, OWL.deprecated, None)):
        if isinstance(s, URIRef) and str(o).lower() in ("true", "1"):
            deprecated_iris.add(str(s))

    # ------------------------------------------------------------------
    # 3. Collect rdfs:label for every OWL class.
    # ------------------------------------------------------------------
    labels: dict[str, str] = {}
    for s, _p, o in g.triples((None, RDFS.label, None)):
        if isinstance(s, URIRef):
            labels[str(s)] = str(o)

    # ------------------------------------------------------------------
    # 4. Transitive descendant classification.
    #
    # For each root (in *sorted* key order for determinism) compute the
    # full set of transitive rdfs:subClassOf descendants via BFS.  Each
    # IRI maps to the kind of the first (sorted) root it is reachable from.
    # ------------------------------------------------------------------
    classified: dict[str, NodeKind] = {}  # iri → kind

    for root_local_id in sorted(roots.keys()):
        kind = roots[root_local_id]
        root_iri = _OBO_BASE + root_local_id

        # Build a reverse index (parent → children) restricted to known triples
        # so BFS is efficient.
        parent_to_children: dict[str, list[str]] = {}
        for child_iri, parents in child_to_parents.items():
            for p in parents:
                parent_to_children.setdefault(p, []).append(child_iri)

        # BFS from root.
        queue: list[str] = [root_iri]
        seen: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            # Assign kind only if not already claimed by an earlier (lower
            # sorted) root (deterministic tie-breaking).
            if current not in classified:
                classified[current] = kind
            for child in parent_to_children.get(current, []):
                if child not in seen:
                    queue.append(child)

    # ------------------------------------------------------------------
    # 5. Emit NodeRecords — only classified, labelled, non-deprecated.
    # ------------------------------------------------------------------
    prov = Provenance(source, source_url, ingested_at)
    raw_nodes: dict[str, NodeRecord] = {}

    for iri, kind in classified.items():
        if iri in deprecated_iris:
            continue
        label = labels.get(iri)
        if not label:
            continue
        # Derive obo: id from IRI, e.g.
        # http://purl.obolibrary.org/obo/STATO_0000304 → obo:STATO_0000304
        local_id = iri.rsplit("/", 1)[-1]
        node_id = f"obo:{local_id}"
        if node_id in raw_nodes:
            continue  # dedupe by id
        raw_nodes[node_id] = NodeRecord(
            id=node_id,
            name=label,
            kind=kind,
            properties={"uri": iri, "ontology": source},
            provenance=prov,
        )

    # ------------------------------------------------------------------
    # 6. Emit EdgeRecords (IS_A) — restrict to the ingested set.
    # ------------------------------------------------------------------
    ingested_iris: set[str] = {
        node.properties["uri"] for node in raw_nodes.values()
    }
    raw_edges: dict[tuple[str, str], EdgeRecord] = {}

    for child_iri, parents in child_to_parents.items():
        if child_iri not in ingested_iris:
            continue
        child_local = child_iri.rsplit("/", 1)[-1]
        child_id = f"obo:{child_local}"
        for parent_iri in parents:
            if parent_iri not in ingested_iris:
                continue
            parent_local = parent_iri.rsplit("/", 1)[-1]
            parent_id = f"obo:{parent_local}"
            key = (child_id, parent_id)
            if key not in raw_edges:
                raw_edges[key] = EdgeRecord(
                    from_id=child_id,
                    to_id=parent_id,
                    kind=EdgeKind.IS_A,
                    properties={},
                    provenance=prov,
                )

    # ------------------------------------------------------------------
    # 7. Deterministic sort: nodes by id; edges by (from_id, to_id).
    # ------------------------------------------------------------------
    nodes = sorted(raw_nodes.values(), key=lambda n: n.id)
    edges = sorted(raw_edges.values(), key=lambda e: (e.from_id, e.to_id))

    return nodes, edges


def parse_stato(
    owl_path: Path,
    *,
    ingested_at: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Parse a STATO OWL file into StatisticalMethod nodes + IS_A edges.

    Root: OBI_0200000 ("data transformation") → NodeKind.STATISTICAL_METHOD.
    This root captures ~193 STATO descendants including t-test, ANOVA,
    regression, and differential-expression methods.

    Note: Assumption and Diagnostic NodeKinds are NOT produced here because
    STATO scatters those terms as leaf concepts with no single clean ontology
    root.
    """
    return parse_ontology_owl(
        owl_path,
        ingested_at=ingested_at,
        source="stato",
        source_url="http://purl.obolibrary.org/obo/stato.owl",
        roots={"OBI_0200000": NodeKind.STATISTICAL_METHOD},
    )


def parse_obi(
    owl_path: Path,
    *,
    ingested_at: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Parse an OBI OWL file into typed ontology-term nodes + IS_A edges.

    Roots:
      OBI_0000070 (assay)        → NodeKind.ASSAY
      OBI_0000272 (protocol)     → NodeKind.PROTOCOL
      OBI_0500000 (study design) → NodeKind.STUDY_DESIGN
      COB_0001300 (device)       → NodeKind.INSTRUMENT
      OBI_0100051 (specimen)     → NodeKind.MATERIAL

    When a class descends from multiple roots, the kind is determined by the
    first match in sorted root key order (COB_0001300 < OBI_0000070 < … < OBI_0500000).
    """
    return parse_ontology_owl(
        owl_path,
        ingested_at=ingested_at,
        source="obi",
        source_url="http://purl.obolibrary.org/obo/obi.owl",
        roots={
            "OBI_0000070": NodeKind.ASSAY,
            "OBI_0000272": NodeKind.PROTOCOL,
            "OBI_0500000": NodeKind.STUDY_DESIGN,
            "COB_0001300": NodeKind.INSTRUMENT,
            "OBI_0100051": NodeKind.MATERIAL,
        },
    )
