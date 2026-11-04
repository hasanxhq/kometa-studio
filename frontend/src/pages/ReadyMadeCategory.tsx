// One Ready-made category: poster grid of its collections; tap to pick, Save keeps them in the bar.

import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError, api, type ReadyMadeEntry } from "../api";
import { BuildBar } from "../components/BuildBar";
import { useHeaderTitle } from "../components/HeaderTitle";
import { PlexPoster } from "../components/PlexPoster";
import { Button } from "../components/ui";
import { categoryOf } from "../defaults";
import { isSelected, useReadyMadePicks } from "../readyMadePicks";

function statusLine(entry: ReadyMadeEntry, selected: boolean, wasBuilt: boolean): string {
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

function CollectionTile({ entry, banner, selected, onToggle }: { entry: ReadyMadeEntry; banner: string; selected: boolean; onToggle: () => void }) {
  const status = statusLine(entry, selected, entry.state === "in_plex");
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        aria-label={entry.title}
        onClick={onToggle}
        className={`flex min-h-11 w-full flex-col gap-2 rounded-control text-left transition ${selected ? "ring-2 ring-accent" : ""}`}
      >
        {entry.thumb ? (
          <PlexPoster thumb={entry.thumb} title={entry.title} />
        ) : (
          <div className={`flex aspect-[2/3] items-end overflow-hidden rounded-control border border-border p-2 font-display text-sm font-semibold ${banner}`}>
            {entry.title}
          </div>
        )}
        <span className="line-clamp-2 text-sm font-medium">{entry.title}</span>
        {entry.items != null && <span className="text-xs text-muted">{entry.items} in your library</span>}
        <span className={`text-xs ${status === "Will be removed" ? "text-warn" : status === "Failed" ? "text-err" : "text-muted"}`}>{status}</span>
        {entry.state === "failed" && entry.last_error && (
          <details className="text-xs text-err">
            <summary className="min-h-11 cursor-pointer content-center">Error</summary>
            <p className="pt-1">{entry.last_error}</p>
          </details>
        )}
        {entry.build_seconds != null && <span className="text-xs text-muted">built in {entry.build_seconds} s</span>}
      </button>
    </li>
  );
}

export function ReadyMadeCategory() {
  const { category: raw } = useParams();
  const category = raw ? decodeURIComponent(raw) : "";
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const names = overview.data?.libraries.map((library) => library.name) ?? [];
  const asked = params.get("library");
  const library = asked && names.includes(asked) ? asked : (names[0] ?? null);
  const picksApi = useReadyMadePicks();

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
          {data.data?.also_default && (
            <p className="mt-2 max-w-2xl text-sm text-warn">
              Kometa's own {data.data.title} default is also on for {library}, so Kometa builds every collection in it, picked here or not.{" "}
              <Link className="underline" to={`/defaults?library=${encodeURIComponent(library)}`}>
                Turn it off in Defaults
              </Link>{" "}
              to build only your picks.
            </p>
          )}
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
              selected={isSelected(entry, category, local)}
              onToggle={() => picksApi.setPicked(library, category, entry, !isSelected(entry, category, local))}
            />
          ))}
        </ul>
      )}

      <BuildBar library={library} />
    </div>
  );
}
