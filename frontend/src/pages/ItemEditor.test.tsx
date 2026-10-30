import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Item, Validation } from "../api";
import { mockApi, renderAt } from "../test-utils";

// A small schema shaped like Kometa's collection and overlay schemas.
const collectionSchema = {
  type: "object",
  properties: { collections: { type: "object", additionalProperties: { $ref: "#/definitions/collection" } } },
  definitions: {
    collection: {
      type: "object",
      additionalProperties: false,
      properties: {
        tmdb_collection: { oneOf: [{ type: "integer" }, { type: "array", items: { type: "integer" } }], description: "TMDb collection IDs" },
        tmdb_trending_weekly: { type: "integer", minimum: 1 },
        summary: { type: "string" },
        sort_title: { type: "string" },
        sync_mode: { type: "string", enum: ["sync", "append"] },
        collection_order: { type: "string" },
        minimum_items: { type: "integer", minimum: 1 },
        visible_home: { oneOf: [{ type: "boolean" }, { type: "string" }] },
        build_collection: { type: "boolean", description: "Build it in Plex" },
        template: { type: "object" },
      },
    },
  },
};

const passed: Validation = { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" };

const heroes: Item = {
  path: "Movies.yml",
  hash: "h1",
  section: "collections",
  name: "Heroes",
  value: { tmdb_collection: [556], summary: "Everything Heroes.", sync_mode: "sometimes", build_collection: true, my_variable: "kept" },
  kind: "collection",
};

const routes = {
  "GET /config/schemas/collection": () => collectionSchema,
  "GET /config/item?path=Movies.yml&section=collections&name=Heroes": () => heroes,
};

beforeEach(() => localStorage.clear());

describe("The collection form", () => {
  it("edits the designed settings and saves only this collection", async () => {
    const calls = mockApi({ ...routes, "POST /config/item": () => ({ backup: "b", files: [], validation: passed }) });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    expect(await screen.findByDisplayValue("Everything Heroes.")).toBeInTheDocument();
    expect(screen.getByLabelText("tmdb_collection")).toHaveValue("- 556");
    // The file's sync_mode isn't allowed by the schema; the form says so where it is.
    await waitFor(() => expect(screen.getByText("Should be one of: sync, append")).toBeInTheDocument());
    // Advanced and unknown settings are hidden but counted.
    expect(screen.getByText(/2 more settings are set here/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Summary/), { target: { value: "All of the Heroes." } });
    fireEvent.change(screen.getByLabelText(/Sync mode/), { target: { value: "sync" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /config/item")?.body).toEqual({
      path: "Movies.yml",
      base_hash: "h1",
      section: "collections",
      name: "Heroes",
      value: { tmdb_collection: [556], summary: "All of the Heroes.", sync_mode: "sync", build_collection: true, my_variable: "kept" },
      create: false,
      rename: null,
    });
  });

  it("shows every other setting under Show Advanced, keeping unknown ones as written", async () => {
    localStorage.setItem("studio.showAdvanced", "true");
    mockApi(routes);
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    const more = (await screen.findByRole("heading", { name: "More settings" })).closest("section")!;
    expect(within(more).getByLabelText("build_collection")).toHaveValue("true");
    expect(within(more).getByText(/kept as written/)).toBeInTheDocument();
    expect(within(more).getByLabelText("my_variable")).toHaveValue("kept");
    const add = within(more).getByRole("combobox", { name: "Add a setting" });
    expect(within(add).getByRole("option", { name: "template" })).toBeInTheDocument();
    expect(within(add).queryByRole("option", { name: "summary" })).toBeNull(); // designed above, not repeated
  });

  it("refuses to save while a YAML box doesn't parse", async () => {
    mockApi(routes);
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    fireEvent.change(await screen.findByLabelText("tmdb_collection"), { target: { value: "- 556\n- [unclosed" } });
    expect(await screen.findByText(/^YAML:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Fix the YAML in tmdb_collection first.")).toBeInTheDocument();
  });

  it("creates a collection with a source", async () => {
    const calls = mockApi({
      "GET /config/schemas/collection": () => collectionSchema,
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }),
      "POST /config/item": () => ({ backup: "b", files: [], validation: passed }),
      "GET /config/item?path=Movies.yml&section=collections&name=Trending": () => ({ ...heroes, name: "Trending", value: { tmdb_trending_weekly: 1 } }),
    });
    renderAt("/items?path=Movies.yml&section=collections&new=1&library=Movies");

    expect(await screen.findByText("New collection in Movies.yml")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Trending" } });
    await screen.findByRole("option", { name: "tmdb_trending_weekly" });
    fireEvent.change(screen.getByLabelText("Add a source"), { target: { value: "tmdb_trending_weekly" } });
    expect(screen.getByLabelText("tmdb_trending_weekly")).toHaveValue(1); // starts at the schema's minimum
    fireEvent.click(screen.getByRole("button", { name: "Add collection" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    expect(calls.find((c) => c.route === "POST /config/item")?.body).toMatchObject({
      name: "Trending",
      value: { tmdb_trending_weekly: 1 },
      create: true,
      rename: null,
    });
  });

  it("runs just this collection, in its library, ignoring its schedule", async () => {
    const calls = mockApi({ ...routes, "POST /runs": () => ({ id: 21 }) });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    fireEvent.click(await screen.findByRole("button", { name: "Run just this collection" }));
    expect(await screen.findByRole("link", { name: "run #21" })).toHaveAttribute("href", "/activity/queue/21");
    expect(calls.find((c) => c.route === "POST /runs")?.body).toMatchObject({
      mode: "collections",
      libraries: ["Movies"],
      collections: ["Heroes"],
      ignore_schedules: true,
    });
  });
});

describe("The overlay form", () => {
  it("places the badge on the preview and keeps the overlay's shorthand", async () => {
    const overlaySchema = {
      type: "object",
      properties: { overlays: { type: "object", additionalProperties: { $ref: "#/definitions/overlay" } } },
      definitions: {
        overlay: {
          type: "object",
          properties: {
            overlay: {
              oneOf: [
                { type: "string" },
                {
                  type: "object",
                  properties: {
                    name: { type: "string" },
                    horizontal_align: { type: "string", enum: ["left", "center", "right"] },
                    vertical_align: { type: "string", enum: ["top", "center", "bottom"] },
                    back_color: { type: "string" },
                  },
                },
              ],
            },
            plex_search: { type: "object" },
          },
        },
      },
    };
    const calls = mockApi({
      "GET /config/schemas/overlay": () => overlaySchema,
      "GET /config/item?path=overlays.yml&section=overlays&name=4K": () => ({
        path: "overlays.yml",
        hash: "h",
        section: "overlays",
        name: "4K",
        value: { overlay: "4K", plex_search: { all: { resolution: "4K" } } },
        kind: "overlay",
      }),
      "POST /config/item": () => ({ backup: "b", files: [], validation: passed }),
    });
    renderAt("/items?path=overlays.yml&section=overlays&name=4K&library=Movies");

    const preview = await screen.findByLabelText("Poster preview");
    expect(preview).toHaveTextContent("4K");
    await screen.findByRole("option", { name: "right" });
    fireEvent.change(screen.getByLabelText(/Horizontal \(horizontal_align\)/), { target: { value: "right" } });
    expect((preview.firstChild as HTMLElement).style.left).toBe("70%"); // 1000 − 300 wide, at the right edge
    expect(screen.queryByRole("button", { name: "Run just this collection" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    expect((calls.find((c) => c.route === "POST /config/item")?.body as { value: unknown }).value).toEqual({
      overlay: { name: "4K", horizontal_align: "right" },
      plex_search: { all: { resolution: "4K" } },
    });
  });
});
