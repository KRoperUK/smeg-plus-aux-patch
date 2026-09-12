# Running the tools

Everything here runs with [uv](https://docs.astral.sh/uv/) — no virtualenv to set up, no
`pip install`. The scripts carry [PEP 723](https://peps.python.org/pep-0723/) inline
metadata, so `uv` installs what each one needs, once, and caches it.

## From a checkout

```sh
git clone https://github.com/KRoperUK/smeg-plus-aux-patch
cd smeg-plus-aux-patch

uv run tools/ringtone_studio.py                     # the Qt app (fetches PySide6)
uv run tools/patch_media.py --help                  # media partition patcher
uv run tools/ringtones.py list                      # ring/wait tone slots
uv run tools/patch_smeg.py --help                   # application image patcher
```

`uv run <script>` reads the script's own dependency list, so the GUI pulls PySide6 and the
CLI tools pull nothing.

## Without a checkout

`uvx` runs the packaged console scripts straight from the repository:

```sh
uvx --from git+https://github.com/KRoperUK/smeg-plus-aux-patch smeg-patch-media --help
uvx --from git+https://github.com/KRoperUK/smeg-plus-aux-patch smeg-ringtones list
uvx --from git+https://github.com/KRoperUK/smeg-plus-aux-patch smeg-patch --help

# the GUI needs the optional Qt extra
uvx --from 'smeg-plus-aux-patch[gui] @ git+https://github.com/KRoperUK/smeg-plus-aux-patch' smeg-studio
```

| console script | equivalent |
|---|---|
| `smeg-studio` | `tools/ringtone_studio.py` |
| `smeg-ringtones` | `tools/ringtones.py` |
| `smeg-patch-media` | `tools/patch_media.py` |
| `smeg-patch` | `tools/patch_smeg.py` |

## Development

A virtualenv with everything (Qt, pytest, zensical) already exists in the repo — Python
3.13, because Homebrew's `python3` is 3.14 and PySide6 has no wheels for it:

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/zensical serve            # live docs preview on :8000
```

Rebuild it with:

```sh
uv venv --seed --python 3.13 .venv
uv pip install --python .venv/bin/python PySide6 pytest zensical
```

The test suite needs **no firmware at all** — it generates a synthetic package, so the
whole patch and repack path is covered in CI.

## One extra binary

Audio conversion (mp3, ogg, flac, m4a, …) shells out to **ffmpeg**. WAV input that is
already in the target format works without it:

```sh
brew install ffmpeg        # macOS
```

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
