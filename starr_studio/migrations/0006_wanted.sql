-- Studio's copy of what Kometa's collections want but Plex doesn't have yet (feedback round 1), so an
-- import from Radarr or Sonarr only runs Kometa when it matters. Filled from Kometa's missing report
-- (<library>_report.yml, written when save_report is on) after each run that went through to run_end.
CREATE TABLE wanted (
    library    TEXT NOT NULL,                 -- the library's name in config.yml
    collection TEXT NOT NULL,
    item       TEXT NOT NULL,                 -- 'tmdb:603' (a movie) or 'tvdb:81189' (a show)
    title      TEXT,
    seen_at    TEXT NOT NULL,                 -- UTC, when Kometa last reported it
    PRIMARY KEY (library, collection, item)
);
CREATE INDEX wanted_item ON wanted (item);

-- Per library: the collection files as they were when Kometa last reported on all its collections.
-- If they've changed since, Studio doesn't know what the collections want, so imports run Kometa.
CREATE TABLE wanted_libraries (
    library     TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    run_id      INTEGER
);
