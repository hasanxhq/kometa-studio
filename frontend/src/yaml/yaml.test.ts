import { describe, expect, it } from "vitest";

import { checkYaml, pathAt } from "./check";
import { compile, controlFor, knownKeys, schemasAt, type JsonSchema } from "./schema";

// A small schema shaped like Kometa's collection schema: a map of definitions with oneOf choices.
const schema: JsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: { collections: { $ref: "#/definitions/collections-map" } },
  definitions: {
    "collections-map": { type: "object", additionalProperties: { $ref: "#/definitions/collection" } },
    collection: {
      type: "object",
      additionalProperties: false,
      properties: {
        sync_mode: { type: "string", enum: ["sync", "append"], description: "How to sync" },
        minimum_items: { type: "integer", minimum: 1 },
        visible_home: { oneOf: [{ type: "boolean" }, { $ref: "#/definitions/schedule" }] },
        imdb_list: { oneOf: [{ type: "string" }, { type: "array", items: { type: "string" } }] },
        plex_search: { $ref: "#/definitions/search" },
      },
    },
    schedule: { type: "string", pattern: "^(daily|weekly)" },
    search: { type: "object", properties: { any: { type: "object" }, all: { type: "object" } }, additionalProperties: false },
  },
};
const validate = compile(schema);

const FILE = `collections:
  Heroes:
    sync_mode: sometimes
    minimum_items: 0
    tmdb_spelled_wrong: 3
    visible_home: 12
`;

describe("checking YAML as you type", () => {
  it("marks schema problems at the right place", () => {
    const problems = checkYaml(FILE, validate);
    const at = (needle: string) => problems.find((p) => FILE.slice(p.from, p.to).includes(needle));
    expect(at("sometimes")?.message).toBe("Should be one of: sync, append");
    expect(at("0")?.message).toBe("must be >= 1");
    expect(at("tmdb_spelled_wrong")?.message).toBe('Kometa doesn\'t know "tmdb_spelled_wrong" here');
    // One plain message for a value that fits none of the shapes, not one per shape.
    expect(problems.filter((p) => FILE.slice(p.from, p.to) === "12").map((p) => p.message)).toEqual(["Isn't one of the shapes Kometa accepts here"]);
  });

  it("reports YAML syntax errors without checking the schema", () => {
    const problems = checkYaml("collections:\n  Heroes: [1,\n", validate);
    expect(problems).toHaveLength(1);
    expect(problems[0].severity).toBe("error");
  });

  it("flags a key given twice", () => {
    expect(checkYaml("collections:\n  A: {}\n  A: {}\n", validate)[0].message).toMatch(/unique/i);
  });

  it("is happy with a valid file", () => {
    expect(checkYaml("collections:\n  Heroes:\n    sync_mode: sync\n    imdb_list:\n      - https://a\n", validate)).toEqual([]);
  });
});

describe("finding what's allowed where", () => {
  it("works out the path at the cursor from indentation", () => {
    const text = "collections:\n  Heroes:\n    plex_search:\n      any:\n        \n";
    expect(pathAt(text, text.length - 1)).toEqual(["collections", "Heroes", "plex_search", "any"]);
    expect(pathAt("collections:\n  Heroes:\n    ", 27)).toEqual(["collections", "Heroes"]);
    const list = "collections:\n  Heroes:\n    template:\n      - name: shared\n        ";
    expect(pathAt(list, list.length)).toEqual(["collections", "Heroes", "template", 0]);
  });

  it("lists known keys through $ref and additionalProperties", () => {
    const keys = knownKeys(schema, ["collections", "Heroes"]);
    expect(keys.map((k) => k.name)).toEqual(["sync_mode", "minimum_items", "visible_home", "imdb_list", "plex_search"]);
    expect(keys[0].description).toBe("How to sync");
    expect(knownKeys(schema, ["collections", "Heroes", "plex_search"]).map((k) => k.name)).toEqual(["any", "all"]);
    expect(schemasAt(schema, ["nonsense"])).toEqual([]);
  });

  it("picks a simple control only for single-shape settings", () => {
    const props = schema.definitions!.collection.properties!;
    expect(controlFor(schema, props.sync_mode)).toEqual({ kind: "enum", options: ["sync", "append"] });
    expect(controlFor(schema, props.minimum_items)).toEqual({ kind: "integer", minimum: 1, maximum: undefined });
    expect(controlFor(schema, props.visible_home)).toEqual({ kind: "yaml" });
    expect(controlFor(schema, props.plex_search)).toEqual({ kind: "yaml" });
  });
});

describe("problems for a form", () => {
  it("are keyed by the setting they're about", async () => {
    const { itemProblems } = await import("./check");
    const problems = itemProblems(validate, "collections", "Heroes", { sync_mode: "sometimes", typo_key: 1, imdb_list: "https://a" });
    expect(problems.get("sync_mode")).toEqual(["Should be one of: sync, append"]);
    expect(problems.get("typo_key")).toEqual(['Kometa doesn\'t know "typo_key" here']);
    expect(problems.has("imdb_list")).toBe(false);
    expect(itemProblems(validate, "collections", "Heroes", { sync_mode: "sync" }).size).toBe(0);
  });
});
