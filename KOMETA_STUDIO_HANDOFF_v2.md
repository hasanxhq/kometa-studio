# Kometa Studio — handoff v2

A web app that gives Kometa a GUI, modelled on the *arr apps (Sonarr, Radarr, Prowlarr, Tautulli, Overseerr). **Kometa stays exactly as it is.** Studio treats Kometa as a script: it edits Kometa's YAML files, decides when a run is due, launches Kometa as a one-shot process, and records what happened.

v1 (`KOMETA_STUDIO_HANDOFF.md`) was the starting suggestion. v2 reflects decisions made on 2026-10-30 and what the Kometa 2.5.3 source shows (reference clone in `kometa/`). Section 12 lists what changed from v1.

Visual direction is unchanged: dark UI, amber accent `#F2B544`, Space Grotesk headings, Inter body, JetBrains Mono for YAML and logs. Design tokens are in §11.

---

## 1. Decisions so far

| Topic | Decision |
|---|---|
| Where Studio runs first | Hasan's home Windows PC, in Docker under WSL2 |
| Where Plex runs | Remote seedbox. Studio and Kometa reach it over the internet or VPN |
| Flexibility goal | Setup must work for Plex on the same host, on the LAN, or remote, without the user knowing URLs or tokens |
| Forms | Hand-designed forms for common options, plus an arr-style **Show Advanced** toggle that exposes every option |
| Raw YAML | Editable, validated before save |
| Kometa code | Never modified. Studio is its own repo; Kometa is a versioned dependency (§10) |

---

## 2. Hard constraints

1. **Never modify Kometa's code.** No patches and no imports of Kometa internals. Studio writes only the user's own config and YAML files that Kometa reads.
2. **Kometa never runs its own scheduler.** Every run includes `--run`, so Kometa does one pass and exits. Never set `--times` or `KOMETA_TIMES`.
3. **One Kometa process at a time.** Runs are queued. This also makes webhook correlation trivial (§5.2).
4. **Studio owns the config files.** Always pass `--read-only-config`.
5. **Survive restarts and power cuts.** Schedules, history and the queue live in SQLite. Missed runs are handled on start-up (§6.3).
6. **Docker is the primary install.** A plain `pip install` path should keep working for a seedbox later, so nothing may depend on Docker-only features (no Docker socket).

---

## 3. Deployment

### 3.1 Image

Build Studio on top of Kometa's official image, the same way Kometa's own `Dockerfile` builds on `kometateam/kometa:${BASE_TAG}`.

- The Kometa image has its source at `/`, its venv at `/.venv`, `/tini` as init, `VOLUME /config` and `KOMETA_DOCKER=True`. Studio overrides the entrypoint.
- Studio gets **its own venv** (e.g. `/studio/.venv`) so its dependencies never conflict with Kometa's.
- Multi-stage build: a Node stage builds the React app; the final stage copies the static files and serves them from FastAPI.
- `ARG KOMETA_TAG` picks the Kometa version. Upgrading Kometa means bumping the tag (§8, System → Updates). Check Docker Hub for the exact tag naming before pinning.
- Studio launches Kometa as `/.venv/bin/python3 /kometa.py --config /config/config.yml --run …`. Inside a Linux container, cancelling is a normal SIGTERM, then SIGKILL after 30 s. The v1 Windows `CTRL_BREAK` question goes away.

### 3.2 Volumes and environment (arr conventions)

```
/config/                     Kometa's config folder (config.yml, collection/overlay files, logs/, overlays/, cache)
/config/.studio/             Studio's own data: studio.db, runs/<id>.log, backups/
/assets/ (optional)          Asset folders, if the user keeps custom posters on disk
PUID, PGID, TZ=Asia/Kolkata, STUDIO_PORT (default 8484, check it doesn't clash with common arr ports)
```

- On Windows, keep `/config` on WSL's ext4 disk or a named volume, **not under `/mnt/c`**. Windows mounts are slow and report mtimes unreliably, and §7.4 relies on mtimes.
- `config/overlays/<library> Original Posters/` is Kometa's backup of un-overlaid posters. Losing it means Kometa can't cleanly remove its overlays. Backups must cover it (§8).

### 3.3 Plex on a remote seedbox

- Overlay runs download and re-upload every poster, so they'll be slower over the internet than on the seedbox. Show run durations so this is visible, and offer `--low-priority`.
- Asset folders must be on the machine running Kometa. If assets live on the seedbox, they need syncing or mounting (out of scope for the prototype; note it in the UI).
- A later seedbox install (pip path) should need no code changes, only different paths.

---

## 4. Connecting to Plex (setup wizard)

Modelled on Overseerr, confirmed in its source (`server/api/plextv.ts`, `server/routes/settings/index.ts`, `src/utils/plex.ts`). Sonarr's Connect → Plex, Tautulli and Bazarr use the same plex.tv PIN sign-in.

### 4.1 Sign in with Plex (PIN flow)

1. Studio's backend calls `POST https://plex.tv/api/v2/pins?strong=true` with `X-Plex-Product: Kometa Studio`, a stable `X-Plex-Client-Identifier` (generated once, stored in SQLite) and the other `X-Plex-*` headers.
2. The browser opens a popup at `https://app.plex.tv/auth/#!?clientID=…&code=<pin code>&context[device][product]=Kometa Studio…`.
3. Studio polls `GET https://plex.tv/api/v2/pins/{id}` every second until `authToken` is set or the PIN expires.
4. Studio stores the account token encrypted in SQLite. It is never sent back to the browser.

### 4.2 Find servers

1. `GET https://plex.tv/api/resources?includeHttps=1` with the account token returns XML `Device` elements. Keep those where `provides` includes `server` and `owned == 1`.
2. Each device lists `Connection` entries with `protocol`, `address`, `port`, `uri` and `local`, plus a per-server `accessToken`.
3. Like Overseerr, expand each connection into two candidates: the `plex.direct` HTTPS URI (valid TLS), and the raw IP address over HTTP.
4. Probe every candidate in parallel with a 5 s timeout (`GET /identity` with the server token). Show each as OK or failed with the error.
5. Rank the working ones: local before remote, HTTPS `plex.direct` before plain HTTP, and **relay last, with a warning** (relay is bandwidth-limited and unsuitable for overlay runs). The user picks one; the best is preselected.

### 4.3 Manual entry (always available)

A URL and token form with a **Test** button, like Tautulli's "Plex IP or hostname / port / SSL / Verify". Needed for seedboxes behind a reverse proxy, whose public URL plex.tv may not list unless it's set in Plex's "Custom server access URLs".

### 4.4 Writing it to Kometa

Studio writes `plex.url` and `plex.token` (the server's `accessToken`) into `config.yml` through the normal save flow (§7). The UI shows the token masked. Re-running the wizard later replaces both.

### 4.5 Other services (arr "Connect" pattern)

Each service in Settings → Connect (TMDb, Trakt, MDBList, Radarr, Sonarr, Tautulli, notifications) gets its own form with a **Test** button. Tests are small, read-only calls Studio makes itself (e.g. Radarr/Sonarr `GET /api/v3/system/status` with `X-Api-Key`), for fast feedback. Kometa's `--validate-level full` stays the authoritative check (§7.3).

---

## 5. Kometa integration

### 5.1 Command builder

Unchanged from v1 §3.2, verified against `kometa.py` in 2.5.3:

- Always: `--config <path> --run --no-countdown --read-only-config --ignore-ghost`.
- Modes: `--collections-only`, `--overlays-only`, `--operations-only`, `--metadata-only`, `--playlists-only`, or none for `all`.
- Filters: `--run-libraries "A|B"`, `--run-collections "A|B"`, `--run-files "A|B"`, `--ignore-schedules`, `--no-missing`, `--tests`.
- New options: `--low-priority` (setting, default on), `--timings` (per run, writes a JSON/CSV breakdown to the logs folder).
- Never from the UI: `--delete-collections`, `--delete-labels`, `--delete-collections-labels`, `--log-requests`.
- On start-up, run `--help` and store it. Disable any control whose flag the installed Kometa lacks.

### 5.2 Structured results through Kometa's own webhooks

Kometa sends JSON webhooks (`kometa/docs/config/webhooks.md`), and each event accepts **a list of targets**. Studio adds its own endpoint to every event, keeping whatever the user already has (Notifiarr, ntfy, etc.):

```yaml
webhooks:
  run_start: [http://127.0.0.1:8484/api/v1/kometa/events?token=…]      # managed by Kometa Studio
  run_end:   [notifiarr, http://127.0.0.1:8484/api/v1/kometa/events?token=…]
  changes:   [http://127.0.0.1:8484/api/v1/kometa/events?token=…]
  error:     [http://127.0.0.1:8484/api/v1/kometa/events?token=…]
  delete:    [http://127.0.0.1:8484/api/v1/kometa/events?token=…]
  version:   [http://127.0.0.1:8484/api/v1/kometa/events?token=…]
```

| Event | Studio uses it for |
|---|---|
| `run_end` | Run summary: collections created/modified/deleted, items added/removed, Radarr/Sonarr adds |
| `changes` | **History**: per collection, items added and removed (TMDb/TVDb IDs), poster URL |
| `error` | Errors at global, library, collection or playlist level, linked to the run |
| `delete` | History entry for deleted collections |
| `version` | Health notice "Kometa update available" |

- **Correlation:** webhooks carry no run ID, but only one run executes at a time, so every event arriving while run *N* is running belongs to run *N*. Events with no running run are logged as orphans.
- The endpoint must accept large bodies: `changes` includes a base64 poster when no poster URL exists. Store the URL, drop base64.
- Studio's entries are marked in the YAML with a comment and shown as locked chips in the UI. The user's own targets stay editable.
- **Log parsing becomes a fallback**, for warnings and for lines that explain a failure. Keep the parsers in one module with fixture logs, as v1 §3.4 said.

### 5.3 Runner

As v1 §3.3: no shell, stream stdout/stderr to `runs/<id>.log` and SSE, store status, exit code, duration and masked command, 3 h default timeout, and runs still `running` at start-up become `interrupted`.

---

## 6. Scheduler

Unchanged from v1 §4: schedules in SQLite, a 30 s asyncio loop, `zoneinfo` for DST, coalescing order `operations → metadata → collections → overlays → playlists` (`all` replaces the rest), no duplicate queued requests, `catch_up` of `run_once` (default) or `skip` within 24 h, and a banner after a catch-up.

In the UI, schedules appear as rows in **System → Tasks** (§8), arr-style: name, interval, last run, next run, a Run Now button.

The incoming Radarr/Sonarr "On Import" webhook (v1 §4.4) stays: map arr instance → library, 10 min debounce, enqueue one run for that library.

---

## 7. Config editing

### 7.1 One document, three views

Every file is held as a `ruamel.yaml` round-trip document (comments, order and anchors survive). Three views edit the same document, so switching never loses anything:

1. **Designed form:** hand-built fields for the common keys (builders, filters, `sync_mode`, `collection_order`, visibility, overlay position and colours, defaults' common template variables).
2. **Show Advanced:** every remaining option from Kometa's JSON schema for that file type.
   - Simple shapes get generated controls: boolean, enum, number, string, list of strings.
   - The schemas use `oneOf` heavily (220 times in the collection schema, 365 in the config schema). Generic form generators handle this poorly, so any `oneOf` or `anyOf` node gets a small inline YAML editor for that key, validated against its sub-schema.
   - **Other keys:** anything the schema doesn't know (notably template variables, which the schema README says it can't validate) is listed untouched as raw key/value pairs.
3. **YAML tab:** the whole file, editable.

### 7.2 Version-matched schemas

Studio serves the JSON schemas from the installed Kometa (`/json-schema/*.json` in the image), so the editor never suggests keys the running version doesn't support.

### 7.3 Validation, three tiers

| Tier | When | How | Network |
|---|---|---|---|
| 1. As you type | In the browser | YAML editor with JSON-schema support (CodeMirror 6 + a schema plugin, or monaco-yaml): autocomplete and inline errors | None |
| 2. On save | Server, before writing | `--validate --validate-level structure --validate-schema` on a temp copy | None |
| 3. Full check | "Full check" button, and nightly | `--validate --validate-level full`: connects to Plex and every configured service, changes nothing | Yes |

- Tier 2's temp copy must keep the same relative folder layout, because `structure` checks that local `file:` paths exist.
- Kometa runs a source-integrity check at start-up for up to 30 s, including validation runs. Pass `--no-source-integrity` for tier 2 only, so saves stay fast. Real runs keep it on.
- Tier 3 replaces both "Dry run" and "Test connections" from the design concept.
- Kometa's validation, not the browser, decides whether a save goes through.

### 7.4 Save flow

As v1 §5: write a temp copy → tier 2 validation → on pass, back up the current files to `.studio/backups/<timestamp>/` and replace atomically → on fail, show Kometa's messages and keep the old files. If a file changed on disk since Studio read it (mtime plus hash), refuse and offer a reload. Keep the last 30 YAML backups.

---

## 8. Information architecture (arr-style)

```
Libraries                 one card per library (like Series/Movies)
  └ <Library>             tabs: Collections · Overlays · Defaults · Operations
Activity
  ├ Queue                 running + queued runs, live log, cancel
  └ History               per-collection changes from webhooks (+12 / −3 in "Trending Movies"), filterable
System
  ├ Status / Health       health banner: last tier-3 result, failed connections, Kometa update available
  ├ Tasks                 schedules + built-ins (Full check, Backup) with last/next run and Run Now
  ├ Backup                YAML backups on every save; scheduled full backups incl. Original Posters; restore with diff
  ├ Logs                  meta.log and per-run logs, level filter
  └ Updates               installed Kometa version, latest from the `version` webhook
Settings
  ├ General               port, auth, API key, timezone
  ├ Plex                  wizard (§4)
  ├ Connect               services (§4.5), incoming arr webhooks, Kometa notification targets
  ├ Kometa                paths, default flags (--low-priority, timeout)
  └ UI                    "Show Advanced" default, theme
```

- **Show Advanced** is a global toggle in the page header, as in the arr apps, and also applies per form.
- **Auth**, arr-style: forms login, with an option "Disabled for local addresses". Bind `0.0.0.0` inside the container; the user controls exposure with the port mapping.
- **API key** in Settings → General. All endpoints accept `X-Api-Key`, so dashboards like Homepage can read `/api/v1/status`.

---

## 9. API (sketch)

Versioned under `/api/v1`, `X-Api-Key` or session cookie.

```
GET  /status                             health, last/next run, queue, Kometa version
POST /runs                               RunRequest → run_id
GET  /runs · /runs/{id} · /runs/{id}/stream (SSE) · POST /runs/{id}/cancel
GET  /history?library=&collection=       from webhook events
POST /kometa/events?token=               Kometa webhook receiver (§5.2)
POST /validate {level}                   tier 2 or 3

GET  /plex/pin · GET /plex/pin/{id}      PIN flow (§4.1)
GET  /plex/servers                       discovered servers + probed connections (§4.2)
POST /plex/test {url, token}             manual test (§4.3)

GET  /config/libraries
GET  /config/files/{id}                  document + raw YAML (secrets masked)
PUT  /config/files/{id}                  save flow (§7.4)
GET  /config/schemas/{type}              version-matched JSON schema
GET  /backups · POST /backups/{id}/restore

GET/POST/PUT/DELETE /schedules
POST /hooks/arr?token=                   Radarr/Sonarr On Import
GET/PUT /settings
```

---

## 10. Repositories

- **Studio** is its own public repository, [hasanxhq/kometa-studio](https://github.com/hasanxhq/kometa-studio) (MIT). Its git workflow is in `AGENTS.md`: `dev` as default branch, topic branches, CI, releases to `main`.
- **`kometa/`** is a read-only reference clone, listed in Studio's `.gitignore`. The version Studio actually runs comes from the Docker base image tag, not this clone.
- **Do not fork Kometa to build Studio.** Fork only to contribute upstream. Kometa's own workflow applies there: branch from `nightly`, PR into `nightly` (`kometa/.github/CONTRIBUTING.md`). Possible contributions that would help Studio: a run ID in webhook payloads, a JSON run report.

---

## 11. Design tokens

```
--bg #0F1114   --surface #16191D   --surface-2 #1A1D21   --sidebar #14171B
--border #23272D   --border-strong #2C3138
--text #ECEDEE   --muted #9AA1A9   --accent #F2B544   --on-accent #1A1406
--ok #8FD6A0   --warn #F2C77A   --err #F29B8A   --info #9DC2F7
radius: 8px controls, 12px cards; touch targets ≥ 44px
```

Stack: Python 3.12+ (FastAPI, Uvicorn, `ruamel.yaml`, SQLite), React + Vite + TypeScript, Tailwind, React Router, TanStack Query, CodeMirror 6.

---

## 12. Build order (each milestone ends runnable)

1. **Skeleton.** (Repo and workflow setup are done.) Dockerfile on the Kometa base image, compose file, FastAPI + Vite shell with the §8 navigation, SQLite migrations. *Done when:* `docker compose up` in WSL shows the empty shell.
2. **Plex wizard.** PIN sign-in, server discovery with probing, manual entry, write `plex.url`/`token` through a minimal save. *Done when:* the seedbox Plex is found and selected without typing a URL.
3. **Runner and events.** Command builder, `--help` probe, queue, live log, cancel, webhook receiver with run correlation, run summary from `run_end`. *Done when:* a "Collections only" run against the seedbox streams logs and shows its `run_end` numbers.
4. **Scheduler.** Tasks screen, tick loop, coalescing, catch-up, interrupted-run recovery. *Done when:* stopping the container across a scheduled time and starting it again gives exactly one catch-up run.
5. **Config read and History.** Parse config and referenced files, library cards, read-only views, History from `changes` events.
6. **Config write.** Three-tier validation, save flow, backups, restore, outside-change detection. *Done when:* a broken edit is rejected with Kometa's message and the files are untouched.
7. **Editors.** Designed forms, Show Advanced, YAML tab with in-browser validation, "Test this collection".
8. **Polish.** Health checks, Updates, scheduled full backups, arr webhook with debounce, auth and API key, phone-width layout.

Tests: command builder, schedule maths incl. timezone, coalescing, catch-up, webhook correlation, plex.tv resource parsing and connection ranking (fixture XML), YAML round-trip, save-flow rollback, log-parser fixtures.

---

## 13. Changes from v1

- Docker under WSL2 is now the primary install (was: plain Python, no Docker).
- Plex discovery via plex.tv sign-in and server probing (v1 assumed a typed URL and token).
- Structured results from Kometa's webhooks; log parsing demoted to fallback (v1 said Kometa had no machine-readable output).
- Forms: designed fields + Show Advanced driven by Kometa's JSON schemas (v1: six hand-coded builders).
- YAML tab editable with three-tier validation (v1: read-only).
- arr-style navigation (v1: five screens from the design concept).
- New flags: `--low-priority`, `--timings`, `--no-source-integrity` for save validation.
- Backups cover the Original Posters folder.

## 14. Open questions

1. How does the PC reach the seedbox's Plex: public `plex.direct`, a reverse-proxy URL, or a VPN? (Decides what the wizard will find.)
2. Is Kometa already set up somewhere? A `config.yml` with tokens removed and one `meta.log` would give fixtures from day one.
3. Do you have asset folders (custom posters on disk), and where?
