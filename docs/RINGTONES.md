# Ring tones and wait tones

Custom audio on the head unit, and the tooling to prepare it.

## What the unit plays

All plain PCM WAV. Two formats, depending on the slot:

| slot(s) | path | format |
|---|---|---|
| `ring1` … `ring5` | `ring_tones/ringNRT.wav` | 16-bit **mono 44 100 Hz** |
| `busy`, `error`, `ok`, `ko` | `ring_tones/{busy,error,ok,ko}RT.wav` | 16-bit **mono 44 100 Hz** |
| `wait:<LANG>` | `wait_tones/MM_HoldOn_<LANG>_8kHz.wav` | 16-bit **stereo 8 000 Hz** |

Wait-tone languages: `CRC CZC DUN ENG FRF GED HRH ITI PLP PTP RUR SPE TRT`.
The `RT` suffix in the ring-tone filenames is part of the real name.

Full inventory with durations is in [Media partition](MEDIA_PARTITION.md).

## The tool

`tools/ringtones.py` — no Python dependencies; uses **ffmpeg** when it needs to decode
anything other than an already-correct WAV (so mp3, ogg, flac, m4a all work). Without
ffmpeg it will still copy a WAV that is already in the target format.

```sh
python3 tools/ringtones.py list                          # slots and expected formats
python3 tools/ringtones.py probe song.mp3                # what is this file?
python3 tools/ringtones.py export --tree media/ -o stock/ # back up the stock tones
python3 tools/ringtones.py convert song.mp3 --slot ring1 -o ring1RT.wav
python3 tools/ringtones.py stage song.ogg --slot ring5 --tree media/
```

`--tree` is an **extracted media partition** — a directory containing `ring_tones/`
and `wait_tones/`. `stage` converts to the exact format and writes it under the correct
filename, ready to be packed back up.

## GUI

`tools/ringtone_studio.py` (Qt / PySide6) wraps the same conversion, lets you preview
and export the stock tones, and builds patched packages from the bundled
`patches/*.json` definitions — including the always-enable-AUX and sticky-AUX variants.
Multiple definitions can be ticked at once; a conflicting address is reported rather
than silently applied.

```sh
pip install -r tools/requirements-gui.txt
python3 tools/ringtone_studio.py
```

The studio builds and runs (verified on macOS with PySide6 6.11.2 — it also has headless
GUI tests in `tests/test_studio.py`, which skip when PySide6 is absent). It has not been
used to produce a package that was then flashed to a car, so treat the end-to-end result
as unverified; the pieces it drives are covered by tests.

## The catch

The tones live **inside the media partition** (`system.bin`), so changing them means
repacking that gzip'd tar and rebuilding its checksum cascade — the same job as the
cheatcode menu and the version marker.

That repack used to be blocked on the `SIZE:` / `SIZE_1..SIZE_32` fields. It no longer
is: they are computable from the tar (see
[Media partition](MEDIA_PARTITION.md#the-size-fields-solved)).

That tool now exists — `tools/patch_media.py` swaps a file inside the tar and rebuilds
`system_ctrl.bin` -> `system.bin` -> `system.bin.inf` -> the module manifest -> the root
manifest. A replacement tone changes size, so the tar definitely changes; the `SIZE`
fields are carried forward by exactly that change.
