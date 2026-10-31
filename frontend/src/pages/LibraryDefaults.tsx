// The Defaults gallery, the concept's second screen: Kometa's own collection and overlay defaults that suit one library, on and
// off with a click, and a panel to customize the one picked: its toggles and common variables as controls, the rest from Kometa's
// schema. Every change is one save of config.yml that Kometa checks, as any edit is. Used by Defaults and by a library's Defaults tab.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { stringify } from "yaml";

import { api, type ConfigLibrary, type DefaultEntry, type DefaultKind, type DefaultToggle, type FileReference, type SaveResult } from "../api";
import { Problems, SettingField, YamlBox } from "../components/forms/fields";
import { Button, Checkbox, ConfirmButton, inputClass } from "../components/ui";
import { SaveError } from "../components/ValidationReport";
import { categories, categoryOf, describeDefault, shortTitle } from "../defaults";
import { defaultVariablesSchema, keySchema, loadSchema, mappingKeys, type JsonSchema } from "../yaml/schema";

type Values = Record<string, unknown>;

// The variables worth a control of their own, where a default has them. The rest are under "More variables".
const FEATURED: { key: string; label: string; switchOn?: boolean; hint?: string; options?: Record<string, string> }[] = [
  { key: "originals_only", label: "Originals only", switchOn: false },
  { key: "use_separator", label: "Separator collection", switchOn: true },
  { key: "region", label: "Watch region", hint: "A two-letter country code, such as IN or US." },
  { key: "collection_mode", label: "Show in Plex", options: { default: "Library default", hide: "Hide collection", hide_items: "Hide items, show collection", show_items: "Show everything" } },
  { key: "language", label: "Language" },
  { key: "sep_style", label: "Separator style" },
  { key: "limit", label: "Items per collection" },
];

// Variables most people reach for first in the list of the rest.
const COMMON = ["use_all", "collection_section", "sort_prefix", "visible_home", "visible_library", "visible_shared", "schedule", "minimum_items", "style"];

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

/** One line of switches: a variable that's either on or left out. */
function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex min-h-11 items-center justify-between gap-3 text-sm">
      {label}
      <input type="checkbox" className="size-[18px] shrink-0 accent-accent" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

/**
 * Template variables as controls: a default's toggles, the featured ones, and under "More variables" anything else, from the
 * schema where it knows them and as YAML where it doesn't (use_<key> and the like).
 */
function VariablesEditor({
  label,
  root,
  schema,
  saved,
  onSave,
  saving,
  error,
  saveLabel = "Save variables",
  alwaysSave = false,
  toggles = [],
  togglesLegend = "",
  preview,
}: {
  label: string;
  root: JsonSchema | null;
  schema: JsonSchema | undefined;
  saved: Values;
  onSave: (values: Values) => void;
  saving: boolean;
  error: Error | null;
  saveLabel?: string;
  alwaysSave?: boolean; // saving does something even with nothing changed: it turns the default on
  toggles?: DefaultToggle[];
  togglesLegend?: string;
  preview?: (values: Values) => string;
}) {
  const [values, setValues] = useState<Values>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState("");
  const { keys, patterns } = useMemo(() => (root ? mappingKeys(root, schema) : { keys: [], patterns: [] }), [root, schema]);
  const known = new Map(keys.map((k) => [k.name, k]));
  const featured = FEATURED.filter((f) => known.has(f.key));
  const handled = new Set([...featured.map((f) => f.key), ...toggles.map((t) => `use_${t.key}`)]);
  const addable = keys
    .map((k) => k.name)
    .filter((name) => !(name in values) && !handled.has(name))
    .sort((a, b) => (COMMON.includes(a) === COMMON.includes(b) ? a.localeCompare(b) : COMMON.includes(a) ? -1 : 1));
  const others = Object.entries(values).filter(([key]) => !handled.has(key));
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
  // Kometa builds a collection unless use_<key> says not to; use_all and a few of its own defaults change where that starts.
  const startsOn = (toggle: DefaultToggle) => toggle.on && values.use_all !== false;

  return (
    <form
      className="flex flex-col gap-4"
      aria-label={label}
      onSubmit={(event) => {
        event.preventDefault();
        if ((dirty || alwaysSave) && badYaml.size === 0) onSave(values);
      }}
    >
      {toggles.length > 1 && (
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1 text-sm font-semibold">{togglesLegend}</legend>
          <div className="grid max-h-72 grid-cols-2 gap-x-3 overflow-y-auto">
            {toggles.map((toggle) => (
              <Checkbox
                key={toggle.key}
                checked={(values[`use_${toggle.key}`] ?? startsOn(toggle)) === true}
                onChange={(checked) => set(`use_${toggle.key}`, checked === startsOn(toggle) ? undefined : checked)}
              >
                {toggle.label}
              </Checkbox>
            ))}
          </div>
        </fieldset>
      )}
      {featured.map(({ key, label: name, switchOn, hint, options }) => {
        const info = known.get(key)!;
        return switchOn === undefined ? (
          <SettingField
            key={key}
            name={key}
            label={name}
            root={root}
            schema={info.schema}
            value={values[key]}
            onChange={(next) => set(key, next)}
            onValidity={(ok) => validity(key, ok)}
            hint={hint}
            unset="Kometa's default"
            optionLabels={options}
          />
        ) : (
          <Switch key={key} label={name} checked={(values[key] ?? switchOn) === true} onChange={(checked) => set(key, checked === switchOn ? undefined : checked)} />
        );
      })}
      {preview && <pre aria-label="What this writes to config.yml" className="overflow-x-auto rounded-control border border-border bg-bg p-3 font-mono text-xs leading-5 text-muted">{preview(values)}</pre>}
      <details className="flex flex-col gap-4 text-sm" open={others.length > 0 || toggles.length + featured.length === 0}>
        <summary className="min-h-11 cursor-pointer content-center text-muted hover:text-text">More variables{others.length > 0 && ` (${others.length})`}</summary>
        <div className="flex flex-col gap-4">
          {others.map(([key, value]) => {
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
      </details>
      {/* Pinned, as the panel can be taller than the screen. */}
      <div className="sticky -bottom-5 z-10 -mb-5 flex flex-col gap-2 bg-surface pt-1 pb-5">
        <Button variant="primary" type="submit" disabled={(!dirty && !alwaysSave) || badYaml.size > 0 || saving}>
          {saving ? "Kometa is checking…" : saveLabel}
        </Button>
        {dirty && <Button onClick={() => setValues(saved)}>Undo my changes</Button>}
        {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML in {[...badYaml].join(", ")} first.</span>}
      </div>
      <SaveError error={error} />
    </form>
  );
}

// A default as the gallery shows it. `reference` is its entry in this library, when it's on (the first, if listed twice: that's the one saves change).
type Listed = DefaultEntry & { kind: DefaultKind; reference?: FileReference };

const idOf = (item: Pick<Listed, "kind" | "name">) => `${item.kind}/${item.name}`;
const titleOf = (item: Listed) => item.title ?? item.name;

function Customize({ library, item, root, libraryType, onClose }: { library: string; item: Listed; root: JsonSchema | null; libraryType: string | null; onClose: () => void }) {
  const save = useSave((values: Values) => api.config.useDefault(library, item.kind, item.name, values));
  const title = shortTitle(titleOf(item));
  const variables = (item.reference?.template_variables ?? {}) as Values;
  const legend = item.name === "streaming" ? "Services to include" : item.kind === "overlay" ? "Overlays to include" : "Collections to include";
  const toggles = item.toggles.filter((toggle) => !libraryType || toggle.types.includes(libraryType));
  const preview = (values: Values) =>
    stringify([{ default: item.name, ...(Object.keys(values).length > 0 && { template_variables: values }) }], { lineWidth: 0 }).trimEnd();
  return (
    <>
      <div>
        <p className="text-xs tracking-[0.06em] text-muted uppercase">Customize default</p>
        <h2 className="mt-1 text-[22px] font-semibold">{title}</h2>
        <p className="mt-1 text-[13px] text-muted">
          Each switch writes a template variable: no YAML needed.
          {item.docs_url && (
            <>
              {" "}
              <a className="underline hover:text-text" href={item.docs_url} target="_blank" rel="noreferrer">
                Kometa wiki
              </a>
            </>
          )}
        </p>
      </div>
      <VariablesEditor
        key={JSON.stringify(variables)}
        label={`Variables for ${titleOf(item)}`}
        root={root}
        schema={root ? defaultVariablesSchema(root, item.kind, item.name) : undefined}
        saved={variables}
        onSave={(values) => save.mutate(values)}
        saving={save.isPending}
        error={save.error}
        saveLabel={`Save to ${library}`}
        alwaysSave={!item.reference}
        toggles={toggles}
        togglesLegend={legend}
        preview={preview}
      />
      {save.isSuccess && (
        <p role="status" className="text-sm text-ok">
          Saved to {library}.
        </p>
      )}
      <Button onClick={onClose}>Close</Button>
    </>
  );
}

function Pill({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`min-h-9 rounded-full border px-3 text-[13px] transition ${pressed ? "border-text bg-text text-bg" : "border-border-strong text-muted hover:text-text"}`}
    >
      {children}
    </button>
  );
}

function Tile({ item, library, selected, onSelect, busy, onAdd, onDrop }: { item: Listed; library: string; selected: boolean; onSelect: () => void; busy: boolean; onAdd: () => void; onDrop: () => void }) {
  const [asking, setAsking] = useState(false);
  const title = titleOf(item);
  return (
    <li aria-label={title} className={`flex flex-col overflow-hidden rounded-card bg-surface ${selected ? "border-2 border-accent" : "border border-border"}`}>
      <button type="button" aria-pressed={selected} aria-label={`Customize ${title} for ${library}`} onClick={onSelect} className="flex grow flex-col text-left">
        <span aria-hidden="true" className={`flex h-[110px] w-full items-end p-3 font-display text-lg leading-snug font-semibold ${categoryOf(item.kind, item).banner}`}>
          {shortTitle(title)}
        </span>
        <span className="px-3.5 pt-3.5 text-[13px] text-muted">{describeDefault(item.kind, item)}</span>
      </button>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 pt-1 pb-2">
        {asking ? (
          <ConfirmButton
            open
            label="Turn off"
            confirm={`Turn off ${title}`}
            warning="Kometa stops building these. What it already made stays in Plex until you delete it."
            onConfirm={onDrop}
            onKeep={() => setAsking(false)}
            busy={busy}
          />
        ) : (
          <Checkbox checked={item.reference !== undefined} disabled={busy} onChange={(on) => (on ? onAdd() : setAsking(true))}>
            {busy ? "Checking…" : "Enabled"}
          </Checkbox>
        )}
        {selected && <span className="text-xs text-accent">Editing</span>}
      </div>
    </li>
  );
}

export function DefaultsGallery({ config, libraryType }: { config: ConfigLibrary; libraryType: string | null }) {
  const catalogue = useQuery({ queryKey: ["config", "defaults"], queryFn: api.config.defaults, staleTime: Infinity });
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const root = schema.data?.root ?? null;
  const library = config.name;
  const type = libraryType === "movie" || libraryType === "show" ? libraryType : null;

  const [kind, setKind] = useState<DefaultKind>("collection");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [changing, setChanging] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const panel = useRef<HTMLElement>(null);
  const add = useSave((item: Listed) => api.config.useDefault(library, item.kind, item.name, {}));
  const drop = useSave((item: Listed) => api.config.dropDefault(library, item.kind, item.name));
  const libraryVariables = useSave((values: Values) => api.config.setLibraryVariables(library, values));

  // Below the grid on a narrow screen, so picking a card has to bring it into view.
  useEffect(() => {
    if (selectedId) panel.current?.scrollIntoView?.({ block: "nearest" });
  }, [selectedId]);

  const list = (which: DefaultKind): Listed[] => {
    const references = (which === "overlay" ? config.overlay_files : config.collection_files).filter((r) => r.kind === "default");
    const known = (which === "overlay" ? catalogue.data?.overlays : catalogue.data?.collections) ?? [];
    const used = new Map([...references].reverse().map((reference) => [reference.value, reference]));
    const items: Listed[] = known.map((entry) => ({ ...entry, kind: which, reference: used.get(entry.name) }));
    // In config.yml, but not a default this Kometa has: still shown, so it can be turned off.
    for (const [name, reference] of used) {
      if (!known.some((entry) => entry.name === name)) {
        const file = reference.files[0];
        items.push({ name, group: which === "overlay" ? "overlays" : "both", types: [], title: file?.title ?? null, docs_url: file?.docs_url ?? null, toggles: [], kind: which, reference });
      }
    }
    return items.filter((item) => !type || item.types.includes(type) || item.reference);
  };
  const collections = list("collection");
  const overlays = list("overlay");
  const fits = kind === "overlay" ? overlays : collections;
  const selected = [...collections, ...overlays].find((item) => idOf(item) === selectedId);
  const enabled = fits.filter((item) => item.reference).length;
  const needle = search.trim().toLowerCase();
  const shown = fits.filter(
    (item) =>
      (category === "all" || (category === "enabled" ? item.reference : categoryOf(kind, item).id === category)) && (!needle || `${item.title ?? ""} ${item.name}`.toLowerCase().includes(needle)),
  );
  const present = categories(kind).filter((c) => fits.some((item) => categoryOf(kind, item).id === c.id));

  return (
    <div className="flex flex-col gap-6 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-5">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter defaults">
          {(["collection", "overlay"] as const).map((k) => (
            <Pill
              key={k}
              pressed={kind === k}
              onClick={() => {
                setKind(k);
                setCategory("all");
              }}
            >
              {k === "overlay" ? "Overlays" : "Collections"}
            </Pill>
          ))}
          <span aria-hidden="true" className="mx-1 w-px bg-border-strong" />
          {[{ id: "all", label: "All" }, { id: "enabled", label: `Enabled (${enabled})` }, ...present].map((c) => (
            <Pill key={c.id} pressed={category === c.id} onClick={() => setCategory(c.id)}>
              {c.label}
            </Pill>
          ))}
        </div>
        <input className={inputClass} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search Kometa's defaults" aria-label="Search Kometa's defaults" />
        {type === null && <p className="text-sm text-muted">Plex doesn't say whether this is a movie or show library, so every default is listed.</p>}
        {add.isSuccess && added && (
          <p role="status" className="text-sm text-ok">
            Added {added}. Pick its card to customize it, or leave Kometa's own choices.
          </p>
        )}
        <SaveError error={add.error ?? drop.error} />
        {catalogue.isError && (
          <p role="alert" className="text-err">
            {catalogue.error.message}
          </p>
        )}
        {catalogue.isPending ? (
          <p className="text-muted">Reading Kometa's defaults…</p>
        ) : shown.length === 0 ? (
          !catalogue.isError && <p className="text-sm text-muted">{category === "enabled" && !needle ? `${library} doesn't use any of these yet.` : "Nothing matches."}</p>
        ) : (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4" aria-label="Kometa's defaults">
            {shown.map((item) => (
              <Tile
                key={idOf(item)}
                item={item}
                library={library}
                selected={idOf(item) === selectedId}
                onSelect={() => setSelectedId(idOf(item))}
                busy={changing === idOf(item) && (add.isPending || drop.isPending)}
                onAdd={() => {
                  setChanging(idOf(item));
                  setAdded(titleOf(item));
                  add.mutate(item);
                }}
                onDrop={() => {
                  setChanging(idOf(item));
                  drop.mutate(item);
                }}
              />
            ))}
          </ul>
        )}
      </div>

      <aside ref={panel} aria-label="Customize" className="flex scroll-mt-4 flex-col gap-[18px] rounded-card border border-border bg-surface p-5 xl:sticky xl:top-0 xl:max-h-[calc(100dvh-7.5rem)] xl:w-[380px] xl:shrink-0 xl:overflow-y-auto">
        {selected ? (
          <Customize key={idOf(selected)} library={library} item={selected} root={root} libraryType={type} onClose={() => setSelectedId(null)} />
        ) : (
          <>
            <div>
              <p className="text-xs tracking-[0.06em] text-muted uppercase">Every default in {library}</p>
              <h2 className="mt-1 text-[22px] font-semibold">Library variables</h2>
              <p className="mt-1 text-[13px] text-muted">
                Set here, a variable reaches every collection and overlay file in {library}. A default's own variables win over these. Pick a card to customize one default.
              </p>
            </div>
            <VariablesEditor
              key={JSON.stringify(config.template_variables)}
              label={`Variables for ${library}`}
              root={root}
              schema={root?.definitions?.["template-variables-library"]}
              saved={config.template_variables as Values}
              onSave={(values) => libraryVariables.mutate(values)}
              saving={libraryVariables.isPending}
              error={libraryVariables.error}
            />
          </>
        )}
      </aside>
    </div>
  );
}
