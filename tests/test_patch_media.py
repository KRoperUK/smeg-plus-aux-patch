import gzip
import io
import os
import re
import struct
import subprocess
import sys
import tarfile
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import media_helpers as mh  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def members(bin_bytes):
    tf = tarfile.open(fileobj=io.BytesIO(gzip.decompress(bin_bytes)))
    return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}


@pytest.fixture()
def media(tmp_path):
    pkg = tmp_path / "SMEG_PLUS_UPG"
    pkg.mkdir()
    info = mh.build_media_package(str(pkg))
    return pkg, info


def extract(tmp_path, pkg, backup=False):
    tree = tmp_path / "tree"
    args = ["extract", "--package", str(pkg), "--module", "NAV", "--tree", str(tree)]
    if backup:
        args += ["--backup", str(tmp_path / "backup")]
    r = run(os.path.join(TOOLS, "patch_media.py"), *args)
    assert r.returncode == 0, r.stderr
    return tree


def test_list_shows_partition_contents(media):
    pkg, info = media
    r = run(os.path.join(TOOLS, "patch_media.py"), "list", "--package", str(pkg), "--module", "NAV")
    assert r.returncode == 0, r.stderr
    for name in info["files"]:
        assert name in r.stdout

    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "list",
        "--package",
        str(pkg),
        "--module",
        "NAV",
        "--tones",
    )
    assert "ring_tones/ring1RT.wav" in r.stdout
    assert "Data_base/smeg.inf" not in r.stdout


def test_extract_restores_the_tree_and_backs_up_originals(media, tmp_path):
    pkg, info = media
    tree = extract(tmp_path, pkg, backup=True)
    for name, data in info["files"].items():
        assert (tree / name).read_bytes() == data
    assert (tmp_path / "backup" / "NAV" / "ring_tones" / "ring1RT.wav").read_bytes() == info[
        "files"
    ]["ring_tones/ring1RT.wav"]


def test_apply_refuses_when_nothing_changed(media, tmp_path):
    pkg, _ = media
    tree = extract(tmp_path, pkg)
    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "apply",
        "--package",
        str(pkg),
        "--module",
        "NAV",
        "--tree",
        str(tree),
        "--out",
        str(tmp_path / "out"),
    )
    assert r.returncode != 0
    assert "no differences" in (r.stdout + r.stderr)


def test_apply_rebuilds_the_whole_cascade(media, tmp_path):
    pkg, info = media
    tree = extract(tmp_path, pkg)

    new_tone = mh.wav_bytes(frames=2000)  # bigger than the 441-frame original
    (tree / "ring_tones" / "ring1RT.wav").write_bytes(new_tone)
    out = tmp_path / "out"

    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "apply",
        "--package",
        str(pkg),
        "--module",
        "NAV",
        "--tree",
        str(tree),
        "--out",
        str(out),
    )
    assert r.returncode == 0, r.stderr

    new_bin = (out / "NAV" / "system.bin").read_bytes()
    data = members(new_bin)

    # the change is in the partition, and only the change
    assert data["ring_tones/ring1RT.wav"] == new_tone
    assert data["ring_tones/ring2RT.wav"] == info["files"]["ring_tones/ring2RT.wav"]

    # system.bin.inf: CRC is over the new container, SIZE moves by exactly our change
    inf = (out / "NAV" / "system.bin.inf").read_bytes().decode()
    g = lambda k: int(re.search(k + r": (\d+)", inf).group(1))
    assert g("CRC32") == crc(new_bin)

    old_len = len(info["files"]["ring_tones/ring1RT.wav"])
    grew = len(new_tone) - old_len
    assert g("SIZE") - info["sizes"]["SIZE"] == grew
    for n in (1, 2, 4, 8, 16, 32):
        b = n * 1024
        expected = (len(new_tone) + b - 1) // b * b - (old_len + b - 1) // b * b
        assert g("SIZE_%d" % n) - info["sizes"]["SIZE_%d" % n] == expected

    # system_ctrl.bin: the record for the changed file carries its new CRC
    ctrl = (out / "NAV" / "system_ctrl.bin").read_bytes()
    off = ctrl.index(b"/SYSTEM/ring_tones/ring1RT.wav")
    assert struct.unpack_from(">I", ctrl, off + 260)[0] == crc(new_tone)
    # ...and the unchanged file still has its original CRC
    off2 = ctrl.index(b"/SYSTEM/ring_tones/ring2RT.wav")
    assert struct.unpack_from(">I", ctrl, off2 + 260)[0] == crc(
        info["files"]["ring_tones/ring2RT.wav"]
    )

    # manifests
    mod = (out / "NAV_ctrl.bin").read_bytes()
    root = (out / "ctrl.bin").read_bytes()
    assert struct.pack(">I", crc(new_bin)) in mod
    assert struct.pack(">I", crc(ctrl)) in mod
    assert struct.pack(">I", crc(mod)) in root

    # the source package is untouched
    assert (pkg / "NAV" / "system.bin").read_bytes() == info["bin"]


def test_size_fields_are_preserved_exactly_when_untouched(media):
    """The vendor's SIZE values carry an offset we do not model — the delta must be zero."""
    sys.path.insert(0, TOOLS)
    import patch_media as pm

    pkg, info = media
    part = pm.Partition(str(pkg), "NAV")
    inf = (pkg / "NAV" / "system.bin.inf").read_bytes()
    old = pm.read_size_fields(inf)
    adjusted = pm.adjusted_size_fields(part.data, part.data, old)
    assert adjusted == old


def test_restore_puts_the_original_back(media, tmp_path):
    pkg, info = media
    tree = extract(tmp_path, pkg, backup=True)
    tone = tree / "ring_tones" / "ring1RT.wav"
    tone.write_bytes(b"not the original at all")

    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "restore",
        "--backup",
        str(tmp_path / "backup"),
        "--tree",
        str(tree),
        "--module",
        "NAV",
        "--only",
        "ring_tones/ring1RT.wav",
    )
    assert r.returncode == 0, r.stderr
    assert tone.read_bytes() == info["files"]["ring_tones/ring1RT.wav"]


def test_apply_only_limits_the_change(media, tmp_path):
    pkg, info = media
    tree = extract(tmp_path, pkg)
    (tree / "ring_tones" / "ring1RT.wav").write_bytes(mh.wav_bytes(frames=2000))
    (tree / "ring_tones" / "ring2RT.wav").write_bytes(mh.wav_bytes(frames=2000))

    out = tmp_path / "out"
    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "apply",
        "--package",
        str(pkg),
        "--module",
        "NAV",
        "--tree",
        str(tree),
        "--out",
        str(out),
        "--only",
        "ring_tones/ring1RT.wav",
    )
    assert r.returncode == 0, r.stderr
    data = members((out / "NAV" / "system.bin").read_bytes())
    assert data["ring_tones/ring1RT.wav"] != info["files"]["ring_tones/ring1RT.wav"]
    assert data["ring_tones/ring2RT.wav"] == info["files"]["ring_tones/ring2RT.wav"]
