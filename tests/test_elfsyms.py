"""Tests for the ELF symbol reader.

The ELF here is assembled byte by byte in the test — the real ones are vendor binaries and
never enter the repository.
"""
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import elfsyms  # noqa: E402

SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB = 1, 2, 3
STT_OBJECT, STT_FUNC = 1, 2
TEXT_ADDR = 0x1000


def build_elf(text=b"\x4e\x80\x00\x20", symbols=(), big_endian=True, bitness=1):
    """A minimal ELF32 BE object with one .text, a symtab and its strtab."""
    names = ["", ".text", ".symtab", ".strtab", ".shstrtab"]
    shstrtab, offsets = b"", {}
    for n in names:
        offsets[n] = len(shstrtab)
        shstrtab += n.encode() + b"\x00"

    strtab, sym_name_off = b"\x00", {}
    for sym in symbols:
        name = sym[0]
        sym_name_off[name] = len(strtab)
        strtab += name.encode() + b"\x00"

    symtab = b"\x00" * 16                       # index 0 is always the null symbol
    for sym in symbols:
        name, value, stype = sym[0], sym[1], sym[2]
        size = sym[3] if len(sym) > 3 else 0
        symtab += struct.pack(">IIIBBH", sym_name_off[name], value, size, stype, 0, 1)

    cursor = 52
    text_off = cursor;      cursor += len(text)
    symtab_off = cursor;    cursor += len(symtab)
    strtab_off = cursor;    cursor += len(strtab)
    shstr_off = cursor;     cursor += len(shstrtab)
    shoff = cursor

    def sh(name, stype, addr, offset, size, link=0, entsize=0):
        return struct.pack(">IIIIIIIIII", offsets[name], stype, 0, addr, offset, size,
                           link, 0, 1, entsize)

    headers = (sh("", 0, 0, 0, 0)
               + sh(".text", SHT_PROGBITS, TEXT_ADDR, text_off, len(text))
               + sh(".symtab", SHT_SYMTAB, 0, symtab_off, len(symtab), link=3, entsize=16)
               + sh(".strtab", SHT_STRTAB, 0, strtab_off, len(strtab))
               + sh(".shstrtab", SHT_STRTAB, 0, shstr_off, len(shstrtab)))

    ident = b"\x7fELF" + bytes([bitness, 2 if big_endian else 1, 1]) + b"\x00" * 9
    ehdr = ident + struct.pack(">HHIIIIIHHHHHH",
                               1, 20, 1, 0, 0, shoff, 0, 52, 0, 0, 40, 5, 4)
    return ehdr + text + symtab + strtab + shstrtab + headers


# --- rejecting things that are not what we want ------------------------------

def test_a_non_elf_is_refused():
    with pytest.raises(elfsyms.ElfError, match="not an ELF"):
        elfsyms.Elf32BE(b"MZ" + b"\x00" * 200)


def test_little_endian_is_refused():
    """These targets are PowerPC; a little-endian object is the wrong file."""
    with pytest.raises(elfsyms.ElfError, match="big-endian"):
        elfsyms.Elf32BE(build_elf(big_endian=False))


def test_64_bit_is_refused():
    with pytest.raises(elfsyms.ElfError, match="32-bit"):
        elfsyms.Elf32BE(build_elf(bitness=2))


# --- reading it --------------------------------------------------------------

SYMS = (("_ZN9C_UPGRADE13ManageZAFilesEv", 0x1010, STT_FUNC),
        ("_ZN9C_UPGRADE11UpgradeTaskEv", 0x1000, STT_FUNC),
        ("some_global", 0x2000, STT_OBJECT))


def test_sections_are_named():
    elf = elfsyms.Elf32BE(build_elf())
    assert [s["name"] for s in elf.sections] == \
        ["", ".text", ".symtab", ".strtab", ".shstrtab"]
    assert elf.section(".text")["addr"] == TEXT_ADDR
    assert elf.section(".nope") is None


def test_symbols_and_functions_are_read():
    elf = elfsyms.Elf32BE(build_elf(symbols=SYMS))
    names = {s["name"] for s in elf.symbols()}
    assert "_ZN9C_UPGRADE13ManageZAFilesEv" in names
    assert "some_global" in names
    funcs = elf.functions()
    assert [f["value"] for f in funcs] == [0x1000, 0x1010]      # address order
    assert all(f["type"] == STT_FUNC for f in funcs)            # the object is excluded


def test_owner_of_an_address_is_the_function_containing_it():
    elf = elfsyms.Elf32BE(build_elf(symbols=SYMS))
    assert elf.owner_of(0x1008)["value"] == 0x1000
    assert elf.owner_of(0x1010)["value"] == 0x1010
    assert elf.owner_of(0x1234)["value"] == 0x1010
    assert elf.owner_of(0x0900) is None


def test_string_literals_come_out_of_text():
    """These objects keep their literals at the tail of .text, not in a .rodata."""
    text = b"\x4e\x80\x00\x20" + b"\x00" + b"Phase 6\x00" + b"Management of ZA files\x00"
    elf = elfsyms.Elf32BE(build_elf(text=text))
    found = dict((s, a) for a, s in elf.literals())
    assert "Phase 6" in found
    assert "Management of ZA files" in found
    assert found["Phase 6"] == TEXT_ADDR + 5


def test_short_runs_are_not_mistaken_for_strings():
    elf = elfsyms.Elf32BE(build_elf(text=b"ab\x00" + b"\x4e\x80\x00\x20"))
    assert [s for _, s in elf.literals()] == []


def test_runs_inside_a_function_are_not_literals():
    """`blr` is 4e 80 00 20 — that trailing 0x20 reads as a space, and the byte before it
    is a NUL, so only the symbol table can rule it out."""
    text = b"\x4e\x80\x00\x20" + b"Phase 6\x00"
    sized = (("_ZN9C_UPGRADE11UpgradeTaskEv", TEXT_ADDR, STT_FUNC, 4),)
    elf = elfsyms.Elf32BE(build_elf(text=text, symbols=sized))
    assert [s for _, s in elf.literals()] == []
    # without the symbol table's help the stray space is indistinguishable from content
    assert [s for _, s in elf.literals(skip_code=False)] == [" Phase 6"]


def test_literals_outside_every_function_are_kept():
    text = b"\x4e\x80\x00\x20" + b"\x00" + b"Management of ZA files\x00"
    sized = (("_ZN9C_UPGRADE11UpgradeTaskEv", TEXT_ADDR, STT_FUNC, 4),)
    elf = elfsyms.Elf32BE(build_elf(text=text, symbols=sized))
    assert [s for _, s in elf.literals()] == ["Management of ZA files"]


# --- demangling --------------------------------------------------------------

@pytest.mark.parametrize("mangled,expected", [
    ("_ZN9C_UPGRADE13ManageZAFilesEv", "C_UPGRADE::ManageZAFiles()"),
    ("_ZN9C_UPGRADE15SetCurrentPhaseERK9CMMString", "C_UPGRADE::SetCurrentPhase(…)"),
    ("_ZN10C_UPG_LOGS8InstanceEv", "C_UPG_LOGS::Instance()"),
])
def test_demangles_the_shape_these_binaries_use(mangled, expected):
    assert elfsyms.demangle(mangled) == expected


@pytest.mark.parametrize("plain", ["tickGet", "memcpy", "", "_not_mangled"])
def test_leaves_unmangled_names_alone(plain):
    assert elfsyms.demangle(plain) == plain
