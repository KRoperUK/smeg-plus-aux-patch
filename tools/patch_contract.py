#!/usr/bin/env python3
"""Re-encrypt `contract.dat` so the unit will accept a modified package.

## Background

The head unit validates the update media before copying anything. Losing that check
produces *"The update file is protected and cannot be copied."* (string 2099), which is
what happens if you patch `AppBin/f_BigQuick.bin` and flash the result.

`contract.dat` is a table of per-file checks, encrypted in 256-byte RSA blocks.
`C_BCM_UPGRADE::CheckTrustedSource()` decrypts it on the unit and compares:

| CheckType | field @64 | field @68 | field @72 |
|---|---|---|---|
| 1 | `0xfffefffe` | `0xfffefffe` | file **size** (u32 BE) |
| 2 | `0xfffefffe` | `0xfffefffe` | file **crc32** (u32 BE) |
| 3 | **length** | **offset** | **raw bytes** read from the file |

Each record is 212 bytes: a NUL-padded path in `[0..62]`, the CheckType in `[63]`, then
those fields. Block 0 is a 152-byte header (`19/09/2017`, manifest version, magic
`deadbeef`/`badef00d`).

The unit *decrypts* with a private key, so the file was *encrypted with the public key*.
RSA public encryption is something anyone with the public key can do — and the key pair
is embedded in the firmware image itself. So a modified package can be re-sealed by
recomputing the checks from the files on disk and re-encrypting.

## Key handling

This tool does **not** ship any key material. It extracts the key pair from the
`f_BigQuick.bin` of the package you point it at — i.e. from the firmware you already own —
and uses it for that package only. The plaintext contract and the key are never written
anywhere.

## Usage

    # after patch_smeg.py / patch_media.py have written the changed files into --out
    python3 tools/patch_contract.py --package SMEG_PLUS_UPG_mod --out SMEG_PLUS_UPG_mod

If the package root is also the output (changes applied in place on a *copy* of the
package), one path is enough. The regenerated `contract.dat` is written to `--out`.

    python3 tools/patch_contract.py --package SMEG_PLUS_UPG_mod --show

prints what it would change without writing.
"""

import argparse
import hashlib
import os
import re
import struct
import sys
import zlib

BLOCK = 256
RECORD_SIZE = 212
HEADER_MSG = b"19/09/2017"
MAGIC = bytes.fromhex("deadbeefbadef00d")
UNUSED = 0xFFFEFFFE
DEFAULT_E = 65537  # universal RSA public exponent; verified against this firmware


# --------------------------------------------------------------------- OAEP


def mgf1(seed, length, hlen=20):
    out, counter = b"", 0
    while len(out) < length:
        out += hashlib.sha1(seed + counter.to_bytes(4, "big"), usedforsecurity=False).digest()
        counter += 1
    return out[:length]


def oaep_decrypt(em, hlen=20):
    """Strip RSA-OAEP (SHA-1) padding. Raises ValueError if malformed."""
    if len(em) < 2 * hlen + 2 or em[0] != 0:
        raise ValueError("not an OAEP block")
    masked_seed, masked_db = em[1 : 1 + hlen], em[1 + hlen :]
    seed = bytes(a ^ b for a, b in zip(masked_seed, mgf1(masked_db, hlen)))
    db = bytes(a ^ b for a, b in zip(masked_db, mgf1(seed, len(masked_db))))
    h = hashlib.sha1(b"", usedforsecurity=False).digest()
    if db[:hlen] != h:
        raise ValueError("OAEP label hash mismatch")
    i = hlen
    while i < len(db) and db[i] == 0:
        i += 1
    if i >= len(db) or db[i] != 1:
        raise ValueError("OAEP separator not found")
    return db[i + 1 :]


def oaep_encrypt(msg, k=BLOCK, hlen=20, seed=None):
    """Apply RSA-OAEP (SHA-1) padding."""
    if len(msg) > k - 2 * hlen - 2:
        raise ValueError("message too long for OAEP")
    db = (
        hashlib.sha1(b"", usedforsecurity=False).digest()
        + b"\x00" * (k - len(msg) - 2 * hlen - 2)
        + b"\x01"
        + msg
    )
    seed = seed or os.urandom(hlen)
    masked_db = bytes(a ^ b for a, b in zip(db, mgf1(seed, k - hlen - 1)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, mgf1(masked_db, hlen)))
    return b"\x00" + masked_seed + masked_db


# ------------------------------------------------------------------ key hunt


def inflate(path):
    raw = open(path, "rb").read()
    for start in (0x801, 0x800):
        try:
            d = zlib.decompressobj()
            out = d.decompress(raw[start:])
            out += d.flush()
        except zlib.error:
            continue
        if len(out) > 0x100000:
            return out
    raise SystemExit("could not inflate %s" % path)


def find_keys(app_image):
    """Recover the RSA key pair(s) embedded in an application image.

    The material is stored as plain decimal literals: two 2048-bit values per key
    (modulus and private exponent) and two 1024-bit values (the primes). A pair is
    accepted when `n == p*q`, and the private exponent is the co-located 2048-bit
    literal satisfying `d*e == 1 mod lambda(n)` — that check is what distinguishes a
    real key from a coincidental product.
    """
    import math

    lits = {}
    for m in re.finditer(rb"(?<!\d)\d{100,}(?!\d)", app_image):
        v = int(m.group())
        lits.setdefault(v.bit_length(), []).append(v)
    allv = [v for vs in lits.values() for v in vs]
    # classify by magnitude, not exact bit length: private exponents can be a few bits
    # short of the modulus (e.g. 2045 vs 2048), which exact grouping would miss.
    big = [v for v in allv if v.bit_length() > 1500]
    small = [v for v in allv if 900 < v.bit_length() < 1500]
    keys = []
    for p in small:
        for q in small:
            if p == q:
                continue
            n = p * q
            if n not in big:
                continue
            lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
            for d in big:
                if d != n and (d * DEFAULT_E) % lam == 1:
                    keys.append({"n": n, "d": d, "p": p, "q": q, "e": DEFAULT_E})
    if not keys:
        raise SystemExit("no RSA key pair found in the application image")
    return keys


def decrypt_block(ct, key):
    m = pow(int.from_bytes(ct, "big"), key["d"], key["n"])
    return oaep_decrypt(m.to_bytes(BLOCK, "big"))


def encrypt_block(pt, key):
    em = oaep_encrypt(pt, BLOCK)
    return pow(int.from_bytes(em, "big"), key["e"], key["n"]).to_bytes(BLOCK, "big")


# ------------------------------------------------------------------ contract


def load_contract(path, keys):
    """Decrypt the contract, trying each candidate key. Returns (header, records, key)."""
    raw = open(path, "rb").read()
    if len(raw) % BLOCK:
        raise SystemExit("contract.dat is not a multiple of %d bytes" % BLOCK)
    errors = []
    for key in keys:
        try:
            blocks = [decrypt_block(raw[i : i + BLOCK], key) for i in range(0, len(raw), BLOCK)]
        except ValueError as e:
            errors.append(str(e))
            continue
        if blocks[0].startswith(HEADER_MSG) and MAGIC in blocks[0]:
            return blocks[0], blocks[1:], key
        errors.append("header mismatch")
    raise SystemExit("no candidate key decrypted the contract (%s)" % "; ".join(errors))


def check_of(rec, data):
    """Recompute a record's payload from the file content, keeping its CheckType."""
    ctype = rec[63]
    if ctype == 1:
        return struct.pack(">I", len(data)), "size"
    if ctype == 2:
        return struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF), "crc32"
    if ctype == 3:
        length, offset = struct.unpack_from(">II", rec, 64)
        return data[offset : offset + length], "spot %d@%d" % (length, offset)
    raise SystemExit("unknown CheckType %d" % ctype)


def rebuild_record(rec, new_payload):
    out = bytearray(rec)
    ctype = rec[63]
    if ctype == 3:
        out[72:212] = bytes(new_payload) + bytes(212 - 72 - len(new_payload))
    else:
        out[72:76] = new_payload
    return bytes(out)


def resolve(package, rec_path):
    """Map a contract path ('/SMEG_PLUS_UPG/NAV/...') onto the package directory."""
    rel = rec_path.lstrip("/")
    if rel.startswith("SMEG_PLUS_UPG/"):
        rel = rel[len("SMEG_PLUS_UPG/") :]
    return os.path.join(package, rel)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--package",
        required=True,
        help="package directory holding contract.dat and the module images",
    )
    ap.add_argument(
        "--module",
        default="NAV",
        help="module whose app image carries the key material (default NAV)",
    )
    ap.add_argument("--out", help="where to write the new contract.dat (default: --package)")
    ap.add_argument("--show", action="store_true", help="report changes without writing")
    args = ap.parse_args()

    out_dir = args.out or args.package
    app = os.path.join(args.package, args.module, "AppBin", "f_BigQuick.bin")
    if not os.path.exists(app):
        sys.exit("no application image at %s" % app)

    keys = find_keys(inflate(app))
    print("found %d candidate key pair(s) in %s" % (len(keys), app))

    contract = os.path.join(args.package, "contract.dat")
    header, recs, key = load_contract(contract, keys)
    print("key recovered (n = %d bits); contract decrypted" % key["n"].bit_length())
    print("contract: %d records" % len(recs))

    changed, missing, kept = 0, 0, 0
    new_recs = []
    for rec in recs:
        path = rec[: rec.index(b"\0")].decode()
        fp = resolve(args.package, path)
        if not os.path.exists(fp):
            missing += 1
            new_recs.append(rec)
            continue
        payload, how = check_of(rec, open(fp, "rb").read())
        updated = rebuild_record(rec, payload)
        if updated != rec:
            changed += 1
            old = rec[72:76].hex() if rec[63] != 3 else "(bytes)"
            new = updated[72:76].hex() if rec[63] != 3 else "(bytes)"
            print(
                "  %-46s type %d  %-12s %s -> %s"
                % (path.replace("/SMEG_PLUS_UPG/", ""), rec[63], how, old, new)
            )
        else:
            kept += 1
        new_recs.append(updated)

    if not changed:
        print("nothing to update — contract already matches the files")

    if args.show:
        print("(dry run: %d changed, %d unchanged, %d missing)" % (changed, kept, missing))
        return

    blob = encrypt_block(header, key) + b"".join(encrypt_block(r, key) for r in new_recs)
    dest = os.path.join(out_dir, "contract.dat")
    os.makedirs(out_dir, exist_ok=True)
    open(dest, "w+b").write(blob)
    print("wrote %s (%d bytes, %d records updated)" % (dest, len(blob), changed))

    # verify by decrypting what we just wrote
    _, check, _ = load_contract(dest, [key])
    for rec, c in zip(new_recs, check):
        fp = resolve(args.package, c[: c.index(b"\0")].decode())
        if os.path.exists(fp):
            with open(fp, "rb") as fh:
                payload, _ = check_of(c, fh.read())
            # not an assert: this is the check that the re-sealed contract matches the
            # files, and `python -O` would remove it silently
            if rebuild_record(c, payload) != c:
                sys.exit(
                    "verification failed for %s — the contract does not match the "
                    "file on disk; do not flash this package" % fp
                )
    print("verified: the new contract decrypts cleanly and matches the files")


if __name__ == "__main__":
    main()
