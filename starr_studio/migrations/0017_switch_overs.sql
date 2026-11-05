-- Moving over from Kometa (phase 4): each Switch over, the full backup it took first, and whether it was undone.
-- Undo is kept for good: it restores Kometa's files and Studio's collection rows from that backup.
CREATE TABLE switch_overs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    backup TEXT NOT NULL,          -- zip name under <data dir>/switch-over/
    summary TEXT NOT NULL,         -- JSON: {imported, ready_made, kept, libraries}
    created_rows TEXT NOT NULL,    -- JSON: ids of the collections rows it added (they adopt what Kometa had built)
    run_id INTEGER,
    undone_at TEXT,
    undo_backup TEXT               -- the full backup taken just before Undo
);
