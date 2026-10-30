import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HistoryEvent } from "../api";
import { mockApi, renderAt } from "../test-utils";

function event(id: number, overrides: Partial<HistoryEvent>): HistoryEvent {
  return {
    id,
    run_id: 4,
    event: "changes",
    received_at: "2026-10-30T03:10:00Z",
    library: "Movies",
    collection: "Trending",
    playlist: null,
    message: null,
    created: false,
    poster_url: null,
    additions: [],
    removals: [],
    radarr_adds: [],
    sonarr_adds: [],
    ...overrides,
  };
}

describe("Activity → History", () => {
  it("lists changes with their items, filters, and pages back", async () => {
    const calls = mockApi({
      "GET /history": () => ({
        events: [
          event(9, { created: true, additions: [{ title: "Dune", tmdb_id: 438631, tvdb_id: null }], removals: [{ title: "Cats", tmdb_id: 536869, tvdb_id: null }] }),
          event(8, { event: "delete", collection: null, message: "Collection Old Stuff Deleted" }),
        ],
        libraries: ["Movies", "TV Shows"],
        next: 8,
      }),
      "GET /history?before=8": () => ({ events: [event(3, { library: "TV Shows", collection: "Popular", additions: [{ title: "Lost", tmdb_id: null, tvdb_id: 73739 }] })], libraries: [], next: null }),
      "GET /history?library=TV+Shows": () => ({ events: [], libraries: ["Movies", "TV Shows"], next: null }),
    });
    renderAt("/activity/history");

    const trending = (await screen.findByText("Trending")).closest("li")!;
    expect(trending).toHaveTextContent("New");
    expect(trending).toHaveTextContent("+1 −1");
    expect(screen.getByRole("link", { name: "Dune" })).toHaveAttribute("href", "https://www.themoviedb.org/movie/438631");
    expect(screen.getByText("Collection Old Stuff Deleted").closest("li")).toHaveTextContent("Deleted");

    fireEvent.click(screen.getByRole("button", { name: "Show older" }));
    expect(await screen.findByRole("link", { name: "Lost" })).toHaveAttribute("href", "https://www.thetvdb.com/dereferrer/series/73739");

    fireEvent.change(screen.getByLabelText("Library"), { target: { value: "TV Shows" } });
    await waitFor(() => expect(calls.some((c) => c.route === "GET /history?library=TV+Shows")).toBe(true));
    expect(await screen.findByText("Nothing matches.")).toBeInTheDocument();
  });
});
