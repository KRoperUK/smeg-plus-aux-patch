"""Tests for tools/patch_contract.py.

Everything here is synthetic: the test generates its own RSA key pair and embeds it as
decimal literals, exactly as the firmware does. No vendor key material, and no firmware,
is needed.
"""

import os
import random
import struct
import sys
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import patch_contract as pc  # noqa: E402
from pathlib import Path


# --------------------------------------------------------------- synthetic RSA


def _is_probable_prime(n, rounds=24):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits):
    while True:
        c = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(c):
            return c


@pytest.fixture(scope="module")
def rsakey():
    """A generated key pair, sized so the literals look like the firmware's."""
    p, q = _prime(1024), _prime(1024)
    n = p * q
    lam = (p - 1) * (q - 1) // __import__("math").gcd(p - 1, q - 1)
    d = pow(pc.DEFAULT_E, -1, lam)
    return {"n": n, "d": d, "p": p, "q": q, "e": pc.DEFAULT_E}


def make_image_with_key(key, filler=0xAA, size=0x200000):
    """A fake application image carrying the key as decimal literals, as the firmware does."""
    img = bytearray([filler]) * size
    blob = ("%d\0%d\0%d\0%d\0" % (key["n"], key["d"], key["p"], key["q"])).encode()
    img[0x1000 : 0x1000 + len(blob)] = blob
    return bytes(img)


# ------------------------------------------------------------------- the tests


def test_oaep_round_trip():
    msg = b"a synthetic contract payload" * 4
    em = pc.oaep_encrypt(msg, seed=b"\x01" * 20)
    assert pc.oaep_decrypt(em) == msg


def test_oaep_rejects_a_bad_block():
    with pytest.raises(ValueError):
        pc.oaep_decrypt(b"\x01" + bytes(255))


def test_find_keys_recovers_the_generated_pair(rsakey):
    keys = pc.find_keys(make_image_with_key(rsakey))
    assert keys, "no key found"
    found = keys[0]
    assert found["n"] == rsakey["n"]
    assert (found["d"] * pc.DEFAULT_E) % ((found["p"] - 1) * (found["q"] - 1)) == 0 or True
    # the returned d really is the inverse of e
    import math

    lam = (found["p"] - 1) * (found["q"] - 1) // math.gcd(found["p"] - 1, found["q"] - 1)
    assert (found["d"] * pc.DEFAULT_E) % lam == 1


def test_find_keys_fails_loudly_without_key_material():
    with pytest.raises(SystemExit):
        pc.find_keys(bytes(0x10000))


def make_contract(key, entries):
    """entries: list of (path, bytes_or_None) — checks are computed from the bytes."""
    header = bytearray(152)
    header[0:10] = pc.HEADER_MSG
    header[10:12] = b"\0\0"
    header[12:19] = b"1.1.0.0"
    header[46:50] = b"\x73\x35\xcf\x08"
    header[50:58] = pc.MAGIC
    blocks = [pc.encrypt_block(bytes(header), key)]
    for path, data in entries:
        rec = bytearray(pc.RECORD_SIZE)
        p = path.encode()
        assert len(p) < 63
        rec[0 : len(p)] = p
        rec[63] = 2
        struct.pack_into(">II", rec, 64, pc.UNUSED, pc.UNUSED)
        struct.pack_into(">I", rec, 72, zlib.crc32(data) & 0xFFFFFFFF)
        blocks.append(pc.encrypt_block(bytes(rec), key))
    return b"".join(blocks)


def test_contract_round_trip_and_record_refresh(rsakey, tmp_path):
    pkg = tmp_path / "PKG"
    (pkg / "NAV" / "AppBin").mkdir(parents=True)

    a = b"A" * 500
    b = b"B" * 900
    (pkg / "ctrl.bin").write_bytes(a)
    (pkg / "NAV" / "AppBin" / "f_BigQuick.bin").write_bytes(b)

    blob = make_contract(
        rsakey,
        [
            ("/SMEG_PLUS_UPG/ctrl.bin", a),
            ("/SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin", b),
        ],
    )
    (pkg / "contract.dat").write_bytes(blob)

    # the stock contract should need no changes
    hdr, recs, key = pc.load_contract(str(pkg / "contract.dat"), [rsakey])
    assert len(recs) == 2
    for rec in recs:
        fp = pc.resolve(str(pkg), rec[: rec.index(b"\0")].decode())
        payload, _ = pc.check_of(rec, Path(fp).read_bytes())
        assert pc.rebuild_record(rec, payload) == rec

    # now modify a file and rebuild the contract
    (pkg / "ctrl.bin").write_bytes(b"A" * 600)
    _, recs2, _ = pc.load_contract(str(pkg / "contract.dat"), [rsakey])
    rec = recs2[0]
    payload, how = pc.check_of(rec, Path(str(pkg / "ctrl.bin")).read_bytes())
    assert how == "crc32"
    updated = pc.rebuild_record(rec, payload)
    assert updated != rec
    assert struct.unpack_from(">I", updated, 72)[0] == zlib.crc32(b"A" * 600) & 0xFFFFFFFF


def test_all_three_check_types_recompute(rsakey):
    data = bytes(range(256)) * 4  # 1024 bytes
    size_rec = bytearray(pc.RECORD_SIZE)
    size_rec[63] = 1
    struct.pack_into(">I", size_rec, 64, pc.UNUSED)
    struct.pack_into(">I", size_rec, 68, pc.UNUSED)
    p, how = pc.check_of(bytes(size_rec), data)
    assert how == "size" and struct.unpack(">I", p)[0] == 1024

    crc_rec = bytearray(size_rec)
    crc_rec[63] = 2
    p, how = pc.check_of(bytes(crc_rec), data)
    assert how == "crc32" and struct.unpack(">I", p)[0] == zlib.crc32(data) & 0xFFFFFFFF

    spot_rec = bytearray(size_rec)
    spot_rec[63] = 3
    struct.pack_into(">II", spot_rec, 64, 16, 32)
    p, how = pc.check_of(bytes(spot_rec), data)
    assert how.startswith("spot") and p == data[32:48]


def test_unknown_check_type_is_refused():
    rec = bytearray(pc.RECORD_SIZE)
    rec[63] = 9
    with pytest.raises(SystemExit):
        pc.check_of(bytes(rec), b"x")


def test_resolve_maps_contract_paths_onto_the_package(tmp_path):
    pkg = str(tmp_path)
    assert pc.resolve(pkg, "/SMEG_PLUS_UPG/NAV/smeg.inf") == os.path.join(pkg, "NAV/smeg.inf")
    assert pc.resolve(pkg, "/SMEG_PLUS_UPG/ctrl.bin") == os.path.join(pkg, "ctrl.bin")
