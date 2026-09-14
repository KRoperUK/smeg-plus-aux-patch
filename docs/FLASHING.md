# Flashing notes

!!! warning "Re-seal the package before flashing"

    The unit validates the media against a signed contract, and will reject a patched
    package with *"The update file is protected and cannot be copied."* (string 2099)
    unless the contract is regenerated:

    ```sh
    uv run tools/patch_smeg.py     --src SMEG_PLUS_UPG --out SMEG_PLUS_UPG_mod
    uv run tools/patch_contract.py --package SMEG_PLUS_UPG_mod
    ```

    A **stock** package needs no such step and can be flashed as-is (including a
    rollback). See [Media protection](MEDIA_PROTECTION.md).

These are generic notes for applying a patched SMEG+ package. They are not a substitute
for the update instructions that came with your vehicle/software. Do this at your own
risk.

## Shipping settings: the `USER_DATA` payload, and why it does not land

A package can carry a `USER_DATA` payload — `NAV/USER_DATA/user_data/sqlite/…` — which the updater
copies over the unit's live settings partition. **It does not currently work**, and the reason is
worth knowing before building one:

- The copy is `xcopy_blk("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA", "/USER_DATA")`, hard-coded, in the
  block that continues **Phase 1** of `UpgradeTask`.
- The destination directory is named from what the updater reads off the stick, and **FAT gives
  out uppercase 8.3 short names**. The application reads its live settings from lowercase
  `/USER_DATA/user_data/sqlite/`, so the payload lands in an uppercase `SQLITE/` sibling and is
  never opened.

Observed on a car, with the log to prove it — see
[the second flash](VERIFICATION.md#second-flash-the-user_data-retry-2026-09-14). A flash with a
correctly-laid-out payload ran the copy, and the unit's own settings dump afterwards still read
the factory `supervisor.Last_Source`.

Two other things the same log and updater binary settled:

- The live directory holds a `.inf` sidecar beside every database (`up_common.sqlite.inf`).
  `C_UPGRADE::ManageSQLiteFiles` says `We have to generate the .inf file!`; the generated file
  found on the stick is exactly `CRC32: <signed decimal>\r\n`, and its value matches the edited
  database. `build_package.py` now writes that pair up front and pre-flight rejects a missing or
  stale sidecar.
- `C_UPGRADE::RestoreDataFromUSB` copies from a **per-unit** directory, `/bd0/<unit-id>/`, not
  from the package path. `C_UPGRADE::SaveDataOnUSB` is what creates it, and it did not run.

### Working around it: give the directory a long-filename entry

The updater names each destination directory after what it reads off the stick, and it reads
**long filenames** but not the FAT "lowercase base" bit. So the fix is to make the payload's
`sqlite` directory carry a long-filename entry.

macOS will not write one for an 8.3-valid name like `sqlite` — it stores the short name
`SQLITE` with that bit set and no LFN, which is precisely how this goes wrong. Renaming does
not help; it does the same thing. The entry has to be written or corrected directly:

1. Name the directory something that *needs* an LFN, e.g. `sqlite_dat`, so macOS writes one.
2. Unmount the volume (`diskutil unmount`, not eject — eject removes the device node), then
   rewrite that one LFN entry's characters to `sqlite`. The short name and its entry checksum
   are untouched, and it is a single 32-byte read-modify-write:

   ```sh
   diskutil unmount /Volumes/SMEGUPDATE
   sudo python3 tools/fix_userdata_case.py --dry-run /dev/rdisk4s1
   sudo python3 tools/fix_userdata_case.py /dev/rdisk4s1
   diskutil mount /dev/disk4s1
   ```

3. Before flashing, unmount once more and run the read-only check against the FAT volume:

   ```sh
   python3 tools/fix_userdata_case.py --check /dev/disk4s1
   ```

   It must print `OK: FAT long-filename entry is exactly 'sqlite'`. Finder displaying lowercase
   is not proof: the checker rejects short-name `SQLITE` even when its FAT lowercase-display bit
   is set, because that is the exact representation the updater mishandles.

!!! warning "Not yet confirmed on hardware"

    The filesystem half is verified: the directory reads back as `sqlite`, and the `.inf` is
    present. Whether the application *accepts* the database once it lands there is the next
    flash's question — the updater log will show the destination case either way. Until that
    is settled, prefer routes that are known to work: an application-image patch (proven on
    hardware) or a media-partition edit.

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

!!! warning "The folder must be called `SMEG_PLUS_UPG` — especially with a `USER_DATA` payload"

    The ordinary update is found by scanning, but the settings payload is **not**.
    `C_UPGRADE::UpgradeTask` checks one literal path —
    `IsDirExist("/bd0/SMEG_PLUS_UPG/NAV/USER_DATA")` — and only then runs
    *"Copy of /USERDATA from /bd0 to NAND"*. Both the folder name and the module are
    hard-coded in that string.

    So a build written to, say, `SMEG_PLUS_UPG_auxdefault` still flashes normally and its
    payload is **skipped without a word**, which looks exactly like the setting having had no
    effect. `tools/preflight.py` fails on this, and `build_package.py` says so at build time.

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
- **SRC steps through to AUX** as one of the normal sources. This patch set does not reorder
  that cycle.
- **Do not expect this patch set to switch to AUX by itself.** Function-level emulation proved
  the status-handler edit is inert, and the hardware result agrees. Boot-to-AUX was a separate
  `USER_DATA` experiment; the unit's SPY dump shows it still read `Last_Source = 1` (FM), not
  the payload's `7`. See [Hardware verification](VERIFICATION.md).

## Rollback

Keep an untouched copy of the original package. Re-flash it the same way; the original
application content differs from the patched one, so it will be rewritten.
