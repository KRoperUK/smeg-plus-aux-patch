"""`spy-dump-userdata` makes SPYSTORE also back up /USER_DATA to the stick.

The edit repurposes the final calibration-copy block in `C_BCM_SPY::CallBackCopy`
into `GetUserDataDir(entity)` + `Xcopy(entity, dest)`. These checks pin the two things
that matter and neither needs firmware:

  1. the replacement really calls `GetUserDataDir` at `0x0105ae44` — decoded from the
     patch's own `lis`/`addi` pair, so a fat-fingered address fails here rather than on a
     car, and
  2. the shipped definition still applies cleanly through `patch_smeg.py` and rebuilds the
     CRC cascade, exercised against a synthetic image that carries the expect bytes.
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

PATCH_FILE = os.path.join(ROOT, "patches", "spy-dump-userdata.json")

GET_USER_DATA_DIR = 0x0105AE44  # C_FS_STORAGE_CTRL_PATH::GetUserDataDir
XCOPY = 0x010554F4  # C_FS_STORAGE_CTRL_IO::Xcopy
BCTRL = 0x4E800421
NOP = 0x60000000
ADDR = 0x01273A1C  # C_BCM_SPY::CallBackCopy, the *regen* copy block


def words(hexstr):
    raw = bytes.fromhex(hexstr)
    return [struct.unpack(">I", raw[i : i + 4])[0] for i in range(0, len(raw), 4)]


def nav():
    spec = json.loads(Path(PATCH_FILE).read_text())
    return spec["variants"]["NAV"]["patches"][0]


def test_replacement_calls_get_user_data_dir():
    """Decode the lis/addi pair the way the CPU does and confirm the callee address."""
    w = words(nav()["bytes"])
    assert len(w) == 12, "the block is 12 instructions (48 bytes)"

    # lis r9, HI ; addi r9, r9, LO  -> the address loaded into r9 before mtctr/bctrl
    lis, addi = w[0], w[1]
    assert lis >> 26 == 15, "first instruction should be lis (addis)"
    assert addi >> 26 == 14, "second instruction should be addi"
    hi = (lis & 0xFFFF) << 16
    lo = addi & 0xFFFF
    if lo & 0x8000:  # addi's immediate is signed
        lo -= 0x10000
    assert (hi + lo) & 0xFFFFFFFF == GET_USER_DATA_DIR, (
        "the block must call GetUserDataDir (%#010x), got %#010x" % (GET_USER_DATA_DIR, hi + lo)
    )


def test_second_call_is_xcopy_via_the_preserved_register():
    """The block does not reload Xcopy: it reuses r26, which the original block itself
    proves still holds Xcopy at this point (it does `mtctr r26` for its own Xcopy here).
    So the tail is `mtctr r26 ; bctrl` and the whole thing ends padded with nops."""
    w = words(nav()["bytes"])
    assert w[4] == BCTRL, "GetUserDataDir is called at instruction 5"
    assert w[7] == 0x7F4903A6, "instruction 8 should be `mtctr r26` (r26 = Xcopy)"
    assert w[8] == BCTRL, "Xcopy is called at instruction 9"
    assert w[9:] == [NOP, NOP, NOP], "the block is padded to 48 bytes with nops"


def test_expect_matches_the_regen_calibration_block():
    """The bytes we overwrite are the *regen* block: two getter/AddName/Xcopy calls.

    Guards against the address drifting to some other run of instructions.
    """
    expect = words(nav()["expect"])
    assert len(expect) == 12
    # three `bctrl` in the original (GetCalibrationDataDir, AddName, Xcopy), and a
    # `lis r4,0x2f6 ; addi r4,r4,0x7280` pair that loads the "*regen*" string pointer.
    assert expect.count(BCTRL) == 3
    assert expect[3] == 0x3C8002F6, "lis r4,0x2f6 (high half of the *regen* string ptr)"
    assert expect[4] == 0x38847280, "addi r4,r4,0x7280"


def test_shipped_definition_applies_and_cascades(tmp_path):
    """End-to-end: the real patches/spy-dump-userdata.json applies through patch_smeg.py.

    The synthetic image is sized past the patch offset and carries both the firmware token
    and the expect bytes at 0x01273a1c.
    """
    off = ADDR - 0x01000000
    img = bytearray(helpers.make_image_with_build("5.43.A.R2", size=0x280000))
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
