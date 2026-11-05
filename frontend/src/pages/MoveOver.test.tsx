import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArrState, ServicesState } from "../api";
import type { ImportReport, SwitchOver } from "../importApi";
import type { RequestsSettingsState } from "../requestsApi";
import { mockApi, renderAt } from "../test-utils";

const off = { enabled: false, trigger: "any" as const, mode: "all" as const, wait_minutes: 10, libraries: [] };
const emptyArr: ArrState = {
  settings: { radarr: off, sonarr: off },
  connections: {
    radarr: { url: null, token: null, root_folder_path: null, quality_profile: null, add_missing: false, search: false, username: null, has_password: false, status: null },
    sonarr: { url: null, token: null, root_folder_path: null, quality_profile: null, add_missing: false, search: false, username: null, has_password: false, status: null },
  },
  pending: {},
  skipped: { radarr: [], sonarr: [] },
  libraries: [],
};

const services: ServicesState = { tmdb: { apikey: "…9f3c" }, mdblist: { apikey: null } };

const requestSettings: RequestsSettingsState = {
  settings: {
    enabled: false,
    via: "auto",
    radarr: { quality_profile: null, root_folder: null, minimum_availability: "released", search: true },
    sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
    daily_cap: null,
    confirm_over: 25,
  },
  seerr: null,
  connected: { radarr: false, sonarr: false, seerr: false },
};

const report = (partial: Partial<ImportReport> = {}): ImportReport => ({
  config: true,
  summary: {
    collections: 3,
    imported: 2,
    ready_made: 1,
    kept: 0,
    kept_with_file: 1,
    already_studio: 0,
    files: { replace: 1, keep: 1, studio: 1 },
  },
  libraries: [
    {
      name: "Movies",
      type: "movie",
      error: null,
      overlay_files: ["overlays/Movies.yml"],
      metadata_files: [],
      files: [
        {
          kind: "file",
          value: "Movies.yml",
          path: "collections/Movies.yml",
          action: "replace",
          reason: "Matched Studio's format",
          ready_made: null,
          collections: [
            {
              name: "Trending",
              result: "imported",
              reason: "Custom collection",
              notes: ["Uses TMDb"],
              definition: null,
              kept_with_file: false,
            },
            {
              name: "Action",
              result: "ready_made",
              reason: "Genre default",
              notes: [],
              definition: null,
              kept_with_file: false,
            },
          ],
        },
        {
          kind: "file",
          value: "kept.yml",
          path: "collections/kept.yml",
          action: "keep",
          reason: "Hand-written",
          ready_made: null,
          collections: [
            {
              name: "Oddballs",
              result: "kept",
              reason: "Kept with its file",
              notes: ["Will still run"],
              definition: null,
              kept_with_file: true,
            },
          ],
        },
        {
          kind: "file",
          value: "built.yml",
          path: "studio/Movies/built.yml",
          action: "studio",
          reason: "Studio generated",
          ready_made: null,
          collections: [
            {
              name: "My Filter",
              result: "studio",
              reason: "Already Studio's",
              notes: [],
              definition: null,
              kept_with_file: false,
            },
          ],
        },
      ],
    },
  ],
  playlist_files: [],
  ...partial,
});

const active: SwitchOver = {
  id: 1,
  created_at: "2026-11-05T12:00:00Z",
  backup: "b-switch",
  imported: 2,
  ready_made: 1,
  kept: 0,
  libraries: ["Movies"],
};

function goToStep(label: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^\\d+\\. ${label}$`) }));
}

function routes(extra: Record<string, (body: unknown) => unknown> = {}, current = report()) {
  return mockApi({
    "GET /import": () => current,
    "GET /import/switch-over": () => ({ active: null }),
    "GET /config/setup": () => ({ plex: true, tmdb: true, library: true, done: true }),
    "GET /settings/services": () => services,
    "GET /settings/arr": () => emptyArr,
    "GET /settings/tautulli": () => ({ url: null, apikey: null }),
    "GET /requests/settings": () => requestSettings,
    ...extra,
  });
}

describe("Move over from Kometa", () => {
  it("renders collection counts, chips, reasons and notes", async () => {
    routes();
    renderAt("/setup/move-over");

    expect(await screen.findByText(/Bring an existing Kometa setup/)).toBeInTheDocument();
    goToStep("Collections");

    const card = (await screen.findByRole("heading", { name: "3. Collections" })).closest("section")!;
    const counts = within(card).getByText(/Importable, kept with its file/).closest("ul")!;
    expect(within(counts).getByText("Imported").closest("li")).toHaveTextContent("2");
    expect(within(counts).getByText("Ready-made").closest("li")).toHaveTextContent("1");
    expect(within(card).getByText(/Importable, kept with its file/)).toHaveTextContent("1");
    expect(within(card).getByText(/Already in Studio/)).toHaveTextContent("0");

    expect(within(card).getByText("collections/Movies.yml")).toBeInTheDocument();
    expect(within(card).getByText("Replaced by Studio")).toBeInTheDocument();
    expect(within(card).getByText("Matched Studio's format")).toBeInTheDocument();
    expect(within(card).getByText("Trending")).toBeInTheDocument();
    expect(within(card).getByText("Custom collection")).toBeInTheDocument();
    expect(within(card).getByText("Uses TMDb")).toBeInTheDocument();
    expect(within(card).getByText("Kept as a Kometa file")).toBeInTheDocument();
    expect(within(card).getByText("Will still run")).toBeInTheDocument();

    const studioFile = within(card).getByText("studio/Movies/built.yml").closest("details")!;
    expect(studioFile).not.toHaveAttribute("open");
  });

  it("needs the checkbox before Switch over, posts confirm, and shows the run link", async () => {
    const calls = routes({
      "POST /import/switch-over": () => ({ switch_over: active, run_id: 42 }),
    });
    renderAt("/setup/move-over");
    await screen.findByText(/Bring an existing Kometa setup/);
    goToStep("Switch over");

    const card = (await screen.findByRole("heading", { name: "6. Switch over" })).closest("section")!;
    expect(within(card).getByText(/2 collections become Studio's/)).toBeInTheDocument();
    const button = within(card).getByRole("button", { name: "Switch over" });
    expect(button).toBeDisabled();

    fireEvent.click(within(card).getByRole("checkbox", { name: /I understand/ }));
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(calls.some((c) => c.route === "POST /import/switch-over")).toBe(true));
    expect(calls.find((c) => c.route === "POST /import/switch-over")!.body).toEqual({ confirm: true });
    expect(await within(card).findByText("Switched over")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open the run" })).toHaveAttribute("href", "/activity/queue/42");
    expect(within(card).getByRole("link", { name: "Collections" })).toHaveAttribute("href", "/collections");
  });

  it("shows a 409's detail", async () => {
    routes({
      "POST /import/switch-over": () => new Response(JSON.stringify({ detail: "A switch-over is already active" }), { status: 409 }),
    });
    renderAt("/setup/move-over");
    await screen.findByText(/Bring an existing Kometa setup/);
    goToStep("Switch over");

    const card = (await screen.findByRole("heading", { name: "6. Switch over" })).closest("section")!;
    fireEvent.click(within(card).getByRole("checkbox", { name: /I understand/ }));
    fireEvent.click(within(card).getByRole("button", { name: "Switch over" }));
    expect(await within(card).findByText("A switch-over is already active")).toBeInTheDocument();
  });

  it("hides the Switch over button when a switch-over is active", async () => {
    routes({ "GET /import/switch-over": () => ({ active }) });
    renderAt("/setup/move-over");
    await screen.findByText(/Bring an existing Kometa setup/);
    goToStep("Switch over");

    const card = (await screen.findByRole("heading", { name: "6. Switch over" })).closest("section")!;
    expect(within(card).getByText(/Switched over on/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Switch over" })).toBeNull();
    expect(within(card).getByRole("link", { name: "System → Backup" })).toHaveAttribute("href", "/system/backup");
  });

  it("hides the Switch over button when there is nothing to import", async () => {
    routes(
      {},
      report({
        summary: {
          collections: 0,
          imported: 0,
          ready_made: 0,
          kept: 0,
          kept_with_file: 0,
          already_studio: 0,
          files: { replace: 0, keep: 0, studio: 0 },
        },
        libraries: [],
      }),
    );
    renderAt("/setup/move-over");
    await screen.findByText(/Bring an existing Kometa setup/);
    goToStep("Switch over");

    const card = (await screen.findByRole("heading", { name: "6. Switch over" })).closest("section")!;
    expect(within(card).getByText(/Nothing to import/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Switch over" })).toBeNull();
  });

  it("says config.yml is missing on the collections step", async () => {
    routes({}, report({ config: false, libraries: [], summary: { collections: 0, imported: 0, ready_made: 0, kept: 0, kept_with_file: 0, already_studio: 0, files: { replace: 0, keep: 0, studio: 0 } } }));
    renderAt("/setup/move-over");
    await screen.findByText(/Bring an existing Kometa setup/);
    goToStep("Collections");
    expect(await screen.findByText(/Kometa's config.yml doesn't exist yet/)).toBeInTheDocument();
  });
});
