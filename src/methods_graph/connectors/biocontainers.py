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
