import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArrState, OverlayLibrary, Schedule } from "../api";
import { mockApi, renderAt } from "../test-utils";

const tv: OverlayLibrary = {
  library: "TV Shows",
  plex_name: "TV Shows",
  off: false,
  files: [{ kind: "default", value: "resolution", error: null, files: [{ path: "defaults/overlays/resolution.yml", title: "Resolution/Edition Overlays", docs_url: "https://kometa.wiki/en/latest/defaults/overlays/resolution", overlays: ["4K"] }] }],
  backup: { posters: 230, bytes: 47_185_920 },
  last_pass: { run_id: 7, status: "failed", started_at: "2026-10-30T19:43:08Z", finished_at: new Date().toISOString() },
  maintainerr: { collections: ["Unwatched - Leaving in 30 Days"], on_top: true },
};
const movies: OverlayLibrary = { ...tv, library: "Movies", plex_name: "Movies", files: [], backup: null, last_pass: null, maintainerr: null };

const schedule: Schedule = {
  id: 3,
  name: "Nightly",
  request: { mode: "all", libraries: [], collections: [], files: [], ignore_schedules: false, no_missing: false, tests: false, timings: false, low_priority: true },
  days: [0, 1, 2, 3, 4, 5, 6],
  time: "03:00",
  timezone: "Asia/Kolkata",
  enabled: true,
  catch_up: "run_once",
  next_run: new Date(Date.now() + 3_600_000).toISOString(),
  last_run: null,
};

const runs = { enabled: true, trigger: "relevant" as const, mode: "all" as const, wait_minutes: 10, libraries: ["TV Shows"] };
const arr = { settings: { radarr: { ...runs, enabled: false }, sonarr: runs } } as unknown as ArrState;

function routes(extra: Record<string, (body: unknown) => unknown> = {}) {
  return mockApi({
    "GET /overlays": () => ({ libraries: [movies, tv] }),
    "GET /schedules": () => ({ schedules: [schedule], timezone: "Asia/Kolkata", catch_up: null }),
    "GET /settings/arr": () => arr,
    ...extra,
  });
}

describe("Overlays", () => {
  it("says per library what draws overlays, when, and how its backup is", async () => {
    routes();
    renderAt("/overlays");

    const card = (await screen.findByRole("heading", { name: "TV Shows" })).closest("section")!;
    expect(within(card).getByRole("link", { name: "Resolution/Edition Overlays" })).toHaveAttribute("href", "https://kometa.wiki/en/latest/defaults/overlays/resolution");
    expect(within(card).getByText("230 posters backed up (45.0 MB)")).toBeInTheDocument();
    expect(within(card).getByText(/Its overlays go on top of Kometa's \(Unwatched - Leaving in 30 Days\)/)).toBeInTheDocument();
    expect(within(card).getByText("Nightly")).toBeInTheDocument();
    expect(within(card).getByText(/Also drawn after Sonarr imports \(those that matter\)/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Failed/ })).toHaveAttribute("href", "/activity/queue/7");

    const empty = screen.getByRole("heading", { name: "Movies" }).closest("section")!;
    expect(within(empty).getByText(/No overlay files/)).toBeInTheDocument();
    expect(within(empty).queryByRole("button", { name: "Turn overlays off" })).toBeNull();
  });

  it("applies now, adds a daily pass, and turns overlays off only after asking", async () => {
    const calls = routes({
      "POST /overlays/TV%20Shows/apply": () => ({ run_id: 8 }),
      "POST /overlays/TV%20Shows/off": () => ({ run_id: 9 }),
      "POST /schedules": () => schedule,
    });
    renderAt("/overlays");
    const card = (await screen.findByRole("heading", { name: "TV Shows" })).closest("section")!;

    fireEvent.click(within(card).getByRole("button", { name: "Apply now" }));
    expect(await within(card).findByRole("link", { name: "run #8" })).toHaveAttribute("href", "/activity/queue/8");

    fireEvent.change(within(card).getByLabelText("Daily overlay pass at"), { target: { value: "05:30" } });
    fireEvent.click(within(card).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.find((c) => c.route === "POST /schedules")?.body).toMatchObject({ name: "Overlays · TV Shows", time: "05:30", days: [0, 1, 2, 3, 4, 5, 6], request: { mode: "overlays", libraries: ["TV Shows"] } }));

    fireEvent.click(within(card).getByRole("button", { name: "Turn overlays off" }));
    expect(calls.some((c) => c.route === "POST /overlays/TV%20Shows/off")).toBe(false);
    expect(within(card).getByText(/Maintainerr's go back on top after/)).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Take them off TV Shows" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /overlays/TV%20Shows/off")).toBe(true));
  });

  it("turns them back on", async () => {
    const calls = routes({ "GET /overlays": () => ({ libraries: [{ ...tv, off: true }] }), "POST /overlays/TV%20Shows/on": () => ({ run_id: 10 }) });
    renderAt("/overlays");
    const card = (await screen.findByRole("heading", { name: "TV Shows" })).closest("section")!;
    expect(within(card).getByText(/Turned off: Kometa keeps the original posters here/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Apply now" })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Turn overlays on" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /overlays/TV%20Shows/on")).toBe(true));
  });
});
