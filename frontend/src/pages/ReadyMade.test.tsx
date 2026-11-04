import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReadyMadeCategory, ReadyMadeEntry, ReadyMadeLibrary } from "../api";
import { mockApi, renderAt } from "../test-utils";

const entry = (partial: Partial<ReadyMadeEntry> & Pick<ReadyMadeEntry, "block" | "key" | "title">): ReadyMadeEntry => ({
  items: 10,
  id: null,
  desired: null,
  state: "none",
  plex_items: null,
  thumb: null,
  last_built_at: null,
  last_error: null,
  build_seconds: null,
  ...partial,
});

const summary = {
  name: "imdb",
  title: "IMDb Collections",
  group: "chart" as const,
  kind: "fixed" as const,
  listable: true,
  reason: null,
  count: 18,
  in_plex: 3,
  picked: 4,
  run_scope: "collection" as const,
};

const gallery: ReadyMadeLibrary = {
  library: "Movies",
  library_type: "movie",
  counted_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  counting: false,
  categories: [
    summary,
    { ...summary, name: "oscars", title: "Oscars Collections", group: "award", kind: "award", count: 12, in_plex: 0, picked: 0 },
    { ...summary, name: "genre", title: "Genre Collections", group: "both", kind: "per_value", count: null, in_plex: 0, picked: 0 },
    { ...summary, name: "basic", title: "Basic Charts Collections", group: "chart", kind: "helper", count: 5, in_plex: 1, picked: 0 },
    {
      ...summary,
      name: "letterboxd",
      title: "Letterboxd Collections",
      group: "chart",
      kind: "fixed",
      listable: false,
      reason: "Needs a Letterboxd username",
      count: null,
      in_plex: 0,
      picked: 0,
    },
  ],
};

const imdbCategory = (): ReadyMadeCategory => ({
  ...summary,
  counted_at: gallery.counted_at,
  collections: [
    entry({ block: "collections", key: "top", title: "IMDb Top 250", items: 120, desired: true, state: "in_plex", plex_items: 42, thumb: "/library/metadata/1/thumb", id: 1 }),
    entry({ block: "collections", key: "popular", title: "IMDb Popular", items: 80, desired: null, state: "none" }),
    entry({ block: "collections", key: "lowest", title: "IMDb Lowest Rated", items: 5, desired: false, state: "missing", id: 2 }),
    entry({ block: "collections", key: "building", title: "Building One", desired: true, state: "building", id: 3 }),
  ],
});

const routes = (category: ReadyMadeCategory = imdbCategory(), library: ReadyMadeLibrary = gallery) => ({
  "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }], playlist_files: [] }),
  "GET /ready-made/libraries/Movies": () => library,
  "GET /ready-made/libraries/Movies/categories/imdb": () => category,
  "GET /ready-made/libraries/Movies/categories/genre": () => ({
    ...library.categories.find((c) => c.name === "genre")!,
    counted_at: null,
    run_scope: "file" as const,
    collections: [entry({ block: "dynamic_collections", key: "Action", title: "Action" })],
  }),
});

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("Ready-made gallery", () => {
  it("lists categories in kind sections with counts and a muted non-listable card", async () => {
    mockApi({ ...routes(), "GET /jobs": () => ({ jobs: [], at: new Date().toISOString() }) });
    renderAt("/ready-made");
    expect(await screen.findByRole("heading", { name: "Charts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Awards" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "One per value in your library" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Other" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ready-made", level: 2 })).toBeInTheDocument();

    const imdb = await screen.findByRole("listitem", { name: "IMDb Collections" });
    expect(within(imdb).getByText("18 collections · 3 in Plex")).toBeInTheDocument();
    expect(within(imdb).getByText("4 picked")).toBeInTheDocument();
    expect(within(imdb).getByRole("link")).toHaveAttribute("href", "/ready-made/imdb?library=Movies");
    expect(imdb.querySelector("img")).toHaveAttribute("src", expect.stringContaining("/api/v1/config/defaults/imdb/cover"));

    const letterboxd = screen.getByRole("listitem", { name: "Letterboxd Collections" });
    expect(within(letterboxd).getByText("Needs a Letterboxd username")).toBeInTheDocument();
    expect(within(letterboxd).queryByRole("link")).toBeNull();
    expect(letterboxd).toHaveClass("opacity-60");

    expect(within(screen.getByRole("listitem", { name: "Genre Collections" })).getByText("Not counted yet")).toBeInTheDocument();
    expect(screen.getByText(/Counted 2 h ago/)).toBeInTheDocument();
  });

  it("says Counting… when counts are still running", async () => {
    mockApi({
      ...routes(imdbCategory(), { ...gallery, counting: true, counted_at: null }),
      "GET /jobs": () => ({ jobs: [], at: new Date().toISOString() }),
    });
    renderAt("/ready-made");
    const genre = await screen.findByRole("listitem", { name: "Genre Collections" });
    expect(within(genre).getByText("Counting…")).toBeInTheDocument();
    expect(screen.getAllByText("Counting…").length).toBeGreaterThanOrEqual(1);
  });
});

describe("Ready-made category picks", () => {
  it("selects by the desired/local rule, Select all / Clear, and shows Will be removed", async () => {
    mockApi(routes({ ...imdbCategory(), collections: imdbCategory().collections.filter((c) => c.key !== "building") }));
    renderAt("/ready-made/imdb?library=Movies");

    const top = await screen.findByRole("button", { name: "IMDb Top 250" });
    const popular = await screen.findByRole("button", { name: "IMDb Popular" });
    expect(top).toHaveAttribute("aria-pressed", "true");
    expect(popular).toHaveAttribute("aria-pressed", "false");
    expect(within(top).getByText("In Plex · 42 titles")).toBeInTheDocument();

    fireEvent.click(top);
    expect(top).toHaveAttribute("aria-pressed", "false");
    expect(within(top).getByText("Will be removed")).toBeInTheDocument();
    expect(screen.getByText("Remove 1")).toBeInTheDocument();

    fireEvent.click(top); // cancel removal
    expect(top).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Remove 1")).not.toBeInTheDocument();

    fireEvent.click(popular);
    expect(popular).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Build 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(await screen.findByRole("button", { name: "IMDb Lowest Rated" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Build 2/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(top).toHaveAttribute("aria-pressed", "false");
    expect(popular).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Remove 1")).toBeInTheDocument();
  });

  it("names the category in the header, not just Category", async () => {
    mockApi(routes());
    renderAt("/ready-made/imdb?library=Movies");
    expect(await screen.findByRole("heading", { level: 1, name: imdbCategory().title })).toBeInTheDocument();
  });

  it("notes when Kometa builds the category as a whole", async () => {
    mockApi(routes());
    renderAt("/ready-made/genre?library=Movies");
    expect(await screen.findByText(/Kometa builds this category as a whole/)).toBeInTheDocument();
  });

  it("polls only while a collection is queued or building", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let building = true;
    const calls = mockApi({
      ...routes(),
      "GET /ready-made/libraries/Movies/categories/imdb": () => ({
        ...imdbCategory(),
        collections: [
          entry({
            block: "collections",
            key: "building",
            title: "Building One",
            desired: true,
            state: building ? "building" : "in_plex",
            id: 3,
            plex_items: building ? null : 1,
          }),
        ],
      }),
    });
    renderAt("/ready-made/imdb?library=Movies");
    expect(await screen.findByText("Building…")).toBeInTheDocument();
    const before = calls.filter((c) => c.route.includes("/categories/imdb")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => expect(calls.filter((c) => c.route.includes("/categories/imdb")).length).toBeGreaterThan(before));

    building = false;
    const afterBuilding = calls.filter((c) => c.route.includes("/categories/imdb")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    // One more fetch may land with in_plex; after that, no further polls.
    await waitFor(() => expect(screen.queryByText("Building…")).not.toBeInTheDocument());
    const settled = calls.filter((c) => c.route.includes("/categories/imdb")).length;
    expect(settled).toBeGreaterThanOrEqual(afterBuilding);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(calls.filter((c) => c.route.includes("/categories/imdb")).length).toBe(settled);
  });

  it("keeps working when sessionStorage is unavailable", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    mockApi(routes({ ...imdbCategory(), collections: [entry({ block: "collections", key: "popular", title: "IMDb Popular" })] }));
    renderAt("/ready-made/imdb?library=Movies");
    const popular = await screen.findByRole("button", { name: "IMDb Popular" });
    fireEvent.click(popular);
    expect(popular).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Build 1")).toBeInTheDocument();
    setItem.mockRestore();
    getItem.mockRestore();
  });
});

describe("Ready-made Build bar", () => {
  it("dry-runs, lists build and non-deletable remove, then confirms and clears picks", async () => {
    const calls = mockApi({
      ...routes({
        ...imdbCategory(),
        collections: [
          entry({ block: "collections", key: "top", title: "IMDb Top 250", desired: true, state: "in_plex", plex_items: 42, id: 1 }),
          entry({ block: "collections", key: "popular", title: "IMDb Popular" }),
        ],
      }),
      "POST /ready-made/build": (body) => {
        const req = body as { dry_run: boolean; add: unknown[]; remove: unknown[] };
        if (req.dry_run) {
          return {
            build: [{ category: "imdb", title: "IMDb Popular" }],
            remove: [
              { category: "imdb", title: "IMDb Top 250", deletable: true, reason: null },
              { category: "imdb", title: "Maintainerr Watchlist", deletable: false, reason: "Maintainerr collection" },
            ],
            run: { libraries: ["Movies"], collections: ["IMDb Popular"], files: [] },
            blocked: [{ category: "imdb", title: "IMDb Lowest Rated", reason: "a collection with this name that Studio didn't make is already in Plex" }],
          };
        }
        return {
          build: [{ category: "imdb", title: "IMDb Popular" }],
          remove: [
            { category: "imdb", title: "IMDb Top 250", deletable: true, reason: null },
            { category: "imdb", title: "Maintainerr Watchlist", deletable: false, reason: "Maintainerr collection" },
          ],
          run: { libraries: ["Movies"], collections: ["IMDb Popular"], files: [] },
          blocked: [],
          run_id: 77,
          removed: ["IMDb Top 250"],
          kept: [{ title: "Maintainerr Watchlist", reason: "Maintainerr collection" }],
        };
      },
    });

    renderAt("/ready-made/imdb?library=Movies");
    const top = await screen.findByRole("button", { name: "IMDb Top 250" });
    const popular = await screen.findByRole("button", { name: "IMDb Popular" });
    fireEvent.click(top);
    fireEvent.click(popular);
    expect(screen.getByText("Build 1 · Remove 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("IMDb Popular")).toBeInTheDocument();
    expect(within(dialog).getByText("IMDb Top 250")).toBeInTheDocument();
    expect(within(dialog).getByText(/won't be deleted: Maintainerr Watchlist/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Maintainerr collection/)).toBeInTheDocument();
    expect(within(dialog).getByText("Won't build")).toBeInTheDocument();
    expect(within(dialog).getByText(/Studio didn't make is already in Plex/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText(/Building in/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /run #77/ })).toHaveAttribute("href", "/activity/queue/77");
    expect(screen.queryByText("Build 1 · Remove 1")).not.toBeInTheDocument();

    const real = calls.find((c) => c.route === "POST /ready-made/build" && (c.body as { dry_run: boolean }).dry_run === false);
    expect(real?.body).toEqual({
      library: "Movies",
      add: [{ category: "imdb", block: "collections", key: "popular" }],
      remove: [{ category: "imdb", block: "collections", key: "top" }],
      dry_run: false,
    });
  });
});
