"""append/init end to end with the fake runner (real ssh-keygen armor made once by make_fixtures.py)."""
import json

import pytest

from methods_graph.biolean.gaf import annotation_id
from methods_graph.biolean.ledger.append import append_entry, base_object, init_ledger, read_signer
from methods_graph.biolean.ledger.errors import LedgerCode as LC, LedgerIntegrityError
from methods_graph.biolean.ledger.format import canon, entry_hash, parse_line, shape_errors
from methods_graph.biolean.ledger.integrity import verify_ledger
from methods_graph.biolean.sshsig import verify_sshsig
from tests.biolean_ledger_fixture import (
    BY_A, BY_B, DIGEST_A, KEY16_A, KEY16_B, KEY_A, KEY_B, LEDGER_ID, LFIX, PUB_A, RELEASE, SCENARIOS,
    SIGNED_SEQUENCE, TS, copy_ledger_store, copy_signed, fake_runner, new_fact, run_scenario, signed_store)


def test_init_writes_allowed_signers_base_json_ledger_json_and_ledger_dir(tmp_path, capsys):
    store = copy_ledger_store(tmp_path / "store")
    out = init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, principal="manu", gaf="goa_human.gaf", ledger_id=LEDGER_ID,
                      allow_fixture_keys=True)
    d = tmp_path / "L"
    assert (d / "ledger").is_dir() and json.loads((d / "ledger.json").read_text()) == {"ledger": LEDGER_ID}
    assert (d / "allowed_signers").read_text() == f'manu namespaces="biolean-ledger" {PUB_A.read_text().strip()}\n'
    base = json.loads((d / "base.json").read_text())
    assert base == base_object(store, gaf="goa_human.gaf") and base["release"] == RELEASE and len(base["obo"]) == 64
    assert out["by"] == BY_A and out["key16"] == KEY16_A and out["fingerprint"].startswith("SHA256:")
    assert out["file"] == f"ledger/{KEY16_A}.jsonl" and out["ledger"] == LEDGER_ID
    assert (d / out["file"]).read_bytes() == b"" and verify_ledger(d).files == {KEY16_A: []}
    with pytest.raises(LedgerIntegrityError, match="exists"):
        init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)


def test_init_defaults_the_principal_to_the_key_comment_and_mints_a_random_id(tmp_path):
    store = copy_ledger_store(tmp_path / "store")
    out = init_ledger(tmp_path / "L", store_dir=store, key=KEY_B, gaf="goa_human.gaf", allow_fixture_keys=True)   # private path: uses b.pub beside it
    assert (tmp_path / "L" / "allowed_signers").read_text().startswith("biolean-fixture-B namespaces=")
    assert len(out["ledger"]) == 32 and out["ledger"] != LEDGER_ID
    out2 = init_ledger(tmp_path / "M", store_dir=store, key=KEY_B, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out2["ledger"] != out["ledger"]


def test_unsupported_key_type_refused_before_signing(tmp_path):
    # Break: run ssh-keygen -y, or read the type after signing.
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    for kind in ("sk-ssh-ed25519@openssh.com", "ssh-ed25519-cert-v01@openssh.com", "ssh-rsa"):
        pub = tmp_path / f"{kind}.pub"
        pub.write_text(f"{kind} {b64} c\n")
        with pytest.raises(LedgerIntegrityError) as exc:
            read_signer(pub)
        assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and kind in exc.value.errors[0].message
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(tmp_path / "L", store_dir=store, key=pub, gaf="goa_human.gaf")
        assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    with pytest.raises(LedgerIntegrityError) as exc:
        read_signer(tmp_path / "nokey")
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    signer = read_signer(KEY_A)
    assert (signer.digest, signer.key16, signer.comment, signer.pub_path) == (DIGEST_A, KEY16_A, "biolean-fixture-A", PUB_A)


def test_init_refuses_the_fixture_keys_unless_told_otherwise(tmp_path):
    # Break: drop the FIXTURE_KEY_DIGESTS check; the fixture keys could then start a real ledger.
    store = copy_ledger_store(tmp_path / "store")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, gaf="goa_human.gaf")
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and "fixture" in exc.value.errors[0].message
    assert not (tmp_path / "L" / "ledger.json").exists()
    assert init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)["key16"] == KEY16_A


def test_init_refuses_a_key16_collision(tmp_path):
    store = copy_ledger_store(tmp_path / "store")
    d = tmp_path / "L"
    (d / "ledger").mkdir(parents=True)
    (d / f"ledger/{KEY16_A}.jsonl").write_bytes(json.dumps({"by": BY_B}).encode() + b"\n")   # A's key16, another signer
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert exc.value.errors[0].code == LC.LEDGER_KEY16_COLLISION and exc.value.errors[0].context["file"] == f"ledger/{KEY16_A}.jsonl"


def test_append_accepts_the_example_fact_and_writes_one_canonical_signed_line(tmp_path):
    res, ledger, store = run_scenario("fresh-axiom", tmp_path)
    assert res.verdict == "ACCEPTED" and res.errors == [] and res.deferred == []
    assert res.file == f"ledger/{KEY16_A}.jsonl" and res.line == 1
    data = (ledger / res.file).read_bytes()
    obj, reason = parse_line(data)
    assert reason is None and obj == res.entry and data == canon(res.entry) + b"\n"
    assert res.hash == entry_hash(res.entry) and len(res.hash) == 64
    assert shape_errors(res.entry, ledger_id=LEDGER_ID) == []
    assert res.entry["prev"] == "" and res.entry["by"] == BY_A and res.entry["ts"] == TS
    assert res.entry["fact"][14] == "biolean:" + KEY16_A and res.entry["check"]["annotation_id"] == annotation_id(res.entry["fact"])
    assert res.entry["base"] == json.loads((ledger / "base.json").read_text())
    assert verify_sshsig(res.entry["sig"], canon({k: v for k, v in res.entry.items() if k != "sig"}))
    payload = res.to_json()
    assert set(payload) == {"verdict", "entry", "hash", "file", "line"}
    state = verify_ledger(ledger)
    assert state.heads() == {KEY16_A: {"entries": 1, "head": res.hash}}


def test_append_chains_prev_and_rejects_without_writing(tmp_path):
    res, ledger, store = run_scenario("signed-append-a", tmp_path)          # a 4th entry by A onto signed/
    assert res.verdict == "ACCEPTED" and res.line == 5                       # A's file: 3 axioms + 1 derived + this
    heads_before = verify_ledger(copy_signed(tmp_path / "pristine")).heads()
    assert res.entry["prev"] == heads_before[KEY16_A]["head"]
    before = (ledger / res.file).read_bytes()
    rej = append_entry(ledger, kind="axiom", body=new_fact(go_id="GO:0009999"), key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert rej.verdict == "REJECTED" and rej.entry is None and rej.hash is None
    assert [(e.code, e.field) for e in rej.errors] == [(LC.UNKNOWN_TERM, "/fact/4")]
    assert rej.deferred == [{"step": 4, "waits_on": [5]}, {"step": 8, "waits_on": [5]}]
    assert set(rej.to_json()) == {"verdict", "errors", "deferred"}
    assert (ledger / res.file).read_bytes() == before


def test_append_object_form_and_at_file_bodies(tmp_path):
    res, ledger, store = run_scenario("fresh-axiom-object", tmp_path)
    assert res.verdict == "ACCEPTED" and res.entry["fact"] == run_scenario("fresh-axiom", tmp_path / "x")[0].entry["fact"]


def test_append_self_verify_refuses_and_writes_nothing(tmp_path):
    # Break: skip the self-verify (the known-message armor would then be written).
    ledger, store = signed_store(tmp_path)
    known = (LFIX / "known" / "a-one.sig").read_bytes()

    def wrong_runner(argv, *, input, capture_output, check):
        assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"]
        return type("R", (), {"stdout": known, "stderr": b"", "returncode": 0})()

    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(db_reference="PMID:8888"), key=KEY_A, ts=TS, runner=wrong_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_SIGNING_FAILED
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_runner_failure_names_the_agent_route(tmp_path):
    import subprocess
    ledger, store = signed_store(tmp_path)

    def failing(argv, *, input, capture_output, check):
        raise subprocess.CalledProcessError(255, argv, stderr=b"incorrect passphrase")

    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(db_reference="PMID:8888"), key=KEY_A, ts=TS, runner=failing,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    e = exc.value.errors[0]
    assert e.code == LC.LEDGER_SIGNING_FAILED and "ssh-agent" in e.message and "incorrect passphrase" in e.message


def test_append_refuses_an_unlisted_signer_and_a_key16_collision(tmp_path):
    ledger, store = signed_store(tmp_path)
    (ledger / "allowed_signers").write_text((ledger / "allowed_signers").read_text().replace("fixture-b", "# fixture-b"))
    # removing B's line makes the whole ledger fail integrity (B's file is still there)
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_UNKNOWN_SIGNER
    (ledger / f"ledger/{KEY16_B}.jsonl").unlink()
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_B, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code == LC.LEDGER_UNKNOWN_SIGNER and "SHA256:" in exc.value.errors[0].message
    # key16 collision: a file under A's key16 whose entries name another full digest
    ledger2, store2 = signed_store(tmp_path / "two")
    text = (ledger2 / f"ledger/{KEY16_A}.jsonl").read_bytes()
    forged = text.replace(BY_A.encode(), (BY_A[:-4] + "0000").encode())
    (ledger2 / f"ledger/{KEY16_A}.jsonl").write_bytes(forged)
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger2, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store2, gaf="goa_human.gaf", use_cache=False)
    assert exc.value.errors[0].code in (LC.LEDGER_SIGNER_MISMATCH, LC.LEDGER_KEY16_COLLISION)


def test_base_mismatch_refuses_append(tmp_path):
    ledger, store = signed_store(tmp_path)
    obo = store / "go-basic.obo"
    obo.write_text(obo.read_text() + "\n[Term]\nid: GO:0000099\nname: extra\nnamespace: biological_process\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    e = exc.value.errors[0]
    assert e.code == LC.LEDGER_BASE_MISMATCH and set(e.context) == {"obo", "gaf", "eco"} and e.field == "/base"


def test_append_derived_stores_the_elaborated_derivation(tmp_path):
    res, ledger, store = run_scenario("signed-derived-elaborated", tmp_path)
    assert res.verdict == "ACCEPTED" and res.entry["kind"] == "derived"
    assert res.entry["derivation"]["goal"]["subject"] == "UniProtKB:P10003"
    assert res.entry["conclusion"]["subject"] == "UniProtKB:P10003"
    assert set(res.entry["check"]) == {"kernel", "axioms", "conflicts"} and len(res.entry["check"]["axioms"]) == 1


def test_append_computed_is_schema_checked_then_refused(tmp_path):
    ledger, store = signed_store(tmp_path)
    body = SCENARIOS["fresh-axiom"].body   # a fact, not a computed body: LEDGER_BAD_BODY first
    res = append_entry(ledger, kind="computed", body=body, key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED" and [e.code for e in res.errors] == [LC.LEDGER_BAD_BODY, LC.NOT_YET_DISCHARGEABLE]
    good = {"method": "m:bcftools plugin fill-tags", "dataset": {"id": "GEO:GSE1", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x", "exit_code": 0},
            "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003",
                           "taxon": "NCBITaxon:9606", "negated": False}}
    res = append_entry(ledger, kind="computed", body=good, key=KEY_A, ts=TS, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED" and [(e.code, e.field) for e in res.errors] == [(LC.NOT_YET_DISCHARGEABLE, None)]
    assert res.deferred == []


def test_signed_fixture_ledger_is_reproducible_from_its_sequence(tmp_path):
    # Replaying SIGNED_SEQUENCE through the fake runner reproduces signed/ byte for byte, which
    # proves the checked-in fixtures match the current envelope, base and kernel version.
    ledger, store = signed_store(tmp_path, replay=True)
    for name in (f"ledger/{KEY16_A}.jsonl", f"ledger/{KEY16_B}.jsonl", "allowed_signers", "base.json", "ledger.json"):
        assert (ledger / name).read_bytes() == (LFIX / "signed" / name).read_bytes(), name


# ---------------------------------------------------------------------------
# the allowed_signers label; bodies nested too deep or holding a bad character
# ---------------------------------------------------------------------------
import copy

from methods_graph.biolean.ledger.format import MAX_DEPTH


def _pub_with_comment(tmp_path, name, comment):
    pub = tmp_path / f"{name}.pub"
    pub.write_text(f"ssh-ed25519 {PUB_A.read_text().split()[1]} {comment}\n")
    return pub


def test_init_falls_back_to_key16_when_the_key_comment_is_not_a_principal(tmp_path):
    # Break: drop the key16 fallback (AllowedSignersError escapes init on "user@host name"), or keep
    # a comment the allowed_signers reader refuses (the double quote): either way init raises.
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    out = init_ledger(tmp_path / "L1", store_dir=store, key=_pub_with_comment(tmp_path, "spaced", "user@host name"),
                      gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out["principal"] == KEY16_A and out["key16"] == KEY16_A
    text = (tmp_path / "L1" / "allowed_signers").read_text()
    assert text == f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64} user@host name\n'
    assert verify_ledger(tmp_path / "L1").files == {KEY16_A: []}              # the line reads back
    out = init_ledger(tmp_path / "L2", store_dir=store, key=_pub_with_comment(tmp_path, "quoted", 'say "hi"'),
                      gaf="goa_human.gaf", allow_fixture_keys=True)
    assert out["principal"] == KEY16_A
    text = (tmp_path / "L2" / "allowed_signers").read_text()
    assert text == f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64}\n'
    assert verify_ledger(tmp_path / "L2").files == {KEY16_A: []}


def test_init_refuses_an_explicit_principal_the_reader_would_not_hand_back(tmp_path):
    # Break: let a refused explicit principal fall back to the comment or key16 (init then succeeds
    # under a name nobody asked for), or let AllowedSignersError escape (a traceback, not exit 2);
    # drop the UTF-8 check ("a\udcff" is what argparse gives for a non-UTF-8 byte): UnicodeEncodeError.
    store = copy_ledger_store(tmp_path / "store")
    for bad in ("", "two words", "#hash", "a,b", 'q"t', "nul\x00x", "tab\tx", "a\udcff"):
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(tmp_path / "L", store_dir=store, key=PUB_A, principal=bad, gaf="goa_human.gaf",
                        allow_fixture_keys=True)
        [e] = exc.value.errors
        assert e.code == LC.LEDGER_UNSUPPORTED_KEY and e.got == bad and "principal" in e.message, repr(bad)
        assert not (tmp_path / "L").exists(), repr(bad)                     # refused before anything is written


def _nested(depth):
    """A list ``depth`` containers deep, built without recursion."""
    node = []
    for _ in range(depth - 1):
        node = [node]
    return node


def test_append_body_nested_deeper_than_max_depth_is_a_bad_body(tmp_path):
    # Break: drop the nesting_depth check in append_entry: the canon() round trip after it still
    # refuses these bodies, but as "not a JSON value", so the message no longer says why. Drop both:
    # the 65-deep derived body is accepted by the kernel (it ignores an unknown top-level key) and
    # canon() raises ValueError on the entry; the 65-deep computed body gets LEDGER_BAD_COMPUTED;
    # the 100,000-deep fact comes back as LEDGER_BAD_COLUMNS with the whole body in `got`.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def append(kind, body):
        return append_entry(ledger, kind=kind, body=body, key=KEY_A, ts=TS, runner=fake_runner,
                            store_dir=store, gaf="goa_human.gaf", use_cache=False)

    derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
    derived["derivation"]["note"] = _nested(MAX_DEPTH - 1)                 # body, derivation, 63 lists: 65 levels
    res = append("derived", derived)
    assert res.verdict == "REJECTED"
    deep = f"the body is nested deeper than {MAX_DEPTH} levels"
    assert [(e.code, e.field, e.got, e.message) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None, deep)]
    res = append("computed", {"dataset": _nested(MAX_DEPTH)})               # 65 levels
    assert [(e.code, e.field) for e in res.errors] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]
    assert res.errors[0].message == deep
    res = append("computed", {"dataset": _nested(MAX_DEPTH - 1)})           # exactly 64: schema-checked as usual
    codes = [e.code for e in res.errors]
    assert LC.LEDGER_BAD_BODY not in codes and LC.LEDGER_BAD_COMPUTED in codes and codes[-1] == LC.NOT_YET_DISCHARGEABLE
    res = append("axiom", _nested(100_000))
    assert [(e.code, e.field, e.got, e.message) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/fact", None, deep)]
    json.dumps(res.to_json(), sort_keys=True)                                # printable: the body is not echoed back
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_body_with_a_bad_character_is_rejected_before_the_runner(tmp_path):
    # Break: drop the character check on derived and computed bodies. The kernel takes any string
    # step id, so the derived entry reaches the signer (and, signed, would be written and then fail
    # verify for the whole ledger at line 5); the computed body loses its LEDGER_BAD_CHARACTER.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def unreachable(argv, **kwargs):
        raise AssertionError("a body with a bad character reached the signer")

    derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
    derived["derivation"]["steps"][0]["id"] = "s1\ud800"
    derived["derivation"]["steps"][1]["premises"] = ["s1\ud800"]
    res = append_entry(ledger, kind="derived", body=derived, key=KEY_A, ts=TS, runner=unreachable,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED"
    assert [(e.code, e.field, e.got, e.fix) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/0/id", "U+D800", "s1"),
        (LC.LEDGER_BAD_CHARACTER, "/derivation/steps/1/premises/0", "U+D800", "s1")]
    good = {"method": "m:bcftools", "dataset": {"id": "GEO:GSE1", "sha256": "ab" * 32},
            "graph_hash": "sha256:" + "cd" * 32,
            "preconditions": [{"id": "replicates>=3", "status": "met", "diagnostic": "n=4e\u0301"}],
            "run": {"command": "nextflow run x", "container": "quay.io/x", "exit_code": 0},
            "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003",
                           "taxon": "NCBITaxon:9606", "negated": False}}
    res = append_entry(ledger, kind="computed", body=good, key=KEY_A, ts=TS, runner=unreachable,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert [(e.code, e.field, e.fix) for e in res.errors] == [
        (LC.LEDGER_BAD_CHARACTER, "/preconditions/0/diagnostic", "n=4\u00e9"), (LC.NOT_YET_DISCHARGEABLE, None, None)]
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before
    assert len(verify_ledger(ledger).entries()) == 5


def test_hostile_files_are_ledger_errors_not_tracebacks(tmp_path):
    # Break: read the .pub catching only OSError (UnicodeDecodeError escapes); read the existing
    # key16 file as `json.loads(first).get("by")` (AttributeError on a JSON list, IsADirectoryError
    # on a directory); read base.json catching only OSError and ValueError (RecursionError escapes).
    store = copy_ledger_store(tmp_path / "store")
    pub = tmp_path / "binary.pub"
    pub.write_bytes(b"ssh-ed25519 \xff\xfe\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        read_signer(pub)
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY
    for name, plant in (("list", lambda p: p.write_bytes(b"[1]\n")), ("directory", lambda p: p.mkdir())):
        d = tmp_path / name
        (d / "ledger").mkdir(parents=True)
        plant(d / f"ledger/{KEY16_A}.jsonl")
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
        [e] = exc.value.errors
        assert (e.code, e.got) == (LC.LEDGER_KEY16_COLLISION, None), name
    ledger, store = signed_store(tmp_path / "deep")
    (ledger / "base.json").write_text("[" * 1_000_000 + "]" * 1_000_000)          # json.loads overflows on 3.12-3.14
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind="axiom", body=new_fact(), key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context["file"] == "base.json"


# ---------------------------------------------------------------------------
# bodies that are not JSON values; the key half of the self-verify; init's writes
# ---------------------------------------------------------------------------
import base64
import dataclasses
import pathlib

from methods_graph.biolean.ledger import append as append_mod
from methods_graph.biolean.ledger.errors import LedgerError


def test_append_body_that_is_not_a_json_value_is_a_bad_body(tmp_path):
    # Break: drop the canon(body) round trip. Infinity and NaN (what json.loads reads for 1e999 and
    # NaN) and a 5,000-digit int in a derived body pass the kernel, then canon(entry) raises
    # ValueError; an int-keyed fact dict from the Python API raises TypeError in fact_from_body.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()

    def append(kind, body):
        return append_entry(ledger, kind=kind, body=body, key=KEY_A, ts=TS, runner=fake_runner,
                            store_dir=store, gaf="goa_human.gaf", use_cache=False)

    for note in (float("inf"), float("-inf"), float("nan"), 10 ** 5000):
        derived = copy.deepcopy(SIGNED_SEQUENCE[4][2])
        derived["derivation"]["note"] = note
        res = append("derived", derived)
        assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/derivation", None)], type(note)
        json.dumps(res.to_json(), allow_nan=False)                           # strict JSON: nothing echoed back
    res = append("computed", {"method": float("nan")})
    assert [(e.code, e.field) for e in res.errors] == [(LC.LEDGER_BAD_BODY, None), (LC.NOT_YET_DISCHARGEABLE, None)]
    for body in (dict(enumerate(new_fact())), new_fact(db_reference=float("nan"))):
        res = append("axiom", body)
        assert [(e.code, e.field, e.got) for e in res.errors] == [(LC.LEDGER_BAD_BODY, "/fact", None)], type(body)
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_append_self_verify_refuses_a_signature_by_another_key(tmp_path, monkeypatch):
    # Break: skip the key comparison after verify_sshsig (`if False:`). A signature that verifies,
    # but under another key than the one --key names (here the verifier is made to report B's
    # key), is then written to A's file.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()
    real, signer_b = append_mod.verify_sshsig, read_signer(KEY_B)
    monkeypatch.setattr(append_mod, "verify_sshsig", lambda sig, message: real(sig, message) and signer_b.blob)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_SIGNING_FAILED and "ssh-agent" in e.message
    assert signer_b.fingerprint in e.message and read_signer(KEY_A).fingerprint in e.message
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_init_builds_and_checks_everything_before_mkdir(tmp_path, monkeypatch):
    # Break: move base_object after mkdir (a bad store leaves a directory behind); drop the
    # read-back of the allowed_signers line (init writes a line that does not permit the ledger
    # namespace); keep a comment that is not UTF-8 text (UnicodeEncodeError at the write).
    store = copy_ledger_store(tmp_path / "store")
    b64 = PUB_A.read_text().split()[1]
    signer = dataclasses.replace(read_signer(PUB_A), comment="c\udcff")
    assert append_mod._signers_entry(signer, None) == (
        KEY16_A, f'{KEY16_A} namespaces="biolean-ledger" ssh-ed25519 {b64}\n'.encode("ascii"))

    def bad_store(*args, **kwargs):
        raise LedgerIntegrityError([LedgerError(LC.LEDGER_MALFORMED, "cannot read the store", None)])

    with monkeypatch.context() as m:
        m.setattr(append_mod, "base_object", bad_store)
        with pytest.raises(LedgerIntegrityError):
            init_ledger(tmp_path / "B", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert not (tmp_path / "B").exists()
    real = append_mod.allowed_signers_line
    monkeypatch.setattr(append_mod, "allowed_signers_line", lambda principal, blob, comment="": real(
        principal, blob, comment).replace('namespaces="biolean-ledger"', 'namespaces="other"'))
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "N", store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert exc.value.errors[0].code == LC.LEDGER_UNSUPPORTED_KEY and "read back" in exc.value.errors[0].message
    assert not (tmp_path / "N").exists()


def test_unwritable_ledger_paths_are_malformed_not_tracebacks(tmp_path, monkeypatch):
    # Break: drop the OSError catch around init's mkdir (FileExistsError: the ledger path is a
    # file) or around append's write (PermissionError, after signing).
    store = copy_ledger_store(tmp_path / "store")
    afile = tmp_path / "afile"
    afile.write_text("x")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(afile, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": str(afile), "line": None}
    ledger, store = signed_store(tmp_path / "S")
    target = ledger / f"ledger/{KEY16_A}.jsonl"
    before = target.read_bytes()
    real_open = pathlib.Path.open

    def refuse_append(self, mode="r", *args, **kwargs):
        if mode == "ab":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", refuse_append)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=fake_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": f"ledger/{KEY16_A}.jsonl", "line": 5}
    assert target.read_bytes() == before


def test_init_survives_a_stat_that_raises(tmp_path, monkeypatch):
    # Break: a bare Path.exists() in init_ledger. Python 3.12 raises PermissionError on EACCES (a
    # directory that cannot be searched); 3.13+ returns False. The ledger.json check treats a
    # failed stat as absent (mkdir then reports the path); the key16-file check fails closed on
    # every version: it calls stat() itself, so the patched stat below reaches it on 3.14 too
    # (break: go back to Path.exists there, which on 3.14 never calls Path.stat and reads absent).
    store = copy_ledger_store(tmp_path / "store")
    new, old = tmp_path / "new", tmp_path / "old"
    (old / "ledger").mkdir(parents=True)
    blocked = {new / "ledger.json", new}
    key16_file = old / f"ledger/{KEY16_A}.jsonl"          # only its stat() raises, as on EACCES
    real_exists, real_mkdir, real_stat = pathlib.Path.exists, pathlib.Path.mkdir, pathlib.Path.stat

    def exists(self, *args, **kwargs):
        if self in blocked:
            raise PermissionError(13, "Permission denied", str(self))
        return real_exists(self, *args, **kwargs)

    def mkdir(self, *args, **kwargs):
        if self in blocked:
            raise PermissionError(13, "Permission denied", str(self))
        return real_mkdir(self, *args, **kwargs)

    def stat(self, *args, **kwargs):
        if self == key16_file:
            raise PermissionError(13, "Permission denied", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "exists", exists)
    monkeypatch.setattr(pathlib.Path, "mkdir", mkdir)
    monkeypatch.setattr(pathlib.Path, "stat", stat)
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(new, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": str(new), "line": None}
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(old, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": f"ledger/{KEY16_A}.jsonl", "line": None}
    monkeypatch.undo()
    assert not new.exists() and sorted(p.name for p in old.iterdir()) == ["ledger"]     # nothing written


def test_init_names_why_a_key_does_not_read_back(tmp_path):
    # Break: drop the AllowedSignersError reason from the read-back refusal. A small-order key
    # passes parse_public_key_line, and only the allowed_signers reader refuses it.
    store = copy_ledger_store(tmp_path / "store")
    blob = b"".join(len(part).to_bytes(4, "big") + part for part in (b"ssh-ed25519", bytes([1]) + bytes(31)))
    pub = tmp_path / "small.pub"
    pub.write_text(f"ssh-ed25519 {base64.b64encode(blob).decode('ascii')} small@host\n")
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(tmp_path / "L", store_dir=store, key=pub, gaf="goa_human.gaf")
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_UNSUPPORTED_KEY and "small-order" in e.message
    assert not (tmp_path / "L").exists()


# ---------------------------------------------------------------------------
# final fix wave: a clone of a fresh ledger, init's first write, the write-time digest
# ---------------------------------------------------------------------------
import shutil

from tests.biolean_ledger_fixture import fresh_ledger


def _clone_files_only(src, dest):
    """What a git clone gives: every file, and no directory that holds none."""
    for p in sorted(src.rglob("*")):
        if p.is_file():
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
    return dest


def test_a_fresh_ledger_survives_a_clone_that_drops_empty_directories(tmp_path):
    # Break: drop init's empty ledger/<key16>.jsonl. git tracks no empty directory, so the clone
    # then has no ledger/ and verify refuses it ("ledger/ directory is missing").
    store = copy_ledger_store(tmp_path / "store")
    original = fresh_ledger(tmp_path / "original", store)
    assert (original / f"ledger/{KEY16_A}.jsonl").read_bytes() == b""
    clone = _clone_files_only(original, tmp_path / "clone")
    assert verify_ledger(clone).heads() == {KEY16_A: {"entries": 0, "head": ""}}
    # a second init with the same key is still refused, on the original and on the clone
    for d in (original, clone):
        with pytest.raises(LedgerIntegrityError) as exc:
            init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", ledger_id=LEDGER_ID, allow_fixture_keys=True)
        assert exc.value.errors[0].code == LC.LEDGER_MALFORMED and "already holds a ledger" in exc.value.errors[0].message
    # the existing empty file is treated as an absent one: the first append lands at line 1, prev ""
    scn = SCENARIOS["fresh-axiom"]
    res = append_entry(clone, kind=scn.kind, body=scn.body, key=scn.key, ts=scn.ts, runner=fake_runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert (res.verdict, res.file, res.line, res.entry["prev"]) == ("ACCEPTED", f"ledger/{KEY16_A}.jsonl", 1, "")
    assert verify_ledger(clone).heads()[KEY16_A] == {"entries": 1, "head": res.hash}


def test_init_writes_ledger_json_first_and_never_through_a_symlink(tmp_path):
    # Break: write ledger.json with write_bytes (it follows the dangling symlink and creates the
    # target), or write it after allowed_signers and base.json (they are then left behind).
    store = copy_ledger_store(tmp_path / "store")
    d = tmp_path / "L"
    d.mkdir()
    (tmp_path / "elsewhere").mkdir()
    target = tmp_path / "elsewhere" / "ledger.json"
    (d / "ledger.json").symlink_to(target)
    with pytest.raises(LedgerIntegrityError) as exc:
        init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", ledger_id=LEDGER_ID, allow_fixture_keys=True)
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_MALFORMED and e.context == {"file": str(d / "ledger.json"), "line": None}
    assert not target.exists() and sorted(p.name for p in d.iterdir()) == ["ledger.json"]      # nothing else written


def test_init_treats_an_empty_key16_file_as_absent_and_never_truncates_one(tmp_path):
    # An empty file holds no entry, so there is no signer to collide with (break: read its missing
    # first line as a signer, `None`, and refuse a key16 collision); a non-empty file of the same
    # key is left as it is (break: create the empty file whenever init runs).
    store = copy_ledger_store(tmp_path / "store")
    d = tmp_path / "L"
    (d / "ledger").mkdir(parents=True)
    (d / f"ledger/{KEY16_A}.jsonl").write_bytes(b"")
    assert init_ledger(d, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)["key16"] == KEY16_A
    kept = copy_signed(tmp_path / "S")
    before = (kept / f"ledger/{KEY16_A}.jsonl").read_bytes()
    (kept / "ledger.json").unlink()
    init_ledger(kept, store_dir=store, key=PUB_A, gaf="goa_human.gaf", allow_fixture_keys=True)
    assert (kept / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


@pytest.mark.parametrize("with_fcntl", [True, False], ids=["flock", "no-fcntl"])
def test_append_refuses_a_file_that_changed_after_it_was_verified(tmp_path, monkeypatch, with_fcntl):
    # Refinement 25. Another append under the same key lands while this one is signing (the runner
    # is the window between the load and the write). Break: drop the digest comparison: this append
    # then writes a second line whose prev is the same old head, a fork verify refuses. Without
    # fcntl the lock is a no-op and the digest check still refuses.
    ledger, store = signed_store(tmp_path)
    target = ledger / f"ledger/{KEY16_A}.jsonl"
    before = target.read_bytes()
    locks = []
    if with_fcntl:
        if append_mod.fcntl is None:
            pytest.skip("no fcntl on this platform")
        lock_ex, real_flock = append_mod.fcntl.LOCK_EX, append_mod.fcntl.flock
        monkeypatch.setattr(append_mod.fcntl, "flock", lambda fd, op: (locks.append(op), real_flock(fd, op))[1])
    else:
        monkeypatch.setattr(append_mod, "fcntl", None)
    won = []

    def racing_runner(argv, **kwargs):
        if not won:
            inner = SCENARIOS["cli-signed-axiom"]
            won.append(append_entry(ledger, kind=inner.kind, body=inner.body, key=KEY_A, ts=TS, runner=fake_runner,
                                    store_dir=store, gaf="goa_human.gaf", use_cache=False))
        return fake_runner(argv, **kwargs)

    outer = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=outer.kind, body=outer.body, key=KEY_A, ts=TS, runner=racing_runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert (e.code, e.field, e.message) == (LC.LEDGER_CHAIN_BROKEN, "/prev", "the file changed since it was verified; retry")
    assert e.context == {"file": f"ledger/{KEY16_A}.jsonl", "line": 5} and e.fix is None
    [first] = won
    assert (first.verdict, first.line) == ("ACCEPTED", 5)                  # the normal path still appends
    assert target.read_bytes() == before + canon(first.entry) + b"\n"      # the refused append wrote nothing
    assert verify_ledger(ledger).heads()[KEY16_A] == {"entries": 5, "head": first.hash}
    assert locks == ([lock_ex] * 2 if with_fcntl else [])                 # both appends took the lock


def test_append_refuses_a_file_swapped_under_it_between_the_open_and_the_re_read(tmp_path, monkeypatch):
    # Refinement 25's same-open-file check. After the lock, the path is replaced by a copy with
    # the same bytes (an editor's save, a git checkout), so the re-hash matches and only the
    # identity check tells the two files apart. Break: drop `not same`: the line then goes to
    # the replaced file, which nothing reads any more, and append reports ACCEPTED.
    import os
    ledger, store = signed_store(tmp_path)
    target = ledger / f"ledger/{KEY16_A}.jsonl"
    before = target.read_bytes()
    replaced = tmp_path / "replaced.jsonl"
    os.link(target, replaced)                                  # keeps the replaced file readable
    armed, swapped = [], []
    real_open = pathlib.Path.open

    def swapping_open(self, mode="r", *args, **kwargs):
        if armed and not swapped and self == target and mode == "rb":
            swapped.append(True)
            copy = target.with_name("swap.tmp")
            copy.write_bytes(target.read_bytes())
            os.replace(copy, target)
        return real_open(self, mode, *args, **kwargs)

    def runner(argv, **kwargs):                                # the window between the load and the write
        armed.append(True)
        return fake_runner(argv, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", swapping_open)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=runner,
                     store_dir=store, gaf="goa_human.gaf", use_cache=False)
    [e] = exc.value.errors
    assert swapped and (e.code, e.message) == (LC.LEDGER_CHAIN_BROKEN, "the file changed since it was verified; retry")
    assert target.read_bytes() == before and replaced.read_bytes() == before      # nothing written to either
    assert not os.path.samefile(target, replaced)


def test_append_refuses_a_bad_character_in_what_it_built_before_signing(tmp_path, monkeypatch):
    # Break: drop character_errors on the built entry. The release header below is NFD text that
    # step 1a never saw (it is read from the store, not the body), so the runner is then called and
    # a line verify's step 2 refuses would be signed.
    ledger, store = signed_store(tmp_path)
    before = (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes()
    real = append_mod.read_release
    nfd = "releases/2026-02-02 café"
    monkeypatch.setattr(append_mod, "read_release",
                        lambda *a, **k: {**real(*a, **k), "go_basic_data_version": nfd})
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        raise RuntimeError("the runner must not be called")

    scn = SCENARIOS["signed-append-a"]
    res = append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, runner=runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    assert res.verdict == "REJECTED" and calls == [] and res.deferred == []
    [e] = res.errors
    assert (e.code, e.field, e.got, e.fix) == (LC.LEDGER_BAD_CHARACTER, "/base/release/go_basic_data_version",
                                               "U+0065", "releases/2026-02-02 café")
    assert (ledger / f"ledger/{KEY16_A}.jsonl").read_bytes() == before


def test_signing_output_that_is_not_armor_names_the_agent_route(tmp_path):
    # Spec section 4: every LEDGER_SIGNING_FAILED names the agent route. Break: drop it from the
    # dearmor failure message.
    import types
    ledger, store = signed_store(tmp_path)
    scn = SCENARIOS["signed-append-a"]
    with pytest.raises(LedgerIntegrityError) as exc:
        append_entry(ledger, kind=scn.kind, body=scn.body, key=KEY_A, ts=TS, store_dir=store, gaf="goa_human.gaf",
                     use_cache=False, runner=lambda argv, **k: types.SimpleNamespace(stdout=b"Enter passphrase:", stderr=b""))
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_SIGNING_FAILED and "not an SSH signature" in e.message and "ssh-agent" in e.message


def test_a_key_path_that_cannot_be_read_as_text_is_unsupported_key(tmp_path):
    # Break: catch only UnicodeDecodeError in read_signer: a NUL in the path raises a bare ValueError.
    with pytest.raises(LedgerIntegrityError) as exc:
        read_signer(tmp_path / "k\x00ey")
    [e] = exc.value.errors
    assert e.code == LC.LEDGER_UNSUPPORTED_KEY and "null" in e.message
