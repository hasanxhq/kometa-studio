import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderAt } from "../test-utils";

describe("System → Logs", () => {
  it("opens meta.log, and filters by level and search", async () => {
    const calls = mockApi({
      "GET /logs": () => ({ files: [{ path: "meta.log", size: 10, modified: 2 }, { path: "Movies/library.log", size: 5, modified: 1 }] }),
      "GET /logs/file?path=meta.log&level=INFO&q=": () => ({
        path: "meta.log",
        lines: [
          { level: "INFO", text: "[2026-10-30 04:00:00,002] kometa.py   INFO       | Starting Run |" },
          { level: "ERROR", text: "[2026-10-30 04:00:03,300] builder.py   ERROR      | Trakt Error: List not found |" },
        ],
        truncated: false,
        size: 10,
      }),
      "GET /logs/file?path=meta.log&level=ERROR&q=": () => ({ path: "meta.log", lines: [{ level: "ERROR", text: "[2026-10-30 04:00:03,300] builder.py   ERROR      | Trakt Error: List not found |" }], truncated: false, size: 10 }),
      "GET /logs/file?path=meta.log&level=ERROR&q=trakt": () => ({ path: "meta.log", lines: [], truncated: false, size: 10 }),
    });
    renderAt("/system/logs");

    expect(await screen.findByText("Starting Run")).toBeInTheDocument();
    expect(screen.getByText("Trakt Error: List not found").parentElement).toHaveClass("text-err");
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/v1/logs/download?path=meta.log");

    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "ERROR" } });
    await waitFor(() => expect(screen.queryByText("Starting Run")).toBeNull());
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "trakt" } });
    expect(await screen.findByText("Nothing matches.")).toBeInTheDocument();
    expect(calls.map((c) => c.route)).toContain("GET /logs/file?path=meta.log&level=ERROR&q=trakt");
  });

  it("shows the time and message without Kometa's columns", async () => {
    const { splitLine } = await import("./SystemLogs");
    expect(splitLine("[2026-10-30 04:00:02,200] builder.py                  WARNING    | Collection Warning: no items  |")).toEqual({
      time: "04:00:02",
      message: "Collection Warning: no items",
    });
    expect(splitLine("[2026-10-30 04:00:04,400] kometa.py   [TRACE]    | Cache hit |")).toEqual({ time: "04:00:04", message: "Cache hit" });
    expect(splitLine("                                                    | (continued) https://trakt.tv/x |")).toEqual({
      time: null,
      message: "(continued) https://trakt.tv/x",
    });
    expect(splitLine("Traceback (most recent call last):")).toEqual({ time: null, message: "Traceback (most recent call last):" });
  });

  it("explains an empty logs folder", async () => {
    mockApi({ "GET /logs": () => ({ files: [] }) });
    renderAt("/system/logs");
    expect(await screen.findByText(/hasn't written any logs yet/)).toBeInTheDocument();
  });
});
