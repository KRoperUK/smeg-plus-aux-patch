"""GUI tests for the Ringtone Studio.

Skipped unless PySide6 is importable, so the suite still runs for contributors without
the optional GUI dependencies. Runs headless via the offscreen platform plugin.
"""
import os
import sys
import wave

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import patch_studio as rs  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def studio(app):
    w = rs.Studio()
    yield w
    w.stop_preview()


def make_wav(path, channels=1, rate=44100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * 4410)
    return str(path)


def test_every_row_has_a_preview_button(studio):
    assert len(studio._preview_btns) == len(rs.SLOTS)
    assert set(studio._preview_btns) == set(rs.SLOTS)
    for btn in studio._preview_btns.values():
        assert btn.toolTip() == "Play this tone"
        assert btn.accessibleName() == "Play this tone"
        assert not btn.icon().isNull(), "icon buttons must carry an icon"


def test_preview_is_disabled_without_a_file(studio, tmp_path):
    studio.tree = str(tmp_path)
    studio.populate()
    assert not any(b.isEnabled() for b in studio._preview_btns.values())


def test_preview_enables_only_for_slots_that_exist(studio, tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    make_wav(tree / "ring_tones" / "ring1RT.wav")
    studio.tree = str(tree)
    studio.populate()

    assert studio._preview_btns["ring1"].isEnabled()
    assert not studio._preview_btns["ring2"].isEnabled()


def test_preview_toggles_and_stops(studio, tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    make_wav(tree / "ring_tones" / "ring1RT.wav")
    studio.tree = str(tree)
    studio.populate()

    studio.preview_tone("ring1")
    assert studio._playing_slot == "ring1"
    assert studio._preview_btns["ring1"].toolTip() == "Stop preview"
    # other rows keep saying Preview
    assert studio._preview_btns["ring2"].toolTip() == "Play this tone"

    # clicking the same row again stops it
    studio.preview_tone("ring1")
    assert studio._playing_slot is None
    assert studio._preview_btns["ring1"].toolTip() == "Play this tone"


def test_stop_preview_is_idempotent(studio):
    studio.stop_preview()
    studio.stop_preview()
    assert studio._playing_slot is None


def test_populate_resets_button_registry(studio, tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    make_wav(tree / "ring_tones" / "ring1RT.wav")
    studio.tree = str(tree)
    studio.populate()
    first = studio._preview_btns["ring1"]
    studio.populate()
    assert studio._preview_btns["ring1"] is not first
    assert len(studio._preview_btns) == len(rs.SLOTS)


def test_switching_slots_stops_the_previous(studio, tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    make_wav(tree / "ring_tones" / "ring1RT.wav")
    make_wav(tree / "ring_tones" / "ring2RT.wav")
    studio.tree = str(tree)
    studio.populate()

    studio.preview_tone("ring1")
    studio.preview_tone("ring2")
    assert studio._playing_slot == "ring2"
    assert studio._preview_btns["ring1"].toolTip() == "Play this tone"
    assert studio._preview_btns["ring2"].toolTip() == "Stop preview"


def test_studio_still_builds_its_tabs(studio):
    """Smoke test: the window and every tab construct without raising."""
    from PySide6.QtWidgets import QTabWidget
    tabs = studio.findChildren(QTabWidget)[0]
    assert tabs.count() == 3
    assert studio.table.rowCount() == len(rs.SLOTS)


# ---------------------------------------------------------------------- splash
#
# A synthetic .pkg keeps these tests free of any vendor firmware: the container is built
# here from flat-colour images and must parse, preview and rebuild.

import struct  # noqa: E402
import zlib  # noqa: E402

import splash  # noqa: E402


def solid_bmp(rgb):
    """A real 800x480 24-bit bottom-up BMP, built by hand so no encoder is involved."""
    body = bytes((rgb[2], rgb[1], rgb[0])) * (splash.IMAGE_W * splash.IMAGE_H)
    file_hdr = b"BM" + struct.pack("<IHHI", 54 + len(body), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, splash.IMAGE_W, splash.IMAGE_H, 1, 24, 0,
                      len(body), 2835, 2835, 0, 0)
    out = file_hdr + dib + body
    assert len(out) == splash.BMP_SIZE
    return out


def make_pkg(path, marque="peugeot", count=4, rgb=(0, 0, 0)):
    """Write a .pkg in the documented layout from synthetic images."""
    chunks = [(zlib.compress(solid_bmp(rgb), 6), b"\x00\x00") for _ in range(count)]
    header = bytearray(splash.HEADER)
    names = [marque + ".bmp"] + ["%s_adml_%02d.bmp" % (marque, i) for i in range(1, count)]
    offs, pos = [], splash.HEADER
    for raw, tr in chunks:
        offs.append(pos)
        pos += 1 + len(raw) + len(tr)
    struct.pack_into(">I", header, 0x04, 1 + len(chunks[0][0]) + len(chunks[0][1]))
    struct.pack_into(">I", header, 0x08, splash.BMP_SIZE)
    p = 0x10
    for i, nm in enumerate(names):
        nb = nm.encode()
        header[p:p + 32] = nb + b"\x00" * (32 - len(nb))
        f = p + 32
        vals = [0, 0, 0, 0, 0, 0]
        if i + 1 < count:
            vals[-2] = offs[i + 1]
            vals[-1] = 1 + len(chunks[i + 1][0]) + len(chunks[i + 1][1])
        for v in vals:
            struct.pack_into(">I", header, f, v)
            f += 4
        p = f
    struct.pack_into(">I", header, 0x00, zlib.crc32(bytes(header[4:])) & 0xffffffff)
    body = b"".join(b"\x08" + raw + tr for raw, tr in chunks)
    path.write_bytes(bytes(header) + body)
    return path


@pytest.fixture()
def media_tree(tmp_path):
    tree = tmp_path / "media"
    (tree / splash.DIR).mkdir(parents=True)
    make_pkg(tree / splash.DIR / "peugeot.pkg")
    make_pkg(tree / splash.DIR / "ds.pkg", marque="ds", count=4)
    return tree


def test_splash_selftest_rebuilds_a_package_byte_for_byte(media_tree):
    """The container model is only right if a rebuild reproduces the input exactly."""
    for marque in ("peugeot", "ds"):
        p = media_tree / splash.DIR / (marque + ".pkg")
        pk = splash.Pkg(p.read_bytes())
        assert len(pk.chunks) == 4
        assert pk.check_hash()
        same = splash.build(pk, {i: pk.image(i) for i in range(len(pk.chunks))},
                            reuse_compressed=True)
        assert same == p.read_bytes()


def test_splash_replace_changes_only_the_targeted_image(media_tree):
    pkg = media_tree / splash.DIR / "peugeot.pkg"
    before = splash.Pkg(pkg.read_bytes())
    png = media_tree / "logo.bmp"
    png.write_bytes(solid_bmp((255, 0, 0)))
    new = {i: before.image(i) for i in range(len(before.chunks))}
    new[0] = splash.flip_bmp(splash.to_bmp(str(png)))
    pkg.write_bytes(splash.build(before, new))

    after = splash.Pkg(pkg.read_bytes())
    assert after.check_hash()
    assert len(after.chunks) == 4
    assert after.image(0) != before.image(0)
    for i in (1, 2, 3):
        assert after.image(i) == before.image(i), "image %d should be untouched" % i


def test_splash_tab_lists_the_images(studio, media_tree):
    studio.tree = str(media_tree)
    studio.splash_load()
    assert studio.splash_table.rowCount() == 4
    assert studio.splash_table.item(0, 1).text() == "peugeot.bmp"


def test_splash_tab_switches_marque(studio, media_tree):
    studio.tree = str(media_tree)
    studio.splash_marque.setCurrentText("ds")
    studio.splash_load()
    assert studio.splash_table.item(0, 1).text() == "ds.bmp"
    assert "ds.pkg" in studio.splash_label.text()


def test_splash_tab_previews_the_selected_image(studio, media_tree):
    studio.tree = str(media_tree)
    studio.splash_load()
    studio.splash_table.selectRow(0)
    assert not studio.splash_view.pixmap().isNull()


def test_splash_tab_reports_a_missing_tree(studio, tmp_path):
    studio.tree = str(tmp_path)
    studio.splash_load()
    assert studio.splash_table.rowCount() == 0
    assert "no package" in studio.splash_label.text()
