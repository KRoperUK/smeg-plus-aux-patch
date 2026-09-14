#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Apply a SMEG+ patch set to an upgrade package and rebuild its checksum cascade.

The application for each variant is AppBin/f_BigQuick.bin: a 0x801-byte header
plus a zlib stream holding the PowerPC image loaded at 0x01000000. This tool:

  1. inflates the image,
  2. checks the original bytes at each patch address ("expect") and applies the
     replacement ("bytes"),
  3. re-deflates the image back into the container,
  4. rebuilds the checksum cascade:

        f_BigQuick.bin --crc32--> f_BigQuick.bin.inf
                       --crc32--> smeg.inf  (BIGQUICK_CRC32)
                       --crc32--> <module>_ctrl.bin
        <module>_ctrl.bin --crc32--> ctrl.bin (root manifest)

Only the changed files are written to --out (mirroring their package-relative
paths). Use tools/apply_files.sh to overlay them onto a copy of your package, or
pass --copy-package to have this tool copy the whole package into --out first.

No vendor firmware is bundled with this tool; point --src at your own legally
obtained package.

usage:
    python3 tools/patch_smeg.py --src SMEG_PLUS_UPG --out SMEG_PLUS_UPG_mod
    python3 tools/patch_smeg.py --src SMEG_PLUS_UPG --out out --only NAV
"""

import argparse
import json
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

DEFAULT_BASE = 0x01000000
HEADER_SIZE = 0x801


def crc32(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def s32(v):
    return struct.unpack(">i", struct.pack(">I", v))[0]


def inflate(raw):
    for start in (HEADER_SIZE, HEADER_SIZE - 1, 0x800):
        try:
            d = zlib.decompressobj()
            out = d.decompress(raw[start:])
            out += d.flush()
        except zlib.error:
            continue
        if len(out) > 0x100000:
            return start, out
    raise SystemExit("could not inflate application image")


def rewrite_inf(blob, new_crc):
    out, n = re.subn(rb"CRC32: -?\d+", ("CRC32: %d" % s32(new_crc)).encode(), blob, count=1)
    if n != 1:
        raise SystemExit("no 'CRC32:' field found in .inf")
    return out


def rewrite_smeg_inf(blob, new_crc):
    out, n = re.subn(
        rb"BIGQUICK_CRC32: -?\d+", ("BIGQUICK_CRC32: %d" % s32(new_crc)).encode(), blob, count=1
    )
    if n != 1:
        raise SystemExit("no 'BIGQUICK_CRC32:' field found in smeg.inf")
    return out


def swap_crc(buf, old, new, what):
    """Replace one 4-byte big-endian CRC in a control file."""
    pat = struct.pack(">I", old)
    n = buf.count(pat)
    if n != 1:
        raise SystemExit(
            "expected exactly one occurrence of %s CRC %#010x in the control file, found %d"
            % (what, old, n)
        )
    return buf.replace(pat, struct.pack(">I", new))


def load(path):
    return Path(path).read_bytes()


def write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Path(path).write_bytes(data)


BUILD_PATH_RE = re.compile(rb"04_HMI_DEV-([^/\x00]{1,32})/")


def firmware_hints(img):
    """Build-version tokens the vendor's own build paths leave in the image."""
    return sorted({m.group(1).decode("latin1") for m in BUILD_PATH_RE.finditer(bytes(img))})


def check_firmware(img, token, label):
    """Refuse to patch an image that is not the one these addresses came from.

    The per-patch ``expect`` bytes are only a heuristic. A short sequence like
    ``li r3,0 ; blr`` can sit at the recorded address in a different firmware version
    by coincidence, and two entries in this repository do exactly that on
    ``5.42.B.R4`` - they would be applied silently to the wrong offset. Addresses are
    per firmware version, so the version itself is checked explicitly.

    ``token`` is a substring of the build path the vendor leaves in the image, e.g.
    ``5.43.A.R2`` from ``E:/ccm_wa71/04_HMI_DEV-5.43.A.R2/04_HMI_DEV/...``. A variant
    with no ``firmware`` key is patched as before, with only the ``expect`` guard.
    """
    if not token:
        return
    if token.encode("latin1") in img:
        print("    firmware      %s" % token)
        return
    hints = firmware_hints(img)
    raise SystemExit(
        "%s: this image is not %s - refusing to patch.\n"
        "  Addresses are per firmware version, and the expect-byte check is not a\n"
        "  reliable substitute: short instruction sequences recur across versions.\n"
        "  Build tokens found in this image: %s"
        % (label, token, ", ".join(hints) if hints else "none")
    )


def apply_patches(img, base, patches, label):
    for p in patches:
        addr = int(str(p["addr"]), 16)
        off = addr - base
        if off < 0 or off + 4 > len(img):
            raise SystemExit("%s: patch address %#x outside image" % (label, addr))
        expect = bytes.fromhex(p["expect"])
        if img[off : off + len(expect)] != expect:
            raise SystemExit(
                "%s: at %#x expected %s, found %s (wrong firmware build?)"
                % (label, addr, expect.hex(), img[off : off + len(expect)].hex())
            )
        new = bytes.fromhex(p["bytes"])
        img[off : off + len(new)] = new
        print(
            "    %-14s %#010x  %s -> %s   %s"
            % (label, addr, expect.hex(), new.hex(), p.get("why", ""))
        )
    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_patches = os.path.normpath(
        os.path.join(here, os.pardir, "patches", "aux-autoswitch.json")
    )

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", required=True, help="original package directory")
    ap.add_argument("--out", required=True, help="output directory for changed files")
    ap.add_argument("--patches", default=default_patches, help="patch definition JSON")
    ap.add_argument("--only", nargs="*", default=None, help="variant name(s) to patch")
    ap.add_argument(
        "--copy-package",
        action="store_true",
        help="copy the whole package into --out before overlaying changes",
    )
    ap.add_argument("--level", type=int, default=6, help="zlib level for re-packing (default 6)")
    args = ap.parse_args()

    spec = json.loads(Path(args.patches).read_text())
    variants = spec["variants"]
    if args.only:
        variants = {k: v for k, v in variants.items() if k in args.only}
        missing = set(args.only) - set(variants)
        if missing:
            raise SystemExit("unknown variant(s): %s" % ", ".join(sorted(missing)))

    print("patch set : %s (%s)" % (spec.get("name", "?"), args.patches))
    print("source    : %s" % args.src)
    print("output    : %s" % args.out)
    if args.copy_package:
        print("copying package ...")
        shutil.copytree(args.src, args.out, dirs_exist_ok=True)

    root_ctrl = bytearray(load(os.path.join(args.src, "ctrl.bin")))
    done = 0

    for name, v in variants.items():
        paths = {k: os.path.join(args.src, v[k]) for k in ("app_image", "inf", "smeg_inf", "ctrl")}
        if not all(os.path.exists(p) for p in paths.values()):
            print("  [skip] %s not present in package" % name)
            continue

        base = int(str(v.get("base", hex(DEFAULT_BASE))), 16)
        old_bq = load(paths["app_image"])
        old_inf = load(paths["inf"])
        old_smeg = load(paths["smeg_inf"])
        old_ctrl = load(paths["ctrl"])

        old_crc = {
            "bq": crc32(old_bq),
            "inf": crc32(old_inf),
            "smeg": crc32(old_smeg),
            "ctrl": crc32(old_ctrl),
        }

        print("  [%s] %d bytes" % (name, len(old_bq)))
        start, img = inflate(old_bq)
        img = bytearray(img)
        check_firmware(img, v.get("firmware"), name)
        apply_patches(img, base, v["patches"], name)

        new_bq = old_bq[:start] + zlib.compress(bytes(img), args.level)
        chk = zlib.decompressobj()
        if chk.decompress(new_bq[start:]) + chk.flush() != bytes(img):
            raise SystemExit("%s: round-trip verification failed" % name)

        new_crc_bq = crc32(new_bq)
        new_inf = rewrite_inf(old_inf, new_crc_bq)
        new_smeg = rewrite_smeg_inf(old_smeg, new_crc_bq)
        new_crc_inf, new_crc_smeg = crc32(new_inf), crc32(new_smeg)

        ctrl = bytearray(old_ctrl)
        ctrl = swap_crc(ctrl, old_crc["bq"], new_crc_bq, "%s/BigQuick" % name)
        ctrl = swap_crc(ctrl, old_crc["inf"], new_crc_inf, "%s/BigQuick.inf" % name)
        ctrl = swap_crc(ctrl, old_crc["smeg"], new_crc_smeg, "%s/smeg.inf" % name)
        new_ctrl = bytes(ctrl)
        new_crc_ctrl = crc32(new_ctrl)

        root_ctrl = bytearray(
            swap_crc(root_ctrl, old_crc["ctrl"], new_crc_ctrl, "%s_ctrl.bin" % name)
        )

        for key, data in (
            ("app_image", new_bq),
            ("inf", new_inf),
            ("smeg_inf", new_smeg),
            ("ctrl", new_ctrl),
        ):
            write(os.path.join(args.out, v[key]), data)

        print(
            "    %-14s %9d -> %-9d  crc %#010x -> %#010x"
            % ("f_BigQuick", len(old_bq), len(new_bq), old_crc["bq"], new_crc_bq)
        )
        done += 1

    if done:
        write(os.path.join(args.out, "ctrl.bin"), bytes(root_ctrl))
        print("wrote ctrl.bin (root manifest)")

    print("changed files written to %s (%d variant(s))" % (args.out, done))
    if not done:
        sys.exit(1)


if __name__ == "__main__":
    main()
