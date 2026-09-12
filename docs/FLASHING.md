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

## Verify

The version strings do not change when re-flashing the same release, so verify by
behaviour:

- With the piggyback feeding audio into AUX, and the head unit on radio, it should switch
  to AUX on its own.
- Stop the source and see whether it returns to radio.

## Rollback

Keep an untouched copy of the original package. Re-flash it the same way; the original
application content differs from the patched one, so it will be rewritten.
