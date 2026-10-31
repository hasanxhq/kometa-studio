// One Plex collection and its titles, opened from a library's poster grid. Each title shows the IDs Kometa's
// builders match on (TMDb, IMDb, TheTVDB), so it's clear why something is in a collection or missing from it.

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { api, type ConfigLibrary, type PlexItem } from "../api";
import { PlexPoster, posterGrid } from "../components/PlexPoster";
import { Button, Card, Tag, inputClass } from "../components/ui";
import { libraryPath, mergeLibraries } from "../libraries";

const PAGE = 100;

type Order = "collection" | "title" | "newest" | "oldest";

const orders: { id: Order; label: string }[] = [
  { id: "collection", label: "The collection's order" },
  { id: "title", label: "Title" },
  { id: "newest", label: "Newest first" },
  { id: "oldest", label: "Oldest first" },
];

function sorted(items: PlexItem[], order: Order): PlexItem[] {
  if (order === "collection") return items;
  const copy = [...items];
  if (order === "title") return copy.sort((a, b) => a.title.localeCompare(b.title));
  const year = (item: PlexItem) => item.year ?? (order === "newest" ? -Infinity : Infinity);
  return copy.sort((a, b) => (order === "newest" ? year(b) - year(a) : year(a) - year(b)));
}

function idLinks(item: PlexItem): { label: string; href: string }[] {
  const show = item.type === "show";
  const links = [];
  if (item.ids.tmdb) links.push({ label: "TMDb", href: `https://www.themoviedb.org/${show ? "tv" : "movie"}/${item.ids.tmdb}` });
  if (item.ids.imdb) links.push({ label: "IMDb", href: `https://www.imdb.com/title/${item.ids.imdb}/` });
  if (item.ids.tvdb) links.push({ label: "TheTVDB", href: `https://www.thetvdb.com/dereferrer/${show ? "series" : "movie"}/${item.ids.tvdb}` });
  return links;
}

/** Where the user's own files define a collection with this name, if they do. Defaults and dynamic collections are named at run time. */
function definedIn(config: ConfigLibrary | undefined, title: string): { path: string; name: string } | null {
  for (const reference of config?.collection_files ?? []) {
    if (reference.kind === "default") continue;
    for (const file of reference.files) {
      const found = file.collections.find((c) => !c.dynamic && c.name.toLowerCase() === title.toLowerCase());
      if (found) return { path: file.path, name: found.name };
    }
  }
  return null;
}

function Item({ item }: { item: PlexItem }) {
  const details = [item.year, item.content_rating, item.episodes !== null ? `${item.episodes} episode${item.episodes === 1 ? "" : "s"}` : null].filter(Boolean);
  return (
    <li className="flex flex-col gap-1.5">
      <PlexPoster thumb={item.thumb} title={item.title} />
      <span className="break-words text-sm font-semibold">{item.title}</span>
      {details.length > 0 && <span className="text-xs text-muted">{details.join(" · ")}</span>}
      <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {idLinks(item).map((link) => (
          <a key={link.label} href={link.href} target="_blank" rel="noreferrer" className="text-muted underline hover:text-text">
            {link.label}
          </a>
        ))}
        {idLinks(item).length === 0 && <span className="text-warn">No TMDb, IMDb or TheTVDB ID in Plex</span>}
      </span>
    </li>
  );
}

export function CollectionDetail() {
  const { name = "", key: ratingKey = "" } = useParams();
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState<Order>("collection");

  const plexList = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000 });
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const entry = mergeLibraries(plexList.data?.libraries, overview.data?.libraries).find((e) => e.name === name);
  const plexKey = entry?.plex?.key ?? null;
  const configName = entry?.config?.name ?? null;
  const config = useQuery({ queryKey: ["config", "library", configName], queryFn: () => api.config.library(configName!), enabled: configName !== null });

  const pages = useInfiniteQuery({
    queryKey: ["plex", "collection", plexKey, ratingKey],
    queryFn: ({ pageParam }) => api.plexLibraries.collection(plexKey!, ratingKey, pageParam, PAGE),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.start + last.items.length < last.total ? last.start + last.items.length : undefined),
    enabled: plexKey !== null,
    staleTime: 60_000,
  });
  const items = useMemo(() => pages.data?.pages.flatMap((page) => page.items) ?? [], [pages.data]);
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return sorted(needle ? items.filter((item) => `${item.title} ${item.year ?? ""}`.toLowerCase().includes(needle)) : items, order);
  }, [items, search, order]);

  const back = (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm text-muted">
      <Link to="/libraries" className="min-h-11 content-center underline hover:text-text">
        Libraries
      </Link>
      <span aria-hidden="true">›</span>
      <Link to={libraryPath(name)} className="min-h-11 content-center underline hover:text-text">
        {name}
      </Link>
    </nav>
  );
  if (plexList.isPending || overview.isPending) return <p className="text-muted">Loading…</p>;
  if (plexKey === null) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <p role="alert" className="text-warn">
          Plex has no library called {name}.
        </p>
      </div>
    );
  }
  if (pages.isPending) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <p className="text-muted">Asking Plex…</p>
      </div>
    );
  }
  if (pages.isError) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <p role="alert" className="text-err">
          {pages.error.message}
        </p>
      </div>
    );
  }

  const { collection, total } = pages.data.pages[0];
  const defined = definedIn(config.data, collection.title);
  const partial = items.length < total;

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      {back}
      <section className="flex gap-4 rounded-card border border-border bg-surface p-4">
        <div className="w-[4.5rem] shrink-0">
          <PlexPoster thumb={collection.thumb} title={collection.title} />
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="break-words text-xl font-semibold">{collection.title}</h2>
          <span className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
            {total} title{total === 1 ? "" : "s"}
            {collection.managed ? <Tag tone="ok">By Kometa</Tag> : collection.maintainerr ? <Tag tone="info">By Maintainerr</Tag> : <Tag>Unmanaged</Tag>}
            {collection.smart && <Tag>Smart</Tag>}
            {defined && config.data && !collection.maintainerr && (
              <Link
                className="ml-1.5 min-h-11 min-w-0 content-center break-words text-muted underline hover:text-text"
                to={`/items?${new URLSearchParams({ path: defined.path, section: "collections", name: defined.name, library: config.data.name })}`}
              >
                Defined in {defined.path}
              </Link>
            )}
          </span>
          {collection.summary && <p className="whitespace-pre-line text-sm">{collection.summary}</p>}
          {collection.maintainerr && <p className="text-sm text-muted">Maintainerr made this collection. Kometa leaves it alone.</p>}
          {collection.smart && <p className="text-sm text-muted">A smart collection: Plex fills it from its filter, so its titles change as the library does.</p>}
        </div>
      </section>

      <Card title="Titles">
        {total === 0 ? (
          <p className="text-sm text-muted">This collection is empty.</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted">Search</span>
                <input className={inputClass} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Title or year" />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted">Order</span>
                <select className={inputClass} value={order} onChange={(e) => setOrder(e.target.value as Order)}>
                  {orders.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {partial && (search || order !== "collection") && (
              <p className="text-sm text-muted">
                Searching and sorting the first {items.length} of {total}. Show more to include the rest.
              </p>
            )}
            {shown.length === 0 ? (
              <p className="text-sm text-muted">Nothing matches.</p>
            ) : (
              <ul className={posterGrid} aria-label="Titles">
                {shown.map((item) => (
                  <Item key={item.rating_key} item={item} />
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
              <span>
                Showing {items.length} of {total}
              </span>
              {pages.hasNextPage && (
                <Button onClick={() => pages.fetchNextPage()} disabled={pages.isFetchingNextPage}>
                  {pages.isFetchingNextPage ? "Loading…" : "Show more"}
                </Button>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
