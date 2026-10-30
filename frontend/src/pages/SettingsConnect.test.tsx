import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ArrState } from "../api";
import { mockApi, renderAt } from "../test-utils";

const state: ArrState = {
  settings: { enabled: false, mode: "all", wait_minutes: 10, libraries: { radarr: [], sonarr: [] } },
  path: "/api/v1/hooks/arr?token=abc",
  last_event: null,
  pending: null,
};

const overview = {
  path: "/config/config.yml",
  libraries: [{ name: "Movies" }, { name: "TV Shows" }],
  playlist_files: [],
};

describe("Settings → Connect", () => {
  it("gives the webhook URL to paste and saves what imports run", async () => {
    const calls = mockApi({
      "GET /settings/arr": () => state,
      "GET /config": () => overview,
      "PUT /settings/arr": (body) => ({ ...state, settings: body }),
    });
    renderAt("/settings/connect");

    expect(await screen.findByLabelText("Webhook URL")).toHaveValue(`${window.location.origin}/api/v1/hooks/arr?token=abc`);
    expect(screen.getByText("Nothing received yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Run Kometa after Radarr or Sonarr imports something"));
    fireEvent.change(screen.getByLabelText("Run"), { target: { value: "overlays" } });
    const radarr = (await screen.findByText("Libraries to run for Radarr's imports")).closest("fieldset")!;
    fireEvent.click(radarr.querySelector("input")!); // Movies
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /settings/arr")).toBe(true));
    expect(calls.find((c) => c.route === "PUT /settings/arr")?.body).toEqual({
      enabled: true,
      mode: "overlays",
      wait_minutes: 10,
      libraries: { radarr: ["Movies"], sonarr: [] },
    });
  });

  it("shows imports waiting for things to go quiet", async () => {
    mockApi({
      "GET /settings/arr": () => ({
        ...state,
        last_event: { at: new Date().toISOString(), kind: "sonarr", event: "Download", title: "Avatar: The Last Airbender (2024)" },
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
    expect(screen.getByText(/Last heard from Sonarr .*: Download, Avatar/)).toBeInTheDocument();
  });
});
