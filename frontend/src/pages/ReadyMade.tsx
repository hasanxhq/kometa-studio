// Ready-made collections: Kometa's defaults as category cards. Pick collections inside a category, then Build once for all.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError, api, type ReadyMadeCategorySummary, type ReadyMadeKind } from "../api";
import { BuildBar } from "../components/BuildBar";
import { Tag } from "../components/ui";
import { categoryOf, shortTitle } from "../defaults";
import { formatRelative } from "../runs";

const SECTIONS: { kind: ReadyMadeKind; label: string }[] = [
  { kind: "fixed", label: "Charts" },
  { kind: "award", label: "Awards" },
  { kind: "per_value", label: "One per value in your library" },
  { kind: "helper", label: "Other" },
];

function countLine(category: ReadyMadeCategorySummary, counting: boolean): string {
  if (category.count === null) return counting ? "Counting…" : "Not counted yet";
  const collections = `${category.count} collection${category.count === 1 ? "" : "s"}`;
  return `${collections} · ${category.in_plex} in Plex`;
}

function CategoryCover({ category }: { category: ReadyMadeCategorySummary }) {
  const [noCover, setNoCover] = useState(false);
  const banner = categoryOf("collection", category).banner;
  if (noCover) {
    return (
      <span aria-hidden="true" className={`flex h-[110px] w-full items-end p-3 font-display text-lg leading-snug font-semibold ${banner}`}>
        {shortTitle(category.title)}
      </span>
    );
  }
  return (
    <>
      <img
        src={api.config.defaultCoverUrl(category.name)}
        alt=""
        loading="lazy"
        onError={() => setNoCover(true)}
        className={`aspect-[720/248] w-full object-cover ${banner}`}
      />
      <span aria-hidden="true" className="px-3.5 pt-3 font-display text-base leading-snug font-semibold">
        {shortTitle(category.title)}
      </span>
    </>
  );
}

function CategoryCard({ category, library, counting }: { category: ReadyMadeCategorySummary; library: string; counting: boolean }) {
  const muted = !category.listable;
  const body = (
    <>
      <CategoryCover category={category} />
      <span className={`px-3.5 pt-1 text-[13px] text-muted ${category.also_default ? "" : "pb-3.5"}`}>{muted ? category.reason : countLine(category, counting)}</span>
      {category.also_default && <span className="px-3.5 pb-3.5 text-[13px] text-warn">Also on in Defaults: Kometa builds all of it</span>}
      {category.picked > 0 && (
        <span className="absolute top-2 right-2">
          <Tag tone="info">{category.picked} picked</Tag>
        </span>
      )}
    </>
  );

  if (muted) {
    return (
      <li aria-label={category.title} className="relative flex flex-col overflow-hidden rounded-card border border-border bg-surface opacity-60">
        <div className="flex flex-col text-left">{body}</div>
      </li>
    );
  }

  return (
    <li aria-label={category.title} className="relative flex flex-col overflow-hidden rounded-card border border-border bg-surface">
      <Link
        to={`/ready-made/${encodeURIComponent(category.name)}?library=${encodeURIComponent(library)}`}
        className="flex min-h-11 grow flex-col text-left hover:bg-surface-2/40"
      >
        {body}
      </Link>
    </li>
  );
}

export function ReadyMade() {
  const [params, setParams] = useSearchParams();
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const names = overview.data?.libraries.map((library) => library.name) ?? [];
  const asked = params.get("library");
  const library = asked && names.includes(asked) ? asked : (names[0] ?? null);
  const data = useQuery({
    queryKey: ["ready-made", "library", library],
    queryFn: () => api.readyMade.library(library!),
    enabled: library !== null,
    refetchInterval: (query) => (query.state.data?.counting ? 3000 : false),
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
        Ready-made collections are per library, and config.yml has none yet.{" "}
        <Link className="underline hover:text-text" to="/libraries">
          Add one from Libraries
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="flex max-w-[1400px] flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[13px] text-muted">Kometa's ready-made collections as categories</p>
          <h2 className="mt-1 text-[32px] leading-tight font-semibold">Ready-made</h2>
          {data.data?.counted_at && (
            <p className="mt-1 text-[13px] text-muted">Counted {formatRelative(data.data.counted_at)}</p>
          )}
          {data.data?.counting && !data.data.counted_at && <p className="mt-1 text-[13px] text-muted">Counting…</p>}
        </div>
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
      </header>

      {data.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : data.isError ? (
        <p role="alert" className="text-err">
          {data.error.message}
        </p>
      ) : (
        SECTIONS.map(({ kind, label }) => {
          const items = data.data.categories.filter((category) => category.kind === kind);
          if (items.length === 0) return null;
          return (
            <section key={kind} aria-labelledby={`ready-made-${kind}`}>
              <h3 id={`ready-made-${kind}`} className="mb-3 text-sm font-semibold tracking-wide text-muted uppercase">
                {label}
              </h3>
              <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((category) => (
                  <CategoryCard key={category.name} category={category} library={library} counting={data.data.counting} />
                ))}
              </ul>
            </section>
          );
        })
      )}

      <BuildBar library={library} />
    </div>
  );
}
