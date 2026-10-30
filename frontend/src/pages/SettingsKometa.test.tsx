import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderAt } from "../test-utils";

describe("Settings → Kometa and UI", () => {
  it("shows where Kometa is, the run limits and its flags", async () => {
    mockApi({
      "GET /kometa": () => ({
        flags: ["--overlays-only", "--run"],
        flags_error: null,
        problem: null,
        paths: { python: "/.venv/bin/python3", entry: "/kometa.py", config: "/config/config.yml", schemas: null },
        run_timeout: 10800,
        kill_after: 30,
      }),
    });
    renderAt("/settings/kometa");
    expect(await screen.findByText("/kometa.py")).toBeInTheDocument();
    expect(screen.getByText("3 h")).toBeInTheDocument();
    expect(screen.getByText("30 s")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument(); // schemas
    expect(screen.getByText("--overlays-only")).toBeInTheDocument();
  });

  it("switches Show Advanced, the same switch as the header's", async () => {
    localStorage.clear();
    mockApi({});
    renderAt("/settings/ui");
    const boxes = await screen.findAllByRole("checkbox", { name: "Show Advanced" });
    expect(boxes).toHaveLength(2);
    fireEvent.click(boxes[1]);
    expect(boxes[0]).toBeChecked();
    expect(localStorage.getItem("studio.showAdvanced")).toBe("true");
  });
});
