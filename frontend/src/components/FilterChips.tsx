// A collection's filters as chips (the concept's collection builder): each filter Kometa applies to what the sources
// found, in words, with × to take it out, and the common ones (year, rating, genre) added from a short form.
// Several filter sets (a list, where any set may match) stay under Show Advanced as YAML.

import { useState } from "react";

import { Button, Card, inputClass } from "./ui";

type Filters = Record<string, unknown>;

// What can be added here: Kometa 2.5.3's names (modules/builder.py: number_filters, tag_filters).
const ADDABLE: { key: string; label: string; input: "year" | "rating" | "list" }[] = [
  { key: "year.gte", label: "Year from", input: "year" },
  { key: "year.lte", label: "Year up to", input: "year" },
  { key: "critic_rating.gte", label: "Critic rating at least", input: "rating" },
  { key: "audience_rating.gte", label: "Audience rating at least", input: "rating" },
  { key: "user_rating.gte", label: "Your rating at least", input: "rating" },
  { key: "genre", label: "Genre is any of", input: "list" },
  { key: "genre.not", label: "Genre is none of", input: "list" },
];

const ATTRIBUTES: Record<string, string> = {
  year: "Year",
  critic_rating: "Critic rating",
  audience_rating: "Audience rating",
  user_rating: "Your rating",
  genre: "Genre",
  content_rating: "Content rating",
  tmdb_vote_average: "TMDb rating",
  tmdb_vote_count: "TMDb votes",
  original_language: "Original language",
  audio_language: "Audio language",
  subtitle_language: "Subtitle language",
  release: "Released",
  added: "Added",
  last_played: "Last played",
  plays: "Plays",
  duration: "Length (min)",
};

const MODIFIERS: Record<string, string> = {
  "": "",
  ".is": "is exactly",
  ".not": "isn't",
  ".isnot": "isn't exactly",
  ".gt": ">",
  ".gte": "≥",
  ".lt": "<",
  ".lte": "≤",
  ".before": "before",
  ".after": "after",
  ".begins": "begins with",
  ".ends": "ends with",
  ".regex": "matches",
  ".count_gt": "count >",
  ".count_gte": "count ≥",
  ".count_lt": "count <",
  ".count_lte": "count ≤",
};

function show(value: unknown): string {
  if (Array.isArray(value)) return value.map(show).join(", ");
  if (value === null || value === undefined) return "(empty)";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** A filter in words: "Year ≥ 2000", "Genre isn't: Horror", "Genre: Comedy, Drama". */
export function describeFilter(key: string, value: unknown): string {
  const dot = key.indexOf(".");
  const attribute = dot === -1 ? key : key.slice(0, dot);
  const modifier = dot === -1 ? "" : key.slice(dot);
  const name = ATTRIBUTES[attribute] ?? attribute.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const word = MODIFIERS[modifier] ?? modifier.slice(1);
  if (typeof value === "boolean" && !word) return value ? name : `Not ${name.toLowerCase()}`;
  if (!word) return `${name}: ${show(value)}`;
  return /^[<>≤≥]|count/.test(word) ? `${name} ${word} ${show(value)}` : `${name} ${word}: ${show(value)}`;
}

function asList(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  return (Array.isArray(value) ? value : String(value).split(",")).map((v) => String(v).trim()).filter(Boolean);
}

/** ``filters`` with one more: a genre list joins what's there, a number replaces it. */
export function withFilter(filters: Filters, key: string, raw: string): Filters {
  const spec = ADDABLE.find((a) => a.key === key)!;
  if (spec.input === "list") {
    const merged = [...new Set([...asList(filters[key]), ...asList(raw)])];
    return { ...filters, [key]: merged.length === 1 ? merged[0] : merged };
  }
  return { ...filters, [key]: Number(raw) };
}

export function FilterChips({ filters, onChange }: { filters: Filters | undefined; onChange: (filters: Filters | undefined) => void }) {
  const current = filters ?? {};
  const [key, setKey] = useState(ADDABLE[0].key);
  const [raw, setRaw] = useState("");
  const spec = ADDABLE.find((a) => a.key === key)!;
  const number = Number(raw);
  const valid =
    spec.input === "list"
      ? asList(raw).length > 0
      : raw.trim() !== "" && Number.isFinite(number) && (spec.input === "year" ? Number.isInteger(number) && number >= 1800 && number <= 2200 : number >= 0 && number <= 10);
  const remove = (name: string) => {
    const next = { ...current };
    delete next[name];
    onChange(Object.keys(next).length ? next : undefined); // no filters left: the key goes
  };
  const add = (event: { preventDefault: () => void }) => {
    event.preventDefault();
    if (!valid) return;
    onChange(withFilter(current, key, raw));
    setRaw("");
  };

  return (
    <Card title="Filters">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">Only what the sources found and every filter allows goes in. Ratings are out of 10.</p>
        {Object.keys(current).length === 0 ? (
          <p className="text-sm text-muted">No filters: everything the sources find goes in.</p>
        ) : (
          <ul className="flex flex-wrap gap-2" aria-label="Filters">
            {Object.entries(current).map(([name, value]) => (
              <li key={name} className="flex min-h-9 items-center gap-1 rounded-full border border-accent/50 bg-surface-2 pl-3 text-sm" title={name}>
                <span className="break-words">{describeFilter(name, value)}</span>
                <button
                  type="button"
                  className="flex size-9 shrink-0 items-center justify-center rounded-full text-muted hover:text-text"
                  aria-label={`Remove ${describeFilter(name, value)}`}
                  onClick={() => remove(name)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {/* A div, not a form: this sits inside the editor's own form. */}
        <div className="flex flex-wrap items-end gap-2" role="group" aria-label="Add a filter" onKeyDown={(e) => e.key === "Enter" && e.target instanceof HTMLInputElement && add(e)}>
          <label className="flex min-w-0 flex-1 basis-48 flex-col gap-1.5 text-sm">
            <span className="text-muted">Add a filter</span>
            <select
              className={inputClass}
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setRaw("");
              }}
            >
              {ADDABLE.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-0 flex-1 basis-40 flex-col gap-1.5 text-sm">
            <span className="text-muted">{spec.input === "list" ? "Genres, separated by commas" : spec.input === "year" ? "Year" : "Rating (0 to 10)"}</span>
            <input
              className={inputClass}
              value={raw}
              inputMode={spec.input === "list" ? "text" : "decimal"}
              placeholder={spec.input === "list" ? "Comedy, Drama" : spec.input === "year" ? "2000" : "7.5"}
              onChange={(e) => setRaw(e.target.value)}
            />
          </label>
          <Button onClick={add} disabled={!valid}>
            Add
          </Button>
        </div>
      </div>
    </Card>
  );
}
