"""Per-file integrity (spec section 3) without signatures: layout, line parsing, the pin, --extends,
the cache key. Task 8 adds the signature-dependent cases over the signed fixture ledger."""
import hashlib
import json
import os
import pathlib

import pytest

from methods_graph.biolean.ledger import integrity as integ
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.format import canon
from methods_graph.biolean.ledger.integrity import (
    LedgerEntry, LedgerState, cache_key, check_extends, integrity_report, verify_ledger)
from methods_graph.biolean.sshsig import allowed_signers_line, parse_allowed_signers, parse_public_key_line
from methods_graph.biolean.store import load_store
from tests.biolean_ledger_fixture import (
    BASE_FILES, BY_A, KEY16_A, KEY16_B, LEDGER_ID, LFIX, PUB_A, PUB_B, TS, ledger_base, RELEASE)

A_BLOB, _ = parse_public_key_line(PUB_A.read_text())
B_BLOB, _ = parse_public_key_line(PUB_B.read_text())
FILE_A = f"ledger/{KEY16_A}.jsonl"


def skeleton(tmp_path, *, signers=(("alice", A_BLOB),)):
    d = tmp_path / "ledger"
    (d / "ledger").mkdir(parents=True)
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID}))
    (d / "allowed_signers").write_text("".join(allowed_signers_line(p, b) for p, b in signers))
    return d


def entry(**over):
    base = ledger_base()
    e = {"v": 1, "kind": "axiom", "ledger": LEDGER_ID,
         "fact": ["UniProtKB", "P10002", "G2", "involved_in", "GO:0000003", "PMID:1", "IDA", "", "P", "", "",
                  "protein", "taxon:9606", "20260925", "biolean:" + KEY16_A, "", ""],
         "base": {**base.digests, "release": RELEASE},
         "check": {"kernel": "0.1.0", "annotation_id": "gaf:0000000000000000", "contested_by": [],
                   "counters": {"new_subject": 0}},
         "prev": "", "by": BY_A, "ts": TS, "sig": "U1NIU0lH"}
    e.update(over)
    return e


def errors_of(d, **kw):
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d, **kw)
    return exc.value.errors


def refuse_stat(monkeypatch):
    """Path.is_dir / is_file / is_symlink raise PermissionError on every path in the returned set,
    as Python 3.12 does on EACCES (an unsearchable directory); 3.13+ returns False there."""
    blocked = set()
    for method in ("is_dir", "is_file", "is_symlink"):
        real = getattr(pathlib.Path, method)

        def refuse(self, *args, _real=real, **kwargs):
            if self in blocked:
                raise PermissionError(13, "Permission denied", str(self))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, method, refuse)
    return blocked


def test_missing_ledger_files_are_malformed_not_a_crash(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "ledger.json"
    (d / "ledger.json").write_text("not json")
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": "XYZ"}))
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID, "extra": 1}))
    assert errors_of(d)[0].context["file"] == "ledger.json"
    (d / "ledger.json").write_text(json.dumps({"ledger": LEDGER_ID}))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "allowed_signers"
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "ledger"
    (d / "ledger").mkdir()
    state = verify_ledger(d)
    assert state.files == {} and state.ledger_id == LEDGER_ID and state.heads() == {}


def test_deep_ledger_json_is_malformed_not_a_crash(tmp_path):
    # Break: catch only OSError and ValueError: json.loads raises RecursionError here.
    d = skeleton(tmp_path)
    (d / "ledger.json").write_text("[" * 200000 + "]" * 200000)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger.json", "line": None}


def test_unreadable_ledger_file_is_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: read the file outside a try: the PermissionError escapes verify_ledger.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    real_read_bytes = pathlib.Path.read_bytes

    def read_bytes(self):
        if self.name == f"{KEY16_A}.jsonl":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    [e] = errors_of(d)                                              # B's file still verifies: one error
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": FILE_A, "line": None}


def test_unreadable_ledger_directory_is_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: list ledger/ outside a try: the PermissionError escapes verify_ledger.
    d = skeleton(tmp_path)
    real_listdir = os.listdir

    def listdir(path="."):
        if pathlib.Path(path) == d / "ledger":
            raise PermissionError(13, "Permission denied", str(path))
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", listdir)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger", "line": None}


def test_unstattable_paths_under_the_ledger_are_malformed_not_a_crash(tmp_path, monkeypatch):
    # Break: call Path.is_symlink, is_file or is_dir bare in verify_ledger: Python 3.12 raises there.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    blocked = refuse_stat(monkeypatch)
    blocked.add(d / FILE_A)
    [e] = errors_of(d)                                              # B's file still verifies: one error
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": FILE_A, "line": None}
    blocked.clear()
    blocked.add(d / "ledger")
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "ledger", "line": None}


def test_allowed_signers_faults_carry_file_and_line(tmp_path):
    d = skeleton(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB) + f'b valid-before="20300101" ssh-ed25519 {PUB_B.read_text().split()[1]}\n')
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "allowed_signers", "line": 2}
    assert "valid-before" in e.message


def test_allowed_signers_not_utf8_names_the_line_of_the_first_bad_byte(tmp_path):
    # Break: leave line None, count every newline in the file, or drop the + 1.
    d = skeleton(tmp_path)
    (d / "allowed_signers").write_bytes(allowed_signers_line("a", A_BLOB).encode("ascii") + b"# \xff\n"
                                        + allowed_signers_line("b", B_BLOB).encode("ascii"))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": "allowed_signers", "line": 2}


def test_bad_file_names_and_symlinks_are_malformed(tmp_path):
    # Break: follow the symlink. Its target is an empty file outside ledger/, which is intact, so a
    # verifier that follows the link reports nothing for ledger/<B>.jsonl.
    d = skeleton(tmp_path)
    (d / "ledger" / "notes.txt").write_text("x")
    (d / "ledger" / (KEY16_A.upper() + ".jsonl")).write_bytes(b"")
    (d / "ledger" / ".DS_Store").write_bytes(b"")
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").symlink_to(outside)
    errs = errors_of(d)
    assert {e.code for e in errs} == {LC.LEDGER_MALFORMED}
    assert sorted(e.context["file"] for e in errs) == sorted([
        "ledger/.DS_Store", "ledger/notes.txt", f"ledger/{KEY16_A.upper()}.jsonl", f"ledger/{KEY16_B}.jsonl"])


def test_empty_file_is_intact_and_holds_no_entries(tmp_path):
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    state = verify_ledger(d)
    assert state.files == {KEY16_A: []} and state.heads() == {KEY16_A: {"entries": 0, "head": ""}}
    assert integrity_report(state)["entries"] == 0 and integrity_report(state)["admitted"] is None


def test_bom_crlf_and_missing_final_newline_are_malformed(tmp_path):
    # Break: decode with utf-8-sig; rstrip("\r\n"); accept a last line without "\n".
    d = skeleton(tmp_path)
    line = canon(entry())
    for name, data, lineno in (("bom", b"\xef\xbb\xbf" + line + b"\n", 1), ("crlf", line + b"\r\n", 1),
                               ("no newline", line + b"\n" + line, 2), ("blank", b"\n" + line + b"\n", 1)):
        (d / FILE_A).write_bytes(data)
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context == {"file": FILE_A, "line": lineno}, name


def test_shape_and_character_faults_at_integrity_keep_version_and_wrong_ledger_codes(tmp_path):
    d = skeleton(tmp_path)
    cases = [(LC.LEDGER_VERSION, entry(v=True)), (LC.LEDGER_VERSION, entry(v=1.0)),
             (LC.LEDGER_WRONG_LEDGER, entry(ledger="f" * 32))]
    for code, e in cases:
        (d / FILE_A).write_bytes(canon(e) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == code and errs[0].context["line"] == 1, code
        assert errs[0].fix == (1 if code == LC.LEDGER_VERSION else None), code   # refinement 14
    # Break: pass `fix=f.fix` through for every code: the surrogate case ships the cleaned value as a fix.
    for e in (entry(kind="rule"), entry(extra=1), {**entry(), "fact": entry()["fact"][:16] + ["\ud800"]},
              entry(ts="2026-02-30T00:00:00Z")):
        (d / FILE_A).write_bytes(canon(e) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context["file"] == FILE_A
        assert errs[0].fix is None, errs[0].field
    (d / FILE_A).write_bytes(canon(entry(kind="rule")) + b"\n")   # the unknown kind keeps its options (refinement 16)
    [e] = errors_of(d)
    assert e.options == ("axiom", "computed", "derived") and e.fix is None


def test_unparseable_sig_is_bad_signature_with_file_and_line(tmp_path):
    d = skeleton(tmp_path)
    for sig in ("U1NIU0lH", "", "U1NI-U0lH", "U1NIU0lH\n"):
        (d / FILE_A).write_bytes(canon(entry(sig=sig)) + b"\n")
        errs = errors_of(d)
        assert errs[0].code == LC.LEDGER_BAD_SIGNATURE and errs[0].context == {"file": FILE_A, "line": 1}, sig


def test_signers_pin_mismatch_fails_before_any_entry_is_read(tmp_path):
    # Break: check the pin after the files are read (the line error would appear too).
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"garbage\n")
    actual = hashlib.sha256((d / "allowed_signers").read_bytes()).hexdigest()
    errs = errors_of(d, expected_signers_sha256=actual)
    assert [e.code for e in errs] == [LC.LEDGER_MALFORMED]
    errs = errors_of(d, expected_signers_sha256="0" * 64)
    assert [e.code for e in errs] == [LC.LEDGER_SIGNERS_MISMATCH]
    assert errs[0].context["file"] == "allowed_signers" and errs[0].context["actual"] == actual


def test_signers_pin_mismatch_reads_no_file_and_marks_no_cache(tmp_path):
    # Break: compare the pin after the read loop, even if it still raises there: the empty file
    # verifies first and, with the cache on, is marked, so the cache directory appears.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    cache = tmp_path / "cache"
    errs = errors_of(d, expected_signers_sha256="0" * 64, cache_dir=cache, use_cache=True)
    assert [e.code for e in errs] == [LC.LEDGER_SIGNERS_MISMATCH]
    assert not cache.exists()
    verify_ledger(d, cache_dir=cache, use_cache=True)       # control: with no pin the same file is marked
    assert len(os.listdir(cache)) == 1


def test_cache_mark_failure_is_counted_not_raised(tmp_path, monkeypatch):
    # Break: let the OSError from writing a mark escape: an intact ledger then fails to load.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    (d / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"")
    not_a_dir = tmp_path / "cache-is-a-file"
    not_a_dir.write_bytes(b"")
    state = verify_ledger(d, cache_dir=not_a_dir, use_cache=True)      # mkdir raises FileExistsError
    assert sorted(state.files) == sorted([KEY16_A, KEY16_B]) and state.cache_mark_failures == 2
    assert integrity_report(state)["cache_mark_failures"] == 2
    _, report = load_store(LFIX, **BASE_FILES, ledger_dir=d, cache_dir=not_a_dir)     # use_cache is on by default
    assert (report["ledger"]["files"], report["ledger"]["cache_mark_failures"]) == (2, 2)
    cache = tmp_path / "cache"
    real_write_bytes = pathlib.Path.write_bytes

    def write_bytes(self, data):
        if self.parent == cache:
            raise PermissionError(13, "Permission denied", str(self))
        return real_write_bytes(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", write_bytes)
    state = verify_ledger(d, cache_dir=cache, use_cache=True)           # mkdir works, the mark does not
    assert state.cache_mark_failures == 2 and os.listdir(cache) == []
    assert verify_ledger(d, cache_dir=cache).cache_mark_failures == 0    # no cache in use: nothing to fail


def test_unstattable_cache_entry_is_a_miss_not_a_crash(tmp_path, monkeypatch):
    # Break: call Path.is_file bare in _cache_hit: Python 3.12 raises there.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    cache = tmp_path / "cache"
    assert verify_ledger(d, cache_dir=cache, use_cache=True).cache_mark_failures == 0    # a hit is there to find
    blocked = refuse_stat(monkeypatch)
    blocked.update(cache / name for name in os.listdir(cache))
    state = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert (sorted(state.files), state.files_verified_from_cache) == ([KEY16_A], 0)      # a miss, never a hit
    blocked.clear()
    assert verify_ledger(d, cache_dir=cache, use_cache=True).files_verified_from_cache == 1   # control: the hit


def test_signers_pin_is_compared_before_allowed_signers_is_parsed(tmp_path, monkeypatch):
    # Break: parse allowed_signers first and compare the pin after: a pinned consumer then gets
    # LEDGER_MALFORMED for a file it never pinned, and the parser runs on unpinned bytes.
    d = skeleton(tmp_path)
    for bad in (b'b valid-before="20300101" ssh-ed25519 AAAA\n', b"# \xff\n"):      # refused option; not UTF-8
        (d / "allowed_signers").write_bytes(bad)
        errs = errors_of(d, expected_signers_sha256="0" * 64)
        assert [e.code for e in errs] == [LC.LEDGER_SIGNERS_MISMATCH], bad
        assert errs[0].context["actual"] == hashlib.sha256(bad).hexdigest()
        pinned = errors_of(d, expected_signers_sha256=hashlib.sha256(bad).hexdigest())   # the right pin: parsed, refused
        assert [e.code for e in pinned] == [LC.LEDGER_MALFORMED], bad
    seen = []
    monkeypatch.setattr(integ, "parse_allowed_signers", lambda text: seen.append(text) or [])
    errors_of(d, expected_signers_sha256="0" * 64)
    assert seen == []


def test_no_home_directory_means_no_cache_not_a_traceback(tmp_path, monkeypatch):
    # Break: drop the RuntimeError catch in default_cache_dir. Path.home() raises it when HOME is
    # unset and the passwd database has no entry for the user.
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")

    def no_home(cls):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(pathlib.Path, "home", classmethod(no_home))
    assert integ.default_cache_dir() is None
    state = verify_ledger(d, use_cache=True)
    assert (sorted(state.files), state.files_verified_from_cache, state.cache_mark_failures) == ([KEY16_A], 0, 1)
    _, report = load_store(LFIX, **BASE_FILES, ledger_dir=d)                 # use_cache is on by default
    assert (report["ledger"]["files_verified_from_cache"], report["ledger"]["cache_mark_failures"]) == (0, 1)


def test_cache_dir_holding_a_nul_is_a_counted_mark_failure_not_a_crash(tmp_path):
    # Break: catch only OSError in _cache_mark: mkdir raises ValueError ("embedded null byte").
    d = skeleton(tmp_path)
    (d / FILE_A).write_bytes(b"")
    state = verify_ledger(d, cache_dir=tmp_path / "ca\x00che", use_cache=True)
    assert (sorted(state.files), state.files_verified_from_cache, state.cache_mark_failures) == ([KEY16_A], 0, 1)


def h(label):
    """A 64-hex stand-in for an entry hash: a heads map must carry the real form."""
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _state(tmp_path, files):
    d = tmp_path / "cur"
    (d / "ledger").mkdir(parents=True)
    state_files = {}
    for k, labels in files.items():
        (d / "ledger" / f"{k}.jsonl").write_bytes(b"".join(f"line-{x}\n".encode() for x in labels))
        state_files[k] = [LedgerEntry(f"ledger/{k}.jsonl", i, {"kind": "axiom"}, h(x)) for i, x in enumerate(labels, 1)]
    signers = parse_allowed_signers(allowed_signers_line("a", A_BLOB))
    return LedgerState(d, LEDGER_ID, signers, "0" * 64, state_files)


def test_check_extends_over_directories_and_heads_maps(tmp_path):
    # Break: compare entry counts only (the divergent-chain case then passes).
    state = _state(tmp_path, {KEY16_A: ["h1", "h2", "h3"], KEY16_B: ["g1"]})
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-h2\n")
    assert check_extends(state, older) == []
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-zz\n")
    [e] = check_extends(state, older)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_A}.jsonl"
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\nline-h2\nline-h3\nline-h4\n")
    assert [e.code for e in check_extends(state, older)] == [LC.LEDGER_ROLLBACK]
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 3, "head": h("h3")}, KEY16_B: {"entries": 1, "head": h("g1")}}))
    assert check_extends(state, heads) == []
    heads.write_text(json.dumps({KEY16_A: {"entries": 4, "head": h("h4")}}))
    assert [e.code for e in check_extends(state, heads)] == [LC.LEDGER_ROLLBACK]
    heads.write_text(json.dumps({KEY16_A: {"entries": 3, "head": h("other")}}))    # same count, other chain
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["older_head"] == h("other") and e.context["head"] == h("h3")
    heads.write_text(json.dumps({KEY16_A: {"entries": 0, "head": ""}}))
    assert check_extends(state, heads) == []


def test_deleted_file_fails_extends_unless_its_key_was_removed(tmp_path):
    # Break: drop `if k in listed` in either branch (the revoked key's deletion then fails).
    state = _state(tmp_path, {KEY16_A: ["h1"]})                                    # B's file is gone; A is listed, B is not
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}, KEY16_B: {"entries": 2, "head": h("g2")}}))
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_B}.jsonl").write_bytes(b"line-g1\n")
    assert check_extends(state, heads) == []                                        # B was revoked: the one allowed shrink
    assert check_extends(state, older) == []                                        # the same shrink, over a directory
    state.signers = parse_allowed_signers(allowed_signers_line("a", A_BLOB) + allowed_signers_line("b", B_BLOB))
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_B}.jsonl" and e.context["entries"] == 0
    assert [e.code for e in check_extends(state, older)] == [LC.LEDGER_ROLLBACK]


def test_check_extends_refuses_a_path_that_is_neither(tmp_path):
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    (tmp_path / "junk.json").write_text("[1, 2]")
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "junk.json")
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "does-not-exist")
    (tmp_path / "nodir").mkdir()
    with pytest.raises(ValueError):
        check_extends(state, tmp_path / "nodir")


def test_check_extends_turns_unreadable_or_deep_input_into_value_error(tmp_path, monkeypatch):
    # Break: catch only ValueError around the heads map, or read the older tree outside a try.
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 200000 + "]" * 200000)
    with pytest.raises(ValueError, match="RecursionError"):
        check_extends(state, deep)
    older = tmp_path / "older"
    (older / "ledger" / f"{KEY16_A}.jsonl").mkdir(parents=True)            # a directory with a ledger file's name
    with pytest.raises(ValueError, match="IsADirectoryError"):
        check_extends(state, older)
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}}))
    assert check_extends(state, heads) == []
    real_read_text = pathlib.Path.read_text

    def read_text(self, *args, **kwargs):
        if self == heads:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    with pytest.raises(ValueError, match="PermissionError"):
        check_extends(state, heads)


def test_check_extends_unstattable_paths_raise_value_error_or_fail_closed(tmp_path, monkeypatch):
    # Break: call Path.is_dir or is_file bare in check_extends: Python 3.12 raises there.
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    older = tmp_path / "older"
    (older / "ledger").mkdir(parents=True)
    (older / "ledger" / f"{KEY16_A}.jsonl").write_bytes(b"line-h1\n")
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 1, "head": h("h1")}}))
    assert check_extends(state, older) == [] and check_extends(state, heads) == []
    blocked = refuse_stat(monkeypatch)
    for target, arg in ((older, older), (older / "ledger", older), (heads, heads)):
        blocked.clear()
        blocked.add(target)
        with pytest.raises(ValueError):
            check_extends(state, arg)
    blocked.clear()
    blocked.add(state.ledger_dir / "ledger" / f"{KEY16_A}.jsonl")          # the current file of a listed key
    [e] = check_extends(state, older)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_A}.jsonl"


def test_check_extends_validates_the_heads_map(tmp_path):
    # Break: drop the heads-map validation (each map below then passes or crashes).
    state = _state(tmp_path, {KEY16_A: ["h1"]})
    heads = tmp_path / "heads.json"
    good = {"entries": 1, "head": h("h1")}
    for bad in ({KEY16_A.upper(): good}, {KEY16_A[:15]: good}, {"../" + KEY16_A[3:]: good},
                {KEY16_A: {"entries": -1, "head": ""}}, {KEY16_A: {"entries": -1, "head": h("h1")}},
                {KEY16_A: {"entries": True, "head": h("h1")}},
                {KEY16_A: {"entries": 1.0, "head": h("h1")}}, {KEY16_A: {"entries": 0, "head": h("h1")}},
                {KEY16_A: {"entries": 1, "head": ""}}, {KEY16_A: {"entries": 1, "head": "h1"}},
                {KEY16_A: {"entries": 1, "head": h("h1").upper()}}, {KEY16_A: {"entries": 1, "head": h("h1") + "\n"}},
                {KEY16_A: {**good, "extra": 1}}, {KEY16_A: [1, h("h1")]}, [good]):
        heads.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            check_extends(state, heads)
    for ok in ({}, {KEY16_A: good}, {KEY16_A: {"entries": 0, "head": ""}}, {KEY16_B: {"entries": 0, "head": ""}}):
        heads.write_text(json.dumps(ok))
        assert check_extends(state, heads) == [], ok


def test_cache_key_includes_file_name_signers_and_verifier_version(monkeypatch):
    # Break: leave the file name out (a byte-identical copy under another name would hit).
    a = cache_key(LEDGER_ID, "a.jsonl", b"data", "s" * 64)
    assert a != cache_key(LEDGER_ID, "b.jsonl", b"data", "s" * 64)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data!", "s" * 64)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data", "t" * 64)
    assert a != cache_key("f" * 32, "a.jsonl", b"data", "s" * 64)
    monkeypatch.setattr(integ, "LEDGER_VERIFIER_VERSION", 999)
    assert a != cache_key(LEDGER_ID, "a.jsonl", b"data", "s" * 64)
    assert len(a) == 64


def test_integrity_report_has_null_base_counters(tmp_path):
    state = _state(tmp_path, {KEY16_A: ["h1", "h2"]})
    r = integrity_report(state)
    assert (r["files"], r["entries"], r["axioms"], r["derived"], r["computed"]) == (1, 2, 2, 0, 0)
    for k in ("admitted", "rechecked_ok", "stale", "stale_entries", "superseded_by_base", "superseded_entries",
              "duplicate_content", "duplicate_content_entries", "contested", "contested_entries",
              "derived_rechecked", "derived_failed", "derived_failed_entries"):
        assert r[k] is None, k
    assert r["heads"] == {KEY16_A: {"entries": 2, "head": h("h2")}} and r["files_verified_from_cache"] == 0
    assert r["cache_mark_failures"] == 0
    assert r["allowed_signers_sha256"] == "0" * 64


# ---------------------------------------------------------------------------
# over the signed fixture ledger (made once by make_fixtures.py)
# ---------------------------------------------------------------------------
import base64

from methods_graph.biolean.ledger.format import entry_hash, parse_line
from tests.biolean_ledger_fixture import DIGEST_B, LFIX, copy_signed


def _lines(d, k=KEY16_A):
    return (d / f"ledger/{k}.jsonl").read_bytes().split(b"\n")[:-1]


def _write(d, lines, k=KEY16_A):
    (d / f"ledger/{k}.jsonl").write_bytes(b"".join(l + b"\n" for l in lines))


def test_signed_fixture_ledger_verifies_and_reports_heads(tmp_path):
    d = copy_signed(tmp_path)
    state = verify_ledger(d)
    assert {k: len(v) for k, v in state.files.items()} == {KEY16_A: 4, KEY16_B: 1}
    assert [e.entry["kind"] for e in state.files[KEY16_A]] == ["axiom", "axiom", "axiom", "derived"]
    assert state.heads()[KEY16_A]["head"] == state.files[KEY16_A][-1].hash
    assert state.entries()[0].file == f"ledger/{KEY16_A}.jsonl" and state.files_verified_from_cache == 0


def test_repeated_row_in_one_file_is_invalid_not_a_crash(tmp_path, monkeypatch):
    # Break: drop `seen_ids` from step 7. The pair then passes integrity and the loader dies in
    # StaticFactStore with a bare ValueError on the duplicate annotation id.
    monkeypatch.setattr(integ, "verify_sshsig", lambda *a, **k: None)     # the repeat is hand-signed here
    d = copy_signed(tmp_path)
    first, _ = parse_line(_lines(d)[0] + b"\n")
    second = dict(first, prev=entry_hash(first))
    _write(d, [canon(first), canon(second)])
    [e] = errors_of(d)
    assert (e.code, e.field, e.context["line"], e.context["first_line"]) == (LC.LEDGER_INVALID_ENTRY, "/fact", 2, 1)
    assert e.got == first["fact"] and e.context["annotation_id"] == first["check"]["annotation_id"]
    _write(d, [canon(first)])
    assert len(verify_ledger(d).entries()) == 2                            # B's file is untouched


def test_one_byte_change_in_a_signed_entry_fails(tmp_path):
    # Every field is covered by the signature; sig itself by the canonical base64 rule.
    d = copy_signed(tmp_path)
    original = _lines(d)
    line = original[0]
    obj, _ = parse_line(line + b"\n")
    for field_ in ("ts", "prev", "by", "ledger", "v", "kind"):
        pos = line.index(f'"{field_}":'.encode()) + len(field_) + 3
        mutated = bytearray(line)
        mutated[pos + 1] ^= 0x01
        _write(d, [bytes(mutated)] + original[1:])
        errs = errors_of(d)
        assert errs[0].context["file"] == FILE_A and errs[0].context["line"] == 1, field_
    fact_pos = line.index(b'"fact":["UniProtKB"') + len(b'"fact":["')
    mutated = bytearray(line)
    mutated[fact_pos] = ord("u")
    _write(d, [bytes(mutated)] + original[1:])
    assert errors_of(d)[0].code == LC.LEDGER_BAD_SIGNATURE
    # a padding-bit change inside sig: same decoded bytes, refused by the canonical base64 rule
    sig = obj["sig"]
    assert sig.endswith("==") or sig.endswith("=")
    last = sig.rstrip("=")[-1]
    alt = chr(ord(last) + 1) if last not in ("9", "z", "Z", "/") else chr(ord(last) - 1)
    mutated_sig = sig.rstrip("=")[:-1] + alt + sig[len(sig.rstrip("=")):]
    assert base64.b64decode(mutated_sig) == base64.b64decode(sig)          # same bytes: only the padding bits differ
    obj2 = dict(obj, sig=mutated_sig)
    _write(d, [canon(obj2)] + original[1:])
    assert errors_of(d)[0].code == LC.LEDGER_BAD_SIGNATURE


def test_reordered_keys_are_malformed(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    reordered = json.dumps(obj, separators=(",", ":"), sort_keys=False).encode()
    reordered = b'{"kind":"axiom",' + reordered[1:].replace(b'"kind":"axiom",', b"", 1)
    assert reordered != original[0] and json.loads(reordered) == obj
    _write(d, [reordered] + original[1:])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_MALFORMED and errs[0].context == {"file": FILE_A, "line": 1}


def test_missing_middle_entry_breaks_chain(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    _write(d, [original[0], original[2], original[3]])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_CHAIN_BROKEN and e.context["line"] == 2 and e.field == "/prev"
    assert e.context["expected_prev"] == entry_hash(parse_line(original[0] + b"\n")[0])
    assert "fork_of_line" not in e.context


def test_fork_is_a_chain_break(tmp_path):
    d = copy_signed(tmp_path)
    fork = (LFIX / "signed-variants" / "fork.jsonl").read_bytes()
    (d / FILE_A).write_bytes(fork)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_CHAIN_BROKEN and e.context["line"] == 4 and e.context["fork_of_line"] == 1
    assert e.got == entry_hash(parse_line(fork.split(b"\n")[0] + b"\n")[0])


def test_unlisted_key_is_unknown_signer(tmp_path):
    d = copy_signed(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_UNKNOWN_SIGNER and e.context["file"] == f"ledger/{KEY16_B}.jsonl"
    assert "SHA256:d4tcaq5zba2R6DiyGsGGv4WQxkz5TnPbHCfGnFPeNNA" in e.message and DIGEST_B in e.message


def test_by_must_match_embedded_key_and_filename(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    _write(d, [canon(dict(obj, by=BY_A[:-4] + "0000"))] + original[1:])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["embedded_key"] == BY_A
    d2 = copy_signed(tmp_path / "two")
    (d2 / f"ledger/{KEY16_B}.jsonl").write_bytes((d2 / FILE_A).read_bytes())     # A's chain under B's name
    errs = errors_of(d2)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["file"] == f"ledger/{KEY16_B}.jsonl"


def test_another_keys_line_in_a_file_is_signer_mismatch(tmp_path):
    # the file-name clause of step 3: B's real entry appended to A's file fails at `by` before any
    # chain check (appending it with A's head as prev is not possible without B's key anyway)
    d = copy_signed(tmp_path)
    _write(d, _lines(d) + [_lines(d, KEY16_B)[0]])
    errs = errors_of(d)
    assert errs[0].code == LC.LEDGER_SIGNER_MISMATCH and errs[0].context["line"] == 5


def test_all_entries_in_a_file_share_by(tmp_path, monkeypatch):
    # The same-`by` clause of step 3. A real key16 collision needs a 2^64 grind, so simulate one:
    # B's key digest is made to start with A's key16. B's line then passes "by == embedded key"
    # and "key16 == file name", and only the same-`by` clause refuses it.
    # Break: drop `or (by is not None and obj["by"] != by)`: the line reaches step 5, BAD_SIGNATURE.
    d = copy_signed(tmp_path)
    obj_b, _ = parse_line(_lines(d, KEY16_B)[0] + b"\n")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()                   # the patched digest would fail B's own file too
    fake_b = KEY16_A + DIGEST_B[16:]
    real = integ.key_digest
    monkeypatch.setattr(integ, "key_digest", lambda blob: fake_b if real(blob) == DIGEST_B else real(blob))
    _write(d, _lines(d) + [canon(dict(obj_b, by="sha256:" + fake_b))])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_SIGNER_MISMATCH and e.context["line"] == 5
    assert e.got == e.context["embedded_key"] == "sha256:" + fake_b   # clauses 1 and 2 held; clause 3 refused


def test_second_key_signature_is_signer_mismatch_or_unknown(tmp_path):
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj_a, _ = parse_line(original[0] + b"\n")
    obj_b, _ = parse_line(_lines(d, KEY16_B)[0] + b"\n")
    _write(d, [canon(dict(obj_a, sig=obj_b["sig"]))] + original[1:])        # B's real signature, by names A
    assert errors_of(d)[0].code == LC.LEDGER_SIGNER_MISMATCH
    d2 = copy_signed(tmp_path / "two")
    (d2 / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    assert errors_of(d2)[0].code == LC.LEDGER_UNKNOWN_SIGNER                  # by names B, B absent


def test_unsupported_allowed_signers_option_refuses_to_load(tmp_path):
    d = copy_signed(tmp_path)
    text = (d / "allowed_signers").read_text().replace('namespaces="biolean-ledger" ssh-ed25519', 'namespaces="biolean-ledger",valid-before="20300101" ssh-ed25519', 1)
    (d / "allowed_signers").write_text(text)
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "allowed_signers" and "valid-before" in e.message


def test_removed_key_fails_whole_ledger_until_its_file_is_deleted(tmp_path):
    # Catches an implementation that skips the unlisted file and loads the rest.
    d = copy_signed(tmp_path)
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d)
    assert [e.code for e in exc.value.errors] == [LC.LEDGER_UNKNOWN_SIGNER]
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    state = verify_ledger(d)
    assert set(state.files) == {KEY16_A} and len(state.files[KEY16_A]) == 4


def test_truncated_tail_passes_integrity_and_fails_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    original = _lines(d)
    _write(d, original[:3])
    state = verify_ledger(d)
    assert len(state.files[KEY16_A]) == 3
    assert [e.code for e in check_extends(state, full)] == [LC.LEDGER_ROLLBACK]
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps(verify_ledger(full).heads()))
    [e] = check_extends(state, heads)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["older_entries"] == 4 and e.context["entries"] == 3


def test_deleted_file_fails_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    state = verify_ledger(d)
    [e] = check_extends(state, full)
    assert e.code == LC.LEDGER_ROLLBACK and e.context["file"] == f"ledger/{KEY16_B}.jsonl"


def test_revoked_key_file_deletion_passes_extends(tmp_path):
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    (d / f"ledger/{KEY16_B}.jsonl").unlink()
    (d / "allowed_signers").write_text(allowed_signers_line("a", A_BLOB))
    state = verify_ledger(d)
    assert check_extends(state, full) == []


def test_divergent_chain_substituted_fails_extends(tmp_path):
    # Same key, same count, a different entry at that position. Catches a count-only check.
    d = copy_signed(tmp_path)
    full = copy_signed(tmp_path / "full")
    fork = (LFIX / "signed-variants" / "fork.jsonl").read_bytes().split(b"\n")[:-1]
    _write(d, fork[:1] + fork[3:4])          # entries 1 and 4 (4's prev is 1's hash): a valid 2-entry chain
    state = verify_ledger(d)
    assert len(state.files[KEY16_A]) == 2
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: {"entries": 2, "head": verify_ledger(full).files[KEY16_A][1].hash}}))
    assert [e.code for e in check_extends(state, heads)] == [LC.LEDGER_ROLLBACK]
    assert [e.code for e in check_extends(state, full)] == [LC.LEDGER_ROLLBACK]


def test_signed_entry_with_bad_character_fails_integrity_not_crash(tmp_path):
    d = copy_signed(tmp_path)
    (d / FILE_A).write_bytes((LFIX / "signed-variants" / "surrogate.jsonl").read_bytes())
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_MALFORMED and e.context["line"] == 1 and "U+D800" in e.message


def test_check_annotation_id_recomputed(tmp_path):
    d = copy_signed(tmp_path)
    (d / FILE_A).write_bytes((LFIX / "signed-variants" / "bad-annotation-id.jsonl").read_bytes())
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_INVALID_ENTRY and e.field == "/check/annotation_id" and e.context["line"] == 1


def test_chain_from_another_ledger_is_wrong_ledger(tmp_path):
    d = copy_signed(tmp_path)
    (d / "ledger.json").write_text(json.dumps({"ledger": "f" * 32}))
    errs = errors_of(d)
    assert {e.code for e in errs} == {LC.LEDGER_WRONG_LEDGER} and {e.context["line"] for e in errs} == {1}


def test_key16_collision_refused(tmp_path):
    d = copy_signed(tmp_path)
    text = (d / "allowed_signers").read_text()
    (d / "allowed_signers").write_text(text + allowed_signers_line("again", A_BLOB))
    assert errors_of(d)[0].code == LC.LEDGER_MALFORMED


def test_s_plus_l_signature_is_rejected_here_though_openssh_accepts_it(tmp_path):
    from methods_graph.biolean.ed25519 import L
    d = copy_signed(tmp_path)
    original = _lines(d)
    obj, _ = parse_line(original[0] + b"\n")
    blob = bytearray(base64.b64decode(obj["sig"]))
    s = int.from_bytes(blob[-32:], "little") + L
    blob[-32:] = s.to_bytes(32, "little")
    _write(d, [canon(dict(obj, sig=base64.b64encode(bytes(blob)).decode()))] + original[1:])
    [e] = errors_of(d)
    assert e.code == LC.LEDGER_BAD_SIGNATURE and "verify" in e.message


def test_verify_from_cache_is_reported_and_bypassable(tmp_path):
    d = copy_signed(tmp_path)
    cache = tmp_path / "cache"
    s1 = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert s1.files_verified_from_cache == 0 and len(list(cache.iterdir())) == 2
    s2 = verify_ledger(d, cache_dir=cache, use_cache=True)
    assert s2.files_verified_from_cache == 2 and s2.heads() == s1.heads()
    assert verify_ledger(d, cache_dir=cache, use_cache=False).files_verified_from_cache == 0
    assert verify_ledger(d).files_verified_from_cache == 0


def test_cache_hit_still_binds_the_file_name_to_its_content_at_step_3(tmp_path):
    # A byte-identical copy of A's file under B's name, with a cache mark planted for exactly that
    # name and those bytes, so the copy is a hit and step 5 is skipped. Step 3 still runs and ties
    # the file name to the signing key: LEDGER_SIGNER_MISMATCH. Break: skip step 3 on a hit. (The
    # file name inside the cache key, which keeps an honest cache from hitting here at all, is
    # pinned by test_cache_key_includes_file_name_signers_and_verifier_version, not by this test.)
    d = copy_signed(tmp_path)
    cache = tmp_path / "cache"
    verify_ledger(d, cache_dir=cache, use_cache=True)
    data = (d / FILE_A).read_bytes()
    (d / f"ledger/{KEY16_B}.jsonl").write_bytes(data)
    signers_sha = hashlib.sha256((d / "allowed_signers").read_bytes()).hexdigest()
    (cache / cache_key(LEDGER_ID, f"{KEY16_B}.jsonl", data, signers_sha)).write_bytes(b"")
    with pytest.raises(LedgerIntegrityError) as exc:
        verify_ledger(d, cache_dir=cache, use_cache=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_SIGNER_MISMATCH and e.context["file"] == f"ledger/{KEY16_B}.jsonl"


def test_cache_path_outside_ledger_dir(tmp_path, monkeypatch):
    d = copy_signed(tmp_path / "L")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))                    # restored after the test, like conftest's
    verify_ledger(d, use_cache=True)
    assert (home / ".cache" / "biolean-ledger").is_dir()
    assert not any(p.name == ".cache" for p in d.rglob("*"))
