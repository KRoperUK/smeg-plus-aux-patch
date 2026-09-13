#!/usr/bin/env python3
"""Find code that references a string, address or pointer inside a SMEG+ image.

Two things are searched for:

  * literal 4-byte big-endian pointers to the target (data/vtable references), and
  * instruction sequences that materialise the target immediate - the
    `lis rX,hi ; addi/ori rX,rX,lo` idiom the compiler uses for addresses.

Give TARGET as a quoted string (its address is located first) or as 0xADDR.

usage:
    python3 tools/xref.py app_nav.bin abs_symbols_base.txt "Auxiliary_Input"
    python3 tools/xref.py app_nav.bin abs_symbols_base.txt 0x023031dc
"""

import argparse
import bisect
import struct
import sys


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
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("image")
    ap.add_argument("symbols")
    ap.add_argument("target")
    ap.add_argument("--base", default="0x01000000")
    args = ap.parse_args()

    base = int(args.base, 16)
    img = open(args.image, "rb").read()
    syms = load_symbols(args.symbols)
    addrs = sorted(syms)

    def name(a, tol=0x400):
        i = bisect.bisect_right(addrs, a) - 1
        if i >= 0 and a - addrs[i] <= tol and addrs[i] >= base:
            return syms[addrs[i]] + ("+0x%x" % (a - addrs[i]) if a - addrs[i] else "")
        return "?"

    try:
        target = int(args.target, 16) if args.target.lower().startswith("0x") else None
    except ValueError:
        target = None

    if target is None:
        off = img.find(args.target.encode())
        if off < 0:
            sys.exit("string not found: %r" % args.target)
        target = base + off
        print("string %r at %#x" % (args.target, target))
    else:
        print("target address %#x (%s)" % (target, name(target)))

    pat = struct.pack(">I", target)

    # 1. literal 4-byte pointers
    n = 0
    j = 0
    while True:
        j = img.find(pat, j)
        if j < 0:
            break
        print("  pointer   @ %#x  in %s" % (base + j, name(base + j)))
        j += 1
        n += 1

    # 2. lis + addi/ori materialisation
    words = struct.unpack(">%dI" % (len(img) // 4), img[: len(img) // 4 * 4])
    m = 0
    for i, w in enumerate(words):
        op = w >> 26
        if op not in (14, 24):  # addi / ori
            continue
        ra = (w >> 16) & 31
        imm = w & 0xFFFF
        if op == 14 and imm & 0x8000:
            imm -= 0x10000
        for k in range(1, 30):
            if i - k < 0:
                break
            pw = words[i - k]
            if (pw >> 26) == 15 and ((pw >> 21) & 31) == ra:  # lis ra,hi
                hi = (pw & 0xFFFF) << 16
                val = (hi | (imm & 0xFFFF)) if op == 24 else ((hi + imm) & 0xFFFFFFFF)
                if val == target:
                    print("  immediate @ %#x  in %s" % (base + i * 4, name(base + i * 4)))
                    m += 1
                break

    print("total: %d pointer(s), %d immediate site(s)" % (n, m))


if __name__ == "__main__":
    main()
