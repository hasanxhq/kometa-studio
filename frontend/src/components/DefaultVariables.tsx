// Template variables for a Kometa default: toggles, featured controls, and the rest under "More variables". Used by the overlay
// designer; every change is one save of config.yml that Kometa checks.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { type DefaultToggle, type SaveResult } from "../api";
import { Problems, SettingField, YamlBox } from "./forms/fields";
import { Button, Checkbox, inputClass } from "./ui";
import { SaveError } from "./ValidationReport";
import { keySchema, mappingKeys, type JsonSchema } from "../yaml/schema";

export type Values = Record<string, unknown>;

export type Featured = { key: string; label: string; switchOn?: boolean; hint?: string; options?: Record<string, string> };

// The variables worth a control of their own, where a default has them. The rest are under "More variables".
const FEATURED: Featured[] = [
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

export function useSave<T = void>(mutation: (arg: T) => Promise<SaveResult>, onSaved?: () => void) {
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
export function VariablesEditor({
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
  onUnsaved,
  onValues,
  featured: featuredList = FEATURED,
  designed = [],
  noToggles,
  top,
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
  onUnsaved?: (unsaved: boolean) => void;
  onValues?: (values: Values) => void; // for a live preview
  featured?: Featured[];
  designed?: string[]; // variables `top` has its own controls for
  noToggles?: ReactNode; // said in place of the toggles when there are none
  top?: (values: Values, set: (key: string, value: unknown) => void) => ReactNode;
}) {
  const [values, setValues] = useState<Values>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState("");
  const { keys, patterns } = useMemo(() => (root ? mappingKeys(root, schema) : { keys: [], patterns: [] }), [root, schema]);
  const known = new Map(keys.map((k) => [k.name, k]));
  const featured = featuredList.filter((f) => known.has(f.key));
  const handled = new Set([...designed, ...featured.map((f) => f.key), ...toggles.map((t) => `use_${t.key}`)]);
  const addable = keys
    .map((k) => k.name)
    .filter((name) => !(name in values) && !handled.has(name))
    .sort((a, b) => (COMMON.includes(a) === COMMON.includes(b) ? a.localeCompare(b) : COMMON.includes(a) ? -1 : 1));
  const others = Object.entries(values).filter(([key]) => !handled.has(key));
  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  // YAML that doesn't parse never reaches `values`, but it's still typing that would be lost.
  const unsaved = dirty || badYaml.size > 0;
  useEffect(() => {
    onUnsaved?.(unsaved);
    return () => onUnsaved?.(false);
  }, [unsaved, onUnsaved]);
  useEffect(() => onValues?.(values), [values, onValues]);
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
      {top?.(values, set)}
      {toggles.length <= 1 && noToggles}
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
              <select className={`${inputClass} font-mono`} value="" onChange={(e) => e.target.value && set(e.target.value, null)}>
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
        {/* Beside the button that caused it: below the pin, a refusal would be off the screen. */}
        <div className="max-h-48 overflow-y-auto">
          <SaveError error={error} />
        </div>
      </div>
    </form>
  );
}
