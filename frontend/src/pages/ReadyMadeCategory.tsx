// One Ready-made category: poster grid of its collections. A tile's tick picks it (Save keeps picks in the bar);
// the tile itself opens a preview of what it would hold.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, type ReadyMadeBuildResult, type ReadyMadeEntry } from "../api";
import { useLibrary } from "../library";
import { BuildBar } from "../components/BuildBar";
import { useHeaderTitle } from "../components/HeaderTitle";
import { DownloadMissingBadge, RequestCountsLine, RequestWaitingButton } from "../components/RequestCounts";
import { PlexPoster } from "../components/PlexPoster";
import { ReadyMadePreview } from "../components/ReadyMadePreview";
import { PosterTile, StatusBadge, badgeFor } from "../components/PosterTile";
import { RetryButton } from "../components/RetryButton";
import { Button } from "../components/ui";
import { categoryOf } from "../defaults";
import { isSelected, useReadyMadePicks } from "../readyMadePicks";

/** Caption line for the preview panel only (not the tile badge). */
function previewStatusCaption(entry: ReadyMadeEntry, selected: boolean, wasBuilt: boolean): string {
  if (wasBuilt && !selected) return "Will be removed";
  switch (entry.state) {
    case "queued":
      return "Queued";
    case "building":
      return "Building…";
    case "in_plex":
      return entry.plex_items != null ? `In Plex · ${entry.plex_items} titles` : "In Plex";
    case "missing":
      return "Not built yet";
    case "failed":
      return "Failed";
    case "removing":
      return "Removing…";
    default:
      return selected ? "Selected" : "Not picked";
  }
}

function readyMadeTileBadge(entry: ReadyMadeEntry, selected: boolean, wasBuilt: boolean): ReactNode {
  const state = wasBuilt && !selected ? ({ kind: "will_remove" } as const) : badgeFor(entry);
  return state && <StatusBadge state={state} />;
}

/** The tile's art: Plex's poster once built, else the one Kometa will apply, else the colour banner. */
function TileArt({ entry, banner }: { entry: ReadyMadeEntry; banner: string }) {
  const [failed, setFailed] = useState(false);
  if (entry.thumb) return <PlexPoster thumb={entry.thumb} title={entry.title} />;
  if (entry.poster && !failed) {
    return (
      <div className="aspect-[2/3] overflow-hidden rounded-control border border-border bg-surface-2">
        <img
          src={api.readyMade.posterUrl(entry.poster)}
          alt=""
          loading="lazy"
          className="size-full object-cover"
          onError={() => setFailed(true)}
        />
      </div>
    );
  }
  return (
    <div className={`flex aspect-[2/3] items-end overflow-hidden rounded-control border border-border p-2 font-display text-sm font-semibold ${banner}`}>
      {entry.title}
    </div>
  );
}

function CollectionTile({
  entry,
  banner,
  selected,
  onToggle,
  onOpen,
  customise,
  retry,
  library,
}: {
  entry: ReadyMadeEntry;
  banner: string;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
  customise?: string;
  retry?: { run: () => Promise<string | null>; onDone: () => void };
  library: string;
}) {
  const wasBuilt = entry.state === "in_plex";
  const badge = readyMadeTileBadge(entry, selected, wasBuilt);
  const waiting = entry.requests?.waiting ?? 0;
  return (
    <PosterTile
      title={entry.title}
      onOpen={onOpen}
      art={<TileArt entry={entry} banner={banner} />}
      badge={badge ?? undefined}
      pick={{ selected, onToggle }}
      selected={selected}
      controlClassName="gap-2 rounded-control transition"
      footer={
        <>
          {entry.id != null && (entry.download_missing || entry.requests) && (
            <div className="mt-1 flex flex-col gap-1">
              <DownloadMissingBadge id={entry.id} downloadMissing={entry.download_missing} library={library} />
              <RequestCountsLine summary={entry.requests} />
            </div>
          )}
          {entry.state === "failed" && retry && <RetryButton title={entry.title} run={retry.run} onDone={retry.onDone} />}
          {entry.id != null && waiting > 0 && <RequestWaitingButton id={entry.id} waiting={waiting} library={library} />}
          {customise && (
            <Link className="inline-flex min-h-11 items-center text-xs text-muted underline hover:text-text" to={customise} aria-label={`Customise ${entry.title}`}>
              Customise
            </Link>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <span className="line-clamp-2 text-sm font-medium">{entry.title}</span>
        {entry.items != null && <span className="text-xs text-muted">{entry.items} in your library</span>}
        {entry.state === "failed" && entry.last_error && (
          <details className="text-xs text-err">
            <summary className="min-h-11 cursor-pointer content-center">Error</summary>
            <p className="pt-1">{entry.last_error}</p>
          </details>
        )}
        {entry.build_seconds != null && <span className="text-xs text-muted">built in {entry.build_seconds} s</span>}
      </div>
    </PosterTile>
  );
}

export function ReadyMadeCategory() {
  const { category: raw } = useParams();
  const category = raw ? decodeURIComponent(raw) : "";
  const navigate = useNavigate();
  const { library, overview } = useLibrary();
  const picksApi = useReadyMadePicks();
  const queryClient = useQueryClient();
  const [opened, setOpened] = useState<string | null>(null);
  const closePreview = useCallback(() => setOpened(null), []);

  const data = useQuery({
    queryKey: ["ready-made", "category", library, category],
    queryFn: () => api.readyMade.category(library!, category),
    enabled: library !== null && category !== "",
    refetchInterval: (query) => {
      const collections = query.state.data?.collections ?? [];
      return collections.some((entry) => entry.state === "queued" || entry.state === "building") ? 3000 : false;
    },
  });
  useHeaderTitle(data.data?.title);

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
        <Link className="underline" to="/ready-made">
          Back to Ready-made
        </Link>
      </p>
    );
  }

  const local = picksApi.picks(library);
  const openedEntry = data.data?.collections.find((entry) => `${entry.block}:${entry.key}` === opened) ?? null;
  const customiseLink = (entry: ReadyMadeEntry) =>
    data.data?.customisable && entry.block
      ? `/collections/new?${new URLSearchParams({ library, category, block: entry.block, key: entry.key })}`
      : undefined;
  const banner = categoryOf("collection", { name: category, group: data.data?.group ?? "both" }).banner;

  return (
    <div className="flex max-w-[1400px] flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[13px] text-muted">
            <Link className="underline hover:text-text" to={`/ready-made?library=${encodeURIComponent(library)}`}>
              Ready-made
            </Link>
            {" · "}
            {library}
          </p>
          <h2 className="mt-1 text-[32px] leading-tight font-semibold">{data.data?.title ?? category}</h2>
          {data.data?.run_scope === "file" && (
            <p className="mt-2 text-sm text-warn">Kometa builds this category as a whole: Build runs all of its collections.</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => data.data && picksApi.selectAll(library, category, data.data.collections)}
            disabled={!data.data}
          >
            Select all
          </Button>
          <Button
            onClick={() => data.data && picksApi.clearCategory(library, category, data.data.collections)}
            disabled={!data.data}
          >
            Clear
          </Button>
          <Button variant="primary" onClick={() => navigate(`/ready-made?library=${encodeURIComponent(library)}`)}>
            Save
          </Button>
        </div>
      </header>

      {data.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : data.isError ? (
        <p role="alert" className="text-err">
          {data.error.message}
        </p>
      ) : !data.data.listable ? (
        <p className="text-muted">{data.data.reason ?? "This category can't be listed."}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(7rem,1fr))]" aria-label={`${data.data.title} collections`}>
          {data.data.collections.map((entry) => (
            <CollectionTile
              key={`${entry.block}:${entry.key}`}
              entry={entry}
              banner={banner}
              library={library}
              selected={isSelected(entry, category, local)}
              onToggle={() => picksApi.setPicked(library, category, entry, !isSelected(entry, category, local))}
              onOpen={() => setOpened(`${entry.block}:${entry.key}`)}
              retry={{
                // Building a pick again: the same Build the bar does, for just this one.
                run: async () => {
                  const result = (await api.readyMade.build({
                    library,
                    add: [{ category, block: entry.block, key: entry.key }],
                    remove: [],
                    dry_run: false,
                    download_missing: false,
                  })) as ReadyMadeBuildResult;
                  return result.blocked[0]?.reason ?? null;
                },
                onDone: () => queryClient.invalidateQueries({ queryKey: ["ready-made"] }),
              }}
              customise={customiseLink(entry)}
            />
          ))}
        </ul>
      )}

      {openedEntry && data.data && (
        <ReadyMadePreview
          library={library}
          category={category}
          entry={openedEntry}
          art={<TileArt entry={openedEntry} banner={banner} />}
          status={previewStatusCaption(openedEntry, isSelected(openedEntry, category, local), openedEntry.state === "in_plex")}
          selected={isSelected(openedEntry, category, local)}
          onToggle={() => picksApi.setPicked(library, category, openedEntry, !isSelected(openedEntry, category, local))}
          customise={customiseLink(openedEntry)}
          onClose={closePreview}
        />
      )}

      <BuildBar library={library} />
    </div>
  );
}
