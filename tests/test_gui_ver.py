"""`media.gui_ver` sets the one version field that is both visible and not gated on.

The System Info screen reads `smeg.inf` from **inside** `system.bin`, so a build marker has
to change `Data_base/smeg.inf` in the partition — not the module-level `NAV/smeg.inf` beside
it, which the updater uses but nothing displays. `GUI_VER` is safe to change because no
update decision depends on it (`VER:` and `media.inf` do).

These checks run against the synthetic media fixture, so no firmware is needed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

import pytest  # noqa: E402
from pathlib import Path  # noqa: E402


def load_build_package():
    import importlib.util

    path = os.path.join(TOOLS, "build_package.py")
    spec = importlib.util.spec_from_file_location("build_package", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = load_build_package()


@pytest.fixture
def tree(tmp_path):
    """A minimal extracted-partition tree carrying the displayed smeg.inf."""
    d = tmp_path / "tree" / "Data_base"
    d.mkdir(parents=True)
    (d / "smeg.inf").write_bytes(
        b"BSP_CRC32: 1898196070 \r\nBIGQUICK_CRC32: 2003021792 \r\n"
        b"VER: SMEG5.43.A.R2 \r\nGUI_VER:32.00 \r\n"
    )
    return str(tmp_path / "tree")


def read(tree):
    return Path(os.path.join(tree, "Data_base", "smeg.inf")).read_bytes()


def test_sets_gui_ver_and_keeps_the_line_format(tree):
    """The unit's format is `KEY:VALUE ` terminated by CRLF — preserve it exactly."""
    bp.set_gui_ver(tree, "32.01")
    raw = read(tree)
    assert b"GUI_VER:32.01 \r\n" in raw
    assert b"GUI_VER:32.00" not in raw
    assert raw.endswith(b"\r\n"), "the trailing CRLF must survive"


def test_leaves_the_gating_fields_alone(tree):
    """`VER:` and the CRC lines drive update decisions — a marker must not disturb them."""
    before = read(tree)
    bp.set_gui_ver(tree, "99.99")
    after = read(tree)
    for line in (b"VER: SMEG5.43.A.R2 ", b"BSP_CRC32: 1898196070 ", b"BIGQUICK_CRC32: 2003021792 "):
        assert line in before and line in after
    assert len(after.split(b"\r\n")) == len(before.split(b"\r\n")), "no lines added or removed"


def test_accepts_a_non_string_value(tree):
    bp.set_gui_ver(tree, 33)
    assert b"GUI_VER:33 \r\n" in read(tree)


def test_fails_loudly_when_there_is_no_gui_ver_line(tmp_path):
    d = tmp_path / "t" / "Data_base"
    d.mkdir(parents=True)
    (d / "smeg.inf").write_bytes(b"VER: X \r\n")
    with pytest.raises(SystemExit) as e:
        bp.set_gui_ver(str(tmp_path / "t"), "1.0")
    assert "GUI_VER" in str(e.value)


def test_fails_loudly_when_the_tree_is_not_a_partition(tmp_path):
    with pytest.raises(SystemExit) as e:
        bp.set_gui_ver(str(tmp_path), "1.0")
    assert "smeg.inf" in str(e.value)
