// Create or edit a Studio smart collection: filter rules on the left, live Plex preview on the right.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api";
import {
  builderApi,
  isKometaPosterUrl,
  posterPreviewSrc,
  type BuilderField,
  type CollectionInput,
  type FilterRule,
  type FilterSpec,
  type Poster,
} from "../builderApi";
import { emptyValue, RuleValueInput, type DraftValue } from "../components/builder/RuleValueInput";
import { useHeaderTitle } from "../components/HeaderTitle";
import { LeaveGuard } from "../components/LeaveGuard";
import { PlexPoster, posterGrid } from "../components/PlexPoster";
import { Button, Checkbox, ConfirmButton, Field, StickyActions, inputClass } from "../components/ui";

type DraftRule = { field: string; modifier: string; value: DraftValue };
type Draft = {
  library: string;
  title: string;
  filters: { match: "all" | "any"; rules: DraftRule[] };
  sort_by: string | null;
  limit: number | null;
  visible: { library: boolean; home: boolean; shared: boolean };
  minimum_items: number;
  summary: string;
  sort_title: string;
  poster: Poster;
};

type PosterMode = "plex" | "upload" | "url" | "kometa";

function posterMode(poster: Poster, kometaUrl: string | null): PosterMode {
  if (!poster) return "plex";
  if (poster.kind === "file") return "upload";
  if (kometaUrl && poster.kind === "url" && poster.url === kometaUrl) return "kometa";
  if (poster.kind === "url" && isKometaPosterUrl(poster.url) && kometaUrl === poster.url) return "kometa";
  return "url";
}

function toInput(draft: Draft): CollectionInput {
  return {
    library: draft.library,
    title: draft.title.trim(),
    filters: {
      match: draft.filters.match,
      rules: draft.filters.rules.map((rule) => ({ field: rule.field, modifier: rule.modifier, value: rule.value as FilterRule["value"] })),
    },
    sort_by: draft.sort_by,
    limit: draft.limit,
    visible: draft.visible,
    minimum_items: draft.minimum_items,
    summary: draft.summary.trim() || null,
    sort_title: draft.sort_title.trim() || null,
    poster: draft.poster,
  };
}

function fromInput(input: CollectionInput): Draft {
  return {
    library: input.library,
    title: input.title,
    filters: {
      match: input.filters.match,
      rules: input.filters.rules.map((rule) => ({ ...rule })),
    },
    sort_by: input.sort_by,
    limit: input.limit,
    visible: { ...input.visible },
    minimum_items: input.minimum_items,
    summary: input.summary ?? "",
    sort_title: input.sort_title ?? "",
    poster: input.poster ?? null,
  };
}

function blankDraft(library: string, fields: BuilderField[]): Draft {
  const field = fields[0];
  const rule: DraftRule = field
    ? { field: field.key, modifier: field.modifiers[0]?.key ?? "", value: emptyValue(field) }
    : { field: "", modifier: "", value: "" };
  return {
    library,
    title: "",
    filters: { match: "all", rules: [rule] },
    sort_by: null,
    limit: null,
    visible: { library: true, home: false, shared: false },
    minimum_items: 1,
    summary: "",
    sort_title: "",
    poster: null,
  };
}

function fieldByKey(fields: BuilderField[], key: string): BuilderField | undefined {
  return fields.find((field) => field.key === key);
}

function groupFields(fields: BuilderField[]): { group: string; fields: BuilderField[] }[] {
  const order: string[] = [];
  const map = new Map<string, BuilderField[]>();
  for (const field of fields) {
    if (!map.has(field.group)) {
      order.push(field.group);
      map.set(field.group, []);
    }
    map.get(field.group)!.push(field);
  }
  return order.map((group) => ({ group, fields: map.get(group)! }));
}

function saveProblems(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const detail = error.detail;
  if (detail && typeof detail === "object" && "problems" in detail && Array.isArray((detail as { problems: unknown }).problems)) {
    return (detail as { problems: string[] }).problems.map(String);
  }
  return [];
}

function RuleRow({
  library,
  fields,
  rule,
  onChange,
  onRemove,
  canRemove,
}: {
  library: string;
  fields: BuilderField[];
  rule: DraftRule;
  onChange: (rule: DraftRule) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const field = fieldByKey(fields, rule.field) ?? fields[0];
  const groups = groupFields(fields);
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border bg-surface-2 p-3" role="group" aria-label="Filter rule">
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Field</span>
          <select
            className={inputClass}
            value={field?.key ?? ""}
            onChange={(event) => {
              const next = fieldByKey(fields, event.target.value);
              if (!next) return;
              onChange({ field: next.key, modifier: next.modifiers[0]?.key ?? "", value: emptyValue(next) });
            }}
            aria-label="Field"
          >
            {groups.map((group) => (
              <optgroup key={group.group} label={group.group}>
                {group.fields.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Modifier</span>
          <select
            className={inputClass}
            value={rule.modifier}
            onChange={(event) => onChange({ ...rule, modifier: event.target.value })}
            aria-label="Modifier"
          >
            {(field?.modifiers ?? []).map((modifier) => (
              <option key={modifier.key || "is"} value={modifier.key}>
                {modifier.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button onClick={onRemove} disabled={!canRemove} aria-label="Remove rule">
            Remove
          </Button>
        </div>
      </div>
      {field && <RuleValueInput library={library} field={field} value={rule.value} onChange={(value) => onChange({ ...rule, value })} />}
    </div>
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
}: {
  id: number | null;
  library: string;
  fields: { fields: BuilderField[]; sorts: { key: string; label: string }[] };
  baseline: Draft;
  templateError: string | null;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const released = useRef(false);
  const [draft, setDraft] = useState(baseline);
  const [baselineSnap] = useState(baseline);
  const dirty = JSON.stringify(toInput(draft)) !== JSON.stringify(toInput(baselineSnap));
  const kometaUrl =
    baselineSnap.poster?.kind === "url" && isKometaPosterUrl(baselineSnap.poster.url) ? baselineSnap.poster.url : null;

  const [previewArgs, setPreviewArgs] = useState<{ filters: FilterSpec; sort_by: string | null } | null>(null);
  useEffect(() => {
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
  }, [draft.filters, draft.sort_by]);

  const preview = useQuery({
    queryKey: ["builder", "preview", library, previewArgs],
    queryFn: () => builderApi.preview({ library, filters: previewArgs!.filters, sort_by: previewArgs!.sort_by }),
    enabled: previewArgs !== null,
    placeholderData: keepPreviousData,
  });

  useHeaderTitle(draft.title.trim() || (id === null ? "New collection" : "Collection"));

  const save = useMutation({
    mutationFn: () => {
      const body = toInput(draft);
      return id === null ? builderApi.create(body) : builderApi.update(id, body);
    },
    onSuccess: (saved) => {
      released.current = true;
      queryClient.invalidateQueries({ queryKey: ["collections"] });
      navigate(`/collections?library=${encodeURIComponent(saved.library)}`);
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
  const conflict = save.error instanceof ApiError && save.error.status === 409 ? save.error.message : null;
  const removeNotice = remove.error instanceof ApiError ? remove.error.message : null;

  const setRule = (index: number, rule: DraftRule) =>
    setDraft((current) => ({
      ...current,
      filters: { ...current.filters, rules: current.filters.rules.map((entry, i) => (i === index ? rule : entry)) },
    }));

  const addRule = () => {
    const field = fields.fields[0];
    if (!field) return;
    setDraft((current) => ({
      ...current,
      filters: {
        ...current.filters,
        rules: [...current.filters.rules, { field: field.key, modifier: field.modifiers[0]?.key ?? "", value: emptyValue(field) }],
      },
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

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-3" aria-labelledby="name-heading">
            <h3 id="name-heading" className="text-[15px] font-semibold">
              Name
            </h3>
            <Field label="Title">
              <input className={inputClass} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required aria-label="Title" />
            </Field>
          </section>

          <section className="flex flex-col gap-3" aria-labelledby="filters-heading">
            <h3 id="filters-heading" className="text-[15px] font-semibold">
              Filters
            </h3>
            <fieldset className="flex flex-wrap gap-4">
              <legend className="sr-only">Match rules</legend>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="match"
                  className="size-4 accent-accent"
                  checked={draft.filters.match === "all"}
                  onChange={() => setDraft({ ...draft, filters: { ...draft.filters, match: "all" } })}
                />
                Match all of these rules
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="match"
                  className="size-4 accent-accent"
                  checked={draft.filters.match === "any"}
                  onChange={() => setDraft({ ...draft, filters: { ...draft.filters, match: "any" } })}
                />
                Match any of these rules
              </label>
            </fieldset>
            <div className="flex flex-col gap-3">
              {draft.filters.rules.map((rule, index) => (
                <RuleRow
                  key={index}
                  library={library}
                  fields={fields.fields}
                  rule={rule}
                  onChange={(next) => setRule(index, next)}
                  onRemove={() =>
                    setDraft((current) => ({
                      ...current,
                      filters: { ...current.filters, rules: current.filters.rules.filter((_, i) => i !== index) },
                    }))
                  }
                  canRemove={draft.filters.rules.length > 1}
                />
              ))}
            </div>
            <Button onClick={addRule} disabled={fields.fields.length === 0}>
              Add rule
            </Button>
          </section>

          <section className="flex flex-col gap-3" aria-labelledby="sort-heading">
            <h3 id="sort-heading" className="text-[15px] font-semibold">
              Sort and size
            </h3>
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
            <Checkbox checked={draft.visible.library} onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, library: checked } })}>
              Library recommended
            </Checkbox>
            <Checkbox checked={draft.visible.home} onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, home: checked } })}>
              My home
            </Checkbox>
            <Checkbox checked={draft.visible.shared} onChange={(checked) => setDraft({ ...draft, visible: { ...draft.visible, shared: checked } })}>
              Friends' home
            </Checkbox>
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
        </div>

        <section className="rounded-card border border-border bg-surface p-4 lg:sticky lg:top-4" aria-labelledby="preview-heading">
          <h3 id="preview-heading" className="mb-3 text-[15px] font-semibold">
            Preview
          </h3>
          <PreviewPane preview={preview.data} updating={preview.isFetching} />
        </section>
      </div>

      {(problems.length > 0 || conflict || removeNotice) && (
        <div role="alert" className="flex flex-col gap-1 text-sm text-err">
          {conflict && <p>{conflict}</p>}
          {removeNotice && <p>{removeNotice}</p>}
          {problems.map((problem) => (
            <p key={problem}>{problem}</p>
          ))}
        </div>
      )}

      <StickyActions>
        <Button variant="primary" onClick={() => save.mutate()} disabled={!draft.title.trim() || save.isPending}>
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

  return (
    <BuilderForm
      key={JSON.stringify(baseline)}
      id={null}
      library={library}
      fields={fieldData.data}
      baseline={baseline}
      templateError={templateError}
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

  return (
    <BuilderForm
      key={collection.data.id}
      id={collection.data.id}
      library={collection.data.library}
      fields={fieldData.data}
      baseline={fromInput(collection.data)}
      templateError={null}
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
