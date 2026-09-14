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
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)


def up_common(last_source=None, names=None):
    names = names or ["Alien", "Blue_lemon"]
    t = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)  # noqa: SIM115  # closed on the next line; delete=False so sqlite can reopen it by name
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
    data = Path(t.name).read_bytes()
    os.unlink(t.name)
    return data


def make_pkg(tmp_path, last_source=None, user_data=False, folder="SMEG_PLUS_UPG"):
    """A minimal package.

    `folder` defaults to the name the updater hard-codes, because a `USER_DATA` payload is
    only read from `/bd0/SMEG_PLUS_UPG/NAV/USER_DATA` — a package built under any other name
    is a real, and silent, mistake. Pass something else to exercise that check.
    """
    pkg = tmp_path / folder
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
        import preflight

        d = pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite"
        d.mkdir(parents=True)
        database = d / "up_common.sqlite"
        database.write_bytes(up_common(last_source))
        (d / "up_common.sqlite.inf").write_bytes(preflight.sqlite_inf(database.read_bytes()))
    return pkg


def run(pkg, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(TOOLS, "preflight.py"), "--package", str(pkg), *extra],
        capture_output=True,
        text=True,
    )


def make_pkg_with_image(tmp_path, version):
    """A package whose application image carries a vendor build path, as the real ones do."""
    import helpers

    pkg = make_pkg(tmp_path)
    appbin = pkg / "NAV" / "AppBin"
    appbin.mkdir(parents=True, exist_ok=True)
    (appbin / "f_BigQuick.bin").write_bytes(
        helpers.pack_bigquick(helpers.make_image_with_build(version))
    )
    return pkg


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
    assert "inf matches the database" in out


def test_refuses_user_data_without_a_crc_sidecar(tmp_path):
    pkg = make_pkg(tmp_path, last_source=7, user_data=True)
    (pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite" / "up_common.sqlite.inf").unlink()

    r = run(pkg)

    assert r.returncode != 0
    assert "has no CRC sidecar" in (r.stdout + r.stderr)


def test_refuses_a_stale_user_data_crc_sidecar(tmp_path):
    pkg = make_pkg(tmp_path, last_source=7, user_data=True)
    sidecar = pkg / "NAV" / "USER_DATA" / "user_data" / "sqlite" / "up_common.sqlite.inf"
    sidecar.write_bytes(b"CRC32: 0\r\n")

    r = run(pkg)

    assert r.returncode != 0
    assert "does not match the database" in (r.stdout + r.stderr)


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


# --- what the firmware version means for the patches --------------------------


def test_reports_the_firmware_version(tmp_path):
    """Every patch address belongs to one version, so say which one this package carries."""
    r = run(make_pkg_with_image(tmp_path, "5.43.A.R2"))
    assert "5.43.A.R2" in (r.stdout + r.stderr)


def test_names_the_version_even_when_it_is_not_the_expected_one(tmp_path):
    r = run(make_pkg_with_image(tmp_path, "5.42.B.R4"))
    assert "5.42.B.R4" in (r.stdout + r.stderr)


def test_says_when_the_version_cannot_be_determined(tmp_path):
    r = run(make_pkg(tmp_path, last_source=7))  # this fixture has no application image
    out = r.stdout + r.stderr
    assert "cannot tell the version" in out, "an unknown must be printed, not omitted"


def test_warns_that_the_payload_directory_must_arrive_lowercase(tmp_path):
    """The trap that made three flashes do nothing: SQLITE vs sqlite, see docs/FLASHING.md."""
    r = run(make_pkg(tmp_path, last_source=7, user_data=True))
    out = r.stdout + r.stderr
    assert "lowercase 'sqlite'" in out
    assert "long-filename" in out, "it should say why it happens"


def test_a_missing_package_is_a_clean_error(tmp_path):
    r = run(tmp_path / "nope")
    assert r.returncode != 0
    assert "no such package" in (r.stdout + r.stderr)



def test_refuses_a_user_data_payload_in_a_wrongly_named_folder(tmp_path):
    """The updater does not search for the payload — it checks one hard-coded path.

    `C_UPGRADE::UpgradeTask` calls `IsDirExist("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA")` and skips
    the copy when it is not there, while the rest of the update succeeds normally. That is
    indistinguishable from a setting having had no effect, so it has to fail the build rather
    than be discovered on a car.
    """
    r = run(make_pkg(tmp_path, last_source=7, user_data=True, folder="SMEG_PLUS_UPG_auxdefault"))

    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "IGNORED" in out
    assert "SMEG_PLUS_UPG_auxdefault" in out, "it should name the offending folder"
    assert "/bd0/SMEG_PLUS_UPG/NAV/USER_DATA" in out, "it should name the path the unit uses"


def test_accepts_a_user_data_payload_in_the_right_folder(tmp_path):
    """The correctly named folder must not trip the check."""
    r = run(make_pkg(tmp_path, last_source=7, user_data=True))

    out = r.stdout + r.stderr
    assert "IGNORED" not in out
    assert "user partition" in out, "the data-loss warning still applies"


def test_folder_name_check_only_applies_to_a_payload(tmp_path):
    """A package with no payload has nothing to lose, so the name does not matter."""
    r = run(make_pkg(tmp_path, last_source=7, folder="whatever"))

    out = r.stdout + r.stderr
    assert "IGNORED" not in out
    assert "no payload" in out


def test_refuses_a_user_data_payload_for_a_non_nav_module(tmp_path):
    """The hard-coded path names NAV, so an AUDIO_BT payload is never read."""
    pkg = make_pkg(tmp_path, last_source=7, user_data=True)
    # move the payload under a module the hard-coded path cannot reach
    (pkg / "AUDIO_BT").mkdir(parents=True, exist_ok=True)
    (pkg / "NAV" / "USER_DATA").rename(pkg / "AUDIO_BT" / "USER_DATA")
    (pkg / "AUDIO_BT" / "system.bin").write_bytes((pkg / "NAV" / "system.bin").read_bytes())

    r = run(pkg, "--module", "AUDIO_BT")

    assert r.returncode != 0
    assert "not read at all" in (r.stdout + r.stderr)
