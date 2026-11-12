"""`mg biolean ledger init|append|verify|show`, `--ledger` on prove|check|goals, exit codes, JSON contract."""
import hashlib
import json
import pathlib
from pathlib import Path

import pytest

from methods_graph import cli
from methods_graph.biolean.ledger.errors import LedgerCode as LC
from methods_graph.biolean.ledger.format import canon
from methods_graph.biolean.ledger.integrity import cache_key, verify_ledger
from methods_graph.biolean.props import Annotation, Term
from methods_graph.biolean.sshsig import fingerprint, parse_public_key_line
from methods_graph.biolean.store import StaticFactStore
from tests.biolean_ledger_fixture import (
    DIGEST_A, KEY16_A, KEY16_B, KEY_A, LEDGER_ID, PUB_A, PUB_B, SCENARIOS, TS, copy_ledger_store, copy_signed,
    fake_runner, fresh_ledger, new_fact, signed_store)

FP_A = fingerprint(parse_public_key_line(PUB_A.read_text())[0])
FP_B = fingerprint(parse_public_key_line(PUB_B.read_text())[0])

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    monkeypatch.setattr("subprocess.run", fake_runner)
    monkeypatch.setattr(cli, "_ledger_now", lambda: TS)
    from methods_graph.biolean import sshsig
    from methods_graph.biolean.ledger import append as append_mod
    monkeypatch.setattr(sshsig, "FIXTURE_KEY_DIGESTS", frozenset())        # init may use the fixture keys here
    monkeypatch.setattr(append_mod, "FIXTURE_KEY_DIGESTS", frozenset())


def _json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def _lines(text):
    return [json.loads(line) for line in text.splitlines()]


def test_gitignore_ignores_a_ledger_clone_at_the_root():
    assert "/biolean-ledger/" in (ROOT / ".gitignore").read_text().splitlines()


def test_init_writes_files_and_prints_json(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    rc = cli.main(["biolean", "ledger", "init", "--ledger", str(tmp_path / "L"), "--store", str(store),
                   "--key", str(PUB_A), "--principal", "manu"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["key16"] == KEY16_A and out["by"] == "sha256:" + DIGEST_A and len(out["ledger"]) == 32
    assert (tmp_path / "L" / "ledger").is_dir() and (tmp_path / "L" / "base.json").exists()
    rc = cli.main(["biolean", "ledger", "init", "--ledger", str(tmp_path / "L"), "--store", str(store), "--key", str(PUB_A)])
    out = _json(capsys.readouterr().out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_MALFORMED


def test_append_accepts_and_rejects_with_exit_codes(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    ledger = fresh_ledger(tmp_path / "L", store)
    body = json.dumps(SCENARIOS["cli-fresh-axiom"].body)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", body, "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "ACCEPTED" and out["line"] == 1 and out["file"] == f"ledger/{KEY16_A}.jsonl"
    assert out["entry"]["ts"] == TS and len(out["hash"]) == 64
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact(go_id="GO:0009999")), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 3 and out["verdict"] == "REJECTED"
    assert [(e["code"], e["field"]) for e in out["errors"]] == [(LC.UNKNOWN_TERM, "/fact/4")]
    assert out["deferred"] == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]
    assert set(out["errors"][0]) == {"code", "message", "field", "got", "fix", "options", "context"}
    # @file body, and the same fact again is LEDGER_DUPLICATE (terminal)
    p = tmp_path / "fact.json"
    p.write_text(body)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", "@" + str(p), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 3 and out["errors"][0]["code"] == LC.LEDGER_DUPLICATE and out["errors"][0]["fix"] is None


def test_append_exit_2_conditions_print_json_errors_on_stdout(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact()), "--no-cache"])
    captured = capsys.readouterr()
    out = _json(captured.out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_MALFORMED and "load_report" not in captured.err
    ledger, store = signed_store(tmp_path / "two")
    (store / "gaf-eco-mapping.txt").write_text("# changed\nIDA\tDefault\tECO:0000314\n")
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(new_fact()), "--no-cache"])
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BASE_MISMATCH
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", "not json", "--no-cache"])                # spec section 2 order: the base mismatch still wins
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BASE_MISMATCH
    with pytest.raises(SystemExit):
        cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A)])


def test_append_body_that_is_not_json_is_rejected_not_a_usage_error(tmp_path, capsys):
    # Break: `_ledger_body` calling `parser.error` on a JSONDecodeError (SystemExit 2, text on stderr).
    ledger, store = signed_store(tmp_path)
    for flag, field in (("--fact", "/fact"), ("--derivation", "/derivation"), ("--computed", None)):
        rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                       flag, "not json", "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert rc == 3 and out["verdict"] == "REJECTED" and out["deferred"] == [], flag
        assert (out["errors"][0]["code"], out["errors"][0]["field"], out["errors"][0]["got"]) == (LC.LEDGER_BAD_BODY, field, "not json")
        assert [e["code"] for e in out["errors"][1:]] == ([LC.NOT_YET_DISCHARGEABLE] if flag == "--computed" else [])
    assert len(verify_ledger(ledger).entries()) == 5                                  # nothing was written


def test_append_body_too_deep_or_with_a_nan_literal_is_a_bad_body(tmp_path, capsys):
    # Break: drop the RecursionError catch in `_ledger_body` (the deep body raises out of main);
    # drop `parse_constant` (NaN and Infinity reach append_entry, which reports got null, not the text).
    # 1,000,000 deep, not 100,000: Python 3.14 bounds the JSON scanner by the C stack, not the
    # recursion limit, and reads 100,000 unclosed brackets to a plain JSONDecodeError.
    ledger, store = signed_store(tmp_path)
    for text in ("[" * 1_000_000, "NaN", '["x", Infinity]'):
        rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                       "--fact", text, "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert rc == 3 and [(e["code"], e["field"], e["got"]) for e in out["errors"]] == [
            (LC.LEDGER_BAD_BODY, "/fact", text)], text[:20]
    assert len(verify_ledger(ledger).entries()) == 5


def test_append_body_file_that_cannot_be_read_is_a_usage_error(tmp_path, capsys):
    # Break: catch only OSError around the @path read (a non-UTF-8 file raises UnicodeDecodeError).
    ledger, store = signed_store(tmp_path)
    (tmp_path / "latin1.json").write_bytes(b'["\xe9"]')
    for bad in (tmp_path / "missing.json", tmp_path / "latin1.json"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                      "--fact", "@" + str(bad), "--no-cache"])
        assert exc.value.code == 2 and str(bad) in capsys.readouterr().err


def test_printed_json_is_ascii_even_when_an_error_carries_a_lone_surrogate(tmp_path, capsys):
    # Break: `ensure_ascii=False` in the ledger subcommand's JSON printer (the lone surrogate in
    # `field` cannot be written as UTF-8, so the print raises).
    ledger, store = signed_store(tmp_path)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--derivation", json.dumps({"\ud800": "\ud800"}), "--no-cache"])
    text = capsys.readouterr().out
    assert text.isascii()
    out = _json(text)
    assert rc == 3 and [(e["code"], e["field"]) for e in out["errors"]] == [
        (LC.LEDGER_BAD_CHARACTER, ""), (LC.LEDGER_BAD_CHARACTER, "/\ud800")]      # the key, then the value under it


def test_key_that_names_no_file_is_unsupported_key_json_not_a_traceback(tmp_path, capsys):
    # Break: a bare `key.with_name(key.name + ".pub")` in read_signer (Path("") has an empty name:
    # ValueError escapes main). An unset shell variable gives --key "".
    ledger, store = signed_store(tmp_path)
    before = verify_ledger(ledger).heads()
    for key in ("", ".", "/"):
        for argv in (["biolean", "ledger", "init", "--ledger", str(tmp_path / "new"), "--store", str(store), "--key", key],
                     ["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", key,
                      "--fact", json.dumps(new_fact()), "--no-cache"]):
            rc = cli.main(argv)
            out = _json(capsys.readouterr().out)
            assert rc == 2 and [e["code"] for e in out["errors"]] == [LC.LEDGER_UNSUPPORTED_KEY], (key, argv[2])
    assert not (tmp_path / "new").exists() and verify_ledger(ledger).heads() == before


def test_show_by_takes_only_a_key16(tmp_path, capsys):
    # Break: drop the --by check (exit 0 and no rows: a by value or a fingerprint silently matches nothing).
    ledger, _ = signed_store(tmp_path)
    for bad in ("sha256:" + DIGEST_A, FP_A, KEY16_A.upper(), KEY16_A[:15], KEY16_A + "\n"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--by", bad])
        assert exc.value.code == 2 and "--by" in capsys.readouterr().err, bad


def test_show_reports_cache_marks_it_could_not_write_on_stderr(tmp_path, capsys):
    # Break: drop the stderr line (the count of failed marks is then never surfaced by show).
    ledger, store = signed_store(tmp_path)
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--no-cache"]) == 0
    rows = capsys.readouterr().out
    good = tmp_path / "cache"
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(good)]) == 0
    captured = capsys.readouterr()
    assert captured.out == rows and captured.err == ""                     # marks written: nothing to say
    not_a_dir = tmp_path / "cache-file"
    not_a_dir.write_bytes(b"")
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(not_a_dir)]) == 0
    captured = capsys.readouterr()
    assert captured.out == rows and captured.err == "cache: 2 mark(s) could not be written\n"


def test_a_store_stat_that_raises_is_a_usage_error(tmp_path, capsys, monkeypatch):
    # Python 3.12 raises PermissionError from Path.exists on EACCES (3.13+ returns False). Break: a
    # bare exists() in `_require_store` or in `_biolean_gaf_name` (the PermissionError escapes main).
    ledger, store = signed_store(tmp_path)

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(pathlib.Path, "exists", denied)
    for argv in (["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store)],
                 ["biolean", "prove", "UniProtKB:P10002 involved_in GO:0000003", "--store", str(store)]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2 and "lacks" in capsys.readouterr().err, argv[1]


def test_verify_without_store_is_integrity_only_and_with_store_reports(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger)])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert out["ledger"]["entries"] == 5 and out["ledger"]["admitted"] is None and out["ledger"]["derived_rechecked"] is None
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store), "--recheck", "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and out["ledger"]["admitted"] == 4 and out["ledger"]["derived_rechecked"] == 1 and out["ledger"]["derived_failed"] == 0
    with pytest.raises(SystemExit) as exc:
        cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--recheck"])
    assert exc.value.code == 2
    actual = out["ledger"]["allowed_signers_sha256"]
    assert cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--signers-sha256", actual]) == 0
    capsys.readouterr()
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--signers-sha256", "0" * 64])
    assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_SIGNERS_MISMATCH
    full = copy_signed(tmp_path / "full")
    (ledger / f"ledger/{KEY16_B}.jsonl").unlink()
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(full)])
    out = _json(capsys.readouterr().out)
    assert rc == 2 and out["errors"][0]["code"] == LC.LEDGER_ROLLBACK
    heads = tmp_path / "heads.json"
    heads.write_text(json.dumps({KEY16_A: verify_ledger(ledger).heads()[KEY16_A]}))        # B's file is gone but B is listed...
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(heads)])
    assert rc == 0 and _json(capsys.readouterr().out)["ok"] is True                        # ...and a heads map that omits B says nothing about it


def test_extends_with_a_bad_path_is_a_usage_error(tmp_path, capsys):
    ledger, _ = signed_store(tmp_path)
    (tmp_path / "junk.json").write_text("[1]")
    for bad in (tmp_path / "junk.json", tmp_path / "missing"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--extends", str(bad)])
        assert exc.value.code == 2
        assert "extends" in capsys.readouterr().err


def test_unreadable_store_is_exit_2_json_not_a_traceback(tmp_path, capsys):
    # Break: drop the BASE_READ_ERRORS wrap in load_with_ledger (EOFError escapes as a traceback);
    # drop `zlib.error` from the tuple (the corrupt-deflate case escapes); call base_object after
    # mkdir in init_ledger (the failed init leaves a directory behind).
    import gzip
    ledger, store = signed_store(tmp_path)
    (store / "goa_human.gaf").unlink()
    good = gzip.compress(b"x" * 2000, mtime=0)
    for name, damage in (("truncated", b"\x1f\x8b\x08garbage"), ("corrupt deflate", good[:10] + b"\xff" * 20 + good[30:])):
        (store / "goa_human.gaf.gz").write_bytes(damage)
        for argv in (["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                      "--fact", json.dumps(new_fact()), "--no-cache"],
                     ["biolean", "ledger", "verify", "--ledger", str(ledger), "--store", str(store), "--no-cache"],
                     ["biolean", "ledger", "init", "--ledger", str(tmp_path / "new"), "--store", str(store), "--key", str(PUB_A)],
                     ["biolean", "prove", "UniProtKB:P10002 involved_in GO:0000003", "--store", str(store),
                      "--ledger", str(ledger), "--no-cache"]):
            rc = cli.main(argv)
            [err] = _json(capsys.readouterr().out)["errors"]
            assert rc == 2 and err["code"] == LC.LEDGER_MALFORMED and err["context"]["file"] == str(store), (name, argv[2])
    assert not (tmp_path / "new").exists()                                        # init wrote nothing


def test_verify_never_reads_the_cache_even_when_show_does(tmp_path, capsys):
    # Break: `use_cache=not args.no_cache` (or dropping the `cmd == "show"` guard) on either verify path.
    ledger, store = signed_store(tmp_path)
    path = ledger / f"ledger/{KEY16_A}.jsonl"
    lines = path.read_bytes().split(b"\n")[:-1]
    obj = json.loads(lines[0])
    sig = obj["sig"]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    obj["sig"] = sig[:200] + alphabet[(alphabet.index(sig[200]) + 1) % 64] + sig[201:]   # inside the signature bytes
    forged = b"".join(l + b"\n" for l in [canon(obj)] + lines[1:])                     # the hash excludes sig: chain intact
    path.write_bytes(forged)
    signers = hashlib.sha256((ledger / "allowed_signers").read_bytes()).hexdigest()
    cache = tmp_path / "cache"
    for c in (cache, tmp_path / ".cache" / "biolean-ledger"):    # --cache-dir, and the default under HOME (conftest)
        c.mkdir(parents=True, exist_ok=True)
        (c / cache_key(LEDGER_ID, path.name, forged, signers)).write_bytes(b"")      # a planted "verified" mark
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store),
                     "--cache-dir", str(cache)]) == 0                                  # show honours the mark
    capsys.readouterr()
    for extra in ([], ["--store", str(store)]):
        rc = cli.main(["biolean", "ledger", "verify", "--ledger", str(ledger), "--cache-dir", str(cache), *extra])
        assert rc == 2 and _json(capsys.readouterr().out)["errors"][0]["code"] == LC.LEDGER_BAD_SIGNATURE, extra


def test_show_filters_and_store_requirement(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger)]) == 0
    rows = _lines(capsys.readouterr().out)
    assert len(rows) == 5 and {r["status"] for r in rows} == {None} and all(r["rechecked"] is False for r in rows)
    assert set(rows[0]) == {"file", "line", "hash", "entry", "fingerprint", "status", "contested", "rechecked",
                            "recheck_errors"}
    assert [r["line"] for r in rows] == [1, 2, 3, 4, 1]
    assert [r["fingerprint"] for r in rows] == [FP_A] * 4 + [FP_B]        # spec section 1: the SHA256:<base64> form
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--by", KEY16_B]) == 0
    assert len(_lines(capsys.readouterr().out)) == 1
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--kind", "derived"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["entry"]["kind"] == "derived" and row["status"] is None
    for flag in ("--contested", "--stale", "--recheck"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), flag])
        assert exc.value.code == 2
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--contested", "--no-cache"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["entry"]["fact"][1] == "P10001" and row["contested"] is True and row["status"] == "admitted"
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--recheck", "--kind", "derived", "--no-cache"]) == 0
    [row] = _lines(capsys.readouterr().out)
    assert row["rechecked"] is True and row["recheck_errors"] == [] and row["status"] == "recorded"
    obo = store / "go-basic.obo"
    obo.write_text(obo.read_text().replace("name: process grandchild\nnamespace: biological_process\n",
                                           "name: process grandchild\nnamespace: biological_process\nis_obsolete: true\n"))
    assert cli.main(["biolean", "ledger", "show", "--ledger", str(ledger), "--store", str(store), "--stale", "--no-cache"]) == 0
    rows = _lines(capsys.readouterr().out)
    assert rows and all(r["status"] == "stale" for r in rows)


def test_prove_check_goals_accept_ledger_and_prove_carries_the_doi(tmp_path, capsys):
    ledger, store = signed_store(tmp_path)
    claim = "UniProtKB:P10006 involved_in GO:0000001"
    rc = cli.main(["biolean", "prove", claim, "--store", str(store)])
    assert rc == 3
    captured = capsys.readouterr()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    captured = capsys.readouterr()
    out = _json(captured.out)
    assert rc == 0 and out["derivation"]["steps"][0]["reference"].startswith("DOI:")
    assert json.loads(captured.err)["load_report"]["ledger"]["admitted"] == 4
    d = tmp_path / "d.json"
    d.write_text(json.dumps(out["derivation"]))
    rc = cli.main(["biolean", "check", str(d), "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    v = _json(capsys.readouterr().out)
    assert rc == 0 and v["verdict"] == "ACCEPTED" and v["axioms"][0]["references"][0].startswith("DOI:")
    rc = cli.main(["biolean", "check", str(d), "--store", str(store)])
    assert rc == 3
    capsys.readouterr()
    rc = cli.main(["biolean", "goals", "UniProtKB:P10006", "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert rc == 0 and [g["prop"]["term"] for g in out["goals"]] == ["GO:0000001", "GO:0000002", "GO:0000003"]
    # the signers pin reaches the load (break: drop expected_signers_sha256= at the load_store call)
    pin = hashlib.sha256((ledger / "allowed_signers").read_bytes()).hexdigest()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache",
                   "--signers-sha256", pin])
    assert rc == 0
    capsys.readouterr()
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache",
                   "--signers-sha256", "0" * 64])
    captured = capsys.readouterr()
    assert rc == 2 and _json(captured.out)["errors"][0]["code"] == LC.LEDGER_SIGNERS_MISMATCH and captured.err == ""
    (ledger / f"ledger/{KEY16_B}.jsonl").write_bytes(b"garbage\n")
    rc = cli.main(["biolean", "prove", claim, "--store", str(store), "--ledger", str(ledger), "--no-cache"])
    captured = capsys.readouterr()
    assert rc == 2 and _json(captured.out)["errors"][0]["code"] == LC.LEDGER_MALFORMED and captured.err == ""


def _ann(i, assigned_by, refs):
    return Annotation(i, "UniProtKB:X", "X", "involved_in", False, "GO:1", "GO:1", tuple(sorted(refs)), "IDA",
                      "ECO:0000314", (), "P", "protein", "NCBITaxon:9606", "", "2020-01-01", assigned_by, "", "")


def test_prove_reference_is_set_only_when_every_matching_row_is_ledger_sourced():
    # Break: pick the reference from any ledger row even when a base row also matches (the kernel's
    # reference filter would then drop the base rows from `axioms`).
    terms = [Term("GO:1", "t", "biological_process", False, (), (), ())]
    step = {"id": "s1", "rule": "axiom", "conclusion": {"subject": "UniProtKB:X", "qualifier": "involved_in", "term": "GO:1",
                                                        "taxon": "NCBITaxon:9606", "negated": False}}
    mixed = StaticFactStore(terms, [], [_ann("gaf:a", "UniProt", ["PMID:1"]), _ann("gaf:b", "biolean:x", ["DOI:10.1/z"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, mixed)
    assert "reference" not in d["steps"][0]
    only_ledger = StaticFactStore(terms, [], [_ann("gaf:b", "biolean:x", ["PMID:9", "DOI:10.1/z", "DOI:10.1/a"]),
                                              _ann("gaf:c", "biolean:y", ["GO_REF:0000001"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, only_ledger)
    assert d["steps"][0]["reference"] == "DOI:10.1/a"                # smallest DOI of the row with the smallest id
    pmid_only = StaticFactStore(terms, [], [_ann("gaf:b", "biolean:x", ["PMID:9", "GO_REF:0000001"])])
    d = {"goal": step["conclusion"], "steps": [dict(step)], "root": "s1"}
    cli._ledger_reference(d, pmid_only)
    assert d["steps"][0]["reference"] == "PMID:9"


def test_bench_has_no_ledger_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["biolean", "bench", "coverage", "--items", str(tmp_path), "--ledger", str(tmp_path)])
    assert exc.value.code == 2


def test_recheck_exits_2_on_a_derived_entry_failing_on_its_own_base_and_nothing_else_does(tmp_path, capsys, monkeypatch):
    # Refinement 24. Break: exit 0 on the own-base failure (CI would pass it); re-prove derived
    # entries on load (plain verify, show, prove --ledger and append then fail on it); or make
    # ok false for a failure on another base. No fixture signature exists for a derived entry the
    # kernel rejects, so the elaborator hands the kernel {} for the signed one.
    from methods_graph.biolean.ledger import check as check_mod
    ledger, store = signed_store(tmp_path)
    L, S = str(ledger), str(store)
    with monkeypatch.context() as m:
        m.setattr(check_mod, "elaborate", lambda derivation, store: ({}, []))
        rc = cli.main(["biolean", "ledger", "verify", "--ledger", L, "--store", S, "--recheck", "--no-cache"])
        out = _json(capsys.readouterr().out)                       # exit 2, and the report is printed
        assert (rc, out["ok"], out["ledger"]["derived_rechecked"], out["ledger"]["derived_failed"]) == (2, False, 1, 1)
        [f] = out["ledger"]["derived_failed_entries"]
        assert (f["file"], f["line"], f["same_base"], f["kernel_codes"]) == (f"ledger/{KEY16_A}.jsonl", 4, True, ["MALFORMED"])
        assert f["errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED
        rc = cli.main(["biolean", "ledger", "show", "--ledger", L, "--store", S, "--recheck", "--kind", "derived",
                       "--no-cache"])
        captured = capsys.readouterr()
        [row] = _lines(captured.out)                               # exit 2, and the rows are printed
        assert (rc, row["status"], row["rechecked"]) == (2, "recorded", True)
        assert row["recheck_errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED
        assert "1 derived entry fail" in captured.err
        # nothing that only loads re-proves it
        rc = cli.main(["biolean", "ledger", "verify", "--ledger", L, "--store", S, "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert (rc, out["ok"], out["ledger"]["derived_failed"]) == (0, True, None)
        assert cli.main(["biolean", "ledger", "show", "--ledger", L, "--store", S, "--kind", "derived", "--no-cache"]) == 0
        capsys.readouterr()
        rc = cli.main(["biolean", "prove", "UniProtKB:P10006 involved_in GO:0000001", "--store", S, "--ledger", L,
                       "--no-cache"])
        assert rc == 0 and _json(capsys.readouterr().out)["derivation"]["steps"][0]["reference"].startswith("DOI:")
        rc = cli.main(["biolean", "ledger", "append", "--ledger", L, "--store", S, "--key", str(KEY_A),
                       "--fact", json.dumps(SCENARIOS["signed-append-a"].body), "--no-cache"])
        out = _json(capsys.readouterr().out)
        assert (rc, out["verdict"], out["line"]) == (0, "ACCEPTED", 5)
    # without the patch the entry passes on its own base
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", L, "--store", S, "--recheck", "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert (rc, out["ok"], out["ledger"]["derived_failed"]) == (0, True, 0)
    # another base (GO:0000003, cited by the derivation's axiom step, is obsolete here): counted
    # and listed with same_base false, ok true, exit 0
    obo = store / "go-basic.obo"
    grandchild = "name: process grandchild\nnamespace: biological_process\n"
    obo.write_text(obo.read_text().replace(grandchild, grandchild + "is_obsolete: true\n"))
    rc = cli.main(["biolean", "ledger", "verify", "--ledger", L, "--store", S, "--recheck", "--no-cache"])
    out = _json(capsys.readouterr().out)
    assert (rc, out["ok"], out["ledger"]["derived_rechecked"], out["ledger"]["derived_failed"]) == (0, True, 1, 1)
    [f] = out["ledger"]["derived_failed_entries"]
    assert (f["file"], f["line"], f["same_base"]) == (f"ledger/{KEY16_A}.jsonl", 4, False)
    assert f["errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED
    rc = cli.main(["biolean", "ledger", "show", "--ledger", L, "--store", S, "--recheck", "--kind", "derived",
                   "--no-cache"])
    captured = capsys.readouterr()
    [row] = _lines(captured.out)
    assert (rc, row["status"], row["rechecked"], captured.err) == (0, "recorded", True, "")
    assert row["recheck_errors"][0]["code"] == LC.LEDGER_DERIVATION_REJECTED


def test_append_racing_another_append_under_the_same_key_is_exit_2_and_writes_nothing(tmp_path, capsys, monkeypatch):
    # Refinement 25, through the CLI. The other append lands while this one is signing. Break:
    # drop the write-time digest comparison (exit 0 and a fork on disk).
    from methods_graph.biolean.ledger.append import append_entry
    ledger, store = signed_store(tmp_path)
    target = ledger / f"ledger/{KEY16_A}.jsonl"
    won = []

    def racing_runner(argv, **kwargs):
        if not won:
            inner = SCENARIOS["signed-append-a"]
            won.append(append_entry(ledger, kind=inner.kind, body=inner.body, key=KEY_A, ts=TS, runner=fake_runner,
                                    store_dir=store, gaf="goa_human.gaf", use_cache=False))
        return fake_runner(argv, **kwargs)

    monkeypatch.setattr("subprocess.run", racing_runner)
    rc = cli.main(["biolean", "ledger", "append", "--ledger", str(ledger), "--store", str(store), "--key", str(KEY_A),
                   "--fact", json.dumps(SCENARIOS["cli-signed-axiom"].body), "--no-cache"])
    [err] = _json(capsys.readouterr().out)["errors"]
    assert (rc, err["code"], err["context"]) == (2, LC.LEDGER_CHAIN_BROKEN, {"file": f"ledger/{KEY16_A}.jsonl", "line": 5})
    after_race = target.read_bytes()
    assert after_race.endswith(canon(won[0].entry) + b"\n") and len(after_race.split(b"\n")) == 6
    assert verify_ledger(ledger).heads()[KEY16_A] == {"entries": 5, "head": won[0].hash}
