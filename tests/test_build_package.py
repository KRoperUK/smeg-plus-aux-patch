"""Tests for the manifest-driven build.

The full build needs a real package with an application image, so it is exercised against
a real one out of band. What is covered here is the orchestration's own logic and the
guards that stop it doing something destructive — those are the parts that would fail
*silently* if they were wrong.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)


def load_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_package", os.path.join(TOOLS, "build_package.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(manifest, *extra):
    import subprocess
    return subprocess.run(
        [sys.executable, os.path.join(TOOLS, "build_package.py"),
         "--manifest", str(manifest), *extra],
        capture_output=True, text=True)


def manifest(tmp_path, **over):
    cfg = {"package": str(tmp_path / "pkg"), "out": str(tmp_path / "out"), "module": "NAV"}
    cfg.update(over)
    p = tmp_path / "build.json"
    p.write_text(json.dumps(cfg))
    return p


@pytest.fixture()
def fake_pkg(tmp_path):
    p = tmp_path / "pkg"
    (p / "NAV").mkdir(parents=True)
    (p / "ctrl.bin").write_bytes(b"x")
    return p


# ------------------------------------------------------------------- helpers

def test_overlay_preserves_relative_paths(tmp_path):
    bp = load_build()
    src = tmp_path / "src"
    (src / "NAV" / "AppBin").mkdir(parents=True)
    (src / "ctrl.bin").write_bytes(b"root")
    (src / "NAV" / "AppBin" / "f_BigQuick.bin").write_bytes(b"img")
    dest = tmp_path / "dest"
    dest.mkdir()

    bp.overlay(str(src), str(dest))

    assert (dest / "ctrl.bin").read_bytes() == b"root"
    assert (dest / "NAV" / "AppBin" / "f_BigQuick.bin").read_bytes() == b"img"


def test_overlay_dry_run_writes_nothing(tmp_path):
    bp = load_build()
    src = tmp_path / "src"
    src.mkdir()
    (src / "ctrl.bin").write_bytes(b"root")
    dest = tmp_path / "dest"
    dest.mkdir()

    bp.overlay(str(src), str(dest), dry=True)

    assert list(dest.iterdir()) == []


# ------------------------------------------------------------------- guards

def test_refuses_to_build_in_place(tmp_path, fake_pkg):
    m = manifest(tmp_path, package=str(fake_pkg), out=str(fake_pkg))
    r = run_cli(m)
    assert r.returncode != 0
    assert "must differ" in (r.stdout + r.stderr)


def test_refuses_to_clobber_an_existing_out(tmp_path, fake_pkg):
    """A half-built directory must never be silently reused."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "precious").write_bytes(b"keep me")
    m = manifest(tmp_path, package=str(fake_pkg), out=str(out))

    r = run_cli(m)

    assert r.returncode != 0
    assert "already exists" in (r.stdout + r.stderr)
    assert (out / "precious").read_bytes() == b"keep me", "must not touch an existing out"


def test_refuses_a_missing_package(tmp_path):
    m = manifest(tmp_path, package=str(tmp_path / "nope"), out=str(tmp_path / "o"))
    r = run_cli(m)
    assert r.returncode != 0
    assert "no such package" in (r.stdout + r.stderr)


def test_refuses_an_unknown_patch_set(tmp_path, fake_pkg):
    m = manifest(tmp_path, package=str(fake_pkg), out=str(tmp_path / "o"),
                 app={"patches": ["not-a-real-patch-set"]})
    r = run_cli(m)
    assert r.returncode != 0
    assert "no such patch set" in (r.stdout + r.stderr)


def test_dry_run_writes_nothing(tmp_path, fake_pkg):
    out = tmp_path / "out"
    m = manifest(tmp_path, package=str(fake_pkg), out=str(out),
                 app={"patches": ["aux-autoswitch"]})

    r = run_cli(m, "--dry-run")

    assert r.returncode == 0, r.stderr
    assert not out.exists(), "dry run must not create the output package"
    assert "dry run" in r.stdout


def test_dry_run_shows_the_order(tmp_path, fake_pkg):
    """The ordering is the reason this tool exists, so assert it is what gets printed."""
    m = manifest(tmp_path, package=str(fake_pkg), out=str(tmp_path / "o"),
                 app={"patches": ["aux-autoswitch"]},
                 media={"tones": {"ring_tones/ring1RT.wav": "tone.wav"}})
    r = run_cli(m, "--dry-run")
    assert r.returncode == 0, r.stderr
    seq = [ln for ln in r.stdout.splitlines() if ln.startswith("==>")]
    assert any("applying patch set aux-autoswitch" in s for s in seq)
    assert any("rebuilding the media partition" in s for s in seq)
    assert "re-sealing the contract" in seq[-1], "the seal must always be last"
    # and the application patch must precede the media work, or the media step rebuilds
    # ctrl.bin without the application change and silently drops it
    app_i = next(i for i, s in enumerate(seq) if "applying patch set" in s)
    media_i = next(i for i, s in enumerate(seq) if "extracting the media partition" in s)
    assert app_i < media_i
