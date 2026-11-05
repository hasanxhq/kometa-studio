// Several list / titles / Plex-search sources for one "Get something new" collection.

import { useState } from "react";

import { sourceLabel, type BuilderField, type Source, type TitleBuilder } from "../../builderApi";
import { Button } from "../ui";
import { blankRule, FilterRules, type DraftFilters } from "./FilterRules";
import { ListSource, type ListSourceValue } from "./ListSource";
import { TitlesSource } from "./TitlesSource";

export const MAX_SOURCES = 20;

// `uid` is only for the page: it keys each row, so a row's own state (the pasted ids) stays with its source when
// another source is removed. It never reaches the API.
export type DraftSource = { uid: string } & (
  | { kind: "list"; builder: string; value: string; label: string | null }
  | { kind: "titles"; builder: TitleBuilder; ids: string[]; label: string | null }
  | { kind: "search"; filters: DraftFilters }
);

let nextUid = 0;
function uid(): string {
  nextUid += 1;
  return `source-${nextUid}`;
}

type AddKind = "list" | "titles" | "search";

function defaultTitlesBuilder(libraryType: "movie" | "show"): TitleBuilder {
  return libraryType === "show" ? "tmdb_show" : "tmdb_movie";
}

export function blankListSource(): DraftSource {
  return { uid: uid(), kind: "list", builder: "", value: "", label: null };
}

export function blankTitlesSource(libraryType: "movie" | "show"): DraftSource {
  const builder = defaultTitlesBuilder(libraryType);
  return { uid: uid(), kind: "titles", builder, ids: [], label: builder === "tmdb_show" ? "TMDb show" : "TMDb movie" };
}

export function blankSearchSource(fields: BuilderField[]): DraftSource {
  return { uid: uid(), kind: "search", filters: { match: "all", rules: [blankRule(fields)] } };
}

export function draftSourcesFrom(sources: Source[]): DraftSource[] {
  const out: DraftSource[] = [];
  for (const source of sources) {
    if (source.kind === "list") out.push({ uid: uid(), kind: "list", builder: source.builder, value: source.value, label: source.label });
    else if (source.kind === "titles") {
      out.push({ uid: uid(), kind: "titles", builder: source.builder, ids: [...source.ids], label: source.label });
    } else if (source.kind === "search") {
      out.push({
        uid: uid(),
        kind: "search",
        filters: {
          match: source.filters.match,
          rules: source.filters.rules.map((rule) => ({ ...rule })),
        },
      });
    }
  }
  return out.length > 0 ? out : [blankListSource()];
}

export function toApiSources(sources: DraftSource[]): Source[] {
  return sources.map((source): Source => {
    if (source.kind === "list") return { kind: "list", builder: source.builder, value: source.value, label: source.label };
    if (source.kind === "titles") return { kind: "titles", builder: source.builder, ids: source.ids, label: source.label };
    return {
      kind: "search",
      filters: {
        match: source.filters.match,
        rules: source.filters.rules.map((rule) => ({
          field: rule.field,
          modifier: rule.modifier,
          value: rule.value as string | number | boolean | string[],
        })),
      },
    };
  });
}

export function sourceReady(source: DraftSource): boolean {
  if (source.kind === "list") return Boolean(source.builder && source.value);
  if (source.kind === "titles") return source.ids.length > 0;
  return source.filters.rules.length > 0;
}

function draftLabel(source: DraftSource): string {
  if (source.kind === "list") return sourceLabel(source);
  if (source.kind === "titles") return sourceLabel(source);
  return "Plex search";
}

export function SourcesEditor({
  library,
  libraryType,
  fields,
  sources,
  onChange,
  onListPicked,
}: {
  library: string;
  libraryType: "movie" | "show";
  fields: BuilderField[];
  sources: DraftSource[];
  onChange: (next: DraftSource[]) => void;
  /** Fired when a list source is chosen, so the form can auto-fill the title. */
  onListPicked?: (label: string | null) => void;
}) {
  const [adding, setAdding] = useState(false);
  const hasSearch = sources.some((source) => source.kind === "search");
  const atLimit = sources.length >= MAX_SOURCES;

  const setAt = (index: number, next: DraftSource) => onChange(sources.map((source, i) => (i === index ? next : source)));
  const removeAt = (index: number) => onChange(sources.filter((_, i) => i !== index));

  const add = (kind: AddKind) => {
    if (atLimit) return;
    if (kind === "search" && hasSearch) return;
    const next =
      kind === "list" ? blankListSource() : kind === "titles" ? blankTitlesSource(libraryType) : blankSearchSource(fields);
    onChange([...sources, next]);
    setAdding(false);
  };

  return (
    <section className="flex flex-col gap-4" aria-labelledby="sources-heading">
      <h3 id="sources-heading" className="text-[15px] font-semibold">
        Sources
      </h3>
      <ul className="flex flex-col gap-4">
        {sources.map((source, index) => (
          <li
            key={source.uid}
            className="flex flex-col gap-3 rounded-control border border-border bg-surface-2 p-3"
            aria-label={`Source: ${draftLabel(source)}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">{draftLabel(source)}</p>
              <Button onClick={() => removeAt(index)} disabled={sources.length <= 1} aria-label={`Remove source ${index + 1}`}>
                Remove
              </Button>
            </div>
            {source.kind === "list" && (
              <ListSource
                library={library}
                value={source.builder && source.value ? { builder: source.builder, value: source.value, label: source.label } : null}
                onChange={(next: ListSourceValue) => {
                  setAt(index, { uid: source.uid, kind: "list", builder: next.builder, value: next.value, label: next.label });
                  onListPicked?.(next.label);
                }}
              />
            )}
            {source.kind === "titles" && (
              <TitlesSource
                libraryType={libraryType}
                builder={source.builder}
                ids={source.ids}
                onChange={(next) => setAt(index, { uid: source.uid, kind: "titles", ...next })}
              />
            )}
            {source.kind === "search" && (
              <FilterRules
                library={library}
                fields={fields}
                value={source.filters}
                matchName={`search-match-${index}`}
                onChange={(filters) => setAt(index, { uid: source.uid, kind: "search", filters })}
              />
            )}
          </li>
        ))}
      </ul>
      {!atLimit && (
        <div className="flex flex-col gap-2">
          {!adding ? (
            <Button onClick={() => setAdding(true)}>Add another source</Button>
          ) : (
            <fieldset className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <legend className="sr-only">Source kind to add</legend>
              <Button onClick={() => add("list")}>From a list</Button>
              <Button onClick={() => add("titles")}>Individual titles</Button>
              <Button onClick={() => add("search")} disabled={hasSearch} title={hasSearch ? "A collection takes one Plex search" : undefined}>
                Plex search
              </Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </fieldset>
          )}
        </div>
      )}
    </section>
  );
}
