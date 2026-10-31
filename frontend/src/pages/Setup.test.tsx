import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SetupState, Validation } from "../api";
import { mockApi, renderAt } from "../test-utils";

const passed: Validation = { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" };
const counts = { collection_files: 0, overlay_files: 0, metadata_files: 0, defaults: 0, collections: 0, overlays: 0, operations: 0, problems: [] };

const general = (configured = false) => ({ auth: { configured, username: null, required: "enabled" } });
const plexState = { config: { path: "/config/config.yml", url: null, token: null, error: null }, account: null };

function routes(setup: () => SetupState, extra = {}) {
  return {
    "GET /config/setup": setup,
    "GET /settings/general": () => general(),
    "GET /plex": () => plexState,
    "GET /settings/services": () => ({ tmdb: { apikey: null }, mdblist: { apikey: null } }),
    ...extra,
  };
}

const none: SetupState = { plex: false, tmdb: false, library: false, done: false };

describe("First-run setup", () => {
  it("starts with Plex, and keeps the rest until it's connected", async () => {
    mockApi(routes(() => none));
    renderAt("/setup");

    expect(await screen.findByText(/Kometa needs three things/)).toBeInTheDocument();
    expect(screen.getByText("Connect Plex").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Add your TMDb key").closest("details")).toBeNull(); // not openable yet
    expect(screen.getByText("Choose your libraries").closest("details")).toBeNull();
    expect(screen.getAllByText("After the step above")).toHaveLength(2);
    expect(screen.queryByText("Kometa is ready to run")).toBeNull();
  });

  it("asks for a tested TMDb key once Plex is connected, then moves on", async () => {
    let state: SetupState = { ...none, plex: true };
    mockApi(
      routes(() => state, {
        "POST /settings/services/tmdb/test": () => ({ ok: true }),
        "PUT /settings/services/tmdb": () => {
          state = { ...state, tmdb: true };
          return { tmdb: { apikey: "…ab12" }, mdblist: { apikey: null } };
        },
        "GET /plex/libraries": () => ({ libraries: [] }),
        "GET /config": () => ({ path: "/config/config.yml", libraries: [], playlist_files: [] }),
      }),
    );
    renderAt("/setup");

    const key = await screen.findByLabelText(/TMDb API key/);
    expect(screen.getByRole("link", { name: "Settings → Network" })).toHaveAttribute("href", "/settings/network");
    const form = screen.getByRole("form", { name: "TMDb" });
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled(); // tested first, like every connection
    fireEvent.change(key, { target: { value: "a-key" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    await waitFor(() => expect(within(form).getByRole("button", { name: "Save" })).toBeEnabled());
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Pick the Plex libraries/)).toBeInTheDocument();
    expect(screen.getByText("Choose your libraries").closest("details")).toHaveAttribute("open");
  });

  it("adds a Plex library, and says Kometa is ready", async () => {
    let state: SetupState = { ...none, plex: true, tmdb: true };
    let inConfig: string[] = [];
    const calls = mockApi(
      routes(() => state, {
        "GET /plex/libraries": () => ({
          libraries: [
            { key: "1", title: "Movies", type: "movie", collections: 0, managed: 0 },
            { key: "2", title: "Bangtan", type: "artist", collections: 0, managed: 0 },
          ],
        }),
        "GET /config": () => ({ path: "/config/config.yml", libraries: inConfig.map((name) => ({ name, plex_name: name, ...counts })), playlist_files: [] }),
        "POST /config/libraries": (body: { name: string }) => {
          inConfig = [body.name];
          state = { ...state, library: true, done: true };
          return { backup: "b", files: [], validation: passed };
        },
      }),
    );
    renderAt("/setup");

    await screen.findByText("Bangtan");
    const movies = screen.getByText("Bangtan").closest("ul")!.querySelector("li")!;
    expect(movies).toHaveTextContent("Movies");
    expect(screen.getByText("Bangtan").closest("li")).toHaveTextContent("Music");
    fireEvent.click(within(movies).getByRole("button", { name: "Add to Kometa" }));

    expect(await screen.findByText("Kometa is ready to run")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /config/libraries")?.body).toEqual({ name: "Movies" });
    expect(screen.getByRole("link", { name: "Add a collection" })).toHaveAttribute("href", "/libraries");
    expect(screen.getByRole("link", { name: /connect Radarr, Sonarr/ })).toHaveAttribute("href", "/settings/connect");
  });

  it("offers sign-in as optional once the rest is done, and doesn't hold Kometa up for it", async () => {
    mockApi(routes(() => ({ plex: true, tmdb: true, library: true, done: true })));
    renderAt("/setup");

    expect(await screen.findByText("Kometa is ready to run")).toBeInTheDocument();
    const step = screen.getByText("Protect Studio with a sign-in").closest("details")!;
    expect(within(step).getByText("Optional")).toBeInTheDocument();
    await waitFor(() => expect(step).toHaveAttribute("open"));
  });
});

describe("Overview on a new install", () => {
  it("goes to setup until Kometa has what it needs", async () => {
    mockApi(routes(() => none));
    renderAt("/");
    expect(await screen.findByText(/Kometa needs three things/)).toBeInTheDocument();
  });

  it("stays put once it has, or if Studio can't tell", async () => {
    mockApi({ "GET /config/setup": () => ({ plex: true, tmdb: true, library: true, done: true }) });
    const { unmount } = renderAt("/");
    expect(await screen.findByText("Now")).toBeInTheDocument();
    expect(screen.queryByText(/Kometa needs three things/)).toBeNull();
    unmount();

    mockApi({});
    renderAt("/");
    expect(await screen.findByText("Now")).toBeInTheDocument();
  });
});
