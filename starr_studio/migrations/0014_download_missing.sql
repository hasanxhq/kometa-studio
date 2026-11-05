-- Download missing (phase 3): a collection asks for the titles it lacks. request_cap overrides the daily cap in
-- Settings → Requests for this collection (NULL = the setting's).
ALTER TABLE collections ADD COLUMN download_missing INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collections ADD COLUMN request_cap INTEGER;
