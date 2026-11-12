"""RFC 8032 §5.1.7 verification, pinned by the §7.1 vectors and by what must fail."""
import json
from pathlib import Path

from methods_graph.biolean.ed25519 import L, P, is_small_order, verify

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "biolean" / "ledger" / "rfc8032-ed25519.json").read_text())

# The eight encodings whose point A satisfies [8]A = identity (enumerated by brute force from a
# torsion generator during planning; the two with y = 0 and the identity are the well-known ones).
SMALL_ORDER = [
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
]


def _v(v):
    return bytes.fromhex(v["public_key"]), bytes.fromhex(v["message"]), bytes.fromhex(v["signature"])


def test_rfc8032_vectors_verify():
    assert [v["name"] for v in VECTORS] == ["1", "2", "3", "1024", "SHA(abc)"]
    for v in VECTORS:
        pk, msg, sig = _v(v)
        assert verify(pk, msg, sig), v["name"]


def test_rfc8032_vector_with_one_bit_flipped_fails():
    # Break: `return True` after the length checks; or comparing only the y coordinate.
    for v in VECTORS:
        pk, msg, sig = _v(v)
        for i in range(64):
            bad = bytearray(sig)
            bad[i] ^= 1
            assert not verify(pk, msg, bytes(bad)), (v["name"], i)
        bad_pk = bytearray(pk)
        bad_pk[0] ^= 1
        assert not verify(bytes(bad_pk), msg, sig)
        assert not verify(pk, msg + b"\x00", sig)
        # Break: `_equal` comparing only y. (R, L - S) puts -[S]B against R + [k]A: same y,
        # opposite x, and a second valid signature for the same message if x is ignored.
        s = int.from_bytes(sig[32:], "little")
        assert not verify(pk, msg, sig[:32] + (L - s).to_bytes(32, "little")), v["name"]


def test_non_canonical_s_rejected():
    # Break: drop the `s >= L` check. S + L is the same scalar mod L, so the equation still holds.
    for v in VECTORS:
        pk, msg, sig = _v(v)
        s = int.from_bytes(sig[32:], "little") + L
        assert s < 2**256
        assert not verify(pk, msg, sig[:32] + s.to_bytes(32, "little")), v["name"]


def test_non_canonical_point_rejected():
    # Break: drop the `y >= P` rejection (y_plus below then decodes to the identity, mod p); or
    # drop the `x == 0 and x_0 == 1` rejection (one_with_sign then does). Each break lets one of
    # the two encodings through, and the identity forgery (R = identity, S = 0) then verifies
    # with that encoding as A or as R.
    pk, msg, sig = _v(VECTORS[0])
    identity = bytes.fromhex(SMALL_ORDER[2])
    forged = identity + bytes(32)
    assert verify(identity, b"m", forged)                       # the forgery this test guards against
    y_plus = (P + 1).to_bytes(32, "little")                     # y = p + 1, sign bit clear
    one_with_sign = (1 | (1 << 255)).to_bytes(32, "little")     # y = 1, x = 0, x_0 = 1
    for bad in (y_plus, one_with_sign):
        assert is_small_order(bad)                              # does not decode at all
        assert not verify(bad, msg, sig)
        assert not verify(pk, msg, bad + sig[32:])
        assert not verify(bad, b"m", forged), bad.hex()               # as A
        assert not verify(identity, b"m", bad + bytes(32)), bad.hex()  # as R
    # bit 255 is the sign of x, not an unused bit: setting it on a valid key gives a different key
    flipped = bytearray(pk)
    flipped[31] ^= 0x80
    assert not verify(bytes(flipped), msg, sig)


def test_small_order_keys_are_detected_and_the_identity_key_forges():
    # Break: `is_small_order` checking [4]A or [2]A instead of [8]A misses the order-8 points.
    for enc in SMALL_ORDER:
        assert is_small_order(bytes.fromhex(enc)), enc
    for v in VECTORS:
        assert not is_small_order(bytes.fromhex(v["public_key"]))
    # Why the list matters: under the identity key, R = identity and S = 0 verifies every message.
    identity = bytes.fromhex(SMALL_ORDER[2])
    forged = identity + bytes(32)
    assert verify(identity, b"one message", forged) and verify(identity, b"another", forged)


def test_wrong_lengths_fail_without_raising():
    # Break: check only the key's length, or only a short signature (`len(signature) < 64`): a
    # 65-byte signature whose first 64 bytes verify must still fail.
    pk, msg, sig = _v(VECTORS[1])
    assert verify(pk, msg, sig)
    assert not verify(pk[:31], msg, sig)
    assert not verify(pk, msg, sig[:63])
    assert not verify(pk + b"\x00", msg, sig)
    assert not verify(pk, msg, sig + b"\x00")
    assert is_small_order(b"")
