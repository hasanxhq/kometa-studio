# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository setup: MIT license, CI, branch workflow rules in AGENTS.md, and a single `VERSION` file.
- App skeleton: `kometa-studio serve`, `/api/v1/status`, SQLite with numbered migrations, and the arr-style navigation shell with a Show Advanced toggle.
- Docker image built on the official Kometa image, plus `compose.yaml`.
- Settings → Plex: sign in with Plex to find your servers. Studio tests every address and preselects the best one (relays last, with a warning). You can also enter a URL and token by hand. Saving writes `plex.url` and `plex.token` into Kometa's `config.yml`, keeping its comments, and backs up the old file to `.studio/backups/`.
- Activity → Queue: run Kometa (everything, or only collections, overlays, operations, metadata or playlists, for chosen libraries; more options under Show Advanced). Runs wait in a queue and go one at a time. You can watch the log live and cancel. Recent runs show their outcome, items added and removed, and errors.
- Each run has its own page with Kometa's numbers (collections created, modified and deleted; items added and removed), the errors and changed collections Kometa reported, and the full log.
- Studio adds its own webhook to every Kometa webhook event in `config.yml` (next to your existing targets, marked "managed by Kometa Studio"), so it learns what each run did.
- A run that hits a critical error, such as a config error, counts as failed even though Kometa exits normally.
- System → Tasks: schedule Kometa runs on chosen days at a set time, in your timezone (daylight saving handled). Each schedule shows its next and last run and has Run now, Edit, Pause and Delete.
- Runs missed while Studio was off are made up once when it starts again (within 24 hours), or skipped if you choose. Tasks shows a notice when this happens, and the run is marked "Catch-up".
- Schedules due at the same moment run in Kometa's order (operations, metadata, collections, overlays, playlists), and an "everything" run replaces the narrower runs it covers.
- `STUDIO_TIMEZONE` sets the timezone for new schedules (default: the container's `TZ`).
- Libraries: a card per Plex library, with its collections split into those Kometa manages (they carry Plex's `Kometa` label, Kometa's own test) and unmanaged ones, and what Kometa's config.yml does with the library. Libraries not in config.yml show too, so this works before any setup.
- Each library has Collections (a poster grid from Plex, filterable by managed and unmanaged, plus collections your config defines that aren't in Plex yet), Overlays, Defaults and Operations tabs, with read-only YAML views. Tokens and API keys are masked.
- Activity → History: what each run changed, collection by collection (items added and removed, new and deleted collections, Radarr/Sonarr adds), filterable by library and name.
- Edit Kometa's YAML files in Studio. Kometa checks every save first, and nothing is written if the change adds a problem. Problems already in your files are shown but don't block saving, so an incomplete config can be built up a step at a time. Secrets show as ••••(n) and are kept when you save.
- Studio never writes a file you didn't edit, refuses to overwrite a file that changed on disk since you opened it, and backs up every file before writing it (System → Backup, the newest 30, with a comparison to today's file and Restore).
- Add files: upload collection, overlay, metadata or playlist files into the config folder, checked by Kometa first.
- System → Status: Full check, where Kometa connects to Plex and every service in your config and changes nothing.
- Checks never send notifications: Kometa validates a sandboxed copy with the webhooks removed. The Docker image now includes Kometa's JSON schemas (left out of Kometa's own image), so Kometa's schema check runs too.

- The YAML editor checks Kometa's schema as you type (the schema of the Kometa version installed), marking each problem where it is, and completes keys with their descriptions.
- Forms for collections and overlays: sources, common settings (summary, sort title, sync mode, order, visibility, schedule) and, for overlays, position and colours with a poster preview. Show Advanced has every other setting Kometa knows, and settings it doesn't know (usually template variables) are kept as written. Saving a form changes only that collection or overlay, and Kometa checks it like any save.
- Run just one collection from its form, in its library, without changing any files.
- Sign-in, arr-style (Settings → General): a username and password, required for everyone or "disabled for local addresses". Until it's set up, Studio only answers this computer and your local network, and says so on every page. Requests through a reverse proxy never count as local. Repeated wrong passwords have to wait.
- An API key for dashboards and scripts (`X-Api-Key` header or `apikey` parameter), shown in Settings → General with Copy and New key.
- Settings → General sets the timezone new schedules use.
- Studio refuses changes sent by other websites (cross-site requests), whatever the sign-in setting.
- System → Status has health checks: Kometa's install, config.yml, Plex answering with its token, the last run, the last full check, free disk space, sign-in and Kometa updates, each with a link to where it's fixed. A dot on Status in the sidebar shows while something is wrong. `/api/v1/status` includes them for dashboards.
- System → Updates: the installed Kometa and whether a newer one is out, with its release notes, from the check Kometa makes at the start of each run.

### Changed

- When Studio edits config.yml itself (Plex connection, webhook entries), it keeps the file's own formatting instead of restyling it.
