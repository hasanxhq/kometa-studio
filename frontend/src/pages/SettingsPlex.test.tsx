import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlexConnectionCheck, PlexServer, PlexState } from "../api";
import { mockApi, renderAt } from "../test-utils";
import { signInTiming } from "./SettingsPlex";

const REMOTE = "https://203-0-113-7.abc123.plex.direct:32400";
const RELAY = "https://198-51-100-9.abc123.plex.direct:8443";

const signedOut: PlexState = {
  config: { path: "/config/config.yml", url: "http://old:32400", token: "…1234", error: null, custom: false },
  account: null,
};
const signedIn: PlexState = { ...signedOut, account: { name: "hasan" } };
const nothingSaved: PlexState = { config: { ...signedOut.config, url: null, token: null }, account: null };

const answers: PlexConnectionCheck = { status: "ok", name: "Seedbox", version: "1.41.2.9200", latency_ms: 45, error: null };
const noAnswer: PlexConnectionCheck = { status: "error", name: null, version: null, latency_ms: null, error: "No answer within 5 s" };

const seedbox: PlexServer = {
  id: "srv1",
  name: "Seedbox",
  version: "1.41.2.9200",
  best: REMOTE,
  connections: [
    { uri: REMOTE, local: false, relay: false, secure: true, ok: true, error: null, latency_ms: 120 },
    { uri: RELAY, local: false, relay: true, secure: true, ok: true, error: null, latency_ms: 300 },
    { uri: "http://172.17.0.2:32400", local: true, relay: false, secure: false, ok: false, error: "Can't connect: refused", latency_ms: null },
  ],
};

function renderPage() {
  return renderAt("/settings/plex");
}

beforeEach(() => {
  signInTiming.pollMs = 1;
});

describe("Settings → Plex", () => {
  it("shows the saved server and its status, without fetching the account's servers", async () => {
    const calls = mockApi({ "GET /plex": () => signedIn, "GET /plex/connection": () => answers });
    renderPage();
    expect(await screen.findByText("Connected · 45 ms")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Seedbox" })).toBeInTheDocument();
    expect(screen.getByText("http://old:32400")).toBeInTheDocument();
    expect(screen.getByText("…1234")).toBeInTheDocument();
    expect(screen.getByText(/Signed in to Plex as hasan/)).toBeInTheDocument();
    expect(calls.some((c) => c.route === "GET /plex/servers")).toBe(false);
    // The custom address form waits until asked for.
    expect(screen.queryByLabelText("Server URL")).toBeNull();
  });

  it("tests again on request: the saved server, then every server on the account", async () => {
    let checks = 0;
    const calls = mockApi({
      "GET /plex": () => signedIn,
      "GET /plex/connection": () => (checks++, answers),
      "GET /plex/servers": () => ({ servers: [seedbox] }),
    });
    renderPage();
    await screen.findByText("Connected · 45 ms");
    fireEvent.click(screen.getByRole("button", { name: "Test again" }));

    const remote = await screen.findByRole("radio", { name: new RegExp(REMOTE) });
    expect(remote).toBeChecked();
    expect(checks).toBe(2);
    // Failed addresses are tucked away until asked for.
    expect(screen.queryByText("http://172.17.0.2:32400")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 1 address that failed" }));
    expect(screen.getByRole("radio", { name: /172\.17\.0\.2/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByRole("radio")).toBeNull();
    expect(calls.filter((c) => c.route === "GET /plex/servers")).toHaveLength(1);
  });

  it("lists the account's servers straight away when the saved one doesn't answer, and saves the chosen address", async () => {
    let state = signedIn;
    const calls = mockApi({
      "GET /plex": () => state,
      "GET /plex/connection": () => (state === signedIn ? noAnswer : answers),
      "GET /plex/servers": () => ({ servers: [seedbox] }),
      "POST /plex/connect": () => {
        state = { ...signedIn, config: { ...signedIn.config, url: RELAY } };
        return state;
      },
    });
    renderPage();

    expect(await screen.findByText("No answer within 5 s")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose another address" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: new RegExp(RELAY) }));
    expect(screen.getByText(/This is a Plex relay/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use this address" }));

    expect(await screen.findByText("Saved to config.yml")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /plex/connect")?.body).toEqual({ server_id: "srv1", uri: RELAY });
    expect(await screen.findByText("Connected · 45 ms")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("signs in through a Plex popup, then lists servers with the best address picked", async () => {
    let state = nothingSaved;
    let polls = 0;
    const popup = { location: { href: "" }, closed: false, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    mockApi({
      "GET /plex": () => state,
      "POST /plex/pin": () => ({ id: 42, auth_url: "https://app.plex.tv/auth/#!?code=abcd" }),
      "GET /plex/pin/42": () => {
        polls += 1;
        if (polls < 2) return { status: "waiting" };
        state = { ...nothingSaved, account: { name: "hasan" } };
        return { status: "signed_in", account: { name: "hasan" } };
      },
      "GET /plex/servers": () => ({ servers: [seedbox] }),
    });
    renderPage();

    expect(await screen.findByText("No Plex server is saved in config.yml yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign in with Plex" }));
    expect(await screen.findByText(/Signed in to Plex as hasan/)).toBeInTheDocument();
    expect(popup.location.href).toBe("https://app.plex.tv/auth/#!?code=abcd");
    expect(popup.close).toHaveBeenCalled();
    expect(await screen.findByRole("radio", { name: new RegExp(REMOTE) })).toBeChecked();
  });

  it("explains when the sign-in window is closed early", async () => {
    vi.spyOn(window, "open").mockReturnValue({ location: { href: "" }, closed: true, close: vi.fn() } as unknown as Window);
    mockApi({
      "GET /plex": () => signedOut,
      "GET /plex/connection": () => answers,
      "POST /plex/pin": () => ({ id: 42, auth_url: "https://app.plex.tv/auth/#!?code=abcd" }),
      "GET /plex/pin/42": () => ({ status: "waiting" }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Plex" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("closed before sign-in finished");
  });

  it("offers a link when the browser blocks the popup", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    mockApi({
      "GET /plex": () => signedOut,
      "GET /plex/connection": () => answers,
      "POST /plex/pin": () => ({ id: 42, auth_url: "https://app.plex.tv/auth/#!?code=abcd" }),
      "GET /plex/pin/42": () => ({ status: "waiting" }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Plex" }));
    const link = await screen.findByRole("link", { name: "Open the Plex sign-in page" });
    expect(link).toHaveAttribute("href", "https://app.plex.tv/auth/#!?code=abcd");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("uses a custom address only after it passes a test", async () => {
    let state = signedOut;
    const calls = mockApi({
      "GET /plex": () => state,
      "GET /plex/connection": () => answers,
      "POST /plex/test": (body) =>
        (body as { token: string }).token === "good"
          ? { ok: true, name: "Seedbox", version: "1.41.2.9200", url: "https://plex.example.com" }
          : { ok: false, error: "The server rejected the token" },
      "POST /plex/connect": () => {
        state = { ...signedOut, config: { ...signedOut.config, url: "https://plex.example.com", custom: true } };
        return state;
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Use a custom address" }));
    const form = screen.getByRole("form", { name: "Custom address" });
    fireEvent.change(within(form).getByLabelText("Server URL"), { target: { value: "https://plex.example.com" } });
    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "bad" } });
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("rejected the token");
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();

    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "good" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Connected to Seedbox (Plex 1.41.2.9200)")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved to config.yml")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /plex/connect")?.body).toEqual({ url: "https://plex.example.com", token: "good" });
    expect(screen.queryByRole("form", { name: "Custom address" })).toBeNull();
    expect(await screen.findByText("Custom address")).toBeInTheDocument(); // the saved server's tag
  });

  it("shows the server's reason when saving a custom address fails", async () => {
    mockApi({
      "GET /plex": () => signedOut,
      "GET /plex/connection": () => answers,
      "POST /plex/test": () => ({ ok: true, name: "Seedbox", version: "1.41.2.9200", url: "https://plex.example.com" }),
      "POST /plex/connect": () => new Response(JSON.stringify({ detail: "Can't update config.yml: it isn't a mapping" }), { status: 409 }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Use a custom address" }));
    const form = screen.getByRole("form", { name: "Custom address" });
    fireEvent.change(within(form).getByLabelText("Server URL"), { target: { value: "https://plex.example.com" } });
    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "t" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    await within(form).findByText("Connected to Seedbox (Plex 1.41.2.9200)");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("it isn't a mapping");
    fireEvent.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form", { name: "Custom address" })).toBeNull();
  });
});
