"""Canonical bytes, entry hash, line parsing, the spec section 1 field schema, the section 2 step 1a
character rules. This module is pure ASCII: non-ASCII test values are written as escapes."""
import json

import pytest

from methods_graph.biolean.ledger.errors import ALL_LEDGER_CODES, LedgerCode as LC, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    ASCII_COLUMNS, FILE_RE, MAX_DEPTH, canon, character_errors, clean_string, column_character_error,
    entry_hash, nesting_depth, parse_line, pointer_get, pointer_set, shape_errors, string_fault, unsigned)

LEDGER_ID = "0123456789abcdef0123456789abcdef"
DIGEST = "ab" * 32
FACT = ["UniProtKB", "P04637", "TP53", "involved_in", "GO:0006915",
        "DOI:10.1038/s41586-026-00001-0", "IDA", "", "P", "", "", "protein",
        "taxon:9606", "20260925", "biolean:3f2a9c1e8b7d6054", "", ""]


def entry(**over):
    e = {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": list(FACT),
         "base": {"obo": DIGEST, "gaf": DIGEST, "eco": DIGEST,
                  "release": {"go_basic_data_version": "releases/2026-07-26",
                              "goa_date_generated": "2026-05-21T08:10", "goa_go_version": "x"}},
         "check": {"kernel": "0.1.0", "annotation_id": "gaf:9d1c0000deadbeef", "contested_by": [],
                   "counters": {"new_subject": 0}},
         "prev": "", "by": "sha256:" + DIGEST, "ts": "2026-09-25T10:00:00Z", "sig": "U1NIU0lH"}
    e.update(over)
    return e


def test_canon_is_compact_sorted_ascii_and_refuses_nan():
    assert canon({"b": 1, "a": [True, None, "\u00e9"]}) == b'{"a":[true,null,"\\u00e9"],"b":1}'
    with pytest.raises(ValueError):
        canon({"x": float("nan")})


def test_entry_hash_excludes_sig_and_is_64_hex():
    e = entry()
    h = entry_hash(e)
    assert len(h) == 64 and h == h.lower() and h == entry_hash(entry(sig="other"))
    assert h != entry_hash(entry(ts="2026-09-25T10:00:01Z"))
    assert "sig" not in unsigned(e) and "sig" in e


def test_parse_line_accepts_only_canonical_lines():
    # Break: compare json.loads results instead of bytes; four "reason" cases then parse
    # (reordered keys, whitespace, number form, duplicate key). Break: drop the ValueError guard
    # around canon; the two overflow cases (json.loads reads them as +-inf) then raise.
    line = canon(entry()) + b"\n"
    obj, reason = parse_line(line)
    assert reason is None and obj == entry()
    reasons = {
        "reordered keys": b'{"v":1,"kind":"axiom"}\n',
        "whitespace": b'{"kind": "axiom","v":1}\n',
        "carriage return": canon(entry()) + b"\r\n",
        "blank": b"\n",
        "missing newline": canon(entry()),
        "NaN": b'{"v":NaN}\n',
        "Infinity": b'{"v":Infinity}\n',
        "number form": b'{"v":1e5}\n',
        "duplicate key": b'{"v":1,"v":2}\n',
        "float overflow": b'{"v":1e999}\n',
        "negative float overflow": b'[-1e400]\n',
        "non-ASCII byte": '{"v":"\u00e9"}\n'.encode("utf-8"),
        "not JSON": b"nope\n",
    }
    for name, bad in reasons.items():
        obj, reason = parse_line(bad)
        assert obj is None and reason, name
    assert "Out of range" in parse_line(b'{"v":1e999}\n')[1]


def _nested(depth):
    obj = "x"
    for i in range(depth):
        obj = {"a": obj} if i % 2 else [obj]
    return obj


def test_nesting_depth_counts_containers_iteratively():
    # Break: a recursive walk (RecursionError at 100000 deep); no stop past MAX_DEPTH (100000 deep
    # then reports 100000, which fails before the cyclic case, and the cyclic list never returns).
    assert (nesting_depth(1), nesting_depth({"a": 1}), nesting_depth({"a": [1]}), nesting_depth([])) == (0, 1, 2, 1)
    assert nesting_depth(entry()) == 3 and nesting_depth(_nested(MAX_DEPTH)) == MAX_DEPTH == 64
    assert nesting_depth(_nested(MAX_DEPTH + 1)) == nesting_depth(_nested(100000)) == MAX_DEPTH + 1
    cyclic = []
    cyclic.append(cyclic)
    assert nesting_depth(cyclic) == MAX_DEPTH + 1
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(cyclic)


def test_parse_line_refuses_nesting_deeper_than_max_depth():
    # Break: drop the depth check (the 65-deep line is then refused by canon's own bound, with the
    # reason "not canonical JSON: nesting deeper than 64 levels", not the one pinned here); drop the
    # RecursionError catch (the 1000000-deep line then raises; 3.14's json.loads decodes 100000
    # levels, 3.12's does not).
    deepest = _nested(MAX_DEPTH)
    assert parse_line(canon(deepest) + b"\n") == (deepest, None)
    too_deep = json.dumps(_nested(MAX_DEPTH + 1), separators=(",", ":")).encode("ascii") + b"\n"
    assert parse_line(too_deep) == (None, "nesting deeper than 64 levels")
    for n in (100000, 1000000):
        assert parse_line(b"[" * n + b"]" * n + b"\n") == (None, "nesting deeper than 64 levels"), n


def test_canon_refuses_nesting_deeper_than_max_depth():
    # Break: drop the depth check in canon; the 65-deep object is then written.
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(_nested(MAX_DEPTH + 1))
    with pytest.raises(ValueError, match="nesting deeper than 64 levels"):
        canon(_nested(100000))


def test_shape_errors_on_the_example_entry_is_empty():
    assert shape_errors(entry(), ledger_id=LEDGER_ID) == []
    assert shape_errors(entry(admission={"policy": "allowed_signers"}), ledger_id=LEDGER_ID) == []
    assert shape_errors(entry(check={**entry()["check"], "reference_resolved": {"title": "x"}}), ledger_id=LEDGER_ID) == []


def test_version_true_or_float_is_ledger_version():
    # Break: `entry.get("v") == 1` (True == 1 and 1.0 == 1 in Python).
    for v in (True, 1.0, "1", 2, None):
        [e] = [x for x in shape_errors(entry(v=v)) if x.field == "/v"]
        assert (e.code, e.got, e.fix) == (LC.LEDGER_VERSION, v, 1)


def test_unknown_kind_missing_and_extra_fields_are_malformed():
    errs = shape_errors(entry(kind="rule"))
    assert [(e.code, e.field) for e in errs] == [(LC.LEDGER_BAD_KIND, "/kind")]
    assert errs[0].options == ("axiom", "computed", "derived") and errs[0].fix is None
    assert [(e.code, e.field) for e in shape_errors(entry(kind="rule"), unknown_kind_code=LC.LEDGER_MALFORMED)] == [(LC.LEDGER_MALFORMED, "/kind")]
    e = entry()
    del e["prev"]
    assert [(x.code, x.field, x.got) for x in shape_errors(e)] == [(LC.LEDGER_MALFORMED, "/prev", None)]
    assert [(x.code, x.field) for x in shape_errors(entry(foo=1))] == [(LC.LEDGER_MALFORMED, "/foo")]
    assert [(x.code, x.field) for x in shape_errors(entry(admission="yes"))] == [(LC.LEDGER_MALFORMED, "/admission")]
    assert [(x.code, x.field) for x in shape_errors("not an object")] == [(LC.LEDGER_MALFORMED, "")]
    # derived and computed carry their own fields, and an axiom must not carry theirs
    assert [(x.code, x.field) for x in shape_errors(entry(derivation={}))] == [(LC.LEDGER_MALFORMED, "/derivation")]


def test_wrong_ledger_id_is_wrong_ledger_and_bad_ids_are_malformed():
    [e] = shape_errors(entry(), ledger_id="f" * 32)
    assert (e.code, e.field, e.got) == (LC.LEDGER_WRONG_LEDGER, "/ledger", LEDGER_ID)
    assert [x.code for x in shape_errors(entry(ledger="ABC"))] == [LC.LEDGER_MALFORMED]
    assert [x.field for x in shape_errors(entry(prev="0" * 63))] == ["/prev"]
    assert [x.field for x in shape_errors(entry(by=DIGEST))] == ["/by"]
    assert [x.field for x in shape_errors(entry(sig=None))] == ["/sig"]


def test_impossible_ts_is_malformed_by_shape():
    # The last case is Arabic-Indic digits. Break: `\d` for `[0-9]` in TS_RE (strptime accepts them).
    for ts in ("2026-02-30T00:00:00Z", "2026-09-25T10:00:00", "2026-09-25 10:00:00Z", "2026-09-25T24:00:00Z",
               "\u0662\u0660\u0662\u0666-09-25T10:00:00Z"):
        assert [(x.code, x.field) for x in shape_errors(entry(ts=ts))] == [(LC.LEDGER_MALFORMED, "/ts")], ts


def test_a_trailing_newline_is_malformed():
    # Break: `$` for `\Z` in HEX64_RE (`$` also matches just before a final newline).
    base = entry()["base"]
    cases = {"/prev": entry(prev="0" * 64 + "\n"), "/by": entry(by="sha256:" + DIGEST + "\n"),
             "/ledger": entry(ledger=LEDGER_ID + "\n"), "/base": entry(base={**base, "obo": DIGEST + "\n"}),
             "/ts": entry(ts="2026-09-25T10:00:00Z\n")}
    for field, e in cases.items():
        assert [(x.code, x.field) for x in shape_errors(e, ledger_id=LEDGER_ID)] == [(LC.LEDGER_MALFORMED, field)], field
    assert FILE_RE.match("0123456789abcdef.jsonl") and not FILE_RE.match("0123456789abcdef.jsonl\n")


def test_base_and_check_blocks_are_typed_per_kind():
    base = entry()["base"]
    assert [x.field for x in shape_errors(entry(base={**base, "obo": "short"}))] == ["/base"]
    assert [x.field for x in shape_errors(entry(base={**base, "extra": 1}))] == ["/base"]
    assert [x.field for x in shape_errors(entry(base={**base, "release": {}}))] == ["/base"]
    chk = entry()["check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "counters": {"new_subject": True}}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "contested_by": "gaf:x"}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(check={**chk, "extra": 1}))] == ["/check"]
    assert [x.field for x in shape_errors(entry(fact=FACT[:16]))] == ["/fact"]
    assert [x.field for x in shape_errors(entry(fact=FACT[:16] + [1]))] == ["/fact"]
    d = entry(kind="derived", derivation={"goal": {}, "steps": [], "root": "s1"},
              conclusion={"subject": "UniProtKB:P1", "qualifier": "involved_in", "term": "GO:1",
                          "taxon": "NCBITaxon:9606", "negated": False},
              check={"kernel": "0.1.0", "axioms": [], "conflicts": []})
    del d["fact"]
    assert shape_errors(d, ledger_id=LEDGER_ID) == []
    assert [x.field for x in shape_errors({**d, "conclusion": {"subject": "x"}})] == ["/conclusion"]
    assert [x.field for x in shape_errors({**d, "check": {"kernel": "0.1.0"}})] == ["/check"]


def test_character_errors_find_surrogates_controls_and_nfc():
    # Break: skip the surrogate check (UnicodeEncodeError later); skip NFC; treat U+2028 as fine.
    e = entry(fact=FACT[:16] + ["\ud800"])
    [err] = character_errors(e)
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/fact/16", "U+D800", "")
    [err] = character_errors(entry(fact=FACT[:16] + ["x\r"]))
    assert (err.field, err.got, err.fix) == ("/fact/16", "U+000D", "x")
    [err] = character_errors(entry(fact=FACT[:1] + ["P0463\u00e9"] + FACT[2:]))   # column 2 is ASCII-only
    assert (err.field, err.got, err.fix) == ("/fact/1", "U+00E9", "P0463")
    nfd = "cafe\u0301"                                                       # column 10 allows non-ASCII, NFC only
    [err] = character_errors(entry(fact=FACT[:9] + [nfd] + FACT[10:]))
    assert (err.field, err.got, err.fix) == ("/fact/9", "U+0065", "caf\u00e9")
    [err] = character_errors(entry(fact=FACT[:9] + ["a\u2028b"] + FACT[10:]))
    assert (err.field, err.got, err.fix) == ("/fact/9", "U+2028", "ab")
    [err] = character_errors(entry(fact=FACT[:9] + ["a\u200bb"] + FACT[10:]))   # Cf
    assert err.got == "U+200B"
    [err] = character_errors(entry(ts="2026-09-25T10:00:00Z\ud800"))
    assert err.field == "/ts" and err.got == "U+D800"
    d = entry(kind="derived", derivation={"steps": [{"id": nfd}]}, conclusion={})
    [err] = character_errors(d)
    assert err.field == "/derivation/steps/0/id" and err.fix == "caf\u00e9"
    assert character_errors(entry()) == []


def test_character_errors_check_dict_keys_at_the_containing_object():
    # Break: walk values only; a key with a lone surrogate or in NFD then passes.
    [err] = character_errors(entry(admission={"policy": "allowed_signers", "s\ud800": "x"}))
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/admission", "U+D800", None)
    assert repr("s\ud800") in err.message
    nfd = "cafe\u0301"
    [err] = character_errors(entry(kind="derived", derivation={"steps": [{nfd: "s1"}]}, conclusion={}))
    assert (err.code, err.field, err.got, err.fix) == (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/0", "U+0065", None)
    assert repr(nfd) in err.message
    [err] = character_errors({**entry(), "\ud800": 1})
    assert (err.field, err.got, err.fix) == ("", "U+D800", None) and "top level" in err.message
    assert character_errors(entry(admission={"policy": "allowed_signers"})) == []
    assert character_errors(entry()) == []


def test_empty_columns_15_16_17_pass_character_check():
    row = list(FACT)
    row[14] = ""
    assert all(column_character_error(i, v) is None for i, v in enumerate(row))
    assert ASCII_COLUMNS == {0, 1, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16}
    assert string_fault("a b", ascii_only=True) == "U+0020" and clean_string("a b", ascii_only=True) == "ab"
    assert string_fault("a b") is None and column_character_error(9, "gene one") is None


def test_pointer_get_and_set():
    e = entry()
    assert pointer_get(e, "/fact/3") == "involved_in" and pointer_get(e, "/check/counters/new_subject") == 0
    e2 = pointer_set(e, "/fact/3", "NOT|involved_in")
    assert e2["fact"][3] == "NOT|involved_in" and e["fact"][3] == "involved_in"
    assert pointer_set({"a~b": {"c/d": 1}}, "/a~0b/c~1d", 2) == {"a~b": {"c/d": 2}}
    assert pointer_get({"x": 1}, "") == {"x": 1}
    with pytest.raises(KeyError):
        pointer_get(e, "/nope")


def test_ledger_error_serializes_exactly_seven_keys_and_the_code_table_is_closed():
    err = LedgerError(LC.LEDGER_BAD_TAXON, "m", "/fact/12", got="x", options=("b", "a"))
    d = err.to_dict()
    assert set(d) == {"code", "message", "field", "got", "fix", "options", "context"}
    assert d["options"] == ["a", "b"] and d["fix"] is None and d["context"] is None
    assert json.dumps(d)
    assert LC.LEDGER_MALFORMED in ALL_LEDGER_CODES and len(ALL_LEDGER_CODES) == 39
    exc = LedgerIntegrityError([err])
    assert exc.to_json() == {"errors": [d]} and exc.errors == [err]


def test_ledger_and_verifier_modules_import_no_network_or_bench_module():
    # Spec section 0.1: the trusted base stays one thing. An ast walk over every import statement,
    # function-level ones included, in the trusted set: the kernel and what its verdict depends on
    # (props, errors, store, obo, gaf, eco), the verifier (ed25519, sshsig) and ledger/*. A banned
    # name anywhere in a dotted module path or an imported name fails, relative or absolute.
    # Break: `from methods_graph import fetch` in ledger/errors.py (a source regex over
    # `methods_graph.fetch` missed exactly this form); `import subprocess` in store.py;
    # `from ..bench import items` in ledger/load.py.
    import ast
    from pathlib import Path
    import methods_graph.biolean as pkg
    root = Path(pkg.__file__).parent
    trusted = [root / f"{m}.py" for m in ("kernel", "props", "errors", "store", "obo", "gaf", "eco", "ed25519", "sshsig")]
    trusted += sorted((root / "ledger").glob("*.py"))
    banned = {"fetch", "bench", "subprocess", "urllib", "socket", "http", "requests"}

    def imported(node):
        if isinstance(node, ast.Import):
            return [a.name for a in node.names]
        module = node.module or ""                 # None for `from . import x`
        return [module] + [f"{module}.{a.name}" if module else a.name for a in node.names]

    offending = []
    for f in trusted:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"), filename=str(f))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                offending += [(f.name, node.lineno, name) for name in imported(node) if banned & set(name.split("."))]
    assert offending == []
    assert all(f.is_file() for f in trusted) and len(trusted) == 16
    # the walk sees the forms a regex over `methods_graph.<name>` would miss
    for src in ("from methods_graph import fetch", "from . import bench", "from ..bench import items",
                "import urllib.request", "def f():\n    import subprocess", "from http import client"):
        assert any(banned & set(name.split(".")) for node in ast.walk(ast.parse(src))
                   if isinstance(node, (ast.Import, ast.ImportFrom)) for name in imported(node)), src
