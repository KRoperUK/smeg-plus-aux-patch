# Running the tools

Everything here runs with [uv](https://docs.astral.sh/uv/) — no virtualenv to set up, no
`pip install`. The scripts carry [PEP 723](https://peps.python.org/pep-0723/) inline
metadata, so `uv` installs what each one needs, once, and caches it.

Two invocation styles appear across these docs, and they are equivalent. `uv run` is the
canonical one used everywhere here; if you have built the `.venv/` (see
[Development](#development)) the plain-Python form works too:

=== "uv (recommended)"

    ```sh
    uv run tools/patch_smeg.py     --src SMEG_PLUS_UPG --out overlay
    uv run tools/patch_contract.py --package SMEG_PLUS_UPG_mod
    ```

=== "venv / plain Python"

    ```sh
    .venv/bin/python tools/patch_smeg.py     --src SMEG_PLUS_UPG --out overlay
    .venv/bin/python tools/patch_contract.py --package SMEG_PLUS_UPG_mod
    ```

## From a checkout

```sh
git clone https://github.com/KRoperUK/smeg-plus-patches
cd smeg-plus-patches

uv run tools/patch_studio.py                        # the Qt app (fetches PySide6)
uv run tools/patch_media.py --help                  # media partition patcher
uv run tools/ringtones.py list                      # ring/wait tone slots
uv run tools/patch_smeg.py --help                   # application image patcher
uv run tools/ppcemu.py --help                       # run a firmware function, emulated
uv run tools/elfsyms.py SMEG_PLUS_UPG/upgrade.out    # the updater's own symbol table
```

`uv run <script>` reads the script's own dependency list, so the GUI pulls PySide6 and the
CLI tools pull nothing.

## Without a checkout

`uvx` runs the packaged console scripts straight from the repository:

```sh
uvx --from git+https://github.com/KRoperUK/smeg-plus-patches smeg-patch-media --help
uvx --from git+https://github.com/KRoperUK/smeg-plus-patches smeg-ringtones list
uvx --from git+https://github.com/KRoperUK/smeg-plus-patches smeg-patch --help

# the GUI needs the optional Qt extra
uvx --from 'smeg-plus-patches[gui] @ git+https://github.com/KRoperUK/smeg-plus-patches' smeg-studio
```

| console script | equivalent |
|---|---|
| `smeg-studio` | `tools/patch_studio.py` |
| `smeg-emu` | `tools/ppcemu.py` |
| `smeg-syms` | `tools/elfsyms.py` |
| `smeg-ringtones` | `tools/ringtones.py` |
| `smeg-patch-media` | `tools/patch_media.py` |
| `smeg-patch` | `tools/patch_smeg.py` |

## Development

`.venv/` is gitignored, so a fresh clone does not have one. Build it once — Python
3.13, because Homebrew's `python3` is 3.14 and PySide6 has no wheels for it:

```sh
uv venv --seed --python 3.13 .venv
uv pip install --python .venv/bin/python PySide6 pytest zensical ruff
```

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/zensical serve            # live docs preview on :8000
```

The test suite needs **no firmware at all** — it generates a synthetic package, so the
whole patch and repack path is covered in CI.

## One extra binary

Audio conversion (mp3, ogg, flac, m4a, …) shells out to **ffmpeg**. WAV input that is
already in the target format works without it:

```sh
brew install ffmpeg        # macOS
```

## One command per package: the manifest build

Applying a patch by hand means running three or four tools in order with an `rsync` between
each, and two of those orderings fail *silently* if you get them wrong — the media step
against an un-patched package drops the application change, and re-sealing before the last
edit leaves the package rejected by the unit (string 2099).

`tools/build_package.py` owns that ordering. A build becomes a file you can read, commit
and re-run:

```json
{
  "package": "SMEG_PLUS_UPG",
  "out": "SMEG_PLUS_UPG_custom",
  "module": "NAV",
  "app":   { "patches": ["aux-autoswitch"] },
  "media": {
    "tones":  { "ring_tones/ring1RT.wav": { "source": "tone.mp3", "gain_db": 7.4 } },
    "splash": { "peugeot": "logo.png" },
    "names":  { "ring1": "Piano Riff" }
  },
  "seal": true
}
```

```sh
uv run tools/build_package.py --manifest build.json
uv run tools/build_package.py --manifest build.json --dry-run   # show the steps only
```

!!! warning "`user_data` ships to the unit's USER_DATA partition — it can wipe settings"

    `system.bin` extracts to the read-only `/SYSTEM/`, so settings edited there can appear to
    do nothing: the application reads them from `/USER_DATA`, a separate partition holding the
    car's own state — paired phones, navigation destinations, presets. The updater has a step
    that copies a `USER_DATA` payload over it.

    A manifest with a `user_data` section is **refused** unless it also sets
    `accept_data_loss: true`, and the warning prints either way. That flag means a person was
    told what it may cost and agreed to it.

`media.settings` writes integers into the settings database
(`Data_base/sqlite/up_common.sqlite`), as `Section.Name`. These need no code patch, so they
are the safest changes the project can make — the worst case is that the firmware ignores
them:

```json
"settings": { "supervisor.Last_Source": 4 }
```

`media.gui_ver` sets `GUI_VER` in the partition's `Data_base/smeg.inf`, which the System Info
screen shows as **Display version**. It is the one visible field nothing gates on, so it is
the safe way to mark a build:

```json
"gui_ver": "32.01"
```

!!! tip "Use it as a build marker"

    Re-flashing the same release changes no other version string, so there is otherwise no
    way to confirm *which* build a unit is running. Bumping `GUI_VER` gives an unambiguous
    on-screen answer. Note it edits the copy **inside `system.bin`** — the module-level
    `NAV/smeg.inf` beside it is what the updater reads and is left alone. See
    [Version strings](VERSION_STRINGS.md).

!!! warning "Patch sets accumulate, in order"

    Listing several sets in `app.patches` applies each one to the package built so far, so a
    build asking for `["aux-always-available", "aux-boot-default"]` carries both edits. (Up
    to and including v0.6.0 each set was applied to the *stock* source, so all but the last
    were silently reverted — if you built a multi-set package before that, rebuild it.)

Ready-made **schemes** live in `builds/`. Each is a whole build, so a scheme is one command:

| scheme | what it does | needs |
|---|---|---|
| `builds/aux-only.json` | the AUX patches and nothing else — the closest thing to stock that still enables AUX, and the baseline to reach for when something behaves unexpectedly | nothing |
| `builds/aux-boot.json` | AUX selectable **and** resumed on every boot (`aux-boot-default`), with a `GUI_VER` marker so you can see which build is running | nothing |
| `builds/diagnostic.json` | turns the application's own logging back on, for establishing whether a message reaches the app at all | nothing |
| `builds/force-aux-default.json` | AUX patches, custom tone and name, and `Last_Source` set so the unit starts on AUX | a tone file, and the `/USER_DATA` acknowledgement |

```sh
uv run tools/build_package.py --manifest builds/aux-only.json
```

### A note on the schemes as committed

They carry **absolute paths for one checkout**, because a manifest is a build recipe rather
than a portable artefact — edit the paths before reusing one. A scheme that reaches outside
the repository (a tone file, an image) will say so in its `_comment`.

Every section is optional. `gain_db` is worth setting: the stock tones sit at about
-1 dBFS, so an unmodified music track sounds muted in the car next to them.

## Pre-flight: check a package before it goes on a stick

`tools/build_package.py` runs this automatically at the end of every build and **fails the
build** if it reports a problem. You can also run it directly:

```sh
uv run tools/preflight.py --package SMEG_PLUS_UPG_auxdefault
uv run tools/preflight.py --package SMEG_PLUS_UPG_auxdefault --json
```

It checks the things that have actually gone wrong, rather than what looks impressive:

- **the contract** — will the unit accept it, or answer with string 2099?
- **the CRC cascade** — image, `.inf`, `smeg.inf`
- **which patches are present**, by reading the bytes at each known address
- **settings values against what the unit accepts** — `supervisor.Last_Source = 4` did not
  start the unit on AUX, and nothing said why. That cost a car trip. The first explanation
  was a `USER_DATA` payload in a folder not named `SMEG_PLUS_UPG`, which is skipped silently
  and looks identical — pre-flight now fails on that — but a later flash was laid out
  correctly and **still** did not apply its payload, so that was not the whole story. See
  [Hardware verification](VERIFICATION.md), and [The AUX chain](AUX_CHAIN.md) for the
  candidate numberings.
- **the firmware version** — every patch address belongs to one version, so it says which one
  this package carries (`firmware 5.43.A.R2`) before anyone decides whether the patches apply.
  Two entries in `patches/` match at the same address on the wrong version, so the bytes alone
  cannot answer this — see [Patch definitions](PATCHES.md).
- **what the update will write**, so the blast radius is visible
- **a `USER_DATA` payload**, which can reset paired phones and presets — and the two ways it
  silently fails to arrive. The updater reads it from the **hard-coded**
  `/bd0/SMEG_PLUS_UPG/NAV/USER_DATA`, so a package folder under any other name, or a payload
  for another module, is skipped while the update otherwise succeeds; pre-flight **fails** on
  both. It also warns about the casing trap that made three flashes do nothing: the payload's
  `sqlite` directory only reaches the unit as lowercase if it carries a long-filename entry.
  See [Flashing](FLASHING.md#working-around-it-give-the-directory-a-long-filename-entry).

And it prints what it **does not know** as prominently as what it does. The unknowns are
where the car trips went.

## Cheat sheet

```sh
# what is in a media partition, and what tones it has
uv run tools/patch_media.py list --package SMEG_PLUS_UPG --module NAV --tones

# pull it out, keeping a copy of the originals for restore
uv run tools/patch_media.py extract --package SMEG_PLUS_UPG --module NAV \
    --tree media --backup backups --backup-tones-only

# put one back
uv run tools/patch_media.py restore --backup backups --tree media \
    --module NAV --only ring_tones/ring1RT.wav

# see what would change, without writing
uv run tools/patch_media.py apply --package SMEG_PLUS_UPG --module NAV \
    --tree media --out overlay --dry-run

# rebuild the package from whatever differs in the tree
uv run tools/patch_media.py apply --package SMEG_PLUS_UPG --module NAV \
    --tree media --out overlay
rsync -a overlay/ SMEG_PLUS_UPG_mod/

# application image patches (the AUX work)
uv run tools/patch_smeg.py --src SMEG_PLUS_UPG --out overlay
rsync -a overlay/ SMEG_PLUS_UPG_mod/

# brand splash: inspect, or swap the boot logo (also works in the GUI)
uv run tools/splash.py --tree media list
uv run tools/splash.py --tree media replace --marque peugeot --image my-logo.png
uv run tools/splash.py --tree media selftest     # proves the container model

# ALWAYS last, whatever else you changed
uv run tools/patch_contract.py --package SMEG_PLUS_UPG_mod
```

!!! warning "These tools write overlays, not packages"

    `patch_smeg.py` and `patch_media.py` write **only the files they change** (a handful
    of manifests, the image, the tar) into `--out` — they do not produce a complete
    package. Overlay the result onto a copy of your package with `rsync`. Pass
    `--copy-package` to `patch_smeg.py` if you would rather it copy the whole thing.

    `patch_contract.py` is the exception: with no `--out` it rewrites `contract.dat`
    **in place**.

Ordering and the two orderings that matter:

- **Application patch, then media patch.** `patch_smeg` rewrites `NAV_ctrl.bin` and
  `ctrl.bin` for the application image; `patch_media` swaps the `system.bin` records
  *inside those same manifests*. Run the media step against the already-patched package
  and it carries the application change; run it against the stock package and it does not.
- **Contract re-seal last.** It seals whatever the package contains at that moment, so
  anything changed afterwards is unsealed and the unit will reject it (string 2099).

A complete worked example — an application patch plus a custom ring tone — is in
[Ring tones](RINGTONES.md#worked-example-replacing-a-ring-tone).
