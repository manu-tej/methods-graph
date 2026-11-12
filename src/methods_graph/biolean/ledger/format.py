"""The entry format (spec §1): canonical bytes, entry hash, the field schema, the character
rules of §2 step 1a, and the RFC 6901 pointers the error payload uses."""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import re
import unicodedata
from typing import Any

from methods_graph.biolean.gaf import GAF_COLUMNS
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError
from methods_graph.biolean.props import Prop

FORMAT_VERSION = 1
KINDS: tuple[str, ...] = ("axiom", "derived", "computed")
COMMON_FIELDS: tuple[str, ...] = ("v", "kind", "ledger", "base", "check", "prev", "by", "ts", "sig")
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "axiom": ("fact",),
    "derived": ("derivation", "conclusion"),
    "computed": ("method", "dataset", "graph_hash", "preconditions", "run", "conclusion"),
}
OPTIONAL_FIELDS: tuple[str, ...] = ("admission",)
RELEASE_KEYS: tuple[str, ...] = ("go_basic_data_version", "goa_date_generated", "goa_go_version")
ASSIGNED_BY_PREFIX = "biolean:"
# Columns 1, 2, 4-9 and 13-17: printable ASCII 0x21-0x7E only, when non-empty (spec §2 step 1a).
ASCII_COLUMNS: frozenset[int] = frozenset({0, 1, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16})

# `\Z`, not `$`: `$` also matches just before a final "\n", so "<64 hex>\n" would pass.
# `[0-9]`, not `\d`: `\d` (and strptime) accept any Unicode digit, e.g. U+0662.
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
LEDGER_ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
BY_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")
FILE_RE = re.compile(r"^[0-9a-f]{16}\.jsonl\Z")
# Deepest container nesting canon() writes and parse_line() reads. A legitimate entry is a few
# levels deep; the bound keeps every recursive walk of an entry far from the interpreter's limit.
MAX_DEPTH = 64
_TOO_DEEP = f"nesting deeper than {MAX_DEPTH} levels"

_AXIOM_CHECK_REQUIRED = ("kernel", "annotation_id", "contested_by", "counters")
_DERIVED_CHECK_REQUIRED = ("kernel", "axioms", "conflicts")
_CHECK_OPTIONAL = ("reference_resolved",)


# ---------------------------------------------------------------------------
# canonical bytes
# ---------------------------------------------------------------------------

def nesting_depth(obj: Any) -> int:
    """Container depth, capped: a scalar is 0, ``{"a": 1}`` is 1, ``{"a": [1]}`` is 2, and anything
    deeper than MAX_DEPTH is MAX_DEPTH + 1. Iterative (an explicit stack), and the walk stops as
    soon as it passes MAX_DEPTH, so neither a deep nor a cyclic object can hang or overflow it."""
    deepest = 0
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, (list, tuple)):
            children = node
        else:
            continue
        depth += 1
        if depth > MAX_DEPTH:
            return MAX_DEPTH + 1
        deepest = max(deepest, depth)
        stack.extend((child, depth) for child in children)
    return deepest


def canon(obj: Any) -> bytes:
    """Compact, key-sorted, ASCII JSON. Refuses NaN/Infinity and nesting deeper than MAX_DEPTH
    (ValueError), so nothing unreadable by parse_line is ever hashed or written."""
    if nesting_depth(obj) > MAX_DEPTH:
        raise ValueError(_TOO_DEEP)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def unsigned(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "sig"}


def entry_hash(entry: dict[str, Any]) -> str:
    return hashlib.sha256(canon(unsigned(entry))).hexdigest()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def parse_line(raw: bytes) -> tuple[Any, str | None]:
    """``(obj, None)`` when ``raw`` is exactly ``canon(obj) + b"\\n"``; else ``(None, reason)``.

    Re-serializing is how key-order and whitespace tampering is caught without a parser of
    its own; a duplicate key collapses on re-serialization and so fails the same way. Nesting
    deeper than MAX_DEPTH is refused whether ``json.loads`` overflows on it or not.
    """
    if not raw.endswith(b"\n"):
        return None, "line does not end with a newline"
    body = raw[:-1]
    if b"\r" in body:
        return None, "carriage return in line"
    if not body.strip():
        return None, "blank line"
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        return None, "non-ASCII byte in line"
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        return None, _TOO_DEEP
    except ValueError as exc:
        return None, f"not JSON: {exc}"
    if nesting_depth(obj) > MAX_DEPTH:
        return None, _TOO_DEEP
    try:
        again = canon(obj)
    except ValueError as exc:  # json.loads reads 1e999 as inf, which canon refuses to write
        return None, f"not canonical JSON: {exc}"
    if again != body:
        return None, "not canonical JSON (key order, whitespace or number form)"
    return obj, None


# ---------------------------------------------------------------------------
# field schema (spec §1 "Fields")
# ---------------------------------------------------------------------------

def _is_int(x: Any) -> bool:
    return type(x) is int


def _malformed(field: str, message: str, got: Any = None) -> LedgerError:
    return LedgerError(LedgerCode.LEDGER_MALFORMED, message, field, got=got)


def _str_list(x: Any) -> bool:
    return isinstance(x, list) and all(isinstance(s, str) for s in x)


def _check_block_ok(kind: str, chk: Any) -> bool:
    if not isinstance(chk, dict):
        return False
    if kind == "computed":
        return True
    required = _AXIOM_CHECK_REQUIRED if kind == "axiom" else _DERIVED_CHECK_REQUIRED
    if set(chk) - set(required) - set(_CHECK_OPTIONAL) or any(k not in chk for k in required):
        return False
    if not isinstance(chk["kernel"], str):
        return False
    if kind == "axiom":
        counters = chk["counters"]
        return (isinstance(chk["annotation_id"], str) and _str_list(chk["contested_by"])
                and isinstance(counters, dict) and set(counters) == {"new_subject"}
                and _is_int(counters["new_subject"]))
    return _str_list(chk["axioms"]) and _str_list(chk["conflicts"])


def _base_ok(base: Any) -> bool:
    if not isinstance(base, dict) or set(base) != {"obo", "gaf", "eco", "release"}:
        return False
    if not all(isinstance(base[k], str) and HEX64_RE.match(base[k]) for k in ("obo", "gaf", "eco")):
        return False
    release = base["release"]
    return (isinstance(release, dict) and set(release) == set(RELEASE_KEYS)
            and all(isinstance(release[k], str) for k in RELEASE_KEYS))


def _ts_ok(ts: Any) -> bool:
    if not isinstance(ts, str) or not TS_RE.match(ts):
        return False
    try:
        _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def shape_errors(
    entry: Any, *, ledger_id: str | None = None,
    unknown_kind_code: str = LedgerCode.LEDGER_BAD_KIND,
) -> list[LedgerError]:
    """Exactly the §1 fields for the entry's kind, with the right JSON types. Body semantics
    (§2) are not checked here. Integrity passes ``unknown_kind_code=LEDGER_MALFORMED``."""
    if not isinstance(entry, dict):
        return [_malformed("", "entry must be a JSON object", entry)]
    errs: list[LedgerError] = []
    v = entry.get("v")
    if not (_is_int(v) and v == FORMAT_VERSION):
        errs.append(LedgerError(LedgerCode.LEDGER_VERSION, "v must be the JSON integer 1", "/v",
                                got=v, fix=FORMAT_VERSION))
    kind = entry.get("kind")
    kind_known = isinstance(kind, str) and kind in KINDS
    if not kind_known:
        errs.append(LedgerError(unknown_kind_code, "kind must be axiom, derived or computed", "/kind",
                                got=kind, options=tuple(sorted(KINDS))))
    expected = COMMON_FIELDS + (KIND_FIELDS[kind] if kind_known else ())
    for k in expected:
        if k not in entry:
            errs.append(_malformed(f"/{k}", f"missing field {k}"))
    # With an unknown kind, any kind's own fields are not reported as extra: the kind error is the fix.
    tolerated = set(OPTIONAL_FIELDS) | (set() if kind_known else {f for fs in KIND_FIELDS.values() for f in fs})
    for k in sorted(set(entry) - set(expected) - tolerated):
        errs.append(_malformed(f"/{k}", f"unknown field {k}", entry[k]))
    if "admission" in entry and not isinstance(entry["admission"], dict):
        errs.append(_malformed("/admission", "admission must be an object", entry["admission"]))
    if "ledger" in entry:
        lid = entry["ledger"]
        if not (isinstance(lid, str) and LEDGER_ID_RE.match(lid)):
            errs.append(_malformed("/ledger", "ledger must be 32 lowercase hex", lid))
        elif ledger_id is not None and lid != ledger_id:
            errs.append(LedgerError(LedgerCode.LEDGER_WRONG_LEDGER,
                                    f"entry belongs to ledger {lid}, this directory is {ledger_id}",
                                    "/ledger", got=lid, context={"ledger": ledger_id}))
    if "base" in entry and not _base_ok(entry["base"]):
        errs.append(_malformed("/base", "base must be {obo, gaf, eco: 64 hex, release: {3 strings}}", entry["base"]))
    if "check" in entry and kind_known and not _check_block_ok(kind, entry["check"]):
        errs.append(_malformed("/check", f"check has the wrong shape for kind {kind}", entry["check"]))
    if "prev" in entry:
        prev = entry["prev"]
        if not (isinstance(prev, str) and (prev == "" or HEX64_RE.match(prev))):
            errs.append(_malformed("/prev", "prev must be \"\" or 64 lowercase hex", prev))
    if "by" in entry and not (isinstance(entry["by"], str) and BY_RE.match(entry["by"])):
        errs.append(_malformed("/by", "by must be sha256:<64 hex>", entry["by"]))
    if "ts" in entry and not _ts_ok(entry["ts"]):
        errs.append(_malformed("/ts", "ts must be YYYY-MM-DDTHH:MM:SSZ, a real UTC instant", entry["ts"]))
    if "sig" in entry and not isinstance(entry["sig"], str):
        errs.append(_malformed("/sig", "sig must be a string", entry["sig"]))
    if kind == "axiom" and "fact" in entry:
        fact = entry["fact"]
        if not (isinstance(fact, list) and len(fact) == len(GAF_COLUMNS) and all(isinstance(c, str) for c in fact)):
            errs.append(_malformed("/fact", "fact must be 17 string columns", fact))
    if kind == "derived":
        if "derivation" in entry and not isinstance(entry["derivation"], dict):
            errs.append(_malformed("/derivation", "derivation must be an object", entry["derivation"]))
        if "conclusion" in entry and Prop.from_dict(entry["conclusion"]) is None:
            errs.append(_malformed("/conclusion", "conclusion must be a Prop", entry["conclusion"]))
    if kind == "computed":
        for k, typ in (("method", str), ("dataset", dict), ("graph_hash", str), ("preconditions", list),
                       ("run", dict), ("conclusion", dict)):
            if k in entry and not isinstance(entry[k], typ):
                errs.append(_malformed(f"/{k}", f"{k} must be a JSON {typ.__name__}", entry[k]))
    return errs


# ---------------------------------------------------------------------------
# characters (spec §2 step 1a)
# ---------------------------------------------------------------------------

_FORBIDDEN_CATEGORIES = frozenset({"Cf", "Zl", "Zp"})


def _is_surrogate(ch: str) -> bool:
    return 0xD800 <= ord(ch) <= 0xDFFF


def _forbidden_in_column(ch: str) -> bool:
    o = ord(ch)
    return (o < 0x20 or 0x7F <= o <= 0x9F or o in (0x2028, 0x2029)
            or unicodedata.category(ch) in _FORBIDDEN_CATEGORIES)


def _bad(ch: str, *, column: bool, ascii_only: bool) -> bool:
    if _is_surrogate(ch):
        return True
    if column and _forbidden_in_column(ch):
        return True
    return ascii_only and not (0x21 <= ord(ch) <= 0x7E)


def string_fault(s: str, *, column: bool = False, ascii_only: bool = False) -> str | None:
    """The first offending code point as ``U+XXXX``, or None. Order: surrogates and forbidden
    characters first, then the first position where NFC differs."""
    for ch in s:
        if _bad(ch, column=column, ascii_only=ascii_only):
            return f"U+{ord(ch):04X}"
    nfc = unicodedata.normalize("NFC", s)
    if nfc != s:
        for a, b in zip(s, nfc):
            if a != b:
                return f"U+{ord(a):04X}"
        return f"U+{ord(s[len(nfc)]):04X}" if len(s) > len(nfc) else f"U+{ord(s[-1]):04X}"
    return None


def clean_string(s: str, *, column: bool = False, ascii_only: bool = False) -> str:
    kept = "".join(ch for ch in s if not _bad(ch, column=column, ascii_only=ascii_only))
    return unicodedata.normalize("NFC", kept)


def column_character_error(i: int, value: str) -> LedgerError | None:
    """§2 step 1a for GAF column ``i`` (0-based). The fix is the cleaned value."""
    ascii_only = i in ASCII_COLUMNS
    got = string_fault(value, column=True, ascii_only=ascii_only)
    if got is None:
        return None
    return LedgerError(LedgerCode.LEDGER_BAD_CHARACTER,
                       f"column {i + 1} ({GAF_COLUMNS[i]}) contains {got}"
                       + (" (printable ASCII only)" if ascii_only else ""),
                       f"/fact/{i}", got=got, fix=clean_string(value, column=True, ascii_only=ascii_only))


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _walk_strings(node: Any, pointer: str, out: list[tuple[str, str, bool]]) -> None:
    """Collect ``(pointer, string, is_key)``. A key is collected at the pointer of the object
    that holds it; a value at its own pointer."""
    if isinstance(node, str):
        out.append((pointer, node, False))
    elif isinstance(node, dict):
        for k in sorted(node):
            out.append((pointer, k, True))
            _walk_strings(node[k], f"{pointer}/{_escape(k)}", out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_strings(item, f"{pointer}/{i}", out)


def character_errors(entry: Any) -> list[LedgerError]:
    """Every string in the entry, keys included, must encode to UTF-8 and be NFC; fact columns
    also obey the column rules. Runs on every line at verify (spec §3 step 2) and at append.
    A bad key has ``fix`` None: renaming a key is not a value ``pointer_set`` can write."""
    errs: list[LedgerError] = []
    strings: list[tuple[str, str, bool]] = []
    _walk_strings(entry, "", strings)
    fact = entry.get("fact") if isinstance(entry, dict) else None
    fact_ok = isinstance(fact, list)
    for pointer, value, is_key in strings:
        if is_key:
            got = string_fault(value)
            if got is not None:
                errs.append(LedgerError(LedgerCode.LEDGER_BAD_CHARACTER,
                                        f"key {value!r} at {pointer or 'the top level'} contains {got}",
                                        pointer, got=got, fix=None))
            continue
        if fact_ok and pointer.startswith("/fact/") and pointer.count("/") == 2:
            idx = int(pointer[6:])
            err = column_character_error(idx, value) if idx < len(GAF_COLUMNS) else None
            if err is not None:
                errs.append(err)
            continue
        got = string_fault(value)
        if got is not None:
            errs.append(LedgerError(LedgerCode.LEDGER_BAD_CHARACTER, f"{pointer} contains {got}",
                                    pointer, got=got, fix=clean_string(value)))
    return errs


# ---------------------------------------------------------------------------
# RFC 6901
# ---------------------------------------------------------------------------

def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"pointer must start with '/': {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer.split("/")[1:]]


def pointer_get(obj: Any, pointer: str) -> Any:
    cur = obj
    for tok in _tokens(pointer):
        if isinstance(cur, list):
            cur = cur[int(tok)]
        elif isinstance(cur, dict):
            cur = cur[tok]
        else:
            raise KeyError(pointer)
    return cur


def pointer_set(obj: Any, pointer: str, value: Any) -> Any:
    """A deep copy of ``obj`` with ``value`` at ``pointer`` (an RFC 6901 replace)."""
    out = copy.deepcopy(obj)
    toks = _tokens(pointer)
    if not toks:
        return copy.deepcopy(value)
    parent = pointer_get(out, "/" + "/".join(_escape(t) for t in toks[:-1])) if len(toks) > 1 else out
    last = toks[-1]
    if isinstance(parent, list):
        parent[int(last)] = value
    else:
        parent[last] = value
    return out
