-- How many lines of a run's log were warnings, counted as the log is written. Earlier runs have 0.
ALTER TABLE runs ADD COLUMN warnings INTEGER NOT NULL DEFAULT 0;
