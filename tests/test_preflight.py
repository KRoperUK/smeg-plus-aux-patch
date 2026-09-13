"""Tests for the pre-flight check.

The point of this tool is that it fails loudly on the things that have cost car trips, so
the tests are about the failures it must catch rather than the happy path.
"""

import gzip
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import preflight  # noqa: E402


def up_common(last_source=None, names=None):
    names = names or ["Alien", "Blue_lemon"]
    t = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    t.close()
    c = sqlite3.connect(t.name)
    c.execute(
        "create table UP_Keys (Section text, Name text, Idx int, IntValue int, StringValue text)"
    )
    for i, n in enumerate(names):
        c.execute("insert into UP_Keys values ('phone','Ringing_List',?,NULL,?)", (i, n))
    if last_source is not None:
        c.execute("insert into UP_Keys values ('supervisor','Last_Source',0,?,'')", (last_source,))
    c.commit()
    c.close()
    data = open(t.name, "rb").read()
    os.unlink(t.name)
    return data


def make_pkg(tmp_path, last_source=None, user_data=False):
    pkg = tmp_path / "pkg"
    files = {"Data_base/sqlite/up_common.sqlite": up_common(last_source)}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(data))
    (pkg / "NAV").mkdir(parents=True)
    (pkg / "NAV" / "system.bin").write_bytes(gzip.compress(buf.getvalue(), 6))
    (pkg / "ctrl.bin").write_bytes(b"x")
    (pkg / "contract.dat").write_bytes(b"x")
    (pkg / "media.inf").write_bytes(b"VER:0\n")
    if user_data:
        d = pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite"
        d.mkdir(parents=True)
        (d / "up_common.sqlite").write_bytes(up_common(last_source))
    return pkg


def run(pkg, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(TOOLS, "preflight.py"), "--package", str(pkg), *extra],
        capture_output=True,
        text=True,
    )


def test_flags_a_source_that_is_not_a_real_source(tmp_path):
    """The exact mistake that cost a car trip: 4 is not a valid source."""
    r = run(make_pkg(tmp_path, last_source=4))
    out = r.stdout + r.stderr
    assert r.returncode != 0, "an invalid source must be a hard failure"
    assert "NOT a valid source" in out
    assert "AUX" in out, "it should name what the valid values are"


def test_accepts_a_real_source(tmp_path):
    r = run(make_pkg(tmp_path, last_source=7))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "= 7 (AUX)" in out


def test_warns_about_a_user_data_payload(tmp_path):
    r = run(make_pkg(tmp_path, last_source=7, user_data=True))
    out = r.stdout + r.stderr
    assert "user partition" in out
    assert "presets" in out, "it should say what is at risk"


def test_says_what_it_does_not_know(tmp_path):
    """The unknowns are where the car trips went, so they must be printed."""
    r = run(make_pkg(tmp_path, last_source=7))
    out = r.stdout + r.stderr
    assert "merge" in out and "replace" in out or "cannot be settled" in out


def test_json_output_is_parseable(tmp_path):
    r = run(make_pkg(tmp_path, last_source=4), "--json")
    data = json.loads(r.stdout)
    assert data["problems"] >= 1
    assert any(row["level"] == "bad" for row in data["rows"])


def test_a_missing_package_is_a_clean_error(tmp_path):
    r = run(tmp_path / "nope")
    assert r.returncode != 0
    assert "no such package" in (r.stdout + r.stderr)


def test_a_user_data_payload_in_a_renamed_folder_is_reported_as_ignored(tmp_path):
    """The updater's path is hard-coded; a renamed package folder silently loses it."""
    pkg = tmp_path / "SMEG_PLUS_UPG_auxdefault"
    sqlite_dir = pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite"
    sqlite_dir.mkdir(parents=True)
    (sqlite_dir / "up_common.sqlite").write_bytes(b"x")

    rep = preflight.Report()
    preflight.check_user_data(rep, str(pkg), "NAV")
    bad = [m for lvl, _, m in rep.rows if lvl == preflight.BAD]
    assert any("IGNORED" in m and "SMEG_PLUS_UPG" in m for m in bad), bad


def test_a_correctly_named_folder_raises_no_path_complaint(tmp_path):
    pkg = tmp_path / "SMEG_PLUS_UPG"
    sqlite_dir = pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite"
    sqlite_dir.mkdir(parents=True)
    (sqlite_dir / "up_common.sqlite").write_bytes(b"x")

    rep = preflight.Report()
    preflight.check_user_data(rep, str(pkg), "NAV")
    assert not [m for lvl, _, m in rep.rows if lvl == preflight.BAD]


def test_a_non_nav_payload_is_reported_as_unread(tmp_path):
    pkg = tmp_path / "SMEG_PLUS_UPG"
    sqlite_dir = pkg / "AUDIO_BT" / "USER_DATA" / "user_data" / "sqlite"
    sqlite_dir.mkdir(parents=True)
    (sqlite_dir / "up_common.sqlite").write_bytes(b"x")

    rep = preflight.Report()
    preflight.check_user_data(rep, str(pkg), "AUDIO_BT")
    bad = [m for lvl, _, m in rep.rows if lvl == preflight.BAD]
    assert any("NAV" in m for m in bad), bad
