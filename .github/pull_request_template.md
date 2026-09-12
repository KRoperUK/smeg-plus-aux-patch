## What does this change?

<!-- A sentence or two. Link the issue it closes, e.g. "Closes #35". -->

## Checklist

- [ ] The **PR title is a conventional commit** — the repo squash-merges, so the title
      becomes the commit on `main` and is what Release Please reads:
      `feat:` (minor) · `fix:` (patch) · `feat!:` / `fix!:` (major) ·
      `docs:` `refactor:` `ci:` `chore:` (no release)
- [ ] `uv run python -m pytest tests -q` passes
- [ ] `uv run ruff check tools tests` is clean
- [ ] If paths or behaviour changed, the docs were updated
- [ ] No vendor firmware, upgrade packages or symbol maps are included
      (`.gitignore` blocks them — this repo ships tooling and notes only)

## Verification

<!-- How did you check it? Which package/unit, what did you observe? -->
