---
hide:
  - navigation
  - toc
---

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

## Find your way in

The site is organised by the part of the firmware you are touching. Start with whichever
card matches what you are trying to do.

<div class="grid cards" markdown>

-   :lucide-compass:{ .lg .middle } __Get orientated__

    ---

    What can and cannot be changed on these units, and how the whole firmware fits
    together. **Read this before starting work.**

    [:lucide-arrow-right: What is reachable](CAPABILITIES.md) ·
    [Architecture](ARCHITECTURE.md)

-   :lucide-shield-check:{ .lg .middle } __The chain that protects it__

    ---

    The boot and update sequence, the signed media contract, and why version strings
    are not a safe marker.

    [:lucide-arrow-right: Boot & update chain](FLASH_CHAIN.md) ·
    [Media protection](MEDIA_PROTECTION.md) ·
    [Version strings](VERSION_STRINGS.md)

-   :lucide-cpu:{ .lg .middle } __The application image__

    ---

    The PowerPC image inside `f_BigQuick.bin`: the patch reference, the AUX
    auto-switch chain gate by gate, and how it was verified by emulation.

    [:lucide-arrow-right: Patch reference](PATCHES.md) ·
    [The AUX chain](AUX_CHAIN.md) ·
    [Emulation](EMULATION.md)

-   :lucide-music:{ .lg .middle } __The media partition__

    ---

    `system.bin`: ring tones, fonts, logos, strings, the cheatcode list — every
    replaceable asset and its risk level.

    [:lucide-arrow-right: Media partition](MEDIA_PARTITION.md) ·
    [Ring tones](RINGTONES.md) ·
    [Customising](CUSTOMISING.md) ·
    [Cheatcodes & spy](CHEATCODES.md)

-   :lucide-terminal:{ .lg .middle } __Build & flash__

    ---

    Running the tools, preparing the stick, the in-car update, and what has actually
    been confirmed on hardware.

    [:lucide-arrow-right: Running the tools](RUNNING.md) ·
    [Flashing](FLASHING.md) ·
    [Hardware verification](VERIFICATION.md)

-   :lucide-book-open:{ .lg .middle } __Reference__

    ---

    The vocabulary of these units in one place, and the repository's own release
    process.

    [:lucide-arrow-right: Glossary](GLOSSARY.md) ·
    [Releasing](RELEASING.md)

</div>

## Target

Developed against `SMEG5.43.A.R2` (CD 26482, 19-09-17) on a **NAV** unit in a 2015 Peugeot
208. The `AUDIO_BT` and `AUDIO_BT_256` builds are supported too; each is a separate image
with its own symbol map and patch addresses.

## Status

A patched, **contract re-sealed** package has been flashed to a real unit successfully: the
media check passed, the application image was written, and the unit came back up working.

- [x] **The re-seal works** — string 2099 (*"the update file is protected and cannot be
  copied"*) never appeared, which was the blocker for the whole project.
- [x] **`IsAUXSRCAvailable()`** — AUX no longer greys out without a signal, and it is back in
  the SRC cycle.
- [x] **Custom ring tone** audio, and a custom ring tone *name*.
- [x] **`SPYSTORE` backs up `/USER_DATA`** — the `spy-dump-userdata` patch, confirmed on a car.
- [ ] **The automatic AUX switch** — the remaining open question.

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
