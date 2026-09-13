# Analysis notes

Reverse-engineering notes for the SMEG+ application, recorded while building the AUX
auto-switch patch. Everything here is derived from observing the author's own device
and firmware; **no vendor binaries are reproduced**. Addresses are for the
`SMEG5.43.A.R2` builds targeted in `patches/aux-autoswitch.json`.

## 1. Package layout

A SMEG+ upgrade package (`SMEG_PLUS_UPG/`) is a set of modules plus a manifest:

```
ctrl.bin                     root manifest: per-file CRC32 list for each module
contract.dat                 signed contract validated by the app, see MEDIA_PROTECTION.md
upgrade.out / upgrade_lib.out / UpgPlugin.out    the updater itself (PPC ELF)
BSP/SMEG_PLUS_{256,512}/     vxWorks.bin (RTOS), dbsystem.bin (40-byte descriptor)
RENESAS/FPComSMEG.mot        front-panel MCU firmware (Motorola S-record)
AUDIO_BT/  AUDIO_BT_256/     media partition tar + AppBin/f_BigQuick.bin
NAV/                         same, for navigation units
HARMONY/BigHarmony_N/        UI skins (BIG_HARMONY.bin + skins)
USERGUIDE/                   user-guide resources
```

Module checksums are recorded in `<module>_ctrl.bin`, and those files are themselves
checksummed in the root `ctrl.bin`. Any patched file therefore requires the whole cascade
to be recomputed — `tools/patch_smeg.py` does this.

## 2. The application image

`AppBin/f_BigQuick.bin` is:

```
0x0000..0x0800    header (version, sizes, segment descriptors, 0xdeadbeef markers)
0x0800            0x08 (compression marker)
0x0801..         a zlib stream
```

Inflating the stream yields the application image (`~32 MB` for `AUDIO_BT`,
`~40 MB` for `NAV`), loaded at `0x01000000`.

The media partition also ships absolute symbol maps under `Application/PKG/`
(`abs_symbols_base.txt.gz`, `abs_symbols.txt.gz`, `symbols_bsp.txt.gz`). The base map
lines up exactly with the inflated image — every symbol lands on a PowerPC function
prologue (`stwu r1,-N(r1) ; mflr r0`) — which is what makes symbol-level patching
possible.

## 3. Audio source model

Relevant classes/functions found in the base map:

```
C_MODULE_AUDIO::Get_aux_status / Set_aux_status / setAUXGain / Get_AUX_signal_status
Radio::Get_AUX_signal_status -> C_I2C_SMART_RADIO::Get_AUX_signal_status
C_MGR_SRC                     source manager (allocation, priorities, permanent sources)
C_HMI_AUDIO_APP_BASE          audio UI app  (IsAUXSRCAvailable, OnEventSelectAUX, …)
C_HMI_MEDIA_APP_BASE          media UI app  (HandleAudioAuxInputStatusChnged)
C_BCM_HMI_AUDIO_CLIENT        DBUS client to the audio server
```

Two distinct statuses exist:

- `Get_aux_status()` → `t_srv_audio_aux_status`, gated by a module flag at `this+0x74`
  (set to 1 in `C_MODULE_AUDIO::Open()` when the config getter succeeds).
- `Get_AUX_signal_status()` → raw AUX signal detection.

`C_HMI_AUDIO_APP_BASE::IsAUXSRCAvailable()` consults both; that is what drives the AUX
entry grey-out / enable behaviour in the source list.

## 4. Event chain

```
audio server
  --DBUS signal AUDIO_AUX_SIGNAL_STATUS_CHANGED-->
     C_BCM_HMI_AUDIO_CLIENT::AUDIO_AUX_SIGNAL_STATUS_CHANGED()
        -> C_DBUS_ClientInstantiate::SendMessage(0xcc)
           -> HMI event 0x613dc
              -> C_HMI_MEDIA_APP_BASE::HandleAudioAuxInputStatusChnged()
                 -> Get_aux_status()
                 -> GetMediaDevice(AUX)          <-- bails out here on failure
                 -> SetMediaDeviceState(AUX, 2) + C_HMI_SrcMgntBase::ActivateSource(true)
```

!!! warning "Correction: there are *two* AUX signals"

    Later analysis found that the DBUS interface `com/MM/BCM_Audio` carries **two**
    AUX notifications, not one:

    - `AUDIO_AUX_SIGNAL_STATUS_CHANGED` — used by the audio module's own mute
      management (`C_MODULE_AUDIO::Elab_AUDIO_AUX_SIGNAL_STATUS_CHANGED`).
    - `AUDIO_AUX_INPUT_STATUS_CHANGED` — and the HMI handler is named
      `HandleAudioAuxInputStatusChnged` (**Input**), which points at this one.

    So the event chain above may be the *signal* path while the auto-switch handler is
    driven by the *input* path. Which one actually fires on the car is the decisive open
    question, and is exactly what the spy capture in [Cheatcodes](CHEATCODES.md) is for.

The handler is registered in the HMI event table (entry: size `0x2c`, event id
`0x613dc`, handler pointer, function size `0x290`, type `7`).

## 5. Why it does not switch

Observed on the target car: AUX is listed and greys out / re-enables with signal, so
availability and signal detection both work — but the unit never switches to AUX on its
own. The event handler contains an early return:

```
023032d0  bl      GetMediaDevice          ; type 5 = AUX
023032e8  419e014c beq cr7, +0x14c        ; if (!ok) return;   <-- before ActivateSource
```

If the AUX media device lookup fails, the function returns before doing anything. That
is the single early exit consistent with the symptom, and it is what the second patch
removes.

## 6. Hardkey path (for a possible later trigger)

The HMI keyboard layer exposes:

```
C_HMI_KeyboardMessage::GetVKeyPressedData / GetVKeyReleasedData
C_HMI_KeyboardMessage::GetVKeyKeepPressedData     (long press)
C_HMI_KeyboardMessage::GetVKeyRepeatData
C_HMI_KeyboardMessage::GetVKeySimultaneusData     (simultaneous keys -> chords possible)
```

so a long-press or chord trigger is representable in principle; the `SRC` key is handled
by `C_HMI_AUDIO_CHANGE_SOURCE_0X_Menu::HandleVCIKey` / `HandleNextSourceKey` and by
`C_HMI_AUDIO_APP_BASE::HandleKeyboardMessage`.

### Why "long-press SRC to select AUX" is not a small patch

Disassembly of the actual handlers makes this look much less attractive than the API
surface suggests:

- **The source menu never sees a long press.** `C_HMI_AUDIO_CHANGE_SOURCE_0X_Menu::HandleVCIKey`
  reads only `GetVKeyReleasedData()`. It switches on the released key code: `0x4f` and
  `0x20051` call `HandleNextSourceKeyEv()` (the SRC cycle), `0x51` synthesises a click on
  the focused item. There is no keep-pressed branch to extend.
- **The only long-press hook that fires is global.** `C_MENU_STATE::ProcessEscKeyLongPress()`
  is a single implementation for *every* screen; it emits a system notification command
  (id `0x12`) which the unit routes to the product-code / system-information view. That is
  the existing SRC long-press behaviour. Replacing it would change that behaviour
  everywhere, not just in the audio app, and would break the existing shortcut.
- **The steering wheel does not report it.** The wheel's SRC produces press/release but
  no keep-pressed event reaching the audio application, so there is nothing to bind on
  that key at all.
- **Upstream, the feature is unfinished.** The image carries the string
  `ESC LONG PRESS handling should be done!!!`, emitted from
  `C_MENU_STATE::HandleTouchEvent` — i.e. long-press handling has stub paths in this
  firmware.

**Conclusion:** not implemented, and not recommended as a first step. It is a
disproportionately invasive change for a convenience shortcut. With
`IsAUXSRCAvailable()` patched, AUX is already reachable through the ordinary SRC cycle —
the auto-switch is the real fix for the switching problem.

## 7. Integrity chain

Verified by recomputation and search:

```
f_BigQuick.bin  --crc32-->  f_BigQuick.bin.inf  ("CRC32: <signed decimal>")
                --crc32-->  smeg.inf             (BIGQUICK_CRC32: <signed decimal>)
                --crc32-->  <module>_ctrl.bin    (4-byte big-endian CRC for each file)
<module>_ctrl.bin --crc32--> ctrl.bin
```

`contract.dat` is not referenced by `upgrade.out` — which is what an earlier pass through
these notes concluded from. That was wrong: the **application image** validates the media
against it in `C_BCM_UPGRADE::CheckTrustedSource()`, and a package with a modified
application image is rejected because of it. See
[Media protection](MEDIA_PROTECTION.md).

## 8. Updater behaviour relevant to flashing

Strings in `upgrade.out` show the update is incremental:

- `manageBootRomUpdateAndReboot: BootRom already done.`
- `ManageRenesasUpdateAndReboot: Renesas version '%s' == Mot. File version '%s'` (skip)
- `ManageBigQuickUpdate: '%s' is a cantidate!` / `WriteNANDBigQuick … return OK`

so an already-updated unit will not rewrite BootROM/Renesas; the BigQuick application is
rewritten when its content differs from what is stored.

## 9. Caveats

- The media contract has been regenerated successfully and the resulting package was
  accepted by a real unit — see [Hardware verification](VERIFICATION.md). The
  `IsAUXSRCAvailable()` patch is confirmed working there.
- **The automatic switch is still unproven.** Removing the early exit in
  `HandleAudioAuxInputStatusChnged()` was a hypothesis; it has not yet been observed
  causing a source change. If it does not, the AUX status event is not reaching that
  handler and the fix belongs on a path that provably runs.
- The `AUDIO_BT` and `AUDIO_BT_256` patch sets are verified against their images but have
  not been flashed.
- Re-flashing the same version does not change the displayed version strings, so
  behaviour is the only reliable confirmation. Do not use System Information to decide
  whether a patch is installed.

## 10. The AUX event chain, verified in the NAV image

!!! info "This section is the original trace; [The AUX chain](AUX_CHAIN.md) is the current one"

    That page carries the whole chain gate by gate, including the links found since — the
    listener registration upstream of the dispatch, and the four gates inside the handler,
    most of them executed rather than read. Prefer it when you want the state of play; this
    section stays because it records how the dispatch was first found.

Traced in `nav_app_image.bin` against `nav_syms.txt` — use those **together**; the 32 MB
`app_image.bin` is the AUDIO_BT image and reading it with the base symbol map gives a
different `HandleAudioAuxInputStatusChnged` address, which is an easy way to conclude the
NAV patch is pointing somewhere wrong when it is not.

```
audio server --DBUS msg 0xcb (203)--> C_HMI_MEDIA_APP_BASE::HandleDBUSMessage()
                                      @ 0x02309398, case at 0x02309638
                                        cmpwi cr7, r0, 0xcb
                                        beq   cr7, 0x2309fbc
                                          -> 0x02309fcc  bctrl HandleAudioAuxInputStatusChnged()

C_HMI_MEDIA_APP_BASE::HandleAudioAuxInputStatusChnged()      @ 0x0230331c
  02303410  bl  GetMediaDevice(type, media_device&)
  02303428  beq cr7, 0x2303574     handler+0x10c — the shared return path, what we nop
  02303434  beq cr7, 0x230348c     the aux-sticky target
  0230345c  bl  SetMediaDeviceState(...)
  02303484  bl  C_HMI_SrcMgntBase::ActivateSource(bool)
```

The handler has exactly one direct caller — the DBUS dispatch — plus a vtable entry.

!!! warning "Corrected by emulation"

    This page previously concluded that removing `0x02303428` *does* reach
    `ActivateSource`. Executing the function proved otherwise, twice over: the branch is
    never taken in the first place (the AUX media device is registered unconditionally, so
    `GetMediaDevice` succeeds), and when it *is* forced to fail, the nop only reaches
    `SetMediaDeviceState` — `GetMediaDevice` leaves the source-manager field null on its
    failure path, so the guard at `0x02303468` returns instead. See
    [Emulating the firmware](EMULATION.md).

**The consequence:** the patch is not the problem. If the unit does not switch by itself,
DBUS message **203** is not reaching the media app. That points at the always-active hook
rather than more surgery inside the handler, and it is a hypothesis that can be settled by
logging received DBUS ids rather than by flashing something.
