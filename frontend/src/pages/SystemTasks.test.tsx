import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunRequest, Schedule, Schedules } from "../api";
import { mockApi, renderAt } from "../test-utils";

const request: RunRequest = {
  mode: "collections",
  libraries: [],
  collections: [],
  files: [],
  ignore_schedules: false,
  no_missing: false,
  tests: false,
  timings: false,
  low_priority: true,
};

const nightly: Schedule = {
  id: 1,
  name: "Nightly collections",
  request,
  days: [0, 1, 2, 3, 4, 5, 6],
  time: "03:00",
  timezone: "Asia/Kolkata",
  enabled: true,
  catch_up: "run_once",
  next_run: new Date(Date.now() + 5 * 3600_000).toISOString(),
  last_run: { id: 9, status: "succeeded", trigger: "catch_up", started_at: "2026-10-30T03:00:00Z", finished_at: "2026-10-30T03:10:00Z" },
};

function listing(overrides: Partial<Schedules> = {}): Schedules {
  return { schedules: [nightly], timezone: "Asia/Kolkata", catch_ups: [], ...overrides };
}

const ready = { "GET /kometa": () => ({ flags: null, flags_error: null, problem: null }) };

describe("System → Tasks", () => {
  it("lists schedules with their next and last run", async () => {
    mockApi({ ...ready, "GET /schedules": () => listing() });
    renderAt("/system/tasks");

    const row = (await screen.findByText("Nightly collections")).closest("li")!;
    expect(row).toHaveTextContent("Collections only · Every day at 03:00");
    expect(row).toHaveTextContent("in 5 h");
    const last = within(row).getByRole("link", { name: /Finished/ });
    expect(last).toHaveAttribute("href", "/activity/queue/9");
    expect(last).toHaveTextContent("Catch-up");
  });

  it("tells you when Studio caught up on missed runs", async () => {
    mockApi({
      ...ready,
      "GET /schedules": () => listing({ catch_ups: [{ id: 9, status: "running", queued_at: "2026-10-30T04:00:00Z", name: "Nightly collections" }] }),
    });
    renderAt("/system/tasks");
    const banner = await screen.findByText("Studio caught up on missed runs");
    expect(banner.closest("section")).toHaveTextContent("Nightly collections: run #9");
  });

  it("adds a weekday schedule", async () => {
    const calls = mockApi({
      ...ready,
      "GET /schedules": () => listing({ schedules: [] }),
      "POST /schedules": () => nightly,
    });
    renderAt("/system/tasks");

    fireEvent.click(await screen.findByRole("button", { name: "Add schedule" }));
    const form = screen.getByRole("form", { name: "New schedule" });
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Weekday overlays" } });
    fireEvent.click(within(form).getByRole("radio", { name: "Overlays" }));
    fireEvent.change(within(form).getByLabelText("Libraries"), { target: { value: "Movies" } });
    fireEvent.click(within(form).getByRole("button", { name: "Weekdays" }));
    fireEvent.change(within(form).getByLabelText("Time"), { target: { value: "04:30" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add schedule" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /schedules")).toBe(true));
    expect(calls.find((c) => c.route === "POST /schedules")?.body).toEqual({
      name: "Weekday overlays",
      request: { ...request, mode: "overlays", libraries: ["Movies"] },
      days: [0, 1, 2, 3, 4],
      time: "04:30",
      timezone: "Asia/Kolkata",
      catch_up: "run_once",
      enabled: true,
    });
  });

  it("keeps a schedule's advanced options when editing with Show Advanced off", async () => {
    const withTimings = { ...nightly, request: { ...request, timings: true } };
    const calls = mockApi({ ...ready, "GET /schedules": () => listing({ schedules: [withTimings] }), "PUT /schedules/1": () => withTimings });
    renderAt("/system/tasks");

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit Nightly collections" });
    expect(within(form).getByText(/also uses advanced options/)).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Time"), { target: { value: "05:00" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /schedules/1")).toBe(true));
    const body = calls.find((c) => c.route === "PUT /schedules/1")?.body as { time: string; request: RunRequest };
    expect(body.time).toBe("05:00");
    expect(body.request.timings).toBe(true);
  });

  it("pauses, runs now and deletes", async () => {
    const calls = mockApi({
      ...ready,
      "GET /schedules": () => listing(),
      "PUT /schedules/1": () => ({ ...nightly, enabled: false }),
      "POST /schedules/1/run": () => ({ id: 12 }),
      "DELETE /schedules/1": () => new Response(null, { status: 204 }),
    });
    renderAt("/system/tasks");

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /schedules/1")?.body).toMatchObject({ enabled: false }));

    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByRole("link", { name: "run #12" })).toHaveAttribute("href", "/activity/queue/12");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.route === "DELETE /schedules/1")).toBe(false); // asks first
    fireEvent.click(screen.getByRole("button", { name: "Delete it" }));
    await waitFor(() => expect(calls.some((c) => c.route === "DELETE /schedules/1")).toBe(true));
  });
});
