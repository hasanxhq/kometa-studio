// One library: what's in Plex, what Kometa's config does with it (handoff v2 §8). Read-only for now.

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, api, type ConfigLibrary, type FileReference, type PlexCollection } from "../api";
import { AddLibrary } from "../components/AddLibrary";
import { PlexPoster } from "../components/PlexPoster";
import { Button, Card, Tag } from "../components/ui";
import { collectionPath, libraryTypeLabels, mergeLibraries } from "../libraries";

const tabs = [
  { id: "collections", label: "Collections" },
  { id: "overlays", label: "Overlays" },
  { id: "defaults", label: "Defaults" },
  { id: "operations", label: "Operations" },
] as const;
type TabId = (typeof tabs)[number]["id"];

const kindLabels: Record<FileReference["kind"], string> = {
  default: "Kometa default",
  file: "File",
  folder: "Folder",
  url: "URL",
  git: "Git",
  repo: "Repo",
  unknown: "?",
};

// --- Shared pieces --------------------------------------------------------------

// Kometa's defaults can't be edited (Studio never changes Kometa); the user's own files can.
const editable = (path: string) => !path.startsWith("/") && !path.startsWith("defaults/");

function FileYaml({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const file = useQuery({ queryKey: ["config", "file", path], queryFn: () => api.config.file(path), enabled: open });
  return (
    <div>
      <span className="flex flex-wrap gap-x-4">
        <button type="button" className="min-h-11 text-sm text-muted underline hover:text-text" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide YAML" : "View YAML"}
        </button>
        {editable(path) && (
          <Link to={`/files?path=${encodeURIComponent(path)}`} className="min-h-11 content-center text-sm text-muted underline hover:text-text">
            Edit {path}
          </Link>
        )}
      </span>
      {open && (
        <pre className="mt-1 max-h-[28rem] overflow-auto rounded-control border border-border bg-bg p-3 font-mono text-xs leading-5">
          {file.isPending ? "Loading…" : file.isError ? file.error.message : file.data.text}
        </pre>
      )}
    </div>
  );
}

function Chips({ items, tone }: { items: string[]; tone?: "muted" | "ok" | "warn" | "err" | "info" }) {
  if (items.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((item) => (
        <Tag key={item} tone={tone}>
          {item}
        </Tag>
      ))}
    </span>
  );
}

function ReferenceHeader({ reference }: { reference: FileReference }) {
  const title = reference.kind === "default" ? reference.files[0]?.title ?? reference.value : reference.value;
  const docs = reference.files[0]?.docs_url;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tag tone={reference.kind === "default" ? "info" : "muted"}>{kindLabels[reference.kind]}</Tag>
      <span className="min-w-0 break-all font-semibold">{title}</span>
      {reference.kind === "default" && <span className="font-mono text-xs text-muted">default: {reference.value}</span>}
      {docs && (
        <a className="text-sm text-muted underline hover:text-text" href={docs} target="_blank" rel="noreferrer">
          Kometa wiki
        </a>
      )}
      {Object.keys(reference.options).length > 0 && (
        <span className="font-mono text-xs text-muted">
          {Object.entries(reference.options)
            .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
            .join(" · ")}
        </span>
      )}
      {reference.error && <span className="break-all text-sm text-warn">{reference.error}</span>}
      {["url", "git", "repo"].includes(reference.kind) && <span className="text-sm text-muted">Remote; Kometa downloads it when it runs.</span>}
    </div>
  );
}

function KeyValues({ values, empty = "None." }: { values: Record<string, unknown>; empty?: string }) {
  const entries = Object.entries(values);
  if (entries.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <dl className="flex flex-col gap-1 font-mono text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="flex flex-col gap-0.5 border-b border-border py-1.5 last:border-0 sm:flex-row sm:gap-4">
          <dt className="shrink-0 text-muted sm:w-56">{key}</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words">{typeof value === "object" && value !== null ? JSON.stringify(value, null, 2) : String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

// --- Collections ----------------------------------------------------------------

type Filter = "all" | "managed" | "maintainerr" | "unmanaged";

function itemLink(path: string, section: string, name: string, library: string): string {
  return `/items?${new URLSearchParams({ path, section, name, library })}`;
}

function newItemLink(path: string, section: string, library: string): string {
  return `/items?${new URLSearchParams({ path, section, new: "1", library })}`;
}

// The builder, starting a new file for the library (it can also pick one of the library's files instead).
function newFileLink(section: string, library: string): string {
  return `/items?${new URLSearchParams({ section, new: "1", library })}`;
}

function NewFileLink({ section, library }: { section: "collections" | "overlays"; library: string }) {
  return (
    <Link className="min-h-11 content-center self-start text-sm text-accent underline" to={newFileLink(section, library)}>
      + New {section === "overlays" ? "overlay" : "collection"} in a new file
    </Link>
  );
}

function Nothing({ name }: { name: string }) {
  return (
    <p className="text-sm text-muted">
      Until {name} has a collection file, an overlay file or an operation, Kometa has nothing to do for it and says so when it runs.
    </p>
  );
}

function CollectionsTab({
  library,
  plexKey,
  plexError,
  config,
}: {
  library: string;
  plexKey: string | null;
  plexError: string | null;
  config: ConfigLibrary | undefined;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const plex = useQuery({
    queryKey: ["plex", "collections", plexKey],
    queryFn: () => api.plexLibraries.collections(plexKey!),
    enabled: plexKey !== null,
    staleTime: 60_000,
  });
  const collections = plex.data?.collections ?? [];
  const managed = collections.filter((c) => c.managed).length;
  const maintainerr = collections.filter((c) => c.maintainerr && !c.managed).length;

  // Collections the user's own files define by name. Defaults and dynamic collections get their names at run time.
  const ownFiles = (config?.collection_files ?? []).filter((r) => r.kind !== "default");
  const configured = ownFiles.flatMap((r) => r.files.flatMap((f) => f.collections.filter((c) => !c.dynamic).map((c) => ({ ...c, file: f.path }))));
  const fileFor = new Map(configured.map((c) => [c.name.toLowerCase(), c.file]));
  const inPlex = new Set(collections.map((c) => c.title.toLowerCase()));
  const notYet = configured.filter((c) => !inPlex.has(c.name.toLowerCase()));
  const owner = (c: PlexCollection): Filter => (c.managed ? "managed" : c.maintainerr ? "maintainerr" : "unmanaged");
  const shown = collections.filter((c) => filter === "all" || owner(c) === filter);

  return (
    <div className="flex flex-col gap-4">
      <Card title="In Plex">
        {plexError ? (
          <p role="alert" className="text-warn">
            Can't read Plex: {plexError}
          </p>
        ) : plexKey === null ? (
          <p className="text-warn">Plex has no library with this name, so there's nothing to show from Plex.</p>
        ) : plex.isPending ? (
          <p className="text-muted">Asking Plex…</p>
        ) : plex.isError ? (
          <p role="alert" className="text-err">
            {plex.error.message}
          </p>
        ) : collections.length === 0 ? (
          <p className="text-muted">This library has no collections yet.</p>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Show">
              {(
                [
                  ["all", `All (${collections.length})`],
                  ["managed", `By Kometa (${managed})`],
                  ...(maintainerr ? [["maintainerr", `By Maintainerr (${maintainerr})`]] : []),
                  ["unmanaged", `Unmanaged (${collections.length - managed - maintainerr})`],
                ] as [Filter, string][]
              ).map(([value, label]) => (
                <Button key={value} onClick={() => setFilter(value)} aria-pressed={filter === value} variant={filter === value ? "primary" : "secondary"}>
                  {label}
                </Button>
              ))}
            </div>
            <p className="mb-4 text-sm text-muted">
              "By Kometa" means the collection has Plex's <span className="font-mono">Kometa</span> label, which Kometa adds to collections it builds.
              Unmanaged collections were made some other way (by hand in Plex, or by another tool), and Kometa leaves them alone.
              {maintainerr > 0 && " Maintainerr's collections are protected: Studio refuses any change, and holds any run, that would let Kometa touch them."}
            </p>
            <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              {shown.map((collection) => {
                const file = fileFor.get(collection.title.toLowerCase());
                return (
                  <li key={collection.rating_key} className="flex flex-col gap-1.5">
                    <Link to={collectionPath(library, collection.rating_key)} className="group flex flex-col gap-1.5" aria-label={`${collection.title}: its titles`}>
                      <div className="transition group-hover:brightness-110">
                        <PlexPoster thumb={collection.thumb} title={collection.title} />
                      </div>
                      <span className="break-words text-sm font-semibold group-hover:underline">{collection.title}</span>
                    </Link>
                    <span className="flex flex-wrap items-center gap-1 text-xs text-muted">
                      {collection.items} item{collection.items === 1 ? "" : "s"}
                      {collection.managed ? (
                        <Tag tone="ok">By Kometa</Tag>
                      ) : collection.maintainerr ? (
                        <Tag tone="info">By Maintainerr</Tag>
                      ) : (
                        <Tag>Unmanaged</Tag>
                      )}
                      {collection.smart && <Tag>Smart</Tag>}
                    </span>
                    {file && config && !collection.maintainerr && (
                      <Link
                        className="text-xs text-muted underline-offset-2 hover:underline"
                        to={itemLink(file, "collections", configured.find((c) => c.name.toLowerCase() === collection.title.toLowerCase())!.name, config.name)}
                      >
                        Defined in {file}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </Card>

      {notYet.length > 0 && (
        <Card title={`Not in Plex yet (${notYet.length})`}>
          <p className="mb-3 text-sm text-muted">Your config defines these, and Kometa will create them when it next runs collections for this library.</p>
          <ul className="flex flex-col text-sm">
            {notYet.map((c) => (
              <li key={`${c.file}/${c.name}`} className="flex flex-wrap items-center gap-2 border-b border-border py-2 last:border-0">
                <span className="font-semibold">{c.name}</span>
                <span className="text-xs text-muted">{c.file}</span>
                <Chips items={c.builders} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      {config && (
        <Card title="Collection files in config.yml" actions={<NewFileLink section="collections" library={config.name} />}>
          {config.collection_files.length === 0 ? (
            config.overlay_files.length === 0 && Object.keys(config.operations).length === 0 ? (
              <Nothing name={config.name} />
            ) : (
              <p className="text-sm text-muted">None.</p>
            )
          ) : (
            <ul className="flex flex-col gap-4">
              {config.collection_files.map((reference, index) => (
                <li key={index} className="flex flex-col gap-2 border-b border-border pb-4 last:border-0">
                  <ReferenceHeader reference={reference} />
                  {reference.files.map((file) => (
                    <div key={file.path} className="flex flex-col gap-1 pl-2">
                      {file.error && <p className="break-all text-sm text-warn">{file.error}</p>}
                      <ul className="flex flex-col gap-1 text-sm">
                        {file.collections.map((c) => (
                          <li key={c.name} className="flex flex-wrap items-center gap-2">
                            {editable(file.path) ? (
                              <Link className="underline-offset-2 hover:underline" to={itemLink(file.path, c.dynamic ? "dynamic_collections" : "collections", c.name, config.name)}>
                                {c.name}
                              </Link>
                            ) : (
                              <span>{c.name}</span>
                            )}
                            {c.dynamic && <Tag tone="info">Dynamic{c.type ? `: ${c.type}` : ""}</Tag>}
                            <Chips items={c.builders} />
                            {c.templates.length > 0 && <span className="text-xs text-muted">template: {c.templates.join(", ")}</span>}
                          </li>
                        ))}
                      </ul>
                      {editable(file.path) && (
                        <Link className="min-h-11 content-center text-sm text-accent underline" to={newItemLink(file.path, "collections", config.name)}>
                          + New collection in {file.path}
                        </Link>
                      )}
                      <FileYaml path={file.path} />
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

// --- Other tabs -------------------------------------------------------------------

function OverlaysTab({ config }: { config: ConfigLibrary }) {
  return (
    <Card title="Overlay files" actions={<NewFileLink section="overlays" library={config.name} />}>
      {config.overlay_files.length === 0 && <p className="text-sm text-muted">This library has no overlay files.</p>}
      <ul className="flex flex-col gap-4">
        {config.overlay_files.map((reference, index) => (
          <li key={index} className="flex flex-col gap-2 border-b border-border pb-4 last:border-0">
            <ReferenceHeader reference={reference} />
            {reference.files.map((file) => (
              <div key={file.path} className="flex flex-col gap-1 pl-2">
                <ul className="flex flex-col gap-1 text-sm">
                  {file.overlays.map((o) => (
                    <li key={o.name} className="flex flex-wrap items-center gap-2">
                      {editable(file.path) ? (
                        <Link className="underline-offset-2 hover:underline" to={itemLink(file.path, "overlays", o.name, config.name)}>
                          {o.name}
                        </Link>
                      ) : (
                        <span>{o.name}</span>
                      )}
                      {o.overlay && o.overlay !== o.name && <span className="text-xs text-muted">shows {o.overlay}</span>}
                      {Object.keys(o.position).length > 0 && (
                        <span className="font-mono text-xs text-muted">
                          {Object.entries(o.position)
                            .map(([k, v]) => `${k.replace("_align", "").replace("_offset", " offset")}: ${v}`)
                            .join(", ")}
                        </span>
                      )}
                      <Chips items={o.builders} />
                    </li>
                  ))}
                </ul>
                {editable(file.path) && (
                  <Link className="min-h-11 content-center text-sm text-accent underline" to={newItemLink(file.path, "overlays", config.name)}>
                    + New overlay in {file.path}
                  </Link>
                )}
                {reference.kind !== "default" && <FileYaml path={file.path} />}
              </div>
            ))}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function DefaultsTab({ config }: { config: ConfigLibrary }) {
  const defaults = [...config.collection_files, ...config.overlay_files].filter((r) => r.kind === "default");
  return (
    <div className="flex flex-col gap-4">
      <Card title="Template variables for every file in this library">
        <KeyValues values={config.template_variables} />
      </Card>
      <Card title={`Kometa defaults in use (${defaults.length})`}>
        {defaults.length === 0 ? (
          <p className="text-sm text-muted">This library doesn't use any of Kometa's defaults.</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {defaults.map((reference, index) => (
              <li key={index} className="flex flex-col gap-2 border-b border-border pb-4 last:border-0">
                <ReferenceHeader reference={reference} />
                <KeyValues values={reference.template_variables} empty="No template variables: Kometa's defaults apply." />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function OperationsTab({ config }: { config: ConfigLibrary }) {
  return (
    <div className="flex flex-col gap-4">
      <Card title="Operations">
        <KeyValues values={config.operations} />
      </Card>
      <Card title="Library settings">
        <KeyValues values={config.settings} />
      </Card>
    </div>
  );
}

// --- Page ---------------------------------------------------------------------------

function TabBar({ current, onChange }: { current: TabId; onChange: (tab: TabId) => void }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-border">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={current === tab.id}
          onClick={() => onChange(tab.id)}
          className={[
            "-mb-px min-h-11 border-b-2 px-4 text-sm",
            current === tab.id ? "border-accent text-accent" : "border-transparent text-muted hover:text-text",
          ].join(" ")}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function LibraryDetail() {
  const name = useParams().name ?? "";
  const [params, setParams] = useSearchParams();
  const tab = (tabs.find((t) => t.id === params.get("tab"))?.id ?? "collections") as TabId;

  const plexList = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000 });
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const settled = !plexList.isPending && !overview.isPending;
  const entry = mergeLibraries(plexList.data?.libraries, overview.data?.libraries).find((e) => e.name === name);
  const configName = entry?.config?.name ?? null;
  const config = useQuery({ queryKey: ["config", "library", configName], queryFn: () => api.config.library(configName!), enabled: configName !== null });

  if (!settled) return <p className="text-muted">Loading…</p>;
  if (!entry) {
    return (
      <p role="alert" className="text-warn">
        Neither Plex nor Kometa's config has a library called {name}. <Link className="underline" to="/libraries">All libraries</Link>
      </p>
    );
  }

  let body: ReactNode;
  if (tab === "collections") {
    body = <CollectionsTab library={entry.name} plexKey={entry.plex?.key ?? null} plexError={plexList.isError ? plexList.error.message : null} config={config.data} />;
  } else if (!entry.config) {
    body = <p className="text-muted">{entry.name} isn't in Kometa's config.yml, so Kometa doesn't touch it yet.</p>;
  } else if (config.isPending) {
    body = <p className="text-muted">Loading…</p>;
  } else if (config.isError) {
    body = (
      <p role="alert" className="text-err">
        {config.error instanceof ApiError ? config.error.message : "Can't read the config"}
      </p>
    );
  } else {
    body = { overlays: <OverlaysTab config={config.data} />, defaults: <DefaultsTab config={config.data} />, operations: <OperationsTab config={config.data} /> }[tab];
  }

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <Link to="/libraries" className="min-h-11 content-center text-sm text-muted underline">
        ← Libraries
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-semibold">{entry.name}</h2>
        {entry.plex && <Tag>{libraryTypeLabels[entry.plex.type] ?? entry.plex.type}</Tag>}
        {!entry.config && <Tag tone="warn">Not in config.yml</Tag>}
        {entry.config && entry.config.name !== entry.name && <span className="text-sm text-muted">config.yml calls it {entry.config.name}</span>}
      </div>
      {!entry.config && entry.plex && (
        <Card title="Not in Kometa yet">
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              Adding {entry.name} puts it under libraries in config.yml. Then give it collections, overlays or Kometa's defaults here.
            </p>
            <AddLibrary name={entry.name} />
          </div>
        </Card>
      )}
      <TabBar current={tab} onChange={(next) => setParams(next === "collections" ? {} : { tab: next }, { replace: true })} />
      {body}
    </div>
  );
}
