#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""The customisable assets in a SMEG+ media partition, with human-readable names.

The partition holds 845 files across directories that give no clue what is what —
`ring1RT.wav`, `MM_HoldOn_GED_8kHz.wav`, `AT_O3.png`, `GillSansPSA.ttf`. This knows
what each one is for, and turns the filename into a label a person can act on, so
"replace a ring tone" or "replace the radio logos" is a choice rather than a hunt.

It only ever *replaces* files that already exist: the partition's `system_ctrl.bin`
records are per-file, so adding a new one would need a record that does not exist.

usage:
    python3 tools/assets.py --tree media list
    python3 tools/assets.py --tree media list --group sounds
    python3 tools/assets.py --tree media export --group logos -o stock-logos/
    python3 tools/assets.py --tree media replace --asset radio-logos --with my-logos/
    python3 tools/assets.py --tree media replace --asset ring1 --with piano.mp3
"""

import argparse
import glob as globmod
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Group -> (human description, path glob relative to the media tree, kind)
# kind decides how a replacement is handled:
#   audio  converted to the slot's exact format
#   image  copied, and optionally checked for the right size
#   file   copied verbatim
GROUPS = [
    (
        "sounds",
        "Ring tones — the five the phone UI offers",
        "ring_tones/ring[1-5]RT.wav",
        "audio",
        ["ringtones", "ring tones", "rings"],
    ),
    (
        "sounds",
        "Call and status tones",
        "ring_tones/{busy,error,ok,ko}RT.wav",
        "audio",
        ["status tones", "call tones"],
    ),
    (
        "sounds",
        "Call-hold tones, one per language",
        "wait_tones/MM_HoldOn_*_8kHz.wav",
        "audio",
        ["wait tones", "hold music", "call hold"],
    ),
    (
        "sounds",
        "Touch feedback — buttons, menus, keyboard",
        "Data_base/boardfs/GUI_STYLE/GUIS_RESSOURCES/gui_sounds/*.wav",
        "audio",
        ["interface sounds", "gui sounds", "ui sounds", "touch sounds"],
    ),
    (
        "logos",
        "Radio station logos — 199 stations in three sizes",
        "Data_base/radio/logo/*/*.png",
        "image",
        ["radio logos", "station logos", "logos"],
    ),
    (
        "logos",
        "Marque logo packages — Peugeot, Citroen, DS",
        "Data_base/graphics/logo/*.pkg",
        "pkg",
        ["marque logos", "brand logos"],
    ),
    (
        "logos",
        "iPod logos, one per marque",
        "Data_base/graphics/logo/iPodLogo/*.bmp",
        "image",
        ["ipod logos"],
    ),
    (
        "graphics",
        "Browser portal artwork",
        "internet_default/portal/*.png",
        "image",
        ["portal", "browser"],
    ),
    (
        "graphics",
        "Browser status pictograms",
        "internet_default/PMS_picto/*.png",
        "image",
        ["pictograms", "pictos"],
    ),
    (
        "graphics",
        "Browser portal error image",
        "internet_default/config/*.png",
        "image",
        ["portal error"],
    ),
    (
        "graphics",
        "Front-panel animation frames",
        "AVR_img/*.png",
        "image",
        ["front panel", "avr", "animation"],
    ),
    (
        "fonts",
        "Interface typefaces",
        "Data_base/TMP/lib/fonts/*.ttf",
        "file",
        ["fonts", "typefaces", "ttf"],
    ),
    (
        "strings",
        "Interface text, one file per language",
        "Data_base/boardfs/GUI_STYLE/GUIS_RESSOURCES/gui_texts/*.xml.bin",
        "file",
        ["strings", "texts", "language"],
    ),
    (
        "config",
        "Layout and skin configuration",
        "Data_base/boardfs/GUI_STYLE/*.xml",
        "file",
        ["config", "layout"],
    ),
]

# Things whose names mean nothing on their own.
REPLACE = {
    "ring1RT": "Ring tone 1",
    "ring2RT": "Ring tone 2",
    "ring3RT": "Ring tone 3",
    "ring4RT": "Ring tone 4",
    "ring5RT": "Ring tone 5",
    "busyRT": "Engaged",
    "errorRT": "Error",
    "okRT": "Confirm",
    "koRT": "Failure",
    "BalayageZ0": "Page sweep",
    "Validation": "Confirm a panel",
    "Abandon": "Cancel / back",
    "Clavier": "Keyboard keys",
    "Welcome": "Welcome screen",
    "Brosser": "Brush",
    "DejaVuSans": "DejaVu Sans (fallback)",
    "GillSansPSA": "Gill Sans PSA (the main UI face)",
    "GillSansSLIDER": "Gill Sans, slider skin",
    "Ecube SLIDER": "Ecube, slider skin",
    "T9typoSLIDER": "T9 typography, slider skin",
    "TYPEC4SLIDER": "Type C4, slider skin",
    "PLAQUESgilsans": "Plaque style",
    "peugeot": "Peugeot",
    "citroen": "Citroen",
    "ds": "DS",
    "iPodLogoPeugeot": "iPod logo, Peugeot",
    "iPodLogoCitroen": "iPod logo, Citroen",
    "gui_config": "Layout, size, harmony id",
    "gui_harmonies": "Look-and-feel ids",
    "gui_languages": "Language ids",
    "gui_sounds": "Sound id to file map",
    "AVR_IMG1": "Animation frame 1",
    "AVR_IMG2": "Animation frame 2",
    "AVR_IMG3": "Animation frame 3",
    "AVR_IMG4": "Animation frame 4",
    "AVR_IMG5": "Animation frame 5",
    "AVR_IMG6": "Animation frame 6",
    "AVR_IMG7": "Animation frame 7",
    "AVR_IMG8": "Animation frame 8",
    "ErreurPortail_V2": "Portal error",
    "sprite_offline": "Portal, offline",
}

LANGS = {
    "CRC": "Czech",
    "CZC": "Czech",
    "DUN": "Dutch",
    "ENG": "English",
    "FRF": "French",
    "GED": "German",
    "HRH": "Croatian",
    "ITI": "Italian",
    "PLP": "Polish",
    "PTP": "Portuguese",
    "RUR": "Russian",
    "SPE": "Spanish",
    "TRT": "Turkish",
}

COUNTRIES = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CH": "Switzerland",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LU": "Luxembourg",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
}


def _tidy(stem):
    """Last-resort prettifier: split the filename into words a person can read."""
    out = stem.replace("_", " ").replace("-", " ").strip()
    for junk in ("8kHz", "RT", "  "):
        out = out.replace(junk, " ")
    return " ".join(out.split())


def label(path):
    """A human-readable name for one asset, from the filename and what we know of it."""
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]

    if stem in REPLACE:
        return REPLACE[stem]

    # wait tones: MM_HoldOn_<LANG>_8kHz
    if stem.startswith("MM_HoldOn_"):
        parts = stem.split("_")
        if len(parts) >= 3:
            return "Call hold — %s" % LANGS.get(parts[2], parts[2])

    # radio logos: CC_Station, in three sizes
    parts = stem.split("_", 1)
    if len(parts) == 2 and parts[0] in COUNTRIES and "radio/logo" in path.replace("\\", "/"):
        size = os.path.basename(os.path.dirname(path))
        return "%s — %s (%s)" % (COUNTRIES[parts[0]], parts[1], size.lower())

    for prefix, nice in (
        ("pgen_peugeot_", "Portal, Peugeot — "),
        ("pgen_citroen_", "Portal, Citroen — "),
    ):
        if stem.startswith(prefix):
            return nice + _tidy(stem[len(prefix) :].replace(".v2.pgen", ""))

    if stem.startswith("gui_text_strings_"):
        return "Interface text — %s" % stem.replace("gui_text_strings_", "")

    if stem.isdigit() and "PMS_picto" in path:
        return "Browser pictogram %s" % stem

    return _tidy(stem)


def find(tree, pattern):
    """Expand a group pattern (which may use braces) against the tree."""
    if "{" in pattern:
        head, rest = pattern.split("{", 1)
        opts, tail = rest.split("}", 1)
        hits = []
        for opt in opts.split(","):
            hits += globmod.glob(os.path.join(tree, head + opt + tail))
        return sorted(hits)
    return sorted(globmod.glob(os.path.join(tree, pattern)))


def catalogue(tree):
    """Everything the catalogue matches, grouped."""
    out = []
    for group, desc, pattern, kind, aliases in GROUPS:
        files = find(tree, pattern)
        if files:
            out.append((group, desc, pattern, kind, files, aliases))
    return out


def group_for(tree, name):
    """Catalogue entries matching a group name, an alias, a path fragment, or a label.

    Deliberately generous, but in a defined order, because the levels mean different
    things: an exact group name or alias selects the group, an **exact label** selects one
    file, and only then does a substring match anything. Without that order, asking for
    "Ring tone 2" pulls in every group whose text happens to contain the words.
    """
    entries = catalogue(tree)
    key = name.lower().replace("-", " ").replace("_", " ").strip()
    hits = []
    for entry in entries:
        group, desc, pattern, kind, files = entry[:5]
        names = entry[5] if len(entry) > 5 else []
        if key == group or key in names or key in desc.lower():
            hits.append(entry)
            continue
        exact = [f for f in files if key == label(f).lower()]
        if exact:
            hits.append((group, desc, pattern, kind, exact))
            continue
        sub = [
            f
            for f in files
            if key in label(f).lower()
            or key in os.path.relpath(f, tree).lower().replace("-", " ").replace("_", " ")
        ]
        if sub:
            hits.append((group, desc, pattern, kind, sub))
    return hits


def format_of(path, kind):
    if kind != "audio":
        return ""
    try:
        import wave

        w = wave.open(path, "rb")
        info = "%d Hz, %d-bit, %s" % (
            w.getframerate(),
            w.getsampwidth() * 8,
            "mono" if w.getnchannels() == 1 else "stereo",
        )
        w.close()
        return info
    except Exception:
        return ""


def cmd_list(args):
    tree = args.tree
    entries = catalogue(tree)
    if args.group:
        entries = [e for e in entries if e[0] == args.group.lower()]
        if not entries:
            sys.exit("no assets in group %r" % args.group)
    for group, desc, pattern, kind, files in (e[:5] for e in entries):
        print(
            "\n%s — %s  (%d file%s)"
            % (group.upper(), desc, len(files), "" if len(files) == 1 else "s")
        )
        show = files if args.all else files[: args.limit]
        for f in show:
            extra = format_of(f, kind)
            print(
                "    %-44s %s%s"
                % (label(f), os.path.relpath(f, tree), ("   " + extra) if extra else "")
            )
        if len(show) < len(files):
            print("    ... %d more (--all to see them)" % (len(files) - len(show)))


def cmd_export(args):
    tree = args.tree
    entries = group_for(tree, args.asset)
    if not entries:
        sys.exit("nothing matched %r - try `list`" % args.asset)
    os.makedirs(args.out, exist_ok=True)
    n = 0
    for group, desc, pattern, kind, files in (e[:5] for e in entries):
        for f in files:
            dest = os.path.join(args.out, os.path.basename(f))
            if os.path.exists(dest) and not args.force:
                continue
            shutil.copy2(f, dest)
            n += 1
    print("exported %d file(s) to %s" % (n, args.out))


def cmd_replace(args):
    tree = args.tree
    entries = group_for(tree, args.asset)
    if not entries:
        sys.exit("nothing matched %r - try `list`" % args.asset)

    src = args.with_
    if os.path.isdir(src):
        pool = [os.path.join(src, f) for f in os.listdir(src)]
    elif os.path.exists(src):
        pool = [src]
    else:
        sys.exit("no such file or directory: %s" % src)

    replaced = 0
    for group, desc, pattern, kind, files in (e[:5] for e in entries):
        if len(pool) == 1 and len(files) == 1:
            pairs = [(files[0], pool[0])]
        else:
            # match by name, so a directory of replacements maps onto the right files
            by_name = {os.path.basename(p): p for p in pool}
            pairs = [
                (f, by_name[os.path.basename(f)]) for f in files if os.path.basename(f) in by_name
            ]
            if not pairs:
                if len(files) > 1 and os.path.isfile(src):
                    sys.exit(
                        "%r covers %d files, so give me a directory of replacements "
                        "named like the originals, or name a single asset"
                        % (args.asset, len(files))
                    )
                sys.exit("no filenames in %s match anything in %r" % (src, args.asset))
        for dest, source in pairs:
            print("  %-40s <- %s" % (label(dest), os.path.basename(source)))
            if args.dry_run:
                continue
            if kind == "audio":
                import ringtones

                channels = 1
                rate = 44100
                try:
                    import wave

                    with wave.open(dest, "rb") as w:
                        channels, rate = w.getnchannels(), w.getframerate()
                except (wave.Error, OSError, EOFError):
                    pass  # not a readable WAV: keep the slot's defaults
                ringtones.convert(source, dest, channels, rate)
            else:
                shutil.copy2(source, dest)
            replaced += 1
    if args.dry_run:
        print("\ndry run - nothing written")
    else:
        print("\nreplaced %d file(s). Rebuild the partition and re-seal:" % replaced)
        print("  python3 tools/patch_media.py apply --package PKG --module NAV \\")
        print("      --tree %s --out overlay" % tree)
        print("  python3 tools/patch_contract.py --package PKG")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--tree", default="media", help="an extracted media partition (contains ring_tones/)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="everything replaceable, with readable names")
    p.add_argument(
        "--group", help="only this group: sounds, logos, graphics, fonts, strings, config"
    )
    p.add_argument("--limit", type=int, default=12, help="files to show per group (default 12)")
    p.add_argument("--all", action="store_true", help="show every file")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("export", help="copy the current assets out, as a backup or a template")
    p.add_argument("asset", help="a group name, a path fragment, or a label")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("replace", help="swap assets in for the current ones")
    p.add_argument("--asset", required=True, help="a group name, a path fragment, or a label")
    p.add_argument(
        "--with",
        dest="with_",
        required=True,
        help="a file (for a single asset) or a directory named to match",
    )
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_replace)

    args = ap.parse_args()
    if not os.path.isdir(args.tree):
        sys.exit("no such media tree: %s" % args.tree)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
