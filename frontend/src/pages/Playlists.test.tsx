import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FileReference, Validation } from "../api";
import { mockApi, renderAt } from "../test-utils";

const file = (path: string, playlists: { name: string; libraries: unknown }[]) => ({
  path,
  title: null,
  docs_url: null,
  collections: [],
  overlays: [],
  playlists,
  metadata: 0,
  templates: [],
  error: null,
});

const playlistFiles: FileReference[] = [
  {
    kind: "file",
    value: "config/Playlists.yml",
    template_variables: {},
    options: {},
    files: [file("Playlists.yml", [{ name: "Marvel in order", libraries: ["Movies", "TV Shows"] }])],
    error: null,
  },
  { kind: "default", value: "playlist", template_variables: {}, options: {}, files: [file("defaults/playlist.yml", [{ name: "Arrowverse", libraries: "TV Shows" }])], error: null },
];

// Shaped like Kometa's playlist schema.
const playlistSchema = {
  type: "object",
  properties: { playlists: { $ref: "#/definitions/playlists-map" } },
  definitions: {
    "playlists-map": { type: "object", additionalProperties: { $ref: "#/definitions/playlist-definition" } },
    "playlist-definition": {
      type: "object",
      additionalProperties: false,
      properties: {
        libraries: { oneOf: [{ type: "string" }, { type: "array", items: { type: "string" } }] },
        summary: { type: "string" },
        sync_mode: { enum: ["sync", "append"] },
        tmdb_collection: { oneOf: [{ type: "integer" }, { type: "array", items: { type: "integer" } }] },
        filters: { type: "object" },
      },
    },
  },
};

const passed: Validation = { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" };

describe("Playlists", () => {
  it("lists config.yml's playlist files and their playlists, and runs them", async () => {
    const calls = mockApi({
      "GET /config": () => ({ path: "/config/config.yml", libraries: [], playlist_files: playlistFiles }),
      "POST /runs": () => ({ id: 12, status: "queued" }),
    });
    renderAt("/playlists");

    const own = await screen.findByRole("link", { name: /Marvel in order/ });
    expect(own).toHaveAttribute("href", "/items?path=Playlists.yml&section=playlists&name=Marvel+in+order");
    expect(own).toHaveTextContent("Movies, TV Shows");
    expect(screen.getByText("Arrowverse").closest("a")).toBeNull(); // Kometa's default: not Studio's to edit
    expect(screen.getByRole("link", { name: "Add a playlist" })).toHaveAttribute("href", "/items?section=playlists&new=1&path=Playlists.yml");

    fireEvent.click(screen.getByRole("button", { name: "Run playlists" }));
    expect(await screen.findByRole("link", { name: "run #12" })).toBeInTheDocument();
    expect((calls.find((c) => c.route === "POST /runs")?.body as { mode: string }).mode).toBe("playlists");
  });

  it("starts a playlist in a new file, which goes in playlist_files rather than a library", async () => {
    const calls = mockApi({
      "GET /config": () => ({ path: "/config/config.yml", libraries: [], playlist_files: [] }),
      "GET /config/schemas/playlist": () => playlistSchema,
      "POST /config/item": () => ({ backup: "b", files: [{ path: "Playlists.yml", hash: "h" }, { path: "config.yml", hash: "c" }], validation: passed }),
      "GET /config/item?path=Playlists.yml&section=playlists&name=Marvel%20in%20order": () => ({ path: "Playlists.yml", hash: "h", section: "playlists", name: "Marvel in order", value: {}, kind: "playlist" }),
    });
    renderAt("/items?section=playlists&new=1");

    expect(await screen.findByRole("heading", { name: "New playlist in a new file" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText(/New file's name/)).toHaveValue("Playlists.yml"));
    expect(screen.getByText(/adds it to playlist_files in config.yml/)).toBeInTheDocument();
    expect(screen.getByText(/A playlist takes its items from one source/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Marvel in order" } });
    fireEvent.change(await screen.findByLabelText("Libraries"), { target: { value: "Movies" } });
    const sources = screen.getByText("Add a source").closest("label")!;
    fireEvent.change(within(sources).getByRole("combobox"), { target: { value: "tmdb_collection" } });
    fireEvent.change(screen.getByLabelText("tmdb_collection"), { target: { value: "556" } });
    fireEvent.click(screen.getByRole("button", { name: "Add playlist" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /config/item")).toBe(true));
    expect(calls.find((c) => c.route === "POST /config/item")?.body).toEqual({
      path: "Playlists.yml",
      base_hash: null,
      section: "playlists",
      name: "Marvel in order",
      value: { libraries: "Movies", tmdb_collection: 556 },
      create: true,
      rename: null,
    });
  });
});
