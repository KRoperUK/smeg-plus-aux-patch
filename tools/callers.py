#!/usr/bin/env python3
"""Find direct (bl) callers of one or more addresses in a SMEG+ PPC image.

Only direct branches are found; virtual calls and calls made through function
pointers (`bctrl`) are not, which is normal for C++ code.

usage:
    python3 tools/callers.py app_nav.bin abs_symbols_base.txt 0x02324928
"""

import argparse
import bisect
import struct


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
    ap.add_argument("targets", nargs="+", help="addresses to look for callers of")
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

    words = struct.unpack(">%dI" % (len(img) // 4), img[: len(img) // 4 * 4])
    index = {}
    for i, w in enumerate(words):
        if (w & 0xFC000003) == 0x48000001:  # bl
            off = w & 0x03FFFFFC
            if off & 0x02000000:
                off -= 0x04000000
            tgt = base + i * 4 + off
            index.setdefault(tgt, []).append(base + i * 4)

    for t in args.targets:
        t = int(t, 16)
        cs = index.get(t, [])
        print("callers of %#x (%s): %d" % (t, name(t), len(cs)))
        for c in cs[:40]:
            print("    %#x  %s" % (c, name(c)))


if __name__ == "__main__":
    main()
