-- Signed-in browsers (handoff v2 §8, forms login). Only a hash of each session token is kept.
CREATE TABLE sessions (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at  TEXT NOT NULL
);
