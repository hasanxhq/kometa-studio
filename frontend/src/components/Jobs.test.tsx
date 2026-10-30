import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Job } from "../api";
import { mockApi, renderAt } from "../test-utils";

const base: Omit<Job, "id" | "title" | "status" | "label"> = {
  kind: "run",
  message: null,
  progress: null,
  started_at: "2026-10-30T15:16:27Z",
  finished_at: null,
  link: "/activity/queue/6",
  run_id: 6,
  cancellable: false,
};

const running: Job = {
  ...base,
  id: "run-6",
  title: "Kometa: Overlays · TV Shows",
  status: "running",
  label: "Running",
  message: "(3/230) Westworld",
  progress: { value: 3, max: 230 },
  cancellable: true,
};
const queued: Job = { ...base, id: "run-7", title: "Kometa: Collections", status: "pending", label: "Queued", message: "Next in the queue", run_id: 7, cancellable: true };
const failed: Job = {
  ...base,
  id: "task-full_backup",
  kind: "task",
  title: "Full backup",
  status: "failed",
  label: "Failed",
  message: "Not enough disk space",
  finished_at: "2026-10-30T04:30:05Z",
  run_id: null,
  link: "/system/backup",
};
const done: Job = { ...base, id: "run-5", title: "Kometa: Everything", status: "completed", label: "Succeeded", finished_at: "2026-10-30T14:00:00Z", run_id: 5 };

beforeEach(() => localStorage.clear());

describe("The jobs drawer", () => {
  it("shows what runs, waits and finished, Bazarr-style, and stops a run", async () => {
    const calls = mockApi({
      "GET /jobs": () => ({ jobs: [running, queued, failed, done], at: "2026-10-30T15:17:00Z" }),
      "POST /runs/6/cancel": () => ({ id: 6 }),
    });
    renderAt("/system/status");

    const button = await screen.findByRole("button", { name: "Jobs: 1 running, 1 waiting" });
    fireEvent.click(button);
    const drawer = screen.getByRole("dialog", { name: "Jobs" });

    const headings = within(drawer)
      .getAllByRole("button", { expanded: true })
      .map((b) => b.textContent);
    expect(headings).toEqual(["▾Running1", "▾Waiting1", "▾Failed1", "▾Finished1"]);

    const run = within(drawer).getByRole("listitem", { name: "Kometa: Overlays · TV Shows" });
    expect(within(run).getByRole("img", { name: "3 of 230" })).toBeInTheDocument();
    expect(within(run).getByText("(3/230) Westworld")).toBeInTheDocument();
    expect(within(run).getByRole("link", { name: "Kometa: Overlays · TV Shows" })).toHaveAttribute("href", "/activity/queue/6");
    expect(within(drawer).getByText("Not enough disk space")).toBeInTheDocument();

    fireEvent.click(within(run).getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /runs/6/cancel")).toBe(true));
  });

  it("clears finished jobs from the drawer, and closes with Escape", async () => {
    mockApi({ "GET /jobs": () => ({ jobs: [failed, done], at: "2026-10-30T15:17:00Z" }) });
    renderAt("/system/status");
    fireEvent.click(await screen.findByRole("button", { name: "Jobs" }));
    const drawer = screen.getByRole("dialog", { name: "Jobs" });
    await within(drawer).findByText("Not enough disk space");
    fireEvent.click(within(drawer).getAllByRole("button", { name: "Clear" })[0]);
    expect(within(drawer).getByText("Nothing running, waiting or recently finished.")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Jobs" })).toBeNull();
  });
});
