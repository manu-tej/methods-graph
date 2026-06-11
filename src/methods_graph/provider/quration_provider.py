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


# --- EDAM-label → quration vocabulary maps -------------------------------------
# Keys are lowercased EDAM *topic* Preferred Labels (only HAS_TOPIC→topic nodes
# feed these maps); values are quration enum *values* (DataModality /
# MethodCategory). Every key below was verified against the non-obsolete EDAM
# topic vocabulary (EDAM.tsv, ~260 topics) — guessed/operation/data labels were
# removed so the tables don't overstate coverage. Unknown topics are dropped
# rather than guessed, so a method is never silently mislabelled.
#
# Honest coverage gaps: EDAM has NO topic for ATAC-seq, single-cell sequencing,
# bisulfite/methylation assay, or sequence alignment, so the corresponding
# quration values (atac_seq, single_cell*, bisulfite_seq, alignment) are not
# reachable from topics alone — Phase 2 can derive these from operations instead.

_TOPIC_TO_MODALITY: dict[str, str] = {
    "rna-seq": "rna_seq",
    "transcriptomics": "rna_seq",
    "chip-seq": "chip_seq",
    "dna polymorphism": "dna_seq",
    "genetic variation": "dna_seq",
    "copy number variation": "dna_seq",
    "structural variation": "dna_seq",
    "whole genome sequencing": "dna_seq",
    "exome sequencing": "dna_seq",
    "genomics": "dna_seq",
    "metagenomics": "metagenomics",
    "metagenomic sequencing": "metagenomics",
    "metatranscriptomics": "metatranscriptomics",
}

_TOPIC_TO_CATEGORY: dict[str, str] = {
    "rna-seq": "rna_seq",
    "transcriptomics": "rna_seq",
    "gene expression": "differential_expression",
    "chip-seq": "chip_seq",
    "dna polymorphism": "variant_calling",
    "genetic variation": "variant_calling",
    "copy number variation": "variant_calling",
    "structural variation": "variant_calling",
    "sequence assembly": "assembly",
    "metagenomics": "metagenomics",
    "metagenomic sequencing": "metagenomics",
    "data quality management": "quality_control",
    "quality affairs": "quality_control",
    "methylated dna immunoprecipitation": "methylation",
    "molecular interactions, pathways and networks": "pathway_analysis",
}


def _map_modalities(topic_labels: list[str]) -> list[str]:
    """Map EDAM topic labels to quration DataModality values, dropping unknowns.

    De-duplicated and order-stable (first occurrence wins)."""
    out: list[str] = []
    for label in topic_labels:
        modality = _TOPIC_TO_MODALITY.get(label.strip().lower())
        if modality and modality not in out:
            out.append(modality)
    return out


def _derive_category(topic_labels: list[str]) -> str:
    """Pick the first recognised MethodCategory from the topics, else 'custom'."""
    for label in topic_labels:
        category = _TOPIC_TO_CATEGORY.get(label.strip().lower())
        if category:
            return category
    return "custom"


def _quality_metrics(props: dict[str, Any], *, has_container: bool) -> dict[str, Any]:
    """Derive structural quality metrics from available signals.

    These are heuristics over packaging/documentation presence, NOT measured
    scores — Phase 2 replaces them with Papers-derived citations and curated
    reproducibility data. ``code_availability`` is true when the tool ships a
    container or exposes a homepage/repository.
    """
    code_available = bool(has_container or props.get("homepage"))
    return {
        "reproducibility_score": 0.8 if has_container else 0.5,
        "code_availability": code_available,
        "documentation_quality": 0.7 if props.get("description") else 0.4,
        "peer_reviewed": False,
        "citation_count": 0,
    }


def _io_specs(nodes: list[dict[str, Any]], *, is_input: bool) -> list[dict[str, Any]]:
    """Build MethodInputSpec or MethodOutputSpec dicts from EDAM Data/Format nodes.

    Inputs/outputs are derived from EDAM Data/Format INPUT/OUTPUT edges and shaped
    as quration MethodInput/OutputSpec dicts (plain dicts — no quration import needed).
    Entries are deduped by (name, data_type) and sorted by name for determinism.
    """
    seen: set[tuple[str, str]] = set()
    specs: list[dict[str, Any]] = []
    for node in nodes:
        name = node["name"]
        data_type = node["name"]
        key = (name, data_type)
        if key in seen:
            continue
        seen.add(key)
        description = f"EDAM {node['kind']}: {name}"
        if is_input:
            specs.append({
                "name": name,
                "description": description,
                "data_type": data_type,
                "required": True,
                "multiple": False,
            })
        else:
            specs.append({
                "name": name,
                "description": description,
                "data_type": data_type,
            })
    specs.sort(key=lambda s: s["name"])
    return specs


def _neighborhood_to_method_dict(nb: dict[str, Any]) -> dict[str, Any]:
    m = nb["method"]
    props = m.get("properties", {})
    topic_labels = [t["name"] for t in nb["topics"]]
    tags = [o["name"] for o in nb["operations"]] + topic_labels
    containers = nb["containers"]
    compute = {}
    if containers:
        compute["container_image"] = containers[0]["properties"].get(
            "image_name", containers[0]["name"])
    return {
        "id": m["id"],
        "name": m["name"],
        "category": _derive_category(topic_labels),
        "description": props.get("description", ""),
        "implementation_type": props.get("implementation_type", "tool"),
        "version": props.get("version", ""),
        "repository_url": props.get("homepage") or None,
        "tags": tags,
        "inputs": _io_specs(nb.get("inputs", []), is_input=True),
        "outputs": _io_specs(nb.get("outputs", []), is_input=False),
        "supported_modalities": _map_modalities(topic_labels),
        "quality_metrics": _quality_metrics(props, has_container=bool(containers)),
        "compute_requirements": compute,
        "status": "active",
        "publications": [],
    }


class KuzuMethodsGraphProvider:
    def __init__(self, db_path: Path):
        self._db = kuzu.Database(str(db_path))
        self._conn = kuzu.Connection(self._db)

    # --- context manager support ---

    def close(self) -> None:
        """Close the connection and database."""
        self._conn.close()
        self._db.close()

    def __enter__(self) -> "KuzuMethodsGraphProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- internal helpers ---

    def _all_method_ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "MATCH (m:Entity {kind:'Method'}) RETURN m.id")]

    # NOTE: get_methods issues ~4 queries per method (one for operations, one for topics,
    # one for containers, and one for the method itself via method_neighborhood).
    # This N+1 pattern is acceptable for small graphs; batching is a Phase 2 optimisation.
    def get_methods(self) -> list[dict[str, Any]]:
        out = []
        for mid in self._all_method_ids():
            out.append(_neighborhood_to_method_dict(method_neighborhood(self._conn, mid)))
        return out

    def retrieve_context(self, req, *, k_hops: int = 1) -> str:
        """Spec-Protocol entry point. Duck-types a quration ParsedRequest:
        uses req.keywords if present, else falls back to splitting req.original_query.
        Delegates to retrieve_context_for_keywords so quration can inject this provider
        without a hard dependency."""
        keywords = list(getattr(req, "keywords", None) or [])
        if not keywords:
            query = getattr(req, "original_query", "") or ""
            keywords = query.split()
        return self.retrieve_context_for_keywords(keywords, k_hops=k_hops)

    def retrieve_context_for_keywords(self, keywords: list[str], *, k_hops: int = 1) -> str:
        seeds = self._method_ids_matching(keywords)
        if not seeds:
            return ""
        return to_rag_text(seed(self._conn, seeds, k_hops=k_hops))

    def _method_ids_matching(self, keywords: list[str]) -> list[str]:
        ids: list[str] = []
        for kw in keywords:
            # NOTE: n.properties is a JSON string, so this matches both keys and values.
            # Keywords coinciding with property KEY names (e.g. "version", "description")
            # will false-positive on every node at scale. Phase 2 should index specific
            # fields (description, labels) instead of substring-scanning the whole blob.

            # Step 1: find ALL entities whose name or properties contain the keyword.
            all_rows = self._conn.execute(
                "MATCH (n:Entity) "
                "WHERE contains(lower(n.name), lower($kw)) "
                "   OR contains(lower(n.properties), lower($kw)) "
                "RETURN n.id, n.kind ORDER BY n.id",
                parameters={"kw": kw},
            )
            direct_method_ids: list[str] = []
            non_method_ids: list[str] = []
            for row in all_rows:
                nid, kind = row[0], row[1]
                if kind == "Method":
                    direct_method_ids.append(nid)
                else:
                    non_method_ids.append(nid)

            # Step 2: collect direct method hits.
            ids.extend(direct_method_ids)

            # Step 3: for non-method hits, walk outward from methods up to 2 hops to
            # find any method that reaches the matched entity.
            # NOTE: *1..2 is intentionally asymmetric — it covers
            #   Method -PERFORMS-> ChildOp -IS_A-> ParentOp
            # so searching a parent EDAM concept surfaces methods that perform its
            # specializations.  The reverse (child keyword matching parent's methods)
            # is NOT covered; that wider expansion is deferred to Phase 2.
            if non_method_ids:
                resolved = self._conn.execute(
                    "MATCH (meth:Entity {kind:'Method'})-[r:Rel*1..2]->(x:Entity) "
                    "WHERE list_contains($matched, x.id) "
                    "RETURN DISTINCT meth.id ORDER BY meth.id",
                    parameters={"matched": non_method_ids},
                )
                ids.extend(row[0] for row in resolved)

        return list(dict.fromkeys(ids))

    def score_method(self, method_id: str, *, keywords: list[str]) -> float:
        # Phase 2: graph/EDAM-overlap scoring. MVP returns neutral.
        return 0.0


def build_analysis_method(method_dict: dict[str, Any]):
    """Upgrade a method dict to a quration AnalysisMethod if quration is installed.

    The dict produced by ``get_methods()`` is complete: ``category``,
    ``supported_modalities`` (mapped to ``DataModality`` values), ``inputs``/``outputs``
    (populated from EDAM Data/Format INPUT/OUTPUT edges), and ``quality_metrics`` are all
    present, so this validates against a real quration install. ``quality_metrics`` are
    structural heuristics until Phase 2 adds Papers enrichment.
    """
    try:
        from quration.broker.models import AnalysisMethod   # type: ignore
    except ImportError as e:
        raise RuntimeError("quration is not installed; install methods-graph[quration]") from e
    return AnalysisMethod(**method_dict)
