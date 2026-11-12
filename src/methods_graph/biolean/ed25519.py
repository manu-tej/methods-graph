"""Ed25519 verification, RFC 8032 §5.1.7, over the stdlib. Verify-only: no signing code.

Field arithmetic mod p = 2^255 - 19 on plain ints; extended twisted-Edwards coordinates
(X, Y, Z, T) with the RFC's a = -1 addition law (§5.1.4); point decoding as §5.1.3, rejecting
a non-canonical y (y >= p) and x = 0 with x_0 = 1; cofactorless ``[S]B = R + [k]A`` with
``S < L``. OpenSSH accepts S + L; this module does not, which is why an entry's ``sig`` is
immutable (spec §1). Pinned by the §7.1 vectors and the mutations in tests/test_biolean_ed25519.py.
Any change here needs review against §5.1.3 and §5.1.7 (spec, Risks).
"""
from __future__ import annotations

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)          # sqrt(-1) mod p

_Point = tuple[int, int, int, int]          # (X, Y, Z, T): x = X/Z, y = Y/Z, x*y = T/Z
_IDENTITY: _Point = (0, 1, 1, 0)


def _decode_point(encoded: bytes) -> _Point | None:
    """§5.1.3. ``None`` for a non-canonical or off-curve encoding."""
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, "little")
    x_0 = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        return None
    y2 = y * y % P
    u = (y2 - 1) % P
    v = (D * y2 + 1) % P
    x = pow(u * pow(v, P - 2, P), (P + 3) // 8, P)
    vx2 = v * x * x % P
    if vx2 == u:
        pass
    elif vx2 == (-u) % P:
        x = x * _SQRT_M1 % P
    else:
        return None
    if x == 0 and x_0 == 1:
        return None
    if (x & 1) != x_0:
        x = P - x
    return (x, y, 1, x * y % P)


def _add(p: _Point, q: _Point) -> _Point:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(k: int, p: _Point) -> _Point:
    q = _IDENTITY
    while k:
        if k & 1:
            q = _add(q, p)
        p = _add(p, p)
        k >>= 1
    return q


def _equal(p: _Point, q: _Point) -> bool:
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


_B_Y = 4 * pow(5, P - 2, P) % P
_B = _decode_point(_B_Y.to_bytes(32, "little"))     # sign bit clear: B has even x
if _B is None:
    raise RuntimeError("ed25519 base point failed to decode")


def is_small_order(public_key: bytes) -> bool:
    """``True`` when the encoding does not decode, or decodes to A with [8]A = identity.

    Under such a key, cofactorless verification accepts R = identity, S = 0 for every message
    (and OpenSSH accepts it too), so ``allowed_signers`` refuses it at parse (spec §4).
    """
    a = _decode_point(public_key)
    if a is None:
        return True
    return _equal(_mul(8, a), _IDENTITY)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7 with S < L and canonical encodings required. Never raises on bad input."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode_point(public_key)
    r = _decode_point(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % L
    return _equal(_mul(s, _B), _add(r, _mul(k, a)))
