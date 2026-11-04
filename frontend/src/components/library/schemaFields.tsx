// Shared pieces for a library's Operations and settings forms: fields from Kometa's config schema,
// with free-form mappings and unknown keys left read-only (edited in the file editor) and kept on save.

import { SettingField } from "../forms/fields";
import { describeDefault } from "../KometaSettings";
import { deref, mappingKeys, type JsonSchema, type KeyInfo } from "../../yaml/schema";

export type Values = Record<string, unknown>;

export function label(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A nested mapping the schema names but doesn't list properties for (genre_mapper and the like) — not a form field. */
export function isFreeMapping(root: JsonSchema, schema: JsonSchema | undefined): boolean {
  const resolved = deref(root, schema);
  if (!resolved || resolved.oneOf || resolved.anyOf || resolved.allOf) return false;
  if (Object.keys(resolved.properties ?? {}).length > 0) return false;
  // Free-form maps only: an object (or patternProperties alone), not an enum/boolean/string with no `type`.
  return resolved.type === "object" || !!resolved.patternProperties;
}

/** Keys the schema can drive a form control for (including a YAML box for oneOf / nested objects with properties). */
export function formableKeys(root: JsonSchema | null, schema: JsonSchema | undefined): KeyInfo[] {
  if (!root) return [];
  return mappingKeys(root, schema).keys.filter((key) => !isFreeMapping(root, key.schema));
}

/** Keys present in ``values`` that the form must not edit or drop: free mappings and anything not in the schema. */
export function readOnlyKeys(root: JsonSchema | null, schema: JsonSchema | undefined, values: Values): string[] {
  const formable = new Set(formableKeys(root, schema).map((key) => key.name));
  return Object.keys(values).filter((key) => !formable.has(key)).sort();
}

export function hint(info: KeyInfo | undefined): string | undefined {
  const description = info?.description?.split("\n")[0]?.replace(/^Used to /, "") ?? "";
  if (!description) return undefined;
  return description.charAt(0).toUpperCase() + description.slice(1).replace(/\.?$/, ".");
}

export function unsetLabel(root: JsonSchema | null, schema: JsonSchema | undefined): string {
  const resolved = root && schema ? deref(root, schema) : undefined;
  if (resolved && "default" in resolved) return `Default (${describeDefault(resolved.default)})`;
  return "Not set";
}

export function KeyValues({ values, empty = "None." }: { values: Values; empty?: string }) {
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

/** Formable fields from the schema for one mapping. */
export function MappingFields({
  root,
  values,
  onChange,
  onValidity,
  keys,
}: {
  root: JsonSchema | null;
  values: Values;
  onChange: (key: string, value: unknown) => void;
  onValidity: (key: string, ok: boolean) => void;
  keys: KeyInfo[];
}) {
  if (keys.length === 0) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {keys.map((key) => (
        <SettingField
          key={key.name}
          name={key.name}
          label={label(key.name)}
          root={root}
          schema={key.schema}
          value={values[key.name]}
          onChange={(next) => onChange(key.name, next)}
          onValidity={(ok) => onValidity(key.name, ok)}
          hint={hint(key)}
          unset={unsetLabel(root, key.schema)}
        />
      ))}
    </div>
  );
}

/** Keys the form can't edit (free mappings, or not in the schema). Kept as-is on save. */
export function ReadOnlyFields({ root, schema, values }: { root: JsonSchema | null; schema: JsonSchema | undefined; values: Values }) {
  const frozen = readOnlyKeys(root, schema, values);
  if (frozen.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm text-muted">Edited in the file editor</p>
      <KeyValues values={Object.fromEntries(frozen.map((key) => [key, values[key]]))} />
    </div>
  );
}
