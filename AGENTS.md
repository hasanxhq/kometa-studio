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
| `kometa_studio/kometa_config.py` | Reads and writes Kometa's `config.yml` (ruamel round-trip: comments survive; backup, then atomic replace), including Studio's own webhook entries |
| `kometa_studio/kometa_command.py` | Builds Kometa's command line from a `RunRequest` and reads the flags its `--help` lists. Never add free-form flags to `RunRequest` |
| `kometa_studio/runner.py`, `runs_routes.py` | The run queue (one Kometa at a time), live logs, cancel, run hooks (`before_run` may hold a run or return an after step), and Kometa's webhook receiver; the `/api/v1/runs` and `/api/v1/kometa` endpoints. Endpoints that use SQLite are `async`, so the shared connection stays on the event loop |
| `kometa_studio/scheduler.py`, `schedules_routes.py` | Schedule maths (zoneinfo, DST), the 30 s tick with catch-up and coalescing; the `/api/v1/schedules` endpoints. Queue runs and move `last_fired_at` in one transaction |
| `kometa_studio/kometa_files.py`, `config_routes.py` | Reads config.yml and the files it references, resolved as Kometa does (read-only); `/api/v1/config*` and `/api/v1/history`. The file endpoint must never serve Studio's data folder, and masks secrets |
| `kometa_studio/plex_library.py` | Reads libraries, collections and a collection's titles (a page at a time, with their TMDb/IMDb/TVDb IDs) from the Plex server in config.yml. "Managed" means the `Kometa` or `PMM` label, Kometa's own rule. Posters only go through `/api/v1/plex/image`, so the token stays on the server |
| `kometa_studio/config_write.py`, `backups.py`, `textmerge.py` | Saving Kometa's files: hash check, secrets put back, Kometa's check in a sandbox (edited files written in, the rest linked, webhooks removed), backup, atomic write. Rules: never write a file that wasn't edited; refuse a save only for problems it adds; a crashed check always refuses; Studio's own edits keep the file's formatting (three-way merge, used only if the data matches) |
| `kometa_studio/config_items.py` | One collection/overlay at a time for the forms: unchanged keys keep their YAML node (comments, quotes), then the normal save flow |
| `kometa_studio/reverse_proxy.py` | The URL base (`UrlBaseMiddleware` strips it; paths without it still work, and pages opened without it redirect; the page gets `<base href>`, which the frontend's `base.ts` reads) and trusted proxies (`visitor`: the right-most X-Forwarded-For entry that isn't a trusted proxy; untrusted proxied requests are never local) |
| `kometa_studio/auth.py`, `auth_routes.py` | Sign-in, sessions and the API key; `AuthMiddleware` guards every `/api` path. Only paths in `OPEN_PATHS` skip it, and each of those checks its own token. New endpoints need nothing extra: they're guarded by default. Tests use a local client address (`TestClient(..., client=("127.0.0.1", 50000))`) |
| `kometa_studio/health.py` | Health checks for System → Status and `/api/v1/status`, and Kometa updates from its `version` webhook. Keep checks cheap; anything that calls out (Plex) is remembered for a few minutes |
| `kometa_studio/tasks.py`, `tasks_routes.py`, `full_backup.py` | Studio's built-in tasks (full backup, full check) with their own schedules, ticked by the scheduler; `/api/v1/tasks` and `/api/v1/backups/full`. Full backups live in `<data dir>/full-backups/`, never inside `backups/` (that folder is the YAML backups, one subfolder each) |
| `kometa_studio/arr.py`, `arr_routes.py` | Radarr and Sonarr over their API: Studio polls their import history (it reaches out; nothing has to reach Studio). The connection is config.yml's `radarr:`/`sonarr:` (url, token, root folder, quality profile), which Settings → Connect writes; only a seedbox proxy login is Studio's own (encrypted). Each app has its own settings (`AppRuns`) and its own debounced pending run in SQLite, queued by the scheduler's tick |
| `GET /config/sources` (`kometa_files.unavailable_sources`), `sourceGroups` in `frontend/src/pages/ItemEditor.tsx` | The Add a source list: grouped, and greyed where a service isn't set up or the library's type can't use a source. The lists are copied from Kometa's `builder.py`, so check them on a Kometa update. Kometa's save check doesn't catch either case; only a run fails. |
| `kometa_studio/wanted.py` | "Only imports that matter": sorts each library's collections from its files (smart / rule-based (Plex searches, or can't tell) / list-based, looking inside templates; IDs written in collections), keeps Studio's merged copy of Kometa's missing report (`wanted` table, after runs that reached `run_end`), and decides per import whether a library needs a whole run, only the collections that want it, or nothing. When unsure, it runs |
| `kometa_studio/usage.py` | Kometa's calls per service: a run hook keeps the totals from `logs/timings-*.json` on the run (`runs.api_calls`). Runs don't pass `--timings` for now, because Kometa 2.5.3 crashes on it, so there are no totals until a fixed Kometa. Runs after imports are held while MDBList's daily use (its `/user` answer, asked at most every 15 min and only while one waits, plus Studio's own runs since) is at 80% or more; scheduled and manual runs always go |
| `GET /config/defaults` (`kometa_files.catalogue`, `_toggles`), `frontend/src/pages/Defaults.tsx`, `LibraryDefaults.tsx`, `frontend/src/defaults.ts` | The Defaults gallery, at `/defaults` and on a library's Defaults tab. Titles, wiki links and toggles (what `use_<key>` turns on or off) are read from the installed Kometa's default files. Categories and one-line descriptions are Studio's, in `defaults.ts`, because Kometa's files don't have them and its docs aren't in its image: check them on a Kometa update. A new default lands in Other until then |
| `GET /config/setup` (`kometa_files.setup_steps`), `frontend/src/pages/Setup.tsx` | First-run setup: what Kometa can't run without (Plex, a TMDb key, a library). Overview sends a new install to `/setup`, and Health reports what's missing. Steps reuse Settings' forms; add a step only for something Kometa needs in order to run. |
| `kometa_studio/overlays_routes.py` | The Overlays page: per library, its overlay files, on/off (`remove_overlays` on the library is the "off" state: Kometa restores originals every run while it's set), the Original Posters backup (`overlays/<library> Original Posters/`; turning off is refused without it), the last overlay pass and Maintainerr's overlays there. Apply/off/on queue an overlays-only run, which the Maintainerr hook wraps like any poster run |
| `kometa_studio/network.py`, `network_routes.py`, `kometa_doh/sitecustomize.py` | Settings → Network: a proxy (HTTP/HTTPS/SOCKS5), DNS over HTTPS for ticked services, and IPv4 first, for Studio and Kometa alike, plus a connection check. Studio's one httpx client uses `NetworkTransport` (proxy unless local or on `no_proxy`; DoH by address with SNI and Host; IPv4 bind). Kometa gets `HTTP(S)_PROXY`/`NO_PROXY` and `kometa_doh/` on `PYTHONPATH` (`Runner.extra_env`, `ConfigWriter.extra_env`). For SOCKS5, Studio copies its own PySocks (one module) to `<data>/kometa-extras`; nothing is installed into Kometa's environment. The proxy and DoH are saved only after a passing test |
| `kometa_studio/doh.py` | DNS over HTTPS lookups (`resolve`, `resolve_all`, and `get`, which connects by address with the real name for TLS and Host) for Settings → Network's DoH and its connection check |
| `kometa_studio/config_sections.py` | Changing one section of config.yml (top-level, or nested such as one library) from a Settings form, adding a library, and starting a new collection/overlay file for a library (the file and its `- file:` entry in one save), all through `ConfigWriter.save` (Kometa's check, backup, formatting kept); turning Kometa's defaults on and off for a library and setting their template variables, and the library's own (`with_library_default`, `with_library_variables`) |
| `kometa_studio/services.py` | TMDb and MDBList keys (config.yml's `tmdb:`/`mdblist:`): tested with the call Kometa makes at start-up, saved only after the server's own test passes. MDBList's `/user` also gives the key's daily allowance and use |
| `kometa_studio/tautulli.py` | Tautulli (config.yml's shared `tautulli:` url and apikey): tested with Kometa's start-up call (`cmd=get_tautulli_info`), saved only after the server's own test passes. A library's own `tautulli:` override is left alone |
| `GET/PUT /config/settings` (`config_sections.with_settings`, `kometa_files.settings_defaults`) | Kometa's own `settings:` block. Defaults come from parsing the installed Kometa's `modules/config.py` with `ast`: every global `check_for_attribute(self.data, "<key>", parent="settings", default=…)`. It's never imported. A save carries the values the form started from (`base`) and is refused if config.yml's settings changed since |
| `kometa_studio/logs_routes.py` | Kometa's own log files under `<config>/logs` for System → Logs; only `*.log` / `*.log.N` inside that folder are served |
| `kometa_studio/maintainerr.py`, `maintainerr_guard.py`, `maintainerr_routes.py` | Maintainerr. Its collections are always protected: `maintainerr_guard.risks` finds every way Kometa's config would touch them (delete_collections not limited to managed/configured, mass_collection_mode, a same-named Kometa collection); saves that add one are refused (`ConfigWriter.guard`), runs that would do one are held (a run hook). "Leave Maintainerr overlays alone" makes Maintainerr's overlay go on last: Studio holds Maintainerr's overlay schedule (its cron set to Maintainerr's own "never", the old one kept to give back) and has it draw after every poster-changing Kometa run (reverted before it, redrawn after, retried until done) and once a day, with Kometa's overlays first when the library has anything new since Kometa's last overlay pass. Its overlays are never switched off (every pass checks `enabled`). Never weaken either without the maintainer saying so |
| `kometa_studio/notifications.py`, `notifications_routes.py` | Settings → Notifications: Kometa's notification services (`notifiarr`, `gotify`, `ntfy`, `apprise`) and its `webhooks:` events; the `/api/v1/settings/notifications` endpoints. A service is saved only if Studio's own test of it passes, and the save route runs that test again itself. Saves go through `ConfigWriter`. Studio's own webhook entries are never edited here. Secrets never reach the browser: keys are masked, webhook URLs masked and named by an id. Tests use `tests/fakenotify.py` |
| `kometa_studio/jobs.py`, `frontend/src/components/Jobs.tsx` | The jobs drawer (Bazarr's Jobs Manager): `/api/v1/jobs` gathers runs, built-in tasks, waiting imports and pending Maintainerr steps as one list. Anything new that runs in the background should show up here |
| `kometa_studio/crypto.py` | Encrypts secrets kept in SQLite with the key in `<data dir>/secret.key`. Never send stored tokens to the browser |
| `kometa_studio/migrations/` | Numbered schema migrations (`0001_initial.sql`, ...). Never edit one that has been merged; add the next number |
| `kometa_studio/static/` | Built frontend (git-ignored; `npm run build` writes it) |
| `frontend/` | React + Vite + TypeScript app. `src/nav.ts` defines the navigation and routes, `src/api.ts` the API calls, `src/components/ui.tsx` shared building blocks, `src/components/RunRequestFields.tsx` the run fields shared by Run now and schedules, `src/yaml/` checking YAML against Kometa's schema (tested on Kometa's own defaults: keep false alarms at zero), `src/components/forms/` the form fields |
| `tests/` | Backend tests and fixtures. `fakeplex.py` stands in for plex.tv and a Plex server (shaped like a real server's answers), `fixtures/fake_kometa.py` for `kometa.py`; tests never touch the network |
| `brand/`, `frontend/public/` | The logo: SVG masters, usage rules and `build_icons.py` in `brand/`; favicons, app icons and the web manifest in `frontend/public/`, which are built from them. Edit the masters, not the built files. |
| `Dockerfile`, `compose.yaml` | Image built on `kometateam/kometa:<tag>`; Kometa stays at `/` with its own venv. Kometa's JSON schemas come from the same tag's source into `/studio/json-schema` (Kometa's image leaves them out) |
| `kometa/` | Read-only clone of upstream Kometa for reference. Git-ignored; never commit it or edit it |

## Tests

CI runs one job, `test` (`.github/workflows/ci.yml`). Each part runs once it exists:

- Backend: `python -m pip install -e ".[dev]"` then `python -m pytest`
- Frontend: `cd frontend && npm ci && npm run typecheck && npm test`

Run the same commands locally before every commit, and let their exit codes decide: piping test output (e.g. into `tail`) hides a failure from `&&`. Keep the job name `test`: branch protection requires it by that name.

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
- **One topic branch per piece of work**, cut from the latest `dev`. At the first checkpoint, open its PR into `dev` **as a draft** (`gh pr create --draft`). CI then runs on every push, tested against the latest `dev`, and others can see the work, but nobody can merge it half-done.
- **Mark the PR ready only when the work is complete:** merge the latest `dev` into the branch, rerun the tests, bring the PR description up to date, then `gh pr ready`.
- **Before pushing, check the branch's PR is still open** (`gh pr view`). Never push to a merged branch; start a new one from `dev`.
- **Keep a branch current by merging `dev` into it**, not by rebasing. Rerun the tests after.
- **Delete topic branches** (local and remote) after their PR merges.
- When several people or agents work at once, use a separate worktree per branch (`git worktree add ../kometa-studio-<topic> -b <topic> origin/dev`), push only to branches you created, and never discard or commit changes you didn't make.

### Commits

- Each commit is one logical change with passing tests. The message says what changed, why, and the test result. Push right after committing.
- A red CI run is a broken checkpoint; fixing it comes next.
- **Never rewrite pushed history:** no force-push, no amending or rebasing pushed commits. Undo with `git revert`.

### Merging

- **Topic → `dev`:** squash merge once the PR is marked ready and CI is green. No review is required; the author may merge their own PR. Never merge a draft, and never mark someone else's PR ready.
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

`vX.Y.Z` tags go only on `main`. Alphas aren't releases: bump `VERSION` and date the changelog in a PR into `dev`, tag that merge commit `vX.Y.Z-alpha.N` (annotated), and publish it as a GitHub pre-release. `main` doesn't move for an alpha. Never move or delete a pushed tag.

## Contributing to Kometa itself

Changes to Kometa belong upstream, not here. Fork `Kometa-Team/Kometa` and follow its workflow: branch from `nightly` and open the PR into `nightly` (see its `.github/CONTRIBUTING.md`).
