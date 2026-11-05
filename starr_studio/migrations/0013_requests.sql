CREATE TABLE requests (
    id            INTEGER PRIMARY KEY,
    item          TEXT NOT NULL,          -- 'tmdb-movie:603' | 'tvdb:81189' | 'tmdb-show:1399'
    media         TEXT NOT NULL,          -- 'movie' | 'show'
    title         TEXT,
    year          INTEGER,
    library       TEXT NOT NULL,          -- config.yml library name
    collection_id INTEGER,                -- collections.id of the collection that asked, NULL for a manual request
    via           TEXT NOT NULL,          -- 'radarr' | 'sonarr' | 'overseerr' | 'jellyseerr'
    external_id   TEXT,                   -- the app's own id (Radarr movie id, Sonarr series id, Seerr request id)
    status        TEXT NOT NULL,          -- 'requested' | 'downloading' | 'imported' | 'failed' | 'cancelled' | 'exists'
    error         TEXT,
    requested_at  TEXT NOT NULL,          -- UTC ISO, like the other tables
    updated_at    TEXT NOT NULL,
    imported_at   TEXT,
    labelled_at   TEXT                    -- when the Plex 'starr' label was added
);
CREATE INDEX requests_item ON requests (item);
CREATE INDEX requests_collection ON requests (collection_id, requested_at);
