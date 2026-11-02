// The overlay designer's pieces, shared with the single overlay form: a poster with its overlays placed on it, the picker for which
// title to preview on, and the nine-cell anchor grid.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useDeferredValue, useState, type ReactNode } from "react";

import { api, type PlexItem } from "../api";
import { mergeLibraries } from "../libraries";
import { POSTER_HEIGHT, POSTER_WIDTH, type Box } from "../overlayLayout";
import { inputClass } from "./ui";

/** Titles from this library to preview on: the newest, or what the search finds. */
export function useSamples(library: string | null) {
  const plex = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000, enabled: !!library });
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false, enabled: !!library });
  const key = mergeLibraries(plex.data?.libraries, overview.data?.libraries).find((entry) => entry.config?.name === library)?.plex?.key ?? null;
  const [search, setSearch] = useState("");
  const needle = useDeferredValue(search.trim());
  const items = useQuery({
    queryKey: ["plex", "items", key, needle],
    queryFn: () => api.plexLibraries.items(key!, needle),
    enabled: key !== null,
    retry: false,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
  const found = items.data?.items ?? [];
  const [picked, setPicked] = useState<PlexItem | null>(null);
  return { found, sample: picked ?? found[0] ?? null, search, setSearch, setPicked, error: plex.error ?? items.error };
}

export function SamplePicker({ samples }: { samples: ReturnType<typeof useSamples> }) {
  const { found, sample, search, setSearch, setPicked } = samples;
  const titles = sample && !found.some((item) => item.rating_key === sample.rating_key) ? [sample, ...found] : found;
  return (
    <div className="flex flex-wrap items-end justify-center gap-2 text-[13px] text-muted">
      <label className="flex items-center gap-2 whitespace-nowrap">
        Preview on
        <select
          className={`${inputClass} w-52 max-w-full`}
          value={sample?.rating_key ?? ""}
          disabled={titles.length === 0}
          onChange={(event) => setPicked(titles.find((item) => item.rating_key === event.target.value) ?? null)}
        >
          {titles.length === 0 && <option value="">No titles</option>}
          {titles.map((item) => (
            <option key={item.rating_key} value={item.rating_key}>
              {item.title}
              {item.year ? ` (${item.year})` : ""}
            </option>
          ))}
        </select>
      </label>
      <input className={`${inputClass} w-40 max-w-full`} type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a title" aria-label="Find a title to preview on" />
    </div>
  );
}

/** A poster with its overlays placed on it. With `onPick`, each overlay is a button; sizes follow the poster's own width. */
export function OverlayPoster({
  item,
  boxes,
  selected,
  onPick,
  label,
  className = "w-full max-w-[340px]",
  fontSize = "3.6cqw",
}: {
  item: PlexItem | null;
  boxes: Box[];
  selected?: string | null;
  onPick?: (box: Box) => void;
  label: string;
  className?: string;
  fontSize?: string; // relative to the poster, so a thumbnail can use a bigger share of it
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const thumb = item?.thumb && failed !== item.thumb ? item.thumb : null;
  return (
    <div role="group" aria-label={label} className={`relative aspect-[2/3] overflow-hidden rounded-[10px] bg-surface-2 ${className}`} style={{ containerType: "inline-size" }}>
      {thumb ? (
        <img src={api.plexLibraries.imageUrl(thumb, 680, 1020)} alt="" className="absolute inset-0 size-full object-cover" onError={() => setFailed(thumb)} />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center p-4 text-center font-display text-sm text-muted">{item?.title}</div>
      )}
      {boxes.map((box) => {
        const place = {
          left: `${(box.x / POSTER_WIDTH) * 100}%`,
          top: `${(box.y / POSTER_HEIGHT) * 100}%`,
          width: `${(box.width / POSTER_WIDTH) * 100}%`,
          height: `${(box.height / POSTER_HEIGHT) * 100}%`,
          background: box.color,
          color: box.textColor,
          borderRadius: `${(box.radius / POSTER_WIDTH) * 100}cqw`,
          fontSize,
        };
        const look = `absolute flex items-center justify-center overflow-hidden px-[1cqw] text-center font-display leading-none font-semibold text-white ${selected === box.key.replace(/-\d+$/, "") ? "outline-2 outline-accent" : ""}`;
        return onPick ? (
          <button key={box.key} type="button" aria-label={`Select ${box.label}`} className={look} style={place} onClick={() => onPick(box)}>
            {box.label}
          </button>
        ) : (
          <span key={box.key} className={look} style={place}>
            {box.label}
          </span>
        );
      })}
    </div>
  );
}

const ROWS = ["top", "center", "bottom"];
const COLUMNS = ["left", "center", "right"];
const words = (word: string) => word[0].toUpperCase() + word.slice(1);

/** The nine places an overlay can anchor to. */
export function AnchorGrid({ horizontal, vertical, onChange, children }: { horizontal: string; vertical: string; onChange: (horizontal: string, vertical: string) => void; children?: ReactNode }) {
  return (
    <fieldset>
      <legend className="mb-2 text-[13px] text-muted">Anchor</legend>
      <div className="grid w-fit grid-cols-3 gap-1.5">
        {ROWS.flatMap((row) =>
          COLUMNS.map((column) => {
            const name = row === "center" && column === "center" ? "Center" : `${words(row === "center" ? "middle" : row)} ${column}`;
            const on = row === vertical && column === horizontal;
            return (
              <button
                key={name}
                type="button"
                aria-label={name}
                aria-pressed={on}
                onClick={() => onChange(column, row)}
                className={`size-11 rounded-control border transition-colors ${on ? "border-accent bg-accent" : "border-border-strong bg-surface-2 hover:border-muted"}`}
              />
            );
          }),
        )}
      </div>
      {children}
    </fieldset>
  );
}

/** Kometa's offsets: pixels on its 1000×1500 poster, or a percentage. */
export function OffsetInput({ value, onChange, label, placeholder = "e.g. 30 or 5%" }: { value: unknown; onChange: (v: unknown) => void; label: string; placeholder?: string }) {
  return (
    <input
      aria-label={label}
      className={inputClass}
      value={value === undefined ? "" : String(value)}
      placeholder={placeholder}
      onChange={(e) => {
        const text = e.target.value.trim();
        onChange(text === "" ? undefined : /^-?\d+$/.test(text) ? Number(text) : text);
      }}
    />
  );
}
