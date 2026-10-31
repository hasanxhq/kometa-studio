import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConfigLibrary, DefaultsCatalogue, DefaultToggle, FileReference } from "../api";
import { mockApi, renderAt } from "../test-utils";

// Shaped like Kometa's config schema: an if/then chain picks each default's template variables.
const configSchema = {
  type: "object",
  definitions: {
    "kometa-default-collection-path": {
      type: "object",
      allOf: [
        {
          if: { properties: { default: { const: "streaming" } }, required: ["default"] },
          then: { properties: { template_variables: { $ref: "#/definitions/streaming-template-vars" } } },
          else: {
            if: { properties: { default: { const: "basic" } }, required: ["default"] },
            then: { properties: { template_variables: { $ref: "#/definitions/chart-template-vars" } } },
          },
        },
      ],
      properties: { default: { type: "string" }, template_variables: { type: "object" } },
    },
    "kometa-default-overlay-path": { type: "object", properties: { default: { type: "string" }, template_variables: { type: "object" } } },
    "streaming-template-vars": {
      type: "object",
      properties: {
        region: { type: "string", description: "Where you stream from" },
        use_all: { type: "boolean", description: "Every collection, unless turned off one by one" },
        sort_prefix: { type: "string" },
        originals_only: { type: "boolean" },
        collection_mode: { type: "string", enum: ["default", "hide", "hide_items", "show_items"] },
      },
      patternProperties: { "^use_(?!all$).+$": { type: "boolean", description: "Turn one collection off" } },
    },
    "chart-template-vars": { type: "object", properties: { limit: { type: "integer" } } },
    "template-variables-library": { type: "object", properties: { sep_style: { type: "string", enum: ["blue", "purple", "gray"] } } },
  },
};

const entry = (name: string, group: string, types: string[], title: string, toggles: DefaultToggle[] = []) => ({ name, group, types, title, docs_url: `https://kometa.wiki/en/latest/defaults/${group}/${name}`, toggles });
const toggle = (key: string, label: string, on = true): DefaultToggle => ({ key, label, on, types: ["movie", "show"] });

const catalogue = {
  collections: [
    entry("basic", "chart", ["movie", "show"], "Basic Charts Collections"),
    entry("oscars", "award", ["movie", "show"], "Oscars Collections"),
    entry("streaming", "both", ["movie", "show"], "Streaming Collections", [toggle("netflix", "Netflix"), toggle("disney", "Disney+"), toggle("rare", "Rare one", false), { ...toggle("anime", "Anime only"), types: ["show"] }]),
    entry("network", "show", ["show"], "Network Collections"),
  ],
  overlays: [entry("resolution", "overlays", ["movie", "show"], "Resolution Overlays"), entry("content_rating_us_show", "overlays", ["show"], "US Show Content Rating")],
} as DefaultsCatalogue;

const ref = (value: string, template_variables: Record<string, unknown> = {}): FileReference => ({ kind: "default", value, template_variables, options: {}, files: [], error: null });

const movies: ConfigLibrary = {
  name: "Movies",
  collection_files: [ref("streaming", { region: "GB", use_netflix: false })],
  overlay_files: [],
  metadata_files: [],
  operations: {},
  template_variables: { sep_style: "purple" },
  settings: {},
  counts: {} as ConfigLibrary["counts"],
};

const shows: ConfigLibrary = { ...movies, name: "TV Shows", collection_files: [], template_variables: {} };

const saved = { backup: "b", files: [{ path: "config.yml", hash: "h" }], validation: { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" } };

const routes = {
  "GET /plex/libraries": () => ({
    libraries: [
      { key: "1", title: "Movies", type: "movie", collections: 0, managed: 0 },
      { key: "2", title: "TV Shows", type: "show", collections: 0, managed: 0 },
    ],
  }),
  "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }, { name: "TV Shows", plex_name: "TV Shows" }], playlist_files: [] }),
  "GET /config/libraries/Movies": () => movies,
  "GET /config/libraries/TV%20Shows": () => shows,
  "GET /config/defaults": () => catalogue,
  "GET /config/schemas/config": () => configSchema,
};

const gallery = () => screen.findByRole("list", { name: "Kometa's defaults" });
const names = () => within(screen.getByRole("list", { name: "Kometa's defaults" })).getAllByRole("listitem").map((li) => li.getAttribute("aria-label"));
const card = (name: string) => screen.findByRole("listitem", { name });
const pick = async (name: string) => fireEvent.click(within(await card(name)).getByRole("button", { name: new RegExp(`^Customize ${name}`) }));

describe("The Defaults gallery", () => {
  it("is a page of its own in the sidebar, applied to one library at a time", async () => {
    mockApi(routes);
    renderAt("/");
    fireEvent.click(await screen.findByRole("link", { name: "Defaults" }));
    expect(await screen.findByRole("heading", { name: "Defaults gallery" })).toBeInTheDocument();

    await waitFor(() => expect(names()).toEqual(["Basic Charts Collections", "Oscars Collections", "Streaming Collections"])); // a movie library: no show-only defaults
    expect(screen.getByLabelText("Apply to")).toHaveValue("Movies");
    expect(within(await card("Streaming Collections")).getByRole("checkbox", { name: "Enabled" })).toBeChecked();
    expect(within(await card("Streaming Collections")).getByText("One collection per service you own")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Apply to"), { target: { value: "TV Shows" } });
    await waitFor(() => expect(names()).toContain("Network Collections"));
    expect(within(await card("Streaming Collections")).getByRole("checkbox", { name: "Enabled" })).not.toBeChecked();
  });

  it("says so when config.yml has no library to apply them to", async () => {
    mockApi({ ...routes, "GET /config": () => ({ path: "/config/config.yml", libraries: [], playlist_files: [] }) });
    renderAt("/defaults");
    expect(await screen.findByRole("link", { name: "Add one from Libraries" })).toHaveAttribute("href", "/libraries");
  });

  it("filters by type, category, what's on and a search, and turns a default on", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/collection/oscars": () => saved });
    renderAt("/libraries/Movies?tab=defaults");
    await gallery();
    await waitFor(() => expect(names()).toEqual(["Basic Charts Collections", "Oscars Collections", "Streaming Collections"]));

    fireEvent.click(screen.getByRole("button", { name: "Award" }));
    expect(names()).toEqual(["Oscars Collections"]);
    fireEvent.click(screen.getByRole("button", { name: "Enabled (1)" }));
    expect(names()).toEqual(["Streaming Collections"]);
    fireEvent.click(screen.getByRole("button", { name: "Overlays" }));
    expect(names()).toEqual(["Resolution Overlays"]);
    fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    fireEvent.change(screen.getByLabelText("Search Kometa's defaults"), { target: { value: "basic" } });
    expect(names()).toEqual(["Basic Charts Collections"]);
    fireEvent.change(screen.getByLabelText("Search Kometa's defaults"), { target: { value: "" } });

    fireEvent.click(within(await card("Oscars Collections")).getByRole("checkbox", { name: "Enabled" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/oscars")?.body).toEqual({ template_variables: {} }));
    expect(await screen.findByText(/Added Oscars Collections/)).toBeInTheDocument();
  });

  it("customises a default with switches and shows what that writes", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/collection/streaming": () => saved });
    renderAt("/defaults");
    await pick("Streaming Collections");
    expect(await within(await card("Streaming Collections")).findByText("Editing")).toBeInTheDocument();

    const panel = screen.getByRole("complementary", { name: "Customize" });
    const form = within(panel).getByRole("form", { name: "Variables for Streaming Collections" });
    expect(within(panel).getByRole("link", { name: "Kometa wiki" })).toHaveAttribute("href", "https://kometa.wiki/en/latest/defaults/both/streaming");
    const services = within(form).getByRole("group", { name: "Services to include" });
    expect(within(services).getByRole("checkbox", { name: "Netflix" })).not.toBeChecked(); // use_netflix: false
    expect(within(services).getByRole("checkbox", { name: "Disney+" })).toBeChecked(); // on unless it says otherwise
    expect(within(services).getByRole("checkbox", { name: "Rare one" })).not.toBeChecked(); // this one starts off
    expect(within(services).queryByRole("checkbox", { name: "Anime only" })).not.toBeInTheDocument(); // shows only
    await waitFor(() => expect(within(form).getByRole("textbox", { name: /Watch region/ })).toHaveValue("GB"));

    fireEvent.click(within(services).getByRole("checkbox", { name: "Netflix" })); // back to Kometa's default: use_netflix goes
    fireEvent.click(within(services).getByRole("checkbox", { name: "Disney+" }));
    fireEvent.click(within(services).getByRole("checkbox", { name: "Rare one" }));
    fireEvent.click(within(form).getByRole("checkbox", { name: "Originals only" }));
    fireEvent.change(within(form).getByRole("textbox", { name: /Watch region/ }), { target: { value: "IN" } });
    fireEvent.change(within(form).getByRole("combobox", { name: /Show in Plex/ }), { target: { value: "hide_items" } });
    expect(within(form).getByRole("option", { name: "Hide items, show collection" })).toBeInTheDocument();
    expect(within(form).getByLabelText("What this writes to config.yml")).toHaveTextContent("- default: streaming template_variables: region: IN use_disney: false use_rare: true originals_only: true collection_mode: hide_items");

    fireEvent.click(within(form).getByRole("button", { name: "Save to Movies" }));
    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/streaming")?.body).toEqual({
        template_variables: { region: "IN", use_disney: false, use_rare: true, originals_only: true, collection_mode: "hide_items" },
      }),
    );
    expect(await within(panel).findByText("Saved to Movies.")).toBeInTheDocument();
  });

  it("follows use_all: with everything off, a switch turns one on", async () => {
    const calls = mockApi({
      ...routes,
      "GET /config/libraries/Movies": () => ({ ...movies, collection_files: [ref("streaming", { use_all: false })] }),
      "PUT /config/libraries/Movies/defaults/collection/streaming": () => saved,
    });
    renderAt("/defaults");
    await pick("Streaming Collections");
    const form = await screen.findByRole("form", { name: "Variables for Streaming Collections" });
    expect(within(form).getByRole("checkbox", { name: "Disney+" })).not.toBeChecked();
    fireEvent.click(within(form).getByRole("checkbox", { name: "Disney+" }));
    fireEvent.click(within(form).getByRole("button", { name: "Save to Movies" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/streaming")?.body).toEqual({ template_variables: { use_all: false, use_disney: true } }));
  });

  it("keeps other variables under More variables, from the schema or as YAML", async () => {
    const calls = mockApi({
      ...routes,
      "GET /config/libraries/Movies": () => ({ ...movies, collection_files: [ref("streaming", { sort_prefix: "!", use_hulu: false, mystery: 1 })] }),
      "PUT /config/libraries/Movies/defaults/collection/streaming": () => saved,
    });
    renderAt("/defaults");
    await pick("Streaming Collections");
    const form = await screen.findByRole("form", { name: "Variables for Streaming Collections" });
    await within(form).findByText("More variables (3)");
    await within(form).findByText("Turn one collection off"); // use_hulu isn't a toggle Kometa's file lists; its pattern is known
    expect(within(form).getByLabelText("sort_prefix")).toHaveValue("!");
    expect(within(form).getByText(/schema doesn't list this variable/)).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Add a variable"), { target: { value: "use_all" } });
    fireEvent.change(within(form).getByLabelText("use_all"), { target: { value: "false" } });
    fireEvent.click(within(form).getByRole("button", { name: "Remove mystery" }));
    fireEvent.click(within(form).getByRole("button", { name: "Save to Movies" }));
    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/streaming")?.body).toEqual({ template_variables: { sort_prefix: "!", use_hulu: false, use_all: false } }),
    );
  });

  it("saves a default that's off with its variables, which turns it on", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/collection/basic": () => saved });
    renderAt("/defaults");
    await pick("Basic Charts Collections");
    const form = await screen.findByRole("form", { name: "Variables for Basic Charts Collections" });
    expect(within(form).getByLabelText("What this writes to config.yml")).toHaveTextContent("- default: basic");
    fireEvent.click(within(form).getByRole("button", { name: "Save to Movies" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/basic")?.body).toEqual({ template_variables: {} }));
  });

  it("turns a default off, after asking", async () => {
    const calls = mockApi({ ...routes, "DELETE /config/libraries/Movies/defaults/collection/streaming": () => saved });
    renderAt("/defaults");
    const streaming = await card("Streaming Collections");
    fireEvent.click(within(streaming).getByRole("checkbox", { name: "Enabled" }));
    expect(calls.some((c) => c.route.startsWith("DELETE"))).toBe(false);
    expect(within(streaming).getByText(/Kometa stops building these/)).toBeInTheDocument();
    fireEvent.click(within(streaming).getByRole("button", { name: "Keep" }));
    fireEvent.click(within(streaming).getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(within(streaming).getByRole("button", { name: "Turn off Streaming Collections" }));
    await waitFor(() => expect(calls.some((c) => c.route === "DELETE /config/libraries/Movies/defaults/collection/streaming")).toBe(true));
  });

  it("still shows a default this Kometa doesn't have, so it can be turned off", async () => {
    mockApi({ ...routes, "GET /config/libraries/Movies": () => ({ ...movies, collection_files: [ref("retired")] }) });
    renderAt("/defaults");
    expect(within(await card("retired")).getByRole("checkbox", { name: "Enabled" })).toBeChecked();
  });

  it("sets the library's own variables when no card is picked, and shows Kometa's refusal", async () => {
    const refusal = { message: "Kometa found problems, so nothing was saved.", validation: { ...saved.validation, ok: false, errors: ["config.yml: sep_style must be one of …"] } };
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/template-variables": () => new Response(JSON.stringify({ detail: refusal }), { status: 422 }) });
    renderAt("/libraries/Movies?tab=defaults");
    const form = await screen.findByRole("form", { name: "Variables for Movies" });
    await waitFor(() => expect(within(form).getByRole("combobox", { name: /Separator style/ })).toHaveValue("purple"));
    fireEvent.change(within(form).getByRole("combobox", { name: /Separator style/ }), { target: { value: "blue" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save variables" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/template-variables")?.body).toEqual({ template_variables: { sep_style: "blue" } }));
    expect(await within(form).findByText(/sep_style must be one of/)).toBeInTheDocument();
  });
});
