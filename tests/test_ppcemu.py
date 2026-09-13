"""Tests for the function-level PowerPC emulator.

Every image here is assembled in the test itself — no firmware is involved, which is the
same rule the rest of the suite follows.
"""
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

pytest.importorskip("unicorn")

import ppcemu  # noqa: E402

BASE = ppcemu.BASE


# --- a very small PowerPC assembler, enough to build test functions ----------

def li(rd, value):          return 0x38000000 | (rd << 21) | (value & 0xFFFF)
def blr():                  return 0x4E800020
def bl(frm, to):            return 0x48000001 | ((to - frm) & 0x03FFFFFC)
def b(frm, to):             return 0x48000000 | ((to - frm) & 0x03FFFFFC)
def cmpwi(ra, value):       return 0x2F800000 | (ra << 16) | (value & 0xFFFF)
def beq(frm, to):           return 0x419E0000 | ((to - frm) & 0xFFFC)
def nop():                  return 0x60000000
def mflr(rd):               return 0x7C0802A6 | (rd << 21)
def mtlr(rs):               return 0x7C0803A6 | (rs << 21)
def stw(rs, d, ra):         return 0x90000000 | (rs << 21) | (ra << 16) | (d & 0xFFFF)
def stwu(rs, d, ra):        return 0x94000000 | (rs << 21) | (ra << 16) | (d & 0xFFFF)


def image(words_at, size=0x20000):
    """Build an image with {address: [instruction words]}."""
    img = bytearray(size)
    for addr, words in words_at.items():
        off = addr - BASE
        for i, w in enumerate(words):
            struct.pack_into(">I", img, off + i * 4, w)
    return bytes(img)


def emu(words_at, **kw):
    return ppcemu.Emulator(image(words_at), **kw)


# --- the basics --------------------------------------------------------------

def test_executes_a_function_and_returns_r3():
    e = emu({BASE: [li(3, 42), blr()]})
    assert e.call(BASE) == 42
    assert e.error is None


def test_arguments_arrive_in_r3_onwards():
    # return r4 by moving it to r3:  or r3,r4,r4
    e = emu({BASE: [0x7C831378, blr()]})
    assert e.call(BASE, [0x1111, 0x2222]) == 0x2222


def test_too_many_arguments_is_refused():
    e = emu({BASE: [blr()]})
    with pytest.raises(ppcemu.EmuError):
        e.call(BASE, list(range(9)))


# --- patching ----------------------------------------------------------------

def test_patch_changes_what_executes():
    e = emu({BASE: [li(3, 0), blr()]})
    assert e.call(BASE) == 0
    e.patch(BASE, struct.pack(">II", li(3, 1), blr()))
    assert e.call(BASE) == 1


def test_patch_accepts_hex_text_like_the_json_files_use():
    e = emu({BASE: [li(3, 0), blr()]})
    e.patch(BASE, "386000014e800020")          # li r3,1 ; blr
    assert e.call(BASE) == 1


def test_apply_patch_file_verifies_expect_first(tmp_path):
    spec = {"variants": {"NAV": {"patches": [
        {"addr": hex(BASE), "expect": "38600000", "bytes": "38600001"}]}}}
    path = tmp_path / "p.json"
    path.write_text(__import__("json").dumps(spec))

    e = emu({BASE: [li(3, 0), blr()]})
    e.apply_patch_file(str(path), "NAV")
    assert e.call(BASE) == 1


def test_apply_patch_file_refuses_a_mismatched_image(tmp_path):
    spec = {"variants": {"NAV": {"patches": [
        {"addr": hex(BASE), "expect": "deadbeef", "bytes": "38600001"}]}}}
    path = tmp_path / "p.json"
    path.write_text(__import__("json").dumps(spec))

    e = emu({BASE: [li(3, 0), blr()]})
    with pytest.raises(ppcemu.EmuError, match="expected deadbeef"):
        e.apply_patch_file(str(path), "NAV")


# --- calls, stubs and reachability ------------------------------------------

CALLEE = BASE + 0x1000


def test_calls_are_recorded_and_really_executed():
    e = emu({BASE:   [stwu(1, -16, 1), mflr(0), stw(0, 20, 1), bl(BASE + 0xC, CALLEE),
                      blr()],
             CALLEE: [li(3, 7), blr()]})
    assert e.call(BASE) == 7
    assert e.reached(CALLEE)
    assert [t for _, t in e.calls] == [CALLEE]


def test_a_stub_replaces_the_callee_and_its_body_never_runs():
    e = emu({BASE:   [bl(BASE, CALLEE), blr()],
             CALLEE: [li(3, 7), blr()]}, trace=True)
    e.stub(CALLEE, 99)
    assert e.call(BASE) == 99
    assert e.reached(CALLEE)                     # the call site was seen ...
    assert not any(line.startswith("%08x" % CALLEE) for line in e.log)   # ... body was not


def test_a_stub_can_write_through_a_pointer_argument():
    """The out-param case: a callee whose result is what it writes, not what it returns."""
    out = ppcemu.SCRATCH + 0x100

    def fills_the_out_param(uc):
        from unicorn.ppc_const import UC_PPC_REG_4
        uc.mem_write(uc.reg_read(UC_PPC_REG_4), struct.pack(">I", 0xABCD))
        return 0

    e = emu({BASE: [bl(BASE, CALLEE), blr()], CALLEE: [li(3, 0), blr()]})
    e.stub(CALLEE, fills_the_out_param)
    e.call(BASE, [0, out])
    assert e.read_u32(out) == 0xABCD


def test_stub_all_isolates_a_function_except_what_you_exempt():
    other = BASE + 0x2000
    e = emu({BASE:   [stwu(1, -16, 1), mflr(0), stw(0, 20, 1),
                      bl(BASE + 0xC, CALLEE), bl(BASE + 0x10, other), blr()],
             CALLEE: [li(3, 1), blr()],
             other:  [li(3, 2), blr()]})
    e.stub_all = True
    e.stub_default = 0x55
    e.run_for_real = {other}
    assert e.call(BASE) == 2                      # `other` really ran; CALLEE was stubbed
    assert [t for _, t in e.calls] == [CALLEE, other]


def test_nopping_a_branch_changes_what_is_reached():
    """The pattern every patch in this repo relies on, in miniature."""
    guard = BASE + 0x10
    layout = {BASE: [stwu(1, -16, 1), mflr(0), stw(0, 20, 1), li(3, 0),
                     cmpwi(3, 0), beq(BASE + 0x14, BASE + 0x1C),   # skip the call
                     bl(BASE + 0x18, CALLEE),
                     blr()],
              CALLEE: [li(3, 123), blr()]}
    assert guard  # the beq sits at BASE+0x14

    stock = emu(dict(layout))
    stock.call(BASE)
    assert not stock.reached(CALLEE)

    patched = emu(dict(layout))
    patched.patch(BASE + 0x14, struct.pack(">I", nop()))
    patched.call(BASE)
    assert patched.reached(CALLEE)


# --- discovering what a function expects ------------------------------------

def test_unmapped_accesses_are_recorded_not_fatal():
    # lwz r3, 0(r3) from an address nothing has mapped
    e = emu({BASE: [0x80630000, blr()]})
    e.call(BASE, [0x12340000])
    assert e.error is None                       # a zero page was mapped instead
    assert any(kind == "read" and addr == 0x12340000 for kind, addr, _, _ in e.unmapped)


def test_call_sequence_renders_names_when_given_them():
    e = emu({BASE: [bl(BASE, CALLEE), blr()], CALLEE: [li(3, 0), blr()]})
    e.stub(CALLEE, 0)
    e.call(BASE)
    assert e.call_sequence({CALLEE: "DoTheThing"}) == ["DoTheThing"]


# --- BSS globals -------------------------------------------------------------

def test_bss_globals_can_be_mapped_and_seeded():
    """Globals past the end of the image are in no file — nothing is mapped there."""
    bss = BASE + 0x80000                       # beyond the image built below
    e = ppcemu.Emulator(image({BASE: [li(3, 0), blr()]}, size=0x1000))
    e.seed_u32(bss, 0xDEADBEEF)
    assert e.read_u32(bss) == 0xDEADBEEF


def test_mapping_an_already_mapped_region_is_harmless():
    e = emu({BASE: [blr()]})
    assert e.map(BASE, 4) == BASE              # the image is mapped already
    assert e.call(BASE) is not None


def test_an_unseeded_bss_global_reads_as_zero():
    """lwz r3, 0(r3) from BSS: the zero page stands in for uninitialised data."""
    e = ppcemu.Emulator(image({BASE: [0x80630000, blr()]}, size=0x1000))
    assert e.call(BASE, [BASE + 0x90000]) == 0
