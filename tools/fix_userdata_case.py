#!/usr/bin/env python3
"""Rewrite one FAT directory entry so the SMEG+ updater reads 'sqlite', not 'SQLITE'.

Why this exists
---------------
A package can carry a USER_DATA payload at
``SMEG_PLUS_UPG/NAV/USER_DATA/user_data/sqlite/up_common.sqlite``. The updater
copies it with ``xcopy_blk("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA", "/USER_DATA")``,
naming each destination directory after what it reads off the stick.

The application reads its live settings from **lowercase** ``/USER_DATA/user_data/sqlite/``.
But ``sqlite`` is a valid 8.3 name, so macOS stores it as the short name ``SQLITE``
with the NT "lowercase base" bit set and **no long-filename entry**. The updater
honours long filenames but not that bit, so it creates an uppercase ``SQLITE``
sibling that the application never opens. Observed on hardware; see
docs/VERIFICATION.md and docs/FLASHING.md.

The fix is to give that one directory a long-filename entry reading ``sqlite``.

Usage
-----
Check a volume or image without writing::

    python3 tools/fix_userdata_case.py --check /dev/diskNsM

To create the required LFN on macOS, first rename ``sqlite`` to a name that needs
one, such as ``sqlite_dat``. Unmount the volume, inspect the planned edit, apply
it through the raw device, then remount and check::

    diskutil unmount /Volumes/<vol>
    sudo python3 tools/fix_userdata_case.py --dry-run /dev/rdiskNsM
    sudo python3 tools/fix_userdata_case.py /dev/rdiskNsM
    diskutil mount /dev/diskNsM
    python3 tools/fix_userdata_case.py --check /dev/diskNsM

It edits one 32-byte entry, read-modify-written inside its 512-byte sector.
Nothing is moved, no cluster is allocated, and the entry checksum is unaffected
because the short name does not change. --dry-run reports and writes nothing.
"""

import os
import struct
import sys

PAYLOAD_PARTS = ("SMEG_PLUS_UPG", "NAV", "USER_DATA", "user_data")
WANT_LFN_PREFIX = "sqlite"
TARGET_NAME = "sqlite"
SECTOR = 512


class Volume:
    """Sector-granular FAT reader/writer.

    Raw block devices refuse unaligned reads and wide reads, and slurping a
    30 GB stick into memory is not an option, so every access goes through a
    single 512-byte sector cache. The largest read is one cluster.
    """

    def __init__(self, fh):
        self.fh = fh
        self._cache = {}

    def sector(self, n):
        if n not in self._cache:
            self._cache[n] = bytearray(os.pread(self.fh, SECTOR, n * SECTOR))
        if len(self._cache[n]) != SECTOR:
            sys.exit(f"short read at sector {n} - is this the right device?")
        return self._cache[n]

    def bytes_at(self, off, length):
        out = bytearray()
        pos = off
        while length > 0:
            n = pos // SECTOR
            start = pos - n * SECTOR
            take = min(SECTOR - start, length)
            out += self.sector(n)[start:start + take]
            pos += take
            length -= take
        return bytes(out)

    def put(self, off, data):
        """Stage a write into the sector cache (never more than one sector)."""
        for i, b in enumerate(data):
            pos = off + i
            n = pos // SECTOR
            self.sector(n)[pos - n * SECTOR] = b

    def flush(self):
        for n, buf in self._cache.items():
            os.pwrite(self.fh, bytes(buf), n * SECTOR)
        self._cache.clear()


def main(argv):
    dry = "--dry-run" in argv
    check = "--check" in argv
    if dry and check:
        sys.exit("choose --check or --dry-run, not both")
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = args[0]

    fh = os.open(path, os.O_RDONLY if check else os.O_RDWR)
    vol = Volume(fh)

    bs = vol.bytes_at(0, SECTOR)
    if bs[510:512] != b"\x55\xaa":
        sys.exit("not a FAT boot sector (no 0x55AA signature)")
    bps = struct.unpack("<H", bs[0x0B:0x0D])[0]
    spc = bs[0x0D]
    res = struct.unpack("<H", bs[0x0E:0x10])[0]
    nfat = bs[0x10]
    rootent = struct.unpack("<H", bs[0x11:0x13])[0]
    fatsz16 = struct.unpack("<H", bs[0x16:0x18])[0]
    fatsz32 = struct.unpack("<I", bs[0x24:0x28])[0]
    fatsz = fatsz32 or fatsz16
    rootclus = struct.unpack("<I", bs[0x2C:0x30])[0]
    fat32 = fatsz16 == 0
    # BS_FilSysType is at 0x36 for FAT12/16 and at 0x52 for FAT32's extended BPB.
    fstype = bytes(bs[0x52:0x5A] if fat32 else bs[0x36:0x3E]).decode("latin1", "replace").strip()
    if bps != SECTOR:
        sys.exit(f"unexpected bytes/sector ({bps}); refusing")

    fat_off = res * bps
    root_off = fat_off + nfat * fatsz * bps
    data_off = root_off + (rootent * 32 if not fat32 else 0)
    cbytes = spc * bps

    def next_in_chain(c):
        if fat32:
            return struct.unpack("<I", vol.bytes_at(fat_off + c * 4, 4))[0] & 0x0FFFFFFF
        return struct.unpack("<H", vol.bytes_at(fat_off + c * 2, 2))[0]

    def regions(cl):
        """Return physical (offset, bytes) chunks for a directory cluster chain."""
        if cl == 0:
            if not fat32:
                return [(root_off, vol.bytes_at(root_off, rootent * 32))]
            cl = rootclus
        out = []
        c = cl
        guard = 0
        while 2 <= c < (0x0FFFFFF8 if fat32 else 0xFFF8):
            off = data_off + (c - 2) * cbytes
            out.append((off, vol.bytes_at(off, cbytes)))
            c = next_in_chain(c)
            guard += 1
            if guard > 4096:
                sys.exit("cluster chain looks cyclic; refusing")
        return out

    def lfn_name(e):
        return (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "ignore").split("\x00")[0]

    def walk(cl):
        out, pend = [], []
        for base, data in regions(cl):
            for i in range(0, len(data), 32):
                e = data[i:i + 32]
                if len(e) < 32 or e[0] == 0:
                    return out
                if e[0] == 0xE5:
                    pend = []
                    continue
                if e[11] == 0x0F:
                    pend.append((base + i, lfn_name(e)))
                    continue
                short = e[0:8].decode("latin1").rstrip()
                ext = e[8:11].decode("latin1").rstrip()
                low = struct.unpack("<H", e[26:28])[0]
                high = struct.unpack("<H", e[20:22])[0] if fat32 else 0
                out.append({
                    "off": base + i, "short": short + ("." + ext if ext else ""),
                    "attr": e[11], "nt": e[12],
                    "lfn": "".join(x[1] for x in reversed(pend)) or None,
                    "lfn_ents": pend, "clus": low | (high << 16),
                })
                pend = []
        return out

    def find_dir(cl, name):
        for e in walk(cl):
            if not e["attr"] & 0x10 or e["short"] in (".", ".."):
                continue
            if (e["lfn"] or e["short"]).lower() == name.lower():
                return e
        return None

    print(f"volume: fstype={fstype!r} bytes/sector={bps} sectors/cluster={spc} "
          f"{'FAT32' if fat32 else 'FAT16'}")

    cur = 0
    for part in PAYLOAD_PARTS:
        ent = find_dir(cur, part)
        if ent is None:
            sys.exit(f"could not find {part!r} - is the payload on this volume?")
        cur = ent["clus"]
        print(f"  found {part!r} (short {ent['short']!r})")

    print(f"listing {PAYLOAD_PARTS[-1]!r}:")
    victim = None
    for e in walk(cur):
        if e["short"] in (".", ".."):
            continue
        flags = " ".join(f for f, m in (("LC-BASE", 0x08), ("LC-EXT", 0x10)) if e["nt"] & m)
        print(f"  {'DIR ' if e['attr'] & 0x10 else 'FILE'} short={e['short']!r:14s} "
              f"ntres=0x{e['nt']:02x} {flags:8s} LFN={e['lfn']!r}")
        if e["attr"] & 0x10 and e["lfn"] and e["lfn"].lower().startswith(WANT_LFN_PREFIX) \
                and e["lfn"].lower() != TARGET_NAME:
            victim = e
        if e["attr"] & 0x10 and e["lfn"] == TARGET_NAME:
            print("OK: FAT long-filename entry is exactly 'sqlite'")
            os.close(fh)
            return

    if check:
        os.close(fh)
        sys.exit(
            "NOT SAFE: the updater will read 'SQLITE', not lowercase 'sqlite'.\n"
            "The directory needs a FAT long-filename entry; see docs/FLASHING.md."
        )
    if victim is None:
        sys.exit(
            "no directory with a long-filename entry to rewrite.\n"
            "Rename the payload directory to something that needs one first, e.g.\n"
            "  mv .../user_data/sqlite .../user_data/sqlite_dat"
        )
    if len(victim["lfn_ents"]) != 1:
        sys.exit(f"{victim['lfn']!r} spans {len(victim['lfn_ents'])} LFN entries; "
                 "use a name of 9-13 characters so it fits in one")

    print(f"\nrewriting LFN {victim['lfn']!r} -> {TARGET_NAME!r} "
          f"(short name {victim['short']!r} and its checksum are unchanged)")
    if dry:
        print("dry run: nothing written")
        os.close(fh)
        return

    p = victim["lfn_ents"][0][0]
    chars = [ord(c) for c in TARGET_NAME] + [0x0000] + [0xFFFF] * (13 - len(TARGET_NAME) - 1)
    vol.put(p + 1, b"".join(struct.pack("<H", x) for x in chars[0:5]))
    vol.put(p + 14, b"".join(struct.pack("<H", x) for x in chars[5:11]))
    vol.put(p + 28, b"".join(struct.pack("<H", x) for x in chars[11:13]))
    vol.flush()
    os.close(fh)
    print("done - remount and check the directory now lists as 'sqlite'")


if __name__ == "__main__":
    main(sys.argv)
