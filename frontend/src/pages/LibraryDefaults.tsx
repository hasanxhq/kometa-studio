// A library's Defaults tab, the concept's Defaults gallery: Kometa's own collection and overlay defaults that suit
// this library, turned on and off with a click, and their template variables as fields from Kometa's schema.
// Every change is one save of config.yml that Kometa checks, as any edit is.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, type ConfigLibrary, type DefaultEntry, type DefaultKind, type FileReference, type SaveResult } from "../api";
import { Problems, SettingField, YamlBox } from "../components/forms/fields";
import { Button, Card, ConfirmButton, Tag, inputClass } from "../components/ui";
import { SaveError } from "../components/ValidationReport";
import { defaultVariablesSchema, keySchema, loadSchema, mappingKeys, type JsonSchema } from "../yaml/schema";

type Values = Record<string, unknown>;

const groups: { id: DefaultEntry["group"]; label: string }[] = [
  { id: "chart", label: "Charts" },
  { id: "award", label: "Awards" },
  { id: "both", label: "Movies and shows" },
  { id: "movie", label: "Movies" },
  { id: "show", label: "Shows" },
  { id: "overlays", label: "Overlays" },
];

// Variables most people reach for first; the rest are under "Add a variable".
const COMMON = ["use_all", "sep_style", "collection_mode", "collection_section", "sort_prefix", "visible_home", "visible_library", "visible_shared", "schedule", "minimum_items", "limit", "language", "region", "style"];

function useSave<T = void>(mutation: (arg: T) => Promise<SaveResult>, onSaved?: () => void) {
  const queryClient = useQueryClient();
  return useMutation<SaveResult, Error, T>({
    mutationFn: mutation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      onSaved?.();
    },
  });
}

/** Template variables as fields: known ones from the schema, the rest (use_<key> and the like) as YAML. */
function VariablesEditor({
  label,
  root,
  schema,
  saved,
  onSave,
  saving,
  error,
  onCancel,
}: {
  label: string;
  root: JsonSchema | null;
  schema: JsonSchema | undefined;
  saved: Values;
  onSave: (values: Values) => void;
  saving: boolean;
  error: Error | null;
  onCancel?: () => void;
}) {
  const [values, setValues] = useState<Values>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState("");
  const { keys, patterns } = useMemo(() => (root ? mappingKeys(root, schema) : { keys: [], patterns: [] }), [root, schema]);
  const known = new Map(keys.map((k) => [k.name, k]));
  const addable = keys
    .map((k) => k.name)
    .filter((name) => !(name in values))
    .sort((a, b) => (COMMON.includes(a) === COMMON.includes(b) ? a.localeCompare(b) : COMMON.includes(a) ? -1 : 1));
  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  const set = (key: string, value: unknown) =>
    setValues((current) => {
      const next = { ...current };
      if (value === undefined) delete next[key];
      else next[key] = value;
      return next;
    });
  const validity = (key: string, ok: boolean) =>
    setBadYaml((current) => {
      const next = new Set(current);
      if (ok) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <form
      className="flex flex-col gap-4"
      aria-label={label}
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && badYaml.size === 0) onSave(values);
      }}
    >
      {Object.keys(values).length === 0 && <p className="text-sm text-muted">No variables set: Kometa's own choices apply.</p>}
      {Object.entries(values).map(([key, value]) => {
        const info = known.get(key);
        const property = info?.schema ?? (root ? keySchema(root, schema, key) : undefined);
        return (
          <div key={key} className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              {property ? (
                <SettingField name={key} root={root} schema={property} value={value} onChange={(next) => set(key, next)} onValidity={(ok) => validity(key, ok)} hint={info?.description ?? property.description} />
              ) : (
                <div className="flex flex-col gap-1.5 text-sm">
                  <span className="font-mono text-xs text-muted">{key}</span>
                  <YamlBox label={key} value={value} onChange={(next) => set(key, next)} onValidity={(ok) => validity(key, ok)} />
                  <Problems messages={root ? ["Kometa's schema doesn't list this variable; it's kept as written."] : undefined} />
                </div>
              )}
            </div>
            <Button className="mt-6" aria-label={`Remove ${key}`} onClick={() => set(key, undefined)}>
              Remove
            </Button>
          </div>
        );
      })}
      <div className="grid gap-3 sm:grid-cols-2">
        {addable.length > 0 && (
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-muted">Add a variable</span>
            <select className={inputClass} value="" onChange={(e) => e.target.value && set(e.target.value, null)}>
              <option value="">Choose from {addable.length}…</option>
              {addable.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex flex-col gap-1.5 text-sm">
          <span className="text-muted">Add one by name</span>
          <div className="flex gap-2">
            <input
              className={`${inputClass} font-mono`}
              value={custom}
              onChange={(e) => setCustom(e.target.value.trim())}
              placeholder={patterns.length ? "e.g. use_netflix" : "variable"}
              aria-label="Variable name"
            />
            <Button
              disabled={!custom || custom in values}
              onClick={() => {
                set(custom, null);
                setCustom("");
              }}
            >
              Add
            </Button>
          </div>
          {patterns.length > 0 && (
            <span className="text-xs text-muted">
              Per-collection variables, such as {patterns.map((p) => p.pattern.replace(/^\^|\$$/g, "").replace(/\(\?!.*?\)/g, "").replace(".+", "<key>")).slice(0, 4).join(", ")}. The
              keys are on the default's wiki page.
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={!dirty || badYaml.size > 0 || saving}>
          {saving ? "Kometa is checking…" : "Save variables"}
        </Button>
        {dirty && <Button onClick={() => setValues(saved)}>Undo my changes</Button>}
        {onCancel && <Button onClick={onCancel}>Close</Button>}
        {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML in {[...badYaml].join(", ")} first.</span>}
      </div>
      <SaveError error={error} />
    </form>
  );
}

type InUse = { kind: DefaultKind; reference: FileReference; entry: DefaultEntry | undefined };

function UsedDefault({ library, item, root }: { library: string; item: InUse; root: JsonSchema | null }) {
  const [editing, setEditing] = useState(false);
  const { kind, reference, entry } = item;
  const variables = reference.template_variables as Values;
  const save = useSave((values: Values) => api.config.useDefault(library, kind, reference.value, values), () => setEditing(false));
  const drop = useSave(() => api.config.dropDefault(library, kind, reference.value));
  const schema = root ? defaultVariablesSchema(root, kind, reference.value) : undefined;
  const title = entry?.title ?? reference.files[0]?.title ?? reference.value;
  const docs = entry?.docs_url ?? reference.files[0]?.docs_url;
  const count = Object.keys(variables).length;
  return (
    <li className="flex flex-col gap-3 border-b border-border py-4 first:pt-0 last:border-0 last:pb-0" aria-label={title}>
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone="info">{kind === "overlay" ? "Overlays" : "Collections"}</Tag>
        <span className="font-semibold">{title}</span>
        <span className="font-mono text-xs text-muted">default: {reference.value}</span>
        {docs && (
          <a className="text-sm text-muted underline hover:text-text" href={docs} target="_blank" rel="noreferrer">
            Kometa wiki
          </a>
        )}
      </div>
      {!editing && (
        <p className="text-sm text-muted">
          {count === 0 ? "No variables set." : Object.entries(variables).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ")}
        </p>
      )}
      {editing ? (
        <VariablesEditor
          label={`Variables for ${title}`}
          root={root}
          schema={schema}
          saved={variables}
          onSave={(values) => save.mutate(values)}
          saving={save.isPending}
          error={save.error}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setEditing(true)}>{count === 0 ? "Set variables" : "Edit variables"}</Button>
          <ConfirmButton
            label="Turn off"
            confirm={`Turn off ${title}`}
            warning="Kometa stops building these. Collections it already made stay in Plex until you delete them."
            onConfirm={() => drop.mutate()}
            busy={drop.isPending}
          />
          {drop.isPending && <span className="text-sm text-muted">Kometa is checking…</span>}
        </div>
      )}
      <SaveError error={drop.error} />
    </li>
  );
}

function Gallery({ library, entries, libraryType }: { library: string; entries: (DefaultEntry & { kind: DefaultKind })[]; libraryType: string | null }) {
  const [group, setGroup] = useState<DefaultEntry["group"] | "all">("all");
  const [search, setSearch] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const add = useSave((entry: DefaultEntry & { kind: DefaultKind }) => api.config.useDefault(library, entry.kind, entry.name, {}));
  const needle = search.trim().toLowerCase();
  const fits = entries.filter((e) => !libraryType || e.types.includes(libraryType));
  const shown = fits.filter((e) => (group === "all" || e.group === group) && (!needle || `${e.title ?? ""} ${e.name}`.toLowerCase().includes(needle)));
  const present = groups.filter((g) => fits.some((e) => e.group === g.id));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Kind of default">
        {[{ id: "all" as const, label: `All (${fits.length})` }, ...present.map((g) => ({ id: g.id, label: `${g.label} (${fits.filter((e) => e.group === g.id).length})` }))].map((g) => (
          <Button key={g.id} variant={group === g.id ? "primary" : "secondary"} aria-pressed={group === g.id} onClick={() => setGroup(g.id)}>
            {g.label}
          </Button>
        ))}
      </div>
      <input className={inputClass} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search Kometa's defaults" aria-label="Search Kometa's defaults" />
      {shown.length === 0 ? (
        <p className="text-sm text-muted">{fits.length === 0 ? "Every default that suits this library is in use." : "Nothing matches."}</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Kometa's defaults">
          {shown.map((entry) => (
            <li key={`${entry.kind}/${entry.name}`} className="flex flex-col gap-2 rounded-control border border-border bg-surface-2 p-3" aria-label={entry.title ?? entry.name}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{entry.title ?? entry.name}</span>
                {entry.kind === "overlay" && <Tag tone="info">Overlays</Tag>}
              </div>
              <span className="font-mono text-xs text-muted">default: {entry.name}</span>
              <div className="mt-auto flex flex-wrap items-center gap-3">
                <Button
                  onClick={() => {
                    setAdded(entry.title ?? entry.name);
                    add.mutate(entry);
                  }}
                  disabled={add.isPending}
                >
                  {add.isPending && added === (entry.title ?? entry.name) ? "Kometa is checking…" : "Add"}
                </Button>
                {entry.docs_url && (
                  <a className="text-sm text-muted underline hover:text-text" href={entry.docs_url} target="_blank" rel="noreferrer">
                    Kometa wiki
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {add.isSuccess && added && (
        <p role="status" className="text-sm text-ok">
          Added {added}. Set its variables under In use, or leave Kometa's own choices.
        </p>
      )}
      <SaveError error={add.error} />
    </div>
  );
}

export function DefaultsTab({ config, libraryType }: { config: ConfigLibrary; libraryType: string | null }) {
  const catalogue = useQuery({ queryKey: ["config", "defaults"], queryFn: api.config.defaults, staleTime: Infinity });
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const root = schema.data?.root ?? null;
  const libraryVariables = useSave((values: Values) => api.config.setLibraryVariables(config.name, values));

  const byName = (kind: DefaultKind) => new Map((kind === "overlay" ? catalogue.data?.overlays : catalogue.data?.collections)?.map((e) => [e.name, e]) ?? []);
  const collections = byName("collection");
  const overlays = byName("overlay");
  const inUse: InUse[] = [
    ...config.collection_files.filter((r) => r.kind === "default").map((reference) => ({ kind: "collection" as const, reference, entry: collections.get(reference.value) })),
    ...config.overlay_files.filter((r) => r.kind === "default").map((reference) => ({ kind: "overlay" as const, reference, entry: overlays.get(reference.value) })),
  ];
  const used = new Set(inUse.map((u) => `${u.kind}/${u.reference.value}`));
  const available = [
    ...(catalogue.data?.collections ?? []).map((e) => ({ ...e, kind: "collection" as const })),
    ...(catalogue.data?.overlays ?? []).map((e) => ({ ...e, kind: "overlay" as const })),
  ].filter((e) => !used.has(`${e.kind}/${e.name}`));
  const type = libraryType === "movie" || libraryType === "show" ? libraryType : null;

  return (
    <div className="flex flex-col gap-4">
      <Card title={`In use (${inUse.length})`}>
        {inUse.length === 0 ? (
          <p className="text-sm text-muted">This library doesn't use any of Kometa's defaults yet. Add some below.</p>
        ) : (
          <ul className="flex flex-col">
            {inUse.map((item, index) => (
              <UsedDefault key={`${item.kind}/${item.reference.value}/${index}/${JSON.stringify(item.reference.template_variables)}`} library={config.name} item={item} root={root} />
            ))}
          </ul>
        )}
      </Card>

      <Card title="Add Kometa's defaults">
        {catalogue.isPending ? (
          <p className="text-muted">Reading Kometa's defaults…</p>
        ) : catalogue.isError ? (
          <p role="alert" className="text-err">
            {catalogue.error.message}
          </p>
        ) : (
          <>
            {type === null && <p className="mb-3 text-sm text-muted">Plex doesn't say whether this is a movie or show library, so every default is listed.</p>}
            <Gallery library={config.name} entries={available} libraryType={type} />
          </>
        )}
      </Card>

      <Card title="Variables for every default in this library">
        <p className="mb-3 text-sm text-muted">
          Set here, a variable reaches every collection and overlay file in {config.name}, such as the separators' style (sep_style). A default's own variables
          win over these.
        </p>
        <VariablesEditor
          key={JSON.stringify(config.template_variables)}
          label={`Variables for ${config.name}`}
          root={root}
          schema={root?.definitions?.["template-variables-library"]}
          saved={config.template_variables as Values}
          onSave={(values) => libraryVariables.mutate(values)}
          saving={libraryVariables.isPending}
          error={libraryVariables.error}
        />
      </Card>
    </div>
  );
}
