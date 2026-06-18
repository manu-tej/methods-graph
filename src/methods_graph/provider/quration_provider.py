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
from methods_graph.extract.seed import seed, method_neighborhood, method_ids_matching


# NOTE: ``category`` and ``supported_modalities`` were previously derived from the
# HAS_TOPIC→Topic layer.  That layer has been removed, so both fields now fall back
# to defaults (category='custom', supported_modalities=[]).  A future, more reliable
# derivation can come from PERFORMS→Operation rather than coarse topics.


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
    tags = [o["name"] for o in nb["operations"]]
    containers = nb["containers"]
    compute = {}
    if containers:
        compute["container_image"] = containers[0]["properties"].get(
            "image_name", containers[0]["name"])
    return {
        "id": m["id"],
        "name": m["name"],
        "category": "custom",
        "description": props.get("description", ""),
        "implementation_type": props.get("implementation_type", "tool"),
        "version": props.get("version", ""),
        "repository_url": props.get("homepage") or None,
        "tags": tags,
        "inputs": _io_specs(nb.get("inputs", []), is_input=True),
        "outputs": _io_specs(nb.get("outputs", []), is_input=False),
        "supported_modalities": [],
        "quality_metrics": _quality_metrics(props, has_container=bool(containers)),
        "compute_requirements": compute,
        "status": "active",
        "publications": [],
    }


class KuzuMethodsGraphProvider:
    def __init__(self, db_path: Path):
        self._db = kuzu.Database(str(db_path), read_only=True)
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

    # NOTE: get_methods issues several queries per method (operations, containers,
    # I/O, stats, plus the method itself) via method_neighborhood. This N+1 pattern
    # is acceptable for small graphs; batching is a Phase 2 optimisation.
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

    # --- quration methods-graph lane (build_real_loop auto-activates on these) ---

    def resolve_method_ids(self, keywords: list[str]) -> list[str]:
        """Method ids matching a relation's keywords, best match first.

        quration's MethodsGraphEvaluationRunner calls this to pick a method id for an
        edge when the broker has no structural pick (``ids[0]`` is taken).  Returns an
        empty list when nothing matches — quration reads that as an honest coverage gap.
        """
        return self._method_ids_matching(keywords)

    def neighborhood(self, method_id: str) -> dict[str, Any]:
        """The method's grounded statistical context for quration's edge evaluation.

        Returns the dict from :func:`method_neighborhood` — notably ``statistical_methods``
        (each ``{name, evidence, ...}``) and ``assumptions`` (each ``{name, via, ...}``,
        ``via`` carrying the statistical method + grounding citation it is inherited
        through).  Raises ``KeyError`` if *method_id* is unknown, which quration maps to
        a COVERAGE_GAP verdict.
        """
        return method_neighborhood(self._conn, method_id)

    def _method_ids_matching(self, keywords: list[str]) -> list[str]:
        # Behavior-preserving delegation to the shared pure helper (see extract/seed.py).
        return method_ids_matching(self._conn, keywords)

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
