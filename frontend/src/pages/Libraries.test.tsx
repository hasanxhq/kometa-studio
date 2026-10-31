import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConfigLibrary, LibraryCounts, PlexCollection, PlexLibrarySummary } from "../api";
import { mockApi, renderAt } from "../test-utils";

const plexLibraries: PlexLibrarySummary[] = [
  { key: "1", title: "Movies", type: "movie", collections: 3, managed: 1 },
  { key: "5", title: "Bangtan", type: "artist", collections: 0, managed: 0 },
];

const counts: LibraryCounts = {
  name: "Movies",
  plex_name: "Movies",
  collection_files: 2,
  overlay_files: 1,
  metadata_files: 0,
  defaults: 1,
  collections: 2,
  overlays: 0,
  operations: 1,
  problems: [],
};

const collections: PlexCollection[] = [
  { rating_key: "101", title: "Marvel", items: 11, managed: true, smart: false, summary: "", thumb: "/library/collections/101/composite/1", added_at: 1, updated_at: 1 },
  { rating_key: "102", title: "Spy Kids", items: 3, managed: false, smart: false, summary: "", thumb: null, added_at: 1, updated_at: 1 },
  { rating_key: "103", title: "Recently Added", items: 50, managed: false, smart: true, summary: "", thumb: null, added_at: 1, updated_at: 1 },
];

const movies: ConfigLibrary = {
  name: "Movies",
  collection_files: [
    {
      kind: "default",
      value: "basic",
      template_variables: { sep_style: "purple" },
      options: {},
      files: [{ path: "defaults/chart/basic.yml", title: "Basic Charts Collections", docs_url: "https://kometa.wiki/x", collections: [], overlays: [], playlists: [], metadata: 0, templates: [], error: null }],
      error: null,
    },
    {
      kind: "file",
      value: "config/Movies.yml",
      template_variables: {},
      options: {},
      files: [
        {
          path: "Movies.yml",
          title: null,
          docs_url: null,
          collections: [
            { name: "Marvel", dynamic: false, type: null, builders: ["tmdb_collection"], templates: [], sync_mode: "sync", schedule: null },
            { name: "Pixar", dynamic: false, type: null, builders: ["tmdb_company"], templates: [], sync_mode: null, schedule: null },
            { name: "Genres", dynamic: true, type: "genre", builders: [], templates: [], sync_mode: null, schedule: null },
          ],
          overlays: [],
          playlists: [],
          metadata: 0,
          templates: [],
          error: null,
        },
      ],
      error: null,
    },
  ],
  overlay_files: [],
  metadata_files: [],
  operations: { mass_genre_update: "tmdb" },
  template_variables: {},
  settings: {},
  counts,
};

const api = {
  "GET /plex/libraries": () => ({ libraries: plexLibraries }),
  "GET /config": () => ({ path: "/config/config.yml", libraries: [counts, { ...counts, name: "Anime", plex_name: "Anime" }], playlist_files: [] }),
  "GET /plex/libraries/1/collections": () => ({ library: { key: "1", title: "Movies", type: "movie" }, collections }),
  "GET /config/libraries/Movies": () => movies,
  "GET /config/file?path=Movies.yml": () => ({ path: "Movies.yml", text: "collections:\n  Marvel:\n" }),
};

describe("Libraries", () => {
  it("shows Plex's libraries with their config, and config libraries Plex lacks", async () => {
    mockApi(api);
    renderAt("/libraries");

    await screen.findByText("Bangtan");
    const cards = within(screen.getByRole("main")).getAllByRole("listitem");
    expect(cards.map((card) => within(card).getByRole("heading").textContent)).toEqual(["Movies", "Bangtan", "Anime"]);
    expect(cards[0]).toHaveTextContent("3 collections · 1 by Kometa · 2 unmanaged");
    expect(cards[0]).toHaveTextContent("2 collection files, 1 overlay file, 1 default");
    expect(cards[1]).toHaveTextContent("Not in Kometa's config.yml yet.");
    expect(cards[2]).toHaveTextContent("Plex has no library called Anime.");
    expect(within(cards[0]).getByRole("link")).toHaveAttribute("href", "/libraries/Movies");
  });

  it("adds a Plex library to Kometa from its card", async () => {
    const calls = mockApi({ ...api, "POST /config/libraries": () => ({ backup: "b", files: [{ path: "config.yml", hash: "h" }], validation: {} }) });
    renderAt("/libraries");
    const bangtan = (await screen.findByText("Bangtan")).closest("li")!;
    expect(within(screen.getByText("Movies", { selector: "h2" }).closest("li")!).queryByRole("button", { name: "Add to Kometa" })).not.toBeInTheDocument();
    fireEvent.click(within(bangtan).getByRole("button", { name: "Add to Kometa" }));
    await waitFor(() => expect(calls.find((c) => c.route === "POST /config/libraries")?.body).toEqual({ name: "Bangtan" }));
  });

  it("still shows Plex's libraries before config.yml exists", async () => {
    mockApi({ ...api, "GET /config": () => new Response(JSON.stringify({ detail: "Kometa's config.yml doesn't exist yet." }), { status: 404 }) });
    renderAt("/libraries");
    expect(await screen.findByText(/config.yml doesn't exist yet, so these are the libraries Plex has/)).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getAllByRole("listitem")).toHaveLength(2);
  });
});

describe("A library", () => {
  it("shows Plex's collections, managed or not, and what the config adds", async () => {
    mockApi(api);
    renderAt("/libraries/Movies");

    expect(await screen.findByText("Spy Kids", { selector: "span.font-semibold" })).toBeInTheDocument();
    const marvel = screen.getByText("Marvel", { selector: "span.font-semibold" }).closest("li")!;
    expect(marvel).toHaveTextContent("11 items");
    expect(marvel).toHaveTextContent("By Kometa");
    expect(marvel).toHaveTextContent("Defined in Movies.yml");
    expect(marvel.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/plex/image?path=%2Flibrary%2Fcollections%2F101%2Fcomposite%2F1&width=240&height=360",
    );

    fireEvent.click(screen.getByRole("button", { name: "Unmanaged (2)" }));
    expect(screen.queryByText("Marvel", { selector: "span.font-semibold" })).not.toBeInTheDocument();
    expect(screen.getByText("Recently Added", { selector: "span.font-semibold" }).closest("li")).toHaveTextContent("Smart");

    // Pixar is in Movies.yml but not in Plex; the dynamic Genres collection can't be matched by name.
    const notYet = (await screen.findByRole("heading", { name: "Not in Plex yet (1)" })).closest("section")!;
    expect(notYet).toHaveTextContent("Pixar");
    expect(notYet).not.toHaveTextContent("Genres");

    const files = screen.getByRole("heading", { name: "Collection files in config.yml" }).closest("section")!;
    const [, moviesYaml] = within(files).getAllByRole("button", { name: "View YAML" }); // the default's, then Movies.yml's
    fireEvent.click(moviesYaml);
    expect(await within(files).findByText(/Marvel:/)).toBeInTheDocument();
  });

  it("marks Maintainerr's collections, apart from unmanaged ones", async () => {
    mockApi({
      ...api,
      "GET /plex/libraries/1/collections": () => ({
        library: { key: "1", title: "Movies", type: "movie" },
        collections: collections.map((c) => (c.rating_key === "102" ? { ...c, maintainerr: true } : c)),
      }),
    });
    renderAt("/libraries/Movies");
    const spyKids = (await screen.findByText("Spy Kids", { selector: "span.font-semibold" })).closest("li")!;
    expect(spyKids).toHaveTextContent("By Maintainerr");
    expect(screen.getByText(/Maintainerr's collections are protected/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Unmanaged (1)" }));
    expect(screen.queryByText("Spy Kids", { selector: "span.font-semibold" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "By Maintainerr (1)" }));
    expect(screen.getByText("Spy Kids", { selector: "span.font-semibold" })).toBeInTheDocument();
  });

  it("shows defaults with their template variables, and operations", async () => {
    mockApi(api);
    renderAt("/libraries/Movies?tab=defaults");
    expect(await screen.findByText("Basic Charts Collections")).toBeInTheDocument();
    expect(screen.getByText("sep_style: purple")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Operations" }));
    await waitFor(() => expect(screen.getByText("mass_genre_update")).toBeInTheDocument());
  });

  it("explains a Plex library that isn't in config.yml", async () => {
    mockApi({ ...api, "GET /plex/libraries/5/collections": () => ({ library: { key: "5", title: "Bangtan", type: "artist" }, collections: [] }) });
    renderAt("/libraries/Bangtan?tab=overlays");
    expect(await screen.findByText(/isn't in Kometa's config.yml, so Kometa doesn't touch it yet/)).toBeInTheDocument();
    const add = screen.getByRole("heading", { name: "Not in Kometa yet" }).closest("section")!;
    expect(within(add).getByRole("button", { name: "Add to Kometa" })).toBeInTheDocument();
  });

  it("starts new collection and overlay files from the library's page", async () => {
    mockApi(api);
    renderAt("/libraries/Movies");
    const files = (await screen.findByRole("heading", { name: "Collection files in config.yml" })).closest("section")!;
    expect(within(files).getByRole("link", { name: "+ New collection in a new file" })).toHaveAttribute("href", "/items?section=collections&new=1&library=Movies");
    fireEvent.click(screen.getByRole("tab", { name: "Overlays" }));
    expect(await screen.findByText("This library has no overlay files.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+ New overlay in a new file" })).toHaveAttribute("href", "/items?section=overlays&new=1&library=Movies");
  });

  it("says a library with nothing in it gives Kometa nothing to do", async () => {
    mockApi({ ...api, "GET /config/libraries/Movies": () => ({ ...movies, collection_files: [], operations: {} }) });
    renderAt("/libraries/Movies");
    expect(await screen.findByText(/Until Movies has a collection file, an overlay file or an operation/)).toBeInTheDocument();
  });
});
