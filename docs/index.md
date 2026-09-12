# SMEG+ reverse-engineering notes

Documentation for patching PSA/Stellantis **SMEG+** head units — the
Magneti Marelli infotainment fitted to Peugeot / Citroën / DS vehicles around
2012–2017.

The immediate goal is an **AUX auto-switch**: an aftermarket CarPlay/Android-Auto
piggyback injects its audio into the head unit's AUX input, so the unit should select
AUX by itself when that audio appears rather than needing a manual source change.

!!! warning "No vendor firmware here"

    This site documents **our own** reverse-engineering and tooling. It contains no
    Peugeot / Citroën / DS / Stellantis / Magneti Marelli firmware, upgrade packages,
    symbol maps or other copyrighted binaries. You supply your own legally obtained
    package.

## Where to start

| page | what it covers |
|---|---|
| [Overview](ANALYSIS.md) | the application image, symbol maps, and the AUX event chain |
| [Architecture](ARCHITECTURE.md) | how the whole firmware fits together — modules, HMI framework, messaging, subsystems, databases |
| [Boot & update chain](FLASH_CHAIN.md) | the RTOS/BSP, front-panel MCU, what the updater does and in what order |
| [Media partition](MEDIA_PARTITION.md) | `system.bin`, ring tones, wait tones, resources, and how it is checksummed |
| [Cheatcodes & spy](CHEATCODES.md) | the diagnostic cheatcode list, the hidden entry screen, and the spy system |
| [Version strings](VERSION_STRINGS.md) | what the version screens read and how the updater gates on them |
| [Patch reference](PATCHES.md) | exact addresses and bytes, per build |
| [Flashing](FLASHING.md) | preparing the USB stick and running the update |

## Target

Developed against `SMEG5.43.A.R2` (CD 26482, 19-09-17) on a **NAV** unit. The
`AUDIO_BT` and `AUDIO_BT_256` builds are supported too; each is a separate image with
its own symbol map and patch addresses.

## Status

The application patches are built and checksum-verified, but **not yet validated on
hardware**. Open questions and ideas are tracked as issues in the
[repository](https://github.com/KRoperUK/smeg-plus-aux-patch/issues).
