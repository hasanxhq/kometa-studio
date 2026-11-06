import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "./test-utils";
import { ReadyMadePicksProvider } from "./readyMadePicks";
import { Collections } from "./pages/Collections";
import { ReadyMade } from "./pages/ReadyMade";

const twoLibraries = {
  "GET /config": () => ({
    path: "/config/config.yml",
    libraries: [
      { name: "Movies", plex_name: "Movies" },
      { name: "TV Shows", plex_name: "TV Shows" },
    ],
    playlist_files: [],
  }),
};

const readyMadeMovies = {
  "GET /ready-made/libraries/Movies": () => ({
    library: "Movies",
    library_type: "movie",
    counted_at: new Date().toISOString(),
    counting: false,
    categories: [],
  }),
  "GET /ready-made/libraries/TV%20Shows": () => ({
    library: "TV Shows",
    library_type: "show",
    counted_at: new Date().toISOString(),
    counting: false,
    categories: [],
  }),
};

const collectionsEmpty = {
  "GET /collections?library=Movies": () => ({ collections: [] }),
  "GET /collections?library=TV%20Shows": () => ({ collections: [] }),
};

function renderLibraryTest(initialPath: string, routes: Record<string, (body: unknown) => unknown>) {
  mockApi({ "GET /jobs": () => ({ jobs: [], at: new Date().toISOString() }), ...routes });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/ready-made", element: <ReadyMade /> },
      { path: "/collections", element: <Collections /> },
    ],
    { initialEntries: [initialPath] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <ReadyMadePicksProvider>
        <RouterProvider router={router} />
      </ReadyMadePicksProvider>
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useLibrary", () => {
  it("prefers a valid ?library= over localStorage", async () => {
    localStorage.setItem("studio:library", "TV Shows");
    renderLibraryTest("/ready-made?library=Movies", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("Movies"));
  });

  it("uses localStorage when the URL has no library", async () => {
    localStorage.setItem("studio:library", "TV Shows");
    renderLibraryTest("/ready-made", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("TV Shows"));
  });

  it("falls back to the first library when ?library= is unknown", async () => {
    renderLibraryTest("/ready-made?library=Nope", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("Movies"));
  });

  it("falls back to the first library when localStorage names an unknown library", async () => {
    localStorage.setItem("studio:library", "Nope");
    renderLibraryTest("/ready-made", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("Movies"));
  });

  it("treats empty localStorage as unset", async () => {
    localStorage.setItem("studio:library", "");
    renderLibraryTest("/ready-made", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("Movies"));
  });

  it("does not break when localStorage get throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderLibraryTest("/ready-made", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("Movies"));
  });

  it("keeps other search params when setLibrary runs", async () => {
    const router = renderLibraryTest("/collections?kept=done&library=Movies", { ...twoLibraries, ...collectionsEmpty });
    await screen.findByRole("heading", { name: "Collections", level: 2 });
    fireEvent.change(screen.getByRole("combobox", { name: /Apply to/i }), { target: { value: "TV Shows" } });
    await waitFor(() => expect(router.state.location.search).toContain("kept=done"));
    expect(router.state.location.search).toContain("library=TV+Shows");
  });

  it("persists a valid ?library= from the URL into localStorage", async () => {
    renderLibraryTest("/ready-made?library=TV%20Shows", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    await waitFor(() => expect(picker).toHaveValue("TV Shows"));
    await waitFor(() => expect(localStorage.getItem("studio:library")).toBe("TV Shows"));
  });

  it("does not break when localStorage set throws on pick", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderLibraryTest("/ready-made", { ...twoLibraries, ...readyMadeMovies });
    const picker = await screen.findByRole("combobox", { name: /Apply to/i });
    fireEvent.change(picker, { target: { value: "TV Shows" } });
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Apply to/i })).toHaveValue("TV Shows"));
  });

  it("remembers the choice across a navigation to another page with no ?library=", async () => {
    mockApi({
      "GET /jobs": () => ({ jobs: [], at: new Date().toISOString() }),
      ...twoLibraries,
      ...readyMadeMovies,
      ...collectionsEmpty,
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter(
      [
        { path: "/ready-made", element: <ReadyMade /> },
        { path: "/collections", element: <Collections /> },
      ],
      { initialEntries: ["/ready-made"] },
    );
    render(
      <QueryClientProvider client={queryClient}>
        <ReadyMadePicksProvider>
          <RouterProvider router={router} />
        </ReadyMadePicksProvider>
      </QueryClientProvider>,
    );
    const applyRm = await screen.findByRole("combobox", { name: /Apply to/i });
    fireEvent.change(applyRm, { target: { value: "TV Shows" } });
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Apply to/i })).toHaveValue("TV Shows"));
    await act(async () => {
      router.navigate("/collections");
    });
    await waitFor(() => expect(screen.getByRole("combobox", { name: /Apply to/i })).toHaveValue("TV Shows"));
  });
});
