#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Read the symbol tables the SMEG+ package ships in plain sight.

`upgrade.out`, `UpgPlugin.out` and `upgrade_lib.out` in the package root are **unstripped
PowerPC ELF objects**. Between them they name the entire USB update flow — `upgrade.out`
alone carries 2171 functions, 117 of them methods of `C_UPGRADE`. Work that has been done
here by matching log strings can be done by reading the symbol table instead.

Nothing about this needs the application image or its absent `abs_symbols_base.txt.gz`;
these are different binaries, for the updater rather than the head-unit application.

usage:
    python3 tools/elfsyms.py SMEG_PLUS_UPG/upgrade.out
    python3 tools/elfsyms.py SMEG_PLUS_UPG/upgrade.out --grep ZA
    python3 tools/elfsyms.py SMEG_PLUS_UPG/upgrade.out --class C_UPGRADE
    python3 tools/elfsyms.py SMEG_PLUS_UPG/upgrade.out --strings Phase
"""

import argparse
import re
import struct
import sys

STT_OBJECT, STT_FUNC, STT_SECTION = 1, 2, 3
SYM_ENTRY = 16


class ElfError(ValueError):
    pass


class Elf32BE:
    """Just enough ELF32 big-endian to read sections, symbols and string literals."""

    def __init__(self, blob):
        if blob[:4] != b"\x7fELF":
            raise ElfError("not an ELF file")
        if blob[4] != 1 or blob[5] != 2:
            raise ElfError("not 32-bit big-endian (this is a PowerPC target)")
        self.blob = blob
        (
            self.e_type,
            self.e_machine,
            _,
            self.e_entry,
            _,
            self.e_shoff,
            _,
            _,
            _,
            _,
            self.e_shentsize,
            self.e_shnum,
            self.e_shstrndx,
        ) = struct.unpack_from(">HHIIIIIHHHHHH", blob, 16)
        self.sections = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            (name, stype, flags, addr, offset, size, link, info, align, entsize) = (
                struct.unpack_from(">IIIIIIIIII", blob, off)
            )
            self.sections.append(
                dict(
                    name_off=name,
                    type=stype,
                    addr=addr,
                    offset=offset,
                    size=size,
                    link=link,
                    entsize=entsize,
                    index=i,
                )
            )
        shstr = self.sections[self.e_shstrndx]
        for s in self.sections:
            s["name"] = self._cstr(shstr["offset"] + s["name_off"])

    # -- helpers -----------------------------------------------------------

    def _cstr(self, at):
        end = self.blob.index(b"\x00", at)
        return self.blob[at:end].decode("latin1")

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None

    # -- the interesting parts ---------------------------------------------

    def symbols(self):
        out = []
        for sec in self.sections:
            if sec["type"] != 2:  # SHT_SYMTAB
                continue
            strtab = self.sections[sec["link"]]
            for i in range(sec["size"] // SYM_ENTRY):
                off = sec["offset"] + i * SYM_ENTRY
                name, value, size, info, other, shndx = struct.unpack_from(
                    ">IIIBBH", self.blob, off
                )
                out.append(
                    dict(
                        name=self._cstr(strtab["offset"] + name),
                        value=value,
                        size=size,
                        type=info & 0xF,
                        bind=info >> 4,
                        shndx=shndx,
                    )
                )
        return out

    def functions(self):
        return sorted(
            (s for s in self.symbols() if s["type"] == STT_FUNC), key=lambda s: s["value"]
        )

    def literals(self, section=".text", minlen=4, maxlen=160, skip_code=True):
        """String literals, which these objects keep at the tail of .text, not in .rodata.

        Two filters keep instruction bytes out, because code and literals are interleaved
        in these objects rather than split into a .rodata:

        * a run must start at a NUL boundary, or at the start of the section;
        * with `skip_code`, a run that falls inside a function's extent is dropped — the
          symbol table knows where every function starts and how long it is, which is the
          one thing plain `strings` cannot use.

        Neither is perfect: `blr` is `4e 80 00 20`, so a literal immediately after one can
        still pick up a leading space.
        """
        extents = []
        if skip_code:
            extents = sorted(
                (f["value"], f["value"] + f["size"]) for f in self.functions() if f["size"]
            )
        sec = self.section(section)
        if sec is None:
            return []
        blob = self.blob[sec["offset"] : sec["offset"] + sec["size"]]
        out = []
        for m in re.finditer(rb"[\x20-\x7e]{%d,%d}\x00" % (minlen, maxlen), blob):
            if m.start() and blob[m.start() - 1] != 0:
                continue
            addr = sec["addr"] + m.start()
            if any(lo <= addr < hi for lo, hi in extents):
                continue
            out.append((addr, m.group()[:-1].decode("ascii")))
        return out

    def owner_of(self, addr):
        """Which function contains this address."""
        best = None
        for f in self.functions():
            if f["value"] <= addr:
                best = f
            else:
                break
        return best


def demangle(name):
    """Enough Itanium demangling for `_ZN<len><Class><len><method>E...` — the shape these use."""
    m = re.match(r"^_ZN(\d+)(.+)$", name)
    if not m:
        return name
    rest, parts = name[3:], []
    while rest:
        lm = re.match(r"^(\d+)", rest)
        if not lm:
            break
        n = int(lm.group(1))
        start = lm.end()
        parts.append(rest[start : start + n])
        rest = rest[start + n :]
    if not parts:
        return name
    tail = "()" if rest.startswith("Ev") else "(…)"
    return "::".join(parts) + tail


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf", help="an .out from the package root")
    ap.add_argument("--grep", help="only symbols whose name contains this (case-insensitive)")
    ap.add_argument(
        "--cls", "--class", dest="cls", help="only methods of this C++ class, in address order"
    )
    ap.add_argument(
        "--strings",
        nargs="?",
        const="",
        metavar="MATCH",
        help="list string literals instead, optionally filtered",
    )
    ap.add_argument("--raw", action="store_true", help="do not demangle")
    args = ap.parse_args()

    try:
        with open(args.elf, "rb") as fh:
            elf = Elf32BE(fh.read())
    except (ElfError, OSError) as exc:
        sys.exit("%s: %s" % (args.elf, exc))

    syms = elf.symbols()
    funcs = [s for s in syms if s["type"] == STT_FUNC]
    print(
        "%s: %d sections, %d symbols, %d functions"
        % (args.elf, len(elf.sections), len(syms), len(funcs))
    )
    print(
        "sections: %s"
        % ", ".join("%s(%d)" % (s["name"], s["size"]) for s in elf.sections if s["size"])
    )

    if args.strings is not None:
        lits = [
            (a, s)
            for a, s in elf.literals()
            if not args.strings or args.strings.lower() in s.lower()
        ]
        print(
            "\n%d string literals%s:"
            % (len(lits), " matching %r" % args.strings if args.strings else "")
        )
        for addr, s in lits[:400]:
            print("  %08x  %r" % (addr, s))
        return 0

    if args.cls:
        prefix = "_ZN%d%s" % (len(args.cls), args.cls)
        hits = sorted((s for s in funcs if s["name"].startswith(prefix)), key=lambda s: s["value"])
        print("\n%s: %d methods, in address order:" % (args.cls, len(hits)))
    else:
        hits = sorted(funcs, key=lambda s: s["value"])
        if args.grep:
            hits = [s for s in hits if args.grep.lower() in s["name"].lower()]
        print("\n%d functions%s:" % (len(hits), " matching %r" % args.grep if args.grep else ""))
    for s in hits[:600]:
        print("  %08x  %s" % (s["value"], s["name"] if args.raw else demangle(s["name"])))
    if len(hits) > 600:
        print("  … %d more (narrow it with --grep)" % (len(hits) - 600))
    return 0


if __name__ == "__main__":
    sys.exit(main())
