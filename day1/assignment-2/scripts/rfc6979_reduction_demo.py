#!/usr/bin/env python3
"""Show why RFC 6979 feeds bits2octets(H(m)), not an arbitrary raw msg32."""

from __future__ import annotations

import hashlib
import hmac


N_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def rfc6979_nonce(private_key: int, digest32: bytes, reduce_digest: bool) -> int:
    """Generate the first RFC 6979 secp256k1 candidate.

    reduce_digest=False models the pre-fix libsecp256k1 behavior for crafted
    32-byte API inputs. reduce_digest=True applies RFC 6979 bits2octets.
    """
    x = private_key.to_bytes(32, "big")
    digest_int = int.from_bytes(digest32, "big")
    h1 = ((digest_int % N_ORDER) if reduce_digest else digest_int).to_bytes(32, "big")

    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac_sha256(k, v + b"\x00" + x + h1)
    v = hmac_sha256(k, v)
    k = hmac_sha256(k, v + b"\x01" + x + h1)
    v = hmac_sha256(k, v)

    while True:
        v = hmac_sha256(k, v)
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N_ORDER:
            return candidate
        k = hmac_sha256(k, v + b"\x00")
        v = hmac_sha256(k, v)


def main() -> None:
    private_key = 1
    crafted = (N_ORDER + 1).to_bytes(32, "big")
    canonical = (1).to_bytes(32, "big")

    old_crafted = rfc6979_nonce(private_key, crafted, reduce_digest=False)
    fixed_crafted = rfc6979_nonce(private_key, crafted, reduce_digest=True)
    fixed_canonical = rfc6979_nonce(private_key, canonical, reduce_digest=True)
    assert fixed_crafted == fixed_canonical
    assert old_crafted != fixed_crafted

    print("RFC 6979 bits2octets demonstration")
    print(f"crafted API value       = n + 1")
    print(f"bits2octets(n + 1)      = 1")
    print(f"old raw-input nonce     = {old_crafted:064x}")
    print(f"fixed reduced nonce     = {fixed_crafted:064x}")
    print(f"canonical input nonce   = {fixed_canonical:064x}")
    print(f"fixed(n + 1) == fixed(1): {fixed_crafted == fixed_canonical}")
    print(f"old(n + 1) != fixed(n + 1): {old_crafted != fixed_crafted}")
    print()
    print("This is the behavior corrected by commit 45f37b650635e46865104f37baed26ef8d2cfb97.")


if __name__ == "__main__":
    main()
