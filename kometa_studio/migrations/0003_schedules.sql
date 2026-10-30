-- Schedules: run Kometa on chosen days at a local time (handoff v2 §6).
CREATE TABLE schedules (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    request       TEXT NOT NULL,                      -- the RunRequest, JSON
    days          INTEGER NOT NULL DEFAULT 127        -- bit 0 = Monday ... bit 6 = Sunday
                  CHECK (days BETWEEN 1 AND 127),
    time          TEXT NOT NULL                       -- local HH:MM
                  CHECK (time GLOB '[0-2][0-9]:[0-5][0-9]'),
    timezone      TEXT NOT NULL,                      -- IANA name, e.g. Asia/Kolkata
    enabled       INTEGER NOT NULL DEFAULT 1,
    catch_up      TEXT NOT NULL DEFAULT 'run_once'    -- after downtime: run once, or skip
                  CHECK (catch_up IN ('run_once', 'skip')),
    last_fired_at TEXT NOT NULL,                      -- UTC; occurrences up to here are handled
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

ALTER TABLE runs ADD COLUMN schedule_id INTEGER REFERENCES schedules (id) ON DELETE SET NULL;
