"""OpenSSH ``sshsig`` signatures, the ``allowed_signers`` list, and key digests. Verify-only.

Layout (OpenSSH PROTOCOL.sshsig):

    blob:        byte[6] "SSHSIG"  uint32 version=1  string publickey  string namespace
                 string reserved  string hash_algorithm  string signature
    signed data: byte[6] "SSHSIG"  string namespace  string reserved  string hash_algorithm
                 string H(message)

``publickey`` is ``string "ssh-ed25519"  string key(32)``; ``signature`` is
``string "ssh-ed25519"  string sig(64)``. The verifier accepts exactly version 1, the
``biolean-ledger`` namespace, ``sha512``, an empty ``reserved`` and no trailing bytes anywhere
(spec §4). Everything else is refused with the reason in the exception.
"""
from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass

from methods_graph.biolean.ed25519 import is_small_order, verify

NAMESPACE = "biolean-ledger"
KEY_TYPE = "ssh-ed25519"
_MAGIC = b"SSHSIG"
_ARMOR_BEGIN = "-----BEGIN SSH SIGNATURE-----"
_ARMOR_END = "-----END SSH SIGNATURE-----"
_KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-")
_REFUSED_OPTIONS = frozenset({"cert-authority", "valid-after", "valid-before"})

# The two test keypairs under tests/fixtures/biolean/ledger/keys/, trusted by nothing outside
# the fixtures. `init` refuses them (spec §9, Fixtures).
FIXTURE_KEY_DIGESTS: frozenset[str] = frozenset({
    "1438014318807ad1a74d1943c05793434d3cbd11009797a646bbc3cd68c7c51e",   # A
    "778b5c6aae736dad91e838b21ac186bf8590c64cf94e73db1c27c69c53de34d0",   # B
})


class SshsigError(ValueError):
    """A signature, key or armor the verifier refuses; ``str(exc)`` is the reason."""


class AllowedSignersError(ValueError):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"allowed_signers line {line}: {reason}")
        self.line = line
        self.reason = reason


# ---------------------------------------------------------------------------
# SSH wire strings and keys
# ---------------------------------------------------------------------------

def _string(buf: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(buf):
        raise SshsigError("truncated length")
    (n,) = struct.unpack(">I", buf[offset:offset + 4])
    end = offset + 4 + n
    if end > len(buf):
        raise SshsigError("truncated string")
    return buf[offset + 4:end], end


def _pack(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def parse_key_blob(blob: bytes) -> bytes:
    """The 32-byte key of an ``ssh-ed25519`` public-key blob; SshsigError for anything else."""
    key_type, offset = _string(blob, 0)
    if key_type != KEY_TYPE.encode("ascii"):
        raise SshsigError(f"key type {key_type.decode('ascii', 'replace')!r} is not {KEY_TYPE}")
    key, offset = _string(blob, offset)
    if offset != len(blob):
        raise SshsigError("trailing bytes after the key")
    if len(key) != 32:
        raise SshsigError(f"ed25519 key must be 32 bytes, got {len(key)}")
    return key


def key_digest(blob: bytes) -> str:
    """sha256 of the raw blob, 64 lowercase hex: the contributor id (``by`` without its prefix)."""
    return hashlib.sha256(blob).hexdigest()


def key16(blob: bytes) -> str:
    return key_digest(blob)[:16]


_key16 = key16      # module alias, so Signer.key16 can call the function


def fingerprint(blob: bytes) -> str:
    """The form ``ssh-keygen -lf`` prints: ``SHA256:`` + unpadded base64 of the digest."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def parse_public_key_line(text: str) -> tuple[bytes, str]:
    """``(blob, comment)`` from one ``ssh-ed25519 AAAA... comment`` line.

    Refuses every other type: ``sk-ssh-ed25519@openssh.com``, ``*-cert-v01@openssh.com``, RSA.
    Refuses text with more than one non-empty line: the comment would carry the rest of the
    file, and ``allowed_signers_line`` would write it out as more trusted keys.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        raise SshsigError(f"expected one public key line, got {len(lines)}")
    fields = text.strip().split(None, 2)
    if len(fields) < 2:
        raise SshsigError("not a public key line")
    if fields[0] != KEY_TYPE:
        raise SshsigError(f"key type {fields[0]!r} is not {KEY_TYPE}")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except ValueError as exc:                      # binascii.Error is a ValueError
        raise SshsigError(f"public key is not base64: {exc}") from None
    parse_key_blob(blob)
    return blob, (fields[2].strip() if len(fields) == 3 else "")


# ---------------------------------------------------------------------------
# sshsig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sshsig:
    public_key_blob: bytes
    public_key: bytes
    namespace: str
    hash_algorithm: str
    signature: bytes


def parse_sshsig(sig: str) -> Sshsig:
    """Decode and structurally check a ``sig`` value (spec §1, §4). Does not verify."""
    if not isinstance(sig, str) or not sig:
        raise SshsigError("sig must be a non-empty string")
    try:
        blob = base64.b64decode(sig, validate=True)
    except ValueError as exc:
        raise SshsigError(f"sig is not standard base64: {exc}") from None
    if base64.b64encode(blob).decode("ascii") != sig:
        raise SshsigError("sig is not canonical base64")
    if blob[:6] != _MAGIC:
        raise SshsigError("missing SSHSIG preamble")
    if len(blob) < 10:
        raise SshsigError("truncated version")
    (version,) = struct.unpack(">I", blob[6:10])
    if version != 1:
        raise SshsigError(f"sshsig version {version} is not 1")
    pk_blob, offset = _string(blob, 10)
    namespace, offset = _string(blob, offset)
    reserved, offset = _string(blob, offset)
    hash_algorithm, offset = _string(blob, offset)
    signature, offset = _string(blob, offset)
    if offset != len(blob):
        raise SshsigError("trailing bytes after the signature")
    if reserved != b"":
        raise SshsigError("reserved field is not empty")
    if hash_algorithm != b"sha512":
        raise SshsigError(f"hash algorithm {hash_algorithm!r} is not sha512")
    public_key = parse_key_blob(pk_blob)
    sig_type, soff = _string(signature, 0)
    sig_value, soff = _string(signature, soff)
    if soff != len(signature):
        raise SshsigError("trailing bytes inside the signature string")
    if sig_type != KEY_TYPE.encode("ascii"):
        raise SshsigError(f"signature type {sig_type!r} is not {KEY_TYPE}")
    if len(sig_value) != 64:
        raise SshsigError(f"ed25519 signature must be 64 bytes, got {len(sig_value)}")
    try:
        ns = namespace.decode("ascii")
    except UnicodeDecodeError:
        raise SshsigError("namespace is not ASCII") from None
    return Sshsig(pk_blob, public_key, ns, "sha512", sig_value)


def signed_data(message: bytes, namespace: str = NAMESPACE) -> bytes:
    """What ssh-keygen signs: the preamble, namespace, reserved, hash name and sha512(message)."""
    return (_MAGIC + _pack(namespace.encode("ascii")) + _pack(b"") + _pack(b"sha512")
            + _pack(hashlib.sha512(message).digest()))


def verify_sshsig(sig: str, message: bytes, *, namespace: str = NAMESPACE) -> bytes:
    """The signer's public-key blob when ``sig`` verifies over ``message`` in ``namespace``;
    SshsigError otherwise."""
    parsed = parse_sshsig(sig)
    if parsed.namespace != namespace:
        raise SshsigError(f"namespace {parsed.namespace!r} is not {namespace!r}")
    if not verify(parsed.public_key, signed_data(message, namespace), parsed.signature):
        raise SshsigError("signature does not verify")
    return parsed.public_key_blob


def dearmor(stdout: bytes) -> str:
    """``sig`` from ssh-keygen's armored stdout: the base64 lines joined with no whitespace."""
    try:
        text = stdout.decode("ascii")
    except UnicodeDecodeError:
        raise SshsigError("armor is not ASCII") from None
    lines = [line.strip() for line in text.splitlines()]
    if _ARMOR_BEGIN not in lines or _ARMOR_END not in lines:
        raise SshsigError("no SSH SIGNATURE armor in the output")
    start, end = lines.index(_ARMOR_BEGIN), lines.index(_ARMOR_END)
    body = "".join(lines[start + 1:end]) if end > start else ""
    if not body:
        raise SshsigError("empty armor")
    return body


def armor(sig: str) -> str:
    """The armored form ``ssh-keygen -Y verify`` reads: base64 wrapped at 70 columns."""
    lines = [sig[i:i + 70] for i in range(0, len(sig), 70)]
    return "\n".join([_ARMOR_BEGIN, *lines, _ARMOR_END]) + "\n"


# ---------------------------------------------------------------------------
# allowed_signers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signer:
    line: int
    principals: tuple[str, ...]
    namespaces: tuple[str, ...] | None      # None: every namespace, as OpenSSH reads it
    blob: bytes

    @property
    def digest(self) -> str:
        return key_digest(self.blob)

    @property
    def key16(self) -> str:
        return _key16(self.blob)

    def permits(self, namespace: str) -> bool:
        return self.namespaces is None or namespace in self.namespaces


def _split_fields(line: str, lineno: int) -> list[str]:
    """Fields separated by space and tab outside double quotes.

    This is how OpenSSH's ``sshkey_advance_past_options`` reads the options field, and only that
    field: there ``\\"`` is an escaped quote (both characters stay in the field and the quoted
    state does not change) and every other backslash is literal. OpenSSH reads the other fields
    differently, so ``parse_allowed_signers`` refuses whatever the two readings would split apart:
    the principals with ``strdelimw``, which has no escapes and ends the principals at the closing
    quote (a principals field holding ``\\"``, or a ``"`` that does not enclose the whole field, is
    refused); the key type and base64 with ``sshkey_read``, which knows no quotes (a quote there
    fails the key-type or base64 check). Any other whitespace (a form feed, U+2028) stays inside
    its field; ``_refuse_stray_whitespace`` then refuses it wherever it lands outside the comment.
    """
    out: list[str] = []
    cur = ""
    quoted = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and line.startswith('"', i + 1):
            cur += '\\"'
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
            cur += ch
        elif ch in " \t" and not quoted:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
        i += 1
    if quoted:
        raise AllowedSignersError(lineno, "unterminated quote")
    if cur:
        out.append(cur)
    return out


def _refuse_stray_whitespace(field: str, lineno: int) -> None:
    """A field holding whitespace outside double quotes is malformed: OpenSSH would not split
    there, so reading two fields out of it could permit what OpenSSH refuses. Quotes are tracked
    as ``_split_fields`` tracks them: ``\\"`` never opens or closes one."""
    quoted = False
    i = 0
    while i < len(field):
        ch = field[i]
        if ch == "\\" and field.startswith('"', i + 1):
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            raise AllowedSignersError(lineno, f"field {field!r} holds whitespace other than space or tab")
        i += 1


def _parse_options(opts: str, lineno: int) -> tuple[str, ...] | None:
    """The ``namespaces`` list, or None when absent. Every other option is refused (spec §4)."""
    namespaces: tuple[str, ...] | None = None
    seen: set[str] = set()
    i = 0
    while i < len(opts):
        j = i
        while j < len(opts) and opts[j] not in "=,":
            j += 1
        name = opts[i:j].lower()
        if not name:
            raise AllowedSignersError(lineno, "empty option")
        value: str | None = None
        if j < len(opts) and opts[j] == "=":
            if j + 1 >= len(opts) or opts[j + 1] != '"':
                raise AllowedSignersError(lineno, f"option {name} needs a double-quoted value")
            # As OpenSSH's opt_dequote reads it: \" is a literal quote, every other backslash is
            # literal, and the value ends at the first unescaped quote.
            chars: list[str] = []
            k = j + 2
            while k < len(opts) and opts[k] != '"':
                if opts[k] == "\\" and opts.startswith('"', k + 1):
                    k += 1
                chars.append(opts[k])
                k += 1
            if k >= len(opts):
                raise AllowedSignersError(lineno, f"option {name}: unterminated value")
            value = "".join(chars)
            i = k + 1
        else:
            i = j
        if i < len(opts):
            if opts[i] != ",":
                raise AllowedSignersError(lineno, f"option {name}: expected ',' after the value")
            i += 1
            if i == len(opts):                     # OpenSSH: "unexpected end-of-options"
                raise AllowedSignersError(lineno, "trailing ',' after the last option")
        if name in seen:
            raise AllowedSignersError(lineno, f"option {name} appears twice")
        seen.add(name)
        if name == "namespaces":
            if value is None:
                raise AllowedSignersError(lineno, "namespaces needs a quoted value")
            if any(c in value for c in "*?!"):
                raise AllowedSignersError(lineno, "namespaces pattern characters (* ? !) are not supported")
            # OpenSSH's match_pattern_list compares each entry verbatim, untrimmed, so " x" never
            # matches "x". Stripping here would permit what OpenSSH denies; refuse instead.
            entries = value.split(",")
            for entry in entries:
                if not entry or entry != entry.strip():
                    raise AllowedSignersError(lineno, f"namespaces entry {entry!r} is empty or has surrounding whitespace")
                # match_pattern_list copies each entry into a 1024-byte buffer and matches nothing
                # at all once an entry reaches 1023 bytes, wherever it sits in the list.
                size = len(entry.encode("utf-8"))
                if size >= 1023:
                    raise AllowedSignersError(lineno, f"namespaces entry of {size} bytes: OpenSSH matches "
                                                      "no namespace when an entry has 1023 bytes or more")
            namespaces = tuple(entries)
        elif name in _REFUSED_OPTIONS:
            raise AllowedSignersError(lineno, f"option {name} is not supported by this verifier")
        else:
            raise AllowedSignersError(lineno, f"unknown option {name}")
    return namespaces


def parse_allowed_signers(text: str) -> list[Signer]:
    """OpenSSH allowed_signers, restricted to what the verifier implements (spec §4).

    Raises AllowedSignersError naming the line for: a key type other than ssh-ed25519, any
    option but ``namespaces``, a namespaces pattern, a namespaces entry of 1023 UTF-8 bytes or
    more (OpenSSH then matches no namespace), a principals field holding ``\\"`` (OpenSSH does
    not read it as an escape there) or a ``"`` that does not enclose the whole field (OpenSSH
    ends the principals at the closing quote), a duplicate key or key16, a small-order key, and a NUL
    anywhere in the line, even in a comment (stricter than OpenSSH, which reads a line only up
    to its first NUL). Blank lines and ``#`` comments are skipped; option names are
    case-insensitive. Lines end at ``\\n`` only, as OpenSSH reads them with getline: a ``\\r``,
    form feed or U+2028 inside a comment is comment text, never a second line
    (``str.splitlines`` would split there). A line is stripped of C whitespace only (space, tab,
    CR, LF, VT, FF), so other whitespace after the key stays in it and is refused, as OpenSSH's
    base64 decoder refuses it. Fields split on space and tab only, as in OpenSSH; other
    whitespace between two fields before the comment is refused.
    """
    signers: list[Signer] = []
    seen_blobs: dict[bytes, int] = {}
    seen_key16: dict[str, int] = {}
    usage = "expected: principals [options] ssh-ed25519 <base64> [comment]"
    for lineno, raw in enumerate(text.split("\n"), 1):
        if "\x00" in raw:
            raise AllowedSignersError(lineno, "NUL byte: OpenSSH reads the line only up to it")
        line = raw.strip(" \t\r\n\v\f")             # C isspace; other whitespace stays and is refused
        if not line or line.startswith("#"):
            continue
        fields = _split_fields(line, lineno)
        if '\\"' in fields[0]:
            # OpenSSH splits the principals with strdelimw, which has no escapes: there \" opens or
            # closes a quote, so the two tokenizers would read different fields. Stricter: refuse.
            raise AllowedSignersError(lineno, f"principals field {fields[0]!r} holds an escaped quote: "
                                              "OpenSSH has no escapes there")
        for field in fields[:2]:                   # the principals; the options or the key type
            _refuse_stray_whitespace(field, lineno)
        if '"' in fields[0] and not (len(fields[0]) >= 2 and fields[0][0] == fields[0][-1] == '"'
                                     and '"' not in fields[0][1:-1]):
            # strdelimw ends the principals at the closing quote and OpenSSH reads the rest of the
            # token as options: `"a"namespaces="git"` is principal a, limited to git. One field here
            # would be one principal with no options, permitting every namespace. Stricter: refuse.
            raise AllowedSignersError(lineno, f"principals field {fields[0]!r} holds a double quote that does not "
                                              "enclose the whole field: OpenSSH ends the principals at the closing quote")
        if len(fields) < 3:
            raise AllowedSignersError(lineno, usage)
        principals_raw = fields[0]
        if len(principals_raw) >= 2 and principals_raw[0] == principals_raw[-1] == '"':
            principals_raw = principals_raw[1:-1]
        principals = tuple(p for p in principals_raw.split(",") if p)
        if not principals:
            raise AllowedSignersError(lineno, "no principal")
        if fields[1] == KEY_TYPE or fields[1].startswith(_KEY_TYPE_PREFIXES):
            options, key_type, b64 = "", fields[1], fields[2]
        elif len(fields) >= 4:
            options, key_type, b64 = fields[1], fields[2], fields[3]
        else:
            raise AllowedSignersError(lineno, usage)
        for field in (key_type, b64):              # everything after b64 is the comment
            _refuse_stray_whitespace(field, lineno)
        if key_type != KEY_TYPE:
            raise AllowedSignersError(lineno, f"key type {key_type!r} is not {KEY_TYPE}")
        namespaces = _parse_options(options, lineno)
        try:
            blob = base64.b64decode(b64, validate=True)
            key = parse_key_blob(blob)
        except ValueError as exc:                  # SshsigError and binascii.Error are ValueErrors
            raise AllowedSignersError(lineno, f"bad key: {exc}") from None
        if is_small_order(key):
            raise AllowedSignersError(lineno, "small-order key: one fixed signature would verify every message")
        if blob in seen_blobs:
            raise AllowedSignersError(lineno, f"key already listed on line {seen_blobs[blob]}")
        short = _key16(blob)
        if short in seen_key16:
            raise AllowedSignersError(lineno, f"key16 {short} collides with line {seen_key16[short]}")
        seen_blobs[blob] = lineno
        seen_key16[short] = lineno
        signers.append(Signer(lineno, principals, namespaces, blob))
    return signers


def find_signer(signers: list[Signer], blob: bytes) -> Signer | None:
    for signer in signers:
        if signer.blob == blob:
            return signer
    return None


def allowed_signers_line(principal: str, blob: bytes, comment: str = "") -> str:
    """One line in the form ``init`` writes: the principal, the ledger namespace, the key.

    Refuses (AllowedSignersError, line 0: not read from a file) any principal the reader would
    not hand back as written: empty, starting with ``#`` (the line reads as a comment), or
    holding ``,`` (several principals), whitespace (a quoted token) or ``"``. Also refuses a
    ``"`` or any line break ``str.splitlines`` honours in the comment, and a NUL in either
    (OpenSSH would read the line only up to it, and the reader refuses it). Each would write a
    file that re-parses to another signer, to none, fails to load, or changes its principal.
    """
    if not principal:
        raise AllowedSignersError(0, "empty principal")
    if principal.startswith("#"):
        raise AllowedSignersError(0, f"principal {principal!r} starts with '#': the line would read as a comment")
    if "," in principal:
        raise AllowedSignersError(0, f"principal {principal!r} contains ',': it would read as several principals")
    if any(c.isspace() for c in principal):
        raise AllowedSignersError(0, f"principal {principal!r} contains whitespace")
    for what, value in (("principal", principal), ("comment", comment)):
        if "\x00" in value:
            raise AllowedSignersError(0, f"{what} {value!r} contains a NUL byte: OpenSSH would end the line there")
        if '"' in value or (value and value.splitlines() != [value]):
            raise AllowedSignersError(0, f"{what} {value!r} contains a double quote or a line break")
    b64 = base64.b64encode(blob).decode("ascii")
    tail = f" {comment}" if comment else ""
    return f'{principal} namespaces="{NAMESPACE}" {KEY_TYPE} {b64}{tail}\n'
