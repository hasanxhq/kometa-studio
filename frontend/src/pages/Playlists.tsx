// Playlists: config.yml's playlist_files (they aren't per library), each file's playlists, adding one, and running them.

import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api, type FileReference, type RunRequest } from "../api";
import { Button, Card, Tag } from "../components/ui";

const kindLabels: Record<FileReference["kind"], string> = {
  default: "Kometa default",
  file: "File",
  folder: "Folder",
  url: "URL",
  git: "Git",
  repo: "Repo",
  unknown: "Unknown",
};

function libraries(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return value ? String(value) : "no libraries set";
}

const playlistsRun: RunRequest = {
  mode: "playlists",
  libraries: [],
  collections: [],
  files: [],
  ignore_schedules: false,
  no_missing: false,
  tests: false,
  timings: false,
  low_priority: true,
};

export function Playlists() {
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const run = useMutation({ mutationFn: () => api.runs.create(playlistsRun) });

  if (overview.isPending) return <p className="text-muted">Loading…</p>;
  if (overview.isError)
    return (
      <p role="alert" className="text-err">
        {overview.error.message}
      </p>
    );

  const references = overview.data.playlist_files;
  // Local files a new playlist can go in; Kometa's defaults, URLs and repos aren't Studio's to change.
  const ownFiles = references.filter((r) => r.kind === "file" || r.kind === "folder").flatMap((r) => r.files.map((f) => f.path)).filter((p) => !p.startsWith("/"));
  const count = references.reduce((sum, r) => sum + r.files.reduce((n, f) => n + f.playlists.length, 0), 0);
  const addLink = `/items?${new URLSearchParams({ section: "playlists", new: "1", ...(ownFiles[0] ? { path: ownFiles[0] } : {}) })}`;

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <Card
        title="Playlists"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link to={addLink} className="inline-flex min-h-11 items-center justify-center rounded-control bg-accent px-4 text-sm font-medium text-on-accent transition hover:brightness-110">
              Add a playlist
            </Link>
            <Button onClick={() => run.mutate()} disabled={run.isPending || count === 0} title={count === 0 ? "No playlists yet" : undefined}>
              {run.isPending ? "Queueing…" : "Run playlists"}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-muted">
          Kometa's playlists, from config.yml's <code className="font-mono text-xs">playlist_files</code>. A playlist can take items from several libraries,
          so playlists aren't listed under a library. Kometa builds them in the Playlists step of a run.
        </p>
        {run.isSuccess && (
          <p role="status" className="mt-2 text-sm text-ok">
            Queued as <Link className="underline" to={`/activity/queue/${run.data.id}`}>run #{run.data.id}</Link>.
          </p>
        )}
        {run.isError && (
          <p role="alert" className="mt-2 text-sm text-err">
            {run.error.message}
          </p>
        )}
      </Card>

      {references.length === 0 ? (
        <p className="text-sm text-muted">No playlist files yet. Add a playlist to start one; saving adds it to config.yml.</p>
      ) : (
        references.map((reference, index) => (
          <Card key={`${reference.kind}:${reference.value}:${index}`} title={reference.value} actions={<Tag>{kindLabels[reference.kind]}</Tag>}>
            {reference.error && <p className="mb-2 text-sm text-err">{reference.error}</p>}
            {reference.files.map((file) => (
              <div key={file.path} className="flex flex-col gap-2">
                {reference.files.length > 1 && <h3 className="font-mono text-xs text-muted">{file.path}</h3>}
                {file.error && <p className="text-sm text-err">{file.error}</p>}
                {file.playlists.length === 0 ? (
                  <p className="text-sm text-muted">No playlists in this file.</p>
                ) : (
                  <ul className="flex flex-col">
                    {file.playlists.map((playlist) => {
                      const editable = reference.kind === "file" || reference.kind === "folder";
                      const row = (
                        <>
                          <span className="min-w-0 flex-1 break-words font-semibold">{playlist.name}</span>
                          <span className="text-sm text-muted">{libraries(playlist.libraries)}</span>
                        </>
                      );
                      return (
                        <li key={playlist.name}>
                          {editable ? (
                            <Link
                              to={`/items?${new URLSearchParams({ path: file.path, section: "playlists", name: playlist.name })}`}
                              className="flex min-h-11 flex-col gap-1 border-b border-border py-2 last:border-0 hover:bg-surface-2 sm:flex-row sm:items-center sm:gap-4 sm:px-2"
                            >
                              {row}
                            </Link>
                          ) : (
                            <div className="flex min-h-11 flex-col gap-1 border-b border-border py-2 last:border-0 sm:flex-row sm:items-center sm:gap-4 sm:px-2">{row}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {(reference.kind === "file" || reference.kind === "folder") && !file.path.startsWith("/") && (
                  <Link className="min-h-11 content-center self-start text-sm text-muted underline hover:text-text" to={`/files?path=${encodeURIComponent(file.path)}`}>
                    Edit {file.path} as YAML
                  </Link>
                )}
              </div>
            ))}
          </Card>
        ))
      )}
    </div>
  );
}
