#!/usr/bin/env python3
"""Parse and verify the Assignment 1 Testnet4 transaction and its block.

The script has no third-party dependencies.  It performs byte-accurate parsing,
calculates txid/wtxid, decodes common output scripts, verifies this transaction's
BIP143 ECDSA signature, and validates the containing block's proof of work,
transaction Merkle root, and SegWit witness commitment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (GX, GY)
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def dsha256(data: bytes) -> bytes:
    return sha256(sha256(data))


def hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", sha256(data)).digest()


def ser_compact_size(value: int) -> bytes:
    if value < 0xFD:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    if value <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", value)
    return b"\xff" + struct.pack("<Q", value)


def bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i, generator in enumerate(generators):
            if (top >> i) & 1:
                chk ^= generator
    return chk


def bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def convertbits(data: bytes, from_bits: int, to_bits: int, pad: bool = True) -> list[int]:
    acc = 0
    bits = 0
    result: list[int] = []
    maxv = (1 << to_bits) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise ValueError("invalid convertbits input")
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            result.append((acc >> bits) & maxv)
    if pad and bits:
        result.append((acc << (to_bits - bits)) & maxv)
    elif not pad and (bits >= from_bits or ((acc << (to_bits - bits)) & maxv)):
        raise ValueError("invalid convertbits padding")
    return result


def segwit_address(program: bytes, version: int = 0, hrp: str = "tb") -> str:
    data = [version] + convertbits(program, 8, 5)
    constant = 1 if version == 0 else 0x2BC830A3
    polymod = bech32_polymod(bech32_hrp_expand(hrp) + data + [0] * 6) ^ constant
    checksum = [(polymod >> (5 * (5 - i))) & 31 for i in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[d] for d in data + checksum)


def decode_script(script: bytes, hrp: str = "tb") -> str:
    if len(script) in (22, 34) and script[0] == 0 and script[1] == len(script) - 2:
        kind = "P2WPKH" if len(script) == 22 else "P2WSH"
        return f"{kind}, {segwit_address(script[2:], 0, hrp)}"
    if len(script) == 34 and script[0] == 0x51 and script[1] == 0x20:
        return f"P2TR, {segwit_address(script[2:], 1, hrp)}"
    if len(script) == 25 and script[:3] == b"\x76\xa9\x14" and script[-2:] == b"\x88\xac":
        return f"P2PKH, pubKeyHash={script[3:23].hex()}"
    if len(script) == 23 and script[:2] == b"\xa9\x14" and script[-1:] == b"\x87":
        return f"P2SH, scriptHash={script[2:22].hex()}"
    if script[:1] == b"\x6a":
        return "OP_RETURN (provably unspendable data)"
    return "non-standard or unclassified script"


@dataclass
class Field:
    offset: int
    length: int
    path: str
    raw: bytes
    decoded: str


class Reader:
    def __init__(self, data: bytes, base_offset: int = 0):
        self.data = data
        self.offset = 0
        self.base_offset = base_offset
        self.fields: list[Field] = []

    def take(self, length: int, path: str, decoded: str = "") -> bytes:
        if length < 0 or self.offset + length > len(self.data):
            raise ValueError(f"truncated data while reading {path}")
        start = self.offset
        raw = self.data[start : start + length]
        self.offset += length
        self.fields.append(Field(self.base_offset + start, length, path, raw, decoded))
        return raw

    def compact(self, path: str) -> tuple[int, bytes]:
        start = self.offset
        prefix = self.data[self.offset]
        if prefix < 0xFD:
            raw = self.take(1, path, str(prefix))
            return prefix, raw
        widths = {0xFD: 2, 0xFE: 4, 0xFF: 8}
        width = widths[prefix]
        raw = self.data[self.offset : self.offset + 1 + width]
        value = int.from_bytes(raw[1:], "little")
        self.offset += 1 + width
        self.fields.append(Field(self.base_offset + start, 1 + width, path, raw, str(value)))
        return value, raw


def parse_tx(reader: Reader, label: str = "tx") -> dict[str, Any]:
    start = reader.offset
    field_start = len(reader.fields)
    version_raw = reader.take(4, f"{label}.version")
    version = int.from_bytes(version_raw, "little", signed=True)
    reader.fields[-1].decoded = f"{version} (32-bit little-endian)"

    segwit = reader.offset + 1 < len(reader.data) and reader.data[reader.offset] == 0 and reader.data[reader.offset + 1] != 0
    marker = flag = b""
    if segwit:
        marker = reader.take(1, f"{label}.marker", "0x00: extended/SegWit serialization marker")
        flag = reader.take(1, f"{label}.flag", "0x01: witness data present")

    input_count, input_count_raw = reader.compact(f"{label}.input_count")
    inputs: list[dict[str, Any]] = []
    stripped_inputs = bytearray()
    for i in range(input_count):
        prefix = f"{label}.vin[{i}]"
        prev_raw = reader.take(32, f"{prefix}.prev_txid")
        reader.fields[-1].decoded = prev_raw[::-1].hex() + " (display order)"
        vout_raw = reader.take(4, f"{prefix}.prev_vout")
        vout = int.from_bytes(vout_raw, "little")
        reader.fields[-1].decoded = str(vout)
        script_len, script_len_raw = reader.compact(f"{prefix}.scriptSig_length")
        script = reader.take(script_len, f"{prefix}.scriptSig", "empty" if not script_len else "legacy unlocking script")
        sequence_raw = reader.take(4, f"{prefix}.sequence")
        sequence = int.from_bytes(sequence_raw, "little")
        rbf = sequence <= 0xFFFFFFFD
        bip68_disabled = bool(sequence & (1 << 31))
        reader.fields[-1].decoded = (
            f"0x{sequence:08x}; BIP125 RBF={'yes' if rbf else 'no'}; "
            f"BIP68 relative lock disabled={'yes' if bip68_disabled else 'no'}"
        )
        stripped_inputs += prev_raw + vout_raw + script_len_raw + script + sequence_raw
        inputs.append(
            {
                "prev_raw": prev_raw,
                "prev_txid": prev_raw[::-1].hex(),
                "vout": vout,
                "vout_raw": vout_raw,
                "script": script,
                "script_len_raw": script_len_raw,
                "sequence": sequence,
                "sequence_raw": sequence_raw,
            }
        )

    output_count, output_count_raw = reader.compact(f"{label}.output_count")
    outputs: list[dict[str, Any]] = []
    stripped_outputs = bytearray()
    for i in range(output_count):
        prefix = f"{label}.vout[{i}]"
        value_raw = reader.take(8, f"{prefix}.value")
        value = int.from_bytes(value_raw, "little")
        reader.fields[-1].decoded = f"{value:,} sat = {value / 100_000_000:.8f} BTC"
        script_len, script_len_raw = reader.compact(f"{prefix}.scriptPubKey_length")
        script = reader.take(script_len, f"{prefix}.scriptPubKey")
        reader.fields[-1].decoded = decode_script(script)
        stripped_outputs += value_raw + script_len_raw + script
        outputs.append({"value": value, "value_raw": value_raw, "script": script, "script_len_raw": script_len_raw})

    witnesses: list[list[bytes]] = []
    if segwit:
        for i in range(input_count):
            item_count, _ = reader.compact(f"{label}.vin[{i}].witness.item_count")
            items: list[bytes] = []
            for j in range(item_count):
                item_len, _ = reader.compact(f"{label}.vin[{i}].witness[{j}].length")
                item = reader.take(item_len, f"{label}.vin[{i}].witness[{j}]")
                if j == 0 and item:
                    reader.fields[-1].decoded = "DER ECDSA signature followed by one-byte sighash type"
                elif j == 1 and len(item) == 33:
                    reader.fields[-1].decoded = f"compressed public key; prefix=0x{item[0]:02x}"
                items.append(item)
            witnesses.append(items)
    else:
        witnesses = [[] for _ in range(input_count)]

    locktime_raw = reader.take(4, f"{label}.locktime")
    locktime = int.from_bytes(locktime_raw, "little")
    lock_kind = "block height" if 0 < locktime < 500_000_000 else ("Unix timestamp" if locktime else "disabled")
    reader.fields[-1].decoded = f"{locktime} ({lock_kind})"

    end = reader.offset
    raw = reader.data[start:end]
    stripped = (
        version_raw
        + input_count_raw
        + bytes(stripped_inputs)
        + output_count_raw
        + bytes(stripped_outputs)
        + locktime_raw
    )
    txid = dsha256(stripped)[::-1].hex()
    wtxid = dsha256(raw)[::-1].hex()
    base_size = len(stripped)
    total_size = len(raw)
    witness_size = total_size - base_size
    weight = base_size * 4 + witness_size
    return {
        "label": label,
        "start": start,
        "end": end,
        "fields": reader.fields[field_start:],
        "version": version,
        "segwit": segwit,
        "marker": marker,
        "flag": flag,
        "inputs": inputs,
        "outputs": outputs,
        "witnesses": witnesses,
        "locktime": locktime,
        "locktime_raw": locktime_raw,
        "input_count_raw": input_count_raw,
        "output_count_raw": output_count_raw,
        "raw": raw,
        "stripped": stripped,
        "txid": txid,
        "wtxid": wtxid,
        "size": total_size,
        "base_size": base_size,
        "witness_size": witness_size,
        "weight": weight,
        "vsize": math.ceil(weight / 4),
        "exact_vsize": weight / 4,
    }


JacobianPoint = tuple[int, int, int]


def jacobian_double(point: JacobianPoint) -> JacobianPoint:
    x, y, z = point
    if z == 0 or y == 0:
        return 0, 1, 0
    yy = y * y % P
    yyyy = yy * yy % P
    s = 4 * x * yy % P
    m = 3 * x * x % P
    x3 = (m * m - 2 * s) % P
    y3 = (m * (s - x3) - 8 * yyyy) % P
    z3 = 2 * y * z % P
    return x3, y3, z3


def jacobian_add(a: JacobianPoint, b: JacobianPoint) -> JacobianPoint:
    x1, y1, z1 = a
    x2, y2, z2 = b
    if z1 == 0:
        return b
    if z2 == 0:
        return a
    z1z1 = z1 * z1 % P
    z2z2 = z2 * z2 % P
    u1 = x1 * z2z2 % P
    u2 = x2 * z1z1 % P
    s1 = y1 * z2 * z2z2 % P
    s2 = y2 * z1 * z1z1 % P
    if u1 == u2:
        return jacobian_double(a) if s1 == s2 else (0, 1, 0)
    h = (u2 - u1) % P
    r = (s2 - s1) % P
    hh = h * h % P
    hhh = h * hh % P
    u1hh = u1 * hh % P
    x3 = (r * r - hhh - 2 * u1hh) % P
    y3 = (r * (u1hh - x3) - s1 * hhh) % P
    z3 = h * z1 * z2 % P
    return x3, y3, z3


def scalar_mul_jacobian(k: int, point: tuple[int, int]) -> JacobianPoint:
    result: JacobianPoint = (0, 1, 0)
    addend: JacobianPoint = (point[0], point[1], 1)
    while k:
        if k & 1:
            result = jacobian_add(result, addend)
        addend = jacobian_double(addend)
        k >>= 1
    return result


def jacobian_to_affine(point: JacobianPoint) -> tuple[int, int] | None:
    x, y, z = point
    if z == 0:
        return None
    z_inv = pow(z, P - 2, P)
    z2 = z_inv * z_inv % P
    return x * z2 % P, y * z2 * z_inv % P


def decode_pubkey(pubkey: bytes) -> tuple[int, int]:
    if len(pubkey) != 33 or pubkey[0] not in (2, 3):
        raise ValueError("only compressed secp256k1 public keys are supported")
    x = int.from_bytes(pubkey[1:], "big")
    y = pow((pow(x, 3, P) + 7) % P, (P + 1) // 4, P)
    if (y & 1) != (pubkey[0] & 1):
        y = P - y
    return x, y


def parse_der_signature(der: bytes) -> tuple[int, int]:
    if len(der) < 8 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise ValueError("invalid DER sequence")
    pos = 2
    if der[pos] != 0x02:
        raise ValueError("invalid DER r tag")
    r_len = der[pos + 1]
    r_bytes = der[pos + 2 : pos + 2 + r_len]
    pos += 2 + r_len
    if pos + 2 > len(der) or der[pos] != 0x02:
        raise ValueError("invalid DER s tag")
    s_len = der[pos + 1]
    s_bytes = der[pos + 2 : pos + 2 + s_len]
    pos += 2 + s_len
    if pos != len(der):
        raise ValueError("trailing DER data")
    return int.from_bytes(r_bytes, "big"), int.from_bytes(s_bytes, "big")


def ecdsa_verify(digest: bytes, der: bytes, pubkey: bytes) -> tuple[bool, int, int]:
    r, s = parse_der_signature(der)
    if not (1 <= r < N and 1 <= s < N):
        return False, r, s
    z = int.from_bytes(digest, "big")
    w = pow(s, N - 2, N)
    point = jacobian_to_affine(
        jacobian_add(
            scalar_mul_jacobian(z * w % N, G),
            scalar_mul_jacobian(r * w % N, decode_pubkey(pubkey)),
        )
    )
    return point is not None and point[0] % N == r, r, s


def serialize_output(output: dict[str, Any]) -> bytes:
    return output["value_raw"] + output["script_len_raw"] + output["script"]


def verify_assignment_signature(tx: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    prev = metadata["input_prevout"]
    index = int(prev.get("input_index", 0))
    txin = tx["inputs"][index]
    witness = tx["witnesses"][index]
    if len(witness) != 2:
        raise ValueError("assignment input is not a two-item P2WPKH witness")
    signature_with_type, pubkey = witness
    sighash_type = signature_with_type[-1]
    der = signature_with_type[:-1]
    prev_script = bytes.fromhex(prev["script_pubkey"])
    if len(prev_script) != 22 or prev_script[:2] != b"\x00\x14":
        raise ValueError("metadata prevout is not P2WPKH")
    pubkey_hash = hash160(pubkey)
    script_code = b"\x76\xa9\x14" + prev_script[2:] + b"\x88\xac"
    hash_prevouts = dsha256(b"".join(i["prev_raw"] + i["vout_raw"] for i in tx["inputs"]))
    hash_sequence = dsha256(b"".join(i["sequence_raw"] for i in tx["inputs"]))
    hash_outputs = dsha256(b"".join(serialize_output(o) for o in tx["outputs"]))
    preimage = (
        struct.pack("<i", tx["version"])
        + hash_prevouts
        + hash_sequence
        + txin["prev_raw"]
        + txin["vout_raw"]
        + ser_compact_size(len(script_code))
        + script_code
        + struct.pack("<Q", int(prev["value_sats"]))
        + txin["sequence_raw"]
        + hash_outputs
        + tx["locktime_raw"]
        + struct.pack("<I", sighash_type)
    )
    digest = dsha256(preimage)
    valid, r, s = ecdsa_verify(digest, der, pubkey)
    return {
        "sighash_type": sighash_type,
        "script_code": script_code,
        "hash_prevouts": hash_prevouts,
        "hash_sequence": hash_sequence,
        "hash_outputs": hash_outputs,
        "preimage": preimage,
        "digest": digest,
        "r": r,
        "s": s,
        "low_s": s <= N // 2,
        "pubkey": pubkey,
        "pubkey_hash": pubkey_hash,
        "expected_pubkey_hash": prev_script[2:],
        "pubkey_hash_matches": pubkey_hash == prev_script[2:],
        "signature_valid": valid,
    }


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("Merkle tree needs at least one leaf")
    level = leaves[:]
    while len(level) > 1:
        if len(level) & 1:
            level.append(level[-1])
        level = [dsha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def compact_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    return mantissa << (8 * (exponent - 3)) if exponent >= 3 else mantissa >> (8 * (3 - exponent))


def parse_block(data: bytes) -> dict[str, Any]:
    reader = Reader(data)
    header_start = reader.offset
    version_raw = reader.take(4, "block.header.version")
    version = int.from_bytes(version_raw, "little", signed=True)
    reader.fields[-1].decoded = f"0x{version & 0xffffffff:08x}"
    prev_raw = reader.take(32, "block.header.previous_block_hash")
    reader.fields[-1].decoded = prev_raw[::-1].hex()
    merkle_raw = reader.take(32, "block.header.transaction_merkle_root")
    reader.fields[-1].decoded = merkle_raw[::-1].hex()
    time_raw = reader.take(4, "block.header.time")
    timestamp = int.from_bytes(time_raw, "little")
    reader.fields[-1].decoded = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    bits_raw = reader.take(4, "block.header.bits")
    bits = int.from_bytes(bits_raw, "little")
    target = compact_target(bits)
    reader.fields[-1].decoded = f"0x{bits:08x}; target=0x{target:064x}"
    nonce_raw = reader.take(4, "block.header.nonce")
    nonce = int.from_bytes(nonce_raw, "little")
    reader.fields[-1].decoded = str(nonce)
    header = data[header_start:reader.offset]
    block_hash = dsha256(header)[::-1].hex()

    tx_count, tx_count_raw = reader.compact("block.transaction_count")
    transactions = [parse_tx(reader, f"block.tx[{i}]") for i in range(tx_count)]
    if reader.offset != len(data):
        raise ValueError(f"{len(data) - reader.offset} unparsed block bytes remain")

    tx_merkle = merkle_root([bytes.fromhex(tx["txid"])[::-1] for tx in transactions])
    witness_leaves = [bytes(32)] + [bytes.fromhex(tx["wtxid"])[::-1] for tx in transactions[1:]]
    witness_merkle = merkle_root(witness_leaves)
    coinbase = transactions[0]
    reserved = coinbase["witnesses"][0][0] if coinbase["witnesses"] and coinbase["witnesses"][0] else b""
    calculated_commitment = dsha256(witness_merkle + reserved) if len(reserved) == 32 else b""
    commitments = [o["script"][6:38] for o in coinbase["outputs"] if len(o["script"]) >= 38 and o["script"][:6] == bytes.fromhex("6a24aa21a9ed")]
    stored_commitment = commitments[-1] if commitments else b""
    stripped_size = 80 + len(tx_count_raw) + sum(tx["base_size"] for tx in transactions)
    weight = stripped_size * 4 + (len(data) - stripped_size)
    hash_as_number = int(block_hash, 16)

    coinbase_height = None
    coinbase_script = coinbase["inputs"][0]["script"]
    if coinbase_script:
        push_len = coinbase_script[0]
        if 1 <= push_len <= 5 and len(coinbase_script) >= 1 + push_len:
            coinbase_height = int.from_bytes(coinbase_script[1 : 1 + push_len], "little")

    return {
        "reader": reader,
        "header": header,
        "version": version,
        "previous_block_hash": prev_raw[::-1].hex(),
        "stored_merkle_root": merkle_raw[::-1].hex(),
        "calculated_merkle_root": tx_merkle[::-1].hex(),
        "merkle_valid": tx_merkle == merkle_raw,
        "timestamp": timestamp,
        "bits": bits,
        "target": target,
        "nonce": nonce,
        "block_hash": block_hash,
        "pow_valid": hash_as_number <= target,
        "tx_count": tx_count,
        "transactions": transactions,
        "size": len(data),
        "stripped_size": stripped_size,
        "weight": weight,
        "vsize": math.ceil(weight / 4),
        "witness_merkle_root": witness_merkle[::-1].hex(),
        "witness_reserved_value": reserved.hex(),
        "stored_witness_commitment": stored_commitment.hex(),
        "calculated_witness_commitment": calculated_commitment.hex(),
        "witness_commitment_valid": bool(stored_commitment) and stored_commitment == calculated_commitment,
        "coinbase_height": coinbase_height,
    }


def coverage(fields: list[Field], total_length: int, base_offset: int = 0) -> tuple[bool, str]:
    cursor = base_offset
    for field in sorted(fields, key=lambda f: f.offset):
        if field.offset != cursor:
            return False, f"coverage discontinuity at {cursor}, next field starts at {field.offset}"
        cursor += field.length
    expected = base_offset + total_length
    if cursor != expected:
        return False, f"coverage ends at {cursor}, expected {expected}"
    return True, f"all {total_length} bytes covered exactly once"


def field_table(fields: list[Field]) -> str:
    lines = [
        "offset(dec/hex) | bytes | field | raw hex | decoded",
        "-" * 120,
    ]
    for field in fields:
        raw = field.raw.hex() if field.length else "<empty>"
        lines.append(
            f"{field.offset:5d}/0x{field.offset:04x} | {field.length:4d} | "
            f"{field.path} | {raw} | {field.decoded}"
        )
    return "\n".join(lines)


def tx_report(tx: dict[str, Any], metadata: dict[str, Any]) -> str:
    verification = verify_assignment_signature(tx, metadata)
    expected_txid = metadata.get("txid", "")
    expected_wtxid = metadata.get("wtxid", "")
    prev_value = int(metadata["input_prevout"]["value_sats"])
    output_value = sum(o["value"] for o in tx["outputs"])
    fee = prev_value - output_value
    lines = [
        "Assignment 1: Testnet4 transaction byte-level parse and verification",
        "=" * 78,
        f"txid                 : {tx['txid']}",
        f"txid matches metadata: {tx['txid'] == expected_txid}",
        f"wtxid                : {tx['wtxid']}",
        f"wtxid matches metadata: {tx['wtxid'] == expected_wtxid}",
        f"version / locktime    : {tx['version']} / {tx['locktime']}",
        f"size / base / witness : {tx['size']} / {tx['base_size']} / {tx['witness_size']} bytes",
        f"weight / vsize        : {tx['weight']} WU / {tx['vsize']} vB (exact {tx['exact_vsize']:.2f} vB)",
        f"input / output value  : {prev_value:,} / {output_value:,} sat",
        f"fee                   : {fee:,} sat",
        f"fee rate              : {fee / tx['exact_vsize']:.8f} sat/vB (exact-weight convention)",
        f"block                 : {metadata['block_height']} / {metadata['block_hash']}",
        "",
        "Inputs",
        "------",
    ]
    for i, txin in enumerate(tx["inputs"]):
        lines.append(
            f"vin[{i}]: {txin['prev_txid']}:{txin['vout']}, sequence=0x{txin['sequence']:08x}, "
            f"scriptSig={txin['script'].hex() or '<empty>'}"
        )
    lines += ["", "Outputs", "-------"]
    for i, output in enumerate(tx["outputs"]):
        lines.append(f"vout[{i}]: {output['value']:,} sat, {decode_script(output['script'])}, script={output['script'].hex()}")
    lines += [
        "",
        "P2WPKH / BIP143 verification",
        "----------------------------",
        f"sighash byte           : 0x{verification['sighash_type']:02x} (SIGHASH_ALL)",
        f"scriptCode             : {verification['script_code'].hex()}",
        f"hashPrevouts           : {verification['hash_prevouts'].hex()}",
        f"hashSequence           : {verification['hash_sequence'].hex()}",
        f"hashOutputs            : {verification['hash_outputs'].hex()}",
        f"BIP143 preimage        : {verification['preimage'].hex()}",
        f"double-SHA256 digest   : {verification['digest'].hex()}",
        f"public key             : {verification['pubkey'].hex()}",
        f"HASH160(public key)    : {verification['pubkey_hash'].hex()}",
        f"prevout witness program: {verification['expected_pubkey_hash'].hex()}",
        f"pubkey hash matches    : {verification['pubkey_hash_matches']}",
        f"ECDSA r                : {verification['r']:064x}",
        f"ECDSA s                : {verification['s']:064x}",
        f"low-S canonical        : {verification['low_s']}",
        f"ECDSA verifies         : {verification['signature_valid']}",
        "",
        "Byte coverage",
        "-------------",
        coverage(tx["fields"], tx["size"], tx["fields"][0].offset)[1],
        "",
        "Complete field map",
        "------------------",
        field_table(tx["fields"]),
        "",
    ]
    return "\n".join(lines)


def block_report(block: dict[str, Any], metadata: dict[str, Any]) -> str:
    lines = [
        "Assignment 1: complete Testnet4 block parse and cryptographic checks",
        "=" * 78,
        f"height (BIP34 coinbase): {block['coinbase_height']}",
        f"expected height         : {metadata['block_height']}",
        f"block hash              : {block['block_hash']}",
        f"expected block hash     : {metadata['block_hash']}",
        f"hash matches metadata   : {block['block_hash'] == metadata['block_hash']}",
        f"version                 : 0x{block['version'] & 0xffffffff:08x}",
        f"previous block          : {block['previous_block_hash']}",
        f"time                     : {datetime.fromtimestamp(block['timestamp'], timezone.utc).isoformat()}",
        f"bits / nonce             : 0x{block['bits']:08x} / {block['nonce']}",
        f"target                   : {block['target']:064x}",
        f"proof of work valid      : {block['pow_valid']}",
        f"transaction count        : {block['tx_count']}",
        f"size / stripped size     : {block['size']} / {block['stripped_size']} bytes",
        f"weight / vsize           : {block['weight']} WU / {block['vsize']} vB",
        f"stored Merkle root       : {block['stored_merkle_root']}",
        f"calculated Merkle root   : {block['calculated_merkle_root']}",
        f"transaction Merkle valid : {block['merkle_valid']}",
        f"witness Merkle root      : {block['witness_merkle_root']}",
        f"witness reserved value   : {block['witness_reserved_value']}",
        f"stored commitment        : {block['stored_witness_commitment']}",
        f"calculated commitment    : {block['calculated_witness_commitment']}",
        f"witness commitment valid : {block['witness_commitment_valid']}",
        "",
        "Transaction index",
        "-----------------",
        "index | txid | wtxid | size | weight | vsize | inputs | outputs",
    ]
    for i, tx in enumerate(block["transactions"]):
        lines.append(
            f"{i:5d} | {tx['txid']} | {tx['wtxid']} | {tx['size']:4d} | {tx['weight']:5d} | "
            f"{tx['vsize']:4d} | {len(tx['inputs']):2d} | {len(tx['outputs']):2d}"
        )
    assignment_index = [i for i, tx in enumerate(block["transactions"]) if tx["txid"] == metadata["txid"]]
    lines += [
        "",
        f"Assignment transaction index: {assignment_index}",
        "",
        "Byte coverage",
        "-------------",
        coverage(block["reader"].fields, block["size"])[1],
        "",
        "Complete block field map (header, transaction count, and every transaction field)",
        "-------------------------------------------------------------------------------",
        field_table(block["reader"].fields),
        "",
    ]
    return "\n".join(lines)


def read_hex_file(path: Path) -> bytes:
    return bytes.fromhex("".join(path.read_text(encoding="utf-8").split()))


def main() -> None:
    here = Path(__file__).resolve().parent
    assignment = here.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx", type=Path, default=assignment / "tx.txt")
    parser.add_argument("--metadata", type=Path, default=assignment / "evidence" / "metadata.json")
    parser.add_argument("--block-hex", type=Path, default=assignment / "evidence" / "block-144878.hex")
    parser.add_argument("--tx-report", type=Path, default=assignment / "evidence" / "tx_parse.txt")
    parser.add_argument("--block-report", type=Path, default=assignment / "evidence" / "block_parse.txt")
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    tx_data = read_hex_file(args.tx)
    tx_reader = Reader(tx_data)
    tx = parse_tx(tx_reader, "tx")
    if tx_reader.offset != len(tx_data):
        raise ValueError("standalone transaction has trailing data")

    block = parse_block(read_hex_file(args.block_hex))
    args.tx_report.write_text(tx_report(tx, metadata), encoding="utf-8")
    args.block_report.write_text(block_report(block, metadata), encoding="utf-8")

    checks = {
        "txid": tx["txid"] == metadata["txid"],
        "wtxid": tx["wtxid"] == metadata["wtxid"],
        "signature": verify_assignment_signature(tx, metadata)["signature_valid"],
        "block_hash": block["block_hash"] == metadata["block_hash"],
        "height": block["coinbase_height"] == metadata["block_height"],
        "proof_of_work": block["pow_valid"],
        "tx_merkle": block["merkle_valid"],
        "witness_commitment": block["witness_commitment_valid"],
        "tx_in_block": any(item["txid"] == tx["txid"] for item in block["transactions"]),
        "tx_byte_coverage": coverage(tx["fields"], tx["size"], tx["fields"][0].offset)[0],
        "block_byte_coverage": coverage(block["reader"].fields, block["size"])[0],
    }
    for name, ok in checks.items():
        print(f"{name:20s}: {'PASS' if ok else 'FAIL'}")
    if not all(checks.values()):
        raise SystemExit(1)
    print(f"wrote {args.tx_report}")
    print(f"wrote {args.block_report}")


if __name__ == "__main__":
    main()
