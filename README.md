# smeg-plus-aux-patch

Reverse-engineering notes and tooling for patching **PSA / Stellantis "SMEG+"**
infotainment firmware so the **AUX audio source is selected automatically** when a
signal appears — the thing you want when an aftermarket CarPlay/Android-Auto piggyback
(such as CarABC / AutoABC) feeds its audio into the head unit's AUX input.

Tested against: **Peugeot 208 (2015), SMEG+ iV1, hardware diversity `NAV`,
firmware `SMEG5.43.A.R2` (CD 26482, 19-09-17)** — but the same approach applies to the
non-NAV (`AUDIO_BT`) builds.

> ## No vendor firmware is included
> This repository contains **only original reverse-engineering notes and scripts**.
> It does **not** contain any Peugeot / Citroën / DS / Stellantis / Magneti Marelli
> firmware, upgrade packages, symbol maps, or other copyrighted binaries — those are
> not distributed here and `.gitignore` is set up to keep them out.
>
> To use these tools you must supply your **own** legally obtained firmware upgrade
> package. You are responsible for complying with the laws and licence terms that apply
> to your own device and software.

---

## Background

The head unit's application is delivered as `AppBin/f_BigQuick.bin`: a **0x801-byte
header** followed by a **zlib stream** that inflates to a raw **PowerPC** image loaded
at `0x01000000`. The release also ships absolute symbol maps
(`Application/PKG/abs_symbols_base.txt.gz`) which line up with that image, so the
firmware can be patched by symbol rather than by blind search.

The firmware already contains the auto-switch logic, in
`C_HMI_MEDIA_APP_BASE::HandleAudioAuxInputStatusChnged()`, reached via the event chain:

```
audio server --DBUS--> C_BCM_HMI_AUDIO_CLIENT::AUDIO_AUX_SIGNAL_STATUS_CHANGED()
  -> internal message 0xcc -> HMI event 0x613dc
  -> HandleAudioAuxInputStatusChnged() -> SetMediaDeviceState()/ActivateSource()
```

Two things stop that from actually switching on some units:

1. `C_HMI_AUDIO_APP_BASE::IsAUXSRCAvailable()` only reports AUX as available when the
   vehicle configuration already has it and a signal is present.
2. `HandleAudioAuxInputStatusChnged()` **returns early if `GetMediaDevice(AUX)` fails**,
   before it ever calls `ActivateSource()`.

The patch set addresses both. See [`docs/ANALYSIS.md`](docs/ANALYSIS.md) for the full
write-up and [`docs/PATCHES.md`](docs/PATCHES.md) for exact addresses and bytes.

## Supported builds / patches

| build | app image | `IsAUXSRCAvailable` | `…StatusChnged +0x10c` |
|---|---|---|---|
| `AUDIO_BT` (512) | `AUDIO_BT/AppBin/f_BigQuick.bin` | `0x02247718` → `li r3,1 ; blr` | `0x023032e8` → `nop` |
| `AUDIO_BT_256` | `AUDIO_BT_256/AppBin/f_BigQuick.bin` | `0x02247718` → `li r3,1 ; blr` | `0x023032e8` → `nop` |
| `NAV` | `NAV/AppBin/f_BigQuick.bin` | `0x02247858` → `li r3,1 ; blr` | `0x02303428` → `nop` |

Patches are data-driven — see [`patches/aux-autoswitch.json`](patches/aux-autoswitch.json).

## Requirements

- [uv](https://docs.astral.sh/uv/) — the scripts declare their own dependencies, so
  `uv run tools/<script>` needs no setup. See [Running the tools](docs/RUNNING.md).
- `ffmpeg` for audio conversion (mp3/ogg/flac/...); WAV needs nothing.
- Your own SMEG+ upgrade package, laid out as `SMEG_PLUS_UPG/…`
- `capstone` is only needed by the disassembly helper (`tools/ppcdis.py`).

## Usage

### 1. Inspect (optional)

```sh
python3 tools/unpack.py SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin app_nav.bin
```

### 2. Patch a copy of the package

```sh
uv run tools/patch_smeg.py --src SMEG_PLUS_UPG --out SMEG_PLUS_UPG_mod
```

```sh
python3 tools/patch_smeg.py \
    --src SMEG_PLUS_UPG \
    --out SMEG_PLUS_UPG_mod
```

This inflates each app image, applies the patches (verifying the original bytes first),
re-deflates it, and rebuilds the whole checksum cascade:

```
f_BigQuick.bin -> f_BigQuick.bin.inf + smeg.inf + <module>_ctrl.bin -> ctrl.bin
```

Use `--only NAV` to patch a single variant, or `--patches my.json` for your own patch
set.

### 3. Flash

Put the modified package folder at the root of a **FAT32** USB stick and run the normal
SMEG+ update on the car (engine running). See [`docs/FLASHING.md`](docs/FLASHING.md).

## Tools

| tool | purpose |
|---|---|
| `tools/unpack.py` | inflate `f_BigQuick.bin` → raw PPC image (and re-pack) |
| `tools/patch_smeg.py` | apply a patch set and rebuild the CRC cascade |
| `tools/mkelf.py` | wrap a raw image + symbol map into a disassemblable PPC ELF |
| `tools/ppcdis.py` | PowerPC disassembler with symbol/call resolution |
| `tools/xref.py` | find code that references a string, address or pointer |
| `tools/callers.py` | find direct (`bl`) callers of a function |
| `tools/patch_media.py` | rebuild a media partition (ring tones, resources) |
| `tools/ringtones.py` | convert custom audio to the unit's ring/wait tone formats |
| `tools/ringtone_studio.py` | Qt front-end: ringtone conversion + patch builder (optional) |
| `tools/apply_files.sh` | overlay patched files onto a package copy |

```sh
pip install capstone
python3 tools/ppcdis.py app_nav.bin abs_symbols_base.txt 0x0230331c 0x02303460
```

## Documentation

Also published as a docs site: <https://smeg.kroper.uk/> (Zensical, built and deployed by GitHub Actions).


| doc | contents |
|---|---|
| [`docs/ANALYSIS.md`](docs/ANALYSIS.md) | application image format, symbol maps, the AUX event chain, why the switch fails |
| [`docs/RUNNING.md`](docs/RUNNING.md) | how to run everything with `uv` / `uvx` |
| [`docs/PATCHES.md`](docs/PATCHES.md) | exact addresses and bytes per build |
| [`docs/FLASHING.md`](docs/FLASHING.md) | preparing the USB stick and flashing |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how the whole firmware fits together: modules, HMI framework, messaging, subsystems, databases |
| [`docs/FLASH_CHAIN.md`](docs/FLASH_CHAIN.md) | BSP/flash layout, the updater's phases and gates, the manifest format used above |
| [`docs/MEDIA_PARTITION.md`](docs/MEDIA_PARTITION.md) | media partition layout, ringtones and wait tones, and the checksum cascade |
| [`docs/CHEATCODES.md`](docs/CHEATCODES.md) | cheatcode list, entry mechanism, spy/diagnostics system |
| [`docs/RELEASING.md`](docs/RELEASING.md) | conventional commits and the automatic release/changelog flow |
| [`docs/RINGTONES.md`](docs/RINGTONES.md) | ring/wait tone formats, the converter, and the Qt studio |
| [`docs/VERSION_STRINGS.md`](docs/VERSION_STRINGS.md) | what the version screens read, and how the updater gates on them |

## Development environment

A virtualenv with the GUI and test dependencies already exists (Python 3.13 — your
Homebrew `python3` is 3.14, where `ensurepip` is broken and PySide6 has no wheels):

```sh
.venv/bin/python tools/ringtone_studio.py     # the GUI
.venv/bin/python -m pytest tests -q           # the test suite
```

Recreate it with `uv venv --seed --python 3.13 .venv && uv pip install --python
.venv/bin/python PySide6 pytest`, or use plain `pip install -r requirements-dev.txt`.

## Tests

`tests/` builds a **synthetic package from scratch** — no vendor firmware is
needed — and asserts the patch/repack path, the `expect` byte check, the CRC cascade
and the docs nav. Run them with `python -m pytest tests -q`; CI runs the same on every
pull request.

## Licence

MIT — see [`LICENSE`](LICENSE). The scripts are the author's own work. No third-party
firmware is covered by, or included under, this licence. See [`NOTICE.md`](NOTICE.md)
for the trademark and no-firmware statements.
