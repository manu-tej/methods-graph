"""Parse local bio.tools API JSON records into EDAM operation/topic node-id maps.

This module provides BUILD-TIME enrichment only — no network calls.
Given a directory of bio.tools API JSON files (one per tool, named <anything>.json),
it extracts EDAM operation and topic node ids for each tool and returns a lookup
map keyed by lowercased biotoolsID.

The node-id scheme matches edam.py exactly:
  http://edamontology.org/operation_3800  →  op:operation_3800
  http://edamontology.org/topic_3170      →  topic:topic_3170

Only operation_ and topic_ URIs are extracted (data_/format_ are ignored here
because this module feeds PERFORMS/HAS_TOPIC edges, not INPUT/OUTPUT edges).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Only these two URI local-name prefixes are relevant for PERFORMS / HAS_TOPIC.
_OP_PREFIX = "operation_"
_TOPIC_PREFIX = "topic_"


def _edam_uri_to_node_id(uri: str) -> str | None:
    """Convert an EDAM URI to a graph node id (op: or topic: only).

    Examples::
        http://edamontology.org/operation_3800  →  op:operation_3800
        http://edamontology.org/topic_3170      →  topic:topic_3170
        http://edamontology.org/data_3494       →  None  (not handled here)
        <anything else>                         →  None

    This matches the scheme in edam.py (_KIND_TO_IDPREFIX) and nfcore.py
    (_EDAM_PREFIX_MAP) exactly, ensuring PERFORMS/HAS_TOPIC edges connect.
    """
    local = uri.rsplit("/", 1)[-1]
    if local.startswith(_OP_PREFIX):
        return f"op:{local}"
    if local.startswith(_TOPIC_PREFIX):
        return f"topic:{local}"
    return None


def _biotools_record_to_edam(record: dict) -> dict:
    """Extract EDAM operation and topic node ids from a single bio.tools record.

    Args:
        record: A dict parsed from a bio.tools API JSON response.

    Returns:
        A dict with keys:
          - "biotools_id": str  (value of biotoolsID, or "" if absent)
          - "operations":  list[str]  (sorted, deduped op: node ids)
          - "topics":      list[str]  (sorted, deduped topic: node ids)

    This is a PURE function — no I/O, no network, no clock.
    """
    biotools_id: str = str(record.get("biotoolsID") or "")

    # Collect all operation uris across all function blocks.
    op_ids: set[str] = set()
    for fn_block in record.get("function") or []:
        if not isinstance(fn_block, dict):
            continue
        for op_entry in fn_block.get("operation") or []:
            if not isinstance(op_entry, dict):
                continue
            uri = op_entry.get("uri")
            if isinstance(uri, str) and uri:
                node_id = _edam_uri_to_node_id(uri)
                if node_id is not None:
                    op_ids.add(node_id)

    # Collect topic uris from the top-level topic list.
    topic_ids: set[str] = set()
    for topic_entry in record.get("topic") or []:
        if not isinstance(topic_entry, dict):
            continue
        uri = topic_entry.get("uri")
        if isinstance(uri, str) and uri:
            node_id = _edam_uri_to_node_id(uri)
            if node_id is not None:
                topic_ids.add(node_id)

    return {
        "biotools_id": biotools_id,
        "operations": sorted(op_ids),
        "topics": sorted(topic_ids),
    }


def load_biotools_edam(biotools_dir: Path) -> dict[str, dict]:
    """Read all *.json files in *biotools_dir* and return a lookup map.

    Args:
        biotools_dir: Directory containing bio.tools API JSON files.

    Returns:
        A dict mapping lowercased biotoolsID → {"operations": [...], "topics": [...]}.
        Records with an empty biotoolsID are skipped.
        Malformed/unparseable JSON files are skipped with a warning (no crash).

    No network calls are made. Files are processed in sorted order for determinism.
    """
    result: dict[str, dict] = {}
    for json_path in sorted(biotools_dir.glob("*.json")):
        try:
            record = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            _log.warning("biotools: skipping malformed file %s: %s", json_path.name, exc)
            continue

        if not isinstance(record, dict):
            _log.warning("biotools: skipping non-object JSON in %s", json_path.name)
            continue

        parsed = _biotools_record_to_edam(record)
        bt_id = parsed["biotools_id"].strip()
        if not bt_id:
            _log.debug("biotools: skipping record with empty biotoolsID in %s", json_path.name)
            continue

        key = bt_id.lower()
        result[key] = {
            "operations": parsed["operations"],
            "topics": parsed["topics"],
        }

    return result
