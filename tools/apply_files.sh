#!/bin/sh
# Overlay the changed files produced by patch_smeg.py onto a copy of your package.
#
# Copy the original package somewhere first, e.g.
#   cp -R SMEG_PLUS_UPG /Volumes/USB/SMEG_PLUS_UPG
# then
#   sh tools/apply_files.sh SMEG_PLUS_UPG_mod /Volumes/USB/SMEG_PLUS_UPG
#
# usage: apply_files.sh PATCHED_DIR DEST_PACKAGE_DIR
set -e

P="${1:?usage: apply_files.sh PATCHED_DIR DEST_PACKAGE_DIR}"
D="${2:?usage: apply_files.sh PATCHED_DIR DEST_PACKAGE_DIR}"

[ -d "$P" ] || { echo "no such patched dir: $P" >&2; exit 1; }
[ -d "$D" ] || { echo "no such destination package dir: $D" >&2; exit 1; }

( cd "$P" && find . -type f ! -name 'README*' ) | while read -r f; do
    mkdir -p "$D/$(dirname "$f")"
    cp "$P/$f" "$D/$f"
    echo "  patched $f"
done
echo "done -> $D"
