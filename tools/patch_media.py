#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Patch files inside a SMEG+ media partition (`<module>/system.bin`).

`system.bin` is a gzip'd tar that the unit extracts to `/SYSTEM/`. Editing anything in
it means rebuilding the tar, re-gzipping, and repairing the whole checksum chain:

    changed file
      -> system_ctrl.bin    (fixed 264-byte records: [path][pad][type][crc32])
      -> system.bin         (tar + gzip)
      -> system.bin.inf     (CRC32 + the SIZE / SIZE_n fields)
      -> <module>_ctrl.bin  (4-byte big-endian CRC32 per packaged file)
      -> ctrl.bin           (root manifest)

The `SIZE` fields are the uncompressed *contents* size, not the tar or gzip size:

    SIZE   = sum of the file sizes inside the tar (headers and padding excluded)
    SIZE_n = the same, with each file rounded up to an n KiB block

They are read by `UpgPlugin.out` (not `upgrade.out`) for the media space check.

Only **replacing** existing files is supported — adding one would need a new
`system_ctrl.bin` record, and the record count/semantics are not fully understood.

usage:
    # see what is in the partition
    python3 tools/patch_media.py list --package SMEG_PLUS_UPG --module NAV

    # extract it (and keep a copy of the originals so you can restore them)
    python3 tools/patch_media.py extract --package SMEG_PLUS_UPG --module NAV \\
        --tree media --backup backups

    # put an original file back
    python3 tools/patch_media.py restore --backup backups --tree media --only ring_tones/ring1RT.wav

    # rebuild the package with everything that differs in the tree
    python3 tools/patch_media.py apply --package SMEG_PLUS_UPG --module NAV \\
        --tree media --out SMEG_PLUS_UPG_mod
"""
import argparse
import gzip
import io
import os
import re
import shutil
import struct
import sys
import tarfile
import zlib

SYSTEM_PREFIX = "/SYSTEM/"
RECORD_SIZE = 264          # system_ctrl.bin record stride
RECORD_CRC_OFF = 260       # CRC32 sits at path_offset + 260
MODULES = ("AUDIO_BT", "AUDIO_BT_256", "NAV")
TONE_DIRS = ("ring_tones", "wait_tones")


def crc32(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def die(msg):
    sys.exit(msg)


def roundup(v, b):
    return (v + b - 1) // b * b


# --------------------------------------------------------------------- partition

class Partition:
    def __init__(self, package, module):
        self.module = module
        self.dir = os.path.join(package, module)
        self.bin = os.path.join(self.dir, "system.bin")
        for p in (self.bin, os.path.join(self.dir, "system_ctrl.bin")):
            if not os.path.exists(p):
                die("missing %s — is --package pointing at a package root?" % p)
        raw = open(self.bin, "rb").read()
        try:
            self.tar_bytes = gzip.decompress(raw)
            self.tf = tarfile.open(fileobj=io.BytesIO(self.tar_bytes), mode="r:")
        except Exception as e:
            die("could not read %s: %s" % (self.bin, e))
        self.members = self.tf.getmembers()
        self.data = {}
        for m in self.members:
            if m.isfile():
                self.data[m.name] = self.tf.extractfile(m).read()

    def size_fields(self, data=None):
        """Our own computation. Kept for reference — see adjusted_size_fields()."""
        data = data if data is not None else self.data
        fields = {"SIZE": sum(len(v) for v in data.values())}
        for n in (1, 2, 4, 8, 16, 32):
            fields["SIZE_%d" % n] = sum(roundup(len(v), n * 1024) for v in data.values())
        return fields

    def build_tar(self, data):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w", format=tarfile.GNU_FORMAT) as tf:
            for m in self.members:
                if m.isfile():
                    payload = data[m.name]
                    info = tarfile.TarInfo(m.name)
                    for attr in ("mode", "uid", "gid", "mtime", "uname", "gname", "type"):
                        setattr(info, attr, getattr(m, attr))
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))
                else:
                    tf.addfile(m)
        return out.getvalue()


def diff_tree(part, tree, only=None):
    """Return {member: new_bytes} for files in the tar whose tree copy differs."""
    changes, missing, same, extra = {}, [], [], []
    seen = set()
    for name in part.data:
        if only and name not in only:
            continue
        path = os.path.join(tree, name)
        if not os.path.isfile(path):
            missing.append(name)
            continue
        seen.add(name)
        new = open(path, "rb").read()
        if new != part.data[name]:
            changes[name] = new
        else:
            same.append(name)
    for root, _dirs, files in os.walk(tree):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), tree)
            if rel not in part.data:
                extra.append(rel)
    return changes, missing, same, extra


# ---------------------------------------------------------------- system_ctrl

SIZE_KEYS = ("SIZE",) + tuple("SIZE_%d" % n for n in (1, 2, 4, 8, 16, 32))


def read_size_fields(inf_bytes):
    found = re.findall(rb"(SIZE(?:_\d+)?): (\d+)", inf_bytes)
    return {k.decode(): int(v) for k, v in found}


def adjusted_size_fields(old_data, new_data, old_fields):
    """Carry the vendor's SIZE values forward by exactly our change.

    Our own formula (sum of contents / per-file block rounding) reproduces `SIZE`
    exactly but lands a fixed, module-independent amount below the vendor's values for
    n = 1/2/4 — a rule we could not identify. Rather than guess it, apply the *delta*
    to the values already in the .inf: an untouched partition then keeps its numbers
    byte-for-byte, and a changed file moves them by exactly its own size change.
    """
    out = {}
    for key in SIZE_KEYS:
        if key not in old_fields:
            continue
        if key == "SIZE":
            delta = (sum(len(v) for v in new_data.values())
                     - sum(len(v) for v in old_data.values()))
        else:
            n = int(key.split("_")[1]) * 1024
            delta = (sum(roundup(len(v), n) for v in new_data.values())
                     - sum(roundup(len(v), n) for v in old_data.values()))
        out[key] = old_fields[key] + delta
    return out


def patch_system_ctrl(ctrl_bytes, changes, old_data):
    buf = bytearray(ctrl_bytes)
    for name, new in changes.items():
        needle = (SYSTEM_PREFIX + name).encode()
        off = buf.find(needle)
        if off < 0:
            die("system_ctrl.bin has no record for %s — cannot replace it" % name)
        if buf.find(needle, off + 1) >= 0:
            die("system_ctrl.bin has more than one record for %s" % name)
        pos = off + RECORD_CRC_OFF
        old_crc, new_crc = crc32(old_data[name]), crc32(new)
        have = struct.unpack_from(">I", buf, pos)[0]
        if have != old_crc:
            die("system_ctrl.bin record for %s holds %#010x, expected %#010x"
                % (name, have, old_crc))
        struct.pack_into(">I", buf, pos, new_crc)
    return bytes(buf)


def patch_inf(inf_bytes, new_crc, size_fields):
    out, n = re.subn(rb"CRC32: -?\d+", b"CRC32: %d" % new_crc, inf_bytes, count=1)
    if n != 1:
        die("no CRC32 field in system.bin.inf")
    for key, val in size_fields.items():
        k = key.encode()
        out, n = re.subn(k + rb": \d+", k + b": %d" % val, out, count=1)
        if n != 1:
            die("no %s field in system.bin.inf" % key)
    return out


def swap_crc(buf, old, new, what):
    pat = struct.pack(">I", old)
    if buf.count(pat) != 1:
        die("expected exactly one %s CRC %#010x in the manifest, found %d"
            % (what, old, buf.count(pat)))
    return buf.replace(pat, struct.pack(">I", new))


# --------------------------------------------------------------------- commands

def cmd_list(args):
    part = Partition(args.package, args.module)
    tones = {n: len(d) for n, d in part.data.items()
             if n.split("/")[0] in TONE_DIRS}
    print("module %s: %d files in the partition, %d tone files"
          % (args.module, len(part.data), len(tones)))
    print("%-52s %10s" % ("PATH", "SIZE"))
    for name in sorted(part.data):
        if args.tones and name.split("/")[0] not in TONE_DIRS:
            continue
        print("%-52s %10d" % (name, len(part.data[name])))


def cmd_extract(args):
    part = Partition(args.package, args.module)
    os.makedirs(args.tree, exist_ok=True)
    n = 0
    for name, data in part.data.items():
        dest = os.path.join(args.tree, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        n += 1
    print("extracted %d file(s) to %s" % (n, args.tree))

    if args.backup:
        b = 0
        for name, data in part.data.items():
            prefix = name.split("/")[0]
            if args.backup_tones_only and prefix not in TONE_DIRS:
                continue
            dest = os.path.join(args.backup, part.module, name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            b += 1
        print("backed up %d original file(s) to %s/%s" % (b, args.backup, part.module))


def cmd_restore(args):
    src_root = os.path.join(args.backup, args.module) if args.module else args.backup
    if not os.path.isdir(src_root):
        die("no backup for that module at %s" % src_root)
    only = set(args.only or [])
    n = 0
    for root, _d, files in os.walk(src_root):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), src_root)
            if only and rel not in only:
                continue
            dest = os.path.join(args.tree, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(os.path.join(root, f), dest)
            print("restored %s" % rel)
            n += 1
    if not n:
        die("nothing to restore (check --only / --module)")
    print("restored %d file(s) into %s" % (n, args.tree))


def cmd_apply(args):
    part = Partition(args.package, args.module)
    only = set(args.only or []) or None
    changes, missing, same, extra = diff_tree(part, args.tree, only)

    if extra:
        print("note: %d file(s) in the tree are not in the partition and will be ignored:"
              % len(extra))
        for e in extra[:10]:
            print("   ", e)
    if not changes:
        die("tree has no differences against %s/%s — nothing to patch"
            % (args.module, "system.bin"))

    print("changes (%d):" % len(changes))
    for name in sorted(changes):
        print("   %-52s %8d -> %8d" % (name, len(part.data[name]), len(changes[name])))

    if args.dry_run:
        print("dry run — nothing written")
        return

    # rebuild the partition
    new_data = dict(part.data)
    new_data.update(changes)
    new_tar = part.build_tar(new_data)
    new_bin = gzip.compress(new_tar, args.level)
    new_ctrl = patch_system_ctrl(open(os.path.join(part.dir, "system_ctrl.bin"), "rb").read(),
                                 changes, part.data)
    old_inf_bytes = open(os.path.join(part.dir, "system.bin.inf"), "rb").read()
    old_fields = read_size_fields(old_inf_bytes)
    new_fields = adjusted_size_fields(part.data, new_data, old_fields)
    new_inf = patch_inf(old_inf_bytes, crc32(new_bin), new_fields)

    # manifests: prefer a previously patched copy if one was handed to us
    base = args.ctrl_from or args.package
    mod_ctrl_path = os.path.join(base, "%s_ctrl.bin" % args.module)
    root_ctrl_path = os.path.join(base, "ctrl.bin")
    old_mod = open(mod_ctrl_path, "rb").read()
    old_root = open(root_ctrl_path, "rb").read()

    old_bin_crc = crc32(open(part.bin, "rb").read())
    old_inf_crc = crc32(open(os.path.join(part.dir, "system.bin.inf"), "rb").read())
    old_ctrl_crc = crc32(open(os.path.join(part.dir, "system_ctrl.bin"), "rb").read())

    mod_ctrl = swap_crc(old_mod, old_bin_crc, crc32(new_bin), "%s/system.bin" % args.module)
    mod_ctrl = swap_crc(mod_ctrl, old_inf_crc, crc32(new_inf), "%s/system.bin.inf" % args.module)
    mod_ctrl = swap_crc(mod_ctrl, old_ctrl_crc, crc32(new_ctrl),
                        "%s/system_ctrl.bin" % args.module)
    root_ctrl = swap_crc(old_root, crc32(old_mod), crc32(mod_ctrl), "%s_ctrl.bin" % args.module)

    out = args.out
    writes = {
        "%s/system.bin" % args.module: new_bin,
        "%s/system.bin.inf" % args.module: new_inf,
        "%s/system_ctrl.bin" % args.module: new_ctrl,
        "%s_ctrl.bin" % args.module: mod_ctrl,
        "ctrl.bin": root_ctrl,
    }
    for rel, data in writes.items():
        dest = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").write(data)

    print("\nwrote:")
    for rel, data in writes.items():
        print("   %-40s %d bytes" % (rel, len(data)))
    print("\ntar %d -> %d bytes, gzip %d -> %d bytes"
          % (len(part.tar_bytes), len(new_tar), os.path.getsize(part.bin), len(new_bin)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, package=True):
        if package:
            p.add_argument("--package", required=True, help="package root (contains <module>/)")
        p.add_argument("--module", default="NAV", choices=MODULES)

    p = sub.add_parser("list", help="list the files in the partition")
    common(p)
    p.add_argument("--tones", action="store_true", help="only ring_tones/ and wait_tones/")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("extract", help="extract the partition (and optionally back up the originals)")
    common(p)
    p.add_argument("--tree", required=True, help="where to extract the tree")
    p.add_argument("--backup", help="also copy the originals here, for restore")
    p.add_argument("--backup-tones-only", action="store_true",
                   help="restrict the backup to ring_tones/ and wait_tones/")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("restore", help="put original files back into a tree")
    p.add_argument("--backup", required=True, help="backup root (from extract --backup)")
    p.add_argument("--tree", required=True)
    p.add_argument("--module", choices=MODULES, help="backup sub-directory to restore from")
    p.add_argument("--only", nargs="*", help="specific member paths, e.g. ring_tones/ring1RT.wav")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("apply", help="rebuild the package from a tree")
    common(p)
    p.add_argument("--tree", required=True, help="the extracted tree to pack")
    p.add_argument("--out", required=True, help="where the changed files are written")
    p.add_argument("--only", nargs="*", help="restrict to specific member paths")
    p.add_argument("--ctrl-from", help="read <module>_ctrl.bin/ctrl.bin from here instead "
                                       "(for chaining after patch_smeg.py)")
    p.add_argument("--level", type=int, default=6, help="gzip level (default 6)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.set_defaults(fn=cmd_apply)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
