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
  filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
  sort_by: null,
  limit: null,
  visible: { library: true, home: false, shared: false },
  minimum_items: 1,
  summary: null,
  sort_title: null,
  plex_items: null,
  thumb: null,
  last_built_at: null,
  last_error: null,
  run_id: null,
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
    expect(within(action).getByText("In Plex · 12 titles")).toBeInTheDocument();
    expect(within(action).getByRole("link")).toHaveAttribute("href", "/collections/1");

    expect(within(screen.getByRole("listitem", { name: "Queued One" })).getByText("Queued")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Building One" })).getByText("Building…")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Broken" })).getByText("Failed: no titles")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Missing One" })).getByText("Not built yet")).toBeInTheDocument();

    const newLinks = screen.getAllByRole("link", { name: "New collection" });
    expect(newLinks[0]).toHaveAttribute("href", "/collections/new?library=Movies");
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
