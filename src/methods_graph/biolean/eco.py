"""Reader for the published ``gaf-eco-mapping.txt``: GAF evidence code → ECO id.

The mapping is data, fetched from ``http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt``,
never a constant in source. Only ``Default`` rows are used; the first ``Default`` row for a
code wins and every other kind of row is counted.
"""
from __future__ import annotations

_REPORT_KEYS = ("comment_lines", "default_rows", "non_default_row", "bad_row")


def parse_eco_mapping(text: str) -> tuple[dict[str, str], dict[str, int]]:
    report = {key: 0 for key in _REPORT_KEYS}
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            report["comment_lines"] += 1
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            report["bad_row"] += 1
            continue
        code, kind, eco = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if kind != "Default":
            report["non_default_row"] += 1
            continue
        report["default_rows"] += 1
        mapping.setdefault(code, eco)
    return mapping, report
