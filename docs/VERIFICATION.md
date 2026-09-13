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
| media phases ran | **yes** — Phase 0, Phase 3 and Phase 5 all observed |
| unit rebooted and came back up | **yes** — multiple Peugeot splash screens, then normally working |
| version strings changed | **no, and that is expected** — re-flashing the same release does not alter them |
| `IsAUXSRCAvailable()` patch | **confirmed working** — AUX no longer greys out with no signal |
| AUX in the SRC cycle | **confirmed** — FM → DAB → AM → USB → AUX |
| automatic switch to AUX | **not delivered, and this patch set never could** — see below |

!!! success "The important one"

    String 2099 is the unit's rejection of a package whose media does not match the signed
    contract. It did not appear, and the update proceeded to write the application image.
    **The re-seal works on hardware.** This was the blocker for the whole project.

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
| 15:44–15:49 | *diagnostic* | `Phase 5` / `Uncompress /SD.DIR` → `Uncompress /SD.DIR.TTS` |
| 15:52 | boot splash | `PEUGEOT` |
| 15:52 | source menu | `FM Radio` `DAB Radio` `AM Radio` `USB` `iPod` `Bluetooth` `AUX` |
| 15:53 | update dialog | `UPDATE LEVEL` / `Identification of media...` |
| 15:54 | update confirm | the same `Software update.` confirmation again |
| 15:55 | System Information | `SMEG5.43.A.R2` / `CD: 26482` / `Dated: 19-09-17` |

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
