-- Kometa runs: queued, running and finished. One runs at a time (handoff v2 §2).
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted', 'timed_out')),
    request     TEXT NOT NULL,                  -- the RunRequest, JSON
    trigger     TEXT NOT NULL DEFAULT 'manual', -- manual, schedule, catch_up, arr
    command     TEXT,                           -- what was executed, for display
    queued_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at  TEXT,
    finished_at TEXT,
    exit_code   INTEGER,
    summary     TEXT,                           -- Kometa's run_end webhook payload, JSON
    error       TEXT                            -- why Studio couldn't run it, or why it stopped
);
CREATE INDEX runs_by_status ON runs (status, id);

-- Webhook events from Kometa. run_id is NULL for events that arrived with no run going.
CREATE TABLE run_events (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER REFERENCES runs (id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    payload     TEXT NOT NULL
);
CREATE INDEX run_events_by_run ON run_events (run_id, event);
