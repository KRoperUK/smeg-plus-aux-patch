import os
import subprocess
import sys
import wave

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import helpers  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def make_wav(path, channels=1, rate=44100, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return str(path)


def test_list_shows_every_slot():
    r = run(os.path.join(TOOLS, "ringtones.py"), "list")
    assert r.returncode == 0, r.stderr
    for slot in ("ring1", "ring5", "busy", "ko", "wait:ENG", "wait:TRT"):
        assert slot in r.stdout


def test_stage_rejects_a_directory_that_is_not_a_media_tree(tmp_path):
    """Regression for the missing validation: a wrong --tree used to be written into."""
    src = make_wav(tmp_path / "song.wav")
    bad = tmp_path / "not-a-tree"
    bad.mkdir()

    r = run(os.path.join(TOOLS, "ringtones.py"), "stage", src,
            "--slot", "ring1", "--tree", str(bad))

    assert r.returncode != 0
    assert "extracted media partition" in (r.stdout + r.stderr)
    assert not (bad / "ring_tones").exists(), "must not create ring_tones/ in a bogus tree"


def test_stage_writes_the_format_the_slot_expects(tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    src = make_wav(tmp_path / "song.wav", channels=1, rate=44100)

    r = run(os.path.join(TOOLS, "ringtones.py"), "stage", src,
            "--slot", "ring1", "--tree", str(tree))
    assert r.returncode == 0, r.stderr

    out = tree / "ring_tones" / "ring1RT.wav"
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 44100, 2)


def test_wait_tone_slot_targets_stereo_8k(tmp_path):
    tree = tmp_path / "media"
    (tree / "wait_tones").mkdir(parents=True)
    src = make_wav(tmp_path / "hold.wav", channels=2, rate=8000)

    r = run(os.path.join(TOOLS, "ringtones.py"), "stage", src,
            "--slot", "wait:ENG", "--tree", str(tree))
    assert r.returncode == 0, r.stderr

    out = tree / "wait_tones" / "MM_HoldOn_ENG_8kHz.wav"
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 8000, 2)


def test_export_needs_a_media_tree(tmp_path):
    bad = tmp_path / "nope"
    bad.mkdir()
    r = run(os.path.join(TOOLS, "ringtones.py"), "export",
            "--tree", str(bad), "-o", str(tmp_path / "out"))
    assert r.returncode != 0
    assert "extracted media partition" in (r.stdout + r.stderr)


def test_probe_reports_format(tmp_path):
    src = make_wav(tmp_path / "song.wav", channels=1, rate=22050)
    r = run(os.path.join(TOOLS, "ringtones.py"), "probe", src)
    assert r.returncode == 0, r.stderr
    assert "22050 Hz" in r.stdout and "mono" in r.stdout
