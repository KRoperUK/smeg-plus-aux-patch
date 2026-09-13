# SMEG+ Patches

Reverse-engineering notes and tooling for PSA / Stellantis **SMEG+** head units — the
Magneti Marelli infotainment fitted to Peugeot, Citroën and DS vehicles around 2012–2017.

The project started with one concrete problem: an aftermarket CarPlay / Android-Auto
piggyback injects its audio into the head unit's AUX input, and the pain is having to switch
the unit to AUX by hand every time. That is still the goal, but the work underneath it — the
signed media contract, the checksum cascade, the settings partitions — generalises to any
patch you want to make to one of these units.

!!! warning "No vendor firmware here"

    This site documents **our own** reverse-engineering and tooling. It contains no
    Peugeot / Citroën / DS / Stellantis / Magneti Marelli firmware, upgrade packages,
    symbol maps, or other copyrighted binaries. You supply your own legally obtained
    package. The licence key material needed to re-seal a package is recovered from that
    package at runtime and is never stored here.

## Start here

**If you are new to the unit**, read in this order — it goes from what the thing *is* to
what you can safely change:

| page | what it covers |
|---|---|
| [What is reachable](CAPABILITIES.md) | what can and cannot be changed, and why — **read this before starting work** |
| [Architecture](ARCHITECTURE.md) | how the whole firmware fits together — modules, HMI framework, messaging, subsystems, databases |
| [Boot & update chain](FLASH_CHAIN.md) | the RTOS/BSP, the front-panel MCU, what the updater does and in what order |
| [Media partition](MEDIA_PARTITION.md) | `system.bin`, ring tones, brand logos, and how it is checksummed |
| [Media protection](MEDIA_PROTECTION.md) | the signed contract, and how to re-seal a modified package |

**If you want to patch something**, this is the working set:

| page | what it covers |
|---|---|
| [Running the tools](RUNNING.md) | the manifest build, pre-flight, and the tool cheat sheet |
| [Patch reference](PATCHES.md) | exact addresses and bytes, per build |
| [Flashing](FLASHING.md) | preparing the stick, the update process, and how to verify |
| [Hardware verification](VERIFICATION.md) | what has actually been confirmed on a car — and what has not |

**For the detail**, as needed: [Overview](ANALYSIS.md) (the image, symbol maps, and the AUX
event chain), [Cheatcodes & spy](CHEATCODES.md), [Ring tones](RINGTONES.md),
[Version strings](VERSION_STRINGS.md), and [Releasing](RELEASING.md).

## Target

Developed against `SMEG5.43.A.R2` (CD 26482, 19-09-17) on a **NAV** unit in a 2015 Peugeot
208. The `AUDIO_BT` and `AUDIO_BT_256` builds are supported too; each is a separate image
with its own symbol map and patch addresses.

## Status

A patched, **contract re-sealed** package has been flashed to a real unit successfully — the
media check passed, the application image was written, and the unit came back up working.

**Confirmed on hardware:**

- the re-seal works: string 2099 (*"the update file is protected and cannot be copied"*) never
  appeared, which was the blocker for the whole project
- `IsAUXSRCAvailable()` — AUX no longer greys out without a signal, and it is back in the SRC
  cycle
- custom ring tone audio, and a custom ring tone *name*

**Not yet confirmed:** the automatic AUX switch, and whether a `USER_DATA` payload is read at
all. Those are the open questions; everything else here is supporting material.

See [Hardware verification](VERIFICATION.md) for the full picture, and the
[repository issues](https://github.com/KRoperUK/smeg-plus-patches/issues) for what is being
worked on.

## The short version of the hard-won lessons

- **The unit keeps its own state.** Settings live on a separate `/USER_DATA` partition, not in
  the package. Editing the copy inside `system.bin` can appear to do nothing.
- **Payloads are version- and value-checked.** A source value the unit does not recognise is
  ignored silently, and it falls back — so validate against the real enum rather than guessing.
- **Build, then check, then flash.** `tools/preflight.py` runs as part of the build and fails
  it; most of the wasted trips in this project were things it would have caught.
