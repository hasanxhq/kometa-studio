# Kometa Studio — agent guide

Instructions for anyone, human or agent, working on this repository. `CLAUDE.md` only points here; put new instructions in this file.

## What this is

An unofficial, arr-style web GUI for [Kometa](https://github.com/Kometa-Team/Kometa). Studio edits Kometa's YAML files, schedules runs, launches Kometa as a one-shot subprocess (`--run`), and records what changed. The current plan is `KOMETA_STUDIO_HANDOFF_v2.md`.

**Never modify Kometa.** No patches, no imports of Kometa internals. Studio only writes the user's own config and YAML files that Kometa reads.

## Layout

| Path | Holds |
|---|---|
| `kometa_studio/` | Python backend (FastAPI). `app.py` API and SPA serving, `db.py` SQLite and migrations, `settings.py` `STUDIO_*` env settings |
| `kometa_studio/plex.py`, `plex_routes.py` | plex.tv sign-in, server discovery and probing; the `/api/v1/plex` endpoints |
| `kometa_studio/kometa_config.py` | Reads and writes Kometa's `config.yml` (ruamel round-trip: comments survive; backup, then atomic replace) |
| `kometa_studio/crypto.py` | Encrypts secrets kept in SQLite with the key in `<data dir>/secret.key`. Never send stored tokens to the browser |
| `kometa_studio/migrations/` | Numbered schema migrations (`0001_initial.sql`, ...). Never edit one that has been merged; add the next number |
| `kometa_studio/static/` | Built frontend (git-ignored; `npm run build` writes it) |
| `frontend/` | React + Vite + TypeScript app. `src/nav.ts` defines the navigation and routes, `src/api.ts` the API calls, `src/components/ui.tsx` shared building blocks |
| `tests/` | Backend tests and fixtures. `fakeplex.py` stands in for plex.tv and a Plex server; tests never touch the network |
| `Dockerfile`, `compose.yaml` | Image built on `kometateam/kometa:<tag>`; Kometa stays at `/` with its own venv |
| `kometa/` | Read-only clone of upstream Kometa for reference. Git-ignored; never commit it or edit it |

## Tests

CI runs one job, `test` (`.github/workflows/ci.yml`). Each part runs once it exists:

- Backend: `python -m pip install -e ".[dev]"` then `python -m pytest`
- Frontend: `cd frontend && npm ci && npm run typecheck && npm test`

Run the same commands locally before every commit. Keep the job name `test`: branch protection requires it by that name.

## Version and changelog

- The version lives only in `VERSION`. When `pyproject.toml` or `frontend/package.json` are added, they must read it from there rather than repeat it.
- `CHANGELOG.md` follows Keep a Changelog. Add every user-facing change under `## [Unreleased]`.

## Git workflow

Follow this exactly; branch protection and CI enforce most of it.

### Branches

| Branch | Holds | Cut from | Merges into |
|---|---|---|---|
| `main` | Released versions only | — | — |
| `dev` | Integrated, tested work; the default branch | `main`, once | `release/*` |
| `<topic>` (e.g. `plex-wizard`) | One piece of work | Latest `dev` | `dev` |
| `release/vX.Y` | One release being finalised | `dev` | `main`, then back into `dev` |
| `hotfix/<name>` | An urgent fix to a release | `main` | `main`, then back into `dev` |

- **Never commit or push to `main` or `dev` directly.** Check `git branch --show-current` before every commit.
- **PRs into `main` come only from `release/*` or `hotfix/*`.** The `pr-source-check` workflow fails any other source.
- **One topic branch per piece of work**, cut from the latest `dev`. Open its PR into `dev` at the first checkpoint so CI runs on every push.
- **Before pushing, check the branch's PR is still open** (`gh pr view`). Never push to a merged branch; start a new one from `dev`.
- **Keep a branch current by merging `dev` into it**, not by rebasing. Rerun the tests after.
- **Delete topic branches** (local and remote) after their PR merges.
- When several people or agents work at once, use a separate worktree per branch (`git worktree add ../kometa-studio-<topic> -b <topic> origin/dev`), push only to branches you created, and never discard or commit changes you didn't make.

### Commits

- Each commit is one logical change with passing tests. The message says what changed, why, and the test result. Push right after committing.
- A red CI run is a broken checkpoint; fixing it comes next.
- **Never rewrite pushed history:** no force-push, no amending or rebasing pushed commits. Undo with `git revert`.

### Merging

- **Topic → `dev`:** squash merge once CI is green. No review is required; the author may merge their own PR.
- **`release/*` or `hotfix/*` → `main`, and `main` → `dev`:** always a **merge commit**, never squash or rebase.
- After merging into `dev`, once that commit's CI is green, tag it `checkpoint/<YYYY-MM-DD>-<topic>` (annotated; check the name is free with `git ls-remote --tags origin`).

### Releases

Only when the maintainer asks. One `release/*` branch at a time.

1. Cut `release/vX.Y` from `dev` once `dev`'s CI is green.
2. On it, only: stabilising fixes, the `VERSION` bump, the `CHANGELOG.md` entry, and docs.
3. PR into `main`; merge with a merge commit after CI passes and the maintainer approves.
4. Tag the merge commit `vX.Y.0` (annotated), push the tag, and create a GitHub release from the changelog entry.
5. Merge `main` back into `dev` through a PR, then delete the release branch.

**Hotfixes:** `hotfix/<name>` from `main` with the fix, its tests, a patch `VERSION` bump and a changelog entry; PR into `main`, tag `vX.Y.Z`, merge `main` back into `dev`. If a release branch is open, merge the hotfix into it too.

`vX.Y.Z` tags go only on `main`. Never move or delete a pushed tag.

## Contributing to Kometa itself

Changes to Kometa belong upstream, not here. Fork `Kometa-Team/Kometa` and follow its workflow: branch from `nightly` and open the PR into `nightly` (see its `.github/CONTRIBUTING.md`).
