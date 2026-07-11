"""Backend-neutral LinkML schema for the methods-graph model.

Exposes :func:`schema_path` so test and validation code can locate the YAML
without hardcoding filesystem paths.
"""
from __future__ import annotations

from pathlib import Path


def schema_path() -> Path:
    """Return the absolute path to the LinkML schema YAML file."""
    return Path(__file__).with_name("methods_graph.yaml")
