#!/bin/sh
# Guard against committing vendor firmware, packages or big binaries.
#
# The project's hard rule is that no Peugeot/Citroen/DS/Stellantis/Magneti Marelli
# firmware, upgrade package, symbol map or recovered key material is ever committed,
# uploaded or stored. `.gitignore` covers the obvious paths, but an explicit `git add -f`
# or a copy under a new name would slip past it — this checks what is actually staged.
set -eu

MAX_KB=1024

# Files that only ever exist as part of a vendor package or a dump of one.
PATTERNS="
f_BigQuick.bin
system.bin
system_data.bin
system_ctrl.bin
system_data_ctrl.bin
contract.dat
flasher.inf
flasher.crc
smeg.inf
media.inf
vxWorks.bin
dbsystem.bin
upgrade.out
upgrade_256.out
upgrade_lib.out
UpgPlugin.out
abs_symbols_base.txt
abs_symbols.txt
symbols_bsp.txt
"

staged=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
[ -n "$staged" ] || exit 0

fail=0

for f in $staged; do
    base=$(basename "$f")

    # exact vendor filenames
    for p in $PATTERNS; do
        if [ "$base" = "$p" ]; then
            echo "BLOCKED: $f looks like vendor firmware/package content (matches '$p')"
            fail=1
        fi
    done

    # the other package manifests and the MCU image
    case "$base" in
        *_ctrl.bin|*.mot|*.bigharmony.ini|SMEG_PLUS_UPG|SMEG_PLUS_UPG.*)
            echo "BLOCKED: $f looks like vendor package content"
            fail=1
            ;;
    esac

    # size: nothing legitimate in this repo is anywhere near a megabyte
    if [ -f "$f" ]; then
        kb=$(wc -c < "$f" | tr -d ' ')
        kb=$((kb / 1024))
        if [ "$kb" -gt "$MAX_KB" ]; then
            echo "BLOCKED: $f is ${kb} KB — too large for this repository"
            fail=1
        fi
    fi
done

# symbol maps are gzipped inside the package, so catch them by content too
for f in $staged; do
    [ -f "$f" ] || continue
    case "$f" in
        *.gz|*.txt|*.txt.gz)
            if gzip -dc "$f" 2>/dev/null | head -c 2000 | grep -qE "abs_symbols|C_HMI_|C_BCM_" 2>/dev/null; then
                echo "BLOCKED: $f looks like a vendor symbol map"
                fail=1
            fi
            ;;
    esac
done

if [ "$fail" -ne 0 ]; then
    echo ""
    echo "Refusing to commit. This repository contains no vendor firmware — see NOTICE.md."
    echo "If this is a false positive, commit with --no-verify and explain why."
    exit 1
fi
