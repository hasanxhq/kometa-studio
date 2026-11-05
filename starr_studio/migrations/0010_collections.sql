-- Studio's ready-made collection picks per library, and cached preview counts for the picker.
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library TEXT NOT NULL,            -- config.yml library name
    category TEXT NOT NULL,           -- Kometa default name, e.g. 'genre', 'imdb', 'oscars'
    block TEXT NOT NULL DEFAULT '',   -- '' for a static collection; the dynamic_collections block name otherwise (e.g. 'Genre')
    key TEXT NOT NULL,                -- static: the mapping name under collections:; dynamic: Kometa's dynamic key (e.g. 'Action', '2020')
    kometa_name TEXT NOT NULL,        -- the name --run-collections takes
    title TEXT NOT NULL,              -- the title expected in Plex
    origin TEXT NOT NULL DEFAULT 'ready_made',
    desired INTEGER NOT NULL DEFAULT 1,   -- 1: should exist in Plex; 0: marked for removal
    run_scope TEXT NOT NULL DEFAULT 'collection',  -- 'collection' (built with --run-collections) or 'file' (fallback: --run-files)
    plex_rating_key TEXT,
    plex_exists INTEGER NOT NULL DEFAULT 0,
    plex_items INTEGER,
    plex_thumb TEXT,
    plex_checked_at TEXT,
    last_built_at TEXT,
    last_run_id INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (library, category, block, key)
);
CREATE INDEX collections_library ON collections (library, category);

CREATE TABLE preview_counts (
    library TEXT NOT NULL,
    category TEXT NOT NULL,
    data TEXT NOT NULL,        -- JSON written by the counting job
    counted_at TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (library, category)
);
