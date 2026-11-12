"""sshsig parsing and verification against real ssh-keygen output; the allowed_signers reader."""
import base64
import struct
from pathlib import Path

import pytest

from methods_graph.biolean import sshsig
from methods_graph.biolean.sshsig import (
    FIXTURE_KEY_DIGESTS, NAMESPACE, AllowedSignersError, SshsigError, allowed_signers_line, armor,
    dearmor, find_signer, fingerprint, key16, key_digest, parse_allowed_signers, parse_public_key_line,
    parse_sshsig, verify_sshsig)
from tests.test_biolean_ed25519 import SMALL_ORDER

LFIX = Path(__file__).parent / "fixtures" / "biolean" / "ledger"
A_PUB = (LFIX / "keys" / "a.pub").read_text()
B_PUB = (LFIX / "keys" / "b.pub").read_text()
A_BLOB, _ = parse_public_key_line(A_PUB)
B_BLOB, _ = parse_public_key_line(B_PUB)
ONE = (LFIX / "known" / "message-one.txt").read_bytes()
TWO = (LFIX / "known" / "message-two.txt").read_bytes()


def _sig(name):
    return dearmor((LFIX / "known" / name).read_bytes())


def _pack(b):
    return struct.pack(">I", len(b)) + b


def _rebuild(sig, *, version=1, pk=None, namespace=None, reserved=b"", halg=b"sha512", signature=None, trailing=b""):
    """Re-encode a parsed sshsig with one field changed."""
    p = parse_sshsig(sig)
    pk_blob = pk if pk is not None else p.public_key_blob
    ns = (namespace if namespace is not None else p.namespace).encode()
    sig_str = signature if signature is not None else _pack(b"ssh-ed25519") + _pack(p.signature)
    blob = (b"SSHSIG" + struct.pack(">I", version) + _pack(pk_blob) + _pack(ns) + _pack(reserved)
            + _pack(halg) + _pack(sig_str) + trailing)
    return base64.b64encode(blob).decode()


def test_real_ssh_keygen_signature_verifies():
    assert verify_sshsig(_sig("a-one.sig"), ONE) == A_BLOB
    assert verify_sshsig(_sig("a-two.sig"), TWO) == A_BLOB
    assert verify_sshsig(_sig("b-one.sig"), ONE) == B_BLOB


def test_wrong_namespace_fails():
    with pytest.raises(SshsigError, match="namespace"):
        verify_sshsig(_sig("a-one-other-namespace.sig"), ONE)
    # and the same signature verifies in the namespace it was made for
    assert verify_sshsig(_sig("a-one-other-namespace.sig"), ONE, namespace="other-ns") == A_BLOB


def test_wrong_message_fails():
    with pytest.raises(SshsigError, match="does not verify"):
        verify_sshsig(_sig("a-one.sig"), TWO)


def test_sshsig_fields_are_enforced():
    # Break: skip any one of these checks; the matching case then verifies or raises elsewhere.
    # Every refusal is SshsigError, never another exception (a bare ValueError, UnicodeDecodeError
    # or struct.error would escape pytest.raises below).
    sig = _sig("a-one.sig")
    p = parse_sshsig(sig)
    assert (p.namespace, p.hash_algorithm, len(p.signature), len(p.public_key)) == (NAMESPACE, "sha512", 64, 32)
    blob = base64.b64decode(sig)

    def b64(raw):
        return base64.b64encode(raw).decode()

    cases = {
        "bad magic": b64(b"SSHSIH" + blob[6:]),
        "non-ed25519 signature type": _rebuild(sig, signature=_pack(b"ssh-rsa") + _pack(p.signature)),
        "truncated in the version": b64(blob[:8]),
        "truncated in the signature": b64(blob[:-1]),
        "non-ASCII namespace": _rebuild(sig, namespace="biolean-lédger"),
        "version": _rebuild(sig, version=2),
        "key type": _rebuild(sig, pk=_pack(b"ssh-rsa") + _pack(p.public_key)),
        "63 bytes": _rebuild(sig, signature=_pack(b"ssh-ed25519") + _pack(p.signature[:63])),
        "sha256": _rebuild(sig, halg=b"sha256"),
        "reserved": _rebuild(sig, reserved=b"x"),
        "trailing bytes": _rebuild(sig, trailing=b"\x00"),
        "trailing inside signature": _rebuild(sig, signature=_pack(b"ssh-ed25519") + _pack(p.signature) + b"\x00"),
        "armor": (LFIX / "known" / "a-one.sig").read_text(),
        "whitespace": sig[:10] + "\n" + sig[10:],
        "urlsafe": sig.replace("+", "-").replace("/", "_"),
        "empty": "",
        "non-canonical padding": sig[:-3] + ("h" if sig[-3] == "g" else "g") + "==",
    }
    for name, bad in cases.items():
        with pytest.raises(SshsigError):
            verify_sshsig(bad, ONE)
        # every refusal is structural: parse_sshsig itself raises, before any crypto
        with pytest.raises(SshsigError):
            parse_sshsig(bad)
    assert verify_sshsig(sig, ONE) == A_BLOB          # the unmodified value still passes


def test_dearmor_and_armor_round_trip():
    raw = (LFIX / "known" / "a-one.sig").read_bytes()
    sig = dearmor(raw)
    assert "\n" not in sig and sig.endswith("==")
    assert armor(sig) == raw.decode()
    with pytest.raises(SshsigError, match="armor"):
        dearmor(b"Signing data on standard input\n")


def test_public_key_digests_match_ssh_keygen_lf():
    assert key16(A_BLOB) == "1438014318807ad1" and key16(B_BLOB) == "778b5c6aae736dad"
    assert fingerprint(A_BLOB) == "SHA256:FDgBQxiAetGnTRlDwFeTQ008vREAl5emRrvDzWjHxR4"
    assert fingerprint(B_BLOB) == "SHA256:d4tcaq5zba2R6DiyGsGGv4WQxkz5TnPbHCfGnFPeNNA"
    assert FIXTURE_KEY_DIGESTS == {key_digest(A_BLOB), key_digest(B_BLOB)}
    assert parse_public_key_line(A_PUB)[1] == "biolean-fixture-A"


def test_unsupported_key_type_refused():
    b64 = A_PUB.split()[1]
    for kind in ("ssh-rsa", "sk-ssh-ed25519@openssh.com", "ssh-ed25519-cert-v01@openssh.com", "ecdsa-sha2-nistp256"):
        with pytest.raises(SshsigError, match=kind):
            parse_public_key_line(f"{kind} {b64} c")
        with pytest.raises(AllowedSignersError, match=kind):
            parse_allowed_signers(f"alice {kind} {b64} c\n")
    with pytest.raises(SshsigError):
        parse_public_key_line("not a key")


def _line(principal="alice", options='namespaces="biolean-ledger"', pub=A_PUB):
    kind, b64, comment = pub.split()
    opts = f" {options}" if options else ""
    return f"{principal}{opts} {kind} {b64} {comment}\n"


def test_allowed_signers_parses_principals_options_and_skips_comments():
    text = "# trusted list\n\n" + _line('"alice smith,bob"', 'namespaces="biolean-ledger,git"') + _line("carol", "", B_PUB)
    signers = parse_allowed_signers(text)
    assert [s.line for s in signers] == [3, 4]
    assert signers[0].principals == ("alice smith", "bob") and signers[0].namespaces == ("biolean-ledger", "git")
    assert signers[0].blob == A_BLOB and signers[0].key16 == "1438014318807ad1"
    assert signers[1].namespaces is None and signers[1].blob == B_BLOB
    assert find_signer(signers, B_BLOB) is signers[1] and find_signer(signers, b"nope") is None
    assert parse_allowed_signers(allowed_signers_line("dave", A_BLOB, "c"))[0].permits(NAMESPACE)


def test_allowed_signers_line_round_trips_or_refuses():
    # A written line re-parses to exactly one Signer with that principal and blob, including the
    # comment a real .pub carries and a comment with spaces.
    _, comment = parse_public_key_line(A_PUB)
    for principal, com in (("dave", "c"), ("dave", comment), ("fixture-a", ""), ("a@b.org", "x y")):
        [s] = parse_allowed_signers(allowed_signers_line(principal, A_BLOB, com))
        assert (s.principals, s.blob, s.namespaces) == ((principal,), A_BLOB, (NAMESPACE,))
    # Break: split the whole text. A second line in a .pub rides in as the "comment", and
    # allowed_signers_line would then write a second trusted key (B) into the file.
    with pytest.raises(SshsigError, match="line"):
        parse_public_key_line(A_PUB + "bob " + B_PUB)
    # Break: write principal and comment unchecked. Each of these writes a file that re-parses to
    # a second signer, to none (a leading '#' makes the line a comment), to two principals (','),
    # to a quoted principal (whitespace), fails to load ("unterminated quote"), or loses its principal;
    # a NUL ends the line early for OpenSSH, and the reader refuses it.
    for principal, com in (("", "c"), ("#x", "c"), ("a,b", "c"), ("dave smith", "c"), ("dave\tsmith", "c"),
                           ('da"ve', "c"), ("dave", 'c"'), ("dave", "c\nbob " + B_PUB),
                           ("dave\rbob", "c"), ("dave", "c\u2028bob " + B_PUB.strip()),   # U+2028: no \n or \r
                           ("dave\x00", ""), ("dave", "c\x00")):
        with pytest.raises(AllowedSignersError):
            allowed_signers_line(principal, A_BLOB, com)


def test_allowed_signers_splits_lines_on_newline_only():
    # Break: split with str.splitlines. OpenSSH reads lines with getline, so a lone \r, a form feed
    # or U+2028 inside a comment is comment text, not a second trusted line (checked against
    # OpenSSH 10.3p1: `ssh-keygen -Y verify -I bob` refuses key B for every break below).
    kind, b64, _ = A_PUB.split()
    for brk in ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
        [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64} c{brk}bob {B_PUB}')
        assert (s.line, s.principals, s.blob) == (1, ("dave",), A_BLOB)
    # A CRLF file reads as OpenSSH reads it: the \r lands in the comment or after the key token.
    crlf = (_line("alice") + f"bob {kind} {B_PUB.split()[1]}\n").replace("\n", "\r\n")
    assert [(s.line, s.blob) for s in parse_allowed_signers(crlf)] == [(1, A_BLOB), (2, B_BLOB)]


def test_allowed_signers_splits_fields_on_space_and_tab_only():
    # Break: split fields on every whitespace character. OpenSSH separates fields with space and
    # tab only, so a form feed between the options and the key type leaves a malformed field, and
    # OpenSSH 10.3p1 refuses the line. The reader refuses it too, never a permitted signer, and
    # likewise for any other non-space, non-tab whitespace between two fields.
    kind, b64, _ = A_PUB.split()
    ns = 'namespaces="biolean-ledger"'
    for text in (f"dave {ns}\x0c{kind} {b64}\n", f"dave {ns}\x0c{kind} {b64} c\n", f"dave {ns}\u2028{kind} {b64} c\n",
                 f"dave\x0c{ns} {kind} {b64} c\n", f"dave {ns} {kind}\x0c{b64} c\n", f"dave {ns} {kind} {b64}\x0cc\n",
                 f"dave\x0b{kind} {b64}\n"):
        with pytest.raises(AllowedSignersError, match="whitespace other than space or tab") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1


def test_allowed_signers_escaped_quote_reads_as_openssh_does():
    # Break: let \" toggle the quoted state. OpenSSH's options tokenizer skips \" without toggling,
    # so the value below never closes and OpenSSH 10.3p1 refuses the line as an unterminated quote.
    # A toggling tokenizer closes it at x\" (the reader once permitted namespaces
    # ('biolean-ledger', 'x\\') here), so the reason is pinned, not only the refusal.
    kind, b64, _ = A_PUB.split()
    for text in (f'dave namespaces="biolean-ledger,x\\" {kind} {b64}\n',
                 f'dave namespaces="biolean-ledger,x\\" {kind} {b64} c\n'):
        with pytest.raises(AllowedSignersError, match="unterminated quote") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1
    # The value is read as OpenSSH's opt_dequote reads it: \" is a literal quote and every other
    # backslash is literal, so \\" is a backslash then an escaped quote. After an escaped quote the
    # value is still quoted, so a space there is inside it, not stray whitespace. OpenSSH 10.3p1
    # verifies key A in biolean-ledger on each of these lines.
    for value, want in (('biolean-ledger,x\\"y', ("biolean-ledger", 'x"y')),
                        ('biolean-ledger,x\\" y', ("biolean-ledger", 'x" y')),
                        ('x\\\\"y,biolean-ledger', ('x\\"y', "biolean-ledger"))):
        [s] = parse_allowed_signers(f'dave namespaces="{value}" {kind} {b64}\n')
        assert (s.namespaces, s.blob) == (want, A_BLOB) and s.permits(NAMESPACE)
    # OpenSSH splits the principals with strdelimw, which has no escapes, so the two tokenizers read
    # this line differently; OpenSSH 10.3p1 refuses it, and any principals field holding \" is refused.
    with pytest.raises(AllowedSignersError, match="escaped quote") as exc:
        parse_allowed_signers(f'"a\\" b" namespaces="biolean-ledger" {kind} {b64}\n')
    assert exc.value.line == 1


def test_allowed_signers_quote_that_closes_inside_the_principals_field_is_refused():
    # Break: drop the refusal. OpenSSH's strdelimw ends the principals at the closing quote and
    # reads the rest of the token as options: OpenSSH 10.3p1 denies key A in biolean-ledger on the
    # first two lines (their principals are "a" and "ax", limited to namespaces="git") and refuses
    # the third ("invalid key"). Read as one field, each line permitted biolean-ledger here.
    kind, b64, _ = A_PUB.split()
    for principals in ('"a"namespaces="git"', 'a"x"namespaces="git"', '"a"b namespaces="biolean-ledger"'):
        with pytest.raises(AllowedSignersError, match="double quote") as exc:
            parse_allowed_signers(f"# trusted list\n{principals} {kind} {b64}\n")
        assert exc.value.line == 2, principals
    # A quote that encloses the whole field is the one OpenSSH form, and OpenSSH 10.3p1 accepts it.
    [s] = parse_allowed_signers(f'"alice smith,bob" namespaces="biolean-ledger" {kind} {b64}\n')
    assert (s.principals, s.blob) == (("alice smith", "bob"), A_BLOB) and s.permits(NAMESPACE)


def test_allowed_signers_strips_c_whitespace_only():
    # Break: strip the line with str.strip(), which drops every Unicode whitespace character. After
    # the key (no comment) OpenSSH's base64 decoder skips only C isspace bytes, so OpenSSH 10.3p1
    # refuses each line below; str.strip() would drop the character first and permit key A.
    kind, b64, _ = A_PUB.split()
    for x in ("\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\xa0", "\u2028", "\u2029"):
        with pytest.raises(AllowedSignersError, match="whitespace other than space or tab") as exc:
            parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64}{x}\n')
        assert exc.value.line == 1
    # C isspace after the key is stripped; OpenSSH 10.3p1 accepts these lines too.
    for x in ("\x0b", "\x0c", "\r"):
        [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64}{x}\n')
        assert (s.line, s.blob) == (1, A_BLOB)
    # Comment text is never checked.
    [s] = parse_allowed_signers(f'dave namespaces="biolean-ledger" {kind} {b64} c\x1c\n')
    assert (s.line, s.blob) == (1, A_BLOB)


def test_allowed_signers_refuses_a_nul_byte_anywhere():
    # Break: read past a NUL. OpenSSH's C string ends there, so to OpenSSH 10.3p1 the first line is
    # just "dave" (invalid), while a NUL-blind reader permits principal 'dave\x00' with key A. A NUL
    # in a comment or a '#' line is refused too: stricter than OpenSSH, never looser.
    kind, b64, _ = A_PUB.split()
    for text in (f'dave\x00 namespaces="biolean-ledger" {kind} {b64}\n',
                 f'dave namespaces="biolean-ledger" {kind} {b64} c\x00d\n',
                 f'# c\x00d\ndave namespaces="biolean-ledger" {kind} {b64}\n'):
        with pytest.raises(AllowedSignersError, match="NUL") as exc:
            parse_allowed_signers(text)
        assert exc.value.line == 1


def test_signer_without_namespaces_option_is_allowed():
    [s] = parse_allowed_signers(_line(options=""))
    assert s.permits("biolean-ledger") and s.permits("anything")


def test_signer_with_other_namespace_is_unknown():
    [s] = parse_allowed_signers(_line(options='namespaces="git"'))
    assert not s.permits("biolean-ledger")
    [s] = parse_allowed_signers(_line(options='NAMESPACES="biolean-ledger"'))   # case-insensitive, as OpenSSH
    assert s.permits("biolean-ledger")


def test_negated_namespace_is_refused_not_permitted():
    # Break: `namespace in value.split(",")` permits "biolean-ledger,!biolean-ledger", which OpenSSH denies.
    for value in ("biolean-ledger,!biolean-ledger", "!biolean-ledger", "biolean-*", "biolean-ledge?"):
        with pytest.raises(AllowedSignersError, match="pattern"):
            parse_allowed_signers(_line(options=f'namespaces="{value}"'))
    # Break: strip each entry, or drop empty ones. OpenSSH's match_pattern_list does not trim, so
    # it refuses the first two (checked against OpenSSH 10.3p1), and a trailing ',' after the last
    # option is "unexpected end-of-options". An empty entry is refused rather than guessed at.
    for opts in ('namespaces="other, biolean-ledger"', 'namespaces=" biolean-ledger"', 'namespaces="biolean-ledger",',
                 'namespaces="biolean-ledger,,git"'):
        with pytest.raises(AllowedSignersError) as exc:
            parse_allowed_signers(_line(options=opts))
        assert exc.value.line == 1


def test_namespaces_entry_of_1023_bytes_or_more_is_refused():
    # Break: no length cap. OpenSSH's match_pattern_list copies each entry into a 1024-byte buffer
    # and matches nothing once an entry reaches 1023 bytes, wherever it sits: OpenSSH 10.3p1
    # verifies with an entry of 1022 bytes beside biolean-ledger and refuses 1023, in either order.
    # Bytes, not characters: 511 two-byte characters are 1022 bytes, and one more 'x' makes 1023.
    for entry in ("x" * 1022, "\xe9" * 511):
        for value in (f"biolean-ledger,{entry}", f"{entry},biolean-ledger"):
            [s] = parse_allowed_signers(_line(options=f'namespaces="{value}"'))
            assert s.permits(NAMESPACE)
    for entry in ("x" * 1023, "\xe9" * 511 + "x"):
        for value in (f"biolean-ledger,{entry}", f"{entry},biolean-ledger"):
            with pytest.raises(AllowedSignersError, match="1023") as exc:
                parse_allowed_signers(_line(options=f'namespaces="{value}"'))
            assert exc.value.line == 1


def test_unsupported_allowed_signers_option_refuses_to_load():
    for opts in ('valid-before="20300101"', 'cert-authority', 'namespaces="biolean-ledger",valid-after="20200101"',
                 'namespaces="biolean-ledger",namespaces="git"', 'namespaces=biolean-ledger', 'bogus="1"'):
        with pytest.raises(AllowedSignersError) as exc:
            parse_allowed_signers(_line(options=opts))
        assert exc.value.line == 1


def test_duplicate_key_and_key16_collision_refused():
    with pytest.raises(AllowedSignersError, match="already listed"):
        parse_allowed_signers(_line("alice") + _line("bob"))
    # A key16 collision needs a second blob with the same first 16 hex of its digest; simulate the
    # index check by monkeypatching key16 to a constant for this call.
    original = sshsig._key16
    sshsig._key16 = lambda blob: "0000000000000000"
    try:
        with pytest.raises(AllowedSignersError, match="key16"):
            parse_allowed_signers(_line("alice") + _line("bob", pub=B_PUB))
    finally:
        sshsig._key16 = original


def test_small_order_keys_refused_in_allowed_signers():
    # Break: drop the is_small_order call; every line then parses.
    for enc in SMALL_ORDER:
        blob = _pack(b"ssh-ed25519") + _pack(bytes.fromhex(enc))
        line = f'evil ssh-ed25519 {base64.b64encode(blob).decode()} c\n'
        with pytest.raises(AllowedSignersError, match="small-order"):
            parse_allowed_signers(line)
    # A 31-byte key, a truncated blob and garbage base64 are refused as bad keys, not accepted.
    for blob in (_pack(b"ssh-ed25519") + _pack(bytes(31)), _pack(b"ssh-ed25519"), b"\x00"):
        with pytest.raises(AllowedSignersError, match="bad key"):
            parse_allowed_signers(f'x ssh-ed25519 {base64.b64encode(blob).decode()}\n')
    with pytest.raises(AllowedSignersError, match="bad key"):
        parse_allowed_signers("x ssh-ed25519 not*base64\n")
