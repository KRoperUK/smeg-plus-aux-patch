# Flashing notes

!!! warning "Re-seal the package before flashing"

    The unit validates the media against a signed contract, and will reject a patched
    package with *"The update file is protected and cannot be copied."* (string 2099)
    unless the contract is regenerated:

    ```sh
    python3 tools/patch_smeg.py     --src SMEG_PLUS_UPG --out SMEG_PLUS_UPG_mod
    python3 tools/patch_contract.py --package SMEG_PLUS_UPG_mod
    ```

    A **stock** package needs no such step and can be flashed as-is (including a
    rollback). See [Media protection](MEDIA_PROTECTION.md).

These are generic notes for applying a patched SMEG+ package. They are not a substitute
for the update instructions that came with your vehicle/software. Do this at your own
risk.

## Prepare the USB stick

- Use a stick of **8 GB or more** (a package with navigation TTS data is roughly 1 GB).
- Format it **FAT32** (`MS-DOS (FAT)`), partition scheme **Master Boot Record**.
  - macOS: Disk Utility → select the **device** (not the volume) → Erase →
    Format "MS-DOS (FAT)", Scheme "Master Boot Record".
- Copy the package folder to the **root** of the stick, so you end up with:

```
/Volumes/USB/SMEG_PLUS_UPG/ctrl.bin
/Volumes/USB/SMEG_PLUS_UPG/contract.dat
/Volumes/USB/SMEG_PLUS_UPG/NAV_ctrl.bin
/Volumes/USB/SMEG_PLUS_UPG/upgrade.out
/Volumes/USB/SMEG_PLUS_UPG/NAV/…
/Volumes/USB/SMEG_PLUS_UPG/AUDIO_BT/…
/Volumes/USB/SMEG_PLUS_UPG/BSP/…
…
```

## Before you go to the car

Confirm the patched image is present and the checksums agree, e.g. for a NAV unit:

```sh
python3 - <<'PY'
import zlib
print(hex(zlib.crc32(open('SMEG_PLUS_UPG_mod/NAV/AppBin/f_BigQuick.bin','rb').read())))
PY
cat SMEG_PLUS_UPG_mod/NAV/AppBin/f_BigQuick.bin.inf
grep BIGQUICK SMEG_PLUS_UPG_mod/NAV/smeg.inf
```

The `.inf` value and `smeg.inf`'s `BIGQUICK_CRC32` must both equal the CRC printed above.

## In the car

- Ignition on, **engine running** (these updates are long and the unit must not lose
  power).
- Insert the stick into the vehicle USB port and let the unit detect the update; follow
  the on-screen prompts.
- The updater is incremental: an already-current unit will report the boot ROM as done
  and skip the Renesas MCU, and will rewrite the application when its content differs.
- Do not remove the stick or cut power until it reboots.

## What you will see

The full run takes **over 20 minutes**, and the unit reboots several times on the way.
The screens alternate between the normal touchscreen UI and a blue bootloader screen with
yellow monospace text.

```
UPDATE LEVEL                 (touchscreen)  media detected
  Identification of media...
  Checking compatibility...
Software update.             (touchscreen)  same version number in both lines is normal
  From version:      CD 26482
  To version number: CD 26482
  Keep the engine running.
  The system will restart.
  Continue?  Yes / No
        |
        v
PEUGEOT                      (splash)       reboot
        |
        v
Renesas Upd...               (bootloader)   front-panel MCU
AppBin Upgrade...            (bootloader)   <-- the application image is written here
AppBin flashing
        |
        v
Phase 0   formatting /SYSTEM                  (bootloader)
Phase 0   defragmenting /USER-DATA/BACKUP
Phase 3   Uncompress /SYSTEM
Phase 3   Check the result of uncompression of /SYSTEM/
          Check progression : 6%
Phase 5   Uncompress /SD_DIR  ->  /SD_DIR_TTS
Phase 6   Management of UserGuide
Phase 6   Management of ZA files
          "The product must reboot in 2 s"   <-- the updater reboots itself here
        |
        v
PEUGEOT  ->  normal UI        (splash)       done
```

The `Phase 0 / 3 / 5` numbering and the `Uncompress` lines are the updater working
through the media partition; the free-space figures on those screens change as partitions
are rewritten. Reboots are expected after the BootROM, U-Boot, Renesas and application
steps — see [Boot and update chain](FLASH_CHAIN.md).

The bootloader screens carry a header identifying the media being flashed. Check it
matches your package — `Upgrade version` comes from `SUBVER` in `upgrade.out.inf` and
`Media version` from `VER` in `media.inf`:

```
Media version :        26482
Upgrade version :      5.3.3
BootRom version :      BSP-215.6.PLUSINT May 26 2017, 13:23:13
UBoot version :        06.03 Apr 22 2013 - 15:57:07
Hardware ID :          155
Hardware diversity :   NAV
Renesas version :      05.e3.01
```

!!! danger "If you see the protected-file error"

    *"The update file is protected and cannot be copied."* (string 2099) means the media
    does not match the signed contract — the re-seal step was skipped, or was run against
    the wrong directory. The unit will refuse the update. Rebuild and re-seal; nothing is
    written.

## Verify

The version strings do **not** change when re-flashing the same release, so verify by
behaviour. System Information will still read the same `SMEG5.43.A.R2` / `CD 26482` after
a successful patched flash — see [Version strings](VERSION_STRINGS.md).

With the `aux-autoswitch` patch set:

- The **AUX tile stays selectable with nothing plugged in** — on stock firmware it greys
  out. This alone confirms `IsAUXSRCAvailable()` is patched.
- **SRC steps through to AUX** as one of the normal sources.
- **The unit should switch to AUX by itself** when audio appears on the input, with the
  head unit on another source. This is the whole point of the patch and the one thing to
  watch for. See [Hardware verification](VERIFICATION.md) for what has been confirmed so
  far.

## Rollback

Keep an untouched copy of the original package. Re-flash it the same way; the original
application content differs from the patched one, so it will be rewritten.
