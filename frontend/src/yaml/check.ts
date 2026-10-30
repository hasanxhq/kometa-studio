// Checking YAML as you type (handoff v2 §7.3, tier 1): syntax errors, and Kometa's schema mapped
// back to the exact place in the text. Kometa's own check on save stays the authority.

import type { ErrorObject, ValidateFunction } from "ajv";
import { isMap, isPair, isScalar, parseDocument, type Document, type Node } from "yaml";

export type Problem = { from: number; to: number; message: string; severity: "error" | "warning" };

function pathOf(instancePath: string): string[] {
  return instancePath
    .split("/")
    .slice(1)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function keyFor(path: (string | number)[], document: Document): (string | number)[] {
  // ajv reports list indexes as strings; the YAML document wants numbers for sequences.
  return path.map((part) => (/^\d+$/.test(String(part)) ? Number(part) : part)).map((part, index) => {
    const parent = index === 0 ? document.contents : document.getIn(path.slice(0, index), true);
    return isMap(parent) ? String(part) : part;
  });
}

function rangeOf(document: Document, path: (string | number)[], key?: string): [number, number] {
  const node = (path.length ? document.getIn(path, true) : document.contents) as Node | undefined;
  if (key !== undefined && isMap(node)) {
    const pair = node.items.find((item) => isPair(item) && isScalar(item.key) && String(item.key.value) === key);
    const keyNode = pair && (pair.key as Node | undefined);
    if (keyNode?.range) return [keyNode.range[0], keyNode.range[1]];
  }
  if (node?.range) return [node.range[0], node.range[1]];
  return [0, 0];
}

function describe(error: ErrorObject): string {
  const params = error.params as Record<string, unknown>;
  switch (error.keyword) {
    case "additionalProperties":
      return `Kometa doesn't know "${String(params.additionalProperty)}" here`;
    case "required":
      return `Missing "${String(params.missingProperty)}"`;
    case "type":
      return `Should be ${String(params.type).replace(",", " or ")}`;
    case "enum":
      return `Should be one of: ${(params.allowedValues as unknown[]).join(", ")}`;
    case "oneOf":
    case "anyOf":
      return "Isn't one of the shapes Kometa accepts here";
    default:
      return error.message ?? "Kometa's schema doesn't allow this";
  }
}

/**
 * The errors worth showing. Inside a value that fits none of a oneOf/anyOf's shapes, ajv also
 * reports why each shape failed, which mostly misleads ("must be boolean" when the value was meant
 * as a schedule). Keep only the oneOf/anyOf error for that value and anything inside it. (Matching
 * on schema paths misses shapes that are $refs, which ajv reports at the definition's path.)
 */
function worthShowing(errors: ErrorObject[]): ErrorObject[] {
  const choices = errors.filter((e) => e.keyword === "oneOf" || e.keyword === "anyOf").map((e) => e.instancePath);
  const inside = (path: string, parent: string) => path === parent || path.startsWith(parent + "/");
  return errors.filter((error) => error.keyword === "oneOf" || error.keyword === "anyOf" || !choices.some((choice) => inside(error.instancePath, choice)));
}

export function checkYaml(text: string, validate: ValidateFunction | null): Problem[] {
  const document = parseDocument(text, { prettyErrors: false, uniqueKeys: true });
  const problems: Problem[] = [];
  for (const error of document.errors) {
    const [from, to] = error.pos;
    problems.push({ from, to: Math.max(to, from + 1), message: error.message.split("\n")[0], severity: "error" });
  }
  for (const warning of document.warnings) {
    const [from, to] = warning.pos;
    problems.push({ from, to: Math.max(to, from + 1), message: warning.message.split("\n")[0], severity: "warning" });
  }
  if (problems.some((p) => p.severity === "error") || !validate) return problems;

  const data = document.toJS({ maxAliasCount: 1000 }) ?? {};
  if (validate(data)) return problems;
  const seen = new Set<string>();
  for (const error of worthShowing(validate.errors ?? [])) {
    const path = keyFor(pathOf(error.instancePath), document);
    const key = error.keyword === "additionalProperties" ? String((error.params as Record<string, unknown>).additionalProperty) : undefined;
    const [from, to] = rangeOf(document, path, key);
    const message = describe(error);
    const id = `${from}:${message}`;
    if (seen.has(id)) continue;
    seen.add(id);
    problems.push({ from, to: Math.max(to, from + 1), message, severity: "error" });
  }
  return problems;
}

/** The path of keys (and list indexes) that the line at ``position`` sits inside, by indentation. */
export function pathAt(text: string, position: number): (string | number)[] {
  const before = text.slice(0, position);
  const lines = before.split("\n");
  const current = lines[lines.length - 1];
  let indent = current.length - current.trimStart().length;
  const path: (string | number)[] = [];
  for (let i = lines.length - 2; i >= 0 && indent > 0; i--) {
    const line = lines[i];
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const lineIndent = line.length - line.trimStart().length;
    if (lineIndent >= indent) continue;
    const content = line.trimStart();
    if (content.startsWith("- ")) {
      path.unshift(0); // inside a list item; which one doesn't matter for what's allowed
      const rest = content.slice(2);
      const match = /^([^:#]+):\s*$/.exec(rest) ?? /^([^:#]+):\s/.exec(rest);
      if (match && lineIndent + 2 < indent) path.splice(1, 0, match[1].trim().replace(/^["']|["']$/g, ""));
    } else {
      const match = /^([^:#]+):/.exec(content);
      if (!match) continue;
      path.unshift(match[1].trim().replace(/^["']|["']$/g, ""));
    }
    indent = lineIndent;
  }
  return path;
}

/**
 * Problems with one item (a collection or overlay) for a form, keyed by the setting they're about
 * ("" for the item as a whole). The item is checked in place, as `{section: {name: value}}`.
 */
export function itemProblems(validate: ValidateFunction, section: string, name: string, value: unknown): Map<string, string[]> {
  const found = new Map<string, string[]>();
  if (validate({ [section]: { [name || "_"]: value } })) return found;
  for (const error of worthShowing(validate.errors ?? [])) {
    const path = pathOf(error.instancePath);
    if (path[0] !== section) continue;
    const key =
      path.length > 2 ? path[2] : error.keyword === "additionalProperties" ? String((error.params as Record<string, unknown>).additionalProperty) : "";
    const message = describe(error);
    found.set(key, [...(found.get(key) ?? []).filter((m) => m !== message), message]);
  }
  return found;
}
