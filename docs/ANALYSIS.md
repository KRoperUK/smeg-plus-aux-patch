# Analysis notes

Reverse-engineering notes for the SMEG+ application, recorded while building the AUX
auto-switch patch. Everything here is derived from observing the author's own device
and firmware; **no vendor binaries are reproduced**. Addresses are for the
`SMEG5.43.A.R2` builds targeted in `patches/aux-autoswitch.json`.

## 1. Package layout

A SMEG+ upgrade package (`SMEG_PLUS_UPG/`) is a set of modules plus a manifest:

```
ctrl.bin                     root manifest: per-file CRC32 list for each module
contract.dat                 high-entropy blob; not referenced by upgrade.out
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
`C_HMI_AUDIO_APP_BASE::HandleKeyboardMessage`. Not implemented here (the auto-switch is
the intended fix).

## 7. Integrity chain

Verified by recomputation and search:

```
f_BigQuick.bin  --crc32-->  f_BigQuick.bin.inf  ("CRC32: <signed decimal>")
                --crc32-->  smeg.inf             (BIGQUICK_CRC32: <signed decimal>)
                --crc32-->  <module>_ctrl.bin    (4-byte big-endian CRC for each file)
<module>_ctrl.bin --crc32--> ctrl.bin
```

`contract.dat` is not referenced anywhere in `upgrade.out` (its checks are CRC-only:
`VerifyCRC32ofFile`, `VerifyNANDBigQuick`), so it appears unused by the on-device updater.

## 8. Updater behaviour relevant to flashing

Strings in `upgrade.out` show the update is incremental:

- `manageBootRomUpdateAndReboot: BootRom already done.`
- `ManageRenesasUpdateAndReboot: Renesas version '%s' == Mot. File version '%s'` (skip)
- `ManageBigQuickUpdate: '%s' is a cantidate!` / `WriteNANDBigQuick … return OK`

so an already-updated unit will not rewrite BootROM/Renesas; the BigQuick application is
rewritten when its content differs from what is stored.

## 9. Caveats

- The patches are static and were not validated on hardware by the author of these notes.
- Patch 2 is a hypothesis at the observed early-exit; it may not be the only cause.
- Re-flashing the same version does not change the displayed version strings, so
  behaviour is the only reliable confirmation.
