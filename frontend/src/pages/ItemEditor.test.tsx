import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Item, Validation } from "../api";
import { mockApi, renderAt } from "../test-utils";
import { isBuilder, sourceGroups } from "./ItemEditor";

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
        mal_id: { type: "integer" },
        tvdb_show: { type: "integer" },
        mdblist_list: { type: "string" },
        summary: { type: "string" },
        sort_title: { type: "string" },
        sync_mode: { type: "string", enum: ["sync", "append"] },
        collection_order: { type: "string" },
        minimum_items: { type: "integer", minimum: 1 },
        visible_home: { oneOf: [{ type: "boolean" }, { type: "string" }] },
        build_collection: { type: "boolean", description: "Build it in Plex" },
        template: { type: "object" },
        filters: { oneOf: [{ type: "object" }, { type: "array", items: { type: "object" } }] },
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

  it("starts a new file for the collection and adds it to the library", async () => {
    const library = {
      name: "Movies",
      collection_files: [
        { kind: "default", value: "basic", template_variables: {}, options: {}, files: [{ path: "defaults/chart/basic.yml" }], error: null },
        { kind: "file", value: "config/Movies.yml", template_variables: {}, options: {}, files: [{ path: "Movies.yml" }], error: null },
      ],
      overlay_files: [],
    };
    const calls = mockApi({
      "GET /config/schemas/collection": () => collectionSchema,
      "GET /config/libraries/Movies": () => library,
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }),
      "POST /config/item": () => ({ backup: "b", files: [{ path: "Pixar.yml", hash: "p" }, { path: "config.yml", hash: "c" }], validation: passed }),
      "GET /config/item?path=Pixar.yml&section=collections&name=Pixar": () => ({ ...heroes, path: "Pixar.yml", name: "Pixar", value: { tmdb_collection: [1] } }),
    });
    renderAt("/items?section=collections&new=1&library=Movies");

    expect(await screen.findByText("New collection in a new file")).toBeInTheDocument();
    const file = screen.getByLabelText("File");
    await screen.findByRole("option", { name: "Movies.yml" }); // the library's own files; not Kometa's defaults
    expect(screen.queryByRole("option", { name: "defaults/chart/basic.yml" })).not.toBeInTheDocument();
    expect(file).toHaveDisplayValue("A new file…");
    expect(screen.getByLabelText("New file's name")).toHaveValue("Movies Collections.yml"); // Movies.yml is taken
    fireEvent.change(screen.getByLabelText("New file's name"), { target: { value: "Pixar" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pixar" } });
    await screen.findByRole("option", { name: "tmdb_collection" });
    fireEvent.change(screen.getByLabelText("Add a source"), { target: { value: "tmdb_collection" } });
    fireEvent.click(screen.getByRole("button", { name: "Add collection" }));

    await waitFor(() =>
      expect(calls.find((c) => c.route === "POST /config/item")?.body).toMatchObject({
        path: "Pixar.yml",
        base_hash: null,
        library: "Movies",
        name: "Pixar",
        create: true,
      }),
    );
    expect(await screen.findByText("Pixar.yml", { selector: "span.font-mono" })).toBeInTheDocument(); // now editing it in its new file
  });

  it("can put a new collection in one of the library's files instead", async () => {
    mockApi({
      "GET /config/schemas/collection": () => collectionSchema,
      "GET /config/libraries/Movies": () => ({
        name: "Movies",
        collection_files: [{ kind: "file", value: "config/Movies.yml", template_variables: {}, options: {}, files: [{ path: "Movies.yml" }], error: null }],
        overlay_files: [],
      }),
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }),
    });
    renderAt("/items?section=collections&new=1&library=Movies");
    await screen.findByRole("option", { name: "Movies.yml" });
    fireEvent.change(screen.getByLabelText("File"), { target: { value: "Movies.yml" } });
    expect(await screen.findByText("New collection in Movies.yml")).toBeInTheDocument();
    expect(screen.queryByLabelText("New file's name")).not.toBeInTheDocument();
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

describe("Where a collection shows", () => {
  const heroesWith = (value: Record<string, unknown>) => ({
    ...routes,
    "GET /config/item?path=Movies.yml&section=collections&name=Heroes": () => ({ ...heroes, value: { ...heroes.value, ...value } }),
    "POST /config/item": () => ({ backup: "b", files: [], validation: passed }),
  });
  const open = () => renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
  const saved = async (calls: { route: string; body: unknown }[]) => {
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    return (calls.find((c) => c.route === "POST /config/item")?.body as { value: Record<string, unknown> }).value;
  };

  it("ticks a box to show it", async () => {
    const calls = mockApi(heroesWith({}));
    open();
    const home = await screen.findByRole("checkbox", { name: "My home" });
    expect(home).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Friends' home" })).toBeInTheDocument();

    fireEvent.click(home);

    expect((await saved(calls)).visible_home).toBe(true);
  });

  it("writes false when a saved yes is unticked, so Kometa changes Plex", async () => {
    const calls = mockApi(heroesWith({ visible_home: true }));
    open();
    const home = await screen.findByRole("checkbox", { name: "My home" });
    expect(home).toBeChecked();

    fireEvent.click(home);

    expect((await saved(calls)).visible_home).toBe(false);
  });

  it("goes back to not set when a box that was never set is ticked and unticked", async () => {
    const calls = mockApi(heroesWith({}));
    open();
    const home = await screen.findByRole("checkbox", { name: "My home" });

    fireEvent.click(home);
    fireEvent.click(home);

    expect(home).not.toBeChecked();
    expect(await saved(calls)).not.toHaveProperty("visible_home");
  });

  it("keeps a schedule as YAML, and the others as boxes", async () => {
    const calls = mockApi(heroesWith({ visible_home: "weekly(sunday)" }));
    open();

    expect(await screen.findByLabelText("My home")).toHaveValue("weekly(sunday)");
    expect(screen.queryByRole("checkbox", { name: "My home" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Friends' home" }));

    expect(await saved(calls)).toMatchObject({ visible_home: "weekly(sunday)", visible_shared: true });
  });

  it("offers YAML for all of them under Show Advanced", async () => {
    localStorage.setItem("studio.showAdvanced", "true");
    mockApi(heroesWith({ visible_home: true }));
    open();

    expect(await screen.findByLabelText(/My home/)).toHaveValue("true"); // yes or no as a control, since the schema's shapes allow it
    expect(screen.getByLabelText(/Friends' home/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "My home" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Turn on Show Advanced/)).not.toBeInTheDocument();
  });
});

describe("Leaving the form", () => {
  async function editHeroes() {
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    fireEvent.change(await screen.findByLabelText(/Summary/), { target: { value: "Not saved yet." } });
  }

  it("asks before leaving unsaved edits, and stays if told to", async () => {
    mockApi(routes);
    await editHeroes();

    fireEvent.click(screen.getByRole("link", { name: "Edit the whole file as YAML" }));
    const dialog = await screen.findByRole("alertdialog", { name: "You have unsaved changes" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay here" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByDisplayValue("Not saved yet.")).toBeInTheDocument();
  });

  it("leaves if told to", async () => {
    mockApi({ ...routes, "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }) });
    await editHeroes();

    fireEvent.click(screen.getByRole("link", { name: "Edit the whole file as YAML" }));
    fireEvent.click(await screen.findByRole("button", { name: "Leave without saving" }));

    expect(await screen.findByRole("heading", { name: "Movies.yml" })).toBeInTheDocument();
  });

  it("doesn't ask when nothing has changed, or once it's saved", async () => {
    mockApi({ ...routes, "POST /config/item": () => ({ backup: "b", files: [], validation: passed }), "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }) });
    await editHeroes();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Kometa checked it, and it's saved.");

    fireEvent.click(screen.getByRole("link", { name: "Edit the whole file as YAML" }));

    expect(await screen.findByRole("heading", { name: "Movies.yml" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("doesn't ask after deleting what was being edited", async () => {
    mockApi({ ...routes, "POST /config/item": () => ({ backup: "b", files: [], validation: passed }) });
    await editHeroes();

    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Heroes" }));

    await waitFor(() => expect(screen.queryByLabelText(/Summary/)).not.toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("doesn't ask when a new collection changes file", async () => {
    mockApi({
      ...routes,
      "GET /config/libraries/Movies": () => ({
        name: "Movies",
        collection_files: [{ kind: "file", value: "config/Movies.yml", template_variables: {}, options: {}, files: [{ path: "Movies.yml" }], error: null }],
        overlay_files: [],
      }),
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections: {}\n", hash: "h1", hidden: 0, kind: "collection" }),
    });
    renderAt("/items?section=collections&new=1&library=Movies");
    await screen.findByRole("option", { name: "Movies.yml" });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pixar" } });
    fireEvent.change(screen.getByLabelText("File"), { target: { value: "Movies.yml" } });

    expect(await screen.findByText("New collection in Movies.yml")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
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

describe("Filter chips", () => {
  it("shows a collection's filters in words, adds year, rating and genre ones, and takes one out", async () => {
    const filtered: Item = { ...heroes, value: { tmdb_collection: [556], filters: { "year.gte": 2000, "genre.not": "Horror", "has_overlay": false } } };
    const calls = mockApi({
      ...routes,
      "GET /config/item?path=Movies.yml&section=collections&name=Heroes": () => filtered,
      "POST /config/item": () => ({ backup: "b", files: [], validation: passed }),
    });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    const chips = await screen.findByRole("list", { name: "Filters" });
    expect([...chips.querySelectorAll("li")].map((li) => li.firstChild?.textContent)).toEqual(["Year ≥ 2000", "Genre isn't: Horror", "Not has overlay"]);

    const add = screen.getByRole("group", { name: "Add a filter" });
    fireEvent.change(within(add).getByRole("combobox"), { target: { value: "critic_rating.gte" } });
    fireEvent.change(within(add).getByRole("textbox"), { target: { value: "11" } });
    expect(within(add).getByRole("button", { name: "Add" })).toBeDisabled(); // ratings are out of 10
    fireEvent.change(within(add).getByRole("textbox"), { target: { value: "7.5" } });
    fireEvent.click(within(add).getByRole("button", { name: "Add" }));
    fireEvent.change(within(add).getByRole("combobox"), { target: { value: "genre.not" } });
    fireEvent.change(within(add).getByRole("textbox"), { target: { value: "Documentary, Horror" } });
    fireEvent.click(within(add).getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Not has overlay" }));
    expect(screen.getByText("Critic rating ≥ 7.5")).toBeInTheDocument();
    expect(screen.getByText("Genre isn't: Horror, Documentary")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect((calls.find((c) => c.route === "POST /config/item")?.body as { value: unknown }).value).toEqual({
      tmdb_collection: [556],
      filters: { "year.gte": 2000, "genre.not": ["Horror", "Documentary"], "critic_rating.gte": 7.5 },
    });
  });

  it("leaves several filter sets to Show Advanced", async () => {
    mockApi({ ...routes, "GET /config/item?path=Movies.yml&section=collections&name=Heroes": () => ({ ...heroes, value: { tmdb_collection: [556], filters: [{ "year.gte": 2000 }, { genre: "Comedy" }] } }) });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    expect(await screen.findByText(/1 more setting is set here/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Add a filter" })).toBeNull();
  });
});

describe("Adding a collection's missing items", () => {
  const counts = { collection_files: 1, overlay_files: 0, metadata_files: 0, defaults: 0, collections: 1, overlays: 0, operations: 0, problems: [] };
  const connection = (url: string | null, everywhere = false) => ({
    url,
    token: url ? "…ab12" : null,
    root_folder_path: null,
    quality_profile: null,
    add_missing: everywhere,
    search: everywhere,
    username: null,
    has_password: false,
    status: null,
  });
  const libraries = (type: string, radarr: ReturnType<typeof connection>) => ({
    ...routes,
    "GET /plex/libraries": () => ({ libraries: [{ key: "1", title: "Movies", type, collections: 1, managed: 1 }] }),
    "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies", ...counts }], playlist_files: [] }),
    "GET /settings/arr": () => ({ settings: {}, connections: { radarr, sonarr: connection(null) }, pending: {}, skipped: { radarr: [], sonarr: [] }, libraries: [] }),
    "POST /config/item": () => ({ backup: "b", files: [], validation: passed }),
  });
  const saved = (calls: { route: string; body: unknown }[]) => (calls.find((c) => c.route === "POST /config/item")?.body as { value: Record<string, unknown> }).value;

  it("sends a movie library's missing items to Radarr, with a warning, and can search for them", async () => {
    const calls = mockApi(libraries("movie", connection("http://radarr:7878")));
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    const add = await screen.findByRole("checkbox", { name: /Add missing movies to Radarr/ });
    expect(add).not.toBeChecked();
    expect(screen.getByText(/use with caution: big lists and collections can send dozens of movies to Radarr at once/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Search for them/ })).toBeNull();

    fireEvent.click(add);
    fireEvent.click(screen.getByRole("checkbox", { name: /Search for them/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    expect(saved(calls)).toEqual({ ...heroes.value, radarr_add_missing: true, radarr_search: true });
  });

  it("writes a setting only where this collection differs from config.yml's radarr block", async () => {
    const calls = mockApi(libraries("movie", connection("http://radarr:7878", true)));
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    const add = await screen.findByRole("checkbox", { name: /Add missing movies to Radarr/ });
    expect(add).toBeChecked(); // on for every collection
    expect(screen.getByText(/config.yml turns this on for every collection/)).toBeInTheDocument();

    fireEvent.click(add);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    expect(saved(calls)).toEqual({ ...heroes.value, radarr_add_missing: false });
  });

  it("can't be ticked until Radarr is connected, and isn't offered for a music library", async () => {
    mockApi(libraries("movie", connection(null)));
    const { unmount } = renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    expect(await screen.findByRole("checkbox", { name: /Add missing movies to Radarr/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Connect it in Settings → Connect/ })).toHaveAttribute("href", "/settings/connect");
    unmount();

    mockApi(libraries("artist", connection("http://radarr:7878")));
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");
    expect(await screen.findByDisplayValue("Everything Heroes.")).toBeInTheDocument();
    expect(screen.queryByText("Missing items")).toBeNull();
  });
});

describe("The source list", () => {
  it("groups sources by service and greys out the ones that aren't set up", async () => {
    mockApi({ ...routes, "GET /config/sources?library=Movies": () => ({ unavailable: { mal: "not set up" } }) });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    await screen.findByRole("option", { name: "mal_id" });
    await waitFor(() => expect(screen.getByRole("option", { name: "mal_id" })).toBeDisabled()); // it moves group once Studio knows
    expect(screen.getByRole("option", { name: "mal_id" }).closest("optgroup")).toHaveAttribute("label", "MyAnimeList (not set up)");
    const usable = screen.getByRole("option", { name: "mdblist_list" });
    expect(usable).toBeEnabled();
    expect(usable.closest("optgroup")).toHaveAttribute("label", "Most used");
    expect(screen.getByRole("link", { name: "Settings → Connect" })).toHaveAttribute("href", "/settings/connect");
  });

  it("leaves a source that's already in the collection alone", async () => {
    mockApi({ ...routes, "GET /config/sources?library=Movies": () => ({ unavailable: { tmdb: "not set up" } }) });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    await waitFor(() => expect(screen.getByRole("option", { name: "tmdb_trending_weekly" })).toBeDisabled());
    expect(screen.getByLabelText("tmdb_collection")).toHaveValue("- 556");
  });

  it("offers everything when Studio can't tell what's set up", async () => {
    mockApi(routes);
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    expect(await screen.findByRole("option", { name: "mal_id" })).toBeEnabled();
    expect(screen.queryByText(/Greyed-out sources/)).toBeNull();
  });

  it("puts the most used first, then services by name, then the ones that can't be used", () => {
    const keys = ["tmdb_collection", "imdb_list", "tmdb_actor", "anilist_id", "mal_id", "tmdb_list", "trakt_description", "mojo_world"];
    expect(sourceGroups(keys, { mal: "not set up", trakt: "no longer supported by Kometa" })).toEqual([
      { label: "Most used", keys: ["tmdb_collection", "imdb_list", "tmdb_list"] },
      { label: "AniList", keys: ["anilist_id"] },
      { label: "Box Office Mojo", keys: ["mojo_world"] },
      { label: "TMDb", keys: ["tmdb_actor"] },
      { label: "MyAnimeList (not set up)", keys: ["mal_id"], greyed: "setup" },
      { label: "Trakt (no longer supported by Kometa)", keys: ["trakt_description"], greyed: "setup" },
    ]);
  });

  it("greys out what the library's type can't use, even if its service isn't set up", () => {
    const keys = ["tmdb_movie", "tmdb_show", "imdb_chart", "serializd_list", "mojo_world", "mal_id"];
    expect(sourceGroups(keys, { serializd: "not set up", mal: "not set up" }, "movie")).toEqual([
      { label: "Most used", keys: ["tmdb_movie", "imdb_chart"] },
      { label: "Box Office Mojo", keys: ["mojo_world"] },
      { label: "MyAnimeList (not set up)", keys: ["mal_id"], greyed: "setup" },
      { label: "TV libraries only", keys: ["tmdb_show", "serializd_list"], greyed: "library" },
    ]);
    expect(sourceGroups(keys, {}, "show").at(-1)).toEqual({ label: "Movie libraries only", keys: ["tmdb_movie", "mojo_world"], greyed: "library" });
    // Nothing is greyed for a type until Plex says what the library is.
    expect(sourceGroups(keys, {}).some((group) => group.greyed)).toBe(false);
  });

  it("leaves a music library only what Kometa allows there", () => {
    const groups = sourceGroups(["plex_search", "plex_all", "smart_filter", "tmdb_poster", "tmdb_movie", "imdb_chart"], {}, "artist");
    expect(groups.at(-1)).toEqual({ label: "Not for music libraries", keys: ["tmdb_movie", "imdb_chart"], greyed: "library" });
    expect(groups.flatMap((group) => (group.greyed ? [] : group.keys)).sort()).toEqual(["plex_all", "plex_search", "smart_filter", "tmdb_poster"]);
  });

  it("greys out a show-only source in a movie library, without pointing to Connect", async () => {
    const counts = { collection_files: 1, overlay_files: 0, metadata_files: 0, defaults: 0, collections: 1, overlays: 0, operations: 0, problems: [] };
    mockApi({
      ...routes,
      "GET /plex/libraries": () => ({ libraries: [{ key: "1", title: "Movies", type: "movie", collections: 1, managed: 1 }] }),
      "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies", ...counts }], playlist_files: [] }),
    });
    renderAt("/items?path=Movies.yml&section=collections&name=Heroes&library=Movies");

    await waitFor(() => expect(screen.getByRole("option", { name: "tvdb_show" })).toBeDisabled());
    expect(screen.getByRole("option", { name: "tvdb_show" }).closest("optgroup")).toHaveAttribute("label", "TV libraries only");
    expect(screen.queryByText(/Greyed-out sources/)).toBeNull();
  });
});

describe("isBuilder", () => {
  it("counts only Kometa's Radarr and Sonarr builders as sources, not their settings", () => {
    expect(["radarr_all", "sonarr_taglist", "radarr_add_missing", "radarr_search", "sonarr_tag", "tmdb_collection", "smart_label"].filter(isBuilder)).toEqual([
      "radarr_all",
      "sonarr_taglist",
      "tmdb_collection",
      "smart_label",
    ]);
  });
});
