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
        "names":  { "ring1": "Piano Riff" }
      },
      "seal": true
    }

Every section is optional. `app.patches` names files in `patches/`; `media.tones` maps a
partition-relative destination to a source audio file of any format ffmpeg reads;
`media.splash` maps a marque to an image; `media.names` renames the ringtone entries the
phone UI shows.

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
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
           "-af", "volume=%gdB" % gain_db, "-ar", str(rate), "-ac", str(channels),
           "-c:a", "pcm_s16le", dest]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed for %s:\n%s" % (source, r.stderr or r.stdout))
    dst_info = rt.probe(dest)
    return "%d Hz, %d-bit, %s (gain %+g dB)" % (
        dst_info[1], dst_info[2] * 8, "mono" if dst_info[0] == 1 else "stereo", gain_db)


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
        cur = con.execute("update UP_Keys set IntValue=? where Section=? and Name=?",
                          (value, section, name))
        if cur.rowcount < 1:
            sys.exit("no UP_Keys row for %s" % dotted)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


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


def ship_user_data(out, tree, names, module):
    """Copy settings databases into the package's USER_DATA payload.

    `system.bin` extracts to /SYSTEM/, which is read-only: the application reads its live
    settings from a separate NAND partition, /USER_DATA. The updater has a step for this
    (`C_UPGRADE::ManageSQLiteFiles`) which copies them from
    `<stick>/<module>/USER_DATA/user_data/sqlite/`, but only if the package ships that
    directory - ours never did, which is why editing system.bin changed nothing on the unit.

    Shipping the whole tree would take the unit's personal state with it, so this copies only
    the named databases.
    """
    dest_dir = os.path.join(out, module, "USER_DATA", "user_data", "sqlite")
    os.makedirs(dest_dir, exist_ok=True)
    for name in names:
        src = os.path.join(tree, "Data_base", "sqlite", name)
        if not os.path.exists(src):
            sys.exit("no %s in the extracted media tree" % name)
        shutil.copy2(src, os.path.join(dest_dir, name))
        print("==> USER_DATA/%s (%d bytes)" % (name, os.path.getsize(src)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--skip-preflight", action="store_true",
                    help="do not run the final pre-flight check (not recommended)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the steps and what would change, without writing")
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
    user_data = cfg.get("user_data") or {}
    any_media = bool(tone_map or splash_map or name_map or settings)

    ud_sqlite = user_data.get("sqlite") or []
    if ud_sqlite and not user_data.get("accept_data_loss"):
        sys.exit(warn_user_data(ud_sqlite) +
                 "\nRefusing to build. Add \"accept_data_loss\": true to the user_data "
                 "section once the person who owns the car has agreed to it.")

    if ud_sqlite:
        print(warn_user_data(ud_sqlite))

    print("building %s -> %s (%s)" % (src, out, module))
    if args.dry_run:
        print("dry run: nothing will be written")

    work = tempfile.mkdtemp(prefix="smegbuild-")

    # 1. start from a copy, so the source stays a rollback
    if not args.dry_run:
        shutil.copytree(src, out, symlinks=True,
                        ignore=shutil.ignore_patterns("._*", ".DS_Store"))
        for root, dirs, _ in os.walk(out):
            for d in list(dirs):
                if d in (".stage6", ".commandcode", ".git"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
    print("==> copied the package")

    # 2. application patches FIRST: patch_media later swaps CRCs inside ctrl.bin, and it
    #    has to be operating on a manifest that already carries the application change.
    for name in app.get("patches", []):
        p = os.path.join(ROOT, "patches", name if name.endswith(".json") else name + ".json")
        if not os.path.exists(p):
            sys.exit("no such patch set: %s" % p)
        o1 = os.path.join(work, "app-%s" % os.path.basename(name))
        run([PY, tool("patch_smeg.py"), "--src", src, "--out", o1, "--only", module,
             "--patches", p], "applying patch set %s" % name, args.dry_run)
        if not args.dry_run:
            overlay(o1, out)

    if any_media:
        # 3. extract the media partition and make the edits in the tree
        tree = os.path.join(work, "media")
        backup = os.path.join(work, "backup")
        run([PY, tool("patch_media.py"), "extract", "--package", out, "--module", module,
             "--tree", tree, "--backup", backup, "--backup-tones-only"],
            "extracting the media partition", args.dry_run)
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
                print("    %s" % convert_tone(rt, source, out_path, rt.SLOTS[slot][1],
                                              rt.SLOTS[slot][2], gain))
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
            for slot, name in name_map.items():
                if not (slot.startswith("ring") and slot[4:].isdigit()):
                    sys.exit("%s: names only apply to ring1..ring5" % slot)
                idx = int(slot[4:]) - 1
                print("==> %s shown as %r" % (slot, name))
                rt.set_ring_name(tree, idx, name)

        # 4. rebuild the partition and the checksum cascade
        o2 = os.path.join(work, "media-overlay")
        run([PY, tool("patch_media.py"), "apply", "--package", out, "--module", module,
             "--tree", tree, "--out", o2], "rebuilding the media partition", args.dry_run)
        if not args.dry_run:
            overlay(o2, out)
            if user_data.get("sqlite"):
                ship_user_data(out, tree, user_data["sqlite"], module)

    # 5. seal LAST — anything changed after this is unsealed and the unit rejects it
    if cfg.get("seal", True):
        run([PY, tool("patch_contract.py"), "--package", out], "re-sealing the contract",
            args.dry_run)

    # 6. final gate: the package must pass its own pre-flight. A build that would be
    #    rejected, or that sets a value the unit cannot accept, should fail here rather
    #    than on a stick in a car.
    if not args.dry_run and not args.skip_preflight:
        r = subprocess.run([PY, tool("preflight.py"), "--package", out],
                           capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode != 0:
            sys.exit("\n%s failed its own pre-flight (above) - not fit to flash.\n"
                     "Fix it, or pass --skip-preflight if you know better." % out)

    shutil.rmtree(work, ignore_errors=True)
    if args.dry_run:
        print("\ndry run complete — nothing was written")
        return
    print("\nbuilt %s" % out)
    print("check it before flashing:  python3 tools/splash.py --tree <tree> selftest"
          "  (and the cascade in docs/RUNNING.md)")


if __name__ == "__main__":
    main()
