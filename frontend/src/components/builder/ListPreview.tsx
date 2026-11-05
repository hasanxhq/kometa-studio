// In-library / missing poster grids for list and titles sources, plus skipped sources Studio can't preview yet.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { builderApi, type Source, type SourcePreview } from "../../builderApi";
import { PlexPoster, posterGrid } from "../PlexPoster";

function MissingPoster({ poster, title }: { poster: string | null; title: string }) {
  return (
    <div className="aspect-[2/3] overflow-hidden rounded-control border border-border bg-surface-2">
      {poster ? (
        <img src={poster} alt="" loading="lazy" className="size-full object-cover" />
      ) : (
        <div className="flex size-full items-center justify-center p-2 text-center font-display text-sm text-muted">{title}</div>
      )}
    </div>
  );
}

function PreviewBody({ preview, updating }: { preview: SourcePreview; updating: boolean }) {
  const skipped = preview.skipped ?? [];

  if (preview.problems.length > 0) {
    return (
      <div className="flex flex-col gap-2">
        {updating && <p className="text-sm text-muted">Updating…</p>}
        <ul className="flex flex-col gap-1 text-sm text-muted" aria-label="Preview hints">
          {preview.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
        {skipped.length > 0 && <SkippedList skipped={skipped} />}
      </div>
    );
  }

  if (!preview.previewable) {
    return (
      <div className="flex flex-col gap-2">
        {updating && <p className="text-sm text-muted">Updating…</p>}
        <p className="text-sm text-muted">{preview.why ?? "This list can't be previewed yet."}</p>
        {skipped.length > 1 && <SkippedList skipped={skipped} />}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {updating && <p className="text-sm text-muted">Updating…</p>}
      {skipped.length > 0 && <SkippedList skipped={skipped} />}
      <section className="flex flex-col gap-3" aria-labelledby="in-library-heading">
        <h4 id="in-library-heading" className="text-[13px] font-semibold">
          In your library ({preview.in_library_count})
        </h4>
        {preview.in_library_count === 0 ? (
          <p className="text-sm text-muted">None in your library yet.</p>
        ) : (
          <ul className={posterGrid} aria-label="In your library">
            {preview.in_library.map((item) => (
              <li key={item.rating_key} className="flex flex-col gap-1">
                <PlexPoster thumb={item.thumb} title={item.title} />
                <span className="line-clamp-2 text-xs font-medium">{item.title}</span>
                {item.year != null && <span className="text-xs text-muted">{item.year}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="flex flex-col gap-3" aria-labelledby="missing-heading">
        <h4 id="missing-heading" className="text-[13px] font-semibold">
          Missing ({preview.missing_count})
        </h4>
        {preview.missing_count === 0 ? (
          <p className="text-sm text-muted">Nothing missing.</p>
        ) : (
          <ul className={posterGrid} aria-label="Missing">
            {preview.missing.map((item) => (
              <li key={item.id} className="flex flex-col gap-1">
                <MissingPoster poster={item.poster} title={item.title} />
                <span className="line-clamp-2 text-xs font-medium">{item.title}</span>
                {item.year != null && <span className="text-xs text-muted">{item.year}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function SkippedList({ skipped }: { skipped: { label: string; why: string }[] }) {
  return (
    <ul className="flex flex-col gap-1 text-sm text-muted" aria-label="Sources not in preview">
      {skipped.map((entry) => (
        <li key={`${entry.label}:${entry.why}`}>
          <span className="font-medium text-text">{entry.label}</span>
          {": "}
          {entry.why}
        </li>
      ))}
    </ul>
  );
}

/** Sources the preview endpoint can try to read (list + titles). Search/filters are skipped server-side. */
function previewableSources(sources: Source[]): Source[] {
  return sources.filter((source) => source.kind === "list" || source.kind === "titles" || source.kind === "search");
}

export function ListPreview({ library, sources }: { library: string; sources: Source[] }) {
  const ready = previewableSources(sources).filter((source) => {
    if (source.kind === "list") return Boolean(source.builder && source.value);
    if (source.kind === "titles") return source.ids.length > 0;
    return source.kind === "search";
  });
  const preview = useQuery({
    queryKey: ["builder", "sources", "preview", library, ready],
    queryFn: () => builderApi.previewSource({ library, sources: ready }),
    enabled: ready.length > 0,
    placeholderData: keepPreviousData,
  });

  if (ready.length === 0) {
    return <p className="text-sm text-muted">Add a list or titles to preview.</p>;
  }
  if (preview.isPending && !preview.data) {
    return <p className="text-sm text-muted">Loading preview…</p>;
  }
  if (preview.isError) {
    return (
      <p role="alert" className="text-sm text-err">
        {preview.error.message}
      </p>
    );
  }
  if (!preview.data) return <p className="text-sm text-muted">Loading preview…</p>;

  return <PreviewBody preview={preview.data} updating={preview.isFetching} />;
}
