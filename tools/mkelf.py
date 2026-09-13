#!/usr/bin/env python3
"""Wrap a raw SMEG+ application image plus its symbol map into a disassemblable ELF.

Some disassemblers (and debuggers) want a real ELF rather than a flat image. This
produces an ELF32 big-endian PowerPC executable whose .text holds the image at its
load address, with the symbol map attached.

usage:
    python3 tools/mkelf.py app_nav.bin abs_symbols_base.txt app_nav.elf
    objdump -d app_nav.elf            # any PPC-capable objdump / llvm-objdump
"""

import argparse
import bisect
import struct

SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4


def align(x, n):
    return (x + n - 1) // n * n


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("image")
    ap.add_argument("symbols")
    ap.add_argument("output")
    ap.add_argument("--base", default="0x01000000")
    args = ap.parse_args()

    base = int(args.base, 16)
    img = open(args.image, "rb").read()

    raw = {}
    for line in open(args.symbols, "r", errors="replace"):
        p = line.split()
        if len(p) >= 3:
            try:
                raw[int(p[0], 16)] = (p[2], p[1])
            except ValueError:
                pass
    addrs = sorted(raw)

    def size(a):
        i = bisect.bisect_right(addrs, a)
        return (addrs[i] - a) if i < len(addrs) else 4

    types = {
        "T": 0x12,
        "t": 0x02,
        "W": 0x12,
        "w": 0x02,
        "D": 0x11,
        "d": 0x01,
        "B": 0x11,
        "b": 0x01,
        "R": 0x11,
        "r": 0x01,
        "V": 0x11,
        "v": 0x01,
        "A": 0x10,
    }

    shstr = b"\x00.text\x00.symtab\x00.strtab\x00.shstrtab\x00"

    def shoff(n):
        return shstr.index(n.encode())

    strtab = bytearray(b"\x00")
    seen = {}

    def addsym(s):
        if s not in seen:
            seen[s] = len(strtab)
            strtab.extend(s.encode() + b"\x00")
        return seen[s]

    syms = [struct.pack(">IIIBBH", 0, 0, 0, 0, 0, 0)]
    for a in addrs:
        nm, typ = raw[a]
        syms.append(struct.pack(">IIIBBH", addsym(nm), a, size(a), types.get(typ, 0x10), 0, 1))
    symdata = b"".join(syms)

    text_off = 0x1000
    symtab_off = align(text_off + len(img), 16)
    strtab_off = symtab_off + len(symdata)
    shstr_off = align(strtab_off + len(strtab), 4)
    shtab_off = align(shstr_off + len(shstr), 4)

    def sec(name, typ, flags, addr, off, size, link, info, al, ent):
        return struct.pack(">IIIIIIIIII", name, typ, flags, addr, off, size, link, info, al, ent)

    sh = b"".join(
        [
            sec(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            sec(shoff(".text"), 1, SHF_ALLOC | SHF_EXECINSTR, base, text_off, len(img), 0, 0, 4, 0),
            sec(shoff(".symtab"), 2, 0, 0, symtab_off, len(symdata), 3, 1, 4, 16),
            sec(shoff(".strtab"), 3, 0, 0, strtab_off, len(strtab), 0, 0, 1, 0),
            sec(shoff(".shstrtab"), 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0),
        ]
    )

    ident = b"\x7fELF" + bytes([1, 2, 1, 0]) + bytes(8)
    ehdr = ident + struct.pack(
        ">HHIIIIIHHHHHH", 2, 20, 1, base, 0, shtab_off, 0, 52, 32, 0, 40, 5, 4
    )

    out = bytearray(ehdr)
    out += b"\x00" * (text_off - len(out))
    out += img
    out += b"\x00" * (symtab_off - len(out))
    out += symdata
    out += strtab
    out += b"\x00" * (shstr_off - len(out))
    out += shstr
    out += b"\x00" * (shtab_off - len(out))
    out += sh
    open(args.output, "wb").write(out)
    print("wrote %s (%d bytes, %d symbols, base %#x)" % (args.output, len(out), len(addrs), base))


if __name__ == "__main__":
    main()
