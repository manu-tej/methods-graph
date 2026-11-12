"""``init`` and ``append`` (spec §2, §4, §6, §7): the only code that writes a ledger.

``append_entry`` loads base plus ledger (integrity first), checks the body, builds the
envelope, signs through ``runner`` (``ssh-keygen -Y sign`` on stdin), verifies the signature
it got back with the in-repo verifier, and only then appends one canonical line, under an
exclusive lock and only while the file still hashes to what integrity verified (refinement 25).
Signing is the contributor's ``ssh-keygen``; there is no signing code here.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import fcntl
except ImportError:                                # not POSIX: the lock is a no-op; the digest check still runs
    fcntl = None                                   # type: ignore[assignment]

from methods_graph.biolean.ledger.check import (
    CheckContext, _not_yet, check_axiom, check_computed, check_derived, fact_from_body)
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    FORMAT_VERSION, MAX_DEPTH, canon, character_errors, entry_hash, nesting_depth, shape_errors)
from methods_graph.biolean.ledger.integrity import _path_is
from methods_graph.biolean.ledger.load import BASE_READ_ERRORS, load_with_ledger
from methods_graph.biolean.sshsig import (
    FIXTURE_KEY_DIGESTS, KEY_TYPE, NAMESPACE, AllowedSignersError, SshsigError, allowed_signers_line, dearmor,
    find_signer, fingerprint, key16 as _key16, key_digest, parse_allowed_signers, parse_public_key_line,
    verify_sshsig)
from methods_graph.biolean.store import base_digests, read_release

KINDS = ("axiom", "derived", "computed")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()   # an absent file reads as an empty one (spec §1)
# Where a body-level LEDGER_BAD_BODY points, per kind (spec §7): a computed body is the entry's top level.
BODY_FIELD: dict[str, str | None] = {"axiom": "/fact", "derived": "/derivation", "computed": None}


@dataclass(frozen=True)
class SignerKey:
    path: Path              # what ssh-keygen gets: the private key, or a .pub whose key is in the agent
    pub_path: Path
    blob: bytes
    digest: str
    key16: str
    fingerprint: str
    comment: str

    @property
    def by(self) -> str:
        return "sha256:" + self.digest


def _fail(code: str, message: str, **kw: Any) -> LedgerIntegrityError:
    return LedgerIntegrityError([LedgerError(code, message, kw.pop("field", None), **kw)])


def read_signer(key: Path) -> SignerKey:
    """The public half of ``--key``: the file itself when it is a ``.pub``, else ``<key>.pub``
    beside it. Never runs ``ssh-keygen -y``. Refuses every type but ssh-ed25519 (spec §4). A path
    with no file name (``""`` from an unset shell variable, ``.``, ``/``) is LEDGER_UNSUPPORTED_KEY."""
    key = Path(key)
    try:
        pub = key if key.suffix == ".pub" else key.with_name(key.name + ".pub")
    except ValueError as exc:                      # with_name on an empty name
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"--key {str(key)!r} names no key file: {exc}", got=str(key))
    try:
        text = pub.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:           # ValueError: UnicodeDecodeError, an embedded NUL in the path
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"cannot read the public key {pub}: {exc}", got=str(key))
    try:
        blob, comment = parse_public_key_line(text)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY, f"{pub}: {exc}; only {KEY_TYPE} keys can sign", got=str(key))
    digest = key_digest(blob)
    return SignerKey(key, pub, blob, digest, _key16(blob), fingerprint(blob), comment)


def base_object(store_dir: Path, *, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz",
                eco: str = "gaf-eco-mapping.txt") -> dict[str, Any]:
    """The §1 ``base`` object: three content digests plus the informational release. A present but
    unreadable base file is LEDGER_MALFORMED (refinement 18), as in `load_with_ledger`."""
    try:
        return {**base_digests(store_dir, obo=obo, gaf=gaf, eco=eco), "release": read_release(store_dir, obo=obo, gaf=gaf)}
    except BASE_READ_ERRORS as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot read the store under {store_dir}: {exc}",
                    context={"file": str(store_dir), "line": None}) from exc


def _utf8_encodable(s: str) -> bool:
    """False for a str holding a lone surrogate: what argparse gives for a non-UTF-8 argv byte."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _signers_entry(signer: SignerKey, principal: str | None) -> tuple[str, bytes]:
    """``(label, allowed_signers bytes)`` for ``init``, built and checked before anything is written.

    The label is ``principal or comment or key16``. An explicit principal that is not UTF-8 text,
    or that the allowed_signers reader would not hand back (``allowed_signers_line`` refuses it), is
    LEDGER_UNSUPPORTED_KEY; a comment that cannot serve as the label (``user@host name``, a double
    quote) gives way to key16, which always can. A comment the reader would refuse even after the
    key (a double quote, a NUL) or that is not UTF-8 text is left off the line: it labels nothing.
    The line must then read back through ``parse_allowed_signers`` as exactly this key and label.
    """
    comment = signer.comment
    try:
        allowed_signers_line(signer.key16, signer.blob, comment)       # key16 is always a valid principal
    except AllowedSignersError:
        comment = ""
    if not _utf8_encodable(comment):
        comment = ""
    if principal is not None:
        if not _utf8_encodable(principal):
            raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                        f"principal {principal!r} is not UTF-8 text (a lone surrogate)", got=principal)
        try:
            label, line = principal, allowed_signers_line(principal, signer.blob, comment)
        except AllowedSignersError as exc:
            raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                        f"principal {principal!r} cannot label an allowed_signers line: {exc.reason}", got=principal)
    else:
        label = comment or signer.key16
        try:
            line = allowed_signers_line(label, signer.blob, comment)
        except AllowedSignersError:
            label, line = signer.key16, allowed_signers_line(signer.key16, signer.blob, comment)
    why = ""
    try:
        back = parse_allowed_signers(line)
    except AllowedSignersError as exc:           # e.g. a small-order key, which parse_public_key_line admits
        back, why = [], f" ({exc})"
    if not (len(back) == 1 and back[0].blob == signer.blob and back[0].principals == (label,)
            and back[0].permits(NAMESPACE)):
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                    f"the allowed_signers line for {label!r} does not read back as {signer.fingerprint}{why}", got=label)
    return label, line.encode("utf-8")


def _write_or_fail(path: Path, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """One filesystem write. An OSError (the path is a file, a read-only parent) is LEDGER_MALFORMED
    naming ``path``: the ledger files cannot be written (spec §7), never a traceback."""
    try:
        return action(*args, **kwargs)
    except OSError as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot write {path}: {exc}",
                    context={"file": str(path), "line": None}) from exc


def _create(path: Path, data: bytes) -> None:
    """Write a new file, refusing any path that already exists, a dangling symlink included
    (``"xb"``: O_CREAT | O_EXCL never follows a symlink)."""
    with path.open("xb") as fh:
        fh.write(data)


def _key16_file_present(path: Path, fname: str) -> bool:
    """Whether ``ledger/<key16>.jsonl`` exists, by ``stat()``: FileNotFoundError and
    NotADirectoryError mean absent; any other OSError fails closed on every Python version
    (``Path.exists`` returns False on EACCES from 3.13 on, which would hide another key's file)."""
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:                         # cannot tell whether another key owns this file
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot check {fname} for a key16 collision: {exc}",
                    context={"file": fname, "line": None}) from exc
    return True


def init_ledger(
    ledger_dir: Path, *, store_dir: Path, key: Path, principal: str | None = None,
    obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz", eco: str = "gaf-eco-mapping.txt",
    ledger_id: str | None = None, allow_fixture_keys: bool = False,
) -> dict[str, Any]:
    """Write ledger.json (first, exclusively), allowed_signers, base.json and an empty
    ``ledger/<key16>.jsonl`` (spec §6, §7). The empty file keeps ``ledger/`` in a git clone,
    which tracks no empty directory; spec §1 makes an empty file an intact, entry-free chain."""
    signer = read_signer(key)
    if signer.digest in FIXTURE_KEY_DIGESTS and not allow_fixture_keys:
        raise _fail(LedgerCode.LEDGER_UNSUPPORTED_KEY,
                    f"{signer.fingerprint} is a test fixture key and cannot start a ledger", got=str(key))
    ledger_dir = Path(ledger_dir)
    # Python 3.12's Path.exists raises PermissionError on EACCES (3.13+ returns False). A stat that
    # fails reads as absent here: mkdir and the writes below then report the unusable path.
    if _path_is((ledger_dir / "ledger.json").exists):
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"{ledger_dir} already holds a ledger (ledger.json exists)")
    label, signers_bytes = _signers_entry(signer, principal)      # before mkdir: a refused principal writes nothing
    base = base_object(store_dir, obo=obo, gaf=gaf, eco=eco)      # before mkdir: a bad store writes nothing
    _write_or_fail(ledger_dir, ledger_dir.mkdir, parents=True, exist_ok=True)
    fname = f"ledger/{signer.key16}.jsonl"
    existing = ledger_dir / fname
    present = _key16_file_present(existing, fname)
    if present:
        try:
            data = existing.read_bytes()
        except OSError:
            data = None
        if data != b"":                            # an empty file holds no entry, so no signer to collide with
            try:
                first = json.loads(data.split(b"\n", 1)[0]) if data is not None else None
            except (ValueError, RecursionError):
                first = None
            by = first.get("by") if isinstance(first, dict) else None
            if by != signer.by:
                raise _fail(LedgerCode.LEDGER_KEY16_COLLISION, f"{fname} exists and was signed by {by}, not {signer.by}",
                            got=by, context={"file": fname, "line": 1})
    lid = ledger_id or secrets.token_hex(16)
    # ledger.json first and exclusively: a second init racing this one, or a ledger.json symlink
    # (even a dangling one), fails here before anything else is written.
    ledger_json = ledger_dir / "ledger.json"
    _write_or_fail(ledger_json, _create, ledger_json, (json.dumps({"ledger": lid}) + "\n").encode("utf-8"))
    for path, data in ((ledger_dir / "allowed_signers", signers_bytes),
                       (ledger_dir / "base.json", (json.dumps(base, sort_keys=True, indent=2) + "\n").encode("utf-8"))):
        _write_or_fail(path, path.write_bytes, data)
    _write_or_fail(ledger_dir / "ledger", (ledger_dir / "ledger").mkdir, exist_ok=True)
    if not present:
        _write_or_fail(existing, _create, existing, b"")
    signers_sha = hashlib.sha256(signers_bytes).hexdigest()
    return {"ledger": lid, "by": signer.by, "key16": signer.key16, "fingerprint": signer.fingerprint,
            "principal": label, "allowed_signers_sha256": signers_sha, "base": base, "file": fname}


def sign(canonical: bytes, key: Path, runner: Callable[..., Any]) -> str:
    """``sig`` for ``canonical``: ssh-keygen -Y sign, message on stdin, armor on stdout (spec §4)."""
    try:
        result = runner(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE],
                        input=canonical, capture_output=True, check=True)
    except Exception as exc:                       # CalledProcessError, OSError (no ssh-keygen), anything the seam raises
        detail = getattr(exc, "stderr", b"")
        detail = detail.decode("utf-8", "replace").strip() if isinstance(detail, bytes) else str(detail)
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED,
                    f"ssh-keygen -Y sign failed: {exc}{(': ' + detail) if detail else ''}. "
                    "A passphrase-protected key must be loaded in ssh-agent, with --key naming its .pub file.",
                    got=str(key))
    try:
        return dearmor(result.stdout)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED,
                    f"ssh-keygen output is not an SSH signature: {exc}. "
                    "A passphrase-protected key must be loaded in ssh-agent, with --key naming its .pub file.",
                    got=str(key))


@dataclass
class AppendResult:
    verdict: str                       # ACCEPTED | REJECTED
    errors: list[LedgerError]
    deferred: list[dict[str, Any]]
    entry: dict[str, Any] | None
    hash: str | None
    file: str | None
    line: int | None

    def to_json(self) -> dict[str, Any]:
        if self.verdict == "ACCEPTED":
            return {"verdict": "ACCEPTED", "entry": self.entry, "hash": self.hash, "file": self.file, "line": self.line}
        return {"verdict": "REJECTED", "errors": [e.to_dict() for e in self.errors], "deferred": self.deferred}


def _rejected(errors: list[LedgerError], deferred: list[dict[str, Any]] | None = None) -> AppendResult:
    return AppendResult("REJECTED", errors, deferred or [], None, None, None, None)


def _not_a_json_value(body: Any, kind: str) -> LedgerError | None:
    """LEDGER_BAD_BODY (``got`` null) unless ``body``, at most MAX_DEPTH deep, is exactly a JSON value.
    ``canon`` refuses NaN and ±Infinity (what ``json.loads`` reads for ``NaN`` and ``1e999``) and an
    int past CPython's 4300-digit limit (ValueError), a set or keys of mixed types (TypeError); a
    non-string key or a tuple survives ``canon`` but not the round trip. Any of them would crash
    ``canon(entry)`` after the check, or reach a check that assumes JSON."""
    try:
        again = json.loads(canon(body))
    except (ValueError, TypeError) as exc:
        reason = str(exc)
    else:
        if again == body:
            return None
        reason = "it changes in a JSON round trip (a key that is not a string, a tuple)"
    return LedgerError(LedgerCode.LEDGER_BAD_BODY, f"the body is not a JSON value: {reason}", BODY_FIELD[kind], got=None)


def append_entry(
    ledger_dir: Path, *, kind: str, body: Any, key: Path, ts: str, runner: Callable[..., Any],
    store_dir: Path, obo: str = "go-basic.obo", gaf: str = "goa_human.gaf.gz", eco: str = "gaf-eco-mapping.txt",
    cache_dir: Path | None = None, use_cache: bool = True, body_error: LedgerError | None = None,
) -> AppendResult:
    """Spec §2: integrity, signer, base, check, envelope, sign, self-verify, write.

    Raises LedgerIntegrityError for every exit-2 condition (unreadable ledger or store, integrity,
    unknown signer, key16 collision, base mismatch, signing failure, a file another append changed
    since it was verified). Returns REJECTED (exit 3) without writing, or ACCEPTED after appending
    exactly one line. ``body_error`` is the CLI's
    "the text is not JSON" `LEDGER_BAD_BODY`; it is reported here, after the exit-2 checks, so
    that a broken ledger or a wrong base still wins over a malformed body (spec §2 order).

    Before any check looks inside it, a body nested deeper than MAX_DEPTH, or one that is not
    exactly a JSON value (NaN, ±Infinity, a huge int, a key that is not a string), is that same
    LEDGER_BAD_BODY (``got`` null: the body is not echoed back), and a derived or computed body is
    held to §2 step 1a (`character_errors`, pointers into the body): the kernel takes any string
    as a step id, and a line verify's step 2 would refuse must never be signed. An axiom's
    columns get step 1a inside `check_axiom`, under the column rules. The built entry gets step 1a
    once more before signing, for what append itself added (``base.release``, the elaborated
    derivation): a fault there is that same REJECTED result, nothing signed. A ledger file that
    cannot be written is LEDGER_MALFORMED.
    """
    if kind not in KINDS:
        raise ValueError(kind)
    ledger_dir = Path(ledger_dir)
    signer = read_signer(key)
    store, _report, loaded = load_with_ledger(store_dir, ledger_dir, obo=obo, gaf=gaf, eco=eco,
                                              cache_dir=cache_dir, use_cache=use_cache)
    state = loaded.state
    listed = find_signer(state.signers, signer.blob)
    if listed is None or not listed.permits(NAMESPACE):
        raise _fail(LedgerCode.LEDGER_UNKNOWN_SIGNER,
                    f"key {signer.by} ({signer.fingerprint}) is not in allowed_signers with {NAMESPACE} permitted",
                    got=signer.by, context={"file": "allowed_signers", "line": None})
    fname = f"ledger/{signer.key16}.jsonl"
    existing = state.files.get(signer.key16, [])
    if existing and existing[0].entry["by"] != signer.by:
        raise _fail(LedgerCode.LEDGER_KEY16_COLLISION,
                    f"{fname} was signed by {existing[0].entry['by']}, not {signer.by}",
                    got=existing[0].entry["by"], context={"file": fname, "line": 1})
    try:
        declared = json.loads((ledger_dir / "base.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:      # RecursionError: a deeply nested base.json
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot read base.json: {exc}", context={"file": "base.json", "line": None})
    digests = loaded.base.digests
    if not (isinstance(declared, dict) and all(declared.get(k) == digests[k] for k in ("obo", "gaf", "eco"))):
        raise _fail(LedgerCode.LEDGER_BASE_MISMATCH,
                    "--store is not the base this ledger declares in base.json", field="/base", got=digests,
                    context={k: (declared.get(k) if isinstance(declared, dict) else None) for k in ("obo", "gaf", "eco")})
    base_obj = {**digests, "release": read_release(store_dir, obo=obo, gaf=gaf)}
    ctx = CheckContext(store=store, eco_map=loaded.base.eco_map, primary_id=loaded.base.primary_id,
                       term=loaded.base.term, key16=signer.key16, ledger_sources=loaded.sources)

    if body_error is None and nesting_depth(body) > MAX_DEPTH:
        body_error = LedgerError(LedgerCode.LEDGER_BAD_BODY, f"the body is nested deeper than {MAX_DEPTH} levels",
                                 BODY_FIELD[kind], got=None)
    if body_error is None:
        body_error = _not_a_json_value(body, kind)
    if body_error is not None:
        return _rejected([body_error, _not_yet()] if kind == "computed" else [body_error])
    if kind != "axiom":
        faults = character_errors(body)
        if faults:
            return _rejected(faults + [_not_yet()] if kind == "computed" else faults)

    fields: dict[str, Any]
    if kind == "axiom":
        fact, errs = fact_from_body(body)
        if errs:
            return _rejected(errs)
        res = check_axiom(fact, ctx)
        if not res.ok:
            return _rejected(res.errors, res.deferred)
        fields, check_block = {"fact": res.fact}, res.check
    elif kind == "derived":
        dres = check_derived(body, ctx)
        if not dres.ok:
            return _rejected(dres.errors)
        fields, check_block = {"derivation": dres.derivation, "conclusion": dres.conclusion}, dres.check
    else:
        return _rejected(check_computed(body, ctx))

    prev = existing[-1].hash if existing else ""
    entry: dict[str, Any] = {"v": FORMAT_VERSION, "kind": kind, "ledger": state.ledger_id, **fields,
                             "base": base_obj, "check": check_block, "prev": prev, "by": signer.by, "ts": ts}
    faults = shape_errors({**entry, "sig": ""}, ledger_id=state.ledger_id)
    if faults:                                     # a defect in this module, never the caller's body
        raise RuntimeError(f"append built a malformed entry: {[f.to_dict() for f in faults]}")
    # §2 step 1a over everything append added (base.release from the store's headers, the elaborated
    # derivation): verify's step 2 refuses a line with a bad character, so none is ever signed.
    char_faults = character_errors(entry)
    if char_faults:
        return _rejected(char_faults)
    canonical = canon(entry)
    sig = sign(canonical, signer.path, runner)
    try:
        blob = verify_sshsig(sig, canonical)
    except SshsigError as exc:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED, f"the signature ssh-keygen returned does not verify: {exc}. "
                    "Check that --key names the intended key (or its .pub when the key is in ssh-agent).",
                    got=str(key))
    if blob != signer.blob:
        raise _fail(LedgerCode.LEDGER_SIGNING_FAILED,
                    f"ssh-keygen signed with {fingerprint(blob)}, not {signer.fingerprint}; nothing written. "
                    "Check that --key names the intended key (or its .pub when the key is in ssh-agent).",
                    got=str(key))
    entry["sig"] = sig
    line = canon(entry) + b"\n"
    _write_line(ledger_dir / fname, line, fname=fname, lineno=len(existing) + 1, prev=entry["prev"],
                expected=state.file_sha256.get(signer.key16, _EMPTY_SHA256))
    return AppendResult("ACCEPTED", [], [], entry, entry_hash(entry), fname, len(existing) + 1)


def _lock(fh: Any) -> None:
    """``flock(LOCK_EX)`` on ``fh``, held until it is closed; a no-op where ``fcntl`` is missing."""
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _write_line(path: Path, line: bytes, *, fname: str, lineno: int, prev: str, expected: str) -> None:
    """Refinement 25: append ``line`` only while the file still hashes to ``expected``, the digest
    integrity verified. The file is opened ``"ab"`` and locked; under the lock it is re-read (through
    a second descriptor that must be the same open file) and re-hashed. Another append that landed
    since the load is LEDGER_CHAIN_BROKEN, and nothing is written; closing the file flushes the line,
    then releases the lock."""
    at = {"file": fname, "line": lineno}
    try:
        with path.open("ab") as fh:
            _lock(fh)
            with path.open("rb") as current:
                same = os.path.sameopenfile(fh.fileno(), current.fileno())
                digest = hashlib.sha256(current.read()).hexdigest()
            if not same or digest != expected:
                raise _fail(LedgerCode.LEDGER_CHAIN_BROKEN, "the file changed since it was verified; retry",
                            field="/prev", got=prev, context=at)
            fh.write(line)
    except OSError as exc:
        raise _fail(LedgerCode.LEDGER_MALFORMED, f"cannot append to {fname}: {exc}", context=at) from exc
