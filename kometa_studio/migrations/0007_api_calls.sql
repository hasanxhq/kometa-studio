-- Each run's calls per service (tmdb, mdblist, …), from Kometa's --timings file: {"tmdb": 412, "mdblist": 38}.
ALTER TABLE runs ADD COLUMN api_calls TEXT;
