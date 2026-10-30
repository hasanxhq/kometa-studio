import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlexCollection, PlexItem } from "../api";
import { mockApi, renderAt } from "../test-utils";

const marvel: PlexCollection = {
  rating_key: "101",
  title: "Marvel",
  items: 3,
  managed: true,
  smart: false,
  summary: "Every Marvel film.",
  thumb: "/library/collections/101/composite/1",
  added_at: 1,
  updated_at: 1,
  maintainerr: false,
};

const film = (n: number, year: number | null, ids: PlexItem["ids"] = { tmdb: String(1700 + n), imdb: `tt0${n}` }): PlexItem => ({
  rating_key: String(200 + n),
  title: `Film ${n}`,
  type: "movie",
  year,
  thumb: `/library/metadata/${200 + n}/thumb/1`,
  ids,
  content_rating: "PG-13",
  audience_rating: 7.5,
  episodes: null,
  added_at: 1,
});

const base = {
  "GET /plex/libraries": () => ({ libraries: [{ key: "1", title: "Movies", type: "movie", collections: 1, managed: 1 }] }),
  "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }], playlist_files: [] }),
  "GET /config/libraries/Movies": () => ({
    name: "Movies",
    collection_files: [
      {
        kind: "file",
        value: "config/Movies.yml",
        template_variables: {},
        options: {},
        error: null,
        files: [{ path: "Movies.yml", collections: [{ name: "Marvel", dynamic: false, builders: ["tmdb_collection"], templates: [] }] }],
      },
    ],
    overlay_files: [],
    metadata_files: [],
    operations: {},
    template_variables: {},
    settings: {},
  }),
};

describe("A collection's titles", () => {
  it("lists them a page at a time, with their IDs and where the collection is defined", async () => {
    const calls = mockApi({
      ...base,
      "GET /plex/libraries/1/collections/101?start=0&size=100": () => ({ collection: marvel, items: [film(1, 2008), film(2, 2010)], start: 0, total: 3 }),
      "GET /plex/libraries/1/collections/101?start=2&size=100": () => ({ collection: marvel, items: [film(3, null, {})], start: 2, total: 3 }),
    });
    renderAt("/libraries/Movies/collections/101");

    expect(await screen.findByRole("heading", { name: "Marvel" })).toBeInTheDocument();
    expect(screen.getByText("Every Marvel film.")).toBeInTheDocument();
    expect(screen.getByText("By Kometa")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Defined in Movies.yml" })).toHaveAttribute(
      "href",
      "/items?path=Movies.yml&section=collections&name=Marvel&library=Movies",
    );

    const titles = screen.getByRole("list", { name: "Titles" });
    const first = within(titles).getByText("Film 1").closest("li")!;
    expect(first).toHaveTextContent("2008 · PG-13");
    expect(within(first).getByRole("link", { name: "TMDb" })).toHaveAttribute("href", "https://www.themoviedb.org/movie/1701");
    expect(within(first).getByRole("link", { name: "IMDb" })).toHaveAttribute("href", "https://www.imdb.com/title/tt01/");
    expect(first.querySelector("img")).toHaveAttribute("src", "/api/v1/plex/image?path=%2Flibrary%2Fmetadata%2F201%2Fthumb%2F1&width=240&height=360");
    expect(screen.getByText("Showing 2 of 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    const third = (await within(titles).findByText("Film 3")).closest("li")!;
    expect(third).toHaveTextContent("No TMDb, IMDb or TheTVDB ID in Plex");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.route.startsWith("GET /plex/libraries/1/collections/101"))).toHaveLength(2);
  });

  it("searches and sorts what's loaded", async () => {
    mockApi({
      ...base,
      "GET /plex/libraries/1/collections/101?start=0&size=100": () => ({ collection: marvel, items: [film(1, 2008), film(2, 2012), film(3, 2010)], start: 0, total: 3 }),
    });
    renderAt("/libraries/Movies/collections/101");
    const titles = await screen.findByRole("list", { name: "Titles" });
    const names = () => within(titles).getAllByText(/^Film \d$/).map((el) => el.textContent);

    fireEvent.change(screen.getByLabelText("Order"), { target: { value: "newest" } });
    expect(names()).toEqual(["Film 2", "Film 3", "Film 1"]);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "2010" } });
    expect(names()).toEqual(["Film 3"]);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "nothing" } });
    expect(screen.getByText("Nothing matches.")).toBeInTheDocument();
  });

  it("opens from the library's poster grid", async () => {
    mockApi({
      ...base,
      "GET /plex/libraries/1/collections": () => ({ library: { key: "1", title: "Movies", type: "movie" }, collections: [marvel] }),
      "GET /plex/libraries/1/collections/101?start=0&size=100": () => ({ collection: marvel, items: [film(1, 2008)], start: 0, total: 1 }),
    });
    renderAt("/libraries/Movies");
    fireEvent.click(await screen.findByRole("link", { name: "Marvel: its titles" }));
    await waitFor(() => expect(screen.getByRole("list", { name: "Titles" })).toHaveTextContent("Film 1"));
    expect(screen.getByRole("link", { name: "← Movies" })).toHaveAttribute("href", "/libraries/Movies");
  });

  it("says when Plex doesn't know the collection", async () => {
    mockApi({
      ...base,
      "GET /plex/libraries/1/collections/999?start=0&size=100": () => new Response(JSON.stringify({ detail: "Plex has no collection 999" }), { status: 404 }),
    });
    renderAt("/libraries/Movies/collections/999");
    expect(await screen.findByRole("alert")).toHaveTextContent("Plex has no collection 999");
  });
});
