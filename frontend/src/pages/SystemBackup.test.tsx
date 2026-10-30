import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BuiltinTask } from "../api";
import { mockApi, renderAt } from "../test-utils";

const backupTask: BuiltinTask = {
  name: "full_backup",
  label: "Full backup",
  enabled: true,
  days: [6],
  time: "04:30",
  timezone: "Asia/Kolkata",
  options: { keep: 4 },
  next_run: "2026-11-01T23:00:00Z",
  running: false,
  last: null,
};

const checkTask: BuiltinTask = { ...backupTask, name: "full_check", label: "Full check", enabled: false, days: [0, 1, 2, 3, 4, 5, 6], time: "04:00", options: {}, next_run: null };

const done = { ...backupTask, last: { started_at: "2026-10-30T10:00:00Z", finished_at: "2026-10-30T10:00:09Z", status: "succeeded" as const, message: "kometa-studio-20261030-100000.zip: 120 files, 85.0 MB" } };

describe("Full backups", () => {
  it("backs up now, and lists the new zip with a download link", async () => {
    let state: BuiltinTask = backupTask;
    let backups: { name: string; size: number; created: string }[] = [];
    const calls = mockApi({
      "GET /backups": () => ({ backups: [], keep: 30 }),
      "GET /tasks": () => ({ tasks: [state, checkTask] }),
      "POST /tasks/full_backup/run": () => {
        state = done;
        backups = [{ name: "kometa-studio-20261030-100000.zip", size: 89_128_960, created: "2026-10-30T10:00:00Z" }];
        return { ...backupTask, running: true };
      },
      "GET /backups/full": () => ({ backups }),
    });
    renderAt("/system/backup");

    const card = (await screen.findByRole("heading", { name: "Full backups" })).closest("section")!;
    expect(await within(card).findByText("No full backups yet.")).toBeInTheDocument();
    expect(within(card).getByText("Sun at 04:30 (Asia/Kolkata)")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Run now" }));

    const link = await within(card).findByRole("link", { name: "Download" });
    expect(link).toHaveAttribute("href", "/api/v1/backups/full/kometa-studio-20261030-100000.zip");
    expect(within(link.closest("li")!).getByText(/85\.0 MB/)).toBeInTheDocument();
    expect(within(card).getByText("Succeeded")).toBeInTheDocument();
    expect(calls.filter((c) => c.route === "POST /tasks/full_backup/run")).toHaveLength(1);
  });
});

describe("Studio's tasks", () => {
  it("changes when a task runs", async () => {
    const calls = mockApi({
      "GET /schedules": () => ({ schedules: [], timezone: "Asia/Kolkata", catch_ups: [] }),
      "GET /kometa": () => ({ flags: [], flags_error: null, problem: null }),
      "GET /tasks": () => ({ tasks: [backupTask, checkTask] }),
      "PUT /tasks/full_check": (body) => ({ ...checkTask, ...(body as object) }),
    });
    renderAt("/system/tasks");

    const card = (await screen.findByRole("heading", { name: "Studio's tasks" })).closest("section")!;
    const check = (await within(card).findByText("Full check")).closest("li")!;
    expect(within(check).getByText("Only when you run it")).toBeInTheDocument();
    fireEvent.click(within(check).getByRole("button", { name: "Edit" }));
    const form = within(card).getByRole("form", { name: "Edit Full check" });
    fireEvent.click(within(form).getByLabelText("Run on a schedule"));
    fireEvent.click(within(form).getByLabelText("Sat"));
    fireEvent.click(within(form).getByLabelText("Sun"));
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /tasks/full_check")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /tasks/full_check")?.body).toEqual({
      enabled: true,
      days: [0, 1, 2, 3, 4],
      time: "04:00",
      timezone: null,
      options: {},
    });
  });
});
