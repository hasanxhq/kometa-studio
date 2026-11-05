-- The TMDb key's DNS bypass (a quick fix) is gone: Settings → Network's proxy replaced it.
DELETE FROM settings WHERE key = 'tmdb.doh';
