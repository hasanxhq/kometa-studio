-- Studio's built-in tasks on System → Tasks (handoff v2 §8): full backups and Kometa's full check.
CREATE TABLE tasks (
    name             TEXT PRIMARY KEY,                    -- full_backup, full_check
    enabled          INTEGER NOT NULL,
    days             INTEGER NOT NULL CHECK (days BETWEEN 1 AND 127),  -- bit 0 = Monday ... bit 6 = Sunday
    time             TEXT NOT NULL CHECK (time GLOB '[0-2][0-9]:[0-5][0-9]'),
    timezone         TEXT NOT NULL,
    options          TEXT NOT NULL DEFAULT '{}',          -- JSON, e.g. {"keep": 4}
    last_fired_at    TEXT NOT NULL,                       -- UTC; occurrences up to here are handled
    last_started_at  TEXT,
    last_finished_at TEXT,
    last_status      TEXT CHECK (last_status IN ('running', 'succeeded', 'failed', 'interrupted')),
    last_message     TEXT
);
