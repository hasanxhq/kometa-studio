-- Overseerr and Jellyseerr became one app, Seerr. Requests filed through either now say 'seerr',
-- so refresh and cancel only need to know one name.
UPDATE requests SET via = 'seerr' WHERE via IN ('overseerr', 'jellyseerr');
