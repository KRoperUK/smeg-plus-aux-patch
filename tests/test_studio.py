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

import ringtone_studio as rs  # noqa: E402


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
        assert btn.text() == "Preview"


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
    assert studio._preview_btns["ring1"].text() == "Stop"
    # other rows keep saying Preview
    assert studio._preview_btns["ring2"].text() == "Preview"

    # clicking the same row again stops it
    studio.preview_tone("ring1")
    assert studio._playing_slot is None
    assert studio._preview_btns["ring1"].text() == "Preview"


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
    assert studio._preview_btns["ring1"].text() == "Preview"
    assert studio._preview_btns["ring2"].text() == "Stop"


def test_studio_still_builds_its_tabs(studio):
    """Smoke test: the window and both tabs construct without raising."""
    from PySide6.QtWidgets import QTabWidget
    tabs = studio.findChildren(QTabWidget)[0]
    assert tabs.count() == 2
    assert studio.table.rowCount() == len(rs.SLOTS)
