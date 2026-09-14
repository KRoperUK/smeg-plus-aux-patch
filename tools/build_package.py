#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Build a patched SMEG+ package from a manifest, in one command.

Applying a patch by hand means running three or four tools in a specific order with an
`rsync` between each one, and two of those orderings are silent if you get them wrong:

  * the media step must run against the **already application-patched** package, or it
    rebuilds `ctrl.bin` without the application change and quietly drops it;
  * the contract must be re-sealed **last**, or the package is left unsealed and the unit
    refuses it (string 2099).

This tool owns that ordering so a build is a file you can read and re-run, not a sequence
you have to remember. It shells out to the individual tools rather than reimplementing
them, so they stay usable on their own.

Manifest (JSON — no extra dependency):

    {
      "package": "SMEG_PLUS_UPG",
      "out": "SMEG_PLUS_UPG_custom",
      "module": "NAV",
      "app":   { "patches": ["aux-autoswitch"] },
      "media": {
        "tones":  { "ring_tones/ring1RT.wav": "piano-riff.mp3" },
        "splash": { "peugeot": "snoopy.png" },
        "names":  { "ring1": "Piano Riff" },
        "gui_ver": "32.01"
      },
      "seal": true
    }

Every section is optional. `app.patches` names files in `patches/`; `media.tones` maps a
partition-relative destination to a source audio file of any format ffmpeg reads;
`media.splash` maps a marque to an image; `media.names` renames the ringtone entries the
phone UI shows; `media.gui_ver` sets `GUI_VER` in the partition's `Data_base/smeg.inf`,
which the System Info screen shows as "Display version" — the one visible field nothing
gates on, so it works as a build marker.

usage:
    python3 tools/build_package.py --manifest build.json
    python3 tools/build_package.py --manifest build.json --dry-run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable


def tool(name):
    return os.path.join(HERE, name)


def load_module(name):
    """Import one of the sibling tools by path (they are scripts, not a package)."""
    import importlib.util

    path = os.path.join(HERE, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(argv, what, dry=False):
    print("==> %s" % what)
    if dry:
        print("    (dry run) %s" % " ".join(argv[2:]))
        return ""
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("%s failed:\n%s" % (what, (r.stderr or r.stdout).strip()))
    for line in (r.stdout or "").rstrip().splitlines()[-4:]:
        print("    %s" % line)
    return r.stdout or ""


def overlay(src, dest, dry=False):
    """Copy the files a tool wrote into the package, preserving relative paths."""
    n = 0
    for root, _, files in os.walk(src):
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(dest, os.path.relpath(s, src))
            n += 1
            if dry:
                continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
    print("    overlaid %d file(s) onto the package" % n)


def convert_tone(rt, source, dest, channels, rate, gain_db=None):
    """Format conversion, plus an optional gain in dB.

    `ringtones.convert` deliberately does not touch level, but the stock tones are mastered
    at about -1 dBFS, so an unmodified music track lands 6-8 dB quieter and sounds muted in
    the car. `gain_db` makes that an explicit, visible choice in the manifest.
    """
    if gain_db is None:
        return rt.convert(source, dest, channels, rate)
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is needed for gain_db")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-af",
        "volume=%gdB" % gain_db,
        "-ar",
        str(rate),
        "-ac",
        str(channels),
        "-c:a",
        "pcm_s16le",
        dest,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed for %s:\n%s" % (source, r.stderr or r.stdout))
    dst_info = rt.probe(dest)
    return "%d Hz, %d-bit, %s (gain %+g dB)" % (
        dst_info[1],
        dst_info[2] * 8,
        "mono" if dst_info[0] == 1 else "stereo",
        gain_db,
    )


def set_up_key(tree, dotted, value):
    """Set an integer in the settings database (`Data_base/sqlite/up_common.sqlite`).

    `dotted` is `Section.Name`, e.g. `supervisor.Last_Source`. Values that live in a
    database are the safest kind of change this project can make: no code is patched, so
    the worst case is that the firmware ignores the value.
    """
    import sqlite3

    section, _, name = dotted.partition(".")
    if not name:
        sys.exit("%r should be Section.Name, e.g. supervisor.Last_Source" % dotted)
    path = os.path.join(tree, "Data_base", "sqlite", "up_common.sqlite")
    if not os.path.exists(path):
        sys.exit("no up_common.sqlite in this tree - is it an extracted media partition?")
    con = sqlite3.connect(path)
    try:
        cur = con.execute(
            "update UP_Keys set IntValue=? where Section=? and Name=?", (value, section, name)
        )
        if cur.rowcount < 1:
            sys.exit("no UP_Keys row for %s" % dotted)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def set_gui_ver(tree, value):
    """Set `GUI_VER` in the media partition's `Data_base/smeg.inf`.

    This is the **displayed** copy. The System Info screen reads `smeg.inf` from inside
    `system.bin`, not the module-level `NAV/smeg.inf` sitting beside it — editing the latter
    is the classic "looks right, changes nothing" mistake.

    `GUI_VER` ("Display version") is the only version field that is both visible and not
    gated on by the updater, so it is the safe place for a build marker. `VER:` and
    `media.inf` drive update decisions and must be left alone.
    """
    path = os.path.join(tree, "Data_base", "smeg.inf")
    if not os.path.exists(path):
        sys.exit("no Data_base/smeg.inf in this tree - is it an extracted media partition?")
    raw = Path(path).read_bytes()
    out, seen = [], False
    for line in raw.split(b"\r\n"):
        if line.startswith(b"GUI_VER:"):
            out.append(b"GUI_VER:" + str(value).encode() + b" ")
            seen = True
        else:
            out.append(line)
    if not seen:
        sys.exit("no GUI_VER line in Data_base/smeg.inf")
    Path(path).write_bytes(b"\r\n".join(out))
    return path


USER_DATA_WARNING = """
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  THIS BUILD REPLACES A DATABASE ON THE UNIT'S USER DATA PARTITION.

  /USER_DATA is where the unit keeps settings that belong to whoever is sitting
  in the car: paired phones, navigation destinations, radio presets, recent
  calls, trip data. The updater copies the payload below over it.

  Depending on whether that step merges per file or replaces the folder, this
  can reset any or all of that. The preset databases in system.bin do not touch
  it, which is exactly why settings edited there appear to do nothing.

  What it will write:
{files}

  If you are the person who drives this car, that is your call to make. If you
  are an agent or a tool doing this on someone else's behalf, STOP and ask them
  first, and tell them in these words what it may cost them.

  To proceed, the manifest must record the decision explicitly:

      "user_data": {{ "sqlite": [...], "accept_data_loss": true }}
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
"""


def warn_user_data(names):
    return USER_DATA_WARNING.format(files="\n".join("    - %s" % n for n in names))


def sqlite_inf(data):
    crc = zlib.crc32(data) & 0xFFFFFFFF
    signed = crc - 0x100000000 if crc & 0x80000000 else crc
    return ("CRC32: %d\r\n" % signed).encode()


def ship_user_data(out, tree, names, module):
    """Copy settings databases and their CRC sidecars into USER_DATA.

    The application reads its live settings from `/USER_DATA`, not the copy in `/SYSTEM`.
    The updater's `ManageSQLiteFiles` generates a `<database>.inf` beside every live SQLite
    file. Its format is the same signed-decimal CRC32 line used elsewhere in the package.
    Shipping the pair makes the payload complete before it reaches the unit.
    """
    sources = []
    for name in names:
        src = os.path.join(tree, "Data_base", "sqlite", name)
        if not os.path.exists(src):
            sys.exit("no %s in the extracted media tree" % name)
        sources.append((name, Path(src).read_bytes()))

    # The updater reads this payload from a path it has hard-coded, so the output folder name
    # and the module both matter. Say so here, while the name is still easy to change.
    folder = os.path.basename(os.path.normpath(os.path.abspath(out)))
    if folder != "SMEG_PLUS_UPG" or module != "NAV":
        print(
            "!!! the updater looks for this payload at the hard-coded path\n"
            "        /bd0/SMEG_PLUS_UPG/NAV/USER_DATA\n"
            "    (C_UPGRADE::UpgradeTask -> IsDirExist, then 'Copy of /USERDATA from /bd0 to"
            " NAND').\n"
            "    This build writes %s/%s/USER_DATA. Unless the folder on the stick is named\n"
            "    SMEG_PLUS_UPG and the module is NAV, the copy is SKIPPED SILENTLY and the\n"
            "    rest of the update still succeeds - which looks exactly like the settings\n"
            "    having had no effect." % (folder, module)
        )

    dest_dir = os.path.join(out, module, "USER_DATA", "user_data", "sqlite")
    os.makedirs(dest_dir, exist_ok=True)
    for name, data in sources:
        dest = os.path.join(dest_dir, name)
        Path(dest).write_bytes(data)
        Path(dest + ".inf").write_bytes(sqlite_inf(data))
        print("==> USER_DATA/%s + .inf (%d bytes)" % (name, len(data)))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="do not run the final pre-flight check (not recommended)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show the steps and what would change, without writing",
    )
    args = ap.parse_args()

    cfg = json.loads(Path(args.manifest).read_text())
    # Paths in a manifest are read the way a person would expect: `~` expands, and a
    # relative path is relative to the manifest itself rather than to wherever the command
    # happened to be run from.
    here = os.path.dirname(os.path.abspath(args.manifest))

    def resolve(p):
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(here, p))

    src = resolve(cfg["package"])
    out = resolve(cfg["out"])
    module = cfg.get("module", "NAV")

    if not os.path.isdir(src):
        sys.exit("no such package: %s\n  (from %r in %s)" % (src, cfg["package"], args.manifest))
    if os.path.abspath(src) == os.path.abspath(out):
        sys.exit("--out must differ from --package; never build in place")
    if os.path.exists(out):
        sys.exit("%s already exists — remove it or pick another --out" % out)

    app = cfg.get("app") or {}
    media = cfg.get("media") or {}
    tone_map = media.get("tones") or {}
    splash_map = media.get("splash") or {}
    name_map = media.get("names") or {}
    settings = media.get("settings") or {}
    gui_ver = media.get("gui_ver")
    user_data = cfg.get("user_data") or {}
    ud_sqlite = user_data.get("sqlite") or []
    any_media = bool(tone_map or splash_map or name_map or settings or gui_ver or ud_sqlite)

    if ud_sqlite and not user_data.get("accept_data_loss"):
        sys.exit(
            warn_user_data(ud_sqlite)
            + '\nRefusing to build. Add "accept_data_loss": true to the user_data '
            "section once the person who owns the car has agreed to it."
        )

    if ud_sqlite:
        print(warn_user_data(ud_sqlite))

    print("building %s -> %s (%s)" % (src, out, module))
    if args.dry_run:
        print("dry run: nothing will be written")

    work = tempfile.mkdtemp(prefix="smegbuild-")

    # 1. start from a copy, so the source stays a rollback
    if not args.dry_run:
        shutil.copytree(src, out, symlinks=True, ignore=shutil.ignore_patterns("._*", ".DS_Store"))
        for root, dirs, _ in os.walk(out):
            for d in list(dirs):
                if d in (".stage6", ".commandcode", ".git"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
    print("==> copied the package")

    # 2. application patches FIRST: patch_media later swaps CRCs inside ctrl.bin, and it
    #    has to be operating on a manifest that already carries the application change.
    #
    #    Each set is applied to the package built so far, not to `src`. Applying every set
    #    against the stock source would make each overlay a stock-plus-one-set package, and
    #    the last one copied would silently revert the others — they all rewrite the same
    #    image and manifests.
    for name in app.get("patches", []):
        p = os.path.join(ROOT, "patches", name if name.endswith(".json") else name + ".json")
        if not os.path.exists(p):
            sys.exit("no such patch set: %s" % p)
        o1 = os.path.join(work, "app-%s" % os.path.basename(name))
        run(
            [
                PY,
                tool("patch_smeg.py"),
                "--src",
                src if args.dry_run else out,
                "--out",
                o1,
                "--only",
                module,
                "--patches",
                p,
            ],
            "applying patch set %s" % name,
            args.dry_run,
        )
        if not args.dry_run:
            overlay(o1, out)

    if any_media:
        # 3. extract the media partition and make the edits in the tree
        tree = os.path.join(work, "media")
        backup = os.path.join(work, "backup")
        run(
            [
                PY,
                tool("patch_media.py"),
                "extract",
                "--package",
                out,
                "--module",
                module,
                "--tree",
                tree,
                "--backup",
                backup,
                "--backup-tones-only",
            ],
            "extracting the media partition",
            args.dry_run,
        )
        if not args.dry_run:
            rt = load_module("ringtones")
            sl = load_module("splash")

            for dest_rel, spec in tone_map.items():
                if isinstance(spec, str):
                    source, gain = spec, None
                else:
                    source, gain = spec["source"], spec.get("gain_db")
                slot = next((k for k, v in rt.SLOTS.items() if v[0] == dest_rel), None)
                if slot is None:
                    sys.exit("%s is not a known tone slot" % dest_rel)
                out_path = os.path.join(tree, dest_rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                print("==> %s: %s -> %s" % (slot, source, dest_rel))
                print(
                    "    %s"
                    % convert_tone(rt, source, out_path, rt.SLOTS[slot][1], rt.SLOTS[slot][2], gain)
                )
            for marque, image in splash_map.items():
                print("==> splash %s <- %s" % (marque, image))
                path = os.path.join(tree, sl.DIR, marque + ".pkg")
                pk = sl.Pkg(Path(path).read_bytes())
                new = {i: pk.image(i) for i in range(len(pk.chunks))}
                new[0] = sl.flip_bmp(sl.to_bmp(image))
                Path(path).write_bytes(sl.build(pk, new))
            for dotted, value in settings.items():
                n = set_up_key(tree, dotted, value)
                print("==> %s = %s  (%d row%s)" % (dotted, value, n, "" if n == 1 else "s"))
            if gui_ver is not None:
                set_gui_ver(tree, gui_ver)
                print(
                    "==> GUI_VER = %s  (Data_base/smeg.inf - shows as 'Display version')"
                    % gui_ver
                )
            for slot, name in name_map.items():
                if not (slot.startswith("ring") and slot[4:].isdigit()):
                    sys.exit("%s: names only apply to ring1..ring5" % slot)
                idx = int(slot[4:]) - 1
                print("==> %s shown as %r" % (slot, name))
                rt.set_ring_name(tree, idx, name)

        # 4. rebuild the partition and the checksum cascade
        o2 = os.path.join(work, "media-overlay")
        run(
            [
                PY,
                tool("patch_media.py"),
                "apply",
                "--package",
                out,
                "--module",
                module,
                "--tree",
                tree,
                "--out",
                o2,
            ],
            "rebuilding the media partition",
            args.dry_run,
        )
        if not args.dry_run:
            overlay(o2, out)
            if user_data.get("sqlite"):
                ship_user_data(out, tree, user_data["sqlite"], module)

    # 5. seal LAST — anything changed after this is unsealed and the unit rejects it
    if cfg.get("seal", True):
        run(
            [PY, tool("patch_contract.py"), "--package", out],
            "re-sealing the contract",
            args.dry_run,
        )

    # 6. final gate: the package must pass its own pre-flight. A build that would be
    #    rejected, or that sets a value the unit cannot accept, should fail here rather
    #    than on a stick in a car.
    if not args.dry_run and not args.skip_preflight:
        r = subprocess.run(
            [PY, tool("preflight.py"), "--package", out], capture_output=True, text=True
        )
        print(r.stdout.rstrip())
        if r.returncode != 0:
            sys.exit(
                "\n%s failed its own pre-flight (above) - not fit to flash.\n"
                "Fix it, or pass --skip-preflight if you know better." % out
            )

    shutil.rmtree(work, ignore_errors=True)
    if args.dry_run:
        print("\ndry run complete — nothing was written")
        return
    print("\nbuilt %s" % out)
    print(
        "check it before flashing:  python3 tools/splash.py --tree <tree> selftest"
        "  (and the cascade in docs/RUNNING.md)"
    )


if __name__ == "__main__":
    main()
