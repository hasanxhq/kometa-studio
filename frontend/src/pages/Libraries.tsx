// Libraries: one card per library, from Plex and Kometa's config together (handoff v2 §8).

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { ApiError, api } from "../api";
import { Button, Tag } from "../components/ui";
import { UploadFiles } from "../components/UploadFiles";
import { libraryPath, libraryTypeLabels, mergeLibraries, type LibraryEntry } from "../libraries";

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function LibraryCard({ entry }: { entry: LibraryEntry }) {
  const { plex, config } = entry;
  const unmanaged = plex ? plex.collections - plex.managed : 0;
  return (
    <li>
      <Link
        to={libraryPath(entry.name)}
        className="flex h-full flex-col gap-3 rounded-card border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2"
      >
        <div className="flex items-start justify-between gap-2">
          <h2 className="min-w-0 break-words text-lg font-semibold">{entry.name}</h2>
          {plex && <Tag>{libraryTypeLabels[plex.type] ?? plex.type}</Tag>}
        </div>
        {plex ? (
          <p className="text-sm">
            {plural(plex.collections, "collection")}
            {plex.collections > 0 && (
              <span className="text-muted">
                {" "}
                · <span className="text-accent">{plex.managed} by Kometa</span> · {unmanaged} unmanaged
              </span>
            )}
          </p>
        ) : (
          <p className="text-sm text-warn">Plex has no library called {config?.plex_name}.</p>
        )}
        {config ? (
          <p className="text-sm text-muted">
            In config.yml: {plural(config.collection_files, "collection file")}, {plural(config.overlay_files, "overlay file")}
            {config.defaults > 0 && `, ${plural(config.defaults, "default")}`}
          </p>
        ) : (
          <p className="text-sm text-muted">Not in Kometa's config.yml yet.</p>
        )}
        {config && config.problems.length > 0 && <p className="text-sm text-warn">{plural(config.problems.length, "problem")} in its files</p>}
      </Link>
    </li>
  );
}

export function Libraries() {
  const [uploading, setUploading] = useState(false);
  const plex = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });

  if (plex.isPending || config.isPending) return <p className="text-muted">Loading your libraries…</p>;

  // No config yet (404) is normal on first run; Plex's libraries still show.
  const configMissing = config.isError && config.error instanceof ApiError && config.error.status === 404;
  const entries = mergeLibraries(plex.data?.libraries, config.data?.libraries);
  const configName = config.data?.path.split("/").pop() ?? "config.yml";

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {!configMissing && (
          <Link
            to={`/files?path=${encodeURIComponent(configName)}`}
            className="inline-flex min-h-11 items-center rounded-control border border-border-strong bg-surface-2 px-4 text-sm font-medium hover:border-muted"
          >
            Edit {configName}
          </Link>
        )}
        {!uploading && <Button onClick={() => setUploading(true)}>Add files…</Button>}
      </div>
      {uploading && <UploadFiles onDone={() => setUploading(false)} />}
      {plex.isError && (
        <p role="alert" className="text-warn">
          Can't list Plex's libraries: {plex.error.message}
        </p>
      )}
      {config.isError && !configMissing && (
        <p role="alert" className="text-warn">
          Can't read Kometa's config: {config.error.message}
        </p>
      )}
      {configMissing && <p className="text-muted">Kometa's config.yml doesn't exist yet, so these are the libraries Plex has.</p>}
      {entries.length === 0 ? (
        <p className="text-muted">No libraries yet. Connect Plex in Settings → Plex.</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry) => (
            <LibraryCard key={entry.name} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  );
}
