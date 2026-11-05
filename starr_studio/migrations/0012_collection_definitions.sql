-- Collections made in the builder (origin 'built', category 'built'): what the user asked for, as JSON
-- {filters, sort_by, limit, visible, minimum_items, summary, sort_title}. NULL for ready-made picks.
ALTER TABLE collections ADD COLUMN definition TEXT;
