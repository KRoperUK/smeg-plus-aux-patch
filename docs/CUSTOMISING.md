# Customising the unit

Every asset inside the media partition that can be replaced, what each one is for, and how
safe it is to touch. All of it lives in `system.bin`, which
[tools/patch_media.py](../tools/patch_media.py) rebuilds — see
[Media partition](MEDIA_PARTITION.md) for the format and the checksum cascade.

**Replacement only.** The partition's `system_ctrl.bin` records are per-file, and adding a
*new* file would need a record that does not exist. Everything below is a swap, keeping the
filename.

!!! tip "Where to start"

    The lowest-risk, highest-visibility swaps are **radio station logos** (597 plain PNGs)
    and the **ring / wait / GUI tones** (plain WAV). No format work, trivially reversible,
    and the worst case is the unit ignoring the file. Save the string tables, `gui_*.xml`
    and the marque `.pkg` containers for later — see the [risk table](#what-is-safe-and-what-is-not).

## Sounds — 28 WAV files

Three independent groups, and they are easy to confuse because they all look like "the
sounds".

### Ring tones — `ring_tones/` (9)

The phone ring tones, and the call/status tones.

| file | what it is | format |
|---|---|---|
| `ring1RT.wav` … `ring5RT.wav` | the five selectable ring tones | 16-bit mono 44.1 kHz |
| `busyRT.wav` | engaged tone | same |
| `errorRT.wav` | error tone | same |
| `okRT.wav` | confirmation tone | same |
| `koRT.wav` | failure tone | same |

The `RT` is part of the real filename. The names the **phone UI** shows are *not* here — they
are rows in `up_common.sqlite` (see [Ring tones](RINGTONES.md)), which is why replacing a tone
changes what you hear and renaming changes what you see.

### Wait tones — `wait_tones/` (13)

Network call-hold music, **one per language**, and a different format from everything else:

```
MM_HoldOn_<LANG>_8kHz.wav     16-bit STEREO 8 kHz
CRC CZC DUN ENG FRF GED HRH ITI PLP PTP RUR SPE TRT
```

### Interface sounds — `boardfs/GUI_STYLE/GUIS_RESSOURCES/gui_sounds/` (6 + a map)

The touch feedback, with a **plain XML** map from id to filename:

```
BalayageZ0.wav     page sweep                     Abandon.wav     cancel / back
Validation.wav     confirm a panel                Clavier.wav     keyboard keys
Welcome.wav        welcome screen appears         Brosser.wav     brush
```

**Stock oddity worth knowing:** `gui_sounds.xml` also lists `OuvertureMenu.wav` (id 1,
`MAIN_MENU_OPENING`) and that file **is not present**. The map promises more sounds than ship.

## Fonts — 7 TrueType files

All in `Data_base/TMP/lib/fonts/`, and the names say what they are for:

| file | likely role |
|---|---|
| `GillSansPSA.ttf` | the main UI typeface — PSA's licensed Gill Sans |
| `PLAQUESgilsans.ttf` | the plaque/harmony style |
| `GillSansSLIDER.ttf`, `Ecube SLIDER.ttf`, `T9typoSLIDER.ttf`, `TYPEC4SLIDER.ttf` | the "slider" family, one per harmony |
| `DejaVuSans.ttf` | a fallback with wider script coverage |

This is a genuine find: **the unit ships its own fonts**, so the typeface is replaceable. Fair
warning — `GillSansPSA` is a licensed commercial face, so substituting it is a licensing
question as much as a technical one. `DejaVuSans` is the free one.

## Images and glyphs — 631 PNG + 2 BMP

### Radio station logos — `Data_base/radio/logo/` (597)

199 stations in **three sizes** (`Large`, `Medium`, `Small`), named by country and station:
`AT_O3.png`, `BE_JoeFM.png`, `…`. Plain PNGs, mapped by `RadioLogo.sqlite` (`PI_Logo_List`).
The most accessible customisation in the whole unit: no format work, no risk, and it is nearly
600 files of visible result.

### Front-panel animation — `AVR_img/` (8)

`AVR_IMG1.png` … `AVR_IMG8.png`, 800×480 RGBA. A wireframe animation of a structure — bridges
and arches — that plays on the **front-panel display**. It is **not** the boot logo.

### Browser portal art — `internet_default/` (26)

```
portal/pgen_<peugeot|citroen>_<home_1..3|load|network|usb>.v2.pgen.png
portal/sprite_offline.v2.png
PMS_picto/6306001.png … 6306012.png        status pictograms
config/ErreurPortail_V2.png                 portal error image
```

The browser's own artwork, and the only place the marque branding is duplicated across both
Peugeot and Citroën in image form.

### iPod logo — `graphics/logo/iPodLogo/` (2 BMP)

`iPodLogoPeugeot.bmp`, `iPodLogoCitroen.bmp` — shown while an iPod is connected. BMP, not PNG,
and per marque.

### Marque logos — `graphics/logo/` (3 `.pkg`)

`peugeot.pkg`, `citroen.pkg`, `ds.pkg`. Decoded in [tools/splash.py](../tools/splash.py) —
four 800×480 images each. **These are not the boot splash**; the boot artwork is in a NAND
area a USB package cannot reach. What reads these is the skin system — `BigHarm3` is labelled
*ESSENTIEL (DS)*, which is why `ds.pkg` exists at all.

## Strings — 16 language tables

`boardfs/GUI_STYLE/GUIS_RESSOURCES/gui_texts/gui_text_strings_<LANG>.xml.bin`

`GB FR GE IT SP DU PO PL RU CZ CR BR HO TU` and more. **Not XML despite the name** — a binary
string table with an id/length/offset directory and NUL-separated data. Decoding it is what
would allow renaming UI labels, e.g. calling the `AUX` tile "CarPlay".

## Theme and layout — the XML

| file | what it controls |
|---|---|
| `boardfs/GUI_STYLE/gui_config.xml` | screen size (800×480), harmony id, language, resource paths |
| `boardfs/GUI_STYLE/gui_harmonies.xml` | look-and-feel ids 0–7: AGORA, BLUEXY, PLAQUE, EKODO, MORGLUB, AGORA2, FOR_TEST, TEST |
| `boardfs/GUI_STYLE/gui_languages.xml` | 16 languages, id → code |
| `gui_sounds.xml` | sound id → file |

**The catch for all of these:** `gui_config.xml` sets harmony id **10**, which is outside the
0–7 range in `gui_harmonies.xml`, and the image/font/colour paths it references are **absent**
from the partition. The real skin is delivered by the **HARMONY module**, not from here. So
these files are configuration for a skin system whose artwork lives elsewhere — editing them
may change nothing, exactly as happened with the marque logos.

See [What is reachable](CAPABILITIES.md) for the HARMONY findings, including the five skins the
unit ships and why custom artwork is out of reach for now.

### Wallpapers

There is **no wallpaper system** in the partition. The nearest things are the browser's
`MMR/background_1.css` and `background_2.css`, which set the portal background, and the skin's
own background, which comes from HARMONY. Choosing a different skin is the realistic route to
a different look; see [What is reachable](CAPABILITIES.md).

## Cheatcode libraries — `Application/CCOD/` (23)

`libcheatcode_<NAME>.out` (+ `.inf`, `.txt.gz`) — loadable modules behind the diagnostic
cheatcodes: `SPYSTORE`, `SPYTAKE`, `SYSPMON`, `REBOOT`, `BTINFO`, `TUNERINFO`, `ZAINFO`,
`HWINFO`, `SWINFO`, `PING`, `FPS` and others. See [Cheatcodes](CHEATCODES.md).

## What is safe, and what is not

| category | risk | why |
|---|---|---|
| Ring tones, wait tones, GUI sounds | **low** | plain WAV, easy to revert, no format work |
| Radio station logos | **low** | plain PNG, 597 of them, no format work |
| Fonts | **low technically**, licensing caveat | plain TTF; `GillSansPSA` is a commercial face |
| Browser portal art, iPod logos | **low** | plain PNG/BMP |
| String tables | **medium** | binary format has to be decoded first |
| `gui_*.xml` | **medium** | plausibly inert, as the skin comes from HARMONY |
| Marque `.pkg` | **unknown** | decodable and rebuildable, but what reads them is unidentified |

Everything here is a **data** change — no application code is patched, and the worst case for
the low-risk rows is that the unit ignores the file. That is a materially safer class of change
than anything in [PATCHES.md](PATCHES.md).

## Tooling

`tools/ringtones.py` handles the tone groups, including format conversion and level matching.
`tools/splash.py` handles the marque `.pkg` containers. The rest — logos, fonts, portal art —
are plain file swaps that `tools/patch_media.py` already supports; a helper that maps a
directory of replacements onto the right paths, with human-readable labels, is the obvious
next step.
