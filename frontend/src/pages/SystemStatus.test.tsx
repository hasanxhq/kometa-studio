import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Status } from "../api";
import { mockApi, renderAt } from "../test-utils";

const status: Status = {
  version: "0.1.0",
  kometa: {
    version: "2.5.3",
    config: "/config/config.yml",
    updates: { installed: "2.5.3", checked_at: "2026-10-30T03:00:05Z", latest: "2.6.0", notes: "- Faster overlays", available: true },
  },
  database: { schema_version: 4 },
  health: [
    { source: "plex", level: "error", message: "Can't reach Plex at the address in config.yml: No answer within 5 s", link: "/settings/plex" },
    { source: "updates", level: "info", message: "Kometa 2.6.0 is out (you have 2.5.3).", link: "/system/updates" },
  ],
};

describe("Health", () => {
  it("lists each problem with a link to where it's fixed, and marks Status in the sidebar", async () => {
    mockApi({ "GET /status": () => status, "GET /kometa/full-check": () => ({ last: null }) });
    renderAt("/system/status");

    const health = (await screen.findByRole("heading", { name: "Health" })).closest("section")!;
    const plex = within(health).getByText(/Can't reach Plex/).closest("li")!;
    expect(within(plex).getByText("Error")).toBeInTheDocument();
    expect(within(plex).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/settings/plex");
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("img", { name: "Health errors" })).toBeInTheDocument();
  });

  it("says so when there's nothing wrong, with no dot", async () => {
    mockApi({ "GET /status": () => ({ ...status, health: [] }), "GET /kometa/full-check": () => ({ last: null }) });
    renderAt("/system/status");
    expect(await screen.findByText("No problems found.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Health/ })).toBeNull();
  });
});

describe("Updates", () => {
  it("shows a new Kometa version with its notes", async () => {
    mockApi({ "GET /status": () => status });
    renderAt("/system/updates");
    expect(await screen.findByText("Kometa 2.6.0 is out.")).toBeInTheDocument();
    expect(screen.getByText("- Faster overlays")).toBeInTheDocument();
  });

  it("says when Kometa was last found up to date", async () => {
    const upToDate = { ...status.kometa.updates, latest: null, notes: null, available: false };
    mockApi({ "GET /status": () => ({ ...status, kometa: { ...status.kometa, updates: upToDate } }) });
    renderAt("/system/updates");
    expect(await screen.findByText(/Up to date when Kometa last checked/)).toBeInTheDocument();
  });
});
