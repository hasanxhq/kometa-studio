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
- `/api/v1/ping`, open without sign-in, for Docker's health check (which used `/status`, and would have failed once sign-in was required).
- An API key for dashboards and scripts (`X-Api-Key` header or `apikey` parameter), shown in Settings → General with Copy and New key.
- Settings → General sets the timezone new schedules use.
- Studio refuses changes sent by other websites (cross-site requests), whatever the sign-in setting.
- System → Status has health checks: Kometa's install, config.yml, Plex answering with its token, the last run, the last full check, free disk space, sign-in and Kometa updates, each with a link to where it's fixed. A dot on Status in the sidebar shows while something is wrong. `/api/v1/status` includes them for dashboards.
- Full backups (System → Backup): a zip of Kometa's config folder, including the Original Posters Kometa needs to remove its overlays, plus Studio's database and key. Kometa's logs and cache are left out. Weekly on Sundays at 04:30 by default, keeping 4; Back up now, Download and Delete. A backup waits while Kometa runs, checks there's room first, and never leaves a half-written zip. Health warns when the Original Posters aren't in a backup from the last 14 days, or the last backup failed.
- System → Tasks lists Studio's own tasks (full backup, full check), each with its own schedule, last outcome and Run now. A time missed while Studio was off runs once on start, as schedules do.
- Settings → Connect: Radarr and Sonarr. Studio checks their import history every 2 minutes, using the connection in Kometa's config.yml or one entered here (with Test, and a username and password for a seedbox proxy in front of it), and runs Kometa after imports for the libraries you choose per app. Nothing has to reach Studio from outside, and imports made while Studio was off are found when it starts (up to a day back). A burst of imports (a season pack) becomes one run, once they stop for 10 minutes (adjustable) or an hour after the first; the waiting run survives a restart. Health warns when Studio can't read an app's imports.
- Maintainerr (Settings → Connect, with Test, and a username and password for a seedbox proxy in front of it): Kometa leaves its collections alone. Libraries mark them "By Maintainerr". Studio refuses a save that would let Kometa delete them (`delete_collections` not limited to `managed: true`), change their mode (`mass_collection_mode`) or take one over (a Kometa collection with the same name), holds a run that would, and lists any such setting already in your config on System → Status.
- "Leave Maintainerr overlays alone" (on by default): Maintainerr's overlays take precedence over Kometa's. Before a Kometa run that can change posters, Maintainerr's overlays are paused (so its own schedule can't draw one mid-run) and it puts back the posters under them; afterwards they're switched back on and drawn again, on top of Kometa's. Switching back on is retried until it works, even after a restart. A revert that takes minutes (Maintainerr goes through every show, season and episode) is waited for, and a redraw asked for while Maintainerr is busy is asked again once it's done. Kometa never sees a countdown, so it can't keep one as an item's original poster. If Maintainerr doesn't answer, those runs wait.
- A jobs drawer, after Bazarr's Jobs Manager: a button in the header spins while something runs and counts what's running and waiting. It opens Running, Waiting, Failed and Finished jobs (the last ten): Kometa runs with a progress ring and their latest log line (Stop or Cancel), the full backup and full check (including what a backup is waiting for), imports waiting to become a run, and Maintainerr overlays waiting to be switched back on. Finished jobs can be cleared from the drawer.
- System → Logs: Kometa's meta.log and its library and collection logs, filtered by level (lines that continue an entry keep its level) and searchable, with Download. Big logs show their end.
- Settings → Kometa shows where Kometa is, the run time limits and the flags the installed Kometa has (all set by the environment). Settings → UI has the Show Advanced switch. Every page in the menu is now built.
- Phone-width pass: every page checked at 375 px with no sideways scrolling. Logs show the time and message, without Kometa's fixed-width columns, and wrap. Sign out sits in the menu on phones.
- System → Updates: the installed Kometa and whether a newer one is out, with its release notes, from the check Kometa makes at the start of each run.
- Settings → Notifications: set up Notifiarr, Gotify, ntfy and Apprise for Kometa's notifications, each with Test. Save stays off until Test passes for what you entered, and Studio tests again before it saves. Gotify and ntfy get one message titled "Kometa Studio test notification"; Notifiarr's API key is checked the way Kometa checks it; an Apprise configuration must list at least one service. Saved keys and tokens are never shown, only their last four characters; leave a field empty to keep the saved one. Remove takes a service out of config.yml. A grid of Kometa's webhook events (error, version, run start and end, changes, delete) against your services and webhook URLs sets where each event goes; Studio's own entries are shown locked and are never changed. Every save is checked by Kometa and backs up config.yml first, as any edit does.
- Settings → Notifications shows each provider you've set up as its own card, followed by an **Add notification provider** card. You pick one of the rest, fill it in, and save once its test passes. It then gets its own card, and the Add card moves after it with what's left; the Add card is gone once all four are set up. A removed provider goes back onto the Add card.
- Libraries: **Add to Kometa** on a Plex library that isn't in config.yml (on its card and its page) adds it under `libraries`, empty, checked by Kometa like any save. Until it has a collection file, an overlay file or an operation, the library's page says Kometa has nothing to do for it.
- The collection and overlay forms can start a new file. **+ New collection in a new file** (and **+ New overlay in a new file**) on a library's page opens the form with a file picker: one of the library's own files, or **A new file…** with a suggested name. Saving creates the file with that collection and adds it to the library's `collection_files` (or `overlay_files`) in config.yml, in one save Kometa checks. A library still on the old `metadata_path` or `overlay_path` is refused, since adding the new list would hide the old one.
- Libraries: every collection in a library's poster grid opens to its titles: the collection's poster, summary, owner (Kometa, Maintainerr or unmanaged), whether it's smart, and where your files define it; then each movie or show with its poster, year, rating, episode count and links to TMDb, IMDb and TheTVDB (the IDs Kometa's builders match on). Titles load 100 at a time (Show more), and can be searched and sorted by title or year.
- Settings → General → Address: a **URL base** for serving Studio under a path behind a reverse proxy (such as `/kometa`). Studio answers with and without it, so the proxy may pass the path on or strip it, and Kometa's webhooks keep working; opening a page without the base redirects to it. **Trusted proxies**: for requests from these addresses only, Studio takes the visitor's address from X-Forwarded-For (the right-most entry that isn't a trusted proxy, so a visitor can't claim another address), so local visitors through the proxy count as local for sign-in and failed sign-ins are counted per visitor. The card says how Studio sees your browser. The README has an nginx example.
- Libraries → a library → **Defaults**, the Defaults gallery: Kometa's own collection and overlay defaults from the installed Kometa (titles and wiki links from the files), filtered to those that suit the library (movie or show), grouped (Charts, Awards, Movies and shows, Movies, Shows, Overlays) and searchable, each added with one click. Defaults in use show their template variables, which are edited as fields built from Kometa's own schema for that default (with descriptions, choices and Yes/No), plus per-collection variables such as `use_<key>` by name; **Turn off** takes one out. The library's own template variables (such as `sep_style`) have their own form. Every change is one save of config.yml that Kometa checks; unchanged variables keep their YAML as written.
- **Overview**, the new first page: what's running, the last run (outcome, items added and removed, errors), the next scheduled run and health at a glance; Run now; what was saved in Studio since the last successful run started, which the next run applies (with a note when that run covered only part of Kometa); the last run's changed collections; each library's size in Plex, its collections and what config.yml does with it; and Kometa's latest full check. The catch-up notice shows here too. The Plex libraries API now reports how many movies or shows each library holds.
- The header names nested pages for what they show, in Plex's words: a library's page is **Library**, a collection's page **Collection** (with a Libraries › library breadcrumb), and a run's page **Run**. They all said "Libraries" or "Queue" before.
- Settings → Connect → **Tautulli**: Kometa's `tautulli:` connection (URL and API key), for `tautulli_popular` and `tautulli_watched` collections. Tested the way Kometa does when it starts (`get_tautulli_info`, showing Tautulli's version), and saved only after a passing test; the key stays masked, and leaving it empty keeps the saved one. A library's own `tautulli:` override in config.yml is left as written.
- Settings → Kometa → **Kometa's settings**: config.yml's `settings:` block as a form. Every setting Kometa knows is grouped (Collections, Assets, Overlays, Playlists, Reports and log detail, How Kometa runs, Other), with a control chosen from Kometa's schema, its description and the installed Kometa's default. The defaults are read from Kometa's own source, not run. Empty means the setting is left out, so Kometa's default applies. Kometa checks every save, unchanged settings keep their YAML as written, and a save made after config.yml's settings changed elsewhere is refused.
- **Run again** on a finished run's page queues the same run (same mode, libraries, collections, files and options) and opens it. It's the main button when the run failed. The Overview's last-run card has it too when that run didn't succeed.
- **Filter chips** in the collection form. A collection's `filters:` show as chips in words, such as “Year ≥ 2008” or “Genre isn't: Documentary”, each with × to remove it. Year from or up to, critic, audience or your rating at least, and genre is any of or none of are added from a short form. Ratings are checked to be 0 to 10, and genres join a list that's already there. Other filters already in the YAML show as chips too. Several filter sets (a list) stay under Show Advanced.
- **Playlists** (Libraries → Playlists): config.yml's `playlist_files`, each file's playlists and their libraries, **Add a playlist**, and **Run playlists**. A playlist opens in the item form with fields for libraries, summary, sharing (`sync_to_users`, `exclude_users`), sync mode and schedule, plus its source and filter chips. A new playlist can start a new file, which saving adds to `playlist_files`, all in one save that Kometa checks. Kometa's own default playlists are listed but not editable.

### Changed

- An **Everything** run means everything configured, not every step Kometa has. With “Leave Maintainerr overlays alone” on, Maintainerr's overlays are put back before a run and redrawn after it only in libraries where that run changes posters: overlay files (or `remove_overlays`), poster operations (`mass_poster_update`, `assets_for_all`), or metadata and image files. Before, any Everything run did it in every library where Maintainerr had overlays, even with no Kometa overlays at all. The Run form says what Everything covers.

- Settings → General: the timezone list is labelled `UTC +05:30 (Asia/Kolkata)` (offset then IANA name). Schedules and Studio's built-in tasks always use this setting; their forms no longer have a timezone picker. Changing it updates every schedule and task.
- A library's Collections tab says when Plex can't be reached, instead of saying Plex has no library by that name.

- When Studio edits config.yml itself (Plex connection, webhook entries), it keeps the file's own formatting instead of restyling it.

- Settings → General: once sign-in is set up, the card shows the username instead of the username and password fields. A "Change username or password" link opens them, with Cancel to close them again. The current password is asked for only when you change something.
- Settings → Plex is one "Your servers" card. Opening it tests only the server saved in config.yml and shows whether it answers. Studio fetches and tests every server on your Plex account only when you press Test again, or when the saved server doesn't answer. "Use a custom address" opens the form for typing a URL and token. It saves only after a test passes, replaces the server chosen from the list, and is then marked "Custom address".
- Settings → Connect: Radarr, Sonarr and Maintainerr share one card, and TMDb and MDBList have their own.
  - Radarr and Sonarr have plain URL and API key boxes, filled in from Kometa's config.yml, instead of choosing between config.yml, "enter it here" and off. After a passing test you pick the root folder and quality profile Kometa uses for adding items, from the app's own lists. Saving writes all four to config.yml, so Kometa uses the same connection. A connection entered only in Studio before this is no longer used; enter it again.
  - A seedbox proxy login is behind a checkbox, for Radarr, Sonarr and Maintainerr alike.
  - Every connection is saved only after a passing test, and Studio tests it again when saving. Changing only Maintainerr's overlay choice needs no test.
  - Radarr and Sonarr each have their own "run Kometa when it imports" settings: on or off, what to run, how long to wait and which libraries. Settings from before carry over to both.
  - TMDb and MDBList keys are tested with the same call Kometa makes, and saved to config.yml only after the test passes. MDBList's test shows how much of today's allowance is used. Trakt and the other trackers aren't offered: Kometa 2.5.3 removed Trakt.
- Runs after imports can be limited to imports that matter to Kometa (per app, "Only imports that matter to Kometa").
  - An import counts when one of these holds:
    - a collection wants it;
    - a collection that searches Plex could take it;
    - the run draws overlays, runs operations or applies metadata files in that library;
    - Studio can't tell.
  - When only collections want it, just those collections run. Other imports are skipped and listed.
  - What collections want comes from the collection files (IDs written in them) and from Kometa's missing report (`save_report`), which Studio keeps its own copy of after each completed run. Settings → Connect can turn the report on.
  - Per library, the page says what Studio can tell and why every import still counts where it does.
- "Leave Maintainerr overlays alone" now puts Maintainerr's overlay on last, over Kometa's.
  - Studio decides when Maintainerr draws:
    - after every Kometa run that changes posters (Maintainerr still puts its posters back first);
    - once a day, for its countdowns.
  - Kometa's overlays go on first when something is new since Kometa last drew overlays, so a new item never gets Maintainerr's overlay before Kometa's. Putting Maintainerr's overlays back then gives Kometa's poster, not the bare one.
  - Maintainerr's own overlay schedule is kept off while this is on, and given back when it's turned off or Maintainerr is disconnected. Settings → Connect shows the schedule Studio holds and the next daily redraw.
  - Maintainerr's overlays are no longer switched off around runs.
- Every run now records how many calls Kometa made to each service (TMDb, MDBList, IMDb, …), using Kometa's `--timings`. System → Status shows today's totals and how much of MDBList's daily allowance is used.
- Runs after imports wait once MDBList reaches 80% of its daily allowance, until it resets at midnight UTC. Scheduled and manual runs always go. The jobs drawer and Health say when a run is waiting for this.
- Overlays page, next to Libraries. For each library it shows:
  - the overlay files it uses;
  - when overlays are drawn: schedules, and imports from Radarr or Sonarr;
  - the last overlay pass;
  - Kometa's Original Posters backup (how many posters, how big);
  - whether Maintainerr's overlays go on top.

  Actions:
  - **Apply now** runs overlays for that library.
  - **Add** sets up a daily overlay pass.
  - **Turn overlays off** has Kometa put the original posters back (with "Leave Maintainerr overlays alone" on, Maintainerr puts its posters back first and draws again over the originals), and Kometa draws none until they're turned on again. It's refused without an Original Posters backup.
- Settings → Network, for Studio's calls and Kometa's alike:
  - **Proxy:** HTTP, HTTPS or SOCKS5, with an optional login and a list of what to reach directly (local addresses always are), one per line or separated by commas. It's saved only after a test shows it works and which address the internet sees. Kometa needs nothing installed for SOCKS5.
  - **DNS over HTTPS** (Cloudflare or Google) for ticked services: TMDb, MDBList, IMDb, TheTVDB, plex.tv, Letterboxd, GitHub. It's saved only after each one resolves.
  - **IPv4 first**, for networks with broken IPv6.
  - **Connection check:** for each service Studio and Kometa use, what this network's DNS says and what DNS over HTTPS says, whether it connects and how fast, and a verdict, such as "Blocked by this network's DNS".
