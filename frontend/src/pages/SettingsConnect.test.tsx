import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArrState, MaintainerrState } from "../api";
import { mockApi, renderAt } from "../test-utils";

const state: ArrState = {
  settings: { enabled: false, mode: "all", wait_minutes: 10, libraries: { radarr: [], sonarr: [] } },
  connections: {
    radarr: { source: "config", url: null, has_key: false, username: null, has_password: false, config_url: "http://radarr:7878", status: null },
    sonarr: { source: "config", url: null, has_key: false, username: null, has_password: false, config_url: null, status: null },
  },
  pending: null,
};

const overview = {
  path: "/config/config.yml",
  libraries: [{ name: "Movies" }, { name: "TV Shows" }],
  playlist_files: [],
};

const notConnected: MaintainerrState = {
  url: null,
  username: null,
  has_password: false,
  leave_overlays_alone: true,
  collections: [],
  overlays_enabled: false,
  error: null,
  checked_seconds_ago: null,
  risks: [],
};

describe("Maintainerr", () => {
  it("tests and connects, keeping its overlays on top by default", async () => {
    const connected: MaintainerrState = {
      ...notConnected,
      url: "http://maintainerr:6246",
      collections: [{ title: "Leaving Soon", library: "Movies", overlays: true }],
      overlays_enabled: true,
      risks: ["Movies: delete_collections would delete Maintainerr's collections (“Leaving Soon”): Kometa sees them as unmanaged. Limit it with managed: true."],
    };
    const calls = mockApi({
      "GET /settings/arr": () => state,
      "GET /config": () => overview,
      "GET /settings/maintainerr": () => notConnected,
      "POST /settings/maintainerr/test": () => ({ ok: true, collections: 1, overlays_enabled: true }),
      "PUT /settings/maintainerr": () => connected,
    });
    renderAt("/settings/connect");

    const form = await screen.findByRole("form", { name: "Maintainerr" });
    fireEvent.change(within(form).getByLabelText("URL"), { target: { value: "http://maintainerr:6246" } });
    expect(within(form).getByLabelText("Password")).toBeDisabled(); // until there's a username
    fireEvent.change(within(form).getByLabelText(/Username/), { target: { value: "hasan" } });
    fireEvent.change(within(form).getByLabelText("Password"), { target: { value: "seedbox-pass" } });
    expect(within(form).getByLabelText(/Leave Maintainerr overlays alone/)).toBeChecked();
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Maintainerr answered: 1 collection, overlays on.")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Kometa's config would touch Maintainerr's collections")).toBeInTheDocument();
    expect(screen.getByText(/Limit it with managed: true/)).toBeInTheDocument();
    expect(screen.getByText("Protecting 1 collection:")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /settings/maintainerr/test")?.body).toEqual({
      url: "http://maintainerr:6246",
      username: "hasan",
      password: "seedbox-pass",
    });
    expect(calls.find((c) => c.route === "PUT /settings/maintainerr")?.body).toEqual({
      url: "http://maintainerr:6246",
      username: "hasan",
      password: "seedbox-pass",
      leave_overlays_alone: true,
    });
  });
});

describe("Settings → Connect", () => {
  it("uses Kometa's Radarr, tests it, and saves what imports run", async () => {
    const calls = mockApi({
      "GET /settings/arr": () => state,
      "GET /config": () => overview,
      "POST /settings/arr/radarr/test": () => ({ ok: true, app: "Radarr", version: "5.14.0" }),
      "PUT /settings/arr": (body) => ({ ...state, settings: body }),
    });
    renderAt("/settings/connect");

    const radarr = await screen.findByRole("form", { name: "Radarr" });
    expect(within(radarr).getByText("http://radarr:7878")).toBeInTheDocument();
    fireEvent.click(within(radarr).getByRole("button", { name: "Test" }));
    expect(await within(radarr).findByText("Radarr 5.14.0 answered.")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /settings/arr/radarr/test")?.body).toEqual({ source: "config" });

    fireEvent.click(screen.getByLabelText("Run Kometa after Radarr or Sonarr imports something"));
    fireEvent.change(screen.getByLabelText("Run"), { target: { value: "overlays" } });
    const libraries = (await screen.findByText("Libraries to run for Radarr's imports")).closest("fieldset")!;
    fireEvent.click(libraries.querySelector("input")!); // Movies
    fireEvent.click(within(screen.getByRole("form", { name: "Runs after imports" })).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /settings/arr")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /settings/arr")?.body).toEqual({
      enabled: true,
      mode: "overlays",
      wait_minutes: 10,
      libraries: { radarr: ["Movies"], sonarr: [] },
    });
  });

  it("saves a Sonarr entered by hand, keeping a saved key secret", async () => {
    const calls = mockApi({
      "GET /settings/arr": () => state,
      "GET /config": () => overview,
      "PUT /settings/arr/sonarr": () => ({
        ...state,
        connections: {
          ...state.connections,
          sonarr: { source: "studio", url: "http://sonarr:8989", has_key: true, username: null, has_password: false, config_url: null, status: null },
        },
      }),
    });
    renderAt("/settings/connect");

    const sonarr = await screen.findByRole("form", { name: "Sonarr" });
    expect(within(sonarr).getByText("(config.yml has no url and token)")).toBeInTheDocument();
    fireEvent.click(within(sonarr).getByLabelText("Enter it here"));
    fireEvent.change(within(sonarr).getByLabelText("URL"), { target: { value: "http://sonarr:8989" } });
    fireEvent.change(within(sonarr).getByLabelText("API key"), { target: { value: "abc123" } });
    fireEvent.click(within(sonarr).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /settings/arr/sonarr")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /settings/arr/sonarr")?.body).toEqual({
      source: "studio",
      url: "http://sonarr:8989",
      api_key: "abc123",
      username: null,
      password: null,
    });
    const saved = await screen.findByRole("form", { name: "Sonarr" });
    expect(within(saved).getByLabelText("API key")).toHaveValue("");
    expect(within(saved).getByPlaceholderText("Saved (leave empty to keep it)")).toBeInTheDocument();
  });

  it("shows imports waiting and a failing check", async () => {
    mockApi({
      "GET /settings/arr": () => ({
        ...state,
        connections: { ...state.connections, radarr: { ...state.connections.radarr, status: { checked_at: new Date().toISOString(), ok: false, error: "The API key was rejected" } } },
        pending: {
          first_at: new Date().toISOString(),
          last_at: new Date().toISOString(),
          due_at: new Date(Date.now() + 10 * 60_000).toISOString(),
          imports: 3,
          titles: ["Avatar: The Last Airbender (2024)"],
          kinds: ["sonarr"],
        },
      }),
      "GET /config": () => overview,
    });
    renderAt("/settings/connect");
    expect(await screen.findByText(/3 imports waiting \(Avatar: The Last Airbender \(2024\)\)/)).toBeInTheDocument();
    expect(screen.getByText(/Last check failed .*The API key was rejected/)).toBeInTheDocument();
  });
});
