-- The Radarr/Sonarr quality profile a collection's requests use instead of the default in Settings → Requests.
-- NULL uses the default.
ALTER TABLE collections ADD COLUMN request_profile TEXT;
