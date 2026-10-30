import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { pages } from "./nav";

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App queryClient={queryClient} />
    </MemoryRouter>,
  );
}

describe("App shell", () => {
  it("links to every page in the sidebar", () => {
    renderAt("/libraries");
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const page of pages) {
      expect(nav.querySelector(`a[href="${page.path}"]`)).not.toBeNull();
    }
  });

  it("sends / to Libraries", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Libraries");
  });

  it("shows versions on System → Status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ version: "0.0.0", kometa: { version: "2.5.3", config: "/config/config.yml" }, database: { schema_version: 1 } }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
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
