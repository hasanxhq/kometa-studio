import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArrState, MaintainerrState, ServicesState } from "../api";
import { mockApi, renderAt } from "../test-utils";

const off = { enabled: false, trigger: "any" as const, mode: "all" as const, wait_minutes: 10, libraries: [] };

const state: ArrState = {
  settings: { radarr: off, sonarr: off },
  connections: {
    radarr: { url: "http://radarr:7878", token: "…ab12", root_folder_path: "/movies", quality_profile: null, username: null, has_password: false, status: null },
    sonarr: { url: null, token: null, root_folder_path: null, quality_profile: null, username: null, has_password: false, status: null },
  },
  pending: {},
  skipped: { radarr: [], sonarr: [] },
  libraries: [],
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
  schedule: { taken_over: false, own_cron: null, last_redraw: null, next_redraw: null },
};

const keys: ServicesState = { tmdb: { apikey: "…9f3c", bypass_dns: false }, mdblist: { apikey: null } };

function routes(extra: Record<string, (body: unknown) => unknown> = {}) {
  return mockApi({
    "GET /settings/arr": () => state,
    "GET /config": () => overview,
    "GET /settings/maintainerr": () => notConnected,
    "GET /settings/services": () => keys,
    ...extra,
  });
}

describe("Radarr and Sonarr", () => {
  it("fills in Kometa's Radarr from config.yml, and saves only after a passing test", async () => {
    const calls = routes({
      "POST /settings/arr/radarr/test": () => ({ ok: true, app: "Radarr", version: "5.14", root_folders: ["/movies", "/films"], quality_profiles: ["HD-1080p"] }),
      "PUT /settings/arr/radarr": () => state,
    });
    renderAt("/settings/connect");

    const form = await screen.findByRole("form", { name: "Radarr connection" });
    expect(within(form).getByLabelText("URL")).toHaveValue("http://radarr:7878");
    expect(within(form).getByLabelText("API key")).toHaveAttribute("placeholder", "Saved (…ab12), leave empty to keep it");
    expect(within(form).getByLabelText(/Root folder/)).toHaveValue("/movies");
    expect(within(form).getByLabelText(/Root folder/)).toBeDisabled();
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();

    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Radarr 5.14 answered.")).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText(/Root folder/), { target: { value: "/films" } });
    fireEvent.change(within(form).getByLabelText(/Quality profile/), { target: { value: "HD-1080p" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /settings/arr/radarr")?.body).toEqual({
        url: "http://radarr:7878",
        api_key: null,
        username: null,
        password: null,
        root_folder_path: "/films",
        quality_profile: "HD-1080p",
      }),
    );
  });

  it("asks for a new test after the address changes, and shows the proxy login only when ticked", async () => {
    routes({ "POST /settings/arr/sonarr/test": () => ({ ok: true, app: "Sonarr", version: "4.0", root_folders: ["/tv"], quality_profiles: [] }) });
    renderAt("/settings/connect");

    const form = await screen.findByRole("form", { name: "Sonarr connection" });
    expect(within(form).queryByLabelText("Username")).toBeNull();
    fireEvent.click(within(form).getByLabelText(/Sonarr is behind a proxy/));
    expect(within(form).getByLabelText("Username")).toBeInTheDocument();

    fireEvent.change(within(form).getByLabelText("URL"), { target: { value: "http://sonarr:8989" } });
    fireEvent.change(within(form).getByLabelText("API key"), { target: { value: "key" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    await within(form).findByText("Sonarr 4.0 answered.");
    expect(within(form).getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.change(within(form).getByLabelText("URL"), { target: { value: "http://sonarr:9999" } });
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("has separate import settings for each app", async () => {
    const calls = routes({ "PUT /settings/arr/sonarr/runs": () => state });
    renderAt("/settings/connect");

    const radarr = await screen.findByRole("form", { name: "Radarr imports" });
    const sonarr = screen.getByRole("form", { name: "Sonarr imports" });
    fireEvent.click(within(sonarr).getByLabelText(/Run Kometa when Sonarr imports something/));
    expect(within(radarr).queryByLabelText("Run")).toBeNull(); // Radarr's stay as they were
    fireEvent.change(within(sonarr).getByLabelText("Run"), { target: { value: "overlays" } });
    fireEvent.click(within(sonarr).getByLabelText("TV Shows"));
    fireEvent.click(within(sonarr).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /settings/arr/sonarr/runs")?.body).toEqual({ enabled: true, trigger: "any", mode: "overlays", wait_minutes: 10, libraries: ["TV Shows"] }),
    );
  });

  it("shows imports waiting and a failing check", async () => {
    const waiting: ArrState = {
      ...state,
      settings: { ...state.settings, radarr: { ...off, enabled: true } },
      connections: {
        ...state.connections,
        radarr: { ...state.connections.radarr, status: { checked_at: new Date().toISOString(), ok: false, error: "The API key was rejected" } },
      },
      pending: { radarr: { first_at: "2026-10-30T20:00:00Z", last_at: "2026-10-30T20:01:00Z", due_at: new Date(Date.now() + 600_000).toISOString(), imports: 2, titles: ["Flow (2024)"] } },
    };
    routes({ "GET /settings/arr": () => waiting });
    renderAt("/settings/connect");
    expect(await screen.findByText(/2 imports waiting \(Flow \(2024\)\)/)).toBeInTheDocument();
    expect(screen.getByText(/Last check failed .*: The API key was rejected/)).toBeInTheDocument();
  });
});

describe("Maintainerr", () => {
  it("tests, then connects, with its overlays on top by default", async () => {
    const connected: MaintainerrState = {
      ...notConnected,
      url: "http://maintainerr:6246",
      username: "hasan",
      has_password: true,
      collections: [{ title: "Leaving Soon", library: "Movies", overlays: true }],
      overlays_enabled: true,
      risks: ["Movies: delete_collections would delete Maintainerr's collections (“Leaving Soon”): Kometa sees them as unmanaged. Limit it with managed: true."],
      schedule: { taken_over: true, own_cron: "0 * * * *", last_redraw: new Date().toISOString(), next_redraw: new Date(Date.now() + 86_400_000).toISOString() },
    };
    const calls = routes({
      "POST /settings/maintainerr/test": () => ({ ok: true, collections: 1, overlays_enabled: true }),
      "PUT /settings/maintainerr": () => connected,
    });
    renderAt("/settings/connect");

    const form = await screen.findByRole("form", { name: "Maintainerr connection" });
    fireEvent.change(within(form).getByLabelText("URL"), { target: { value: "http://maintainerr:6246" } });
    fireEvent.click(within(form).getByLabelText(/Maintainerr is behind a proxy/));
    fireEvent.change(within(form).getByLabelText("Username"), { target: { value: "hasan" } });
    fireEvent.change(within(form).getByLabelText("Password"), { target: { value: "seedbox-pass" } });
    expect(within(form).getByLabelText(/Leave Maintainerr overlays alone/)).toBeChecked();
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Maintainerr answered: 1 collection, overlays on.")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByText("Kometa's config would touch Maintainerr's collections")).toBeInTheDocument();
    expect(within(form).getByText("Protecting 1 collection:")).toBeInTheDocument();
    expect(within(form).getByText(/Studio holds Maintainerr's overlay schedule \(its own: 0 \* \* \* \*\)/)).toBeInTheDocument();
    expect(calls.find((c) => c.route === "PUT /settings/maintainerr")?.body).toEqual({
      url: "http://maintainerr:6246",
      username: "hasan",
      password: "seedbox-pass",
      leave_overlays_alone: true,
    });
  });

  it("saves the overlay choice alone without a test", async () => {
    const connected: MaintainerrState = { ...notConnected, url: "http://maintainerr:6246" };
    const calls = routes({ "GET /settings/maintainerr": () => connected, "PUT /settings/maintainerr": () => ({ ...connected, leave_overlays_alone: false }) });
    renderAt("/settings/connect");
    const form = await screen.findByRole("form", { name: "Maintainerr connection" });
    fireEvent.click(within(form).getByLabelText(/Leave Maintainerr overlays alone/));
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/maintainerr")?.body).toMatchObject({ leave_overlays_alone: false }));
  });
});

describe("TMDb and MDBList", () => {
  it("tests a key before saving it, and MDBList says how much of today's allowance is used", async () => {
    let saved = keys;
    const calls = routes({
      "GET /settings/services": () => saved,
      "POST /settings/services/mdblist/test": () => ({ ok: true, limit: 1000, used: 312 }),
      "PUT /settings/services/mdblist": () => {
        saved = { ...keys, mdblist: { apikey: "…k3y9" } };
        return saved;
      },
    });
    renderAt("/settings/connect");

    const tmdb = await screen.findByRole("form", { name: "TMDb" });
    expect(within(tmdb).getByLabelText("TMDb API key")).toHaveAttribute("placeholder", "Saved (…9f3c), leave empty to keep it");
    expect(within(tmdb).queryByRole("button", { name: "Remove" })).toBeNull(); // Kometa needs it

    const mdb = screen.getByRole("form", { name: "MDBList" });
    fireEvent.change(within(mdb).getByLabelText("MDBList API key"), { target: { value: "new-k3y9" } });
    expect(within(mdb).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(mdb).getByRole("button", { name: "Test" }));
    expect(await within(mdb).findByText("MDBList accepted the key: 312 of 1000 requests used today.")).toBeInTheDocument();
    fireEvent.click(within(mdb).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/services/mdblist")?.body).toEqual({ apikey: "new-k3y9", bypass_dns: false }));
    await waitFor(() => expect(screen.getByLabelText("MDBList API key")).toHaveAttribute("placeholder", "Saved (…k3y9), leave empty to keep it"));
  });
});

describe("Only imports that matter", () => {
  it("says per library what Studio can tell, offers to turn on Kometa's report, and lists skipped imports", async () => {
    const relevance = (library: string, extra: object) => ({
      library,
      reports: true,
      reported_at: "2026-10-30T18:00:00Z",
      changed: false,
      wanted: 12,
      ids: 2,
      lists: 4,
      rule: [],
      unreadable: [],
      overlays: false,
      ...extra,
    });
    const known: ArrState = {
      ...state,
      settings: { ...state.settings, radarr: { ...off, enabled: true, mode: "collections" } },
      skipped: { radarr: [{ at: new Date().toISOString(), title: "Paddington 2 (2017)", libraries: "Movies" }], sonarr: [] },
      libraries: [relevance("Movies", {}), relevance("Kids", { reports: false, reported_at: null }), relevance("4K", { rule: ["Recently Added"] })],
    };
    const calls = routes({ "GET /settings/arr": () => known, "POST /settings/arr/reports": () => known, "PUT /settings/arr/radarr/runs": () => known });
    renderAt("/settings/connect");

    const form = await screen.findByRole("form", { name: "Radarr imports" });
    expect(within(form).getByText(/Skipped lately: Paddington 2 \(2017\)/)).toBeInTheDocument();
    fireEvent.click(within(form).getByLabelText(/Only imports that matter to Kometa/));
    expect(within(form).getByText(/only imports its collections want: 14 known/)).toBeInTheDocument();
    expect(within(form).getByText("every import counts until Kometa's missing report is on")).toBeInTheDocument();
    expect(within(form).getByText("every import counts: “Recently Added” search Plex")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Turn on Kometa's missing report" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /settings/arr/reports")).toBe(true));
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/arr/radarr/runs")?.body).toMatchObject({ trigger: "relevant" }));
  });
});

describe("TMDb's DNS bypass", () => {
  it("is tested and saved with the key, and can be switched for the saved key alone", async () => {
    let saved = keys;
    const calls = routes({
      "GET /settings/services": () => saved,
      "POST /settings/services/tmdb/test": (body) => ((body as { bypass_dns: boolean }).bypass_dns ? { ok: true } : { ok: false, error: "Can't reach TMDb: Name or service not known" }),
      "PUT /settings/services/tmdb": () => {
        saved = { ...keys, tmdb: { apikey: "…9f3c", bypass_dns: true } };
        return saved;
      },
    });
    renderAt("/settings/connect");

    const tmdb = await screen.findByRole("form", { name: "TMDb" });
    const box = within(tmdb).getByLabelText("DNS bypass");
    expect(box).not.toBeChecked();
    fireEvent.click(within(tmdb).getByRole("button", { name: "Test" }));
    expect(await within(tmdb).findByText(/Name or service not known/)).toBeInTheDocument();

    fireEvent.click(box);
    expect(within(tmdb).getByText(/Cloudflare's DNS over HTTPS \(1\.1\.1\.1\)/)).toBeInTheDocument();
    expect(within(tmdb).getByRole("button", { name: "Save" })).toBeDisabled(); // not tested this way yet
    fireEvent.click(within(tmdb).getByRole("button", { name: "Test" }));
    expect(await within(tmdb).findByText("TMDb accepted the key (looked up over DNS over HTTPS).")).toBeInTheDocument();
    fireEvent.click(within(tmdb).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/services/tmdb")?.body).toEqual({ apikey: null, bypass_dns: true }));
    await waitFor(() => expect(screen.getByLabelText("DNS bypass")).toBeChecked());
  });
});
