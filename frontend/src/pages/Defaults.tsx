// Defaults, the concept's Defaults gallery: Kometa's ready-made collections and overlays, for whichever library it's applied to.
// A library's own Defaults tab is the same gallery.

import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { ApiError, api } from "../api";
import { useLibraryType } from "../libraries";
import { DefaultsGallery } from "./LibraryDefaults";

export function Defaults() {
  const [params, setParams] = useSearchParams();
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const names = overview.data?.libraries.map((library) => library.name) ?? [];
  const asked = params.get("library");
  const library = asked && names.includes(asked) ? asked : (names[0] ?? null);
  const config = useQuery({ queryKey: ["config", "library", library], queryFn: () => api.config.library(library!), enabled: library !== null });
  const libraryType = useLibraryType(library);

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
        Defaults are set per library, and config.yml has none yet.{" "}
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
          <p className="text-[13px] text-muted">Pre-built collection and overlay files</p>
          <h2 className="mt-1 text-[32px] leading-tight font-semibold">Defaults gallery</h2>
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
      {config.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : config.isError ? (
        <p role="alert" className="text-err">
          {config.error.message}
        </p>
      ) : (
        <DefaultsGallery key={library} config={config.data} libraryType={libraryType ?? null} />
      )}
    </div>
  );
}
