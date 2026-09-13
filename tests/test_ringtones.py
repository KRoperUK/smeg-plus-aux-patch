import os
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)


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

    r = run(
        os.path.join(TOOLS, "ringtones.py"), "stage", src, "--slot", "ring1", "--tree", str(bad)
    )

    assert r.returncode != 0
    assert "extracted media partition" in (r.stdout + r.stderr)
    assert not (bad / "ring_tones").exists(), "must not create ring_tones/ in a bogus tree"


def test_stage_writes_the_format_the_slot_expects(tmp_path):
    tree = tmp_path / "media"
    (tree / "ring_tones").mkdir(parents=True)
    src = make_wav(tmp_path / "song.wav", channels=1, rate=44100)

    r = run(
        os.path.join(TOOLS, "ringtones.py"), "stage", src, "--slot", "ring1", "--tree", str(tree)
    )
    assert r.returncode == 0, r.stderr

    out = tree / "ring_tones" / "ring1RT.wav"
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 44100, 2)


def test_wait_tone_slot_targets_stereo_8k(tmp_path):
    tree = tmp_path / "media"
    (tree / "wait_tones").mkdir(parents=True)
    src = make_wav(tmp_path / "hold.wav", channels=2, rate=8000)

    r = run(
        os.path.join(TOOLS, "ringtones.py"), "stage", src, "--slot", "wait:ENG", "--tree", str(tree)
    )
    assert r.returncode == 0, r.stderr

    out = tree / "wait_tones" / "MM_HoldOn_ENG_8kHz.wav"
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 8000, 2)


def test_export_needs_a_media_tree(tmp_path):
    bad = tmp_path / "nope"
    bad.mkdir()
    r = run(
        os.path.join(TOOLS, "ringtones.py"),
        "export",
        "--tree",
        str(bad),
        "-o",
        str(tmp_path / "out"),
    )
    assert r.returncode != 0
    assert "extracted media partition" in (r.stdout + r.stderr)


def test_probe_reports_format(tmp_path):
    src = make_wav(tmp_path / "song.wav", channels=1, rate=22050)
    r = run(os.path.join(TOOLS, "ringtones.py"), "probe", src)
    assert r.returncode == 0, r.stderr
    assert "22050 Hz" in r.stdout and "mono" in r.stdout


# --------------------------------------------------------------- ringtone names
#
# The names the phone UI shows are not in the WAVs. They are rows in up_common.sqlite,
# so replacing a tone changes what you hear and renaming changes what you see.

import sqlite3  # noqa: E402

import media_helpers as mh  # noqa: E402
import ringtones as rt  # noqa: E402


def make_tree(tmp_path, names=None):
    tree = tmp_path / "tree"
    d = tree / "Data_base" / "sqlite"
    d.mkdir(parents=True)
    (d / "up_common.sqlite").write_bytes(mh.up_common_bytes(names))
    return tree


def test_ring_names_reads_the_phone_list(tmp_path):
    tree = make_tree(tmp_path)
    names = rt.ring_names(str(tree))
    assert names[0] == "Alien"
    assert len(names) == 10


def test_ring_names_is_empty_without_the_database(tmp_path):
    """Reading must not be fatal — the GUI calls this for any tree."""
    assert rt.ring_names(str(tmp_path)) == []
    assert rt.ring_names("") == []


def test_set_ring_name_changes_exactly_one_row(tmp_path):
    tree = make_tree(tmp_path)
    rt.set_ring_name(str(tree), 0, "Piano Riff")
    names = rt.ring_names(str(tree))
    assert names[0] == "Piano Riff"
    assert names[1] == "Blue_lemon", "only the named row should move"
    assert len(names) == 10


def test_set_ring_name_refuses_a_missing_index(tmp_path):
    tree = make_tree(tmp_path, names=["Only_one"])
    try:
        rt.set_ring_name(str(tree), 5, "nope")
    except SystemExit as e:
        assert "exactly one row" in str(e)
    else:
        raise AssertionError("expected SystemExit for an index that does not exist")


def test_set_ring_name_refuses_a_tree_without_the_database(tmp_path):
    try:
        rt.set_ring_name(str(tmp_path), 0, "nope")
    except SystemExit as e:
        assert "up_common.sqlite" in str(e)
    else:
        raise AssertionError("expected SystemExit when the database is absent")


def test_names_cli(tmp_path):
    tree = make_tree(tmp_path)
    r = run(os.path.join(TOOLS, "ringtones.py"), "names", "--tree", str(tree))
    assert r.returncode == 0, r.stderr
    assert "Idx 0" in r.stdout and "Alien" in r.stdout


def test_rename_cli(tmp_path):
    tree = make_tree(tmp_path)
    r = run(
        os.path.join(TOOLS, "ringtones.py"),
        "rename",
        "--tree",
        str(tree),
        "--slot",
        "ring1",
        "--name",
        "Piano Riff",
    )
    assert r.returncode == 0, r.stderr
    assert "Piano Riff" in r.stdout
    assert rt.ring_names(str(tree))[0] == "Piano Riff"


def test_rename_cli_rejects_a_non_ring_slot(tmp_path):
    tree = make_tree(tmp_path)
    r = run(
        os.path.join(TOOLS, "ringtones.py"),
        "rename",
        "--tree",
        str(tree),
        "--slot",
        "busy",
        "--name",
        "x",
    )
    assert r.returncode != 0
    assert "ring1..ring5" in (r.stdout + r.stderr)


def test_a_renamed_tone_survives_a_media_rebuild(tmp_path):
    """The whole point: rename in the tree, rebuild the partition, read it back out."""
    import gzip
    import io
    import tarfile

    pkg = tmp_path / "pkg"
    mh.build_media_package(
        pkg, extra_files={"Data_base/sqlite/up_common.sqlite": mh.up_common_bytes()}
    )
    tree = tmp_path / "extracted"
    out = tmp_path / "out"

    r = run(
        os.path.join(TOOLS, "patch_media.py"),
        "extract",
        "--package",
        str(pkg),
        "--module",
        "NAV",
        "--tree",
        str(tree),
        "--backup",
        str(tmp_path / "bk"),
    )
    assert r.returncode == 0, r.stderr

    rt.set_ring_name(str(tree), 0, "Piano Riff")

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

    with gzip.open(out / "NAV" / "system.bin", "rb") as gz:
        reb = gz.read()
    tf = tarfile.open(fileobj=io.BytesIO(reb))  # noqa: SIM115  # reads a BytesIO, not a file descriptor
    db = tf.extractfile("Data_base/sqlite/up_common.sqlite").read()
    tmp_db = tmp_path / "readback.sqlite"
    tmp_db.write_bytes(db)
    con = sqlite3.connect(tmp_db)
    got = con.execute(
        "select StringValue from UP_Keys where Section='phone' and Name='Ringing_List' and Idx=0"
    ).fetchone()[0]
    con.close()
    assert got == "Piano Riff"
