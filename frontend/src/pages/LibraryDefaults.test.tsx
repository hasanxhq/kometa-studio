import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConfigLibrary, DefaultsCatalogue, FileReference } from "../api";
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
      },
      patternProperties: { "^use_(?!all$).+$": { type: "boolean", description: "Turn one collection off" } },
    },
    "chart-template-vars": { type: "object", properties: { limit: { type: "integer" } } },
    "template-variables-library": { type: "object", properties: { sep_style: { type: "string", enum: ["blue", "purple", "gray"] } } },
  },
};

const entry = (name: string, group: string, types: string[], title: string) => ({ name, group, types, title, docs_url: `https://kometa.wiki/en/latest/defaults/${group}/${name}` });

const catalogue = {
  collections: [
    entry("basic", "chart", ["movie", "show"], "Basic Charts Collections"),
    entry("oscars", "award", ["movie", "show"], "Oscars Collections"),
    entry("streaming", "both", ["movie", "show"], "Streaming Collections"),
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

const saved = { backup: "b", files: [{ path: "config.yml", hash: "h" }], validation: { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" } };

const routes = {
  "GET /plex/libraries": () => ({ libraries: [{ key: "1", title: "Movies", type: "movie", collections: 0, managed: 0 }] }),
  "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }], playlist_files: [] }),
  "GET /config/libraries/Movies": () => movies,
  "GET /config/defaults": () => catalogue,
  "GET /config/schemas/config": () => configSchema,
};

describe("A library's defaults", () => {
  it("lists those in use and the rest that suit the library, and adds one", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/collection/oscars": () => saved });
    renderAt("/libraries/Movies?tab=defaults");

    const inUse = (await screen.findByRole("heading", { name: "In use (1)" })).closest("section")!;
    const streaming = await within(inUse).findByRole("listitem", { name: "Streaming Collections" });
    expect(streaming).toHaveTextContent("region: GB · use_netflix: false");
    expect(within(streaming).getByRole("link", { name: "Kometa wiki" })).toHaveAttribute("href", "https://kometa.wiki/en/latest/defaults/both/streaming");

    const gallery = screen.getByRole("list", { name: "Kometa's defaults" });
    const names = () => within(gallery).getAllByRole("listitem").map((li) => li.getAttribute("aria-label"));
    expect(names()).toEqual(["Basic Charts Collections", "Oscars Collections", "Resolution Overlays"]); // a movie library: no show-only defaults
    fireEvent.click(screen.getByRole("button", { name: "Awards (1)" }));
    expect(names()).toEqual(["Oscars Collections"]);
    fireEvent.click(screen.getByRole("button", { name: "All (3)" }));
    fireEvent.change(screen.getByLabelText("Search Kometa's defaults"), { target: { value: "resol" } });
    expect(names()).toEqual(["Resolution Overlays"]);
    fireEvent.change(screen.getByLabelText("Search Kometa's defaults"), { target: { value: "" } });

    fireEvent.click(within(within(gallery).getByRole("listitem", { name: "Oscars Collections" })).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/oscars")?.body).toEqual({ template_variables: {} }));
    expect(await screen.findByText(/Added Oscars Collections/)).toBeInTheDocument();
  });

  it("edits a default's variables with fields from Kometa's schema", async () => {
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/defaults/collection/streaming": () => saved });
    renderAt("/libraries/Movies?tab=defaults");

    const streaming = await screen.findByRole("listitem", { name: "Streaming Collections" });
    fireEvent.click(within(streaming).getByRole("button", { name: "Edit variables" }));
    const form = within(streaming).getByRole("form", { name: "Variables for Streaming Collections" });
    await within(form).findByText("Where you stream from");
    expect(within(form).getByLabelText("region")).toHaveValue("GB");
    expect(within(form).getByText("Turn one collection off")).toBeInTheDocument(); // use_netflix, by its pattern
    fireEvent.change(within(form).getByLabelText("region"), { target: { value: "IN" } });
    fireEvent.change(within(form).getByLabelText("Add a variable"), { target: { value: "use_all" } });
    fireEvent.change(within(form).getByLabelText("use_all"), { target: { value: "false" } });
    fireEvent.click(within(form).getByRole("button", { name: "Remove use_netflix" }));
    fireEvent.click(within(form).getByRole("button", { name: "Save variables" }));

    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/defaults/collection/streaming")?.body).toEqual({ template_variables: { region: "IN", use_all: false } }),
    );
  });

  it("turns a default off, after asking", async () => {
    const calls = mockApi({ ...routes, "DELETE /config/libraries/Movies/defaults/collection/streaming": () => saved });
    renderAt("/libraries/Movies?tab=defaults");
    const streaming = await screen.findByRole("listitem", { name: "Streaming Collections" });
    fireEvent.click(within(streaming).getByRole("button", { name: "Turn off" }));
    expect(within(streaming).getByText(/Kometa stops building these/)).toBeInTheDocument();
    fireEvent.click(within(streaming).getByRole("button", { name: "Turn off Streaming Collections" }));
    await waitFor(() => expect(calls.some((c) => c.route === "DELETE /config/libraries/Movies/defaults/collection/streaming")).toBe(true));
  });

  it("sets the library's own variables, and shows Kometa's refusal", async () => {
    const refusal = { message: "Kometa found problems, so nothing was saved.", validation: { ...saved.validation, ok: false, errors: ["config.yml: sep_style must be one of …"] } };
    const calls = mockApi({ ...routes, "PUT /config/libraries/Movies/template-variables": () => new Response(JSON.stringify({ detail: refusal }), { status: 422 }) });
    renderAt("/libraries/Movies?tab=defaults");
    const form = await screen.findByRole("form", { name: "Variables for Movies" });
    await waitFor(() => expect(within(form).getByLabelText("sep_style")).toHaveValue("purple"));
    fireEvent.change(within(form).getByLabelText("sep_style"), { target: { value: "blue" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save variables" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /config/libraries/Movies/template-variables")?.body).toEqual({ template_variables: { sep_style: "blue" } }));
    expect(await within(form).findByText(/sep_style must be one of/)).toBeInTheDocument();
  });
});
