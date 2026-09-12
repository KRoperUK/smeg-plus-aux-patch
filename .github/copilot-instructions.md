# Copilot instructions

See [`AGENTS.md`](../AGENTS.md) at the repository root — it is the single source of
guidance for AI agents here (and covers the rules that matter most: never commit vendor
firmware, use conventional commit titles, `main` is PR-only, and test with the synthetic
fixture rather than a real package).

Quick reminders, in case the model only reads this file:

- **No vendor firmware, ever.** No `.bin`/`.out`/`.mot`/symbol maps/tones committed,
  uploaded as artefacts, or attached to issues.
- **PR titles are conventional commits** — the repo squash-merges, so the title becomes
  the commit on `main` and drives Release Please. `feat:` minor, `fix:` patch,
  `feat!:`/`fix!:` major.
- **Run `pytest tests -q` and `ruff check tools tests`** before proposing a change; both
  work without any firmware.
- Application patches live in `patches/*.json` — prefer adding an entry there over new
  code.
- The patches are **not validated on hardware**. Do not claim a patch works.
