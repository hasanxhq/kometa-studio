# UI rework plan: a library-first Studio

A plan for agents (Claude Code or others) to carry out the UI rework drawn on the design canvas. Read this whole file before starting a phase, then the phase's boards, then the code it names.

- **Design canvas:** https://claude.ai/artifact/CpsJsiczKSkj2ZceqTuhHM. Read it with the Artifact tool (`action: "read"`, `path: "project/<board>.dc.html"`). The `Built-*` boards are the app as it was on `dev` on 2026-11-06; the `Idea-*` boards are the target. Sticky notes on the canvas list the gaps and each change. The Kometa-era boards at the top are history: ignore them.
- **Where things stand:** `dev` at `a3c50cc` (PR #82). The boards are mockups with sample data. Where a board and this plan disagree, this plan wins. Where this plan and the code disagree about what exists today, the code wins: check it and adjust.

## Working rules for every phase

These add to `AGENTS.md`; they don't replace it.

1. **One phase step = one topic branch and one PR into `dev`**, cut from the latest `dev` in its own worktree (`git worktree add ../starrstudio-<topic> -b <topic> origin/dev`). Open the PR as a draft at the first checkpoint and mark it ready only when the step's acceptance list passes. Branch names are given per step.
2. **Decide, don't ask.** Where the plan leaves a choice open, take the sensible default and list each choice under "Choices made" in the PR description. Ask the maintainer only before anything that changes what Plex, Radarr, Sonarr or Seerr receive, or that deletes data.
3. **Keep every URL working.** Old paths redirect to their new home (`<Navigate replace>`). Bookmarks and links in run logs must not break.
4. **No new YAML in the UI.** Studio owns the config; YAML stays read-only behind a disclosure, as today.
5. **Look and feel:** the tokens in `frontend/src/index.css` (`bg`, `surface`, `surface-2`, `border`, `accent` …), Space Grotesk headings, Inter body (always through the `--font-*` variables, so F1's switch reaches them), `rounded-card` / `rounded-control`. Touch targets at least 44 px (`min-h-11`). Real `<button>`, `<a>` and `<label>` elements; `aria-label` on icon-only buttons. Icons are inline stroke SVGs in one new file, `frontend/src/components/icons.tsx`; no icon library, no emoji.
6. **Copy:** plain words, sentence case, no jargon a Plex user wouldn't know. Say what happens ("Kometa redraws about 1,100 posters"), not what the code does. Plain text says "Starr Studio"; only the logo is styled St*arr.
7. **Editors keep their guards:** anything with unsaved state uses `LeaveGuard` / `useLeaveEditor`.
8. **Tests come with the change.** Frontend: Vitest + Testing Library next to the page (`*.test.tsx`). Backend: pytest with `tests/fakeplex.py`; never the network. Run both suites before each commit, exactly as CI does (see `AGENTS.md` → Tests).
9. **`CHANGELOG.md`:** one line per user-facing change under `## [Unreleased]`.
10. **`AGENTS.md` layout table:** update it whenever a file's job changes or a new module, route or migration appears.
11. **Hands off:** never modify Kometa, never touch Maintainerr's collections, and keep its overlays on top (see `maintainerr_guard.py`). Real-Plex manual tests name collections `TEST …` and leave them for the maintainer to delete.

## Order and parallel work

```
P0 foundations ──┬── P1 navigation ── P2 Home
                 ├── P3 Collections (P3a backend first) ── P4 Builder
                 └── P5 Overlay studio
```

- P0 comes first; everything uses it.
- After P0, three tracks can run in parallel worktrees: **P1 → P2**, **P3 → P4**, and **P5**. They touch different pages. The shared files are `nav.ts`, `Layout.tsx` and `api.ts`: keep edits there small and merge `dev` in often.
- Steps inside a phase are separate PRs, in the order given.
- **F1 (font choice)** depends on nothing and nothing depends on it. Do it first, so the maintainer can try system fonts while the rest is built.

---

## F1 · Font choice in Settings → UI (`font-choice`)

The maintainer wants to compare Studio's bundled fonts with the device's own before deciding the default. This step adds the switch only; the default stays as it is.

- **Settings → UI** (`frontend/src/pages/SettingsUI.tsx`) gets a "Text" card under "Forms", with a radio group labelled **Fonts**:
  - **Studio fonts** (the default): Space Grotesk headings, Inter text, JetBrains Mono code, as today.
  - **System text, Studio headings:** the device's font for text and code; headings stay Space Grotesk.
  - **System everywhere:** the device's font for headings, text and code.
  - Help line: "Studio's fonts look the same on every device. System fonts match your computer or phone, and text wraps a little differently on each. Remembered in this browser."
- **Stored in this browser**, like Show Advanced (`advanced.tsx`):
  - a small `fonts.ts` module with `readFonts()` / `applyFonts()`
  - localStorage key `studio.fonts`, holding `studio`, `system-text` or `system`
  - every read and write in `try/catch`; a missing or unknown value reads as `studio`
- **Applied as `data-fonts` on `<html>`.** `index.css` overrides the three variables under `:root[data-fonts="system-text"]` and `:root[data-fonts="system"]`:
  - text: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`
  - code: `ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace`
  - headings (`system` only): the same as text
  - Keep the three Fontsource imports in `main.tsx`. Browsers fetch a font file only when some text uses it, so the system modes download none.
- **No flash on load:** a few lines of inline script in `frontend/index.html`'s `<head>` read `studio.fonts` (in `try/catch`) and set `data-fonts` before the page paints. A change in Settings applies at once, with no reload.
- Every font in the app already goes through `--font-display`, `--font-sans` and `--font-mono` (including the YAML editor). Keep it that way: no font names in classes or components.
- **Tests:** `SettingsUI.test.tsx`: each option sets `document.documentElement.dataset.fonts` and the stored value. `fonts.test.ts`: an unknown stored value, or storage that throws, gives `studio`.
- **Acceptance:**
  - Switching changes every page's text at once, and a reload keeps the choice.
  - In "System everywhere", the browser's network tab shows no `.woff2` requests after a hard reload.
  - Overview, Collections and the overlay designer at 390 px wide, in each mode: nothing overflows and no button label wraps out of its button.
- **Not in this step:** changing the default or removing the bundled fonts. The maintainer decides after trying it, and that's a separate PR.

---

## P0 · Foundations

Shared pieces the later phases build on. No visible redesign yet.

### P0.1 One library choice for the whole app (`library-context`)

Today every library page reads `?library=` itself and falls back to the first library (`ReadyMade.tsx`, `Collections.tsx`, `OverlayDesigner.tsx`, `Requests`, …).

- New `frontend/src/library.tsx`:
  - `LibraryProvider` loads `api.config.overview` once.
  - `useLibrary()` returns `{ library, libraries, setLibrary, libraryType }`.
  - The choice is read from `?library=` first, then `localStorage` (`studio:library`; wrap every access in try/catch), then the first library.
  - `setLibrary` updates the URL (`replace: true`) and `localStorage`.
  - Merge in or reuse what `libraries.ts` and `useLibraryType` already do.
- Move each page's own `params.get("library")` logic to `useLibrary()`. Keep the visible pickers for now; P1 replaces them with the sidebar picker.
- **Tests:**
  - the choice survives a page change
  - the URL wins over storage
  - an unknown name falls back to the first library
  - storage that throws doesn't break the page
- **Acceptance:**
  - Choosing TV Shows on Ready-made, then opening Collections and Overlays, shows TV Shows on both.
  - No page keeps its own fallback logic.

### P0.2 Shared poster tile and status badge (`poster-tile`)

- New `frontend/src/components/PosterTile.tsx`:
  - a 2:3 poster (Plex thumb through `PlexPoster`, else the colour banner with the title)
  - a status badge in the top-right corner
  - an optional tick button in the bottom-right corner (today's ready-made pick control)
  - caption lines below the poster
- New `StatusBadge`, mapping one state to a dot, a short text and a tone:

  | State | Badge |
  |---|---|
  | `in_plex` (with count) | ok dot + "31" |
  | `building` / `queued` | info dot + "Building" / "Queued" |
  | `missing` | dashed outline + "Not built" |
  | `failed` | err dot + "Failed" |
  | downloading missing | info dot + "9 · 3 coming" |
  | `changed` (from P3a) | accent dot + "Changed" |

  Colours must differ in lightness, not only hue. The badge has text, so it is never colour-only.
- Use it in `Collections.tsx` and `ReadyMadeCategory.tsx` now. Same information as today, moved from caption lines into the badge.
- **Acceptance:** both pages render through `PosterTile`; their existing tests still pass after selector updates; `StatusBadge` has one test per state.

### P0.3 Floating action bar (`action-bar`)

- Generalise `StickyActions` (`ui.tsx`) into `ActionBar`:
  - sticks to the bottom of `<main>`, with a summary text on the left and actions on the right
  - wraps on phones
  - `role="region"` with an `aria-label`
- `BuildBar.tsx` uses it, and it behaves exactly as before.

---

## P1 · Navigation (board B1's sidebar)

### P1.1 Sidebar: library picker, icons, badges (`nav-sidebar`)

Target: `Idea-Home` sidebar.

- In `nav.ts`, the sidebar becomes:
  - Home `/`
  - Collections `/collections`
  - Requests `/requests`
  - Overlays `/overlays`
  - Playlists `/playlists`
  - Activity `/activity`
  - a spacer
  - System `/system`
  - Settings `/settings`
- Libraries (the page) moves into Settings as a "Libraries" tab (P1.2), since the picker now selects the library. Ready-made moves into Collections in P3.2; until then, keep a Ready-made link under Collections so nothing is lost between PRs.
- The library picker sits at the top of the sidebar (a `<select>` labelled "Library"), bound to `useLibrary()`.
- Badges:
  - Requests: the count of waiting requests (requested + downloading), from `requestsApi`, refetched every 60 s
  - Collections: the number of collections in the library
  - System: keeps the health dot (`HealthDot`)
- Icons from `icons.tsx`, each `aria-hidden`.
- **Tests:** `nav.test.ts` covers the new list and the redirects. Layout test: the picker changes the library; badges show and hide.

### P1.2 System and Settings hubs (`nav-hubs`)

- `/system` and `/settings` each become a page with a tab bar (`role="tablist"`; each tab is a link, so URLs stay real):
  - System: Status, Tasks, Backup, Logs, Updates.
  - Settings: General, Plex, Libraries, Connect, Requests, Notifications, Network, Kometa, UI.
- `/system` opens Status and `/settings` opens General.
- Every existing path (`/system/tasks`, `/settings/plex`, `/libraries`, `/libraries/:name`) keeps working, rendered inside its hub.
- `pageTitle()` gives "Settings · Plex" style titles.
- **Acceptance:** every old sidebar path still opens its page; the sidebar has 9 entries; on a phone the tab bar scrolls sideways inside its own box, not the page.

### P1.3 Activity page and run card (`nav-activity`)

- `/activity` holds two tabs: Queue (`/activity/queue`) and History (`/activity/history`). Move the **Run Kometa** form (`RunForm`, today on Overview) to the top of Queue.
- **Run card** at the bottom of the sidebar, replacing the header's Jobs button:
  - From `/api/v1/jobs`.
  - Shows the running job's name ("Building 5 ready-made"), its library and collections, elapsed time, and how many are queued.
  - Clicking it opens the existing `JobsDrawer`.
  - Hidden when nothing runs or waits.
  - There's no real progress figure from Kometa, so the bar is indeterminate. Never show a made-up percentage.
- The header keeps Show Advanced and Sign out.
- **Acceptance:** with a running fake run (`tests/fixtures/fake_kometa.py`), the card shows and opens the drawer; with none, it's gone.

---

## P2 · Home (board `Idea-Home`)

### P2.1 Shelf data: one list of a library's collections (`shelf-api`)

Home and the Collections page need builder collections and built ready-made collections in one list.

- Backend: `GET /api/v1/collections?library=<name>&origin=all` (in `builder_routes.list_collections`).
  - Today it returns builder collections only.
  - With `origin=all`, it also returns ready-made rows that are present or picked (from `collections.py`), in the same shape as `_built_json`, plus `origin: "built" | "ready_made"`, `category` and `kometa_name`.
  - Keep the default response unchanged.
- Each row also gets `last_change` (`{added, removed, run_id}`), joined from the last run's webhook events for that collection title, when there are any.
- **Tests:** `tests/test_builder_routes.py` cases for `origin=all` with fakeplex.

### P2.2 Home page (`home`)

Replace `Overview.tsx`'s dashboard (keep the redirect to `/setup` for new installs).

- **Header:**
  - the library name
  - a line with the title count, collection count and next run ("next run tonight 03:00", from `status.runs.next_scheduled`)
  - a "+ New collection" button
- **Needs you:**
  - shown only when the list isn't empty
  - from three sources: failed collections (P2.1; actions: "Retry", plus "Fix the link" when the error is a source error, opening the builder), failed requests (`requestsApi`, action "Open request"), and health errors (`status.health`, action: the check's own link)
  - at most 5 rows, then "And N more"
- **Your collections:**
  - the first 12 tiles from P2.1 (failed first, then building, then most recently changed), each a `PosterTile`
  - the caption shows the last change ("+27 last run") or the source
  - the last tile is "+ New"
  - "See all N" links to `/collections`
- **Coming in:** counts of downloading, requested and arrived today, plus the two latest rows. Hidden when requests are off and nothing was ever requested.
- **What changed in Plex:** the last finished run's collection events (today's `LastRunChanges` data), New / +n / −n / Gone.
  - Undo is a follow-up, not this PR. Only "Gone" ready-made collections could be restored (re-pick and build), and that sends a build to Plex.
- **Connected:** one line of dots (Plex, Radarr, Sonarr, Seerr, TMDb, Kometa version), from `FullCheck` data, with a link to System → Status.
- Remove from Home: the Run form (now in Activity), "Saved since the last run" (it stays reachable in System → Backup), and the four summary tiles.
- **Tests:** rewrite `Overview.test.tsx`. Needs-you hides when empty; shelf order; Coming in hides when requests are off; setup redirect kept.
- **Acceptance:** with fakeplex data, Home shows the failed collection first in Needs you and on the shelf, and nothing on it mentions run numbers or YAML.

---

## P3 · One Collections page (board `Idea-Collections`)

### P3a Save without building, then one build (`build-queue-api`)

Today every builder save writes files and queues its own run (`builder_routes._save_and_run`), and ready-made builds queue another (`ready_made_routes.build`). The target is one bar that collects everything unbuilt and one Kometa run.

- **Migration `0018_collection_changed.sql`:** add `changed_at TEXT NULL` to `collections`. Set it when a builder definition is saved without a build; clear it when a run containing that collection reaches `run_end`. Never edit a merged migration.
- **`POST/PUT /collections`:** accept `build: bool = true`.
  - With `false`: write the generated files as today (`studio_files.write_from_db`, so Kometa's check still runs) and set `changed_at`, but don't enqueue.
  - Requests for missing titles are filed only when the collection is built.
- **New `POST /api/v1/libraries/{library}/build`** with body `{ready_made: {add, remove}, collections: [row_id], download_missing, dry_run}`:
  - Refactor the planning half of `ready_made_routes.build` (checks: a title taken by a non-Studio collection, Maintainerr, removals) into a function both routes call.
  - `dry_run` returns `{build: [...], remove: [...], blocked: [{title, reason}]}` across both kinds.
  - Otherwise: one `studio_files.write_from_db`, the removals as today, then **one** `RunRequest(mode="collections", libraries=[library], collections=[...all kometa_names])`. Set the run on every row (`col.set_run`) and file the missing requests per collection as `_request_now` does.
  - Keep `/ready-made/build` working; it can call the shared function.
- **`GET /collections?origin=all`:** add `changed: bool`.
- **Tests:**
  - save without building writes but doesn't queue
  - the combined build queues exactly one run with every name
  - a blocked title is reported and left out
  - the Maintainerr guard still holds
  - removals only touch `Studio`-labelled collections
  - `changed_at` clears after `run_end`

### P3.2 The page (`collections-page`)

- `/collections` gets two tabs:
  - **Yours** (default): builder collections, today's `Collections.tsx` grid.
  - **Ready-made:** today's `ReadyMade.tsx` category grid, compact banners, with "N picked · M built" per category.
- Category pages move to `/collections/ready-made/:category`. `/ready-made` and `/ready-made/:category` redirect there, keeping the query string.
- Header:
  - a search box filters the visible tab by title, client-side
  - "Upload a file" opens today's `UploadDialog`
  - "+ New collection" goes to the builder
- Yours tab filter chips, with counts: All, In Plex, Building, Not built, Failed, Fetching missing, Changed. Single choice, kept in `?show=`.
- **Changes bar** (`ActionBar`):
  - shown when there are local ready-made picks (`readyMadePicks.tsx`, sessionStorage) or rows with `changed: true`
  - summary: "6 changes waiting · 5 ready-made picks, 1 edited collection"
  - controls: the Download missing checkbox (greyed with its "?" help when requests are off, as today), Review (the dry-run dialog, extended from today's BuildBar dialog to list both kinds), and **Build all** (one call to the P3a endpoint)
  - It replaces `BuildBar` on both tabs and the category page.
- **Tests:**
  - tab switching keeps the library
  - old URLs redirect
  - the bar counts both kinds
  - Build all sends one request with both
  - Discard clears local picks only
- **Acceptance:** picking 2 ready-made collections and saving 1 builder edit without building ends in one run that builds all 3.

---

## P4 · Builder with a live shelf (board `Idea-Builder`)

### P4a Per-title requests (`request-pick-api`)

Today Download missing is all or nothing per collection.

- Add `skip_requests: [item_key]` to the builder definition (the keys from `list_sources.missing_key`).
  - `_missing_now` leaves those keys out.
  - So does the post-run requester that works from Kometa's missing report (find it from `collection_requests` and `wanted.py`).
  - Keys stay skipped across runs until un-ticked.
- `POST /builder/sources/preview` returns, per missing title, its `key` and whether it's already requested (from the `requests` table), so the UI can tick it.
- **Tests:** skipped keys are never requested, before or after a build; un-ticking requests them on the next save.

### P4.1 The builder page (`builder-shelf`)

Rework `CollectionBuilder.tsx`. Keep its data flow (`draft`, `save`, `LeaveGuard`) and both modes ("Organise what I have" / "Get something new").

- **Header:** breadcrumb plus the title as an inline input (labelled "Title" for screen readers). Auto-title from the first list stays as today.
- **Left column (max 420 px): numbered step cards.** The open step shows its form; closed steps show a one-line summary and an "Edit" button.
  1. What goes in (sources; or Filters in organise mode)
  2. Narrow it down (filters on top of sources, where the mode allows)
  3. Order and size
  4. How it looks in Plex (Poster + Where it shows)
  5. Details (optional)

  Summaries are written from the draft, e.g. "As the list has it · no limit · at least 1 title". Validation errors open their step.
- **Right: the shelf, the main pane.**
  - the collection's poster at a large size
  - "24 titles now, 31 when complete"
  - a segmented control: "In <library> · 24" / "Missing · 7"
  - a poster wall (`ListPreview` / `PreviewPane` data, shown larger)
  - In organise mode there's no Missing tab.
- **Missing tab:** each title has a request checkbox (P4a), ticked by default when Download missing is on, disabled with a reason when requests are off or the title is already requested.
- **Draft:** autosave the draft to `localStorage` per library and collection id (`studio:builder-draft:<library>:<id|new>`, try/catch). Offer "Restore your unsaved draft?" on return. "Draft saved" in the header refers only to this local draft. Don't promise a server save.
- **Build bar** (`ActionBar`, always visible):
  - a short note ("Plex keeps it up to date after that")
  - a "Download N missing" checkbox
  - Cancel
  - "Save for later" (P3a `build: false`)
  - **Build**
- **Tests:** update `CollectionBuilder.test.tsx`. Step summaries; an error opens its step; the shelf tabs; per-title ticks go into `skip_requests`; draft restore; Save for later vs Build.
- **Acceptance:** making the "A24 Horror" example from the board, with 3 of 7 missing ticked, requests exactly those 3.

---

## P5 · Overlay studio (board `Idea-Overlays`)

Today: `Overlays.tsx` (per-library on/off, schedule, backup, Apply now) and `OverlayDesigner.tsx` (layers, placement preview, variables). Target: one page per library.

**Known bug to fix on the way:** the designer draws its placement boxes on Plex's current poster (`OverlayPreview.tsx` uses `item.thumb`). Once Kometa has drawn overlays, that poster already carries them, so the preview shows every badge twice. P5a fixes it.

### P5a Original posters and a redraw estimate (`overlay-api`)

- **New `GET /api/v1/overlays/{library}/original/{rating_key}`:**
  - Serves Kometa's backup of the untouched poster: `<overlay folder>/<library mapping name> Original Posters/<rating_key>.{png,jpg,webp}`.
  - Check the path rules in `kometa/modules/library.py` (`overlay_backup`) and `modules/overlays.py` (`_scan_overlay_backup_extensions`). Resolve the overlay folder the way `overlays_routes.py` already finds the backup.
  - Shrink to at most 680×1020 WebP, cached under `<data dir>/overlay-originals/` keyed by file mtime.
  - 404 when there's no backup: the item has never had an overlay, so its Plex poster is already the original.
  - Reject any `rating_key` that isn't digits; never serve outside that folder.
- **`GET /overlays`:** per library, add `items` (the library's item count, from Plex) and `last_pass_seconds` (`finished_at − started_at` of the last pass).
- **New `POST /api/v1/overlays/{library}/estimate`** with body `{layers: [{name, variables}]}`. Returns `{posters, minutes}`:
  - `posters` = the library's item count. Kometa reads every item and redraws those whose overlay changed; Studio can't know which ahead of time, so call it "up to".
  - `minutes` = from `last_pass_seconds`, scaled by item count when that changed; `null` when there has never been a pass.
  - Keep the copy honest: "Kometa redraws up to 1,284 posters, about 20 minutes like the last pass".
- **Tests:**
  - original served, 404 without a backup
  - path traversal refused
  - the estimate with and without a previous pass

### P5.1 One page per library (`overlay-studio`)

- `/overlays` becomes the studio for the selected library. `/overlays/designer?library=` redirects to `/overlays`.
- **Header:**
  - "Overlays · <library>"
  - a status line: last drawn (relative), "N original posters backed up", Maintainerr's position (today's texts from `LibraryCard`)
  - an **Overlays on** switch (today's off/on, including the confirm before turning off and the refusal without a backup)
  - a "Schedule · nightly 03:30" button opening today's `Schedules` + `Imports` controls in a dialog
- **Left: Layers panel.**
  - Rows in **draw order with the top drawn last** (the reverse of today's list; say "top draws last").
  - Drag to reorder with a keyboard alternative: a focused row moves with Alt+↑/↓, and the ↑/↓ buttons stay available. Each drop calls `setOverlayOrder`, as today.
  - An eye button hides a layer in the preview only. It never saves.
  - The user's own overlay files show as locked rows, linking to Libraries → <library> → Overlays.
  - "Add a layer": chips for the five most common addable defaults, then "All N…" opening the full list (today's `addable`).
- **Middle: preview.**
  - A segmented control: **Now in Plex** (`item.thumb`, no boxes) / **With your changes** (the P5a original, or the thumb when 404, plus the placement boxes).
  - The 3×3 snap guides show while a layer is selected.
  - **Drag a box** on the poster: on drop, snap to the nearest of the nine anchors and set the offsets from the remainder (only for layers that move with `horizontal_align`/`vertical_align`; position-based layers like ratings snap to their allowed positions).
  - Selecting a box selects its layer.
  - "Placement only: Kometa draws the real badges with their own images" stays under the poster.
- **Try it on:**
  - a row of up to 5 sample titles picked for different traits from `useSamples`: highest resolution, a 1080p one, one without ratings, a show if the library has seasons
  - "+ Pick a title" opens today's `SamplePicker` search
  - a title where two boxes overlap gets an "Overlaps" caption, computed from the boxes' rectangles
- **Right: settings in three tabs.**
  - **Place:** the anchor grid; for ratings, "Run: Across / Down"; a "Distance from the edge" slider writing both offsets; numeric fields under Show Advanced.
  - **Style:** background swatches (black, charcoal, white, accent, custom), a "See-through" slider writing the alpha digits of `back_color`, a "Rounded corners" slider (`back_radius`), and the per-default featured controls (rating sources, logos).
  - **Show when:** today's toggles and `noToggles` texts.
- **What changes:** one sentence built from the difference between the saved and the panel's variables ("Ratings move from the right side to the bottom corner and run across."). Today's YAML preview moves behind "Show the config.yml lines". More variables stays, under Show Advanced.
- **Apply bar** (`ActionBar`): "N layers changed · Kometa redraws up to X posters, about Y minutes" (P5a), with:
  - **Undo** (back to the saved variables)
  - **Save for tonight** (today's save; the next scheduled pass draws it)
  - **Apply now** (save, then `api.overlays.apply`)
- Removing a layer is a quiet button at the bottom of the settings panel, with today's confirm.
- **Tests:** rewrite `Overlays.test.tsx` and `OverlayDesigner.test.tsx`.
  - Now / With changes use the right images
  - dragging snaps to an anchor and sets the right variables
  - layer order saves
  - the overlap caption
  - the sentence for at least alignment, offset and colour changes
  - Save for tonight vs Apply now
  - turning off still asks and still refuses without a backup
- **Acceptance:** on a library that already has overlays, the "With your changes" preview shows each badge once, and moving Resolution to the top right then pressing Apply now queues one overlays-only run.

---

## Out of scope for this plan

- Collection Undo on Home (needs its own design: what Undo sends to Plex).
- Real-time Kometa progress (no source for it).
- Playlists and the Requests page beyond the nav badge.
- Any change to Kometa or to Maintainerr's collections.

## Risks to watch

- **Moved pages:** P1 and P3 move many pages. Run the whole frontend suite and click through every old path before marking ready.
- **One run for everything (P3a):** check that `--run-collections` with many titles still implies collections-only, and never add `--mode` (see `AGENTS.md` → `kometa_command.py`).
- **Kometa updates:** original-poster paths (P5a) follow Kometa's internals. Note the source lines in a comment and in `AGENTS.md`'s layout table, so they're checked on a Kometa update like the other catalogues.
- **Shared defaults:** the overlay studio's drag-to-snap writes the same template variables as today. Kometa's check on save (`ConfigWriter`) must still pass for every variable it writes.
