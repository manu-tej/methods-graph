"""Database-free rule engine over the curated crosslinks.

Resolves the same ``method_preconditions`` contract the Kùzu provider returns, but reads the
hand-curated YAML directly: no graph database, no built artifact, no network. That makes the
guardrail *portable* — importable from a PreToolUse hook, a CI lint step, or a notebook —
which is what makes it model-invariant. A gate that only runs where a 19,425-node database
has been built degrades to advice everywhere else, and advice depends on the model choosing
to follow it.

Only the **used** path is resolved:

    method --USES--> statistical_method --REQUIRES--> assumption --checked by--> diagnostic

That is deliberate, and it is the whole reason this module can exist. The operation-mediated
AMENABLE_TO layer (statistics runnable *downstream* of a tool's output) needs the ingested
EDAM/bio.tools graph — but it must never gate, because inheriting a bulk-DE replicate floor
from an operation tag is how a read aligner came to refuse an experiment. Since only the
used path gates, only hand-curated YAML is needed to enforce.

Evidence policy: when a gate carries a numeric threshold, the evidence reported is the
**threshold's** source (the diagnostic's ``ref``), not the assumption link's. Blocking work
means justifying the number, and the number's provenance is what a caller has to be able to
show — an assumption may be grounded in a statistics tutorial while the floor itself comes
from a specific study.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

_CROSSLINKS = Path(__file__).parent / "crosslinks"
_ASSUM_PREFIX = "assum:"
# Threshold keys a diagnostic may carry. Presence predicates (``requires``) are supported by
# the verdict engine but not yet curated, so nothing maps to them here.
_THRESHOLD_KEYS = ("min_replicates_per_group", "min_peptides_per_protein")


def _evidence_token(evidence: Any) -> str:
    """Render a curated evidence value as a single token.

    Link rows carry either a bare token (``"url:https://…"``) or a block
    (``{doi:, pmid:, url:}``); a DOI is preferred, then a URL, then a PMID.
    """
    if isinstance(evidence, str):
        return evidence
    if isinstance(evidence, dict):
        if evidence.get("doi"):
            return f"doi:{evidence['doi']}"
        if evidence.get("url"):
            return f"url:{evidence['url']}"
        if evidence.get("pmid"):
            return f"pmid:{evidence['pmid']}"
    return ""


def _slug(assumption_id: str) -> str:
    """``assum:asymptotic_normality`` -> ``asymptotic_normality``.

    Both spellings are curated: diagnostics conventionally reference assumptions by bare
    slug in ``checks`` and ``applies_to_assumption`` while link rows use the prefixed id —
    but the curated loader accepts either and normalizes to the prefixed form. So EVERY
    comparison of two assumption ids here goes through this function on BOTH sides. Compare
    a raw pair and a curator writing the accepted-but-unconventional spelling silently
    loses the diagnostic and its threshold in this engine only: the hook would stop
    blocking while ``mg guardrail`` still blocks, with nothing to signal the divergence.
    """
    return assumption_id[len(_ASSUM_PREFIX):] if assumption_id.startswith(_ASSUM_PREFIX) \
        else assumption_id


class Rules:
    """Curated rules, indexed for lookup. Construct via :func:`load_rules`."""

    def __init__(self, uses: list[dict], requires: list[dict],
                 assumption_names: dict[str, str], diagnostics: dict[str, dict]) -> None:
        self._uses = uses
        self._requires = requires
        self._assumption_names = assumption_names
        self._diagnostics = diagnostics

    def method_ids(self) -> list[str]:
        """Methods with at least one curated statistical-method link, sorted."""
        return sorted({link["method"] for link in self._uses})

    def _diagnostics_for(self, assumption_id: str) -> list[tuple[str, dict]]:
        slug = _slug(assumption_id)
        return sorted(
            (f"diag:{name}", body)
            for name, body in self._diagnostics.items()
            if slug in {_slug(str(check)) for check in (body.get("checks") or [])}
        )

    def method_preconditions(self, method_id: str) -> dict[str, Any]:
        """The evaluability contract for *method_id*, resolved from YAML alone.

        Shape-compatible with the Kùzu provider's method, so
        :func:`methods_graph.guardrail.evaluate_preconditions` consumes it unchanged.
        Raises ``KeyError`` when the method has no curated statistical-method link — this
        engine knows only the curated set and never implies coverage it does not have.
        """
        stat_links = [link for link in self._uses if link["method"] == method_id]
        if not stat_links:
            raise KeyError(method_id)

        # assumption_id -> aggregated record. One record per assumption; source is always
        # "used" here, so every one of them is gateable.
        records: dict[str, dict[str, Any]] = {}
        diagnostics_seen: dict[str, dict[str, Any]] = {}

        for link in stat_links:
            stat_id = link["statistical_method"]
            for row in self._requires:
                if row["statistical_method"] != stat_id:
                    continue
                assumption_id = row["assumption"]
                record = records.get(assumption_id)
                if record is None:
                    record = {
                        "id": assumption_id,
                        "name": self._assumption_names.get(assumption_id, _slug(assumption_id)),
                        "source": "used",
                        "evidence": _evidence_token(row.get("evidence")),
                        "via": [],
                        "checkable": "",
                        "threshold": None,
                        "diagnostics": [],
                    }
                    records[assumption_id] = record
                label = link.get("label") or stat_id
                if label not in record["via"]:
                    record["via"].append(label)

                for diag_id, body in self._diagnostics_for(assumption_id):
                    if diag_id not in record["diagnostics"]:
                        record["diagnostics"].append(diag_id)
                    diagnostics_seen.setdefault(diag_id, {
                        "id": diag_id, "name": body.get("name", ""),
                        "checks": list(body.get("checks") or []),
                        "checkable": body.get("checkable", ""),
                    })

                    checkable = str(body.get("checkable", "") or "")
                    if checkable == "pre_run" or (
                            checkable == "post_run" and record["checkable"] != "pre_run"):
                        record["checkable"] = checkable

                    # A diagnostic may CHECK several assumptions while its numeric threshold
                    # pertains to exactly one. Honour that scope or the floor leaks onto
                    # every assumption the diagnostic touches.
                    scope = str(body.get("applies_to_assumption", "") or "")
                    if scope and _slug(scope) != _slug(assumption_id):
                        continue
                    for key in _THRESHOLD_KEYS:
                        value = body.get(key)
                        if value is None:
                            continue
                        prior = (record["threshold"] or {}).get(key)
                        record["threshold"] = {
                            **(record["threshold"] or {}),
                            key: value if prior is None else max(prior, value),
                        }
                        # Blocking on a number means citing that number's source.
                        if body.get("ref"):
                            record["evidence"] = _evidence_token(body["ref"])

        return {
            "method_id": method_id,
            "assumptions": sorted(records.values(), key=lambda r: r["name"]),
            "diagnostics": sorted(diagnostics_seen.values(), key=lambda d: d["id"]),
        }


@functools.lru_cache(maxsize=None)
def load_rules(crosslinks_dir: str | None = None) -> Rules:
    """Load and index the curated crosslinks. Cached; pass a directory to override."""
    base = Path(crosslinks_dir) if crosslinks_dir else _CROSSLINKS

    def _read(name: str) -> dict:
        with (base / name).open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    method_stats = _read("method_statistical_methods.yaml")
    stat_assumptions = _read("statistical_method_assumptions.yaml")
    diagnostics_doc = _read("assumption_diagnostics.yaml")

    return Rules(
        uses=list(method_stats.get("links") or []),
        requires=list(stat_assumptions.get("requires") or []),
        assumption_names={
            a["id"]: a.get("name", "") for a in (stat_assumptions.get("assumptions") or [])
        },
        diagnostics=dict(diagnostics_doc.get("diagnostics") or {}),
    )
