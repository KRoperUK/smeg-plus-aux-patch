
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
