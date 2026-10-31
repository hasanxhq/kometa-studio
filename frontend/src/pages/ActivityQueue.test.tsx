import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { KometaInfo, Run, RunDetail } from "../api";
import { FakeEventSource, mockApi, renderAt } from "../test-utils";

const ALL_FLAGS = ["--run", "--collections-only", "--overlays-only", "--operations-only", "--metadata-only", "--playlists-only", "--low-priority"];
const ready: KometaInfo = { flags: ALL_FLAGS, flags_error: null, problem: null };

const request = {
  mode: "collections" as const,
  libraries: ["Movies"],
  collections: [],
  files: [],
  ignore_schedules: false,
  no_missing: false,
  tests: false,
  timings: false,
  low_priority: true,
};

function run(overrides: Partial<Run>): Run {
  return {
    id: 1,
    status: "succeeded",
    trigger: "manual",
    schedule_id: null,
    request,
    command: "/.venv/bin/python3 /kometa.py --config /config/config.yml --run --collections-only",
    queued_at: "2026-10-30T03:00:00Z",
    started_at: "2026-10-30T03:00:01Z",
    finished_at: "2026-10-30T03:04:31Z",
    exit_code: 0,
    error: null,
    summary: null,
    error_events: 0,
    ...overrides,
  };
}

beforeEach(() => {
  FakeEventSource.install();
});

describe("Activity → Queue", () => {
  it("queues a collections run for the typed libraries", async () => {
    const calls = mockApi({
      "GET /runs": () => ({ runs: [], current: null }),
      "GET /kometa": () => ready,
      "POST /runs": () => run({ id: 7, status: "queued" }),
    });
    renderAt("/activity/queue");

    fireEvent.click(await screen.findByRole("radio", { name: "Collections" }));
    fireEvent.change(screen.getByLabelText("Libraries"), { target: { value: "Movies, TV Shows ," } });
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));

    expect(await screen.findByRole("link", { name: "run #7" })).toHaveAttribute("href", "/activity/queue/7");
    expect(calls.find((c) => c.route === "POST /runs")?.body).toEqual({
      ...request,
      libraries: ["Movies", "TV Shows"],
    });
  });

  it("follows the running run's log and can cancel it", async () => {
    const calls = mockApi({
      "GET /runs": () => ({ runs: [run({ id: 3, status: "running", finished_at: null, exit_code: null })], current: 3 }),
      "GET /kometa": () => ready,
      "POST /runs/3/cancel": () => run({ id: 3, status: "cancelled" }),
    });
    renderAt("/activity/queue");

    expect(await screen.findByRole("heading", { name: "Running: Collections only · Movies" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Details" })).toHaveAttribute("href", "/activity/queue/3");
    const source = FakeEventSource.latest();
    expect(source.url).toBe("/api/v1/runs/3/stream");
    source.open();
    source.emit("lines", ["Starting Kometa", "| Config Error: tmdb apikey is required |"]);
    const log = screen.getByLabelText("Run log");
    expect(within(log).getByText("Starting Kometa")).toBeInTheDocument();
    expect(within(log).getByText(/Config Error/)).toHaveClass("text-err");

    // A reconnect resends the log so far; it must not show twice.
    source.open();
    source.emit("lines", ["Starting Kometa"]);
    expect(within(log).getAllByText("Starting Kometa")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /runs/3/cancel")).toBe(true));
    source.emit("end", { status: "cancelled", dropped: false });
    expect(source.closed).toBe(true);
  });

  it("lists recent runs with their numbers", async () => {
    mockApi({
      "GET /runs": () => ({
        runs: [run({ id: 2, summary: { items_added: 12, items_removed: 3 }, error_events: 1 }), run({ id: 1, status: "failed" })],
        current: null,
      }),
      "GET /kometa": () => ready,
    });
    renderAt("/activity/queue");

    const recent = (await screen.findByRole("heading", { name: "Recent runs" })).closest("section")!;
    const first = await within(recent).findByRole("link", { name: /#2/ });
    expect(first).toHaveAttribute("href", "/activity/queue/2");
    expect(first).toHaveTextContent("+12 −3 items");
    expect(first).toHaveTextContent("1 error");
    expect(first).toHaveTextContent("4 min 30 s");
    expect(within(recent).getByRole("link", { name: /#1/ })).toHaveTextContent("Failed");
  });

  it("explains when Kometa can't run, and greys out what it doesn't support", async () => {
    mockApi({
      "GET /runs": () => ({ runs: [], current: null }),
      "GET /kometa": () => ({ flags: ["--run", "--collections-only"], flags_error: null, problem: "Kometa's config.yml doesn't exist yet." }),
    });
    renderAt("/activity/queue");

    expect(await screen.findByRole("alert")).toHaveTextContent("config.yml doesn't exist yet");
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Overlays" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Collections" })).toBeEnabled();
  });
});

describe("A run's page", () => {
  it("shows Kometa's numbers, errors and changed collections", async () => {
    const detail: RunDetail = {
      ...run({
        id: 5,
        summary: { collections_created: 1, collections_modified: 4, items_added: 12, items_removed: 3 },
        error_events: 1,
      }),
      events: [
        { event: "changes", received_at: "", library_name: "Movies", collection: "Trending", created: true, additions: 10, removals: 0 },
        { event: "changes", received_at: "", library_name: "Movies", collection: "Popular", additions: 2, removals: 3 },
        { event: "error", received_at: "", library_name: "Movies", collection: "IMDb Top 250", error: "IMDb list not found", critical: false },
      ],
    };
    mockApi({ "GET /runs/5": () => detail });
    renderAt("/activity/queue/5");

    expect(await screen.findByRole("heading", { name: "Run #5: Collections only · Movies" })).toBeInTheDocument();
    const numbers = screen.getByRole("heading", { name: "What changed" }).closest("section")!;
    expect(within(numbers).getByText("Items added").previousSibling).toHaveTextContent("12");
    expect(screen.getByText("IMDb list not found")).toBeInTheDocument();
    const changed = screen.getByRole("heading", { name: "Collections changed (2)" }).closest("section")!;
    expect(within(changed).getByText("Movies · Trending")).toBeInTheDocument();
    expect(within(changed).getByText("New")).toBeInTheDocument();
    expect(FakeEventSource.latest().url).toBe("/api/v1/runs/5/stream");
  });

  it("runs a failed run again with the same request, and opens the new run", async () => {
    const failed: RunDetail = { ...run({ id: 6, status: "failed", error: "Config Error: tmdb sub-attribute apikey not found" }), events: [] };
    const calls = mockApi({
      "GET /runs/6": () => failed,
      "POST /runs": () => run({ id: 7, status: "queued", started_at: null, finished_at: null }),
      "GET /runs/7": (): RunDetail => ({ ...run({ id: 7, status: "queued", started_at: null, finished_at: null }), events: [] }),
    });
    renderAt("/activity/queue/6");

    fireEvent.click(await screen.findByRole("button", { name: "Run again" }));
    expect(await screen.findByRole("heading", { name: "Run #7: Collections only · Movies" })).toBeInTheDocument();
    expect(calls.find((call) => call.route === "POST /runs")?.body).toEqual(request);
  });

  it("has no Run again while a run is going", async () => {
    mockApi({ "GET /runs/8": (): RunDetail => ({ ...run({ id: 8, status: "running", finished_at: null }), events: [] }) });
    renderAt("/activity/queue/8");
    expect(await screen.findByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run again" })).toBeNull();
  });
});
