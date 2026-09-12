# Releasing

Releases are automated with [Release Please](https://github.com/googleapis/release-please).
You do not edit version numbers or the changelog by hand.

## Commit messages

Because the repository squash-merges pull requests, **the PR title becomes the commit
message on `main`** — so the PR title must be a conventional commit.

| commit / PR title | release |
|---|---|
| `feat: add long-press SRC trigger` | **minor** — `0.1.0` → `0.2.0` |
| `fix: correct AUX gain default` | **patch** — `0.1.0` → `0.1.1` |
| `feat!: drop the availability patch` | **major** — `0.1.0` → `1.0.0` |
| `fix!: change patch file layout` | **major** |
| `docs:`, `refactor:`, `perf:`, `chore:`, `ci:`, `test:`, `build:` | no release on their own |

A breaking change can also be flagged with a footer instead of the `!`:

```
feat: rework the patch definition format

BREAKING CHANGE: patches/*.json now requires a "base" field.
```

Anything hidden by `changelog-sections` (chore, ci, test, build) still appears in the
commit history but not in the changelog.

## What happens automatically

1. A push to `main` triggers `.github/workflows/release-please.yml`.
2. Release Please opens (or updates) a **release PR** containing the bumped
   `version.txt`, `CHANGELOG.md`, `.release-please-manifest.json` and, for a `!`
   commit, a `⚠ BREAKING CHANGES` section.
3. Merging that PR creates the git tag (`vX.Y.Z`), the GitHub Release, and the
   changelog entry.

Because the branch ruleset allows merge/squash/rebase and requires linear history, the
release PR merges normally. The tag is not covered by the branch ruleset.

## Configuration

- `release-please-config.json` — release type, changelog sections, version bump rules.
- `.release-please-manifest.json` — current released version (kept in sync by the bot).
- `version.txt` — the version file bumped by the `simple` release type.

!!! note "Pre-1.0 behaviour"

    `bump-minor-pre-major` and `bump-patch-for-minor-pre-major` are both `false`, so a
    breaking change takes the project to `1.0.0` rather than staying inside `0.x`. If you
    would rather stay pre-1.0, set `bump-minor-pre-major` to `true`.
