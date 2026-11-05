// Create or edit a Studio smart collection: filter rules on the left, live Plex preview on the right.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api";
import {
  builderApi,
  canDownloadMissing,
  isKometaPosterUrl,
  posterPreviewSrc,
  sourcesOf,
  type BuilderField,
  type CollectionInput,
  type FilterRule,
  type FilterSpec,
  type Poster,
  type Source,
  type VisibleFlags,
} from "../builderApi";
import { blankRule, FilterRules, type DraftFilters } from "../components/builder/FilterRules";
import { ListPreview } from "../components/builder/ListPreview";
import { MissingTitles } from "../components/builder/MissingTitles";
import {
  blankListSource,
  draftSourcesFrom,
  sourceReady,
  SourcesEditor,
  toApiSources,
  type DraftSource,
} from "../components/builder/SourcesEditor";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useHeaderTitle } from "../components/HeaderTitle";
import { LeaveGuard } from "../components/LeaveGuard";
import { PlexPoster, posterGrid } from "../components/PlexPoster";
import { Button, ConfirmButton, Field, StickyActions, inputClass } from "../components/ui";
import { needsConfirm, type NeedsConfirm } from "../requestsApi";

type StartMode = "filters" | "list";
type Draft = {
  library: string;
  title: string;
  /** Smart-filter mode only; list mode uses ``sources``. */
  filters: DraftFilters;
  sources: DraftSource[];
  sort_by: string | null;
  limit: number | null;
  visible: VisibleFlags;
  minimum_items: number;
  summary: string;
  sort_title: string;
  poster: Poster;
  download_missing: boolean;
  request_cap: number | null;
  request_profile: string | null;
};

const EMPTY_FILTERS: FilterSpec = { match: "all", rules: [] };
const LIST_SORTS = [
  { key: "custom", label: "List order" },
  { key: "release", label: "Release date" },
  { key: "alpha", label: "Title" },
] as const;

type PosterMode = "plex" | "upload" | "url" | "kometa";

function posterMode(poster: Poster, kometaUrl: string | null): PosterMode {
  if (!poster) return "plex";
  if (poster.kind === "file") return "upload";
  if (kometaUrl && poster.kind === "url" && poster.url === kometaUrl) return "kometa";
  if (poster.kind === "url" && isKometaPosterUrl(poster.url) && kometaUrl === poster.url) return "kometa";
  return "url";
}

function toInput(draft: Draft, mode: StartMode): CollectionInput {
  const list = mode === "list";
  const sources: Source[] = list ? toApiSources(draft.sources) : [{ kind: "filters" }];
  const canMissing = list && canDownloadMissing(sources);
  return {
    library: draft.library,
    title: draft.title.trim(),
    source: sources[0],
    sources,
    filters: list
      ? EMPTY_FILTERS
      : {
          match: draft.filters.match,
          rules: draft.filters.rules.map((rule) => ({ field: rule.field, modifier: rule.modifier, value: rule.value as FilterRule["value"] })),
        },
    sort_by: draft.sort_by,
    limit: list ? null : draft.limit,
    visible: draft.visible,
    minimum_items: draft.minimum_items,
    summary: draft.summary.trim() || null,
    sort_title: draft.sort_title.trim() || null,
    poster: draft.poster,
    download_missing: canMissing ? draft.download_missing : false,
    request_cap: canMissing && draft.download_missing ? draft.request_cap : null,
    request_profile: canMissing && draft.download_missing ? draft.request_profile : null,
  };
}

function fromInput(input: CollectionInput): Draft {
  const loaded = sourcesOf(input);
  const listSources = loaded.filter((source) => source.kind !== "filters");
  return {
    library: input.library,
    title: input.title,
    filters: {
      match: input.filters.match,
      rules: input.filters.rules.map((rule) => ({ ...rule })),
    },
    sources: draftSourcesFrom(listSources.length > 0 ? listSources : loaded[0]?.kind === "filters" ? [] : loaded),
    sort_by: input.sort_by,
    limit: input.limit,
    visible: { ...input.visible },
    minimum_items: input.minimum_items,
    summary: input.summary ?? "",
    sort_title: input.sort_title ?? "",
    poster: input.poster ?? null,
    download_missing: input.download_missing ?? false,
    request_cap: input.request_cap ?? null,
    request_profile: input.request_profile ?? null,
  };
}

function blankDraft(library: string, fields: BuilderField[]): Draft {
  return {
    library,
    title: "",
    filters: { match: "all", rules: [blankRule(fields)] },
    sources: [blankListSource()],
    sort_by: null,
    limit: null,
    visible: { library: true, home: false, shared: false },
    minimum_items: 1,
    summary: "",
    sort_title: "",
    poster: null,
    download_missing: false,
    request_cap: null,
    request_profile: null,
  };
}

function canSave(draft: Draft, mode: StartMode): boolean {
  if (!draft.title.trim()) return false;
  if (mode === "list") return draft.sources.length > 0 && draft.sources.every(sourceReady);
  return true;
}

function startModeOf(input: CollectionInput): StartMode {
  const sources = sourcesOf(input);
  return sources.length === 1 && sources[0]?.kind === "filters" ? "filters" : "list";
}

function saveProblems(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const detail = error.detail;
  if (detail && typeof detail === "object" && "problems" in detail && Array.isArray((detail as { problems: unknown }).problems)) {
    return (detail as { problems: string[] }).problems.map(String);
  }
  return [];
}

/** Checkbox that keeps ``null`` ("Plex's setting") until the user toggles it. */
function VisibleCheck({
  checked,
  onChange,
  children,
}: {
  checked: boolean | null;
  onChange: (checked: boolean) => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = checked === null;
  }, [checked]);
  return (
    <label className="flex min-h-11 items-start gap-2 text-sm">
      <input
        ref={ref}
        type="checkbox"
        className="mt-1 size-4 shrink-0 accent-accent"
        checked={checked === true}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        {children}
        {checked === null && <span className="block text-xs text-muted">Plex&apos;s setting</span>}
      </span>
    </label>
  );
}

function PosterSection({
  poster,
  kometaUrl,
  onChange,
}: {
  poster: Poster;
  kometaUrl: string | null;
  onChange: (poster: Poster) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Local mode so "Upload an image" stays selected before a file is chosen (poster is still null).
  const [mode, setModeState] = useState<PosterMode>(() => posterMode(poster, kometaUrl));
  const preview = posterPreviewSrc(poster);

  const setMode = (next: PosterMode) => {
    setUploadError(null);
    setModeState(next);
    if (next === "plex") onChange(null);
    else if (next === "kometa" && kometaUrl) onChange({ kind: "url", url: kometaUrl });
    else if (next === "upload") {
      if (poster?.kind !== "file") onChange(null);
    } else if (next === "url") {
      onChange(poster?.kind === "url" && (!kometaUrl || poster.url !== kometaUrl) ? poster : { kind: "url", url: "" });
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      onChange(await builderApi.uploadPoster(file));
      setModeState("upload");
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="flex flex-col gap-3" aria-labelledby="poster-heading">
      <h3 id="poster-heading" className="text-[15px] font-semibold">
        Poster
      </h3>
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Poster source</legend>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" name="poster" className="size-4 accent-accent" checked={mode === "plex"} onChange={() => setMode("plex")} />
          Plex&apos;s own
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" name="poster" className="size-4 accent-accent" checked={mode === "upload"} onChange={() => setMode("upload")} />
          Upload an image
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" name="poster" className="size-4 accent-accent" checked={mode === "url"} onChange={() => setMode("url")} />
          Image link
        </label>
        {kometaUrl && (
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="radio" name="poster" className="size-4 accent-accent" checked={mode === "kometa"} onChange={() => setMode("kometa")} />
            Kometa&apos;s artwork
          </label>
        )}
      </fieldset>
      {mode === "upload" && (
        <Field label="Image file" hint="JPEG, PNG or WebP, up to 10 MB">
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
            className="min-h-11 text-sm file:mr-3 file:min-h-11 file:rounded-control file:border file:border-border-strong file:bg-surface-2 file:px-4 file:text-text"
            disabled={uploading}
            onChange={(event) => {
              void onFile(event.target.files?.[0]);
              event.target.value = "";
            }}
            aria-label="Upload poster"
          />
        </Field>
      )}
      {mode === "url" && (
        <Field label="Image URL">
          <input
            className={inputClass}
            type="url"
            value={poster?.kind === "url" ? poster.url : ""}
            onChange={(event) => onChange({ kind: "url", url: event.target.value })}
            placeholder="https://"
            aria-label="Poster URL"
          />
        </Field>
      )}
      {uploadError && (
        <p role="alert" className="text-sm text-err">
          {uploadError}
        </p>
      )}
      {uploading && <p className="text-sm text-muted">Uploading…</p>}
      <div className="w-28 overflow-hidden rounded-control border border-border bg-surface-2 aspect-[2/3]" aria-label="Poster preview">
        {preview ? (
          <img src={preview} alt="" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center p-2 text-center text-xs text-muted">
            {mode === "plex" ? "Plex mosaic" : "No image yet"}
          </div>
        )}
      </div>
    </section>
  );
}

function PreviewPane({
  preview,
  updating,
}: {
  preview: { count: number; items: { rating_key: string; title: string; year: number | null; thumb: string | null }[]; problems: string[] } | undefined;
  updating: boolean;
}) {
  if (!preview) {
    return <p className="text-sm text-muted">{updating ? "Updating…" : "Loading preview…"}</p>;
  }
  if (preview.problems.length > 0) {
    return (
      <div className="flex flex-col gap-2">
        {updating && <p className="text-sm text-muted">Updating…</p>}
        <ul className="flex flex-col gap-1 text-sm text-muted" aria-label="Preview hints">
          {preview.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        {preview.count} title{preview.count === 1 ? "" : "s"}
        {updating ? " · Updating…" : ""}
      </p>
      {preview.count === 0 ? (
        <p className="text-sm text-muted">No titles match yet.</p>
      ) : (
        <ul className={posterGrid} aria-label="Preview titles">
          {preview.items.slice(0, 30).map((item) => (
            <li key={item.rating_key} className="flex flex-col gap-1">
              <PlexPoster thumb={item.thumb} title={item.title} />
              <span className="line-clamp-2 text-xs font-medium">{item.title}</span>
              {item.year != null && <span className="text-xs text-muted">{item.year}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BuilderForm({
  id,
  library,
  fields,
  baseline,
  templateError,
  initialMode,
}: {
  id: number | null;
  library: string;
  fields: { fields: BuilderField[]; sorts: { key: string; label: string }[]; library_type?: "movie" | "show" };
  baseline: Draft;
  templateError: string | null;
  /** null = new collection waiting for the start choice */
  initialMode: StartMode | null;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const released = useRef(false);
  const [draft, setDraft] = useState(baseline);
  const [baselineSnap] = useState(baseline);
  const [mode, setMode] = useState<StartMode | null>(initialMode);
  const [autoTitle, setAutoTitle] = useState<string | null>(() => {
    const first = baseline.sources[0];
    return first?.kind === "list" ? first.label : null;
  });
  const [confirmMore, setConfirmMore] = useState<NeedsConfirm | null>(null);
  const dirty =
    mode !== null && JSON.stringify(toInput(draft, mode)) !== JSON.stringify(toInput(baselineSnap, initialMode ?? mode));
  const kometaUrl =
    baselineSnap.poster?.kind === "url" && isKometaPosterUrl(baselineSnap.poster.url) ? baselineSnap.poster.url : null;
  const isList = mode === "list";
  const apiSources = isList ? toApiSources(draft.sources) : [];

  const [previewArgs, setPreviewArgs] = useState<{ filters: FilterSpec; sort_by: string | null } | null>(null);
  useEffect(() => {
    if (mode !== "filters") {
      setPreviewArgs(null);
      return;
    }
    const handle = window.setTimeout(() => {
      setPreviewArgs({
        filters: {
          match: draft.filters.match,
          rules: draft.filters.rules.map((rule) => ({ field: rule.field, modifier: rule.modifier, value: rule.value as FilterRule["value"] })),
        },
        sort_by: draft.sort_by,
      });
    }, 500);
    return () => window.clearTimeout(handle);
  }, [mode, draft.filters, draft.sort_by]);

  const preview = useQuery({
    queryKey: ["builder", "preview", library, previewArgs],
    queryFn: () => builderApi.preview({ library, filters: previewArgs!.filters, sort_by: previewArgs!.sort_by }),
    enabled: mode === "filters" && previewArgs !== null,
    placeholderData: keepPreviousData,
  });

  useHeaderTitle(draft.title.trim() || (id === null ? "New collection" : "Collection"));

  const save = useMutation({
    mutationFn: async (confirm_requests: boolean) => {
      const body = { ...toInput(draft, mode!), confirm_requests };
      return id === null ? builderApi.create(body) : builderApi.update(id, body);
    },
    onSuccess: (saved) => {
      setConfirmMore(null);
      released.current = true;
      queryClient.invalidateQueries({ queryKey: ["collections"] });
      queryClient.invalidateQueries({ queryKey: ["requests"] });
      navigate(`/collections?library=${encodeURIComponent(saved.library)}`);
    },
    onError: (error) => {
      const confirm = needsConfirm(error);
      if (confirm) setConfirmMore(confirm);
    },
  });

  const remove = useMutation({
    mutationFn: () => builderApi.remove(id!),
    onSuccess: (result) => {
      released.current = true;
      queryClient.invalidateQueries({ queryKey: ["collections"] });
      const q = new URLSearchParams({ library });
      if (!result.removed && result.reason) q.set("kept", result.reason);
      navigate(`/collections?${q}`);
    },
  });

  const problems = saveProblems(save.error);
  const conflict =
    save.error instanceof ApiError && save.error.status === 409 && !needsConfirm(save.error) ? save.error.message : null;
  const removeNotice = remove.error instanceof ApiError ? remove.error.message : null;

  const switchMode = (next: StartMode) => {
    setMode(next);
    if (next === "filters") {
      setDraft((current) => {
        const blank = blankDraft(library, fields.fields);
        return {
          ...current,
          filters: current.filters.rules.length > 0 ? current.filters : blank.filters,
          sources: [blankListSource()],
          sort_by: null,
          limit: null,
          download_missing: false,
          request_cap: null,
          request_profile: null,
        };
      });
      return;
    }
    setDraft((current) => ({
      ...current,
      sources: current.sources.length > 0 ? current.sources : [blankListSource()],
      filters: { match: "all", rules: [] },
      sort_by: current.sort_by && LIST_SORTS.some((s) => s.key === current.sort_by) ? current.sort_by : "custom",
      limit: null,
    }));
  };

  return (
    <div className="flex max-w-[1400px] flex-col gap-5">
      <LeaveGuard dirty={dirty} released={released} />
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[13px] text-muted">
            <Link className="underline hover:text-text" to={`/collections?library=${encodeURIComponent(library)}`}>
              Collections
            </Link>
            {" · "}
            {library}
          </p>
          <h2 className="mt-1 text-[32px] leading-tight font-semibold">{id === null ? "New collection" : draft.title.trim() || "Collection"}</h2>
        </div>
      </header>

      {templateError && (
        <p role="status" className="rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-muted">
          {templateError}
        </p>
      )}

      <section className="flex flex-col gap-3" aria-labelledby="start-heading">
        <h3 id="start-heading" className="text-[15px] font-semibold">
          How to start
        </h3>
        <fieldset className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
          <legend className="sr-only">How to start</legend>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="radio"
              name="start"
              className="size-4 accent-accent"
              checked={mode === "filters"}
              onChange={() => switchMode("filters")}
            />
            Organise what I have
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="radio" name="start" className="size-4 accent-accent" checked={mode === "list"} onChange={() => switchMode("list")} />
            Get something new
          </label>
        </fieldset>
      </section>

      {mode !== null && (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
          <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-3" aria-labelledby="name-heading">
              <h3 id="name-heading" className="text-[15px] font-semibold">
                Name
              </h3>
              <Field label="Title">
                <input
                  className={inputClass}
                  value={draft.title}
                  onChange={(event) => {
                    setAutoTitle(null);
                    setDraft({ ...draft, title: event.target.value });
                  }}
                  required
                  aria-label="Title"
                />
              </Field>
            </section>

            {isList ? (
              <SourcesEditor
                library={library}
                libraryType={fields.library_type ?? "movie"}
                fields={fields.fields}
                sources={draft.sources}
                onChange={(sources) => setDraft({ ...draft, sources })}
                onListPicked={(label) => {
                  setDraft((current) => {
                    const title =
                      !current.title.trim() || (autoTitle !== null && current.title === autoTitle) ? (label ?? current.title) : current.title;
                    return { ...current, title };
                  });
                  if (label) setAutoTitle(label);
                }}
              />
            ) : (
              <section className="flex flex-col gap-3" aria-labelledby="filters-heading">
                <h3 id="filters-heading" className="text-[15px] font-semibold">
                  Filters
                </h3>
                <FilterRules
                  library={library}
                  fields={fields.fields}
                  value={draft.filters}
                  onChange={(filters) => setDraft({ ...draft, filters })}
                />
              </section>
            )}

            <section className="flex flex-col gap-3" aria-labelledby="sort-heading">
              <h3 id="sort-heading" className="text-[15px] font-semibold">
                {isList ? "Order and size" : "Sort and size"}
              </h3>
              {isList ? (
                <Field label="Order">
                  <select
                    className={inputClass}
                    value={draft.sort_by ?? "custom"}
                    onChange={(event) => setDraft({ ...draft, sort_by: event.target.value })}
                    aria-label="Order"
                  >
                    {LIST_SORTS.map((sort) => (
                      <option key={sort.key} value={sort.key}>
                        {sort.label}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <>
                  <Field label="Sort">
                    <select
                      className={inputClass}
                      value={draft.sort_by ?? ""}
                      onChange={(event) => setDraft({ ...draft, sort_by: event.target.value || null })}
                      aria-label="Sort"
                    >
                      <option value="">Kometa&apos;s default (random)</option>
                      {fields.sorts.map((sort) => (
                        <option key={sort.key} value={sort.key}>
                          {sort.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Limit">
                    <input
                      type="number"
                      min={1}
                      className={inputClass}
                      value={draft.limit ?? ""}
                      onChange={(event) => setDraft({ ...draft, limit: event.target.value === "" ? null : Number.parseInt(event.target.value, 10) })}
                      aria-label="Limit"
                    />
                  </Field>
                </>
              )}
              <Field label="Minimum titles" hint="Kometa doesn't make it with fewer">
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={draft.minimum_items}
                  onChange={(event) => setDraft({ ...draft, minimum_items: Number.parseInt(event.target.value || "1", 10) })}
                  aria-label="Minimum titles"
                />
              </Field>
            </section>

            <PosterSection poster={draft.poster} kometaUrl={kometaUrl} onChange={(poster) => setDraft({ ...draft, poster })} />

            <section className="flex flex-col gap-2" aria-labelledby="visible-heading">
              <h3 id="visible-heading" className="text-[15px] font-semibold">
                Where it shows
              </h3>
              <VisibleCheck
                checked={draft.visible.library}
                onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, library: checked } })}
              >
                Library recommended
              </VisibleCheck>
              <VisibleCheck checked={draft.visible.home} onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, home: checked } })}>
                My home
              </VisibleCheck>
              <VisibleCheck
                checked={draft.visible.shared}
                onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, shared: checked } })}
              >
                Friends' home
              </VisibleCheck>
            </section>

            <section className="flex flex-col gap-3" aria-labelledby="details-heading">
              <h3 id="details-heading" className="text-[15px] font-semibold">
                Details
              </h3>
              <Field label="Summary">
                <textarea className={`${inputClass} min-h-24 py-2`} value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} aria-label="Summary" />
              </Field>
              <Field label="Sort title">
                <input className={inputClass} value={draft.sort_title} onChange={(event) => setDraft({ ...draft, sort_title: event.target.value })} aria-label="Sort title" />
              </Field>
            </section>

            {isList && (
              <MissingTitles
                library={library}
                sources={apiSources}
                downloadMissing={draft.download_missing}
                requestCap={draft.request_cap}
                libraryType={fields.library_type ?? "movie"}
                requestProfile={draft.request_profile}
                onRequestProfile={(request_profile) => setDraft({ ...draft, request_profile })}
                onDownloadMissing={(download_missing) => setDraft({ ...draft, download_missing })}
                onRequestCap={(request_cap) => setDraft({ ...draft, request_cap })}
              />
            )}
          </div>

          <section className="rounded-card border border-border bg-surface p-4 lg:sticky lg:top-4" aria-labelledby="preview-heading">
            <h3 id="preview-heading" className="mb-3 text-[15px] font-semibold">
              Preview
            </h3>
            {isList ? <ListPreview library={library} sources={apiSources} /> : <PreviewPane preview={preview.data} updating={preview.isFetching} />}
          </section>
        </div>
      )}

      {(problems.length > 0 || conflict || removeNotice) && (
        <div role="alert" className="flex flex-col gap-1 text-sm text-err">
          {conflict && <p>{conflict}</p>}
          {removeNotice && <p>{removeNotice}</p>}
          {problems.map((problem) => (
            <p key={problem}>{problem}</p>
          ))}
        </div>
      )}

      {mode !== null && (
        <StickyActions>
          <Button variant="primary" onClick={() => save.mutate(false)} disabled={!canSave(draft, mode) || save.isPending}>
            {save.isPending ? "Saving…" : id === null ? "Create" : "Save"}
          </Button>
          {id !== null && (
            <ConfirmButton
              label="Delete"
              confirm="Delete"
              warning="Deletes it from Plex too. Only collections Studio made are ever deleted."
              onConfirm={() => remove.mutate()}
              busy={remove.isPending}
            />
          )}
        </StickyActions>
      )}

      {confirmMore && (
        <ConfirmDialog
          title="Request missing titles"
          confirm={`Request ${confirmMore.count}`}
          busy={save.isPending}
          onConfirm={() => save.mutate(true)}
          onCancel={() => {
            setConfirmMore(null);
            save.reset();
          }}
        >
          {confirmMore.message || `Request ${confirmMore.count} titles now?`}
        </ConfirmDialog>
      )}
    </div>
  );
}

function NewBuilder({ library }: { library: string }) {
  const [params] = useSearchParams();
  const category = params.get("category");
  const block = params.get("block");
  const key = params.get("key");
  const wantsTemplate = Boolean(category && block && key);

  const fieldData = useQuery({ queryKey: ["builder", "fields", library], queryFn: () => builderApi.fields(library) });
  const template = useQuery({
    queryKey: ["builder", "customise", library, category, block, key],
    queryFn: () => builderApi.customise(library, category!, block!, key!),
    enabled: wantsTemplate,
    retry: false,
  });

  const ready = fieldData.isSuccess && (!wantsTemplate || template.isFetched);
  const templateError = template.isError ? (template.error instanceof ApiError ? template.error.message : "That ready-made can't be used as filters.") : null;

  const baseline = useMemo(() => {
    if (!fieldData.data) return null;
    if (template.data) return fromInput(template.data);
    return blankDraft(library, fieldData.data.fields);
  }, [fieldData.data, template.data, library]);

  if (fieldData.isPending || (wantsTemplate && template.isPending)) return <p className="text-muted">Loading…</p>;
  if (fieldData.isError) {
    return (
      <p role="alert" className="text-err">
        {fieldData.error.message}
      </p>
    );
  }
  if (!ready || !baseline || !fieldData.data) return <p className="text-muted">Loading…</p>;

  // Templates open as filters; a plain new collection waits for the start choice.
  const initialMode: StartMode | null = wantsTemplate || template.data ? "filters" : null;

  return (
    <BuilderForm
      key={JSON.stringify(baseline)}
      id={null}
      library={library}
      fields={fieldData.data}
      baseline={baseline}
      templateError={templateError}
      initialMode={initialMode}
    />
  );
}

function EditBuilder({ id }: { id: number }) {
  const collection = useQuery({ queryKey: ["collections", id], queryFn: () => builderApi.get(id) });
  const library = collection.data?.library;
  const fieldData = useQuery({
    queryKey: ["builder", "fields", library],
    queryFn: () => builderApi.fields(library!),
    enabled: Boolean(library),
  });

  if (collection.isPending || (library && fieldData.isPending)) return <p className="text-muted">Loading…</p>;
  if (collection.isError) {
    return (
      <p role="alert" className="text-err">
        {collection.error.message}
      </p>
    );
  }
  if (fieldData.isError) {
    return (
      <p role="alert" className="text-err">
        {fieldData.error.message}
      </p>
    );
  }
  if (!collection.data || !fieldData.data) return <p className="text-muted">Loading…</p>;

  const baseline = fromInput(collection.data);
  return (
    <BuilderForm
      key={collection.data.id}
      id={collection.data.id}
      library={collection.data.library}
      fields={fieldData.data}
      baseline={baseline}
      templateError={null}
      initialMode={startModeOf(collection.data)}
    />
  );
}

export function CollectionBuilder() {
  const { id: rawId } = useParams();
  const [params] = useSearchParams();
  const id = rawId ? Number.parseInt(rawId, 10) : null;
  const editing = rawId !== undefined && !Number.isNaN(id);

  if (editing) return <EditBuilder id={id!} />;

  const library = params.get("library");
  if (!library) {
    return (
      <p className="text-muted">
        Pick a library first.{" "}
        <Link className="underline" to="/collections">
          Back to Collections
        </Link>
      </p>
    );
  }
  return <NewBuilder library={library} />;
}
