#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = ["unicorn>=2.0", "capstone>=5.0"]
# ///

"""Execute individual firmware functions on an emulated PowerPC core.

Every address in `patches/` was derived by reading disassembly, and every claim about
what a patch *does* was an inference from that reading. This runs the code instead.

The SMEG+ SoC is a Freescale MPC5121e — an e300 core, which is plain 32-bit PowerPC, so
Unicorn executes the shipped image directly. There is no attempt to boot the unit: no
VxWorks, no peripherals, no DBUS. One function is called at a time, with a stack and a
scratch region, and anything it calls is either executed too or stubbed with a value you
choose. That is enough to answer the question a patch actually raises — *does control
reach the code I think it reaches, and under which conditions* — which is otherwise a
question only a car can answer.

What it is good for:

  * proving a patch changes the path taken, and that an unpatched image does not;
  * finding the *other* conditions on that path, which is where the surprises are
    (see docs/EMULATION.md for the ones this found);
  * regression-testing a patch set without any hardware.

What it cannot tell you: whether the surrounding state is what the car really has. A stub
returning 0 is an assumption, not an observation. Reachability is proof; behaviour is not.

usage:
    python3 tools/unpack.py SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin app_nav.bin
    python3 tools/ppcemu.py app_nav.bin --call 0x02247858 --arg 0x60000000
    python3 tools/ppcemu.py app_nav.bin --call 0x02247858 --arg 0x60000000 \\
        --patches patches/aux-autoswitch.json --module NAV --trace
"""
import argparse
import json
import struct
import sys

BASE = 0x01000000
PAGE = 0x1000
STACK_TOP = 0x70000000
STACK_SIZE = 0x100000
SCRATCH = 0x60000000
SCRATCH_SIZE = 0x100000
RETURN_MAGIC = 0x0BADF00C      # 4-byte aligned; emulation stops when PC lands here


class EmuError(RuntimeError):
    pass


def _need(mod, what):
    try:
        return __import__(mod)
    except ImportError:                                      # pragma: no cover
        raise EmuError("%s is needed for %s — `pip install %s`" % (mod, what, mod))


class Emulator:
    """One firmware image, mapped and executable a function at a time.

    stubs map a callee address to either an int (its return value in r3) or a callable
    taking the Unicorn instance, for a callee that has to write through a pointer
    argument. `stub_all` stubs every call that is not listed in `run_for_real`, which is
    how you isolate a single function from the rest of the firmware.
    """

    def __init__(self, image, base=BASE, trace=False, max_calls=512):
        unicorn = _need("unicorn", "emulation")
        from unicorn import UC_ARCH_PPC, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_PROT_ALL
        from unicorn import UC_MODE_BIG_ENDIAN, UC_MODE_PPC32, Uc, UcError

        self._unicorn, self._UcError = unicorn, UcError
        self.image = bytearray(image)
        self.base = base
        self.trace = trace
        self.max_calls = max_calls

        self.calls = []          # (call_site, target) in order
        self.unmapped = []       # (kind, address, size, pc) — state the code expected
        self.log = []            # disassembly, when trace=True
        self.stubs = {}
        self.stub_all = False
        self.stub_default = 0
        self.run_for_real = set()
        self.error = None

        self.uc = uc = Uc(UC_ARCH_PPC, UC_MODE_PPC32 | UC_MODE_BIG_ENDIAN)
        uc.mem_map(base, (len(self.image) + PAGE - 1) & ~(PAGE - 1), UC_PROT_ALL)
        uc.mem_write(base, bytes(self.image))
        uc.mem_map(STACK_TOP - STACK_SIZE, STACK_SIZE * 2, UC_PROT_ALL)
        uc.mem_map(SCRATCH, SCRATCH_SIZE, UC_PROT_ALL)
        uc.mem_map(RETURN_MAGIC & ~(PAGE - 1), PAGE, UC_PROT_ALL)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        uc.hook_add(UC_HOOK_CODE, self._on_code)
        self._md = None
        if trace:
            capstone = _need("capstone", "tracing")
            self._md = capstone.Cs(capstone.CS_ARCH_PPC,
                                   capstone.CS_MODE_32 | capstone.CS_MODE_BIG_ENDIAN)

    # -- setup -------------------------------------------------------------

    def patch(self, addr, raw):
        """Apply a patch in memory. Accepts hex text or bytes, as patches/*.json does.

        The translation cache has to be dropped for the range: Unicorn keeps compiled
        blocks, so an image patched after a call would otherwise keep running the code it
        had before, silently.
        """
        if isinstance(raw, str):
            raw = bytes.fromhex(raw)
        self.image[addr - self.base:addr - self.base + len(raw)] = raw
        self.uc.mem_write(addr, raw)
        try:
            self.uc.ctl_remove_cache(addr, addr + len(raw) + 4)
        except (AttributeError, self._UcError):        # older unicorn: no cache control
            pass

    def apply_patch_file(self, path, module):
        """Apply one variant of a patches/*.json definition, checking `expect` first."""
        spec = json.load(open(path))
        variant = spec["variants"][module]
        for p in variant["patches"]:
            addr = int(p["addr"], 16)
            expect = p.get("expect")
            if expect:
                want = bytes.fromhex(expect)
                got = bytes(self.uc.mem_read(addr, len(want)))
                if got != want:
                    raise EmuError("%08x: expected %s, found %s — wrong image or already "
                                   "patched" % (addr, expect, got.hex()))
            self.patch(addr, p["bytes"])
        return variant

    def stub(self, addr, behaviour=0):
        self.stubs[addr] = behaviour

    def write(self, addr, raw):
        self.uc.mem_write(addr, raw)

    def read(self, addr, size):
        return bytes(self.uc.mem_read(addr, size))

    def read_u32(self, addr):
        return struct.unpack(">I", self.read(addr, 4))[0]

    def write_u32(self, addr, value):
        self.uc.mem_write(addr, struct.pack(">I", value & 0xFFFFFFFF))

    # -- hooks -------------------------------------------------------------

    def _on_unmapped(self, uc, access, address, size, value, _ctx):
        from unicorn import UC_MEM_FETCH_UNMAPPED, UC_MEM_READ_UNMAPPED
        from unicorn import UC_MEM_WRITE_UNMAPPED, UC_PROT_ALL
        kind = {UC_MEM_READ_UNMAPPED: "read", UC_MEM_WRITE_UNMAPPED: "write",
                UC_MEM_FETCH_UNMAPPED: "fetch"}.get(access, str(access))
        self.unmapped.append((kind, address, size, uc.reg_read(self._reg("PC"))))
        if kind == "fetch":
            return False                    # a real jump into nothing: let it stop
        try:                                # otherwise map a zero page and carry on,
            uc.mem_map(address & ~(PAGE - 1), PAGE, UC_PROT_ALL)   # recording what it
        except self._UcError:               # wanted — that list is the function's
            pass                            # unstated dependency on machine state
        return True

    def _on_code(self, uc, address, size, _ctx):
        if address == RETURN_MAGIC:
            uc.emu_stop()
            return
        if self._md is not None:
            for insn in self._md.disasm(bytes(uc.mem_read(address, size)), address):
                self.log.append("%08x  %-8s %s" % (insn.address, insn.mnemonic, insn.op_str))
        target = self._call_target(uc, address)
        if target is None:
            return
        self.calls.append((address, target))
        if len(self.calls) > self.max_calls:
            uc.emu_stop()
            return
        stubbed = target in self.stubs or (self.stub_all and target not in self.run_for_real)
        if not stubbed:
            return
        behaviour = self.stubs.get(target, self.stub_default)
        result = behaviour(uc) if callable(behaviour) else behaviour
        uc.reg_write(self._reg("3"), (result or 0) & 0xFFFFFFFF)
        uc.reg_write(self._reg("PC"), address + 4)       # skip the call entirely
        uc.reg_write(self._reg("LR"), address + 4)

    def _call_target(self, uc, address):
        """The target of a `bl` or `bctrl` at address, or None if it is not a call."""
        word = struct.unpack(">I", bytes(uc.mem_read(address, 4)))[0]
        op = word >> 26
        if op == 18 and (word & 1):                               # bl / bla
            offset = word & 0x03FFFFFC
            if offset & 0x02000000:
                offset -= 0x04000000
            return (offset if (word & 2) else address + offset) & 0xFFFFFFFF
        if op == 19 and ((word >> 1) & 0x3FF) == 528 and (word & 1):   # bctrl
            return uc.reg_read(self._reg("CTR"))
        return None

    def _reg(self, name):
        from unicorn import ppc_const
        return getattr(ppc_const, "UC_PPC_REG_%s" % name)

    # -- running -----------------------------------------------------------

    def call(self, addr, args=(), max_insns=200000, timeout=10_000_000):
        """Call a function. Returns r3. Stops when it returns, faults or runs too long."""
        uc = self.uc
        sp = STACK_TOP - 0x1000
        uc.mem_write(sp - 0x800, b"\x00" * 0x1000)        # a clean frame each time
        uc.reg_write(self._reg("1"), sp)
        uc.reg_write(self._reg("LR"), RETURN_MAGIC)
        for i, value in enumerate(args):
            if i > 7:
                raise EmuError("more than 8 register arguments is not supported")
            uc.reg_write(self._reg(str(3 + i)), value & 0xFFFFFFFF)
        self.error = None
        try:
            uc.emu_start(addr, RETURN_MAGIC, timeout=timeout, count=max_insns)
        except self._UcError as exc:
            self.error = str(exc)
        return uc.reg_read(self._reg("3"))

    def reached(self, target):
        return any(t == target for _, t in self.calls)

    def call_sequence(self, names=None):
        names = names or {}
        return [names.get(t, "%08x" % t) for _, t in self.calls]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", help="raw image from tools/unpack.py")
    ap.add_argument("--base", default=hex(BASE), help="load address (default 0x01000000)")
    ap.add_argument("--call", required=True, help="function address to call")
    ap.add_argument("--arg", action="append", default=[], help="register argument (repeatable)")
    ap.add_argument("--patches", help="a patches/*.json to apply first")
    ap.add_argument("--module", default="NAV", help="which variant of --patches to apply")
    ap.add_argument("--stub-all", action="store_true",
                    help="stub every call instead of executing it")
    ap.add_argument("--stub", action="append", default=[],
                    help="ADDR=VALUE — stub one callee's return value (repeatable)")
    ap.add_argument("--trace", action="store_true", help="print the instructions executed")
    args = ap.parse_args()

    base = int(args.base, 0)
    emu = Emulator(open(args.image, "rb").read(), base=base, trace=args.trace)
    if args.patches:
        emu.apply_patch_file(args.patches, args.module)
        print("applied %s (%s)" % (args.patches, args.module))
    emu.stub_all = args.stub_all
    for item in args.stub:
        addr, _, value = item.partition("=")
        emu.stub(int(addr, 0), int(value or 0, 0))

    r3 = emu.call(int(args.call, 0), [int(a, 0) for a in args.arg])
    if args.trace:
        print("\n".join(emu.log))
    print("r3          : 0x%08x (%d)" % (r3, struct.unpack(">i", struct.pack(">I", r3))[0]))
    print("instructions: %d" % len(emu.log) if args.trace
          else "instructions: (use --trace)")
    print("calls       : %s" % (", ".join("%08x" % t for _, t in emu.calls) or "none"))
    if emu.unmapped:
        print("unmapped    : %s" % ", ".join(
            "%s@%08x" % (k, a) for k, a, _, _ in emu.unmapped[:8]))
    if emu.error:
        print("stopped     : %s" % emu.error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
