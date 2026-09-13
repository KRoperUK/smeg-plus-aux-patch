#!/usr/bin/env python3
"""Inflate a SMEG+ AppBin/f_BigQuick.bin to the raw PowerPC application image.

f_BigQuick.bin is a 0x801-byte header followed by a zlib stream. The inflated
image is loaded at 0x01000000 and the release's Application/PKG/abs_symbols_base
map lines up with it, so addresses from the symbol map map 1:1 onto this file.

usage:
    python3 tools/unpack.py SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin app_nav.bin
"""
import argparse
import hashlib
import zlib


def inflate(raw):
    """Return (stream_offset, image_bytes)."""
    for start in (0x801, 0x800, 0x800 + 1):
        try:
            d = zlib.decompressobj()
            out = d.decompress(raw[start:])
            out += d.flush()
        except zlib.error:
            continue
        if len(out) > 0x100000:
            return start, out
    raise SystemExit("no zlib stream found (is this really an f_BigQuick.bin?)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="f_BigQuick.bin")
    ap.add_argument("output", help="raw application image to write")
    args = ap.parse_args()

    raw = open(args.input, "rb").read()
    start, img = inflate(raw)
    open(args.output, "wb").write(img)

    print("input           : %s (%d bytes)" % (args.input, len(raw)))
    print("zlib stream at  : %#x" % start)
    print("image           : %s (%d bytes / %#x)" % (args.output, len(img), len(img)))
    print("image crc32     : %#010x" % (zlib.crc32(img) & 0xffffffff))
    # a fingerprint for telling images apart, not a security primitive
    print("image sha1      : %s"
          % hashlib.sha1(img, usedforsecurity=False).hexdigest())
    print("load address    : 0x01000000  (symbol offsets = address - 0x01000000)")


if __name__ == "__main__":
    main()
