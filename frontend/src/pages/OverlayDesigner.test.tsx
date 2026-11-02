import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConfigLibrary, DefaultsCatalogue, FileReference, OverlayLayout, OverlayLibrary, PlexItem } from "../api";
import { mockApi, renderAt } from "../test-utils";

const aligned: OverlayLayout = {
  moved_by: "align",
  variables: { horizontal_align: "left", vertical_align: "top", horizontal_offset: 15, vertical_offset: 15, back_color: "#00000099" },
  conditionals: { back_width: { default: 305, conditions: [] }, back_height: { default: 105, conditions: [] } },
};
const positioned: OverlayLayout = { moved_by: "position", variables: { horizontal_position: "left", vertical_position: "center" }, conditionals: {} };

const entry = (name: string, title: string, layout: OverlayLayout, toggles: DefaultsCatalogue["overlays"][number]["toggles"] = [], types = ["movie", "show"]) => ({ name, group: "overlays" as const, types, title, docs_url: `https://kometa.wiki/${name}`, toggles, layout });

const catalogue: DefaultsCatalogue = {
  collections: [],
  overlays: [
    entry("resolution", "Resolution Overlay", aligned),
    entry("ratings", "Ratings Overlays", positioned),
    entry("status", "Status Overlay", aligned, [
      { key: "airing", label: "Airing", on: true, types: ["movie", "show"] },
      { key: "ended", label: "Ended", on: true, types: ["movie", "show"] },
    ]),
    entry("ribbon", "Ribbon Overlay", aligned),
    entry("episode_info", "Episode Info Overlay", aligned, [], ["show"]),
  ],
};

const ref = (value: string, template_variables: Record<string, unknown> = {}): FileReference => ({ kind: "default", value, template_variables, options: {}, files: [], error: null });

const movies: ConfigLibrary = {
  name: "Movies",
  collection_files: [],
  overlay_files: [ref("resolution", { horizontal_align: "right" }), ref("ratings"), { kind: "file", value: "config/mine.yml", template_variables: {}, options: {}, files: [], error: null }, ref("status")],
  metadata_files: [],
  operations: {},
  template_variables: {},
  settings: {},
  counts: {} as ConfigLibrary["counts"],
};

const shows: ConfigLibrary = { ...movies, name: "TV Shows", overlay_files: [ref("resolution")] };

const configSchema = {
  type: "object",
  definitions: {
    "kometa-default-overlay-path": { type: "object", properties: { default: { type: "string" }, template_variables: { $ref: "#/definitions/template-variables-overlays" } } },
    "template-variables-overlays": {
      type: "object",
      properties: {
        back_color: { type: "string" },
        back_radius: { type: "integer" },
        horizontal_align: { type: "string", enum: ["left", "center", "right"] },
        vertical_align: { type: "string", enum: ["top", "center", "bottom"] },
        horizontal_offset: { type: ["string", "integer"] },
        vertical_offset: { type: ["string", "integer"] },
        horizontal_position: { type: "string" },
        vertical_position: { type: "string" },
        rating1: { type: "string", enum: ["none", "imdb", "tmdb", "critic"] },
        rating1_image: { type: "string", enum: ["imdb", "tmdb", "rt_tomato"] },
        builder_level: { type: "string", enum: ["show", "season", "episode"] },
        use_resolution: { type: "boolean" },
        use_edition: { type: "boolean" },
      },
      patternProperties: { "^use_.*$": { type: "boolean" } },
    },
  },
};

const item = (rating_key: string, title: string, video_resolution: string | null): PlexItem => ({ rating_key, title, type: "movie", year: 2021, thumb: `/library/metadata/${rating_key}/thumb/1`, ids: {}, content_rating: null, audience_rating: null, episodes: null, added_at: null, video_resolution, audio_codec: null });

const status: OverlayLibrary = { library: "Movies", plex_name: "Movies", off: false, files: [], backup: null, last_pass: null, maintainerr: null };

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
  "GET /overlays": () => ({ libraries: [status] }),
  "GET /plex/libraries/1/items": () => ({ items: [item("5", "Dune", "4k"), item("6", "Heat", "1080")], start: 0, total: 2 }),
  "GET /plex/libraries/2/items": () => ({ items: [], start: 0, total: 0 }),
};

const layers = () => screen.findByRole("region", { name: "Layers · Movies" });
const settings = () => screen.getByRole("complementary", { name: "Layer settings" });
const pressed = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });

describe("The overlay designer", () => {
  it("lists the library's overlay defaults as layers, in order, and is reached from Overlays", async () => {
    mockApi({ ...routes, "GET /schedules": () => ({ schedules: [], timezone: "UTC", catch_ups: [] }), "GET /arr": () => ({ settings: { radarr: { enabled: false }, sonarr: { enabled: false } } }) });
    renderAt("/overlays");
    fireEvent.click(await screen.findByRole("link", { name: "Open the overlay designer" }));
    expect(await screen.findByRole("heading", { name: "Overlay designer" })).toBeInTheDocument();

    const list = await layers();
    await waitFor(() => expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Resolutiontop-right↑↓", "Ratingscenter-left↑↓", "Statustop-left↑↓"]));
    expect(within(list).getByText(/Also draws 1 of your own overlay file/)).toBeInTheDocument();
  });

  it("moves a layer with the anchor grid and offsets, live on the preview, and saves its template variables", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/overlay/resolution": () => saved });
    renderAt("/overlays/designer");
    await layers();
    const poster = await screen.findByRole("group", { name: "Overlays on Dune" });
    const badge = await within(poster).findByRole("button", { name: "Select 4K" });
    expect(badge.style.left).toBe("68%"); // right, 15 in: 1000 − 305 − 15
    expect(await screen.findByRole("button", { name: "Top right" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Bottom right" }));
    expect(badge.style.top).toBe(`${((1500 - 105 - 15) / 1500) * 100}%`);
    fireEvent.change(screen.getByLabelText("Offset X"), { target: { value: "40" } });
    expect(badge.style.left).toBe(`${((1000 - 305 - 40) / 1000) * 100}%`);
    expect(within(settings()).getByLabelText("What this writes to config.yml")).toHaveTextContent("- default: resolution template_variables: horizontal_align: right vertical_align: bottom horizontal_offset: 40");

    fireEvent.click(screen.getByRole("button", { name: "Apply on next run" }));
    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/overlay/resolution")?.body).toEqual({ template_variables: { horizontal_align: "right", vertical_align: "bottom", horizontal_offset: 40 } }),
    );
    expect(await screen.findByText(/Kometa draws it on the next overlay run/)).toBeInTheDocument();
  });

  it("takes a variable out when the anchor goes back to where the default starts", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    await layers();
    fireEvent.click(await screen.findByRole("button", { name: "Top left" }));
    expect(within(settings()).getByLabelText("What this writes to config.yml").textContent).toBe("- default: resolution");
  });

  it("moves ratings with their own position variables, and has no offsets for them", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    fireEvent.click(await within(await layers()).findByRole("button", { name: /^Ratings/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Bottom right" }));
    expect(within(settings()).getByLabelText("What this writes to config.yml")).toHaveTextContent("horizontal_position: right vertical_position: bottom");
    expect(screen.queryByLabelText("Offset X")).not.toBeInTheDocument();
    fireEvent.change(await within(settings()).findByRole("combobox", { name: /^Rating 1 \(/ }), { target: { value: "critic" } });
    fireEvent.change(within(settings()).getByRole("combobox", { name: /Rating 1 logo/ }), { target: { value: "rt_tomato" } });
    expect(within(settings()).getByLabelText("What this writes to config.yml")).toHaveTextContent("rating1: critic rating1_image: rt_tomato");
  });

  it("offers what a default can choose under Show when, and says so when it has nothing", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    await layers();
    expect(await within(settings()).findByText(/own resolution and edition/)).toBeInTheDocument();
    fireEvent.click(pressed("Ratings"));
    expect(await within(settings()).findByText(/no choices to make there/)).toBeInTheDocument();
    fireEvent.click(pressed("Status"));
    const when = await screen.findByRole("group", { name: "Show when" });
    fireEvent.click(within(when).getByRole("checkbox", { name: "Ended" }));
    expect(within(settings()).getByLabelText("What this writes to config.yml")).toHaveTextContent("use_ended: false");
  });

  it("selects a layer from the poster", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    await layers();
    fireEvent.click(await screen.findByRole("button", { name: "Select Status" }));
    expect(await screen.findByRole("form", { name: "Variables for Status" })).toBeInTheDocument();
  });

  it("previews on a chosen title, and the same layers on others", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    await layers();
    const small = await screen.findByRole("group", { name: "Overlays on Heat" });
    expect(within(small).getByText("1080P")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Preview on"), { target: { value: "6" } });
    expect(await screen.findByRole("button", { name: "Select 1080P" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Overlays on Dune" })).toBeInTheDocument();
  });

  it("still places overlays when Plex can't be reached", async () => {
    mockApi({ ...routes, "GET /plex/libraries/1/items": () => new Response(JSON.stringify({ detail: "Plex answered HTTP 503" }), { status: 503 }) });
    renderAt("/overlays/designer");
    await layers();
    expect(await screen.findByText(/Can't get posters from Plex/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Select 4K" })).toBeInTheDocument();
  });

  it("adds a layer that suits the library, and turns one off after asking", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/overlay/ribbon": () => saved, "DELETE /config/libraries/Movies/defaults/overlay/resolution": () => saved });
    renderAt("/overlays/designer");
    await layers();
    const add = await screen.findByLabelText("Add a layer");
    await waitFor(() => expect(within(add).getByRole("option", { name: "Ribbon" })).toBeInTheDocument());
    expect(within(add).queryByRole("option", { name: "Episode Info" })).not.toBeInTheDocument(); // shows only
    fireEvent.change(add, { target: { value: "ribbon" } });
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/overlay/ribbon")?.body).toEqual({ template_variables: {} }));

    fireEvent.click(await within(settings()).findByRole("button", { name: "Turn off" }));
    expect(calls.some((c) => c.route.startsWith("DELETE"))).toBe(false);
    fireEvent.click(within(settings()).getByRole("button", { name: "Turn off Resolution" }));
    await waitFor(() => expect(calls.some((c) => c.route === "DELETE /config/libraries/Movies/defaults/overlay/resolution")).toBe(true));
  });

  it("shows Kometa's refusal beside the button", async () => {
    const refusal = { message: "Kometa found problems, so nothing was saved.", validation: { ...saved.validation, ok: false, errors: ["config.yml: back_color doesn't match the pattern"] } };
    mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/overlay/resolution": () => new Response(JSON.stringify({ detail: refusal }), { status: 422 }) });
    renderAt("/overlays/designer");
    await layers();
    fireEvent.click(await screen.findByRole("button", { name: "Bottom left" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply on next run" }));
    expect(await within(settings()).findByText(/back_color doesn't match/)).toBeInTheDocument();
  });

  it("changes the order Kometa draws them in", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/overlay-order": () => saved });
    renderAt("/overlays/designer");
    const list = await layers();
    expect(await within(list).findByRole("button", { name: "Draw Resolution earlier" })).toBeDisabled();
    fireEvent.click(within(list).getByRole("button", { name: "Draw Resolution later" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/overlay-order")?.body).toEqual({ names: ["ratings", "resolution", "status"] }));
  });

  it("asks before unsaved changes are lost, by picking a layer or a library", async () => {
    mockApi(routes);
    renderAt("/overlays/designer");
    await layers();
    fireEvent.click(await screen.findByRole("button", { name: "Bottom left" }));

    fireEvent.click(pressed("Status"));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stay here" }));
    expect(screen.getByRole("form", { name: "Variables for Resolution" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Library"), { target: { value: "TV Shows" } });
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Stay here" }));
    expect(screen.getByLabelText("Library")).toHaveValue("Movies");

    fireEvent.click(pressed("Status"));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Leave without saving" }));
    expect(await screen.findByRole("form", { name: "Variables for Status" })).toBeInTheDocument();
  });

  it("offers Draw on in a show library, and says when overlays are off or Maintainerr's go on top", async () => {
    mockApi({ ...routes, "GET /overlays": () => ({ libraries: [{ ...status, library: "TV Shows", plex_name: "TV Shows", off: true, maintainerr: { collections: ["Leaving"], on_top: true } }] }) });
    renderAt("/overlays/designer?library=TV%20Shows");
    expect(await screen.findByRole("combobox", { name: /Draw on/ })).toBeInTheDocument();
    expect(screen.getByText(/Overlays are turned off for TV Shows/)).toBeInTheDocument();
    expect(screen.getByText(/Maintainerr's overlays still go on top/)).toBeInTheDocument();
  });

  it("starts empty with a way in", async () => {
    mockApi({ ...routes, "GET /config/libraries/Movies": () => ({ ...movies, overlay_files: [] }) });
    renderAt("/overlays/designer");
    expect(await screen.findByText("No overlay defaults yet. Add a layer to start.")).toBeInTheDocument();
    expect(screen.getByText("Pick a layer to move and style it.")).toBeInTheDocument();
  });
});
