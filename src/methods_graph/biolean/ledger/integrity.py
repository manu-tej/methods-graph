"""Per-file integrity (spec §3), ``verify --extends``, and the verification cache.

A ledger is either intact or it is not: ``verify_ledger`` raises ``LedgerIntegrityError``
with every error it found (each carrying ``file`` and ``line`` in ``context``) and nothing
loads. Steps, per file: 0 signers pin; 1 names and the trusted list; 2 canonical line, field
schema, characters; 3 ``by`` against the embedded key and the file name; 4 known signer;
5 signature; 6 chain; 7 the recomputed annotation id, not repeated within the file (and no
    ``computed`` entry in v1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from methods_graph.biolean.gaf import annotation_id
from methods_graph.biolean.ledger.errors import LedgerCode, LedgerError, LedgerIntegrityError
from methods_graph.biolean.ledger.format import (
    FILE_RE, HEX64_RE, LEDGER_ID_RE, canon, character_errors, entry_hash, parse_line, shape_errors, unsigned)
from methods_graph.biolean.sshsig import (
    NAMESPACE, AllowedSignersError, Signer, SshsigError, find_signer, fingerprint, key_digest,
    parse_allowed_signers, parse_sshsig, verify_sshsig)

# Bump on any change to ed25519.py, sshsig.py, or steps 1-6 below: the cache key carries it.
# 2: sshsig.py refuses a principals field whose quote closes inside it (final fix wave, A1).
LEDGER_VERIFIER_VERSION = 2
_KEEP_CODES = frozenset({LedgerCode.LEDGER_VERSION, LedgerCode.LEDGER_WRONG_LEDGER})
_KEY16_RE = re.compile(r"^[0-9a-f]{16}\Z")


@dataclass(frozen=True)
class LedgerEntry:
    file: str                       # "ledger/<key16>.jsonl"
    line: int                       # 1-based
    entry: dict[str, Any]
    hash: str

    @property
    def key16(self) -> str:
        return self.file[len("ledger/"):len("ledger/") + 16]


@dataclass
class LedgerState:
    ledger_dir: Path
    ledger_id: str
    signers: list[Signer]
    allowed_signers_sha256: str
    files: dict[str, list[LedgerEntry]] = field(default_factory=dict)
    files_verified_from_cache: int = 0
    cache_mark_failures: int = 0            # verified files whose cache mark could not be written
    # key16 -> sha256 of the exact bytes verified; append writes only while the file still hashes
    # to it (plan refinement 25)
    file_sha256: dict[str, str] = field(default_factory=dict)

    def heads(self) -> dict[str, dict[str, Any]]:
        return {k: {"entries": len(v), "head": v[-1].hash if v else ""} for k, v in sorted(self.files.items())}

    def entries(self) -> list[LedgerEntry]:
        return [e for k in sorted(self.files) for e in self.files[k]]

    def listed_key16s(self) -> set[str]:
        return {s.key16 for s in self.signers}


def _err(code: str, message: str, *, file: str, line: int | None = None, field_: str | None = None,
         got: Any = None, fix: Any = None, options=(), extra: dict[str, Any] | None = None) -> LedgerError:
    context: dict[str, Any] = {"file": file, "line": line}
    if extra:
        context.update(extra)
    return LedgerError(code, message, field_, got=got, fix=fix, options=tuple(options), context=context)


def _path_is(check: Callable[[], bool]) -> bool:
    """``check`` is a bound ``Path.exists`` / ``is_file`` / ``is_dir`` / ``is_symlink``, given
    ``os.path`` semantics on every supported Python: an OSError means "not there" or "not that
    kind of file", never an exception. Python 3.12 raises PermissionError there on EACCES (a
    directory that cannot be searched); 3.13+ returns False."""
    try:
        return check()
    except OSError:
        return False


def read_ledger_id(ledger_dir: Path) -> str:
    path = Path(ledger_dir) / "ledger.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:      # RecursionError: a deeply nested ledger.json
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot read ledger.json: {exc}", file="ledger.json")])
    if not (isinstance(obj, dict) and set(obj) == {"ledger"} and isinstance(obj["ledger"], str)
            and LEDGER_ID_RE.match(obj["ledger"])):
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, 'ledger.json must be {"ledger": "<32 hex>"}',
                                         file="ledger.json", got=obj)])
    return obj["ledger"]


def read_allowed_signers(ledger_dir: Path, *, expected_sha256: str | None = None) -> tuple[bytes, list[Signer]]:
    """The raw bytes of ``allowed_signers`` and the signers parsed from them. With
    ``expected_sha256`` (step 0, the pin) the raw bytes' sha256 is compared before the parser runs,
    so a pinned consumer gets LEDGER_SIGNERS_MISMATCH for any other file, parseable or not, and
    the parser never sees bytes nobody pinned."""
    path = Path(ledger_dir) / "allowed_signers"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot read allowed_signers: {exc}", file="allowed_signers")])
    actual = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise LedgerIntegrityError([_err(
            LedgerCode.LEDGER_SIGNERS_MISMATCH,
            "allowed_signers does not match the pinned digest; no entry was read",
            file="allowed_signers", got=actual, extra={"expected": expected_sha256, "actual": actual})])
    try:
        signers = parse_allowed_signers(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1     # lines end at "\n" only, as parse_allowed_signers reads them
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"allowed_signers is not UTF-8: {exc}",
                                         file="allowed_signers", line=line)])
    except AllowedSignersError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, exc.reason, file="allowed_signers", line=exc.line)])
    return data, signers


# ---------------------------------------------------------------------------
# the cache: "steps 1-6 passed for these exact bytes" on this machine only
# ---------------------------------------------------------------------------

def default_cache_dir() -> Path | None:
    """``~/.cache/biolean-ledger``, or None when there is no home directory to hold it:
    ``Path.home()`` raises RuntimeError with no HOME and no passwd entry. None means no cache (every
    file a miss, every mark a counted failure), never a traceback."""
    try:
        return Path.home() / ".cache" / "biolean-ledger"
    except RuntimeError:
        return None


def cache_key(ledger_id: str, name: str, data: bytes, signers_sha256: str) -> str:
    material = "\n".join([ledger_id, name, hashlib.sha256(data).hexdigest(), signers_sha256,
                          str(LEDGER_VERIFIER_VERSION)]).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _cache_hit(cache_dir: Path, key: str) -> bool:
    """A mark that cannot be stat'ed is a miss, never a hit and never an exception."""
    return _path_is((cache_dir / key).is_file)


def _cache_mark(cache_dir: Path, key: str) -> bool:
    """Mark a verified file; False when the mark cannot be written (``cache_dir`` is a file, a
    read-only parent, a caller-supplied path holding a NUL, which raises ValueError). The file
    verified all the same, so the caller counts the failure and goes on: a cache is an
    optimisation and never fails a ledger."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / key).write_bytes(b"")
    except (OSError, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------
# one file
# ---------------------------------------------------------------------------

def _verify_file(name: str, data: bytes, ledger_id: str, signers: list[Signer], *, skip_signatures: bool,
                 ) -> tuple[list[LedgerEntry], list[LedgerError]]:
    file = f"ledger/{name}"
    k = name[:16]
    entries: list[LedgerEntry] = []
    if data == b"":
        return entries, []
    if not data.endswith(b"\n"):
        return entries, [_err(LedgerCode.LEDGER_MALFORMED, "final line has no newline", file=file, line=data.count(b"\n") + 1)]
    prev = ""
    by: str | None = None
    seen_ids: dict[str, int] = {}                  # step 7: a fact may not repeat within one file
    for n, raw in enumerate(data.split(b"\n")[:-1], 1):
        # step 2
        obj, reason = parse_line(raw + b"\n")
        if reason is not None:
            return entries, [_err(LedgerCode.LEDGER_MALFORMED, reason, file=file, line=n)]
        faults = shape_errors(obj, ledger_id=ledger_id, unknown_kind_code=LedgerCode.LEDGER_MALFORMED)
        faults += character_errors(obj)
        if faults:
            out = []
            for f in faults:
                code = f.code if f.code in _KEEP_CODES else LedgerCode.LEDGER_MALFORMED
                # §7: an integrity code carries no value fix; LEDGER_VERSION keeps its `1` (refinement 14),
                # an unknown kind keeps its options (refinement 16).
                out.append(_err(code, f.message, file=file, line=n, field_=f.field, got=f.got,
                                fix=f.fix if code in _KEEP_CODES else None, options=f.options, extra=f.context))
            return entries, out
        # step 3
        try:
            parsed = parse_sshsig(obj["sig"])
        except SshsigError as exc:
            return entries, [_err(LedgerCode.LEDGER_BAD_SIGNATURE, str(exc), file=file, line=n, field_="/sig")]
        digest = key_digest(parsed.public_key_blob)
        embedded = "sha256:" + digest
        fp = fingerprint(parsed.public_key_blob)
        if obj["by"] != embedded or digest[:16] != k or (by is not None and obj["by"] != by):
            return entries, [_err(LedgerCode.LEDGER_SIGNER_MISMATCH,
                                  f"by {obj['by']} must equal the signing key {embedded} ({fp}), match the file name, "
                                  f"and be the same on every line of {file}",
                                  file=file, line=n, field_="/by", got=obj["by"],
                                  extra={"embedded_key": embedded, "fingerprint": fp})]
        by = obj["by"]
        # step 4
        signer = find_signer(signers, parsed.public_key_blob)
        if signer is None or not signer.permits(NAMESPACE):
            return entries, [_err(LedgerCode.LEDGER_UNKNOWN_SIGNER,
                                  f"key {embedded} ({fp}) is not in allowed_signers with {NAMESPACE} permitted",
                                  file=file, line=n, field_="/by", got=obj["by"],
                                  extra={"embedded_key": embedded, "fingerprint": fp})]
        # step 5
        if not skip_signatures:
            try:
                verify_sshsig(obj["sig"], canon(unsigned(obj)))
            except SshsigError as exc:
                return entries, [_err(LedgerCode.LEDGER_BAD_SIGNATURE, str(exc), file=file, line=n, field_="/sig")]
        # step 6
        if obj["prev"] != prev:
            extra: dict[str, Any] = {"expected_prev": prev}
            fork = next((e.line for e in entries if e.hash == obj["prev"]), None)
            if fork is not None:
                extra["fork_of_line"] = fork
            return entries, [_err(LedgerCode.LEDGER_CHAIN_BROKEN,
                                  "prev does not name the previous entry" + (" (a fork)" if fork else ""),
                                  file=file, line=n, field_="/prev", got=obj["prev"], extra=extra)]
        h = entry_hash(obj)
        # step 7
        if obj["kind"] == "axiom":
            recomputed = annotation_id(obj["fact"])
            if recomputed != obj["check"]["annotation_id"]:
                return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, "check.annotation_id does not match fact",
                                      file=file, line=n, field_="/check/annotation_id", got=obj["check"]["annotation_id"],
                                      extra={"annotation_id": recomputed})]
            first = seen_ids.get(recomputed)
            if first is not None:                  # append refuses this as LEDGER_DUPLICATE; hand-signed files may not
                return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, f"fact repeats line {first} of this file",
                                      file=file, line=n, field_="/fact", got=obj["fact"],
                                      extra={"first_line": first, "annotation_id": recomputed})]
            seen_ids[recomputed] = n
        elif obj["kind"] == "computed":
            return entries, [_err(LedgerCode.LEDGER_INVALID_ENTRY, "v1 never writes a computed entry",
                                  file=file, line=n, field_="/kind", got="computed")]
        entries.append(LedgerEntry(file, n, obj, h))
        prev = h
    return entries, []


# ---------------------------------------------------------------------------
# the whole directory
# ---------------------------------------------------------------------------

def verify_ledger(
    ledger_dir: Path, *, expected_signers_sha256: str | None = None, cache_dir: Path | None = None,
    use_cache: bool = False,
) -> LedgerState:
    """Spec §3 integrity over every ``ledger/*.jsonl``. Raises LedgerIntegrityError, and nothing
    else on hostile input (an unreadable file or directory is LEDGER_MALFORMED); nothing loads
    then. ``use_cache`` skips step 5 for a file whose bytes, name, signers and verifier version
    were verified before on this machine (never used by ``ledger verify``); a mark that cannot be
    written, or a default cache with no home directory to hold it, is counted in
    ``cache_mark_failures``, never raised."""
    ledger_dir = Path(ledger_dir)
    ledger_id = read_ledger_id(ledger_dir)
    signers_bytes, signers = read_allowed_signers(ledger_dir, expected_sha256=expected_signers_sha256)
    signers_sha = hashlib.sha256(signers_bytes).hexdigest()
    sub = ledger_dir / "ledger"
    if not _path_is(sub.is_dir):
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, "ledger/ directory is missing", file="ledger")])
    if use_cache and cache_dir is None:
        cache_dir = default_cache_dir()
    try:
        names = sorted(os.listdir(sub))
    except OSError as exc:
        raise LedgerIntegrityError([_err(LedgerCode.LEDGER_MALFORMED, f"cannot list ledger/: {exc}", file="ledger")])
    errors: list[LedgerError] = []
    files: dict[str, list[LedgerEntry]] = {}
    digests: dict[str, str] = {}
    hits = 0
    mark_failures = 0
    for name in names:
        path = sub / name
        if not FILE_RE.match(name) or _path_is(path.is_symlink) or not _path_is(path.is_file):
            errors.append(_err(LedgerCode.LEDGER_MALFORMED, f"unexpected entry under ledger/: {name}", file=f"ledger/{name}"))
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(_err(LedgerCode.LEDGER_MALFORMED, f"cannot read ledger/{name}: {exc}", file=f"ledger/{name}"))
            continue
        key = cache_key(ledger_id, name, data, signers_sha)
        hit = bool(use_cache and cache_dir is not None and _cache_hit(cache_dir, key))
        entries, errs = _verify_file(name, data, ledger_id, signers, skip_signatures=hit)
        if errs:
            errors.extend(errs)
            continue
        if hit:
            hits += 1
        elif use_cache and (cache_dir is None or not _cache_mark(cache_dir, key)):   # None: no home directory
            mark_failures += 1
        files[name[:16]] = entries
        digests[name[:16]] = hashlib.sha256(data).hexdigest()
    if errors:
        errors.sort(key=lambda e: (e.context["file"], e.context.get("line") or 0))
        raise LedgerIntegrityError(errors)
    return LedgerState(ledger_dir, ledger_id, signers, signers_sha, files, hits, mark_failures, digests)


def integrity_report(state: LedgerState) -> dict[str, Any]:
    """The ``ledger`` report block without a base: base-dependent counters are None."""
    kinds = Counter(e.entry["kind"] for e in state.entries())
    return {
        "files": len(state.files), "entries": sum(kinds.values()),
        "axioms": kinds["axiom"], "derived": kinds["derived"], "computed": kinds["computed"],
        "admitted": None, "rechecked_ok": None, "stale": None, "stale_entries": None,
        "superseded_by_base": None, "superseded_entries": None,
        "duplicate_content": None, "duplicate_content_entries": None,
        "contested": None, "contested_entries": None,
        "heads": state.heads(), "allowed_signers_sha256": state.allowed_signers_sha256,
        "files_verified_from_cache": state.files_verified_from_cache,
        "cache_mark_failures": state.cache_mark_failures,
        "derived_rechecked": None, "derived_failed": None, "derived_failed_entries": None,
    }


# ---------------------------------------------------------------------------
# --extends
# ---------------------------------------------------------------------------

def _older_head(data: bytes) -> tuple[int, str | None]:
    lines = data.split(b"\n")[:-1] if data.endswith(b"\n") else data.split(b"\n")
    lines = [l for l in lines if l]
    if not lines:
        return 0, ""
    obj, reason = parse_line(lines[-1] + b"\n")
    return len(lines), (entry_hash(obj) if reason is None and isinstance(obj, dict) else None)


def _rollback(state: LedgerState, k: str, message: str, older_entries: int, older_head: str | None) -> LedgerError:
    cur = state.files.get(k, [])
    return _err(LedgerCode.LEDGER_ROLLBACK, message, file=f"ledger/{k}.jsonl",
                extra={"older_entries": older_entries, "older_head": older_head,
                       "entries": len(cur), "head": cur[-1].hash if cur else ""})


def _read_or_value_error(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: cannot read: {type(exc).__name__}: {exc}") from exc


def _heads_map_ok(heads: Any) -> bool:
    """Every key a key16; ``entries`` a non-negative JSON integer; ``head`` "" exactly when
    ``entries`` is 0, else 64 lowercase hex (an entry hash)."""
    if not isinstance(heads, dict):
        return False
    for k, v in heads.items():
        if not (_KEY16_RE.match(k) and isinstance(v, dict) and set(v) == {"entries", "head"}):
            return False
        n, head = v["entries"], v["head"]
        if not (type(n) is int and n >= 0 and isinstance(head, str)):
            return False
        if (head != "") if n == 0 else not HEX64_RE.match(head):
            return False
    return True


def check_extends(state: LedgerState, older: Path) -> list[LedgerError]:
    """Spec §3 ``verify --extends``: the current ledger must extend ``older`` (a ledger directory
    or a heads map). Deleting a revoked key's file is the one allowed shrink. Raises ValueError,
    and nothing else, when ``older`` is neither, cannot be read, or is not a valid heads map."""
    older = Path(older)
    listed = state.listed_key16s()
    errors: list[LedgerError] = []
    if _path_is(older.is_dir):
        sub = older / "ledger"
        if not _path_is(sub.is_dir):
            raise ValueError(f"{older}: no ledger/ directory")
        try:
            names = sorted(os.listdir(sub))
        except OSError as exc:
            raise ValueError(f"{sub}: cannot list: {type(exc).__name__}: {exc}") from exc
        for name in names:
            if not FILE_RE.match(name):
                continue
            k = name[:16]
            old = _read_or_value_error(sub / name)
            n_old, head_old = _older_head(old)
            cur_path = state.ledger_dir / "ledger" / name
            if not _path_is(cur_path.is_file):         # a stat failure reads as missing: a listed key fails closed
                if k in listed:
                    errors.append(_rollback(state, k, "file is missing but its key is still listed", n_old, head_old))
                continue
            if not _read_or_value_error(cur_path).startswith(old):
                errors.append(_rollback(state, k, "current file is not a byte extension of the older file", n_old, head_old))
        return errors
    if _path_is(older.is_file):
        try:
            heads = json.loads(older.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as exc:
            raise ValueError(f"{older}: not a heads map: {type(exc).__name__}: {exc}") from exc
        if not _heads_map_ok(heads):
            raise ValueError(f'{older}: not a heads map: {{"<key16>": {{"entries": n >= 0, '
                             f'"head": "" when n is 0, else 64 hex}}}}')
        for k in sorted(heads):
            n_old, head_old = heads[k]["entries"], heads[k]["head"]
            cur = state.files.get(k)
            if cur is None:
                if k in listed:
                    errors.append(_rollback(state, k, "file is missing but its key is still listed", n_old, head_old))
                continue
            if len(cur) < n_old:
                errors.append(_rollback(state, k, "fewer entries than the older state", n_old, head_old))
            elif n_old > 0 and cur[n_old - 1].hash != head_old:
                errors.append(_rollback(state, k, "the older head is not at its position in the current chain", n_old, head_old))
        return errors
    raise ValueError(f"{older}: not a ledger directory or a heads.json file")
