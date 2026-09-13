# AGENTS.md

Guidance for AI coding agents (and the humans supervising them) working in this
repository. Read this before making changes.

## What this project is

Reverse-engineering notes and tooling for **PSA/Stellantis SMEG+** head units. The
headline goal is an **AUX auto-switch**: an aftermarket CarPlay/Android-Auto piggyback
feeds audio into the unit's AUX input, and the unit should select AUX by itself.

The work is split in two:

* **Application patches** — in-place edits to the PowerPC image inside
  `AppBin/f_BigQuick.bin`, applied and checksum-cascaded by `tools/patch_smeg.py`.
  This is the shipped, tested path.
* **Media-partition edits** — ringing tones, the cheatcode menu, version markers. These
  need `system.bin` unpacked, edited and repacked. **This path is not finished** — see
  issue #35 for the tool and #36 for the one open detail.

## Hard rules

1. **Never commit vendor firmware.** No Peugeot/Citroën/DS/Stellantis/Magneti Marelli
   binaries, no upgrade packages, no symbol maps, no extracted images or tones. The repo
   documents and patches; it does not distribute. `.gitignore` blocks the usual
   extensions, but check before you commit. If a task seems to need a vendor binary in
   the repo, it needs a synthetic fixture instead.
2. **Never upload firmware anywhere** — no CI artefacts, no release assets, no issue
   attachments.
3. **Conventional commit titles.** The repository squash-merges, so **the PR title
   becomes the commit on `main`** and drives Release Please. `feat:` → minor,
   `fix:` → patch, `feat!:`/`fix!:` (or a `BREAKING CHANGE:` footer) → major, everything
   else → no release. See [docs/RELEASING.md](docs/RELEASING.md). Getting this wrong
   silently produces no release.
   **This is enforced** by `tools/check_commit_msg.py` in two places — a `commit-msg` hook
   and a CI check on the PR title. If you are an agent, write the message in the right form
   the first time; `--title` will tell you before you push:
   `python3 tools/check_commit_msg.py --title "feat: ..."`.
4. **Warn the user before anything that can destroy their settings.** Some changes are not
   recoverable by reflashing because they overwrite state the *car* owns rather than state
   we ship. Shipping a `USER_DATA` payload is the current example: it replaces databases on
   the unit's user partition, which hold paired phones, navigation destinations and presets.
   Say so plainly, in those terms, and wait to be told it is acceptable. Never treat a
   person's "I don't care about my settings" as covering a *different* person's car.

   `build_package.py` enforces this: a manifest with `user_data` is refused unless it also
   sets `accept_data_loss: true`, and the warning is printed either way.

5. **`main` is protected.** No direct pushes — work on a branch and open a PR. Deletion,
   force-push and non-linear history are blocked.
6. **A release PR needs a human approval click. That is expected — do not automate it.**
   Release Please opens its PR with the default `GITHUB_TOKEN`, and GitHub will not run
   workflows on a PR created that way until someone approves them, so the release PR sits
   at `BLOCKED` with **no checks reported** and every run showing `action_required`. That
   is the designed behaviour, not a fault, and it is deliberately left to a person:
   approving a release is a decision, not a chore.

   If you are an agent, **do not** work around it — do not call the run-approval API, do
   not add a PAT, do not weaken the ruleset. Report that the release PR is waiting on a
   human and move on. The same applies to merging a release PR.

## How to run things

```sh
.venv/bin/python -m pytest tests -q        # the suite, no firmware required
.venv/bin/python -m ruff check tools tests # lint (E9 + F)
.venv/bin/python tools/patch_studio.py     # the GUI
.venv/bin/zensical serve                   # live docs preview
```

`.venv/` is gitignored, so a fresh clone has none — build it first (Python 3.13, because
Homebrew's `python3` is 3.14, where `ensurepip` is broken and PySide6 has no wheels):
`uv venv --seed --python 3.13 .venv && uv pip install --python .venv/bin/python PySide6 pytest zensical ruff`.

## Testing without firmware

`tests/helpers.py` builds a **synthetic package from scratch** — header + zlib container,
`.inf`, `smeg.inf`, module and root manifests — so the whole patch/repack path is
exercisable without any vendor file. Use it. Adding a fixture is cheap; adding a binary
is not allowed.

Building those tests immediately caught two fixture bugs, so it is worth the effort.

## Areas and their traps

| area | notes |
|---|---|
| `tools/patch_smeg.py` | Checks `expect` bytes before writing, then rebuilds the whole CRC cascade. Prefer adding a `patches/*.json` entry over new code. |
| `tools/ringtones.py` | Needs ffmpeg for non-WAV input, but degrades gracefully. Slot formats matter: ring/status tones are 16-bit **mono 44.1 kHz**, wait tones 16-bit **stereo 8 kHz**. |
| `tools/patch_studio.py` | Qt GUI. Set `QT_QPA_PLATFORM=offscreen` to test it headlessly. |
| `tools/ppcemu.py` | Executes one function at a time on an emulated PowerPC core (Unicorn). Reachability is proof; stub return values are assumptions. Prefer it over reasoning about a branch by eye — it has already overturned one conclusion. |
| `tools/ppcdis.py`, `xref.py`, `callers.py`, `mkelf.py` | The analysis tools every patch address was derived with. Need `capstone`. Untested — see #38. |
| `docs/` | Published with Zensical to <https://smeg.kroper.uk/>. A broken anchor fails the build; run `zensical build` before pushing docs. |

## Firmware knowledge that is easy to get wrong

- The application image is **not** encrypted: `f_BigQuick.bin` is a 0x800-byte header, a
  `0x08` marker at 0x800, then a **zlib stream** from 0x801, inflating to a raw PPC image
  at `0x01000000`. The shipped `abs_symbols_base.txt.gz` lines up with it exactly, so
  patch by symbol, not by pattern.
- Addresses are **per build**. `AUDIO_BT` and `AUDIO_BT_256` usually match each other;
  the NAV build is offset. Never copy an address between builds without checking.
- The media partition is a gzip'd **tar**, and `system_ctrl.bin` holds a per-file CRC for
  everything inside it. `SIZE`/`SIZE_n` in `system.bin.inf` are computable — `SIZE` is the
  sum of the file sizes in the tar, `SIZE_n` the same rounded up per file to *n* KiB.
- **Version strings are not a safe marker.** Display reads `Data_base/smeg.inf` *inside*
  the media partition, so patching the app image changes nothing visible. Editing
  `media.inf` can block the update outright. `GUI_VER` is the only safe visible field.
- The **updater reboots** the unit during the BootROM and Renesas steps. Never propose
  updating while driving.
- **A modified package must be re-sealed** before flashing, or the unit rejects it with
  string 2099. Always run `tools/patch_contract.py` after any change that alters a file
  the contract covers. See `docs/MEDIA_PROTECTION.md`.
- The contract's RSA key material lives in the firmware image and must **never** be
  committed or reproduced in docs. `patch_contract.py` extracts it from the user's own
  package at runtime; keep it that way.

## Working style

- Prefer **data-driven** changes: a new `patches/*.json` beats new Python.
- The patches are **not validated on hardware** by the maintainer. Say so plainly; do not
  claim a patch "works". Report what was verified statically and what needs a car test.
- Add a regression test for any bug fixed, and a synthetic fixture for any new file
  format.
- Keep docs current in the same PR — the user-facing pages are the product here.

## Related documents

- [README.md](README.md) — overview and tool table
- [CONTRIBUTING.md](CONTRIBUTING.md) — the human-facing version of the rules above
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the whole firmware fits together
- [docs/FLASH_CHAIN.md](docs/FLASH_CHAIN.md) — the boot and update chain
- [docs/PATCHES.md](docs/PATCHES.md) — exact addresses and bytes
- [docs/AUX_CHAIN.md](docs/AUX_CHAIN.md) — the AUX auto-switch gate by gate, and which claims are executed rather than read
