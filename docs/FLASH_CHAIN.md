# Boot and update chain

What boots the unit, what the USB updater does, and in what order. Derived from the
package layout, the byte structure of the manifests, and the human-readable message
strings inside `upgrade.out` (an unstripped PowerPC ELF).

## 1. Flash layout

`BSP/SMEG_PLUS_<variant>/flasher.inf` is three fields per line — **path, address,
CRC** (the updater logs `(ReadField_InFlasherInfFile): Field: '%s', Path = '%s',
Address = '0x%X', CRC = '0x%X'`):

```
BSP/SMEG_PLUS_512/flasher.inf
  SMEG_PLUS_UPG/BSP/SMEG_PLUS_512/vxWorks.bin   0x720000  71242c66
  SMEG_PLUS_UPG/BSP/SMEG_PLUS_512/dbsystem.bin  0x180000  215167f7

BSP/SMEG_PLUS_256/flasher.inf
  SMEG_PLUS_UPG/BSP/SMEG_PLUS_256/vxWorks.bin   0x420000  731ae273
  SMEG_PLUS_UPG/BSP/SMEG_PLUS_256/dbsystem.bin  0x180000  718c41b5
```

| image | 256 build | 512 build |
|---|---|---|
| `vxWorks.bin` (RTOS) | `0x420000` | `0x720000` |
| `dbsystem.bin` | `0x180000` | `0x180000` |

**256 vs 512** is the NAND/board size, not a firmware feature level. The two BSP trees
differ only in the `vxWorks.bin` image and its address; the updater selects a tree from
the hardware type (`GetHWType`, `SMEG_PLUS_256/` vs `SMEG_PLUS_512/`) and the 256 units
use the dedicated relauncher `upgrade_256.out` ("Relaunch For 256"). This package ships
both, with the root `flasher.inf`/`flasher.crc` mirroring the 512 variant.

### `dbsystem.bin` — the 40-byte vxWorks descriptor

Despite being tiny, it is meaningful. The updater logs:

```
VxWorks.bin parameters in dbsystem are (size: %d ==? %d, crc: 0x%X ==? 0x%X, Nb blocks = %d)
```

and it embeds the matching `vxWorks.bin` CRC32 (`71242c66` for 512, `731ae273` for
256), plus a leading byte equal to the top byte of the load address (`0x72` / `0x42`).
So it is the **size / CRC / block-count descriptor** used to cross-check `vxWorks.bin`
before flashing. Exact per-field offsets are not yet pinned down.

### Other BSP files

- `flasher.crc` is the CRC32 of `flasher.inf` (confirmed: the value equals the CRC the
  root manifest records for `/flasher.inf`).
- `BSP/SMEG_PLUS_<variant>_ctrl.bin` lists exactly the six BSP files.

### Front-panel MCU

`RENESAS/FPComSMEG.mot` is **Motorola S-record** (starts `S0` "start>", then `S2`/`S3`
records), version `05.e3.01`, with two LVDS configuration words
(`RENCONF_1_LVDS`, `RENCONF_2_LVDS`). Flashed by `ManageRenesasUpdateAndReboot`.

## 2. The updater

`upgrade.out` / `upgrade_256.out` (entry modules) with `upgrade_lib.out` and
`UpgPlugin.out` (plugin). Entry flow, from symbol names plus emitted messages:

```
C_UPGRADE::UpgradeTask()
  LaunchUpgrade()
    CheckVersions()
    CheckCtrlFilesBeforeLaunchingUpgrade()      validate every *_ctrl.bin
    ManageBootRomUpdateAndReboot()              BSP
    ManageUBootUpdateAndReboot()                U-Boot
    ManageRenesasUpdateAndReboot()              front-panel MCU
    ManageBigQuickUpdate()                      application image
    ManageHarmoniesVersions() / UpgradeHarmoniesIfNeeded()   UI skins
    Phase 2..6                                  media partition, SD, userguide, db_dwnl
```

It emits `=== PHASE %d ===>>> End : %ld seconds` markers and finishes with
`<<<<<<< The product must restarting in 5 s >>>>>>>`. The `Manage*AndReboot` naming
indicates the unit reboots after the BootROM, U-Boot and Renesas steps so the new
low-level code runs next.

### Skip gates (why a re-flash is usually small)

```
manageBootRomUpdateAndReboot: BootRom already done.
ManageRenesasUpdateAndReboot: Renesas version '%s' == Mot. File version '%s'   -> skip
```

So on an already-current unit, the boot ROM and the MCU are skipped and only the parts
whose content differs are written.

### The application image

```
ManageBigQuickUpdate: '%s' is a cantidate!
ManageBigQuickUpdate: WriteNANDBigQuick ('%s').
VerifyNANDBigQuick : CRC of data BigQuick is NOK / WriteNANDBigQuick - CRC on source file / CRC on the flash
```

It scans `AppBin/`, rejects non-binaries, and treats a file as a **candidate when its
checksum differs from what is stored**. It then writes and reads back to verify. If the
running BSP is too old to expose `WriteNANDBigQuick` it refuses
(`Error loading symbol WriteNANDBigQuick, it's an old BSP!!!`,
`BSP Not compatible. Please use the loader button...`).

This is why a patched `f_BigQuick.bin` (different content ⇒ different CRC) is rewritten
even though the version *string* is unchanged.

### Harmony (UI skins)

`ManageHarmoniesVersions` compares versions — `Harmonies are compatibles` or
`Harmonies are not compatibles, new Harmony must be erased` — and `EraseNandHarmony` is
a dynamically-resolved BSP symbol. `UpgradeHarmoniesIfNeeded` runs four steps: save the
harmony offset from `Harmony.ini`, erase all harmonies, manage the ones on the stick,
then write them. Images are read/written with bad-block handling.

**Resolved since this was first written:** the `SIZE:` / `SIZE_1..SIZE_32` fields are
computable — `SIZE` is the sum of the file sizes inside the tar and `SIZE_n` the same with
each file rounded up to *n* KiB. They are read by `UpgPlugin.out` for the media space check.
See [Media partition](MEDIA_PARTITION.md#the-size-fields-solved).

### Version gates

```
(UpgradeTask) The version on media.inf not allows an upgrade
Upgrade not possible / Upgrade not possible!! value is too high
(GetUBootVersionMedia): field 'VER:' not found!
```

`media.inf` carries `VER:26482` (the "CD / media version") and is a **hard gate** — see
[Version strings](VERSION_STRINGS.md). Versions also drive the U-Boot
(`%02d.%02d`) and harmony/BSP decisions, which is why inventing a version is risky.

## 3. The manifest cascade

```
data file  ->  .inf (CRC32)  ->  smeg.inf (BIGQUICK_CRC32)  ->  <module>_ctrl.bin  ->  ctrl.bin
```

Inside the media partition it is one layer deeper:
`file -> system_ctrl.bin -> system.bin (+.inf) -> <module>_ctrl.bin -> ctrl.bin`.

### `*_ctrl.bin` format

```
"19/09/2017  2.1.0.0"      generation date + manifest format version, padded
<count>                    1 byte (ctrl.bin = 0x13 = 19, USERGUIDE = 0x1E = 30,
                                    BSP_512 = 0x06 = 6, NAV = 0x13)
<count> x { CheckType(1 byte), CRC32(4 bytes big-endian), path(NUL-padded) }
```

Confirmed by byte inspection: the record for `/BSP/SMEG_PLUS_512/dbsystem.bin` is
preceded by `02 21 51 67 F7`, i.e. `CheckType 2` + the CRC `0x215167F7`; the
`vxWorks.bin` record carries `0x71242C66`. The updater logs
`CheckEntryFile : CheckType = 0 / 1 / 2 / 3 / unknown for file %s`, so the first byte is
the check type. `flasher.crc` is the CRC32 of `flasher.inf`.

`SD_DIR_TTS.crc` uses a different, textual scheme (`NUMBERFILES:394`, `CRC16:2305`).

## 4. `contract.dat` — the media contract

A 29 696-byte blob at the package root: 116 RSA-OAEP blocks holding a table of per-file
checks (size, crc32, and a content spot-check). It is **not** in the root manifest and
`upgrade.out` does not reference it, but the **application image** reads it in
`C_BCM_UPGRADE::CheckTrustedSource()` and validates the rest of the media against it.

A package with a modified application image is rejected with *"The update file is protected
and cannot be copied."* unless the contract is regenerated — the format is decoded and
`tools/patch_contract.py` does exactly that. See
[Media protection](MEDIA_PROTECTION.md).

### `*_ctrl.bin` format

## 5. Open questions

- Exact field offsets inside `dbsystem.bin`.
- `CheckType` semantics for values 0–3.
- Which module a given unit selects at runtime (`AUDIO_BT` vs `_256` vs `NAV`) — read
  from the vehicle/hardware type, not traced.
