// Activity → History: what each Kometa run changed, collection by collection, from its webhooks (handoff v2 §8).

import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, type HistoryEvent, type HistoryItem } from "../api";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";
import { formatTime } from "../runs";

function itemLink(item: HistoryItem): string | null {
  if (item.tmdb_id) return `https://www.themoviedb.org/movie/${item.tmdb_id}`;
  if (item.tvdb_id) return `https://www.thetvdb.com/dereferrer/series/${item.tvdb_id}`;
  return null;
}

function Items({ label, items, tone }: { label: string; items: HistoryItem[]; tone: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wider ${tone}`}>
        {label} ({items.length})
      </h4>
      <ul className="mt-1 flex flex-col gap-0.5 text-sm">
        {items.map((item, index) => {
          const href = itemLink(item);
          return (
            <li key={index}>
              {href ? (
                <a className="underline-offset-2 hover:underline" href={href} target="_blank" rel="noreferrer">
                  {item.title ?? "Untitled"}
                </a>
              ) : (
                (item.title ?? "Untitled")
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EventRow({ event }: { event: HistoryEvent }) {
  const name = event.collection ?? event.playlist;
  const detail = event.additions.length + event.removals.length + event.radarr_adds.length + event.sonarr_adds.length > 0;
  const summary = (
    <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
      <span className="w-40 shrink-0 text-xs text-muted">{formatTime(event.received_at)}</span>
      <span className="min-w-0 break-words">
        {event.event === "delete" ? (
          event.message
        ) : (
          <>
            {event.library && <span className="text-muted">{event.library} · </span>}
            <span className="font-semibold">{name}</span>
            {event.playlist && <span className="text-muted"> (playlist)</span>}
          </>
        )}
      </span>
      {event.created && <Tag tone="ok">New</Tag>}
      {event.event === "delete" && <Tag tone="err">Deleted</Tag>}
      {event.event === "changes" && (
        <span className="text-xs">
          <span className="text-ok">+{event.additions.length}</span> <span className="text-err">−{event.removals.length}</span>
        </span>
      )}
      {event.radarr_adds.length > 0 && <span className="text-xs text-info">{event.radarr_adds.length} sent to Radarr</span>}
      {event.sonarr_adds.length > 0 && <span className="text-xs text-info">{event.sonarr_adds.length} sent to Sonarr</span>}
      {event.run_id !== null && (
        <Link to={`/activity/queue/${event.run_id}`} className="text-xs text-muted underline" onClick={(e) => e.stopPropagation()}>
          run #{event.run_id}
        </Link>
      )}
    </span>
  );
  return (
    <li className="border-b border-border last:border-0">
      {detail ? (
        <details>
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 py-2 hover:bg-surface-2">{summary}</summary>
          <div className="grid gap-4 pb-3 pl-2 sm:grid-cols-2 lg:grid-cols-4">
            <Items label="Added" items={event.additions} tone="text-ok" />
            <Items label="Removed" items={event.removals} tone="text-err" />
            <Items label="Sent to Radarr" items={event.radarr_adds} tone="text-info" />
            <Items label="Sent to Sonarr" items={event.sonarr_adds} tone="text-info" />
          </div>
        </details>
      ) : (
        <div className="flex min-h-11 items-center gap-2 py-2">{summary}</div>
      )}
    </li>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function ActivityHistory() {
  const [library, setLibrary] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const history = useInfiniteQuery({
    queryKey: ["history", library, q],
    queryFn: ({ pageParam }) => api.history({ library: library || undefined, q: q || undefined, before: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next ?? undefined,
  });

  const pages = history.data?.pages ?? [];
  const events = pages.flatMap((page) => page.events);
  const libraries = pages[0]?.libraries ?? [];

  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <Card title="What Kometa changed">
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <Field label="Library">
            <select className={inputClass} value={library} onChange={(e) => setLibrary(e.target.value)}>
              <option value="">All libraries</option>
              {libraries.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Collection">
            <input className={inputClass} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name" />
          </Field>
        </div>
        {history.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : history.isError ? (
          <p role="alert" className="text-err">
            Can't load the history: {history.error.message}
          </p>
        ) : events.length === 0 ? (
          <p className="text-muted">
            {library || q
              ? "Nothing matches."
              : "Nothing yet. Each time Kometa adds or removes items in a collection, it shows up here."}
          </p>
        ) : (
          <>
            <ul>
              {events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
            {history.hasNextPage && (
              <Button className="mt-4" onClick={() => history.fetchNextPage()} disabled={history.isFetchingNextPage}>
                {history.isFetchingNextPage ? "Loading…" : "Show older"}
              </Button>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
