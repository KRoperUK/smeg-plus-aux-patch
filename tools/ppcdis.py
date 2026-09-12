#!/usr/bin/env python3
"""PowerPC (32-bit, big-endian) disassembler for SMEG+ application images.

Resolves symbols from an absolute symbol map (e.g. Application/PKG/abs_symbols_base.txt)
and annotates indirect calls made through the `lis/addi -> mtctr -> bctrl` idiom that
the compiler emits, so `bctrl` shows the callee name.

usage:
    python3 tools/ppcdis.py IMAGE SYMFILE ADDRESS END
    python3 tools/ppcdis.py app_nav.bin abs_symbols_base.txt 0x0230331c 0x02303460
"""
import argparse
import bisect
import sys

try:
    from capstone import CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
    from capstone.ppc import PPC_OP_IMM, PPC_OP_REG
except ImportError:
    sys.exit("capstone is required:  pip install capstone")


def load_symbols(path):
    syms = {}
    for line in open(path, "r", errors="replace"):
        p = line.split()
        if len(p) >= 3:
            try:
                syms[int(p[0], 16)] = p[2]
            except ValueError:
                pass
    return syms


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("symbols")
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--base", default="0x01000000")
    args = ap.parse_args()

    base = int(args.base, 16)
    start, end = int(args.start, 16), int(args.end, 16)
    img = open(args.image, "rb").read()
    syms = load_symbols(args.symbols)
    addrs = sorted(syms)

    def name(a, tol=0x100):
        if a in syms:
            return syms[a]
        i = bisect.bisect_right(addrs, a) - 1
        if i >= 0 and a - addrs[i] <= tol:
            return "%s+0x%x" % (syms[addrs[i]], a - addrs[i])
        return "0x%x" % a

    md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    md.detail = True

    regs, ctr, lr = {}, None, None
    for ins in md.disasm(img[start - base:end - base], start):
        m, ops = ins.mnemonic, ins.op_str
        o = ins.operands
        ann = ""
        if m == "lis" and len(o) == 2 and o[1].type == PPC_OP_IMM:
            regs[o[0].reg] = o[1].imm << 16
        elif m == "addi" and len(o) == 3 and o[1].type == PPC_OP_REG and o[2].type == PPC_OP_IMM:
            b = regs.get(o[1].reg)
            if b is not None:
                regs[o[0].reg] = (b + o[2].imm) & 0xffffffff
        elif m == "ori" and len(o) == 3 and o[1].type == PPC_OP_REG and o[2].type == PPC_OP_IMM:
            b = regs.get(o[1].reg)
            if b is not None:
                regs[o[0].reg] = b | o[2].imm
        elif m == "mtctr" and len(o) == 1:
            ctr = regs.get(o[0].reg)
        elif m == "mtlr" and len(o) == 1:
            lr = regs.get(o[0].reg)
        elif m in ("bctrl", "bcctrl", "blrl"):
            t = lr if m == "blrl" else ctr
            if t:
                ann = "  ; call %s" % name(t)
        elif m in ("b", "bl", "ba", "bla") and o and o[-1].type == PPC_OP_IMM:
            ann = "  ; -> %s" % name(o[-1].imm)
        elif m.startswith("bc") and o and o[-1].type == PPC_OP_IMM:
            ann = "  ; -> %s" % name(o[-1].imm)
        print("  %08x: %-9s %-34s%s" % (ins.address, m, ops, ann))


if __name__ == "__main__":
    main()
