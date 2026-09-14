# Version strings — display, sources and gating

## What the System Info screen shows

| field | value on SMEG5.43.A.R2 | source |
|---|---|---|
| Main SMEG software | `5.43.A.R2` | `smeg.inf` -> `VER:` |
| Display version | `32.00` | `smeg.inf` -> `GUI_VER:` |
| CD / Media version | `26482` | `media.inf` -> `VER:` |
| Bluetooth | `1.2.0` | Bluetooth firmware |
| BootROM / uBoot / Renesas | as flashed | their own images |

The application does **not** carry these strings for display. The image contains the
path `/SYSTEM/Data_base/smeg.inf`, i.e. it reads the **media partition** copy. So:

- Patching `AppBin/f_BigQuick.bin` never changes any version string.
- Changing `VER:`/`GUI_VER:` in a *module* `smeg.inf` (`AUDIO_BT/smeg.inf`) is used by
  the updater but does not change what the screen shows — the displayed copy is
  `Data_base/smeg.inf` **inside `system.bin`**.
- A visible marker therefore requires a media-partition edit (see
  [Media partition](MEDIA_PARTITION.md)). The `SIZE:` fields are no longer a blocker —
  they are computable — but the packing tool is still to be written (issue #35).

`AUDIO_BT/smeg.inf` and the tar's `Data_base/smeg.inf` currently hold identical content,
which is why it is easy to assume editing one affects the other.

## The updater gates on these strings

From `upgrade.out` strings:

```
(UpgradeTask) The version on media.inf not allows an upgrade
(UpgradeTask): Actual BSP (%f) is very old... The new version of the BSP need to format the NAND.
(GetUBootVersionMedia): field 'VER:' not found!
(ManageHarmoniesVersions) Harmonies are not compatibles, new Harmony must be erased
(ManageRenesasUpdateAndReboot) Renesas version '%s' == Mot. File version '%s'
manageBootRomUpdateAndReboot: BootRom already done.
ManageBigQuickUpdate: '%s' is a cantidate!
```

So versions are compared, and the comparisons drive more than "update or skip":

- `media.inf` has an explicit gate — **"not allows an upgrade"** — so a wrong value
  there can *block* the package.
- UBoot versions are parsed numerically (`%02d.%02d`) and a missing/unparsable `VER:`
  is an error, so an invented series is not guaranteed to parse.
- Harmony compatibility and BSP age are version-driven, and those branches do
  destructive things (erase the harmony images, format the NAND).

## Why not to invent a version

- Bumping `smeg.inf` `VER:` to e.g. `5.43.A.R3` makes the application look newer, so the
  updater applies it — but it changes nothing visible (display reads the media copy) and
  nothing functional (content is whatever was patched).
- An unrecognised series such as `5.43.X.R1` may not parse, landing on the
  "not allows an upgrade" path or, worse, triggering a harmony/BSP re-flash.
- `media.inf` is the one with the hard gate; do not edit it as a marker.

**If a visible marker is wanted, the safe field is `GUI_VER` (Display version)** — it is
presentation-only and nothing gates on it. It still lives in the media partition, so it
is the same rebuild job.

!!! tip "The one safe visible marker"

    `GUI_VER` is the only version field that is both **shown on screen** and **not gated
    on** by the updater. Everything else is either invisible (the app never displays it) or
    dangerous to change (`media.inf` can block the whole package). For now, rely on the
    updater's own progress screens as evidence the application was written, and judge by
    behaviour — see [Hardware verification](VERIFICATION.md).
