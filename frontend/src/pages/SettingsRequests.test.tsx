import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RequestSettings, RequestsSettingsState } from "../requestsApi";
import { mockApi, renderAt } from "../test-utils";

const defaults: RequestSettings = {
  enabled: false,
  via: "auto",
  radarr: { quality_profile: null, root_folder: null, minimum_availability: "released", search: true },
  sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
  daily_cap: null,
  confirm_over: 25,
};

const state = (partial: Partial<RequestsSettingsState> = {}): RequestsSettingsState => ({
  settings: defaults,
  seerr: null,
  connected: { radarr: true, sonarr: true, seerr: false },
  ...partial,
});

function routes(extra: Record<string, (body: unknown) => unknown> = {}, current = state()) {
  return mockApi({
    "GET /requests/settings": () => current,
    "GET /requests/options": () => ({
      radarr: { quality_profiles: ["HD-1080p"], root_folders: ["/movies"] },
      sonarr: { quality_profiles: ["Any"], root_folders: ["/tv"] },
      errors: {},
    }),
    ...extra,
  });
}

describe("Settings → Requests", () => {
  it("is under Settings in the sidebar after Connect", async () => {
    routes();
    renderAt("/settings/requests");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link").map((link) => link.getAttribute("href"));
    const connect = links.indexOf("/settings/connect");
    const requests = links.indexOf("/settings/requests");
    expect(connect).toBeGreaterThanOrEqual(0);
    expect(requests).toBe(connect + 1);
  });

  it("asks before turning requests on, then saves settings", async () => {
    const calls = routes({
      "PUT /requests/settings": (body) => state({ settings: body as RequestSettings }),
    });
    renderAt("/settings/requests");

    const form = await screen.findByRole("form", { name: "Requests settings" });
    fireEvent.click(within(form).getByRole("checkbox", { name: /Requests/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Nothing is requested until you tick Download missing/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn on requests" }));
    expect(within(form).getByRole("checkbox", { name: /Requests/ })).toBeChecked();

    fireEvent.change(within(form).getByLabelText("Ask before requesting more than"), { target: { value: "10" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "PUT /requests/settings")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /requests/settings")!.body).toMatchObject({ enabled: true, confirm_over: 10 });
  });

  it("disables Overseerr when it isn't connected, and manages Seerr with a masked key", async () => {
    const connected = state({
      seerr: { kind: "overseerr", url: "http://overseerr:5055", api_key: "…ab12", username: null, has_password: false },
      connected: { radarr: true, sonarr: false, seerr: true },
    });
    const calls = routes(
      {
        "POST /requests/seerr/test": () => ({ ok: true }),
        "PUT /requests/seerr": () => connected,
        "DELETE /requests/seerr": () => state(),
      },
      connected,
    );
    renderAt("/settings/requests");

    const settings = await screen.findByRole("form", { name: "Requests settings" });
    expect(within(settings).getByRole("radio", { name: /Overseerr or Jellyseerr/ })).toBeEnabled();
    expect(screen.getByText(/Sonarr isn't connected/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings → Connect" })).toHaveAttribute("href", "/settings/connect");

    const seerr = screen.getByRole("form", { name: "Overseerr / Jellyseerr connection" });
    expect(within(seerr).getByLabelText("API key")).toHaveAttribute("placeholder", "Saved (…ab12), leave empty to keep it");
    fireEvent.click(within(seerr).getByRole("button", { name: "Test" }));
    expect(await within(seerr).findByText("Connected.")).toBeInTheDocument();
    fireEvent.click(within(seerr).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "PUT /requests/seerr")).toBe(true));
  });
});
