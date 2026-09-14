import json
import os
import subprocess
import sys
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import helpers  # noqa: E402
from pathlib import Path


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


@pytest.fixture()
def pkg(tmp_path):
    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    info = helpers.build_package(str(src))
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(helpers.patch_spec(variant=info["variant"], addr=info["patch_addr"]))
    )
    return src, spec, info


def test_patches_image_and_rebuilds_crc_cascade(pkg, tmp_path):
    src, spec, info = pkg
    out = tmp_path / "out"
    r = run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(out),
        "--patches",
        str(spec),
    )
    assert r.returncode == 0, r.stderr

    bq = os.path.join(str(out), info["variant"], "AppBin", "f_BigQuick.bin")
    raw = Path(bq).read_bytes()

    # the patch is present in the inflated image, and the original bytes are gone
    img = helpers.inflate_container(raw)
    assert img[info["patch_addr"] : info["patch_addr"] + 8].hex() == "386000014e800020"
    assert img != info["image"]

    # cascade: .inf, smeg.inf and the module manifest all agree with the new file CRC
    new_crc = zlib.crc32(raw) & 0xFFFFFFFF
    inf_text = Path(
        os.path.join(str(out), info["variant"], "AppBin", "f_BigQuick.bin.inf")
    ).read_text()
    inf_crc = int(inf_text.splitlines()[0].strip().split()[-1])
    smeg = Path(os.path.join(str(out), info["variant"], "smeg.inf")).read_bytes()
    assert helpers.read_crc_field(smeg, "BIGQUICK_CRC32") == new_crc
    assert inf_crc & 0xFFFFFFFF == new_crc

    import struct

    mod_ctrl = Path(os.path.join(str(out), "%s_ctrl.bin" % info["variant"])).read_bytes()
    assert struct.pack(">I", new_crc) in mod_ctrl
    root_ctrl = Path(os.path.join(str(out), "ctrl.bin")).read_bytes()
    assert struct.pack(">I", zlib.crc32(mod_ctrl) & 0xFFFFFFFF) in root_ctrl


def test_original_untouched(pkg, tmp_path):
    src, spec, info = pkg
    before = Path(info["app_image"]).read_bytes()
    run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(tmp_path / "out"),
        "--patches",
        str(spec),
    )
    assert Path(info["app_image"]).read_bytes() == before


def test_expect_mismatch_fails_loudly(pkg, tmp_path):
    src, spec, info = pkg
    bad = json.loads(spec.read_text())
    bad["variants"][info["variant"]]["patches"][0]["expect"] = "deadbeef"
    spec.write_text(json.dumps(bad))
    r = run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(tmp_path / "out"),
        "--patches",
        str(spec),
    )
    assert r.returncode != 0
    assert "expected" in (r.stdout + r.stderr).lower()


def test_only_flag_skips_other_variants(tmp_path):
    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    helpers.build_package(str(src), variant="NAV")
    helpers.build_package(str(src), variant="AUDIO_BT")
    helpers.set_root_ctrl(str(src), ["NAV", "AUDIO_BT"])
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "name": "synthetic",
                "variants": {
                    **helpers.patch_spec(variant="NAV")["variants"],
                    **helpers.patch_spec(variant="AUDIO_BT")["variants"],
                },
            }
        )
    )
    out = tmp_path / "out"
    r = run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(out),
        "--patches",
        str(spec),
        "--only",
        "NAV",
    )
    assert r.returncode == 0, r.stderr
    assert os.path.exists(os.path.join(str(out), "NAV", "AppBin", "f_BigQuick.bin"))
    assert not os.path.exists(os.path.join(str(out), "AUDIO_BT", "AppBin", "f_BigQuick.bin"))


def test_unpack_round_trip(tmp_path):
    img = helpers.make_image()
    container = tmp_path / "f_BigQuick.bin"
    container.write_bytes(helpers.pack_bigquick(img))
    out = tmp_path / "img.bin"
    r = run(os.path.join(TOOLS, "unpack.py"), str(container), str(out))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == img


# --- addresses are per firmware version --------------------------------------


def test_refuses_an_image_from_another_firmware_version(tmp_path):
    """The `expect` bytes alone are not enough.

    Two entries in `patches/` match at the same address on the `5.42.B.R4` NAV image
    (`0x010346d0`, in `diagnostic-logging` and `diagnostic-logsink`), so on that version
    the expect check would pass and the tool would write to the wrong offset — then
    rebuild the CRC cascade around the damage. The version token is what stops it.
    """
    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    info = helpers.build_package(str(src), img=helpers.make_image_with_build("5.42.B.R4"))
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            helpers.patch_spec(
                variant=info["variant"], addr=info["patch_addr"], firmware="5.43.A.R2"
            )
        )
    )
    out = tmp_path / "out"
    r = run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(out),
        "--patches",
        str(spec),
    )
    assert r.returncode != 0, "a wrong-version image must not be patched"
    combined = r.stdout + r.stderr
    assert "5.43.A.R2" in combined
    assert "5.42.B.R4" in combined, "the message should say which version it did find"
    assert not os.path.exists(os.path.join(str(out), info["variant"], "AppBin", "f_BigQuick.bin"))


def test_applies_when_the_firmware_version_matches(tmp_path):
    src = tmp_path / "SMEG_PLUS_UPG"
    src.mkdir()
    info = helpers.build_package(str(src), img=helpers.make_image_with_build("5.43.A.R2"))
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            helpers.patch_spec(
                variant=info["variant"], addr=info["patch_addr"], firmware="5.43.A.R2"
            )
        )
    )
    out = tmp_path / "out"
    r = run(
        os.path.join(TOOLS, "patch_smeg.py"),
        "--src",
        str(src),
        "--out",
        str(out),
        "--patches",
        str(spec),
    )
    assert r.returncode == 0, r.stderr
    assert "5.43.A.R2" in r.stdout


def test_zensical_nav_matches_docs():
    """Every page listed in the site nav must exist (guards against broken nav)."""
    import re

    cfg = Path(os.path.join(ROOT, "zensical.toml")).read_text()
    pages = re.findall(r'"([A-Za-z0-9_./-]+\.md)"', cfg)
    assert pages, "no pages found in zensical.toml nav"
    for page in pages:
        assert os.path.exists(os.path.join(ROOT, "docs", page)), "missing doc: %s" % page
