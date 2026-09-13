# What is reachable, and what is not

This project has spent real time on things that turned out to be impossible, and the reasons
are worth writing down so nobody repeats them. Every claim here is grounded in the firmware
or in a hardware observation — the evidence is named so it can be checked.

## The two update systems

The unit has **two unrelated update paths**. Confusing them wastes effort, because they share
the USB port and nothing else.

| | firmware / head unit | cartography (maps) |
|---|---|---|
| content | `system.bin`, `AppBin/f_BigQuick.bin`, BSP, Renesas | map database |
| written by | `C_UPGRADE::UpgradeTask` — the flow in [Boot and update chain](FLASH_CHAIN.md) | `C_SDHC_UPGRADE` |
| protected by | `contract.dat` (see [Media protection](MEDIA_PROTECTION.md)) | its own, simpler scheme |
| updatable by us | **yes** | no — see below |

Maps being a separate system is not an inference: the updater has a whole subsystem for it,
with its own partition and format handling.

```
C_SDHC_UPGRADE::ReadCapacity / ReadCapacityInBlocks / CheckPartition
C_SDHC_UPGRADE::getSDBlkDeviceWrapper / sdhcMBRResetWrapper
[ERROR] - #8GB# Unable to format the cartography SD partition index='%d' cluster_size='%d'
ManageSD_8GB_DoublePartition()
```

**`/sdhc:0/` is not a card slot.** A Peugeot 208 (2015) has **no removable SD card** — the only
user interface is the USB socket in the centre console. That device name is an SDHC block
device the BSP exposes over **internal storage**, and the updater writes an MBR to it. So there
is no card to pull, image, or back up.

## Impossible, and why

### Native CarPlay

**No, and no amount of patching changes it.** Two independent blockers, one of them physical:

- The application image contains **zero** `CarPlay` strings. There is no stack to enable.
- CarPlay requires an **Apple MFi authentication coprocessor** in the accessory. The iPhone
  performs a cryptographic handshake with that chip and refuses to start a session without it.
  No firmware can emulate it, which is exactly why every retrofit on older head units is a
  piggyback box containing the SoC *and* that chip.
- CarPlay delivers **H.264** video. The unit's video handling is MPEG4 status events for USB
  file playback — there is no H.264 decoder, and no path to display an arbitrary stream.

What the unit *does* have is `iPod` support over USB (28 `MFi`-related strings, the `iPod`
source in the source menu). That is **iAP audio and metadata, not CarPlay.**

### New radios — WiFi, cellular

The USB stack is mass storage plus video; there is no network driver, so a USB WiFi dongle
will not enumerate. There is no WiFi or cellular hardware. Anything needing a new radio needs
an external box.

### Maps, beyond the last official release

- The map database is proprietary PSA/Magneti Marelli format.
- PSA stopped shipping SMEG+ maps years ago, so there is no feed to convert *from*.
- It sits on **internal storage** behind the updater, so unlike the head unit's own
  partitions we cannot even inspect it without opening the unit.

Three independent blockers. Park it.

Third-party map updates for some other PSA units do circulate; that is a different platform
and is not evidence that this one is reachable.

## Present but gated — reachable with work

These already exist in the firmware. The work is finding the switch, not building the feature.

### Bluetooth tethering — the thing WiFi would be for

The unit supports **Bluetooth PAN** (network access point) over DUN/BNEP:

```
C_BCM_T2BF        connectivity.sqlite
```

So it can get internet through a paired phone, and it ships a **browser** to use it
(`browser.sqlite`, the `internet_default/` portal tree). No new hardware required. Tracked as
a spike.

### Speed cameras / danger zones — the one navigation win

Not on the cartography partition. They are **ZA files** the unit manages itself:

```
C_UPGRADE::ManageZAFiles
ManageZAFiles : Copy ZA files from /SYSTEM_DATA to /USER_DATA
AddListOfZARorPOIofProduct
(UpgradeTask): Transfert ZA in the Renesas OK
```

`ZAR` is *zones à risque*, the French legal formulation. The application image has
`Configure_Radar_Alert`, `Configure_Dangerous_Area_Alert` and `NOTIFY RADAR WARNING INFO` with
`coords %ld,%ld` — so it stores coordinates and alerts on them.

That means a **dedicated updater step, files in a partition we can already write, and no
dependency on map data.** The open question is the file format, which is a contained,
offline job.

### Other settings-driven behaviour

Seen in `up_common.sqlite` or the application image, all data rather than code:

- **Welcome image** — `SetWelcomeImageStatus` and a user-data popup family. Separate from the
  NAND boot logo, so this is where a custom image can actually go.
- **Jukebox** — `media_jkb_catalog.sqlite`.
- **Extra video inputs** — `video: Video_Input_2/3`, `Reverse1/2/3`.
- **Cheatcodes** — `cheatcodes.sqlite` is data.
- **Radio logos**, **GUI sounds**, **UI strings** — see the media partition notes.

Four settings databases have not been opened at all: `up_config.sqlite`, `up_user_hmi.sqlite`,
`desktopServices.sqlite`, `config_options.sqlite`. Feature flags hide in exactly such places.

## The hard boundary

**We can change behaviour, configuration and data. We cannot add hardware capability.**

Every "can it do X?" question resolves to one of:

1. **Is the code already there?** Then it is a patch or a setting. (AUX, ZA, BT PAN.)
2. **Is it a hardware capability?** Then it needs an external box. (CarPlay.)
3. **Is it data we do not have and cannot generate?** Then it is out of reach. (Maps.)

## The car's own look — the HARMONY module

The unit's on-screen styling is the **HARMONY** module, and it is **in the update package**.
`ManageHarmoniesVersions` and `ManageSkinCopyFromMedia` in the updater manage it.

### Five skins ship, and the unit names them

The `.bigharmony.ini` files document every variant in plain text:

```
BigHarm1 : GRAPHIC (LCB) / ELLIPTIC / CUBIC / GRAPHIC (LCD)
BigHarm2 : REDLINE / REFLEX / ESSENTIEL
BigHarm3 : SQUARE (NAV) / WARMLIGHT (NAV) / ESSENTIEL (DS)
BigHarm4 : SQUARE (AUDIO)
BigHarm5 : WARMLIGHT (AUDIO)
```

and which one a car gets is chosen by **vehicle trim**:

```
LIST_NAV:2,0,0,3,0,0          <- a NAV unit uses BigHarm2 and BigHarm3
LIST_AUDIO_BT:4,5
```

So a given car runs **one** of these while the others sit unused in the unit. Each is a
`BIG_HARMONY.bin` of 26–28 MB plus a per-display `BIG_SKIN_NAV.bin` / `BIG_SKIN_AUDIO.bin`.

This also explains the marque logo packages. `BigHarm3` is labelled *ESSENTIEL (DS)* — DS
branding is a **skin variant**, which is why `Data_base/graphics/logo/` holds `peugeot.pkg`,
`citroen.pkg` **and** `ds.pkg`. Those are the skin's brand artwork, not the boot splash. The
loop closes: we decoded them, they do nothing at boot, and now we know what does read them.

### Custom artwork: no

The payload is opaque, and not merely compressed:

```
00000000: 42 49 47 48 41 52 4d 4f 4e 59     "BIGHARMONY" + zero padding
HEADER_SIZE:900   HEADER_CRC32:817740569   VERSION_BIGHARMONY_STRUCT:01.00.00.b
zlib at 0x0 / 0x384 / 0x385 / 0x400 -> all fail
```

26 MB per skin that will not inflate. Almost certainly encrypted. Drawing your own theme means
breaking that format first — a project in its own right, not a patch.

### Switching skin: plausible, as a data change

The choice is a **mapping in a text `.ini`** inside the module, and the module is something the
package already ships. So switching a unit to a different one of the five looks like a file
edit rather than a code patch. That is the realistic route to changing how the car's screen
looks.

**Caveats.** Nobody has established which harmony a 208 NAV actually uses, so the alternatives
cannot be described yet. The updater **version-checks** harmonies and will erase and rewrite
them on a mismatch, so this is not free. And the vehicle type that drives the mapping may come
over CAN, which would make it less directly editable than it appears.
