// Paste TMDb / IMDb / TVDb ids (or TMDb links) for an individual-titles source.

import { useState } from "react";

import type { TitleBuilder } from "../../builderApi";
import { Field, inputClass } from "../ui";

const MOVIE_BUILDERS: { builder: TitleBuilder; label: string }[] = [
  { builder: "tmdb_movie", label: "TMDb movie" },
  { builder: "imdb_id", label: "IMDb title" },
];

const SHOW_BUILDERS: { builder: TitleBuilder; label: string }[] = [
  { builder: "tmdb_show", label: "TMDb show" },
  { builder: "tvdb_show", label: "TVDb show" },
  { builder: "imdb_id", label: "IMDb title" },
];

/** Pull one id out of a pasted token (plain id or a common link). */
export function extractTitleId(token: string, builder: TitleBuilder): string | null {
  const text = token.trim();
  if (!text) return null;
  if (builder === "imdb_id") {
    const fromUrl = text.match(/imdb\.com\/title\/(tt\d+)/i);
    if (fromUrl) return fromUrl[1].toLowerCase();
    const bare = text.match(/^(tt\d+)$/i);
    return bare ? bare[1].toLowerCase() : null;
  }
  if (builder === "tmdb_movie") {
    const fromUrl = text.match(/themoviedb\.org\/movie\/(\d+)/i);
    if (fromUrl) return String(Number.parseInt(fromUrl[1], 10));
  }
  if (builder === "tmdb_show") {
    const fromUrl = text.match(/themoviedb\.org\/tv\/(\d+)/i);
    if (fromUrl) return String(Number.parseInt(fromUrl[1], 10));
  }
  if (builder === "tvdb_show") {
    const fromUrl = text.match(/thetvdb\.com\/(?:series|movies)\/[^/\s]*\/?.*?[?&]id=(\d+)/i) || text.match(/[?&]id=(\d+)/i);
    if (fromUrl) return String(Number.parseInt(fromUrl[1], 10));
  }
  if (/^\d+$/.test(text) && Number.parseInt(text, 10) >= 1) return String(Number.parseInt(text, 10));
  return null;
}

/** Ids read from pasted text (lines or commas); skips tokens that don't match the builder. */
export function parseTitleIds(text: string, builder: TitleBuilder): string[] {
  const tokens = text
    .split(/[\n,]+/)
    .flatMap((line) => line.trim().split(/\s+/))
    .map((token) => token.trim())
    .filter(Boolean);
  const out: string[] = [];
  for (const token of tokens) {
    const id = extractTitleId(token, builder);
    if (id && !out.includes(id)) out.push(id);
  }
  return out;
}

export function TitlesSource({
  libraryType,
  builder,
  ids,
  onChange,
}: {
  libraryType: "movie" | "show";
  builder: TitleBuilder;
  ids: string[];
  onChange: (next: { builder: TitleBuilder; ids: string[]; label: string | null }) => void;
}) {
  const choices = libraryType === "show" ? SHOW_BUILDERS : MOVIE_BUILDERS;
  const active = choices.some((c) => c.builder === builder) ? builder : choices[0]!.builder;
  const [text, setText] = useState(() => ids.join("\n"));
  const read = parseTitleIds(text, active);

  const apply = (nextBuilder: TitleBuilder, nextText: string) => {
    const nextIds = parseTitleIds(nextText, nextBuilder);
    const label = choices.find((c) => c.builder === nextBuilder)?.label ?? nextBuilder;
    onChange({ builder: nextBuilder, ids: nextIds, label: nextIds.length ? `${label} · ${nextIds.length}` : label });
  };

  return (
    <div className="flex flex-col gap-3">
      <Field label="Id kind">
        <select
          className={inputClass}
          value={active}
          onChange={(event) => {
            const next = event.target.value as TitleBuilder;
            apply(next, text);
          }}
          aria-label="Id kind"
        >
          {choices.map((choice) => (
            <option key={choice.builder} value={choice.builder}>
              {choice.label}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Titles"
        hint={
          active === "imdb_id"
            ? "IMDb ids (tt…) or title links, one per line or comma separated"
            : active.startsWith("tmdb_")
              ? "TMDb ids or themoviedb.org links, one per line or comma separated"
              : "TVDb ids, one per line or comma separated"
        }
      >
        <textarea
          className={`${inputClass} min-h-28 py-2 font-mono text-sm`}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            apply(active, event.target.value);
          }}
          aria-label="Title ids"
          placeholder={active === "imdb_id" ? "tt0133093" : "550"}
        />
      </Field>
      <p className="text-sm text-muted" aria-live="polite">
        {read.length === 0 ? "No ids read yet." : `Read ${read.length} id${read.length === 1 ? "" : "s"}.`}
      </p>
    </div>
  );
}
