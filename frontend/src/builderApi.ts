// Collection builder API: fields, live preview, and Studio-built collections.

import { ApiError, SIGNED_OUT_EVENT, request } from "./api";
import { urlBase } from "./base";
import type { RequestSummary } from "./requestsApi";

export type { RequestSummary };

export type FilterRule = { field: string; modifier: string; value: string | number | boolean | string[] };
export type FilterSpec = { match: "all" | "any"; rules: FilterRule[] };

export type Source =
  | { kind: "filters" }
  | { kind: "list"; builder: string; value: string; label: string | null }
  | { kind: "titles"; builder: "tmdb_movie" | "tmdb_show" | "tvdb_show" | "imdb_id"; ids: string[]; label: string | null }
  | { kind: "search"; filters: FilterSpec };

export type TitleBuilder = Extract<Source, { kind: "titles" }>["builder"];

export type SourceKind = {
  builder: string;
  label: string;
  group: "TMDb" | "IMDb" | "Letterboxd" | "MDBList";
  input: "search" | "link" | "choice" | "count";
  placeholder: string | null;
  choices: { value: string; label: string }[] | null;
  previewable: boolean;
  available: boolean;
  why: string | null;
};

export type SourceSearchResult = { value: string; title: string; year: number | null; poster: string | null };

export type SkippedSource = { label: string; why: string };

export type SourcePreview = {
  previewable: boolean;
  why: string | null;
  total: number | null;
  in_library: { rating_key: string; title: string; year: number | null; thumb: string | null }[];
  in_library_count: number;
  missing: { id: string; title: string; year: number | null; poster: string | null }[];
  missing_count: number;
  problems: string[];
  skipped?: SkippedSource[];
};

export type Poster =
  | null
  | { kind: "file"; path: string }
  | { kind: "url"; url: string };

export type BuilderField = {
  key: string;
  label: string;
  kind: "tag" | "string" | "number" | "float" | "date" | "boolean" | "year";
  modifiers: { key: string; label: string }[];
  group: string;
  listable: boolean;
};

export type BuilderFields = {
  library: string;
  library_type: "movie" | "show";
  fields: BuilderField[];
  sorts: { key: string; label: string }[];
};

export type BuilderValues = { values: { key: string; title: string }[] };

export type BuilderPreview = {
  count: number;
  items: { rating_key: string; title: string; year: number | null; thumb: string | null }[];
  problems: string[];
};

export type VisibleFlags = { library: boolean | null; home: boolean | null; shared: boolean | null };

export type CollectionInput = {
  library: string;
  title: string;
  /** Prefer ``sources``; old responses may only send ``source`` (the first). */
  source?: Source;
  sources?: Source[];
  filters: FilterSpec;
  sort_by: string | null;
  limit: number | null;
  visible: VisibleFlags;
  minimum_items: number;
  summary: string | null;
  sort_title: string | null;
  poster: Poster;
  download_missing: boolean;
  request_cap: number | null;
  /** Radarr/Sonarr quality profile for this collection's requests; null uses the default in Settings → Requests. */
  request_profile: string | null;
};

export type CollectionSaveBody = CollectionInput & { confirm_requests?: boolean };

export type BuiltCollection = CollectionInput & {
  id: number;
  state: "queued" | "building" | "in_plex" | "failed" | "missing";
  plex_items: number | null;
  thumb: string | null;
  last_built_at: string | null;
  last_error: string | null;
  run_id: number | null;
  requests: RequestSummary;
};

/** A collection's sources: ``sources`` when present, else the one ``source`` (old responses). */
export function sourcesOf(input: { sources?: Source[] | null; source?: Source | null }): Source[] {
  if (input.sources && input.sources.length > 0) return input.sources;
  return [input.source ?? { kind: "filters" }];
}

export function sourceLabel(source: Source): string {
  if (source.kind === "filters") return "Smart filter";
  if (source.kind === "list") return source.label?.trim() || source.builder || "List";
  if (source.kind === "titles") {
    if (source.label?.trim()) return source.label.trim();
    const names: Record<TitleBuilder, string> = {
      tmdb_movie: "TMDb movie",
      tmdb_show: "TMDb show",
      tvdb_show: "TVDb show",
      imdb_id: "IMDb title",
    };
    const n = source.ids?.length ?? 0;
    return n > 0 ? `${names[source.builder]} · ${n}` : names[source.builder];
  }
  return "Plex search";
}

/** True when Download missing can apply (a list or titles source). */
export function hasMissingSources(sources: Source[]): boolean {
  return sources.some((source) => source.kind === "list" || source.kind === "titles");
}

/** True when at least one list/titles source is filled in enough to request missing titles. */
export function canDownloadMissing(sources: Source[]): boolean {
  return sources.some(
    (source) =>
      (source.kind === "list" && Boolean(source.builder && source.value)) || (source.kind === "titles" && source.ids.length > 0),
  );
}

export function isKometaPosterUrl(url: string): boolean {
  return url.includes("raw.githubusercontent.com/Kometa-Team/");
}

export function posterPreviewSrc(poster: Poster): string | null {
  if (!poster) return null;
  if (poster.kind === "url") return poster.url;
  const name = poster.path.split("/").pop();
  return name ? `${urlBase}/api/v1/builder/posters/${encodeURIComponent(name)}` : null;
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // not JSON
  }
  let message = `${response.status} ${response.statusText}`;
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail)) message = detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
  else if (detail && typeof detail === "object" && "message" in detail) message = String((detail as { message: unknown }).message);
  return new ApiError(response.status, message, detail);
}

export const builderApi = {
  fields: (library: string) => request<BuilderFields>("GET", `/builder/fields?library=${encodeURIComponent(library)}`),
  values: (library: string, field: string) =>
    request<BuilderValues>("GET", `/builder/values?library=${encodeURIComponent(library)}&field=${encodeURIComponent(field)}`),
  preview: (body: { library: string; filters: FilterSpec; sort_by: string | null }) => request<BuilderPreview>("POST", "/builder/preview", body),
  sources: (library: string) => request<{ sources: SourceKind[] }>("GET", `/builder/sources?library=${encodeURIComponent(library)}`),
  sourceFromLink: (body: { library: string; url: string }) =>
    request<{ builder: string; value: string; label: string | null }>("POST", "/builder/sources/link", body),
  searchSource: (library: string, builder: string, q: string) =>
    request<{ results: SourceSearchResult[] }>(
      "GET",
      `/builder/sources/search?library=${encodeURIComponent(library)}&builder=${encodeURIComponent(builder)}&q=${encodeURIComponent(q)}`,
    ),
  previewSource: (body: { library: string; sources: Source[] } | { library: string; source: { builder: string; value: string } }) =>
    request<SourcePreview>("POST", "/builder/sources/preview", body),
  /** What one Ready-made collection would hold before it's built (a Plex filter run, or its chart's list). */
  readyMadePreview: (library: string, category: string, block: string, key: string) =>
    request<SourcePreview>(
      "GET",
      `/ready-made/libraries/${encodeURIComponent(library)}/categories/${encodeURIComponent(category)}/preview?${new URLSearchParams({ block, key })}`,
    ),
  list: (library: string) => request<{ collections: BuiltCollection[] }>("GET", `/collections?library=${encodeURIComponent(library)}`),
  get: (id: number) => request<BuiltCollection>("GET", `/collections/${id}`),
  create: (body: CollectionSaveBody) => request<BuiltCollection>("POST", "/collections", body),
  update: (id: number, body: CollectionSaveBody) => request<BuiltCollection>("PUT", `/collections/${id}`, body),
  retry: (id: number) => request<BuiltCollection>("POST", `/collections/${id}/retry`),
  remove: (id: number) => request<{ removed: boolean; reason: string | null }>("DELETE", `/collections/${id}`),
  customise: (library: string, category: string, block: string, key: string) => {
    const q = new URLSearchParams({ block, key });
    return request<CollectionInput>("GET", `/ready-made/libraries/${encodeURIComponent(library)}/categories/${encodeURIComponent(category)}/customise?${q}`);
  },
  /** Upload a poster: the image is the request body (no multipart; python-multipart isn't a dependency). */
  uploadPoster: async (file: File): Promise<{ kind: "file"; path: string }> => {
    const response = await fetch(`${urlBase}/api/v1/builder/posters`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
      throw await errorFrom(response);
    }
    return response.json();
  },
};
