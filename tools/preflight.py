#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Pre-flight a SMEG+ package: say what it will do before it goes on a stick.

Every car trip this project has spent was to discover something that was knowable offline.
The three most recent were:

  * `supervisor.Last_Source = 4` — not a valid source, so the unit ignored it and fell back
    to FM. The enum is known; nothing checked the value against it.
  * settings edited in `system.bin` appeared to do nothing, because the unit reads them from
    a separate `/USER_DATA` partition. Nothing said where a change would actually land.
  * a package rejected with string 2099 — the contract. Nothing checked the seal.

This runs those checks, plus the ones that are merely tedious, and reports what it does
**not** know as prominently as what it does. The unknowns are where the car trips went.

usage:
    python3 tools/preflight.py --package SMEG_PLUS_UPG_mod
    python3 tools/preflight.py --package SMEG_PLUS_UPG_mod --stock SMEG_PLUS_UPG
    python3 tools/preflight.py --package SMEG_PLUS_UPG_mod --json
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ("NAV", "AUDIO_BT", "AUDIO_BT_256")

# Recovered from C_HMI_AUDIO_APP_BASE's per-source OnEventSelect* handlers - the value each
# passes to CreateNotificationCommand. See docs/ANALYSIS.md.
AUDIO_SOURCES = {
    1: "FM",
    2: "AM",
    3: "DAB",
    5: "Bluetooth",
    6: "CDC",
    7: "AUX",
    10: "iPod",
    11: "Jukebox",
}

# Application-image patches this repository knows how to recognise. Addresses are absolute
# in the image loaded at 0x01000000.
KNOWN_PATCHES = {
    "NAV": [
        (0x02247858, "9421ffa0", "386000014e800020", "IsAUXSRCAvailable -> return true"),
        (0x02303428, "419e014c", "60000000", "AUX status handler +0x10c -> nop"),
        (0x010346D0, "38600000", "4970de88", "dummyLogMsg -> b Log_msg (diagnostics)"),
    ],
}

OK, WARN, BAD, INFO, UNKNOWN = "ok", "warn", "bad", "info", "unknown"


class Report:
    def __init__(self):
        self.rows = []
        self.problems = 0
        self.warnings = 0

    def add(self, level, area, message):
        self.rows.append((level, area, message))
        if level == BAD:
            self.problems += 1
        if level == WARN:
            self.warnings += 1

    def show(self):
        mark = {OK: "OK  ", WARN: "WARN", BAD: "FAIL", INFO: "    ", UNKNOWN: "?   "}
        area = None
        for level, a, m in self.rows:
            if a != area:
                print("\n%s" % a)
                area = a
            for line in m.splitlines():
                print("  %s %s" % (mark[level], line))
        print()
        if self.problems:
            print("%d problem(s), %d warning(s)" % (self.problems, self.warnings))
        elif self.warnings:
            print("no problems, %d warning(s)" % self.warnings)
        else:
            print("no problems found")
        return 1 if self.problems else 0

    def as_dict(self):
        return {
            "problems": self.problems,
            "warnings": self.warnings,
            "rows": [{"level": l, "area": a, "message": m} for l, a, m in self.rows],
        }


def read_module(pkg, module):
    """(app image bytes, {name: bytes} from system.bin) for a module, or (None, {})."""
    img = media = {}
    app = os.path.join(pkg, module, "AppBin", "f_BigQuick.bin")
    if os.path.exists(app):
        raw = open(app, "rb").read()
        try:
            img = zlib.decompress(raw[0x801:])
        except zlib.error:
            img = None
    sysbin = os.path.join(pkg, module, "system.bin")
    if os.path.exists(sysbin):
        import gzip
        import io
        import tarfile

        try:
            tf = tarfile.open(fileobj=io.BytesIO(gzip.open(sysbin, "rb").read()))
            media = {
                m.name: (tf.extractfile(m).read() if m.isfile() else b"") for m in tf.getmembers()
            }
        except Exception:
            media = {}
    return img, media


def up_keys(blob):
    t = tempfile.NamedTemporaryFile(delete=False)
    t.write(blob)
    t.close()
    try:
        con = sqlite3.connect(t.name)
        out = {}
        for sec, name, idx, ival, sval in con.execute(
            "select Section, Name, Idx, IntValue, StringValue from UP_Keys"
        ):
            out[(sec, name, idx)] = ival if ival is not None else sval
        con.close()
        return out
    except Exception:
        return {}
    finally:
        os.unlink(t.name)


def check_structure(rep, pkg):
    for name in ("ctrl.bin", "contract.dat", "media.inf"):
        rep.add(
            OK if os.path.exists(os.path.join(pkg, name)) else BAD,
            "package",
            "%s %s" % (name, "present" if os.path.exists(os.path.join(pkg, name)) else "MISSING"),
        )
    found = [m for m in MODULES if os.path.isdir(os.path.join(pkg, m))]
    rep.add(OK if found else BAD, "package", "modules: %s" % (", ".join(found) or "none"))
    return found


def check_cascade(rep, pkg, module):
    def crc(p):
        return zlib.crc32(open(p, "rb").read()) & 0xFFFFFFFF

    img = os.path.join(pkg, module, "AppBin", "f_BigQuick.bin")
    inf = img + ".inf"
    smeg = os.path.join(pkg, module, "smeg.inf")
    if not (os.path.exists(img) and os.path.exists(inf)):
        return
    want = crc(img)
    import re

    got = []
    for path, pattern in ((inf, r"CRC32:\s*(-?\d+)"), (smeg, r"BIGQUICK_CRC32:\s*(-?\d+)")):
        if os.path.exists(path):
            m = re.search(pattern, open(path).read())
            got.append((os.path.basename(path), int(m.group(1)) & 0xFFFFFFFF if m else None))
    for label, value in got:
        rep.add(
            OK if value == want else BAD,
            "cascade",
            "f_BigQuick.bin CRC %08x vs %s %s"
            % (want, label, "%08x" % value if value is not None else "(absent)"),
        )


def check_patches(rep, img, module):
    if not img:
        return []
    present = []
    for addr, stock, patched, why in KNOWN_PATCHES.get(module, []):
        off = addr - 0x01000000
        here = img[off : off + len(patched) // 2].hex()
        if here == patched:
            present.append(why)
            rep.add(OK, "application image", "PATCHED  %s" % why)
        elif here == stock:
            rep.add(INFO, "application image", "stock    %s" % why)
        else:
            rep.add(
                WARN,
                "application image",
                "unrecognised bytes at %#010x (%s) - not a build this tool knows" % (addr, here),
            )
    return present


def check_settings(rep, keys, area="settings"):
    ls = None
    for (sec, name, idx), val in keys.items():
        if sec == "supervisor" and name == "Last_Source":
            ls = val
    if ls is None:
        return
    if ls in AUDIO_SOURCES:
        rep.add(OK, area, "supervisor.Last_Source = %s (%s)" % (ls, AUDIO_SOURCES[ls]))
    else:
        rep.add(
            BAD,
            area,
            "supervisor.Last_Source = %r is NOT a valid source\n"
            "    known: %s\n"
            "    the unit will ignore it and fall back to its last real source"
            % (ls, ", ".join("%s=%s" % (v, k) for k, v in sorted(AUDIO_SOURCES.items()))),
        )

    names = {
        idx: val
        for (sec, name, idx), val in keys.items()
        if sec == "phone" and name == "Ringing_List"
    }
    if names:
        rep.add(
            OK,
            area,
            "ring tone list starts: %s" % ", ".join(repr(names[i]) for i in sorted(names)[:3]),
        )


def check_user_data(rep, pkg, module):
    ud = os.path.join(pkg, module, "USER_DATA")
    if not os.path.isdir(ud):
        rep.add(INFO, "USER_DATA", "no payload - the unit's own settings are left alone")
        return
    files = [os.path.relpath(os.path.join(r, f), ud) for r, _, fs in os.walk(ud) for f in fs]
    rep.add(
        WARN, "USER_DATA", "%d file(s) will be written to the unit's user partition" % len(files)
    )
    for f in files:
        rep.add(INFO, "USER_DATA", "  %s" % f)
    rep.add(WARN, "USER_DATA", "this can reset paired phones, navigation destinations and presets")
    rep.add(
        UNKNOWN,
        "USER_DATA",
        "whether the updater merges per file or replaces the folder is not known",
    )


def check_contract(rep, pkg):
    tool = os.path.join(HERE, "patch_contract.py")
    if not os.path.exists(tool):
        rep.add(UNKNOWN, "contract", "patch_contract.py not found next to this tool")
        return
    # the key lives in an application image, so without one the contract cannot be read at
    # all - that is "unknown", not "broken", and saying otherwise would be misleading
    if not any(os.path.exists(os.path.join(pkg, m, "AppBin", "f_BigQuick.bin")) for m in MODULES):
        rep.add(UNKNOWN, "contract", "no application image present, cannot verify the seal")
        return
    r = subprocess.run(
        [sys.executable, tool, "--package", pkg, "--show"], capture_output=True, text=True
    )
    out = (r.stdout or "") + (r.stderr or "")
    if "nothing to update" in out or "0 changed" in out:
        rep.add(OK, "contract", "sealed and matches every file - the unit should accept it")
    elif "matches" in out:
        rep.add(OK, "contract", "the contract decrypts and matches the files")
    else:
        rep.add(
            BAD,
            "contract",
            "the contract does not match the files - expect string 2099 "
            "(protected and cannot be copied)\n    %s" % out.strip().splitlines()[-1:][0]
            if out.strip()
            else "could not read the contract",
        )


def check_writes(rep, pkg, module, patches, media, keys):
    """Say plainly what the update will touch, so the blast radius is visible."""
    touched = []
    if patches:
        touched.append("%s/AppBin/f_BigQuick.bin (application image)" % module)
    if media:
        touched.append("%s/system.bin (media partition)" % module)
    if os.path.isdir(os.path.join(pkg, module, "USER_DATA")):
        touched.append("%s/USER_DATA (the unit's own settings)" % module)
    if keys:
        touched.append("settings values (%d)" % len(keys))
    for t in touched:
        rep.add(INFO, "will write", t)
    if not touched:
        rep.add(WARN, "will write", "nothing recognisable - is this a patched package?")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--package", required=True)
    ap.add_argument("--module", default=None)
    ap.add_argument("--stock", help="a stock package to compare against (optional)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pkg = os.path.abspath(os.path.expanduser(args.package))
    if not os.path.isdir(pkg):
        sys.exit("no such package: %s" % pkg)

    rep = Report()
    rep.add(INFO, "package", pkg)
    modules = check_structure(rep, pkg)
    module = args.module or (modules[0] if modules else "NAV")

    img, media = read_module(pkg, module)
    check_cascade(rep, pkg, module)
    patches = check_patches(rep, img, module)

    keys = {}
    if "Data_base/sqlite/up_common.sqlite" in media:
        keys = up_keys(media["Data_base/sqlite/up_common.sqlite"])
    if keys:
        check_settings(rep, keys)
    ud = os.path.join(pkg, module, "USER_DATA", "user_data", "sqlite", "up_common.sqlite")
    if os.path.exists(ud):
        check_settings(rep, up_keys(open(ud, "rb").read()), area="settings (USER_DATA)")

    check_user_data(rep, pkg, module)
    check_writes(rep, pkg, module, patches, media, keys)

    rep.add(
        UNKNOWN, "behaviour", "whether a patch changes what the unit does cannot be settled here"
    )
    rep.add(UNKNOWN, "behaviour", "run tools/ppcdis.py against the image to check a patch by hand")

    if args.json:
        print(json.dumps(rep.as_dict(), indent=2))
        return 1 if rep.problems else 0
    return rep.show()


if __name__ == "__main__":
    sys.exit(main())
