# Hardware verification

What has actually been confirmed on a car, as opposed to in the test suite. The patches
were static and unit-tested against a synthetic fixture; this page records what happened
when a patched, contract re-sealed package was flashed for real.

**Test unit:** Peugeot 208 (2015), SMEG+ iV1, hardware ID `155`, hardware diversity
`NAV`, running `SMEG5.43.A.R2` (CD 26482, 19-09-17). Package built from `NAV` with the
default patch set (`aux-autoswitch`: both `IsAUXSRCAvailable()` and the
`HandleAudioAuxInputStatusChnged()` early exit), re-sealed with
`tools/patch_contract.py`, application image CRC `0x7c310f0f`.

## Result summary

| check | outcome |
|---|---|
| contract check (string 2099, *"update file is protected and cannot be copied"*) | **not triggered** — the re-sealed package was accepted |
| application image written | **yes** — updater reached `AppBin flashing` |
| media phases ran | **yes** — Phases 0, 3 and 5 observed in this run; Phase 6 observed in a later one |
| unit rebooted and came back up | **yes** — multiple Peugeot splash screens, then normally working |
| version strings changed | **no, and that is expected** — re-flashing the same release does not alter them |
| `IsAUXSRCAvailable()` patch | **confirmed working** — AUX no longer greys out with no signal |
| AUX in the SRC cycle | **confirmed** — FM → DAB → AM → USB → AUX |
| automatic switch to AUX | **not delivered, and this patch set never could** — see below |

!!! success "The important one"

    String 2099 is the unit's rejection of a package whose media does not match the signed
    contract. It did not appear, and the update proceeded to write the application image.
    **The re-seal works on hardware.** This was the blocker for the whole project.

## Second flash — the `USER_DATA` retry (2026-09-14)

A second patched package (`builds/aux-default-retry.json`) was flashed to the same unit on the
same day, to try `supervisor.Last_Source = 7` for the first time. It carried a **beacon** —
`clock.Time_Zone` moved from `16` to `0` — so that "the payload did not apply" could be told
apart from "the value is wrong".

| check | outcome | how it is known |
|---|---|---|
| update ran | **yes** — offered and installed fully | on the unit |
| application image | **patched** — AUX still does not grey out with no signal | on the unit; same as the first flash |
| `USER_DATA` payload applied | **no** — the time zone did not change | on the unit; that is exactly what the beacon tests |
| the unit's own state | **undisturbed** — paired phones and presets intact | on the unit |
| boot source | **FM radio**, not AUX | on the unit |
| `src` behaviour | unchanged; AUX is not offered first | on the unit — and expected: `src` order is issue #66, never part of this patch set |

!!! warning "The folder-name explanation is falsified"

    The stick was inspected afterwards and the payload was present at exactly the path the
    updater tests — `SMEG_PLUS_UPG/NAV/USER_DATA/user_data/sqlite/up_common.sqlite` — with its
    **build** timestamp intact (12:38), not the flash time. A write by the updater would have
    moved that timestamp. So `IsDirExist("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA")` had every reason
    to succeed, and "the payload was skipped because the folder was named
    `SMEG_PLUS_UPG_auxdefault`" no longer explains the failure.

**`Last_Source = 7` has therefore still not been tested on a car** — indeed no value has, because
the payload has never been observed to apply. The boot-to-FM result carries no information about
whether `7` is the right number.

What the updater would do with the payload, **read from `upgrade.out`, not executed**:

- `UpgradeTask` copies it with `xcopy_blk("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA", "/USER_DATA")`,
  under a bare `IsDirExist` test with no fallback, in the block that continues **Phase 1**. That
  block is reached only when the persisted step (`readStep`, `this+0xc0`) is `0` or `1`; the
  switch `goto`s past it for any higher step.
- `C_UPGRADE::RestoreDataFromUSB()` runs unconditionally just before it and copies from a base
  path held at `this+0x24` into `/USER_DATA` and `/USER_DATA_BACKUP`.
- The updater logs all of this to `/SYSTEM_TMP_DATA/spy/UPG/UPG_log.txt` on the unit
  (`C_UPGRADE::MakeLogArchive` rotates it). Since that lives in the spy directory, `SPYSTORE`
  copies it to a stick — see issue **#24**.

### Root cause, from the updater's own log (2026-09-14)

The log came off the unit with `SPYSTORE` (see [Cheatcodes](CHEATCODES.md)), and it shows the copy
**did** run — the step gate was not the problem:

```
copying dir  /bd0/SMEG_PLUS_UPG/NAV/USER_DATA/user_data  -> /USER_DATA/user_data
copying dir  .../USER_DATA/user_data/SQLITE             -> /USER_DATA/user_data/SQLITE
copying file .../SQLITE/up_common.sqlite                -> .../SQLITE/up_common.sqlite
(tUpgrade): Copy of /USERDATA from /bd0 to NAND
```

**`SQLITE`, uppercase.** The unit's own dump names the path the application actually uses — in its
open file table and in a database error — as lowercase `sqlite`:

```
/USER_DATA/user_data/sqlite/navigation.sqlite
ERROR: <up_common> [CMMSQLDataBaseImp::BackUp error : disk I/O error
       from </USER_DATA/user_data/sqlite/up_common.sqlite>]
```

FAT hands out uppercase 8.3 short names, and the updater named the destination directory from what
it read off the stick. The payload landed in a sibling directory that differs only by case, which
the application never opens.

**Confirmed from the unit's own settings dump** (`CMMUPKeys::ShowStatus`, 271 keys):

```
supervisor.Last_Source.0            <int> : 1
supervisor.Last_Source_Priority.0   <int> : 10
supervisor.Src_Radio_SchedPos.0     <int> : 7
```

`Last_Source` is still the factory `1`, so `7` never reached the live database.

Two further differences in the same log, either of which would also have to be fixed:

- The payload shipped **no `.inf` sidecar**, while every database in the live directory has one
  (`up_common.sqlite.inf`).
- `RestoreDataFromUSB` looks for a **per-unit** directory — `/bd0/00FE…0035` style, named after
  the unit itself — not the package path; and `SaveDataOnUSB`, which would have created it, never
  ran at all (zero mentions in the log).

### Later flash report — the case-workaround package

The package staged after identifying the FAT case problem was flashed again. The unit still
booted to FM and the SRC button still followed its normal cycle. **No new SPYSTORE capture was
made after that flash.** The dump discussed below is timestamped 18:29; the case-workaround
payload and its `.inf` on the stick are timestamped 19:06, so that dump describes the earlier
run and cannot prove how the later one named its destination. That is two separate results:

- **The application patches remain installed, but do not change either behaviour.** Normal SRC
  order is expected: no shipped patch reorders it. Boot-to-AUX depended on the database payload,
  not `IsAUXSRCAvailable()` or the inert status-handler edit.
- **The old live-database capture supplied FM.** The 18:29 SPY capture says both
  `6639::Last_Source : 1 (0x1)` and `supervisor.Last_Source.0 <int> : 1`; it also records
  `Current_source ... SRC_TUNER`. That is direct runtime evidence for the earlier uppercase-copy
  run, not the later case-workaround flash.

The updater log in that earlier capture names the copied directory uppercase:

```
copying dir  .../USER_DATA/user_data/SQLITE -> /USER_DATA/user_data/SQLITE
copying file .../SQLITE/up_common.sqlite    -> .../SQLITE/up_common.sqlite
```

So the proposed long-filename workaround was **not demonstrated by this flash**. Either the FAT
entry on the flashed stick was still exposed as `SQLITE`, or the updater canonicalised it; the log
cannot distinguish those. Do not call that workaround hardware-confirmed.

The same log shows what happened to the existing settings before that payload copy: it copied the
live lowercase `/USER_DATA/user_data/sqlite` tree to temporary storage, formatted `/USER_DATA`,
and restored the tree — including `up_common.sqlite`, navigation databases and audio data — before
copying the separate uppercase payload directory. That supports **preservation** of the old data,
but it does not prove whether a particular phone pairing survived; only checking the unit can do
that.

!!! note "The spy dump is a general diagnostic, not just this log"

    `SPYSTORE` also yielded `abs_symbols_base.txt.gz` (98 365 lines) and `symbols_bsp.txt.gz`
    (22 497 lines) — the application and BSP symbol tables `AGENTS.md` describes but which the
    repository does not ship. The analysis tools resolve names with them instead of `?`. The
    dump additionally carries a task/exception capture, which is where the settings listing
    above came from.

## Observed update sequence

Captured from photographs taken during the update, ordered by capture time. Screens marked
*diagnostic* are the blue bootloader/flasher screens with yellow monospace text; the rest
are the normal touchscreen UI.

| time | screen | verbatim text |
|---|---|---|
| 15:34 | update dialog | `UPDATE LEVEL` / `Identification of media...` |
| 15:37 | update dialog | `UPDATE LEVEL` / `Checking compatibility...` |
| 15:37 | update confirm | `Software update.` / `From version:` `CD 26482` / `To version number:` `CD 26482` / `Keep the engine running.` / `The system will restart.` / `Continue?` `Yes` `No` |
| 15:40–15:41 | boot splash ×3 | `PEUGEOT` |
| 15:41 | *diagnostic* | `Renesas Upd...` / `FPComSMEG.N...` |
| 15:41 | *diagnostic* | `AppBin Upgrade...` / `AppBin flashing` / `(Upgrade in progress)` |
| 15:41 | *diagnostic* | `Phase 0` / formatting `/SYSTEM` / `(please wait)` |
| 15:42 | *diagnostic* | `Phase 0` / defragmenting `/USER-DATA/BACKUP` |
| 15:42 | *diagnostic* | `Phase 3` / `Uncompress /SYSTEM` |
| 15:44 | *diagnostic* | `Phase 3` / `Check the result of uncompression of /SYSTEM/` / `Check progression : 6%` |
| 15:44–15:49 | *diagnostic* | `Phase 5` / `Uncompress /SD_DIR` → `Uncompress /SD_DIR_TTS` / `Free space on SD: 2190624 Kbytes` |
| 15:52 | boot splash | `PEUGEOT` |
| 15:52 | source menu | `FM Radio` `DAB Radio` `AM Radio` `USB` `iPod` `Bluetooth` `AUX` |
| 15:53 | update dialog | `UPDATE LEVEL` / `Identification of media...` |
| 15:54 | update confirm | the same `Software update.` confirmation again |
| 15:55 | System Information | `SMEG5.43.A.R2` / `CD: 26482` / `Dated: 19-09-17` |

### Phase 6, from a later session the same day

A second capture at **17:26** — a separate flash, not part of the 15:34–15:55 run above —
shows the phase that sequence never caught:

```
Phase 6
Management of ZA files

(please wait)

The product must reboot in 2 s
```

This fills the gap between the last diagnostic screen at 15:49 and the boot splash at
15:52: the run does not end after Phase 5, it goes on to Phase 6 and **reboots itself from
there**. The reboot at the end of an update is Phase 6's doing, not an unexplained restart.

`Management of ZA files` is `C_UPGRADE::ManageZAFiles()` at `0000fd04` in `upgrade.out` —
see [Boot and update chain](FLASH_CHAIN.md#3-the-package-ships-its-own-symbol-tables). The ZA
files themselves are the ones copied from `/SYSTEM_DATA` to `/USER_DATA`, described in
[What is reachable](CAPABILITIES.md).

The update-confirmation dialog appears **twice**, at 15:37 and again at 15:54 — after the
unit had already completed the update and come back up. That is consistent with the stick
being left in or re-inserted and the unit offering the update again; the System
Information screens follow a minute later. The write itself is the 15:37 pass, since the
flasher screens run immediately after it.

A phase number of 1 appears once, in a blurred frame, alongside a word ending in
`BACKUP`; it is not legible enough to record as fact.

The diagnostic screens carry a fixed header that identifies the media being flashed:

```
Media version :        26482
Upgrade version :      5.3.3
BootRom version :      BSP-215.6.PLUSINT May 26 2017, 13:23:13
UBoot version :        06.03 Apr 22 2013 - 15:57:07
Hardware ID :          155
Hardware diversity :   NAV
Renesas version :      05.e3.01
```

These map exactly onto the package contents — `Upgrade version 5.3.3` is `SUBVER` in
`upgrade.out.inf`, `Media version 26482` is `VER` in `media.inf`, and `05.e3.01` is the
`FPComSMEG.mot` version — which confirms the unit was reading **our** package.

### Multiple reboots

At least four `PEUGEOT` splash screens appear in the series, interleaved with the
diagnostic screens. That matches the `Manage*AndReboot` naming in
[Boot and update chain](FLASH_CHAIN.md): the unit restarts after the BootROM, U-Boot,
Renesas and application steps so the new code runs next.

### Progress and free-space figures

The only percentage captured is `Check progression : 6%` during the Phase 3 verification
pass. The diagnostic screens otherwise show free space rather than progress, and the
figures change as partitions are rewritten:

| partition | values observed |
|---|---|
| `/SYSTEM` | 107384 → 107776 → 97452 → 73256 Kbytes |
| SD | 2717184 → 2706080 → 2190624 Kbytes |

## Behaviour observed afterwards

- **AUX stays selectable with no signal.** On stock firmware the AUX tile greys out when
  nothing is connected; after the patch it remains available. This is
  `IsAUXSRCAvailable()` returning true, confirmed on hardware.
- **AUX is in the SRC cycle.** Pressing SRC steps FM → DAB → AM → USB → AUX as normal.
- **Long-pressing SRC does not select AUX.** That behaviour was never implemented — the
  idea is tracked as an issue, not shipped in this build. Note that on-screen SRC
  long-press is already bound by the firmware to the product-code/system-information
  view (`C_MENU_STATE::ProcessEscKeyLongPress`), and the steering-wheel SRC does not
  deliver a keep-pressed event to the audio application at all.
- **Automatic switching did not happen, and the patch could not have caused it.** See
  below — this is now explained rather than open.

## What this does *not* prove

- **The auto-switch was never going to work from this patch.** The edit that removes the
  early exit in `HandleAudioAuxInputStatusChnged()` is in the flashed image and is inert:
  emulating the function shows the branch is never taken (the AUX media device is
  registered unconditionally, so `GetMediaDevice(AUX)` succeeds), and that forcing the
  failure case still stops one guard later, because `GetMediaDevice` leaves the
  source-manager field null when it fails. See
  [Emulating the firmware](EMULATION.md) for the runs.

    This does not mean the car test was wasted — it confirmed the re-seal, the flash and
    `IsAUXSRCAvailable()`. It means the remaining question is upstream of the handler:
    **is the handler entered at all, and does the AUX status query return a signal?** Note
    that the handler discards that query's return value, so a failed query is
    indistinguishable from "no signal" and lands in the change-detector as "nothing
    changed". Settle it with the diagnostic build before flashing anything else.

    The handler logs its own name on **every** exit — `HandleAudioAuxInputStatusChnged() -`,
    at level 1, on the shared return path. That would settle "is it entered at all?" in one
    flash, if the log went anywhere: `Log_msg`'s sink is stubbed out in this build, so the
    message is formatted and discarded. Giving the firmware an output path is the
    prerequisite, and is still open — see [Patch reference](PATCHES.md).
- **Version strings are not a marker.** System Information still reads `SMEG5.43.A.R2` /
  `CD 26482` after a successful patched flash. See
  [Version strings](VERSION_STRINGS.md) for why. Do not use them to decide whether a
  patch is installed — use behaviour.
- **Single unit, single build.** All of the above is `NAV` on one car. The `AUDIO_BT`
  and `AUDIO_BT_256` patch sets are verified against their images but have not been
  flashed.

## Reproducing

See [Flashing](FLASHING.md) for preparing the stick and
[Media protection](MEDIA_PROTECTION.md) for why the contract must be regenerated.
