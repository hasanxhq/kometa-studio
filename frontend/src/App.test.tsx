import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { pages } from "./nav";
import { mockApi, renderAt } from "./test-utils";

describe("App shell", () => {
  it("links to every page in the sidebar", async () => {
    mockApi({});
    renderAt("/libraries");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const page of pages) {
      expect(nav.querySelector(`a[href="${page.path}"]`)).not.toBeNull();
    }
  });

  it("opens on the Overview", async () => {
    mockApi({});
    renderAt("/");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Overview"));
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Libraries" })).not.toHaveAttribute("aria-current");
  });

  it("shows versions on System → Status", async () => {
    mockApi({
      "GET /status": () => ({ version: "0.0.0", kometa: { version: "2.5.3", config: "/config/config.yml", updates: { installed: "2.5.3", checked_at: null, latest: null, notes: null, available: false } }, database: { schema_version: 1 }, health: [] }),
      "GET /kometa/full-check": () => ({ last: null }),
    });
    renderAt("/system/status");
    expect(await screen.findByText("2.5.3")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("explains when the API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 502, statusText: "Bad Gateway" }));
    renderAt("/system/status");
    expect(await screen.findByRole("alert")).toHaveTextContent("502");
  });
});
