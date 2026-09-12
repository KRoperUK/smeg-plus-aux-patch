# Contributing

Small project, so this is short. The two rules that matter are **conventional commit
titles** and **no vendor firmware**.

## 1. Conventional commit titles

Pull requests are squash-merged, so **the PR title becomes the commit on `main`** — and
that is what [Release Please](https://github.com/googleapis/release-please) reads to
decide the version and build `CHANGELOG.md`.

| title | release |
|---|---|
| `feat: add long-press SRC trigger` | **minor** — `0.2.0` → `0.3.0` |
| `fix: correct AUX gain default` | **patch** — `0.2.0` → `0.2.1` |
| `feat!: drop the availability patch` | **major** — `0.2.0` → `1.0.0` |
| `fix!: change the patch file layout` | **major** |
| `docs:` `refactor:` `perf:` `chore:` `ci:` `test:` `build:` | no release on their own |

A breaking change can also be flagged with a footer:

```
feat: rework the patch definition format

BREAKING CHANGE: patches/*.json now requires a "base" field.
```

Getting the title wrong is the usual reason a merged PR produces no release. See
[Releasing](https://smeg.kroper.uk/RELEASING/) for the full flow.

## 2. No vendor firmware

This repository ships **tooling and notes only**. Never commit upgrade packages, firmware
images, symbol maps, ring tones or other Magneti Marelli / Stellantis content — the
`.gitignore` blocks the usual extensions, but check before you commit. Tests build a
synthetic package precisely so that no real firmware is needed.

## Working with AI agents

If you are an AI agent, or you use one on this repository, read
[`AGENTS.md`](AGENTS.md) first — it is the authoritative brief (hard rules, how to run
things, testing without firmware, and the firmware details that are easy to get wrong).
`.github/copilot-instructions.md` points at it for GitHub Copilot.

## Working on it

```sh
git clone https://github.com/KRoperUK/smeg-plus-patches
cd smeg-plus-patches

uv run python -m pytest tests -q      # 19 tests, no firmware required
uv run ruff check tools tests
uv run tools/ringtone_studio.py      # the GUI
```

`uv` reads the PEP 723 metadata in each script, so there is nothing to install by hand.
See [Running the tools](https://smeg.kroper.uk/RUNNING/).

## Changing a patch address

Patch definitions live in `patches/*.json` and are checked before they are written — each
entry carries the original bytes it expects. When you move a patch for a different build,
verify the address against the symbol map for that build first, and say in the PR which
images you checked.
