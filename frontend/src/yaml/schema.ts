// Kometa's JSON schemas in the browser (handoff v2 §7.2): compiled once per kind, and walked to
// find what's allowed at a given place in a file, for autocomplete and the designed forms.

import Ajv, { type ValidateFunction } from "ajv";
import draft06 from "ajv/dist/refs/json-schema-draft-06.json";

import { urlBase } from "../base";

export type SchemaKind = "config" | "collection" | "overlay" | "metadata" | "playlist" | "template";

export type JsonSchema = {
  $ref?: string;
  type?: string | string[];
  enum?: unknown[];
  description?: string;
  properties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  patternProperties?: Record<string, JsonSchema>;
  items?: JsonSchema | JsonSchema[];
  oneOf?: JsonSchema[];
  anyOf?: JsonSchema[];
  allOf?: JsonSchema[];
  definitions?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  default?: unknown;
};

export type LoadedSchema = { root: JsonSchema; validate: ValidateFunction };

const loaded = new Map<SchemaKind, Promise<LoadedSchema | null>>();

/** Kometa's schema for ``kind``, compiled. Null when this Kometa has none (checking is then server-side only). */
export function loadSchema(kind: SchemaKind): Promise<LoadedSchema | null> {
  let promise = loaded.get(kind);
  if (!promise) {
    promise = fetch(`${urlBase}/api/v1/config/schemas/${kind}`)
      .then((response) => (response.ok ? (response.json() as Promise<JsonSchema>) : null))
      .then((root) => (root ? { root, validate: compile(root) } : null))
      .catch(() => null);
    loaded.set(kind, promise);
  }
  return promise;
}

export function compile(root: JsonSchema): ValidateFunction {
  // Like Kometa's own check: no format checks; Kometa's colour patterns need non-Unicode regexes.
  const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false, unicodeRegExp: false });
  ajv.addMetaSchema(draft06);
  return ajv.compile(root);
}

/** Follow a local `$ref` (#/definitions/…). */
export function deref(root: JsonSchema, schema: JsonSchema | undefined, seen = 0): JsonSchema | undefined {
  if (!schema?.$ref || seen > 20) return schema;
  const target = schema.$ref
    .replace(/^#\//, "")
    .split("/")
    .reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part.replace(/~1/g, "/").replace(/~0/g, "~")], root);
  return deref(root, target as JsonSchema | undefined, seen + 1);
}

/** The schemas a value could follow here: oneOf/anyOf/allOf branches flattened. */
export function branches(root: JsonSchema, schema: JsonSchema | undefined): JsonSchema[] {
  const resolved = deref(root, schema);
  if (!resolved) return [];
  const options = [...(resolved.oneOf ?? []), ...(resolved.anyOf ?? []), ...(resolved.allOf ?? [])];
  if (options.length === 0) return [resolved];
  return [resolved, ...options.flatMap((option) => branches(root, option))];
}

/** What a mapping key may hold, inside any of ``schemas``. */
function childOf(root: JsonSchema, schemas: JsonSchema[], key: string | number): JsonSchema[] {
  const found: JsonSchema[] = [];
  for (const schema of schemas) {
    if (typeof key === "number") {
      const items = Array.isArray(schema.items) ? schema.items[key] : schema.items;
      if (items) found.push(...branches(root, items));
      continue;
    }
    if (schema.properties?.[key]) found.push(...branches(root, schema.properties[key]));
    else {
      const pattern = Object.entries(schema.patternProperties ?? {}).find(([regex]) => new RegExp(regex).test(key));
      if (pattern) found.push(...branches(root, pattern[1]));
      else if (typeof schema.additionalProperties === "object") found.push(...branches(root, schema.additionalProperties));
    }
  }
  return found;
}

/** Every schema that could apply at ``path`` (keys and list indexes from the top of the file). */
export function schemasAt(root: JsonSchema, path: (string | number)[]): JsonSchema[] {
  let schemas = branches(root, root);
  for (const key of path) {
    schemas = childOf(root, schemas, key);
    if (schemas.length === 0) break;
  }
  return schemas;
}

export type KeyInfo = { name: string; description?: string; schema: JsonSchema };

/** The keys Kometa knows for a mapping at ``path``, with their descriptions. */
export function knownKeys(root: JsonSchema, path: (string | number)[]): KeyInfo[] {
  const keys = new Map<string, KeyInfo>();
  for (const schema of schemasAt(root, path)) {
    for (const [name, property] of Object.entries(schema.properties ?? {})) {
      if (!keys.has(name)) {
        const resolved = deref(root, property);
        keys.set(name, { name, description: property.description ?? resolved?.description, schema: property });
      }
    }
  }
  return [...keys.values()];
}

export type Control =
  | { kind: "boolean" }
  | { kind: "enum"; options: string[] }
  | { kind: "integer" | "number"; minimum?: number; maximum?: number }
  | { kind: "string" }
  | { kind: "yaml" }; // anything with several possible shapes, lists or mappings

/** The form control for a setting: a simple control when there's exactly one simple shape, else a YAML box. */
export function controlFor(root: JsonSchema, schema: JsonSchema): Control {
  const resolved = deref(root, schema);
  if (!resolved || resolved.oneOf || resolved.anyOf || resolved.allOf) return { kind: "yaml" };
  if (resolved.enum && resolved.enum.every((option) => typeof option === "string")) return { kind: "enum", options: resolved.enum as string[] };
  switch (resolved.type) {
    case "boolean":
      return { kind: "boolean" };
    case "integer":
    case "number":
      return { kind: resolved.type, minimum: resolved.minimum, maximum: resolved.maximum };
    case "string":
      return { kind: "string" };
    default:
      return { kind: "yaml" };
  }
}
