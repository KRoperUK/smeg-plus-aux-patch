"""Multiple `app.patches` entries must accumulate, not overwrite each other.

Every patch set rewrites the same application image and the same manifests. Applying each
one against the **stock** source produced a stock-plus-one-set overlay per run, so copying
them in order left only the last set's edits — silently, with a valid CRC cascade and a
clean re-seal. A build asking for two patch sets therefore shipped one.

This pins the fix: each set is applied to the package built so far, so a two-set build
carries both edits.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import helpers  # noqa: E402
from pathlib import Path  # noqa: E402

# Two edits at different addresses, both inside the synthetic image.
A_ADDR, A_EXPECT, A_BYTES = 0x01001000, "9421ffa0", "386000014e800020"
B_ADDR, B_EXPECT, B_BYTES = 0x01002000, "81210008", "39200007"


def write_patch(path, name, addr, expect, raw):
    Path(path).write_text(
        json.dumps(
            {
                "name": name,
                "description": name,
                "variants": {
                    "NAV": {
                        "app_image": "NAV/AppBin/f_BigQuick.bin",
                        "inf": "NAV/AppBin/f_BigQuick.bin.inf",
                        "smeg_inf": "NAV/smeg.inf",
                        "ctrl": "NAV_ctrl.bin",
                        "base": "0x01000000",
                        "firmware": "5.43.A.R2",
                        "patches": [
                            {"addr": hex(addr), "expect": expect, "bytes": raw, "why": name}
                        ],
                    }
                },
            }
        )
    )


def test_two_patch_sets_both_land(tmp_path, monkeypatch):
    img = bytearray(helpers.make_image_with_build("5.43.A.R2", size=0x200000))
    a_off, b_off = A_ADDR - 0x01000000, B_ADDR - 0x01000000
    img[a_off : a_off + 4] = bytes.fromhex(A_EXPECT)
    img[b_off : b_off + 4] = bytes.fromhex(B_EXPECT)

    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    helpers.build_package(str(src), variant="NAV", img=bytes(img))

    # the patch sets have to live in the repo's patches/ dir — build_package resolves by name
    pdir = Path(ROOT) / "patches"
    a, b = pdir / "_test_chain_a.json", pdir / "_test_chain_b.json"
    write_patch(a, "_test_chain_a", A_ADDR, A_EXPECT, A_BYTES)
    write_patch(b, "_test_chain_b", B_ADDR, B_EXPECT, B_BYTES)

    out = tmp_path / "out"
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "package": str(src),
                "out": str(out),
                "module": "NAV",
                "app": {"patches": ["_test_chain_a", "_test_chain_b"]},
                "seal": False,
            }
        )
    )

    try:
        r = subprocess.run(
            [
                sys.executable,
                os.path.join(TOOLS, "build_package.py"),
                "--manifest",
                str(manifest),
                "--skip-preflight",
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stdout + r.stderr

        patched = helpers.inflate_container(
            (out / "NAV" / "AppBin" / "f_BigQuick.bin").read_bytes()
        )
        got_a = patched[a_off : a_off + len(A_BYTES) // 2].hex()
        got_b = patched[b_off : b_off + len(B_BYTES) // 2].hex()
        assert got_a == A_BYTES, "the first patch set was reverted by the second"
        assert got_b == B_BYTES, "the second patch set did not land"
    finally:
        a.unlink(missing_ok=True)
        b.unlink(missing_ok=True)
