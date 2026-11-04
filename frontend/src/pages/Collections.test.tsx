import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BuiltCollection } from "../builderApi";
import { mockApi } from "../test-utils";
import { CollectionBuilder } from "./CollectionBuilder";
import { Collections } from "./Collections";

const collection = (partial: Partial<BuiltCollection> & Pick<BuiltCollection, "id" | "title" | "state">): BuiltCollection => ({
  library: "Movies",
  source: { kind: "filters" },
  filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
  sort_by: null,
  limit: null,
  visible: { library: true, home: false, shared: false },
  minimum_items: 1,
  summary: null,
  sort_title: null,
  poster: null,
  download_missing: false,
  request_cap: null,
  plex_items: null,
  thumb: null,
  last_built_at: null,
  last_error: null,
  run_id: null,
  requests: { waiting: 0, requested: 0, downloading: 0, imported: 0, failed: 0 },
  ...partial,
});

function renderCollections(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/collections", element: <Collections /> },
      { path: "/collections/new", element: <CollectionBuilder /> },
      { path: "/collections/:id", element: <CollectionBuilder /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const config = {
  "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }, { name: "TV Shows", plex_name: "TV Shows" }], playlist_files: [] }),
};

afterEach(() => {
  vi.useRealTimers();
});

describe("Collections list", () => {
  it("lists collections with status lines and links", async () => {
    mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({
        collections: [
          collection({ id: 1, title: "Action Picks", state: "in_plex", plex_items: 12, thumb: "/library/collections/1/thumb" }),
          collection({ id: 2, title: "Queued One", state: "queued" }),
          collection({ id: 3, title: "Building One", state: "building" }),
          collection({ id: 4, title: "Broken", state: "failed", last_error: "no titles" }),
          collection({ id: 5, title: "Missing One", state: "missing" }),
        ],
      }),
    });
    renderCollections("/collections?library=Movies");

    expect(await screen.findByRole("heading", { name: "Collections", level: 2 })).toBeInTheDocument();
    expect(screen.getByText(/Smart collections you build/)).toBeInTheDocument();

    const action = await screen.findByRole("listitem", { name: "Action Picks" });
    expect(within(action).getByText("Smart filter")).toBeInTheDocument();
    expect(within(action).getByText("In Plex · 12 titles")).toBeInTheDocument();
    expect(within(action).getByRole("link")).toHaveAttribute("href", "/collections/1");

    expect(within(screen.getByRole("listitem", { name: "Queued One" })).getByText("Queued")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Building One" })).getByText("Building…")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Broken" })).getByText("Failed: no titles")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Missing One" })).getByText("Not built yet")).toBeInTheDocument();

    const newLinks = screen.getAllByRole("link", { name: "New collection" });
    expect(newLinks[0]).toHaveAttribute("href", "/collections/new?library=Movies");
  });

  it("shows Smart filter or the list label under the title", async () => {
    mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({
        collections: [
          collection({ id: 1, title: "Action Picks", state: "in_plex", plex_items: 12 }),
          collection({
            id: 2,
            title: "Die Hard",
            state: "missing",
            source: { kind: "list", builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" },
            filters: { match: "all", rules: [] },
          }),
          collection({
            id: 3,
            title: "Chart",
            state: "missing",
            source: { kind: "list", builder: "imdb_chart", value: "top", label: null },
            filters: { match: "all", rules: [] },
          }),
        ],
      }),
    });
    renderCollections("/collections?library=Movies");
    expect(within(await screen.findByRole("listitem", { name: "Action Picks" })).getByText("Smart filter")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Die Hard" })).getByText("Die Hard Collection")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Chart" })).getByText("imdb_chart")).toBeInTheDocument();
  });

  it("shows request counts, Request N titles, and Turn off for download_missing", async () => {
    const calls = mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({
        collections: [
          collection({
            id: 9,
            title: "Franchise",
            state: "in_plex",
            plex_items: 3,
            download_missing: true,
            requests: { waiting: 4, requested: 0, downloading: 2, imported: 5, failed: 1 },
          }),
        ],
      }),
      "POST /collections/9/request-missing": () => ({ requested: 4, exists: 0, failed: 0, capped: 0, skipped: 0, items: [] }),
      "PUT /collections/9/download-missing": () => ({ download_missing: false }),
    });
    renderCollections("/collections?library=Movies");
    const card = await screen.findByRole("listitem", { name: "Franchise" });
    expect(within(card).getByText(/2 downloading/)).toBeInTheDocument();
    expect(within(card).getByText(/5 imported/)).toBeInTheDocument();
    expect(within(card).getByText(/1 failed/)).toHaveClass("text-err");
    expect(within(card).getByText(/Downloads missing/)).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Request 4 titles" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections/9/request-missing")).toBe(true));

    fireEvent.click(within(card).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(calls.some((c) => c.route === "PUT /collections/9/download-missing")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /collections/9/download-missing")!.body).toEqual({ download_missing: false });
  });

  it("retries a failed collection", async () => {
    let failed = true;
    const calls = mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({
        collections: [
          collection({ id: 1, title: "Action Picks", state: "in_plex" }),
          collection({ id: 4, title: "Broken", state: failed ? "failed" : "queued", last_error: failed ? "TMDb Error: Connection reset" : null }),
        ],
      }),
      "POST /collections/4/retry": () => {
        failed = false;
        return collection({ id: 4, title: "Broken", state: "queued", run_id: 9 });
      },
    });
    renderCollections("/collections?library=Movies");
    const broken = await screen.findByRole("listitem", { name: "Broken" });
    expect(within(screen.getByRole("listitem", { name: "Action Picks" })).queryByRole("button", { name: /Retry/ })).toBeNull();
    fireEvent.click(within(broken).getByRole("button", { name: "Retry Broken" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections/4/retry")).toBe(true));
    expect(await within(screen.getByRole("listitem", { name: "Broken" })).findByText("Queued")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Broken" })).queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows the empty state", async () => {
    mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({ collections: [] }),
    });
    renderCollections("/collections?library=Movies");
    expect(await screen.findByText("No collections yet in Movies.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "New collection" })[0]).toHaveAttribute("href", "/collections/new?library=Movies");
  });

  it("polls only while something is queued or building", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    mockApi({
      ...config,
      "GET /collections?library=Movies": () => {
        calls += 1;
        if (calls === 1) {
          return { collections: [collection({ id: 1, title: "Building One", state: "building" })] };
        }
        return { collections: [collection({ id: 1, title: "Building One", state: "in_plex", plex_items: 3 })] };
      },
    });
    renderCollections("/collections?library=Movies");
    expect(await screen.findByText("Building…")).toBeInTheDocument();
    expect(calls).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await waitFor(() => expect(calls).toBe(2));
    expect(await screen.findByText("In Plex · 3 titles")).toBeInTheDocument();

    const after = calls;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(calls).toBe(after);
  });

  it("changes library from Apply to", async () => {
    mockApi({
      ...config,
      "GET /collections?library=Movies": () => ({ collections: [collection({ id: 1, title: "Movies One", state: "missing" })] }),
      "GET /collections?library=TV%20Shows": () => ({ collections: [collection({ id: 2, title: "Shows One", state: "missing", library: "TV Shows" })] }),
    });
    renderCollections("/collections?library=Movies");
    expect(await screen.findByRole("listitem", { name: "Movies One" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Apply to"), { target: { value: "TV Shows" } });
    expect(await screen.findByRole("listitem", { name: "Shows One" })).toBeInTheDocument();
  });
});
