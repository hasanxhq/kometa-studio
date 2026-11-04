import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConfigLibrary, LibraryCounts, PlexLibrarySummary } from "../../api";
import { mockApi, renderAt } from "../../test-utils";

// Shaped like Kometa's config-schema.json definitions for operations and settings.
const configSchema = {
  type: "object",
  definitions: {
    operations: {
      oneOf: [
        {
          type: "object",
          properties: {
            mass_genre_update: { enum: ["tmdb", "imdb", "tvdb"], description: "Used to update every item's genre." },
            assets_for_all: { type: "boolean" },
            delete_collections: {
              type: "object",
              properties: { managed: { type: "boolean" }, less: { type: "integer" } },
            },
            genre_mapper: { type: "object", properties: {}, patternProperties: { "^.*$": { type: "string" } } },
            mass_poster_update: { type: "boolean" },
            update_blank_track_titles: { type: "boolean", description: "Used to fill blank track titles." },
          },
        },
        { type: "array", items: { type: "object" } },
      ],
    },
    settings: {
      type: "object",
      properties: {
        sync_mode: { enum: ["sync", "append"], description: "Used to set the sync_mode for collections." },
        cache: { type: "boolean", description: "Used to control Kometa's cache database." },
        minimum_items: { type: "integer", minimum: 1 },
      },
    },
  },
};

const counts: LibraryCounts = {
  name: "Movies",
  plex_name: "Movies",
  collection_files: 0,
  overlay_files: 0,
  metadata_files: 0,
  defaults: 0,
  collections: 0,
  overlays: 0,
  operations: 1,
  problems: [],
};

const movies: ConfigLibrary = {
  name: "Movies",
  collection_files: [],
  overlay_files: [],
  metadata_files: [],
  operations: { mass_genre_update: "tmdb", genre_mapper: { Action: "Action/Adventure" } },
  template_variables: {},
  settings: { sync_mode: "append" },
  counts,
};

const plexLibraries: PlexLibrarySummary[] = [{ key: "1", title: "Movies", type: "movie", collections: 0, managed: 0 }];

const ok = { backup: "b1", files: [], validation: { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" } };

function routes(library: ConfigLibrary = movies) {
  return {
    "GET /plex/libraries": () => ({ libraries: plexLibraries }),
    "GET /config": () => ({ path: "/config/config.yml", libraries: [counts], playlist_files: [] }),
    "GET /plex/libraries/1/collections": () => ({ library: { key: "1", title: "Movies", type: "movie" }, collections: [] }),
    "GET /config/libraries/Movies": () => library,
    "GET /config/schemas/config": () => configSchema,
  };
}

describe("Library operations and settings forms", () => {
  it("renders schema fields, enables Save only when dirty, and posts base and values", async () => {
    const calls = mockApi({
      ...routes(),
      "PUT /config/libraries/Movies/operations": () => ok,
    });
    renderAt("/libraries/Movies?tab=operations");

    const form = await screen.findByRole("form", { name: "Library operations" });
    const genre = await within(form).findByLabelText(/Mass genre update/);
    expect(genre).toHaveValue("tmdb");
    expect(within(form).getByText("Edited in the file editor")).toBeInTheDocument();
    expect(within(form).getByText("genre_mapper")).toBeInTheDocument();
    expect(within(form).getByText("More operations")).toBeInTheDocument();

    const save = within(form).getByRole("button", { name: "Save operations" });
    expect(save).toBeDisabled();
    fireEvent.change(genre, { target: { value: "imdb" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((call) => call.route === "PUT /config/libraries/Movies/operations")).toBe(true));
    expect(calls.find((call) => call.route === "PUT /config/libraries/Movies/operations")?.body).toEqual({
      base: { mass_genre_update: "tmdb", genre_mapper: { Action: "Action/Adventure" } },
      values: { mass_genre_update: "imdb", genre_mapper: { Action: "Action/Adventure" } },
    });
    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
  });

  it("saves library settings the same way and shows a refusal", async () => {
    const calls = mockApi({
      ...routes(),
      "PUT /config/libraries/Movies/settings": () =>
        new Response(JSON.stringify({ detail: { message: "The settings for Movies in config.yml changed since you opened them. Reload to see the new ones." } }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
    });
    renderAt("/libraries/Movies?tab=operations");

    const form = await screen.findByRole("form", { name: "Library settings" });
    const sync = await within(form).findByLabelText(/Sync mode/);
    expect(sync).toHaveValue("append");
    const save = within(form).getByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    fireEvent.change(sync, { target: { value: "sync" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((call) => call.route === "PUT /config/libraries/Movies/settings")).toBe(true));
    expect(calls.find((call) => call.route === "PUT /config/libraries/Movies/settings")?.body).toEqual({
      base: { sync_mode: "append" },
      values: { sync_mode: "sync" },
    });
    expect(await screen.findByText(/changed since you opened them/)).toBeInTheDocument();
  });

  it("round-trips list-form operations as a list of blocks", async () => {
    const list: ConfigLibrary = {
      ...movies,
      operations: [
        { mass_genre_update: "tmdb", schedule: "weekly(sunday)" },
        { assets_for_all: true },
      ],
    };
    const calls = mockApi({
      ...routes(list),
      "PUT /config/libraries/Movies/operations": () => ok,
    });
    renderAt("/libraries/Movies?tab=operations");

    expect(await screen.findByText("Operation 1")).toBeInTheDocument();
    expect(screen.getByText("Operation 2")).toBeInTheDocument();
    expect(screen.getAllByText("Edited in the file editor").length).toBeGreaterThan(0);
    expect(screen.getByText("weekly(sunday)")).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Library operations" });
    const genres = within(form).getAllByLabelText(/Mass genre update/);
    fireEvent.change(genres[0], { target: { value: "imdb" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save operations" }));
    await waitFor(() => expect(calls.some((call) => call.route === "PUT /config/libraries/Movies/operations")).toBe(true));
    expect(calls.find((call) => call.route === "PUT /config/libraries/Movies/operations")?.body).toEqual({
      base: [
        { mass_genre_update: "tmdb", schedule: "weekly(sunday)" },
        { assets_for_all: true },
      ],
      values: [
        { mass_genre_update: "imdb", schedule: "weekly(sunday)" },
        { assets_for_all: true },
      ],
    });
  });
});
