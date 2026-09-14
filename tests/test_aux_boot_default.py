"""`aux-boot-default` forces C_MGR_SRC::StartUp to restore AUX (position 7) on every boot.

The edit replaces one load in the boot-restore path with a constant, so the value written
to this+0xb4 (which the scheduler matches against each request node's Sched_Pos) is always
7 (POS_AUX) instead of the saved Last_Source. Neither check needs firmware:

  1. `expect` decodes to `lwz r9, 8(r1)` and `bytes` to `li r9, 7`, so a wrong opcode or
     register fails here rather than on a car, and
  2. the shipped definition still applies through `patch_smeg.py` and rebuilds the CRC
     cascade, exercised against a synthetic image carrying the expect bytes at 0x0169948c.
"""

import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import helpers  # noqa: E402
from pathlib import Path  # noqa: E402

PATCH_FILE = os.path.join(ROOT, "patches", "aux-boot-default.json")
ADDR = 0x0169948C  # C_MGR_SRC::StartUp, the boot-restore load


def word(hexstr):
    return struct.unpack(">I", bytes.fromhex(hexstr))[0]


def fields(w):
    return (w >> 26, (w >> 21) & 0x1F, (w >> 16) & 0x1F, w & 0xFFFF)  # op, rD, rA, imm


def nav():
    spec = json.loads(Path(PATCH_FILE).read_text())
    return spec["variants"]["NAV"]["patches"][0]


def test_expect_is_lwz_r9_8_r1():
    """The byte we overwrite must be `lwz r9, 8(r1)` — the saved-source load."""
    op, rd, ra, imm = fields(word(nav()["expect"]))
    assert op == 32, "expect should be lwz (opcode 32)"
    assert rd == 9, "into r9"
    assert ra == 1 and imm == 8, "from 8(r1)"


def test_bytes_are_li_r9_7():
    """The replacement must be `li r9, 7` (addi r9, r0, 7) — force position 7 = POS_AUX."""
    op, rd, ra, imm = fields(word(nav()["bytes"]))
    assert op == 14, "bytes should be addi (opcode 14)"
    assert rd == 9, "into r9 (the value stored to this+0xb4)"
    assert ra == 0, "li form: base register r0"
    assert imm == 7, "the constant must be 7 (POS_AUX), not another source"


def test_shipped_definition_applies_and_cascades(tmp_path):
    """End-to-end: patches/aux-boot-default.json applies through patch_smeg.py."""
    off = ADDR - 0x01000000
    img = bytearray(helpers.make_image_with_build("5.43.A.R2", size=0x6A0000))
    expect = bytes.fromhex(nav()["expect"])
    img[off : off + len(expect)] = expect

    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    helpers.build_package(str(src), variant="NAV", img=bytes(img))

    out = tmp_path / "out"
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(TOOLS, "patch_smeg.py"),
            "--src",
            str(src),
            "--out",
            str(out),
            "--patches",
            PATCH_FILE,
            "--only",
            "NAV",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    bq = out / "NAV" / "AppBin" / "f_BigQuick.bin"
    patched = helpers.inflate_container(bq.read_bytes())
    assert patched[off : off + len(expect)].hex() == nav()["bytes"], "the edit did not land"
