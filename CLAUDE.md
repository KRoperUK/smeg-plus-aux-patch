# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read [AGENTS.md](AGENTS.md) as well — it holds the hard rules (no vendor firmware anywhere,
conventional commit titles, `main` is PR-only, warn before anything that destroys the car
owner's settings, do not automate the release PR approval). Those rules are not repeated here.

## Commands

No virtualenv is checked in. Every script declares its own dependencies in a PEP 723 header,
so `uv run` needs no setup:

```sh
uv run tools/patch_smeg.py --help
uv run tools/build_package.py --manifest builds/aux-only.json
uv run tools/patch_studio.py                  # the Qt GUI (fetches PySide6)
```

For the tests, lint and docs, create the venv the docs assume (Python 3.13 — Homebrew's
3.14 has a broken `ensurepip` and no PySide6 wheels):

```sh
uv venv --seed --python 3.13 .venv
uv pip install --python .venv/bin/python PySide6 pytest zensical ruff
```

```sh
.venv/bin/python -m pytest tests -q                       # full suite, no firmware needed
.venv/bin/python -m pytest tests/test_patch_smeg.py -q    # one file
.venv/bin/python -m pytest tests/test_studio.py -k preview -q # one test
.venv/bin/python -m ruff check tools tests                # lint (E9 + F only)
.venv/bin/python -m zensical build --strict               # docs; a broken anchor fails it
.venv/bin/zensical serve                                  # live docs preview on :8000
python3 tools/check_commit_msg.py --title "feat: ..."     # check a PR title before pushing
```

CI runs exactly `ruff check tools tests`, `pytest tests -q` and `zensical build --clean`.
Pre-commit additionally runs the tests, the strict docs build and `tools/check_no_firmware.sh`
on every commit, so a commit that breaks any of them cannot be made locally.

GUI tests skip without PySide6 and run headless via `QT_QPA_PLATFORM=offscreen`.

## Architecture

### What a package is

A user-supplied upgrade package is `SMEG_PLUS_UPG/<module>/…`, where `<module>` is one of
`NAV`, `AUDIO_BT`, `AUDIO_BT_256`. Two things inside it are patchable, and they are
independent formats:

* **the application** — `<module>/AppBin/f_BigQuick.bin`: a 0x800-byte header, a `0x08`
  marker at 0x800, then a zlib stream from 0x801 inflating to a raw PowerPC image based at
  `0x01000000`. Not encrypted. The shipped `abs_symbols_base.txt.gz` lines up exactly, so
  patches are located by symbol, never by pattern.
* **the media partition** — `<module>/system.bin`: a gzip'd tar extracted to a read-only
  `/SYSTEM/` on the unit. Holds ring tones, the seed settings database, logo bundles.
  Only *replacing* existing files is supported; adding one would need a new
  `system_ctrl.bin` record and that format is not fully understood.

### The checksum cascade

Every edit has to walk a chain of checksums back to the root manifest, and both patchers
own their own half of it:

```
f_BigQuick.bin -> f_BigQuick.bin.inf -> smeg.inf (BIGQUICK_CRC32) -> <module>_ctrl.bin -> ctrl.bin
system.bin     -> system_ctrl.bin + system.bin.inf (CRC + SIZE/SIZE_n) -> <module>_ctrl.bin -> ctrl.bin
```

On top of that, `contract.dat` seals the package. A modified package that is not re-sealed
is rejected on the unit with string 2099. `tools/patch_contract.py` re-seals it, extracting
the RSA key pair from the user's own `f_BigQuick.bin` at runtime — it ships no key material
and must never be changed to.

### Ordering (the part that fails silently)

1. application patches, 2. media rebuild against the **already application-patched** package,
3. contract re-seal **last**. Get 2 wrong and `ctrl.bin` is rebuilt without the application
change; get 3 wrong and the unit refuses the package. `tools/build_package.py` exists to own
this ordering — prefer it over running the tools by hand.

### Data-driven layers

* `patches/*.json` — one patch set per behaviour (`aux-autoswitch`, `aux-sticky`,
  `aux-always-available`, `diagnostic-logging`). Keyed by `variants.<module>`, each giving
  the file paths its cascade touches plus a list of `{addr, expect, bytes}` — `expect` is the
  original bytes, verified before anything is written. **A new `patches/*.json` beats new
  Python.**
* `builds/*.json` — whole-build manifests for `build_package.py`: which package, which
  module, which patch sets, media tones/names/settings, `seal`, and optionally `user_data`.

### Tools

| tool | role |
|---|---|
| `build_package.py` | manifest → finished package; shells out to the others in the correct order |
| `preflight.py` | validate a built package offline before it goes on a stick; reports unknowns as loudly as knowns |
| `patch_smeg.py` | application image patches + that half of the cascade |
| `patch_media.py` | `list`/`extract`/`restore`/`apply` on the media partition |
| `patch_contract.py` | re-seal `contract.dat` |
| `ringtones.py` | audio → the unit's tone formats (ffmpeg for non-WAV) |
| `patch_studio.py` | Qt front-end over ringtones + patch selection |
| `splash.py` | the `Data_base/graphics/logo/*.pkg` marque bundles (**not** the boot splash) |
| `unpack.py`, `mkelf.py`, `ppcdis.py`, `xref.py`, `callers.py` | the analysis tools every patch address was derived with; need `capstone`; untested |
| `check_commit_msg.py`, `check_no_firmware.sh` | the two enforcement hooks |

### Tests

`tests/helpers.py` and `tests/media_helpers.py` build a **synthetic package from scratch** —
header, zlib container, `.inf`, `smeg.inf`, tar, module and root manifests — so the whole
patch/repack path is exercisable with no vendor file present. Any new file format needs a
synthetic fixture here, never a binary.

## Firmware facts that are easy to get wrong

* **Addresses are per build.** `AUDIO_BT` and `AUDIO_BT_256` usually match; `NAV` is offset.
  Never copy an address between modules without re-deriving it.
* **`system.bin` settings are not the live settings.** It extracts to a read-only `/SYSTEM/`;
  the unit reads its actual settings from the `USER_DATA` partition. Editing the seed
  database alone changes nothing on the car (confirmed on hardware). Shipping a `USER_DATA`
  payload does work, but overwrites state the car owns — paired phones, destinations, presets —
  and `build_package.py` refuses it without `accept_data_loss: true`.
* **Version strings are not a safe marker.** The display reads `Data_base/smeg.inf` *inside*
  the media partition; editing `media.inf` can block the update outright. `GUI_VER` is the
  only safe visible field.
* **The updater reboots the unit** mid-update. Never propose updating while driving.
* Tone slot formats differ: ring/status tones are 16-bit **mono 44.1 kHz**, wait tones
  16-bit **stereo 8 kHz**.

## Claims

Patches are verified statically, and only partially on hardware — a re-sealed package has
flashed and the `IsAUXSRCAvailable()` change is confirmed, but the automatic switch itself
has not been observed working. Say what was verified and what still needs a car test; do not
claim a patch "works". See [docs/VERIFICATION.md](docs/VERIFICATION.md).
