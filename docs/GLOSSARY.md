# Glossary

The recurring vocabulary of these units, in one place. Terms are defined here
once; the rest of the site links back rather than re-explaining them.

## Hardware and platform

`SMEG+`
:   The Magneti Marelli infotainment head unit fitted to Peugeot, Citroën and DS
    vehicles roughly 2012–2017. The subject of this whole site.

`NAV` / `AUDIO_BT` / `AUDIO_BT_256`
:   The three build variants of the firmware. `NAV` has navigation; the two
    `AUDIO_BT` builds do not. Each is a separate image with its own symbol map
    and its own patch addresses — an address from one build is meaningless on
    another. See [Patch reference](PATCHES.md).

PowerPC
:   The big-endian CPU architecture the application image runs on. Patch bytes
    are PowerPC machine code.

VxWorks / BSP
:   The real-time operating system and its Board Support Package — the low-level
    layer that boots the unit before the application starts. See
    [Boot & update chain](FLASH_CHAIN.md).

Renesas MCU
:   The front-panel microcontroller. The updater reflashes it as one of its
    phases, which is one reason the unit reboots mid-update.

## The firmware image and its parts

`f_BigQuick.bin`
:   The application image as shipped: an `0x800`-byte header, an `0x08` marker,
    then a zlib stream that inflates to the raw PowerPC image at `0x01000000`.
    It is **not** encrypted. Patching happens here.

`system.bin`
:   The media partition — a gzip'd tar holding ring tones, fonts, logos, the
    cheatcode list, version markers and more. See
    [Media partition](MEDIA_PARTITION.md).

`system_ctrl.bin`
:   The per-file CRC manifest for everything inside `system.bin`. Editing a file
    in the partition means recomputing its record here.

`smeg.inf`
:   The version-marker file **inside** the media partition that the System Info
    screen actually reads. Patching the application image does not change it.
    See [Version strings](VERSION_STRINGS.md).

`USER_DATA`
:   The partition the *car* owns — paired phones, navigation destinations,
    presets, settings. It is not shipped in the package, which is why editing a
    copy inside `system.bin` appears to do nothing, and why overwriting it is
    destructive and unrecoverable by reflashing.

## Integrity and protection

`contract.dat`
:   The signed media contract. Its RSA-OAEP records let the unit verify the
    package has not been tampered with. A modified package must be re-sealed or
    the unit rejects it. See [Media protection](MEDIA_PROTECTION.md).

`CheckTrustedSource()`
:   The routine that validates the contract. When it fails, the unit shows
    string 2099.

String 2099
:   The on-screen error *"the update file is protected and cannot be copied"* —
    what you see when the contract does not match the package.

CRC cascade
:   The chain of checksums (file → manifest → module → root) that must all be
    recomputed, in order, after any change. `tools/patch_smeg.py` rebuilds it.

`SIZE` / `SIZE_n`
:   Computed fields in `system.bin.inf`: `SIZE` is the sum of the file sizes in
    the tar; `SIZE_n` is the same rounded up per file to *n* KiB.

## Audio and the AUX chain

`IsAUXSRCAvailable()`
:   The check that decides whether AUX appears in the source list. Patched so
    AUX no longer greys out without a signal. **Confirmed on hardware.**

`HandleAudioAuxInputStatusChnged()`
:   The handler that reacts to AUX signal-status changes — the gate chain the
    automatic-switch work targets. See [The AUX chain](AUX_CHAIN.md).

`C_MGR_SRC`
:   The source manager. Owns the key/value mechanism and the request scheduler
    that actually change the active audio source.

`Last_Source` / `Sched_Pos`
:   Runtime values that record and schedule the selected source. Central to how
    a source switch is requested and remembered.

## Diagnostics

Cheatcode
:   A hidden service code, data-driven from `cheatcodes.sqlite`, reached from a
    hidden entry screen. See [Cheatcodes & spy](CHEATCODES.md).

`C_BCM_SPY` / `SPYSTORE`
:   The on-unit diagnostics/spy subsystem and the action that dumps its data to
    a USB stick. The `spy-dump-userdata` patch repurposes part of its copy loop
    to also back up `/USER_DATA`.

`HARMONY`
:   The skin/theme module that owns the car's on-screen look. Five skins ship;
    custom artwork is gated. See [What is reachable](CAPABILITIES.md).

`ZA files`
:   Danger-zone / speed-camera data files the unit can ingest.

## Project process

`GUI_VER`
:   The only version field that is both visible and safe to change.

Release Please
:   The automation that turns Conventional Commit titles on `main` into releases.
    See [Releasing](RELEASING.md).
