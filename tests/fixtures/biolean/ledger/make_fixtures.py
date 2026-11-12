"""Regenerate every signed fixture with the real ssh-keygen. Run from the repo root:

    .venv/bin/python tests/fixtures/biolean/ledger/make_fixtures.py

Not a test (the suite never runs it). Ed25519 and sshsig carry no randomness, so unchanged
inputs give byte-identical output. Re-run after any change to the entry envelope, the kernel
version, the fixture base, SIGNED_SEQUENCE or SCENARIOS, then commit the result.

Writes: signed/ (the fixture ledger), signed-variants/ (hand-signed lines that must fail in a
specific way), sigs/<sha256 of the bytes signed>.sig (real armor for every append a test makes).
Keys come from keys/ (never regenerated; their digests are pinned in code).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from methods_graph.biolean.gaf import annotation_id                                    # noqa: E402
from methods_graph.biolean.ledger.append import sign                                   # noqa: E402
from methods_graph.biolean.ledger.format import canon, entry_hash, parse_line            # noqa: E402
from tests.biolean_ledger_fixture import (                                             # noqa: E402
    BY_A, KEY16_A, KEY16_B, KEY_A, KEY_B, LEDGER_ID, SCENARIOS, TS, build_signed, copy_ledger_store, copy_signed,
    fresh_ledger, ledger_base, new_fact, RELEASE)

SIGS = HERE / "sigs"


def private_copies(tmp: Path) -> dict[Path, Path]:
    """ssh-keygen refuses a 0644 private key; git checkouts are 0644. Sign from 0600 copies."""
    tmp.mkdir(parents=True, exist_ok=True)
    out = {}
    for key in (KEY_A, KEY_B):
        dst = tmp / key.name
        shutil.copy(key, dst)
        shutil.copy(key.with_name(key.name + ".pub"), tmp / (key.name + ".pub"))
        os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR)
        out[key] = dst
    return out


def recording_runner(keymap: dict[Path, Path]):
    def runner(argv, *, input, capture_output, check):
        assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"]
        real = list(argv)
        real[4] = str(keymap[Path(argv[4])])
        result = subprocess.run(real, input=input, capture_output=capture_output, check=check)
        SIGS.mkdir(exist_ok=True)
        (SIGS / (hashlib.sha256(input).hexdigest() + ".sig")).write_bytes(result.stdout)
        return result
    return runner


def raw_entry(fact, *, key16=KEY16_A, base=None, prev="", contested_by=(), ann_id=None):
    """An axiom entry built outside append. ``ann_id`` overrides check.annotation_id for a row
    that annotation_id() cannot hash (a lone surrogate); integrity refuses such a line before step 7."""
    row = list(fact)
    if row[14] == "":
        row[14] = "biolean:" + key16
    return {"v": 1, "kind": "axiom", "ledger": LEDGER_ID, "fact": row,
            "base": base or {**ledger_base().digests, "release": RELEASE},
            "check": {"kernel": "0.1.0", "annotation_id": ann_id or annotation_id(row), "contested_by": list(contested_by),
                      "counters": {"new_subject": 0}},
            "prev": prev, "by": BY_A, "ts": TS}


def raw_sign(entry: dict, key: Path, runner) -> bytes:
    """One canonical signed line for an entry built outside append (bypasses every check)."""
    e = dict(entry)
    e["sig"] = sign(canon(e), key, runner)
    return canon(e) + b"\n"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        keymap = private_copies(tmp / "keys")
        runner = recording_runner(keymap)
        if SIGS.exists():
            shutil.rmtree(SIGS)
        SIGS.mkdir()
        store = copy_ledger_store(tmp / "store")

        # 1. signed/: init + SIGNED_SEQUENCE
        signed = HERE / "signed"
        if signed.exists():
            shutil.rmtree(signed)
        build_signed(signed, store, runner=runner)
        for junk in signed.rglob("__pycache__"):
            shutil.rmtree(junk)

        # 2. sigs/ for every scenario (fresh and signed starts)
        for name, scn in sorted(SCENARIOS.items()):
            work = tmp / "scn" / name
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            ledger = work / "ledger"
            if scn.start == "fresh":
                fresh_ledger(ledger, store)
            else:
                copy_signed(ledger)
            from methods_graph.biolean.ledger.append import append_entry
            res = append_entry(ledger, kind=scn.kind, body=scn.body, key=scn.key, ts=scn.ts, runner=runner,
                               store_dir=store, gaf="goa_human.gaf", use_cache=False)
            assert res.verdict == "ACCEPTED", (name, [e.to_dict() for e in res.errors])
            print(f"scenario {name}: {res.file}:{res.line} {res.hash[:16]}")

        # 3. signed-variants/: hand-signed lines
        variants = HERE / "signed-variants"
        if variants.exists():
            shutil.rmtree(variants)
        variants.mkdir()
        a_lines = (signed / f"ledger/{KEY16_A}.jsonl").read_bytes().split(b"\n")[:-1]
        entries = [parse_line(l + b"\n")[0] for l in a_lines]
        h1 = entry_hash(entries[0])
        # fork: A's three axioms plus a fourth whose prev is entry 1's hash
        fork_body = raw_entry(new_fact(db_object_id="P10005", db_object_symbol="G5", db_reference="PMID:777"), prev=h1)
        (variants / "fork.jsonl").write_bytes(b"".join(l + b"\n" for l in a_lines[:3]) + raw_sign(fork_body, KEY_A, runner))
        # column 15 names B's key16, signed by A, base matches
        (variants / "assigned-by-b.jsonl").write_bytes(raw_sign(raw_entry(new_fact(assigned_by="biolean:" + KEY16_B)), KEY_A, runner))
        # a base-independent fault (bad reference) with a made-up base
        made_up = {"obo": "0" * 64, "gaf": "1" * 64, "eco": "2" * 64, "release": RELEASE}
        (variants / "made-up-base.jsonl").write_bytes(raw_sign(raw_entry(new_fact(db_reference="PMID:0"), base=made_up), KEY_A, runner))
        # a lone surrogate in column 17
        (variants / "surrogate.jsonl").write_bytes(raw_sign(
            raw_entry(new_fact(gene_product_form_id="\ud800"), ann_id="gaf:0000000000000000"), KEY_A, runner))
        # check.annotation_id that does not match fact
        bad = raw_entry(new_fact(db_reference="PMID:778"))
        bad["check"]["annotation_id"] = "gaf:0000000000000000"
        (variants / "bad-annotation-id.jsonl").write_bytes(raw_sign(bad, KEY_A, runner))
        print(f"wrote {signed}, {variants}, {len(list(SIGS.iterdir()))} signatures under {SIGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
