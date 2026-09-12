# Media partition (`system.bin`)

The head unit keeps its user-facing data partition in `AUDIO_BT/system.bin` /
`NAV/system.bin`: a gzip-compressed **tar** that is extracted to `/SYSTEM/` on the unit.

Nothing here is patched by the current tooling — the app-image patcher only touches
`AppBin/f_BigQuick.bin`. This document records what lives in the partition and what
would be involved in editing it.

## How the partition is described

| file | role |
|---|---|
| `<module>/system.bin` | the gzipped tar (media partition payload) |
| `<module>/system.bin.inf` | `CRC32:` plus `SIZE:` / `SIZE_1..SIZE_32` |
| `<module>/system_ctrl.bin` | per-file CRC32 list for everything inside the tar |
| `<module>/system_data.bin` (+ `.inf`) | separate small data payload |
| `<module>_ctrl.bin` | module manifest: CRC32 for `system.bin`, its `.inf`, `system_ctrl.bin`, … |
| `ctrl.bin` (root) | CRC32 for each `<module>_ctrl.bin` |

So a single file inside the partition sits under a long cascade:

```
ring_tones/ring1RT.wav
  -> system_ctrl.bin      (per-file CRC)
  -> system.bin           (tar+gzip content)
  -> system.bin.inf       (CRC32 + SIZE fields)  +  <module>_ctrl.bin
  -> ctrl.bin             (root manifest)
```

**Open question / blocker:** the meaning of `SIZE:` and `SIZE_1..SIZE_32` in
`system.bin.inf` is not yet confirmed. They do not equal the compressed file size or
the uncompressed tar size, so any edit that changes the tar needs this cracked first.
That is why media edits (ringtones, version marker, cheatcode menu) are parked
pending a safe rebuild.

## Top-level layout

```
Data_base/          sqlite databases, boardfs GUI resources, graphics/radio logos, fonts
Application/        PKG/ (symbol maps), CCOD/ (cheatcode libraries), BlackFin/
ring_tones/         phone call / status tones  (see below)
wait_tones/         network call-hold tones, one per language
AVR_img/            front-panel AVR images
internet_default/   browser portal defaults
```

## Ring tones — `/SYSTEM/ring_tones/`

All are **RIFF/WAVE, Microsoft PCM, 16-bit, mono, 44 100 Hz**. The five `ringN` files are
the selectable ringtones; the rest are call/status tones.

| file | duration | size |
|---|---|---|
| `ring1RT.wav` | 1.78 s | 157 018 |
| `ring2RT.wav` | 3.58 s | 315 816 |
| `ring3RT.wav` | 3.58 s | 316 264 |
| `ring4RT.wav` | 1.78 s | 156 830 |
| `ring5RT.wav` | 3.56 s | 313 838 |
| `busyRT.wav` | 4.49 s | 396 206 |
| `errorRT.wav` | 0.22 s | 19 900 |
| `koRT.wav` | 0.22 s | 19 900 |
| `okRT.wav` | 0.22 s | 19 724 |

The `RT` suffix is part of the real filename — the application image contains the
literal strings `ring1RT.wav` … `ring5RT.wav` as well as `/busy.wav`, `/error.wav`,
`/ok.wav` and `/ring1.wav` … `/ring5.wav`, so more than one form exists in the code.

Relevant code: `C_SRV_RING_TOUCH` (`srvPlayTouch`, `srvSetCurrentIDTone`,
`SetRingFilePath`), `C_FS_STORAGE_CTRL_PATH::GetRingTonesDir`, and
`GetRingToneList` / `GetRingtoneID` / `SetRingToneID` behind the phone settings UI.

**Custom ringtones** would mean replacing `ringNRT.wav` with your own file in the same
format, keeping the filename. That is a media-partition edit, i.e. blocked on the same
rebuild question above (and your replacement WAV will not be the same size, so the tar
definitely changes).

## Wait tones — `/SYSTEM/wait_tones/`

Network call-hold tones, one per language: **RIFF/WAVE, PCM, 16-bit, stereo, 8 000 Hz**.

```
MM_HoldOn_CRC_8kHz.wav  14.60 s      MM_HoldOn_ITI_8kHz.wav  21.82 s
MM_HoldOn_CZC_8kHz.wav  12.85 s      MM_HoldOn_PLP_8kHz.wav  18.43 s
MM_HoldOn_DUN_8kHz.wav  20.25 s      MM_HoldOn_PTP_8kHz.wav  19.40 s
MM_HoldOn_ENG_8kHz.wav  17.31 s      MM_HoldOn_RUR_8kHz.wav  19.49 s
MM_HoldOn_FRF_8kHz.wav  20.49 s      MM_HoldOn_SPE_8kHz.wav  19.31 s
MM_HoldOn_GED_8kHz.wav  22.15 s      MM_HoldOn_TRT_8kHz.wav  14.09 s
MM_HoldOn_HRH_8kHz.wav  18.46 s
```

Path helper: `C_FS_STORAGE_CTRL_PATH::GetWaitTonesDir`. The suffixes are PSA language
codes (`CRC` Czech, `ENG` English, `FRF` French, `GED` German, `ITI` Italian, … ).
