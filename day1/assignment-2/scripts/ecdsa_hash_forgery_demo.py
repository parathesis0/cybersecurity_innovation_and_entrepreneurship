#!/usr/bin/env python3
"""Demonstrate ECDSA existential forgery when a verifier accepts a supplied hash.

This is an educational, dependency-free implementation over the real secp256k1
curve.  It does not recover a private key and it does not forge a signature for
an attacker-chosen ordinary message.  Instead, it constructs (e, r, s) together,
exactly as described on the course slide.
"""

from __future__ import annotations

import hashlib
from typing import Optional, Tuple


P_FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

# A valid public key chosen before the forging experiment. Its discrete log is
# neither stored nor used by this program.
PUBLIC_KEY = (
    0x597489820C95C852D0ADEC5CFF2628BABA879201FB72CAB0AE379F89009892ED,
    0x595C92E5D9F34F46BB8E58CF3AD855C4791FFBF392A77FA789CFA2BE2FE808E0,
)

Point = Optional[Tuple[int, int]]


def inverse(value: int, modulus: int) -> int:
    """Return value^(-1) modulo modulus."""
    return pow(value % modulus, -1, modulus)


def point_add(left: Point, right: Point) -> Point:
    """Add two affine points on y^2 = x^3 + 7 over F_p."""
    if left is None:
        return right
    if right is None:
        return left

    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % P_FIELD == 0:
        return None

    if left == right:
        slope = (3 * x1 * x1) * inverse(2 * y1, P_FIELD) % P_FIELD
    else:
        slope = (y2 - y1) * inverse(x2 - x1, P_FIELD) % P_FIELD

    x3 = (slope * slope - x1 - x2) % P_FIELD
    y3 = (slope * (x1 - x3) - y1) % P_FIELD
    return x3, y3


def scalar_mul(scalar: int, point: Point) -> Point:
    """Multiply a point with the double-and-add algorithm."""
    result: Point = None
    addend = point
    scalar %= N_ORDER
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def verify_hash(public_key: Point, e: int, r: int, s: int) -> bool:
    """Verify an ECDSA signature against an already supplied integer hash e."""
    if public_key is None or not (1 <= r < N_ORDER and 1 <= s < N_ORDER):
        return False
    w = inverse(s, N_ORDER)
    check_point = point_add(
        scalar_mul((e * w) % N_ORDER, G),
        scalar_mul((r * w) % N_ORDER, public_key),
    )
    return check_point is not None and check_point[0] % N_ORDER == r


def labeled_scalar(label: bytes) -> int:
    value = int.from_bytes(hashlib.sha256(label).digest(), "big") % N_ORDER
    return value or 1


def short_hex(value: int) -> str:
    text = f"{value:064x}"
    return f"{text[:16]}...{text[-16:]}"


def main() -> None:
    public_key = PUBLIC_KEY
    assert (public_key[1] * public_key[1] - public_key[0] ** 3 - 7) % P_FIELD == 0

    # Attacker-selected non-zero u and v.
    u = labeled_scalar(b"assignment-2-u")
    v = labeled_scalar(b"assignment-2-v")

    # R' = uG + vP, r' = x(R') mod n.
    forged_point = point_add(scalar_mul(u, G), scalar_mul(v, public_key))
    assert forged_point is not None
    r = forged_point[0] % N_ORDER
    if r == 0:
        raise RuntimeError("Cryptographically negligible r=0 case; choose new labels")

    # e' = r' u v^(-1) and s' = r' v^(-1), all modulo n.
    v_inverse = inverse(v, N_ORDER)
    e = (r * u * v_inverse) % N_ORDER
    s = (r * v_inverse) % N_ORDER

    # libsecp256k1 accepts only lower-S ECDSA signatures.  If s is high, n-s
    # verifies too: verification obtains -R', whose x-coordinate is unchanged.
    if s > N_ORDER // 2:
        s = N_ORDER - s

    chosen_message = b"I authorize this Bitcoin transaction"
    chosen_message_hash = int.from_bytes(hashlib.sha256(chosen_message).digest(), "big") % N_ORDER
    is_valid = verify_hash(public_key, e, r, s)
    assert is_valid
    assert chosen_message_hash != e

    print("ECDSA chosen-hash forgery demo on the real secp256k1 curve")
    print(f"public key x = {short_hex(public_key[0])}")
    print(f"public key y = {short_hex(public_key[1])}")
    print(f"attacker u    = {short_hex(u)}")
    print(f"attacker v    = {short_hex(v)}")
    print(f"forged e      = {e:064x}")
    print(f"forged r      = {r:064x}")
    print(f"forged s      = {s:064x} (lower-S)")
    print(f"verify(P, e, r, s) = {is_valid}")
    print()
    print(f"SHA256(chosen message) mod n = {chosen_message_hash:064x}")
    print(f"Does it equal forged e?       {chosen_message_hash == e}")
    print()
    print("Conclusion: the tuple is valid only for the algebraically chosen hash e.")
    print("A correct application computes the transaction/message hash itself, so an")
    print("attacker must additionally solve a 256-bit hash preimage problem.")


if __name__ == "__main__":
    main()
