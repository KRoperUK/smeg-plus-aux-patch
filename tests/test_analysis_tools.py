import os
import struct
import subprocess
import sys

import pytest

import helpers

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")


def run(tool, *args):
    return subprocess.run(
        [sys.executable, os.path.join(TOOLS, tool), *map(str, args)],
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def fixture(tmp_path):
    return helpers.make_ppc_analysis_fixture(tmp_path)


def test_ppcdis_resolves_direct_and_indirect_calls(fixture):
    pytest.importorskip("capstone")
    image, symbols = fixture
    result = run("ppcdis.py", image, symbols, "0x01000000", "0x01000018")
    assert result.returncode == 0, result.stderr
    assert "0100000c: bctrl" in result.stdout
    assert "; call target_function" in result.stdout
    assert "01000010: bl" in result.stdout
    assert "; -> target_function" in result.stdout


def test_callers_finds_a_direct_bl_but_not_bctrl(fixture):
    image, symbols = fixture
    result = run("callers.py", image, symbols, "0x01000040")
    assert result.returncode == 0, result.stderr
    assert "callers of 0x1000040 (target_function): 1" in result.stdout
    assert "0x1000010  caller+0x10" in result.stdout


def test_xref_finds_pointer_and_materialised_string_address(fixture):
    image, symbols = fixture
    result = run("xref.py", image, symbols, "Auxiliary_Input")
    assert result.returncode == 0, result.stderr
    assert "string 'Auxiliary_Input' at 0x1000080" in result.stdout
    assert "pointer   @ 0x100001c  in caller+0x1c" in result.stdout
    assert "immediate @ 0x1000024  in caller+0x24" in result.stdout
    assert "total: 1 pointer(s), 1 immediate site(s)" in result.stdout


def test_mkelf_wraps_the_image_and_symbols_as_powerpc_elf(fixture, tmp_path):
    image, symbols = fixture
    output = tmp_path / "analysis.elf"
    result = run("mkelf.py", image, symbols, output)
    assert result.returncode == 0, result.stderr
    assert "3 symbols" in result.stdout

    elf = output.read_bytes()
    assert elf[:16] == b"\x7fELF\x01\x02\x01\x00" + bytes(8)
    header = struct.unpack(">HHIIIIIHHHHHH", elf[16:52])
    assert header[:4] == (2, 20, 1, 0x01000000)
    section_offset, section_size, section_count = header[5], header[10], header[11]
    assert (section_size, section_count) == (40, 5)

    text = struct.unpack(">IIIIIIIIII", elf[section_offset + 40 : section_offset + 80])
    assert text[1:4] == (1, 0x6, 0x01000000)
    assert elf[text[4] : text[4] + text[5]] == image.read_bytes()

    assert b"caller\x00" in elf
    assert b"target_function\x00" in elf
    assert b"aux_name\x00" in elf
