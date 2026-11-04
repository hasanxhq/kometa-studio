// Collection builder API: fields, live preview, and Studio-built collections.

import { request } from "./api";

export type FilterRule = { field: string; modifier: string; value: string | number | boolean | string[] };
export type FilterSpec = { match: "all" | "any"; rules: FilterRule[] };

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

export type CollectionInput = {
  library: string;
  title: string;
  filters: FilterSpec;
  sort_by: string | null;
  limit: number | null;
  visible: { library: boolean; home: boolean; shared: boolean };
  minimum_items: number;
  summary: string | null;
  sort_title: string | null;
};

export type BuiltCollection = CollectionInput & {
  id: number;
  state: "queued" | "building" | "in_plex" | "failed" | "missing";
  plex_items: number | null;
  thumb: string | null;
  last_built_at: string | null;
  last_error: string | null;
  run_id: number | null;
};

export const builderApi = {
  fields: (library: string) => request<BuilderFields>("GET", `/builder/fields?library=${encodeURIComponent(library)}`),
  values: (library: string, field: string) =>
    request<BuilderValues>("GET", `/builder/values?library=${encodeURIComponent(library)}&field=${encodeURIComponent(field)}`),
  preview: (body: { library: string; filters: FilterSpec; sort_by: string | null }) => request<BuilderPreview>("POST", "/builder/preview", body),
  list: (library: string) => request<{ collections: BuiltCollection[] }>("GET", `/collections?library=${encodeURIComponent(library)}`),
  get: (id: number) => request<BuiltCollection>("GET", `/collections/${id}`),
  create: (body: CollectionInput) => request<BuiltCollection>("POST", "/collections", body),
  update: (id: number, body: CollectionInput) => request<BuiltCollection>("PUT", `/collections/${id}`, body),
  remove: (id: number) => request<{ removed: boolean; reason: string | null }>("DELETE", `/collections/${id}`),
  customise: (library: string, category: string, block: string, key: string) => {
    const q = new URLSearchParams({ block, key });
    return request<CollectionInput>("GET", `/ready-made/libraries/${encodeURIComponent(library)}/categories/${encodeURIComponent(category)}/customise?${q}`);
  },
};
