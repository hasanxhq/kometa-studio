# Kometa Studio — Claude Code handoff (prototype)

A persistent web app that gives Kometa a GUI. **Kometa stays exactly as it is.** The app treats Kometa as a script: it edits Kometa's YAML files, decides when a run is due, launches Kometa as a one-shot subprocess, and reads back its output and logs.

Design reference: the "Kometa GUI concept" canvas (5 screens: Overview, Defaults gallery, Collection builder, Overlay designer, Schedule & runs). Visual direction: dark UI, amber accent `#F2B544`, Space Grotesk headings, Inter body, JetBrains Mono for YAML/logs.

---

## 1. Hard constraints

1. **Never modify Kometa's code or install.** No patches, no imports of Kometa internals, no files written inside the Kometa folder except the user's own config/YAML files that Kometa already reads.
2. **Kometa never runs in its own scheduler mode.** Every invocation includes `--run`, so Kometa does one pass and exits. The web app is the only scheduler. Do not set `--times` / `KOMETA_TIMES`.
3. **One Kometa process at a time.** Runs are queued; a second trigger while one is running waits in the queue (or is coalesced, see §4).
4. **The web app owns the config files.** Always pass `--read-only-config` so Kometa never rewrites `config.yml` underneath the app.
5. **The app must survive restarts and power cuts.** Schedules, run history and the queue persist in SQLite. On start-up the app handles missed runs (§4.3).
6. **Plain Python process, no Docker or root required.** It must run as a normal user (e.g. under `systemd --user`, or a startup task on Windows), so it works on a shared seedbox as well as a home PC.

---

## 2. Architecture

```
┌──────────────────────────── Kometa Studio (one process) ────────────────────────────┐
│                                                                                      │
│  React SPA (built, served as static files)                                           │
│        │  REST + Server-Sent Events                                                  │
│  FastAPI app ── ConfigService ── (ruamel.yaml round-trip) ──► config.yml + YAML files│
│        │                                                                             │
│        ├── Scheduler loop (asyncio, ticks every 30 s, reads schedules from SQLite)   │
│        │        │ enqueue                                                            │
│        ├── RunQueue ──► KometaRunner ──► subprocess: <kometa python> kometa.py --run …│
│        │                      │  stdout/stderr lines → SSE + run log file            │
│        │                      └─ exit code, duration, summary → SQLite               │
│        └── Webhook endpoint (Radarr/Sonarr "on import") → enqueue                    │
│                                                                                      │
│  SQLite: settings, schedules, runs, run_events, config_backups                       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Stack
- **Backend:** Python 3.12, FastAPI, Uvicorn, `ruamel.yaml` (round-trip, keeps comments and order), SQLite via SQLAlchemy 2 or plain `sqlite3`, `pydantic-settings` for app config.
- **Scheduler:** our own small asyncio loop with schedules stored in SQLite. Do **not** add Celery/Redis. APScheduler is acceptable only if its job store is SQLite and missed-run handling matches §4.3; a hand-rolled loop is simpler and preferred.
- **Frontend:** React + Vite + TypeScript, Tailwind (tokens below), React Router, TanStack Query. A YAML viewer with syntax highlighting (CodeMirror 6, read-only in the prototype).
- **Packaging:** `pip install -e .` → `kometa-studio` CLI that serves the built frontend from FastAPI. One port, one process.

### Design tokens
```
--bg #0F1114   --surface #16191D   --surface-2 #1A1D21   --sidebar #14171B
--border #23272D   --border-strong #2C3138
--text #ECEDEE   --muted #9AA1A9   --accent #F2B544   --on-accent #1A1406
--ok #8FD6A0   --warn #F2C77A   --err #F29B8A   --info #9DC2F7
radius: 8px controls, 12px cards; touch targets ≥ 44px
```

---

## 3. Kometa integration contract

### 3.1 App settings (first-run wizard, stored in SQLite; overridable by env vars)
| Setting | Example | Notes |
|---|---|---|
| `kometa_python` | `/home/user/kometa/kometa-venv/bin/python` | The interpreter of Kometa's own venv |
| `kometa_entry` | `/home/user/kometa/kometa.py` | |
| `kometa_config` | `/home/user/kometa/config/config.yml` | Passed as `--config` |
| `kometa_logs_dir` | `/home/user/kometa/config/logs` | Default: `logs/` beside the config. Verify on the real install |
| `extra_env` | `{}` | Passed through, e.g. `KOMETA_*` secrets |

The wizard checks each path exists, runs `<python> <entry> --help` and stores the output so the app can detect which flags this Kometa version supports.

### 3.2 Command builder
Every run is built from a `RunRequest`:

```python
@dataclass
class RunRequest:
    mode: Literal["all", "collections", "overlays", "operations", "metadata", "playlists"]
    libraries: list[str] | None = None      # → --run-libraries "A|B"
    collections: list[str] | None = None    # → --run-collections "A|B"
    files: list[str] | None = None          # → --run-files "A|B"  (not overlay files)
    ignore_schedules: bool = False          # → --ignore-schedules
    no_missing: bool = False                # → --no-missing
    tests_only: bool = False                # → --tests  (collections marked test: true)
    trigger: Literal["manual", "schedule", "webhook", "catch_up"]
```

Always added: `--config <path> --run --no-countdown --read-only-config --ignore-ghost`.

Mode flags: `collections → --collections-only`, `overlays → --overlays-only`, `operations → --operations-only`, `metadata → --metadata-only`, `playlists → --playlists-only`, `all → none`.

Validation run (used for the "check before save" and "test connections" features): `--config <path> --validate --validate-level full` — exits 0 on pass, 1 on errors, and does not change Plex.

**Before relying on any flag, confirm it against the stored `--help` output** and disable the matching UI control if the installed Kometa lacks it. Flags were taken from the Kometa wiki's run-commands page in October 2026.

Never pass `--delete-collections`, `--delete-labels` or `--log-requests` from the UI in the prototype. They are destructive or leak tokens.

### 3.3 Runner behaviour
- Launch with `asyncio.create_subprocess_exec` (no shell), `cwd` = Kometa's folder, env = `os.environ + extra_env`.
- Stream stdout/stderr line by line: write to `data/runs/<run_id>.log`, push to SSE subscribers, and match lines for warnings/errors (`WARNING`, `ERROR`, `CRITICAL`, tracebacks) to build the run summary.
- Store: start, end, duration, exit code, command (with secrets masked), warning count, error count, trigger, status (`queued|running|succeeded|failed|cancelled|interrupted`).
- **Cancel:** send SIGTERM (CTRL_BREAK on Windows), wait 30 s, then kill. Mark `cancelled`.
- **Hard timeout:** configurable, default 3 h → kill, mark `failed: timeout`.
- On app start, any run still marked `running` becomes `interrupted` (it died with the app).
- The runner must work on Linux and Windows (Hasan's PC may be either; check before choosing signals).

### 3.4 "What changed" summary
Kometa has no machine-readable output, so this is best-effort log parsing. Write the parsers in one module (`kometa_studio/parse.py`) with fixture logs in `tests/fixtures/` so they can be fixed when Kometa's log format changes. If a line doesn't match, show the raw log rather than guessing. Use a real `meta.log` from Hasan's install as the first fixture.

---

## 4. Scheduler

### 4.1 Model
```
schedules(id, name, mode, libraries_json, days_mask, time_local, timezone, enabled,
          ignore_schedules, last_fired_at, created_at)
```
- One row per line on the "Schedule & runs" screen (e.g. *Collections · all libraries · every day 03:00*, *Overlays · Movies, TV · Tue + Sat*).
- Timezone stored explicitly (default `Asia/Kolkata`); DST-safe via `zoneinfo`.

### 4.2 Loop
Every 30 s: compute schedules whose next occurrence ≤ now and > `last_fired_at`, enqueue a `RunRequest`, set `last_fired_at` in the same transaction.

**Coalescing:** if several schedules fire in the same tick, enqueue them in the order `operations → metadata → collections → overlays → playlists`. If one of them is `all`, it replaces the others. Never enqueue a duplicate of a request that is already queued.

### 4.3 Missed runs (power cuts, restarts)
Per schedule, a `catch_up` setting:
- `run_once` (default): if one or more occurrences were missed while the app was down, run once on start-up, tagged `catch_up`.
- `skip`: ignore missed occurrences.
Only consider occurrences in the last 24 h. Show a banner on the Overview after a catch-up.

### 4.4 Webhook trigger
`POST /api/hooks/arr?token=<secret>` accepts Radarr/Sonarr "On Import" payloads, maps the arr instance to a library (a mapping set in Settings), and enqueues `{mode: "all", libraries: [lib]}` after a **debounce window** (default 10 min) so a batch of imports causes one run.

---

## 5. Config editing

- `ConfigService` loads `config.yml` and every file it references (`collection_files`, `overlay_files`, `playlist_files`, `metadata_files`; `file:` entries only — `default:`, `url:` and `git:` entries are read-only references).
- All edits go through `ruamel.yaml` round-trip so comments, key order and anchors survive.
- **Save flow:** write to a temp copy → run Kometa `--validate` against the temp config → if it passes, back up the current files to `data/backups/<timestamp>/` and atomically replace them → otherwise show the validation errors and keep the old files. Keep the last 30 backups and offer restore on a diff screen.
- If a file changed on disk since the app read it (mtime/hash), refuse the save and show a "file changed outside Kometa Studio — reload" message.
- Every form shows the YAML it will write (Form/YAML toggle). In the prototype the YAML tab is **read-only**.

---

## 6. Screens — prototype scope

| Screen | Prototype must do | Deferred |
|---|---|---|
| **Overview** | Run-now with mode select; status cards (last run, next run, warnings); per-library cards (count of collections/overlay files from config); last-run summary list; connection status from the latest `--validate` result | Item counts from Plex |
| **Defaults gallery** | List defaults a library uses; enable/disable a default; edit a small set of template variables per default as form fields with raw key/value fallback; save via §5 | Full catalogue of every default's variables (start with Streaming, TMDb charts, Genre, Separators, Resolution/Audio overlays) |
| **Collection builder** | List collections per file; create/edit a collection with builders `tmdb_trending_weekly`, `trakt_list`, `imdb_chart`, `mdblist_list`, `letterboxd_list`, `plex_search`; filters as chips (year, rating, genre); `sync_mode`, `collection_order`, visible home/library/shared, `radarr_add_missing`; "Test this collection" = set `test: true` on it temporarily, run with `--tests`, then remove the flag | **Live preview** of matching items (would need the app to call TMDb/Trakt itself — out of scope) |
| **Overlay designer** | List overlay files and their overlays; edit position (`horizontal_align`, `vertical_align`, offsets), `back_color`, `back_radius`, conditions as `plex_search` fields; a CSS mock of the poster showing badge placement | Rendering real overlay images; drag to position |
| **Schedule & runs** | CRUD schedules (§4); run history table; live log via SSE; cancel; retry; catch-up setting; webhook mapping | Log search |
| **Settings** | First-run wizard (§3.1); app password; bind address/port; timezone | — |

### Changes from the design mock
- **"Dry run" button → "Validate".** Kometa has no dry run; `--validate --validate-level full` is the closest safe equivalent.
- **"Pending changes"** = files edited in the app since the last successful run (tracked by the app, not Kometa).
- The poster colours in the mock are placeholders; the prototype keeps placeholders (no poster fetching).

---

## 7. API (sketch)

```
GET  /api/status                      last run, next run, queue, running run
POST /api/runs                        body: RunRequest → run_id
GET  /api/runs?limit=50               history
GET  /api/runs/{id}                   detail + summary
GET  /api/runs/{id}/stream            SSE log lines (replays file, then live)
POST /api/runs/{id}/cancel
POST /api/validate                    run --validate, return parsed result

GET  /api/config/libraries            libraries + their attached files/defaults
GET  /api/config/files/{file_id}      parsed content + raw YAML
PUT  /api/config/files/{file_id}      edited structure → save flow (§5)
GET  /api/config/backups              list ; POST /api/config/backups/{id}/restore

GET/POST/PUT/DELETE /api/schedules
POST /api/hooks/arr?token=…
GET/PUT /api/settings
```

---

## 8. Security
- Bind to `127.0.0.1` by default. If bound publicly (seedbox), require the app password (argon2 hash, session cookie) and recommend reaching it through the existing VPN or a reverse proxy with HTTPS.
- Never send Plex/TMDb/Trakt tokens to the browser: mask `token`, `apikey`, `client_secret`, `authorization` values in API responses, YAML previews and the stored command line.
- Webhook endpoint protected by its own random token.
- Subprocess launched without a shell; arguments built from validated values only (library/collection names must exist in the config).

---

## 9. Build order (each milestone ends runnable)

1. **Skeleton** — FastAPI + Vite app, design tokens, sidebar shell with the five routes, SQLite migrations, `kometa-studio` CLI. *Done when:* `kometa-studio serve` shows the empty shell.
2. **Settings + runner** — first-run wizard, `--help` probe, KometaRunner, run-now, live log over SSE, cancel, run history. *Done when:* a manual "Collections only" run on Hasan's real install streams logs to the browser and appears in history with the right exit status.
3. **Scheduler** — schedules CRUD, tick loop, coalescing, catch-up, interrupted-run recovery. *Done when:* killing the app across a scheduled time and restarting produces exactly one catch-up run.
4. **Config read** — parse config + referenced files; Overview library cards; read-only views of collections, overlays and defaults with YAML tab.
5. **Config write** — save flow with temp-copy validation, backups, restore, external-change detection. *Done when:* a deliberately broken edit is rejected with Kometa's validation message and the original files are untouched.
6. **Editors** — Defaults toggles/variables, Collection builder, Overlay properties, "Test this collection".
7. **Webhook + polish** — arr webhook with debounce, catch-up banner, connection status, empty/error states, phone-width layout.

Write tests for: command builder, schedule next-occurrence maths (incl. timezone), coalescing, catch-up, log parser fixtures, YAML round-trip (comments preserved), save-flow rollback.

---

## 10. Out of scope for the prototype
Multiple Plex servers · multiple users/roles · editing Kometa's own source or defaults · live item previews from external APIs · rendering real overlay images · Docker image (nice later, not required).

## 11. Open questions for Hasan
1. Where does Studio run first — the seedbox next to Plex, or the home PC? (Affects bind address, service manager and Windows support.)
2. Is Kometa already installed? If yes, send a copy of `config.yml` (tokens removed) and one `meta.log` to use as fixtures.
3. Which libraries should the first schedule cover, and at what local time?
4. Keep the YAML tab read-only for the prototype, or allow raw edits (still validated before save)?
