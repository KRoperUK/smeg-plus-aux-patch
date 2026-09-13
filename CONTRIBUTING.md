# Contributing

Small project, so this is short. The two rules that matter are **conventional commit
titles** and **no vendor firmware**.

## 1. Conventional commit titles

**This is enforced, not a preference.** Two checks will stop you:

* a `commit-msg` hook, installed by `pre-commit install`, rejects a local commit whose
  message does not parse;
* the **PR title** check in CI, because the PR title is the message that actually lands.

Both run the same validator, which you can also call yourself:

```sh
python3 tools/check_commit_msg.py --title "feat: always offer AUX first in the SRC cycle"
```

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
uv run tools/patch_studio.py         # the GUI
```

`uv` reads the PEP 723 metadata in each script, so there is nothing to install by hand.
See [Running the tools](https://smeg.kroper.uk/RUNNING/).

## Changing a patch address

Patch definitions live in `patches/*.json` and are checked before they are written — each
entry carries the original bytes it expects. When you move a patch for a different build,
verify the address against the symbol map for that build first, and say in the PR which
images you checked.

## 3. Gotchas worth knowing

Things that have each cost time here at least once, in roughly the order you meet them.

### The working loop

```sh
uv run tools/build_package.py --manifest builds/<scheme>.json
```

That is the whole loop. The build **runs its own pre-flight** (`tools/preflight.py`) and
refuses to produce a package that fails it, so a bad value or an unsealed contract is caught
here rather than after a twenty-minute flash in a car.

The pre-flight prints what it **does not know** as prominently as what it does. Read that
part — it is where the expensive surprises live.

### The two hook gates

`pre-commit install` wires **all three** hook types — the config asks for them, so there is
no `--hook-type` to remember. They are split by how long they take:

| stage | what runs | why there |
|---|---|---|
| `pre-commit` | whitespace, EOF, YAML, merge markers, large files, line endings, `ruff --fix`, and the no-firmware guard | fast enough that you never want to skip it |
| `commit-msg` | `tools/check_commit_msg.py` | the message has to parse before it exists |
| `pre-push` | `pytest`, `zensical build --strict`, `bandit` | this is what CI would tell you twenty minutes later |

A push that would go red in CI fails locally first. If you genuinely need to bypass one,
`git push --no-verify` — but the same checks run on the PR, so it only moves the failure.

`bandit` is the security scan. Its config lives in `[tool.bandit]` in `pyproject.toml`, and
the three skips there are deliberate: these tools shell out to `ffmpeg` and to each other,
which is the job rather than a finding. If you add a genuine exception, say why in the
config rather than with a bare `# nosec`.

### Commits and merges

- **Conventional commits are enforced** in two places: a `commit-msg` hook and a CI check on
  the PR title. The description must start **lower case** — `fix: AUX is wrong` is rejected,
  `fix: the AUX value is wrong` is not.
- **The repo squash-merges**, so local branches never appear as ancestors of `main` even once
  merged. `git branch --merged` will not tell you what is safe to delete; ask GitHub instead:
  `gh pr list --state merged --json headRefName`.
- **The `end-of-file-fixer` hook modifies files and then aborts the commit.** If you generate
  JSON with `json.dump`, add the trailing newline yourself or you will commit twice.

### Blocked PRs

`BLOCKED` with every check green almost always means **unresolved review threads**, not a
failed check. CodeQL posts its findings as review threads and **does not resolve them when
the code changes**, so a fixed alert can still be holding the merge:

```sh
gh api graphql -f query='{ repository(owner:"KRoperUK", name:"smeg-plus-patches") {
  pullRequest(number:N) { reviewThreads(first:30) { nodes { id isResolved path } } } } }'
```

Resolve them, or fix the code and resolve them — but check, because the failure mode is
silent.

### CodeQL

Two shapes keep coming up:

- **"File is not always closed"** — use `pathlib` (`Path(p).read_text()`), which closes what
  it opens. This is the third time it has been raised.
- **"Potentially uninitialized local variable"** — `argparse.error()` looks like it returns.
  Use `sys.exit()` where the fall-through must be impossible.

### The USB stick, on macOS

Writing to FAT32 makes macOS silently create an AppleDouble `._*` file **per file**, including
for files you add in a later copy. They are invisible to the updater but they are junk, and
they have caused confusion twice. After any copy:

```sh
find /Volumes/SMEG -name '._*' -delete; find /Volumes/SMEG -name '.DS_Store' -delete
```

### Releases

Release Please opens its PR with the default `GITHUB_TOKEN`, so **no workflows run on it** and
it sits at `BLOCKED` with *no checks reported*. That is expected. Approving it is a human's
job — see [docs/RELEASING.md](docs/RELEASING.md).
