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
  download_missing: false,
  requests: null,
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

describe("Ready-made tile art", () => {
  it("shows Plex's poster once built, else the one Kometa will apply, else the banner", async () => {
    const category = {
      ...imdbCategory(),
      collections: [
        entry({ block: "", key: "top", title: "IMDb Top 250", state: "in_plex", thumb: "/library/metadata/1/thumb", id: 1, poster: "ready-made/posters/movie/imdb?block=&key=IMDb+Top+250" }),
        entry({ block: "", key: "popular", title: "IMDb Popular", poster: "ready-made/posters/movie/imdb?block=&key=IMDb+Popular" }),
        entry({ block: "", key: "lowest", title: "IMDb Lowest Rated", poster: null }),
      ],
    };
    mockApi(routes(category));
    renderAt("/ready-made/imdb?library=Movies");

    const top = await screen.findByRole("button", { name: "IMDb Top 250" });
    expect(top.querySelector("img")).toHaveAttribute("src", expect.stringContaining("/api/v1/plex/image?path=%2Flibrary%2Fmetadata%2F1%2Fthumb"));

    const popular = screen.getByRole("button", { name: "IMDb Popular" });
    const kometa = popular.querySelector("img")!;
    expect(kometa).toHaveAttribute("src", expect.stringContaining("/api/v1/ready-made/posters/movie/imdb?block=&key=IMDb+Popular"));
    fireEvent.error(kometa); // a 404: Kometa's image repo doesn't have it
    expect(popular.querySelector("img")).toBeNull();
    expect(within(popular).getAllByText("IMDb Popular").length).toBe(2); // the banner and the caption

    const lowest = screen.getByRole("button", { name: "IMDb Lowest Rated" });
    expect(lowest.querySelector("img")).toBeNull();
  });
});

describe("Ready-made preview", () => {
  it("opens a tile's preview: what it would hold, what's missing, and Pick from the panel", async () => {
    const asked: string[] = [];
    mockApi({
      ...routes(),
      "GET /ready-made/libraries/Movies/categories/imdb/preview?block=collections&key=popular": () => {
        asked.push("popular");
        return {
          previewable: true,
          why: null,
          total: 3,
          in_library: [{ rating_key: "7", title: "Dune", year: 2021, thumb: "/library/metadata/7/thumb" }],
          in_library_count: 1,
          missing: [{ id: "tmdb:1", title: "Sinners", year: 2025, poster: null }],
          missing_count: 2,
          problems: [],
          skipped: [],
        };
      },
    });
    renderAt("/ready-made/imdb?library=Movies");
    fireEvent.click(await screen.findByRole("button", { name: "IMDb Popular" }));

    const panel = await screen.findByRole("dialog", { name: "IMDb Popular" });
    expect(await within(panel).findByText("In your library (1)")).toBeInTheDocument();
    expect(within(panel).getByText("Dune")).toBeInTheDocument();
    expect(within(panel).getByText(/Missing \(2\)/)).toBeInTheDocument();
    expect(within(panel).getByText("Not picked")).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Pick" }));
    expect(within(panel).getByRole("button", { name: "Unpick" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Pick IMDb Popular" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Build 1")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "IMDb Popular" })).not.toBeInTheDocument();
    expect(asked).toEqual(["popular"]);
  });

  it("says why when Studio can't preview one, and links a built one to its page", async () => {
    mockApi({
      ...routes({
        ...imdbCategory(),
        collections: [entry({ block: "collections", key: "top", title: "IMDb Top 250", state: "in_plex", desired: true, id: 1, rating_key: "4321" })],
      }),
      "GET /ready-made/libraries/Movies/categories/imdb/preview?block=collections&key=top": () => ({
        previewable: false,
        why: "Studio can show what's in this list once it has been built.",
        total: null,
        in_library: [],
        in_library_count: 0,
        missing: [],
        missing_count: 0,
        problems: [],
        skipped: [],
      }),
    });
    renderAt("/ready-made/imdb?library=Movies");
    fireEvent.click(await screen.findByRole("button", { name: "IMDb Top 250" }));
    const panel = await screen.findByRole("dialog", { name: "IMDb Top 250" });
    expect(await within(panel).findByText("Studio can show what's in this list once it has been built.")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open its page" })).toHaveAttribute("href", "/libraries/Movies/collections/4321");
    fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Ready-made category picks", () => {
  it("selects by the desired/local rule, Select all / Clear, and shows Will be removed", async () => {
    mockApi(routes({ ...imdbCategory(), collections: imdbCategory().collections.filter((c) => c.key !== "building") }));
    renderAt("/ready-made/imdb?library=Movies");

    const top = await screen.findByRole("button", { name: "Pick IMDb Top 250" });
    const popular = await screen.findByRole("button", { name: "Pick IMDb Popular" });
    const topTile = screen.getByRole("listitem", { name: "IMDb Top 250" });
    expect(top).toHaveAttribute("aria-pressed", "true");
    expect(popular).toHaveAttribute("aria-pressed", "false");
    expect(within(topTile).getByTitle("In Plex · 42 titles")).toBeInTheDocument();

    fireEvent.click(top);
    expect(top).toHaveAttribute("aria-pressed", "false");
    expect(within(topTile).getByTitle("Will be removed")).toBeInTheDocument();
    expect(screen.getByText("Remove 1")).toBeInTheDocument();

    fireEvent.click(top); // cancel removal
    expect(top).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Remove 1")).not.toBeInTheDocument();

    fireEvent.click(popular);
    expect(popular).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Build 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(await screen.findByRole("button", { name: "Pick IMDb Lowest Rated" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Build 2/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(top).toHaveAttribute("aria-pressed", "false");
    expect(popular).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Remove 1")).toBeInTheDocument();
  });

  it("opens a Plex-filter collection in the builder with Customise", async () => {
    mockApi(routes({ ...imdbCategory(), customisable: true }));
    renderAt("/ready-made/imdb?library=Movies");
    const link = await screen.findByRole("link", { name: "Customise IMDb Popular" });
    expect(link).toHaveAttribute("href", "/collections/new?library=Movies&category=imdb&block=collections&key=popular");
  });

  it("has no Customise for a category that comes from a list", async () => {
    mockApi(routes({ ...imdbCategory(), customisable: false }));
    renderAt("/ready-made/imdb?library=Movies");
    await screen.findByRole("button", { name: "IMDb Popular" });
    expect(screen.queryByRole("link", { name: /^Customise/ })).not.toBeInTheDocument();
  });

  it("names the category in the header, not just Category", async () => {
    mockApi(routes());
    renderAt("/ready-made/imdb?library=Movies");
    expect(await screen.findByRole("heading", { level: 1, name: imdbCategory().title })).toBeInTheDocument();
  });

  it("retries a failed pick with a Build of just that pick", async () => {
    const failed = entry({ block: "collections", key: "popular", title: "IMDb Popular", desired: true, state: "failed", last_error: "TMDb Error", id: 5 });
    const calls = mockApi({
      ...routes({ ...imdbCategory(), collections: [failed] }),
      "POST /ready-made/build": () => ({ build: [], remove: [], run: null, blocked: [{ category: "imdb", title: "IMDb Popular", reason: "Maintainerr has a collection with this name" }], run_id: null, removed: [], kept: [] }),
    });
    renderAt("/ready-made/imdb?library=Movies");
    fireEvent.click(await screen.findByRole("button", { name: "Retry IMDb Popular" }));
    expect(await screen.findByText("Maintainerr has a collection with this name")).toBeInTheDocument();
    const sent = calls.find((c) => c.route === "POST /ready-made/build");
    expect(sent?.body).toEqual({
      library: "Movies",
      add: [{ category: "imdb", block: "collections", key: "popular" }],
      remove: [],
      dry_run: false,
      download_missing: false,
    });
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
    expect(await screen.findByTitle("Building")).toBeInTheDocument();
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
    await waitFor(() => expect(screen.queryByTitle("Building")).not.toBeInTheDocument());
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
    const popular = await screen.findByRole("button", { name: "Pick IMDb Popular" });
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
    fireEvent.click(await screen.findByRole("button", { name: "Pick IMDb Top 250" }));
    fireEvent.click(screen.getByRole("button", { name: "Pick IMDb Popular" }));
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
      download_missing: false,
    });
  });

  it("sends download_missing from the build bar when requests are on", async () => {
    const calls = mockApi({
      ...routes({
        ...imdbCategory(),
        collections: [entry({ block: "collections", key: "popular", title: "IMDb Popular" })],
      }),
      "GET /requests/settings": () => ({
        settings: {
          enabled: true,
          via: "arr",
          radarr: { quality_profile: null, root_folder: null, minimum_availability: "released", search: true },
          sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
          daily_cap: null,
          confirm_over: 25,
        },
        seerr: null,
        connected: { radarr: true, sonarr: false, seerr: false },
      }),
      "POST /ready-made/build": (body) => {
        const req = body as { dry_run: boolean };
        if (req.dry_run) return { build: [{ category: "imdb", title: "IMDb Popular" }], remove: [], run: null, blocked: [] };
        return { build: [{ category: "imdb", title: "IMDb Popular" }], remove: [], run: null, blocked: [], run_id: 1, removed: [], kept: [] };
      },
    });
    renderAt("/ready-made/imdb?library=Movies");
    fireEvent.click(await screen.findByRole("button", { name: "Pick IMDb Popular" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Download missing/ }));
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    await screen.findByRole("dialog");
    const dry = calls.find((c) => c.route === "POST /ready-made/build" && (c.body as { dry_run: boolean }).dry_run === true);
    expect(dry?.body).toMatchObject({ download_missing: true });
  });
});
