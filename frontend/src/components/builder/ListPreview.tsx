// In-library / missing poster grids for a list source, or the why when Studio can't preview yet.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { builderApi, type SourcePreview } from "../../builderApi";
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

  if (!preview.previewable) {
    return (
      <div className="flex flex-col gap-2">
        {updating && <p className="text-sm text-muted">Updating…</p>}
        <p className="text-sm text-muted">{preview.why ?? "This list can't be previewed yet."}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {updating && <p className="text-sm text-muted">Updating…</p>}
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

export function ListPreview({
  library,
  builder,
  value,
}: {
  library: string;
  builder: string;
  value: string;
}) {
  const preview = useQuery({
    queryKey: ["builder", "sources", "preview", library, builder, value],
    queryFn: () => builderApi.previewSource({ library, source: { builder, value } }),
    enabled: Boolean(builder && value),
    placeholderData: keepPreviousData,
  });

  if (!builder || !value) {
    return <p className="text-sm text-muted">Pick a list to preview.</p>;
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
