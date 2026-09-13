#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""Ring tone / wait tone tool for SMEG+ — inspect, convert and stage custom audio.

The unit plays plain PCM WAV:

    ring_tones/ring1RT.wav .. ring5RT.wav     16-bit mono   44100 Hz
    ring_tones/{busy,error,ok,ko}RT.wav       16-bit mono   44100 Hz
    wait_tones/MM_HoldOn_<LANG>_8kHz.wav      16-bit stereo  8000 Hz

`convert` produces a file in exactly the right format from anything ffmpeg can read
(mp3, ogg, flac, m4a, ...). If ffmpeg is not installed, WAV input that is already in
the target format is accepted and copied; anything else is refused with a clear
message. `stage` writes the converted file into an extracted media-partition tree
under the correct name, ready for repacking.

Note: the WAVs live inside the media partition (`system.bin`). Repacking that tar is
tracked separately and is not done here — `stage` prepares the tree.

usage:
    python3 tools/ringtones.py list
    python3 tools/ringtones.py export --tree media/ -o out/
    python3 tools/ringtones.py convert song.mp3 --slot ring1 -o ring1RT.wav
    python3 tools/ringtones.py stage song.ogg --slot ring5 --tree media/
    python3 tools/ringtones.py probe some.wav
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import wave

RING_DIR = "ring_tones"
WAIT_DIR = "wait_tones"
WAIT_LANGS = [
    "CRC",
    "CZC",
    "DUN",
    "ENG",
    "FRF",
    "GED",
    "HRH",
    "ITI",
    "PLP",
    "PTP",
    "RUR",
    "SPE",
    "TRT",
]

# slot -> (relative path template, channels, sample rate)
SLOTS = {}
for _n in range(1, 6):
    SLOTS["ring%d" % _n] = ("%s/ring%dRT.wav" % (RING_DIR, _n), 1, 44100)
for _n in ("busy", "error", "ok", "ko"):
    SLOTS[_n] = ("%s/%sRT.wav" % (RING_DIR, _n), 1, 44100)
for _lang in WAIT_LANGS:
    SLOTS["wait:%s" % _lang] = ("%s/MM_HoldOn_%s_8kHz.wav" % (WAIT_DIR, _lang), 2, 8000)


def resolve_slot(name):
    if name not in SLOTS:
        sys.exit("unknown slot %r\nknown slots: %s" % (name, ", ".join(sorted(SLOTS))))
    return SLOTS[name]


def have_ffmpeg():
    return shutil.which("ffmpeg") is not None


def probe(path):
    """Return (channels, rate, width) for a WAV, or None if it isn't one."""
    try:
        with wave.open(path, "rb") as w:
            return (w.getnchannels(), w.getframerate(), w.getsampwidth())
    except Exception:
        return None


def describe(path):
    info = probe(path)
    if info is None:
        size = os.path.getsize(path) if os.path.exists(path) else 0
        return "not WAV (or unreadable), %d bytes" % size
    ch, rate, width = info
    return "%d Hz, %d-bit, %s" % (rate, width * 8, "mono" if ch == 1 else "stereo")


def convert(src, dst, channels, rate):
    """Convert src to a 16-bit PCM WAV at the given channel count / sample rate."""
    if not os.path.exists(src):
        sys.exit("no such file: %s" % src)

    info = probe(src)
    if info == (channels, rate, 2):
        shutil.copyfile(src, dst)
        return "already in target format (copied)"

    if not have_ffmpeg():
        sys.exit(
            "ffmpeg is required to convert %s.\n"
            "  target: %d Hz, 16-bit, %s\n"
            "  Install ffmpeg (e.g. `brew install ffmpeg`) or supply a WAV that is "
            "already in the target format."
            % (describe(src), rate, "mono" if channels == 1 else "stereo")
        )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        src,
        "-ac",
        str(channels),
        "-ar",
        str(rate),
        "-c:a",
        "pcm_s16le",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        sys.exit("ffmpeg failed:\n%s" % (r.stderr.strip() or r.stdout.strip()))
    return "converted with ffmpeg"


def cmd_list(_args):
    print("%-12s %-42s %s" % ("SLOT", "FILE", "FORMAT"))
    for name in sorted(SLOTS, key=lambda k: (k.startswith("wait"), k)):
        rel, ch, rate = SLOTS[name]
        print("%-12s %-42s %d Hz, 16-bit, %s" % (name, rel, rate, "mono" if ch == 1 else "stereo"))


def cmd_probe(args):
    print("%s: %s" % (args.input, describe(args.input)))


def require_media_tree(tree):
    """A media tree must have at least one of the tone directories, or we are pointed wrong."""
    if not any(os.path.isdir(os.path.join(tree, d)) for d in (RING_DIR, WAIT_DIR)):
        sys.exit(
            "%s does not look like an extracted media partition (no %s/ or %s/)\n"
            "Pass the directory that contains them, not the package folder."
            % (tree, RING_DIR, WAIT_DIR)
        )


def cmd_export(args):
    tree = args.tree
    require_media_tree(tree)
    os.makedirs(args.output, exist_ok=True)
    n = 0
    for sub in (RING_DIR, WAIT_DIR):
        d = os.path.join(tree, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".wav"):
                shutil.copyfile(os.path.join(d, f), os.path.join(args.output, f))
                n += 1
    print("exported %d file(s) to %s" % (n, args.output))


def cmd_convert(args):
    rel, ch, rate = resolve_slot(args.slot)
    dst = args.output or os.path.basename(rel)
    how = convert(args.input, dst, ch, rate)
    print("%s -> %s (%s)\n  %s" % (args.input, dst, how, describe(dst)))


def cmd_stage(args):
    rel, ch, rate = resolve_slot(args.slot)
    require_media_tree(args.tree)
    dst = os.path.join(args.tree, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    how = convert(args.input, dst, ch, rate)
    print("staged %s -> %s (%s)\n  %s" % (args.input, dst, how, describe(dst)))
    print(
        "\nThe WAV lives inside the media partition (system.bin). Repacking that tar is\n"
        "tracked separately - see docs/MEDIA_PARTITION.md."
    )


# The names the phone UI shows are not in the WAVs — they are rows in
# Data_base/sqlite/up_common.sqlite, table UP_Keys, Section 'phone', Name 'Ringing_List',
# one row per Idx. Replacing a tone changes what you hear; renaming changes what you see.
UP_COMMON = "Data_base/sqlite/up_common.sqlite"
NAME_SECTION = "phone"
NAME_KEY = "Ringing_List"


def _name_db(tree):
    import sqlite3

    path = os.path.join(tree, UP_COMMON)
    if not os.path.exists(path):
        sys.exit("no %s in this tree — is it an extracted media partition?" % UP_COMMON)
    return sqlite3.connect(path), path


def ring_names(tree):
    """The ringtone display names, in Idx order (empty if the tree has no such database)."""
    path = os.path.join(tree or "", UP_COMMON)
    if not os.path.exists(path):
        return []
    import sqlite3

    con = sqlite3.connect(path)
    try:
        return [
            r[0]
            for r in con.execute(
                "select StringValue from UP_Keys where Section=? and Name=? order by Idx",
                (NAME_SECTION, NAME_KEY),
            )
        ]
    finally:
        con.close()


def set_ring_name(tree, index, name):
    """Rename one entry of the list. `index` is the Idx column, not the ring number."""
    con, _ = _name_db(tree)
    try:
        cur = con.execute(
            "update UP_Keys set StringValue=? where Section=? and Name=? and Idx=?",
            (name, NAME_SECTION, NAME_KEY, index),
        )
        if cur.rowcount != 1:
            sys.exit(
                "expected to update exactly one row at Idx=%d, updated %d" % (index, cur.rowcount)
            )
        con.commit()
    finally:
        con.close()
    return name


def cmd_names(args):
    names = ring_names(args.tree)
    if not names:
        print("no %s rows found" % NAME_KEY)
        return
    for i, n in enumerate(names):
        print("  Idx %-2d  %s" % (i, n))
    print("\nIdx 0..4 are the names for ring1..ring5 as the phone UI lists them.")


def cmd_rename(args):
    names = ring_names(args.tree)
    m = re.match(r"ring(\d)$", args.slot)
    if not m:
        sys.exit("--slot must be ring1..ring5 (the names are the phone ringtone list)")
    idx = int(m.group(1)) - 1
    if idx >= len(names):
        sys.exit("this tree only has %d names" % len(names))
    old = names[idx]
    set_ring_name(args.tree, idx, args.name)
    print("%s: %r -> %r  (Idx %d)" % (args.slot, old, args.name, idx))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show the slots and the format each expects").set_defaults(
        fn=cmd_list
    )

    p = sub.add_parser("probe", help="describe an audio file")
    p.add_argument("input")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("export", help="copy the stock WAVs out of an extracted media tree")
    p.add_argument("--tree", required=True)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("convert", help="convert a file to a slot's format")
    p.add_argument("input")
    p.add_argument("--slot", required=True)
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_convert)

    p = sub.add_parser("stage", help="convert and place a file into an extracted media tree")
    p.add_argument("input")
    p.add_argument("--slot", required=True)
    p.add_argument("--tree", required=True, help="extracted media partition (contains ring_tones/)")
    p.set_defaults(fn=cmd_stage)

    p = sub.add_parser("names", help="list the ringtone names the phone UI shows")
    p.add_argument("--tree", required=True)
    p.set_defaults(fn=cmd_names)

    p = sub.add_parser("rename", help="change one of those names")
    p.add_argument("--tree", required=True)
    p.add_argument("--slot", required=True, help="ring1..ring5")
    p.add_argument("--name", required=True)
    p.set_defaults(fn=cmd_rename)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
