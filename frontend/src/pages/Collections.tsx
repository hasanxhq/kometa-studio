// Studio-built smart collections for one library.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { ApiError, api } from "../api";
import { builderApi, sourceLabel, sourcesOf, type BuiltCollection } from "../builderApi";
import { DownloadMissingBadge, RequestCountsLine, RequestWaitingButton } from "../components/RequestCounts";
import { PlexPoster } from "../components/PlexPoster";
import { RetryButton } from "../components/RetryButton";

function statusLine(collection: BuiltCollection): { text: string; tone: "muted" | "err" } {
  switch (collection.state) {
    case "queued":
      return { text: "Queued", tone: "muted" };
    case "building":
      return { text: "Building…", tone: "muted" };
    case "in_plex":
      return {
        text: collection.plex_items != null ? `In Plex · ${collection.plex_items} titles` : "In Plex",
        tone: "muted",
      };
    case "failed":
      return { text: collection.last_error ? `Failed: ${collection.last_error}` : "Failed", tone: "err" };
    case "missing":
    default:
      return { text: "Not built yet", tone: "muted" };
  }
}

function sourceLine(collection: BuiltCollection): string {
  const sources = sourcesOf(collection);
  if (sources.length > 1) return `${sources.length} sources`;
  return sourceLabel(sources[0] ?? { kind: "filters" });
}

function CollectionCard({ collection }: { collection: BuiltCollection }) {
  const status = statusLine(collection);
  const queryClient = useQueryClient();
  const waiting = collection.requests?.waiting ?? 0;
  return (
    <li aria-label={collection.title} className="relative flex flex-col overflow-hidden rounded-card border border-border bg-surface">
      <Link to={`/collections/${collection.id}`} className="flex min-h-11 grow flex-col text-left hover:bg-surface-2/40">
        {collection.thumb ? (
          <PlexPoster thumb={collection.thumb} title={collection.title} />
        ) : (
          <span aria-hidden="true" className="flex aspect-[2/3] items-end overflow-hidden bg-banner-studio p-3 font-display text-base leading-snug font-semibold">
            {collection.title}
          </span>
        )}
        <span className="px-3.5 pt-3 font-display text-base leading-snug font-semibold">{collection.title}</span>
        <span className="px-3.5 pt-1 text-[13px] text-muted">{sourceLine(collection)}</span>
        <span className={`px-3.5 pt-1 pb-3.5 text-[13px] ${status.tone === "err" ? "text-err" : "text-muted"}`}>{status.text}</span>
      </Link>
      {(collection.download_missing || collection.requests || collection.state === "failed" || waiting > 0) && (
        <div className="flex flex-col gap-2 px-3.5 pb-3.5">
          <DownloadMissingBadge id={collection.id} downloadMissing={collection.download_missing} library={collection.library} />
          <RequestCountsLine summary={collection.requests} />
          {collection.state === "failed" && (
            <RetryButton
              title={collection.title}
              run={async () => {
                await builderApi.retry(collection.id);
                return null;
              }}
              onDone={() => queryClient.invalidateQueries({ queryKey: ["collections", collection.library] })}
            />
          )}
          <RequestWaitingButton id={collection.id} waiting={waiting} library={collection.library} />
        </div>
      )}
    </li>
  );
}

export function Collections() {
  const [params, setParams] = useSearchParams();
  const kept = params.get("kept");
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const names = overview.data?.libraries.map((library) => library.name) ?? [];
  const asked = params.get("library");
  const library = asked && names.includes(asked) ? asked : (names[0] ?? null);

  const data = useQuery({
    queryKey: ["collections", library],
    queryFn: () => builderApi.list(library!),
    enabled: library !== null,
    refetchInterval: (query) => {
      const collections = query.state.data?.collections ?? [];
      return collections.some((entry) => entry.state === "queued" || entry.state === "building") ? 3000 : false;
    },
  });

  if (overview.isPending) return <p className="text-muted">Loading…</p>;
  if (overview.isError) {
    return (
      <p role="alert" className="text-err">
        {overview.error instanceof ApiError ? overview.error.message : "Can't read the config"}
      </p>
    );
  }
  if (library === null) {
    return (
      <p className="text-muted">
        Collections are per library, and config.yml has none yet.{" "}
        <Link className="underline hover:text-text" to="/libraries">
          Add one from Libraries
        </Link>
        .
      </p>
    );
  }

  const collections = data.data?.collections ?? [];

  return (
    <div className="flex max-w-[1400px] flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[32px] leading-tight font-semibold">Collections</h2>
          <p className="mt-1 max-w-xl text-[13px] text-muted">Smart collections you build from your library&apos;s own data. Plex keeps them up to date.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-[13px] text-muted">
            Apply to
            <select
              className="min-h-11 rounded-control border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent focus:outline-none"
              value={library}
              onChange={(event) => setParams({ library: event.target.value }, { replace: true })}
            >
              {names.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
          <Link
            to={`/collections/new?library=${encodeURIComponent(library)}`}
            className="inline-flex min-h-11 items-center justify-center rounded-control bg-accent px-4 text-sm font-medium text-on-accent transition hover:brightness-110"
          >
            New collection
          </Link>
        </div>
      </header>

      {kept && (
        <p role="status" className="rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-muted">
          {kept}
        </p>
      )}

      {data.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : data.isError ? (
        <p role="alert" className="text-err">
          {data.error.message}
        </p>
      ) : collections.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-card border border-dashed border-border px-4 py-10">
          <p className="text-muted">No collections yet in {library}.</p>
          <Link
            to={`/collections/new?library=${encodeURIComponent(library)}`}
            className="inline-flex min-h-11 items-center justify-center rounded-control bg-accent px-4 text-sm font-medium text-on-accent transition hover:brightness-110"
          >
            New collection
          </Link>
        </div>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(9rem,1fr))]" aria-label="Collections">
          {collections.map((collection) => (
            <CollectionCard key={collection.id} collection={collection} />
          ))}
        </ul>
      )}
    </div>
  );
}
