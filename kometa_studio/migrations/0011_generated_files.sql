-- What Studio last wrote to each of its generated files (studio/<library>/<category>.yml), to notice hand edits.
CREATE TABLE generated_files (
    path TEXT PRIMARY KEY,     -- relative to Kometa's config folder
    hash TEXT NOT NULL,        -- sha256 of the text Studio wrote
    written_at TEXT NOT NULL
);
