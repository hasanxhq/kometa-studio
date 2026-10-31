import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Backup, LibraryCounts, Run, RunDetail, RunRequest, Status } from "../api";
import { mockApi, renderAt } from "../test-utils";
import { savedSince } from "./Overview";

const everything: RunRequest = {
  mode: "all",
  libraries: [],
  collections: [],
  files: [],
  ignore_schedules: false,
  no_missing: false,
  tests: false,
  timings: false,
  low_priority: true,
};

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3600_000).toISOString().replace(/\.\d+Z$/, "Z");

function run(overrides: Partial<Run>): Run {
  return {
    id: 1,
    status: "succeeded",
    trigger: "manual",
    schedule_id: null,
    request: everything,
    command: null,
    queued_at: hoursAgo(5),
    started_at: hoursAgo(5),
    finished_at: hoursAgo(4.9),
    exit_code: 0,
    error: null,
    summary: null,
    error_events: 0,
    ...overrides,
  };
}

const lastNight = run({
  id: 7,
  trigger: "schedule",
  started_at: hoursAgo(3),
  finished_at: hoursAgo(2.9),
  summary: { collections_created: 1, collections_modified: 2, items_added: 14, items_removed: 3 },
});

const status: Status = {
  version: "0.1.0",
  kometa: { version: "2.5.3", config: "/config/config.yml", updates: { installed: "2.5.3", checked_at: null, latest: null, notes: null, available: false } },
  database: { schema_version: 8 },
  health: [],
  runs: { current: null, queued: 0, next_scheduled: { at: new Date(Date.now() + 5 * 3600_000).toISOString(), schedule_id: 1, name: "Nightly" } },
};

const counts: LibraryCounts = {
  name: "Movies",
  plex_name: "Movies",
  collection_files: 2,
  overlay_files: 1,
  metadata_files: 0,
  defaults: 3,
  collections: 2,
  overlays: 0,
  operations: 0,
  problems: [],
};

const backup = (id: string, hours: number, reason: string): Backup => ({ id, created: hoursAgo(hours), reason, files: ["config.yml"], new_files: [] });

function routes(overrides: Record<string, (body: unknown) => unknown> = {}) {
  return {
    "GET /status": () => status,
    "GET /runs": () => ({ runs: [lastNight, run({ id: 6, status: "failed", started_at: hoursAgo(30), finished_at: hoursAgo(29) })], current: null }),
    "GET /runs/7": (): RunDetail => ({
      ...lastNight,
      events: [
        { event: "changes", received_at: hoursAgo(2.9), library_name: "Movies", collection: "Marvel", created: false, additions: 3, removals: 1 } as never,
        { event: "changes", received_at: hoursAgo(2.9), library_name: "Movies", collection: "Trending", created: true, additions: 11, removals: 0 } as never,
      ],
    }),
    "GET /schedules": () => ({ schedules: [], timezone: "UTC", catch_ups: [] }),
    "GET /kometa": () => ({ flags: [], flags_error: null, problem: null }),
    "GET /backups": () => ({ backups: [backup("b2", 1, "Added the Pixar collection"), backup("b1", 26, "Turned on the basic default for Movies")], keep: 30 }),
    "GET /plex/libraries": () => ({
      libraries: [
        { key: "1", title: "Movies", type: "movie", items: 1234, collections: 3, managed: 2 },
        { key: "2", title: "TV Shows", type: "show", items: 64, collections: 0, managed: 0 },
      ],
    }),
    "GET /config": () => ({ path: "/config/config.yml", libraries: [counts], playlist_files: [] }),
    "GET /kometa/full-check": () => ({
      last: { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "", at: hoursAgo(1) },
    }),
    ...overrides,
  };
}

describe("The Overview", () => {
  it("shows the last and next run, health, libraries and connections at a glance", async () => {
    mockApi(routes());
    renderAt("/");

    const glance = await screen.findByRole("list", { name: "At a glance" });
    await waitFor(() => expect(glance).toHaveTextContent("Nightly"));
    expect(within(glance).getByRole("link", { name: /Now/ })).toHaveTextContent("Nothing running");
    const last = within(glance).getByRole("link", { name: /Last run/ });
    expect(last).toHaveAttribute("href", "/activity/queue/7");
    expect(last).toHaveTextContent("Finished Everything");
    expect(last).toHaveTextContent("Scheduled");
    expect(last).toHaveTextContent("+14 −3 items");
    expect(within(glance).getByRole("link", { name: /Next run/ })).toHaveTextContent("in 5 h");
    expect(within(glance).getByRole("link", { name: /Health/ })).toHaveTextContent("No problems");

    const changed = await screen.findByRole("list", { name: "Collections changed" });
    expect(changed).toHaveTextContent("Movies · Marvel+3 −1");
    expect(changed).toHaveTextContent("New");

    const movies = (await screen.findByRole("link", { name: /^Movies/ })).closest("li")!;
    expect(movies).toHaveTextContent("1,234 movies");
    expect(movies).toHaveTextContent("3 collections · 2 by Kometa");
    expect(movies).toHaveTextContent("2 collection files, 1 overlay file, 3 defaults");
    expect(screen.getByRole("link", { name: /^TV Shows/ })).toHaveTextContent("Not in Kometa's config.yml");

    expect(await screen.findByText(/^Passed/)).toBeInTheDocument();
  });

  it("lists what was saved since the last successful run started", async () => {
    mockApi(routes());
    renderAt("/");
    const card = (await screen.findByText("Added the Pixar collection")).closest("section")!;
    expect(card).toHaveTextContent("Saved after run #7 started");
    expect(card).toHaveTextContent("The next run applies these.");
    expect(card).not.toHaveTextContent("Turned on the basic default");
  });

  it("says when a scoped run may have left changes unapplied", async () => {
    const scoped = run({ id: 8, request: { ...everything, mode: "collections", libraries: ["Movies"] }, started_at: hoursAgo(0.5), finished_at: hoursAgo(0.4) });
    mockApi(routes({ "GET /runs": () => ({ runs: [scoped], current: null }), "GET /runs/8": () => ({ ...scoped, events: [] }) }));
    renderAt("/");
    const card = (await screen.findByText(/Nothing has been saved since/)).closest("section")!;
    expect(card).toHaveTextContent("That run was Collections only · Movies, so it may not have applied everything saved before it.");
  });

  it("shows a running run, problems and a catch-up", async () => {
    const running = run({ id: 9, status: "running", trigger: "catch_up", started_at: hoursAgo(0.1), finished_at: null });
    mockApi(
      routes({
        "GET /status": () => ({
          ...status,
          health: [
            { source: "plex", level: "error", message: "Can't reach Plex.", link: "/settings/plex" },
            { source: "sign_in", level: "warning", message: "Sign-in isn't set up.", link: "/settings/general" },
          ],
          runs: { current: 9, queued: 1, next_scheduled: null },
        }),
        "GET /runs": () => ({ runs: [run({ id: 10, status: "queued", started_at: null, finished_at: null }), running, lastNight], current: 9 }),
        "GET /schedules": () => ({ schedules: [], timezone: "UTC", catch_ups: [{ id: 9, status: "running", queued_at: hoursAgo(0.1), name: "Nightly" }] }),
      }),
    );
    renderAt("/");
    const glance = await screen.findByRole("list", { name: "At a glance" });
    await waitFor(() => expect(within(glance).getByRole("link", { name: /Now/ })).toHaveTextContent("Running Everything"));
    expect(within(glance).getByRole("link", { name: /Now/ })).toHaveTextContent("Run #9");
    expect(within(glance).getByRole("link", { name: /Now/ })).toHaveTextContent("1 waiting");
    expect(within(glance).getByRole("link", { name: /Now/ })).toHaveAttribute("href", "/activity/queue/9");
    await waitFor(() => expect(within(glance).getByRole("link", { name: /Health/ })).toHaveTextContent("1 error, 1 warning"));
    expect(within(glance).getByRole("link", { name: /Health/ })).toHaveTextContent("Can't reach Plex.");
    expect(within(glance).getByRole("link", { name: /Next run/ })).toHaveTextContent("No schedule");
    expect(screen.getByText("Studio caught up on missed runs")).toBeInTheDocument();
  });

  it("starts a run", async () => {
    const calls = mockApi(routes({ "POST /runs": () => run({ id: 11, status: "queued" }) }));
    renderAt("/");
    const button = await screen.findByRole("button", { name: "Run now" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByRole("link", { name: "run #11" })).toHaveAttribute("href", "/activity/queue/11");
    expect(calls.find((call) => call.route === "POST /runs")?.body).toMatchObject({ mode: "all" });
  });
});

describe("Saves waiting for a run", () => {
  it("counts saves after the run started, and every save when nothing has run", () => {
    const backups = [backup("b2", 1, "new"), backup("b1", 3, "old")];
    expect(savedSince(backups, run({ started_at: hoursAgo(2) })).map((b) => b.id)).toEqual(["b2"]);
    expect(savedSince(backups, undefined).map((b) => b.id)).toEqual(["b2", "b1"]);
  });
});
