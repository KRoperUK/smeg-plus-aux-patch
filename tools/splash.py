#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Brand logo images for SMEG+ — inspect and replace the `Data_base/graphics/logo/*.pkg` bundles.

Despite the name these are NOT the boot splash. Flashing a replaced one leaves the factory
animation untouched: nothing in the application image references these files, and the boot
artwork lives in a separate NAND "Logo Area" that the USB update flow has no step for. See
docs/MEDIA_PARTITION.md. These images are real marque artwork used elsewhere; that use is
still unidentified, so treat their effect on the unit as unknown.

`Data_base/graphics/logo/` holds one `.pkg` per marque (`peugeot`, `citroen`, `ds`). Each is a
small container holding four 800x480 24-bit images, the first of which is the boot
splash — the Peugeot lion and wordmark that appears while the unit starts.

Container layout (verified against the shipped packages):

    0x0000  u32   crc32 of bytes 0x0004..0x0800        (directory integrity)
    0x0004  u32   size of the first chunk, as the offset of the next chunk from 0x0800
    0x0008  u32   uncompressed size of every chunk (800*480*3 + 54 = 1152054)
    0x000c  u32   0
    0x0010  ...   directory records, zero-padded to 0x0800
    ...

Each directory record is a 32-byte NUL-padded name followed by 6 or 7 big-endian u32s; the
last two carry the offset of the *next* chunk's marker byte and that chunk's length + 3.

The data region runs from 0x0800. Every chunk is:

    u8  0x08 marker
    ... a standard zlib stream (deflate level 6) holding one 800x480 24-bit BMP
    u16 an unidentified two-byte trailer, preserved verbatim

The BMPs are ordinary bottom-up 24-bit BMPs, but they are stored **vertically mirrored**:
read with normal BMP semantics the artwork is upside down. That matches the car, where the
splash displays correctly, so the unit flips it when rendering. To make a replacement
display the right way up it must therefore be stored flipped — `replace` does that for you.

Known unknown: the two-byte trailer after each zlib stream has not been identified (it is
not a crc32 or adler32 fragment of the chunk). It is preserved as-is, and a rebuilt package
has not yet been flashed, so treat a replaced splash as unverified until a unit accepts it.

usage:
    python3 tools/splash.py list --tree media/
    python3 tools/splash.py extract --tree media/ -o splash/ --marque peugeot
    python3 tools/splash.py replace --tree media/ --marque peugeot --image mine.png
    python3 tools/splash.py selftest --tree media/
"""
import argparse
import os
import struct
import sys
import zlib

DIR = "Data_base/graphics/logo"
MARQUES = ("peugeot", "citroen", "ds")
HEADER = 0x800
MARKER = 0x08
IMAGE_W, IMAGE_H = 800, 480
BMP_SIZE = IMAGE_W * IMAGE_H * 3 + 54


def die(msg):
    sys.exit("splash: " + msg)


def _roundup(n, m):
    return (n + m - 1) // m * m


class Chunk:
    """One embedded image: where its marker, zlib stream and trailer live."""

    def __init__(self, index, marker_off, data_off, length, trailer_off, trailer):
        self.index = index
        self.marker_off = marker_off
        self.data_off = data_off
        self.length = length          # length of the zlib stream
        self.trailer_off = trailer_off
        self.trailer = trailer

    @property
    def end(self):
        return self.trailer_off + len(self.trailer)


class Pkg:
    def __init__(self, raw):
        self.raw = raw
        self.hash, self.chunk0_size, self.usize, self.zero = struct.unpack_from(">4I", raw, 0)
        self.records = self._records()
        self.chunks = self._chunks()

    # -- directory -----------------------------------------------------------
    @staticmethod
    def _is_name(buf):
        head = buf.split(b"\x00")[0]
        return bool(head) and b"." in head and all(32 <= c < 127 for c in head)

    def _records(self):
        out = []
        off = 0x10
        while off + 32 <= HEADER and self._is_name(self.raw[off:off + 32]):
            fields = []
            p = off + 32
            while p + 32 <= HEADER and not self._is_name(self.raw[p:p + 32]):
                fields.append(struct.unpack_from(">I", self.raw, p)[0])
                p += 4
            out.append((off, self.raw[off:off + 32].split(b"\x00")[0].decode(), fields))
            off = p
        return out

    # -- data region ---------------------------------------------------------
    def _chunks(self):
        chunks = []
        pos = HEADER
        idx = 0
        while pos < len(self.raw):
            if self.raw[pos] != MARKER:
                break
            marker_off = pos
            data_off = pos + 1
            if data_off + 2 > len(self.raw):
                break
            do = zlib.decompressobj()
            try:
                do.decompress(self.raw[data_off:])
            except zlib.error:
                break
            length = len(self.raw) - data_off - len(do.unused_data)
            if length <= 0:
                break
            trailer_off = data_off + length
            trailer = self.raw[trailer_off:trailer_off + 2]
            chunks.append(Chunk(idx, marker_off, data_off, length, trailer_off, trailer))
            pos = trailer_off + len(trailer)
            idx += 1
        return chunks

    def image(self, i):
        c = self.chunks[i]
        return zlib.decompress(self.raw[c.data_off:c.data_off + c.length])

    def check_hash(self):
        return (zlib.crc32(self.raw[4:HEADER]) & 0xffffffff) == self.hash


# -- BMP helpers -------------------------------------------------------------
def flip_bmp(bmp):
    """Vertically mirror a bottom-up 24-bit BMP, preserving the header."""
    if len(bmp) != BMP_SIZE:
        die("expected a %d-byte 800x480 24-bit BMP, got %d bytes" % (BMP_SIZE, len(bmp)))
    magic, fsize, r1, r2, pixoff = struct.unpack_from("<2sIHHI", bmp, 0)
    if magic != b"BM":
        die("not a BMP")
    dib, w, h = struct.unpack_from("<Iii", bmp, 14)
    bpp = struct.unpack_from("<H", bmp, 28)[0]
    if (w, h, bpp, dib) != (IMAGE_W, IMAGE_H, 24, 40):
        die("expected 800x480 24-bit, uncompressed; got %dx%d %dbpp dib=%d" % (w, h, bpp, dib))
    stride = _roundup(w * 3, 4)
    body = bmp[pixoff:]
    rows = [body[i * stride:(i + 1) * stride] for i in range(len(body) // stride)]
    return bmp[:pixoff] + b"".join(reversed(rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", default="media",
                    help="an extracted media partition (contains %s/)" % DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="show the images in each marque's package")
    p = sub.add_parser("extract", help="write the images out as BMP")
    p.add_argument("--marque", default="peugeot", choices=MARQUES)
    p.add_argument("-o", "--out", default="splash")
    p = sub.add_parser("replace", help="replace an image and rebuild the package")
    p.add_argument("--marque", default="peugeot", choices=MARQUES)
    p.add_argument("--image", required=True, help="new 800x480 24-bit image (any format ffmpeg reads)")
    p.add_argument("--index", type=int, default=0, help="which image to replace (default 0 = the main marque image)")
    p.add_argument("--out", help="write here instead of in place")
    p = sub.add_parser("selftest", help="rebuild from the stock images and compare")

    args = ap.parse_args()

    def load(marque):
        path = os.path.join(args.tree, DIR, marque + ".pkg")
        if not os.path.exists(path):
            die("no such package: %s" % path)
        return path, Pkg(open(path, "rb").read())

    if args.cmd == "list":
        for m in MARQUES:
            path = os.path.join(args.tree, DIR, m + ".pkg")
            if not os.path.exists(path):
                continue
            pk = Pkg(open(path, "rb").read())
            print("%s.pkg  (%d bytes, %d images, directory hash %s)"
                  % (m, os.path.getsize(path), len(pk.chunks),
                     "ok" if pk.check_hash() else "MISMATCH"))
            for o, name, f in pk.records:
                extra = ""
                if len(f) >= 2 and f[-2]:
                    extra = "   data to 0x%x" % f[-2]
                print("    %-24s %s%s" % (name, " ".join("%08x" % x for x in f[:2]), extra))
        return

    if args.cmd == "selftest":
        ok = True
        for m in MARQUES:
            path, pk = load(m)
            for i in range(len(pk.chunks)):
                img = pk.image(i)
                if len(img) != BMP_SIZE:
                    print("  %s[%d]: unexpected size %d" % (m, i, len(img)))
                    ok = False
            rebuild = build(pk, {i: pk.image(i) for i in range(len(pk.chunks))}, reuse_compressed=True)
            same = rebuild == pk.raw
            print("  %-8s %d images, hash %s, byte-identical rebuild: %s"
                  % (m, len(pk.chunks), "ok" if pk.check_hash() else "BAD",
                     "YES" if same else "NO"))
            ok &= same
            if not same and len(rebuild) == len(pk.raw):
                diff = [i for i in range(len(rebuild)) if rebuild[i] != pk.raw[i]]
                print("       %d differing bytes, first at 0x%x" % (len(diff), diff[0]))
        sys.exit(0 if ok else 1)

    if args.cmd == "extract":
        path, pk = load(args.marque)
        os.makedirs(args.out, exist_ok=True)
        for o, name, f in pk.records:
            pass
        for i, c in enumerate(pk.chunks):
            tag = pk.records[i][1] if i < len(pk.records) else "image%d.bmp" % i
            dest = os.path.join(args.out, tag)
            open(dest, "wb").write(pk.image(i))
            print("  %-24s -> %s (%d bytes)" % (tag, dest, len(pk.image(i))))
        print("note: the stored images are vertically mirrored; flip them to see them upright")
        return

    if args.cmd == "replace":
        path, pk = load(args.marque)
        bmp = to_bmp(args.image)
        if args.index < 0 or args.index >= len(pk.chunks):
            die("--index %d out of range (0..%d)" % (args.index, len(pk.chunks) - 1))
        new = {i: pk.image(i) for i in range(len(pk.chunks))}
        new[args.index] = flip_bmp(bmp)          # store mirrored, as the unit expects
        out = build(pk, new)
        dest = args.out or path
        if os.path.abspath(dest) != os.path.abspath(path) and os.path.exists(dest):
            die("refusing to overwrite %s" % dest)
        before = len(pk.raw)
        open(dest, "wb").write(out)
        print("replaced image %d in %s" % (args.index, dest))
        print("  %d -> %d bytes" % (before, len(out)))
        print("  NOTE: unverified on a unit — the two-byte chunk trailer is preserved as-is")
        return


def to_bmp(src):
    """Convert anything ffmpeg reads into the exact 800x480 24-bit bottom-up BMP."""
    import shutil
    import subprocess
    if src.lower().endswith(".bmp"):
        d = open(src, "rb").read()
        if len(d) == BMP_SIZE:
            return d
    if not shutil.which("ffmpeg"):
        die("ffmpeg is required to convert %s" % src)
    tmp = os.path.splitext(src)[0] + ".splash.bmp"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                        "-vf", "scale=%d:%d" % (IMAGE_W, IMAGE_H),
                        "-pix_fmt", "bgr24", tmp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("ffmpeg failed: %s" % (r.stderr.strip() or r.stdout.strip()))
    d = open(tmp, "rb").read()
    os.unlink(tmp)
    if len(d) != BMP_SIZE:
        die("conversion produced %d bytes, expected %d" % (len(d), BMP_SIZE))
    return d


def _patch_u32(buf, start, end, old, new, what):
    """Replace the single big-endian u32 equal to `old` within buf[start:end]."""
    if old == new:
        return
    hits = [p for p in range(start, end - 3, 4) if struct.unpack_from(">I", buf, p)[0] == old]
    if len(hits) != 1:
        die("expected one %s == 0x%x in the directory, found %d" % (what, old, len(hits)))
    struct.pack_into(">I", buf, hits[0], new)


def build(pk, images, reuse_compressed=False):
    """Rebuild the .pkg with the given images (index -> BMP bytes).

    The directory's u32 fields are only partly understood, so they are not rewritten from
    scratch: the values we do know — each chunk's offset and total size, and the first
    chunk's size in the header — are located by value and updated in place. Everything else
    is carried over untouched, and the leading crc32 is recomputed last.
    """
    chunks = []
    for i, c in enumerate(pk.chunks):
        comp = (pk.raw[c.data_off:c.data_off + c.length] if reuse_compressed
                else zlib.compress(images[i], 6))
        chunks.append((comp, c.trailer))
    if not chunks:
        die("no chunks to write")

    old_tot = [1 + c.length + len(c.trailer) for c in pk.chunks]
    new_off, new_tot, pos = [], [], HEADER
    for comp, trailer in chunks:
        new_off.append(pos)
        new_tot.append(1 + len(comp) + len(trailer))
        pos += new_tot[-1]

    header = bytearray(pk.raw[:HEADER])
    _patch_u32(header, 0x04, 0x10, old_tot[0], new_tot[0], "first-chunk size")

    for i, (off, name, fields) in enumerate(pk.records):
        if i + 1 >= len(chunks):
            continue
        start, end = off + 32, off + 32 + 4 * len(fields)
        _patch_u32(header, start, end, pk.chunks[i + 1].marker_off, new_off[i + 1],
                   "%s offset" % name)
        _patch_u32(header, start, end, old_tot[i + 1], new_tot[i + 1], "%s size" % name)

    struct.pack_into(">I", header, 0x00, 0)
    struct.pack_into(">I", header, 0x00, zlib.crc32(bytes(header[4:HEADER])) & 0xffffffff)

    body = b"".join(bytes([MARKER]) + comp + trailer for comp, trailer in chunks)
    return bytes(header) + body


if __name__ == "__main__":
    main()
