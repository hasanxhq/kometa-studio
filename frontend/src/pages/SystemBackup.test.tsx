import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BuiltinTask } from "../api";
import type { SwitchOver } from "../importApi";
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

const done = { ...backupTask, last: { started_at: "2026-10-30T10:00:00Z", finished_at: "2026-10-30T10:00:09Z", status: "succeeded" as const, message: "starr-studio-20261030-100000.zip: 120 files, 85.0 MB" } };

const active: SwitchOver = {
  id: 1,
  created_at: "2026-11-05T12:00:00Z",
  backup: "b-switch",
  imported: 2,
  ready_made: 1,
  kept: 0,
  libraries: ["Movies"],
  run_id: 7,
};

describe("Full backups", () => {
  it("backs up now, and lists the new zip with a download link", async () => {
    let state: BuiltinTask = backupTask;
    let backups: { name: string; size: number; created: string }[] = [];
    const calls = mockApi({
      "GET /import/switch-over": () => ({ active: null }),
      "GET /backups": () => ({ backups: [], keep: 30 }),
      "GET /tasks": () => ({ tasks: [state, checkTask] }),
      "POST /tasks/full_backup/run": () => {
        state = done;
        backups = [{ name: "starr-studio-20261030-100000.zip", size: 89_128_960, created: "2026-10-30T10:00:00Z" }];
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
    expect(link).toHaveAttribute("href", "/api/v1/backups/full/starr-studio-20261030-100000.zip");
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

describe("Move over from Kometa on Backup", () => {
  it("links to the wizard when there is no active switch-over", async () => {
    mockApi({
      "GET /import/switch-over": () => ({ active: null }),
      "GET /backups": () => ({ backups: [], keep: 30 }),
      "GET /tasks": () => ({ tasks: [backupTask, checkTask] }),
      "GET /backups/full": () => ({ backups: [] }),
    });
    renderAt("/system/backup");

    const card = (await screen.findByRole("heading", { name: "Move over from Kometa" })).closest("section")!;
    expect(within(card).getByRole("link", { name: "Move over from Kometa" })).toHaveAttribute("href", "/setup/move-over");
  });

  it("shows Undo and Export, lists losses, and posts delete_from_plex", async () => {
    const calls = mockApi({
      "GET /import/switch-over": () => ({ active }),
      "GET /import/undo": () => ({
        loses: {
          added: [{ library: "Movies", title: "New Studio Pick" }],
          changed: [{ library: "Movies", title: "Trending" }],
        },
        plex: [
          { library: "Movies", title: "New Studio Pick" },
          { library: "Movies", title: "Action" },
        ],
        unlabels: [{ library: "Movies", title: "Marvel" }],
        files: ["config.yml"],
        removes: ["studio/Movies/genre.yml"],
      }),
      "POST /import/undo": () => ({
        restored_files: 2,
        deleted_from_plex: ["New Studio Pick"],
        unlabelled_in_plex: ["Marvel"],
        problems: ["Not deleted from Plex: Action: the collection in Plex has no Studio label, so Studio didn't make it"],
        backup: "b-switch",
      }),
      "GET /backups": () => ({ backups: [], keep: 30 }),
      "GET /tasks": () => ({ tasks: [backupTask, checkTask] }),
      "GET /backups/full": () => ({ backups: [] }),
    });
    renderAt("/system/backup");

    const card = (await screen.findByRole("heading", { name: "Move over from Kometa" })).closest("section")!;
    expect(within(card).getByRole("link", { name: "Export" })).toHaveAttribute("href", "/api/v1/import/export");
    fireEvent.click(within(card).getByRole("button", { name: "Undo" }));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Collections added since")).toBeInTheDocument();
    expect(within(dialog).getByText("Collections changed since")).toBeInTheDocument();
    expect(within(dialog).getAllByText(/Movies: New Studio Pick/)).toHaveLength(2);
    expect(within(dialog).getByText(/Movies: Trending/)).toBeInTheDocument();
    expect(within(dialog).getByText("Back to Kometa: Studio's label comes off in Plex")).toBeInTheDocument();
    expect(within(dialog).getByText(/Movies: Marvel/)).toBeInTheDocument();
    expect(within(dialog).getByText("Studio's files removed")).toBeInTheDocument();
    expect(within(dialog).getByText("studio/Movies/genre.yml")).toBeInTheDocument();
    expect(within(dialog).getByText("config.yml")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Also delete these collections from Plex/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Undo" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /import/undo")).toBe(true));
    expect(calls.find((c) => c.route === "POST /import/undo")!.body).toEqual({ confirm: true, delete_from_plex: true });
    expect(await within(dialog).findByText(/Put back 2 files/)).toBeInTheDocument();
    expect(within(dialog).getByText("Deleted from Plex: New Studio Pick")).toBeInTheDocument();
    expect(within(dialog).getByText("Studio's label taken off in Plex: Marvel")).toBeInTheDocument();
    expect(within(dialog).getByText(/Not deleted from Plex: Action/)).toBeInTheDocument();
  });
});
