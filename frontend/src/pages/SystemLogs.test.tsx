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
          { level: "INFO", text: "| Starting Run |" },
          { level: "ERROR", text: "| Trakt Error: List not found |" },
        ],
        truncated: false,
        size: 10,
      }),
      "GET /logs/file?path=meta.log&level=ERROR&q=": () => ({ path: "meta.log", lines: [{ level: "ERROR", text: "| Trakt Error: List not found |" }], truncated: false, size: 10 }),
      "GET /logs/file?path=meta.log&level=ERROR&q=trakt": () => ({ path: "meta.log", lines: [], truncated: false, size: 10 }),
    });
    renderAt("/system/logs");

    expect(await screen.findByText("| Starting Run |")).toBeInTheDocument();
    expect(screen.getByText("| Trakt Error: List not found |")).toHaveClass("text-err");
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/v1/logs/download?path=meta.log");

    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "ERROR" } });
    await waitFor(() => expect(screen.queryByText("| Starting Run |")).toBeNull());
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "trakt" } });
    expect(await screen.findByText("Nothing matches.")).toBeInTheDocument();
    expect(calls.map((c) => c.route)).toContain("GET /logs/file?path=meta.log&level=ERROR&q=trakt");
  });

  it("explains an empty logs folder", async () => {
    mockApi({ "GET /logs": () => ({ files: [] }) });
    renderAt("/system/logs");
    expect(await screen.findByText(/hasn't written any logs yet/)).toBeInTheDocument();
  });
});
