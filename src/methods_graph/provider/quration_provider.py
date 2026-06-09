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
