import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlexServer, PlexState } from "../api";
import { mockApi, renderAt } from "../test-utils";
import { signInTiming } from "./SettingsPlex";

const REMOTE = "https://203-0-113-7.abc123.plex.direct:32400";
const RELAY = "https://198-51-100-9.abc123.plex.direct:8443";

const signedOut: PlexState = {
  config: { path: "/config/config.yml", url: "http://old:32400", token: "…1234", error: null },
  account: null,
};
const signedIn: PlexState = { ...signedOut, account: { name: "hasan" } };

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
  it("shows the current connection with the token masked", async () => {
    mockApi({ "GET /plex": () => signedOut });
    renderPage();
    expect(await screen.findByText("http://old:32400")).toBeInTheDocument();
    expect(screen.getByText("…1234")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in with Plex" })).toBeInTheDocument();
  });

  it("signs in through a Plex popup, then lists servers with the best address picked", async () => {
    let state = signedOut;
    let polls = 0;
    const popup = { location: { href: "" }, closed: false, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    mockApi({
      "GET /plex": () => state,
      "POST /plex/pin": () => ({ id: 42, auth_url: "https://app.plex.tv/auth/#!?code=abcd" }),
      "GET /plex/pin/42": () => {
        polls += 1;
        if (polls < 2) return { status: "waiting" };
        state = signedIn;
        return { status: "signed_in", account: { name: "hasan" } };
      },
      "GET /plex/servers": () => ({ servers: [seedbox] }),
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Plex" }));
    expect(await screen.findByText(/Signed in to Plex as hasan/)).toBeInTheDocument();
    expect(popup.location.href).toBe("https://app.plex.tv/auth/#!?code=abcd");
    expect(popup.close).toHaveBeenCalled();

    const remote = await screen.findByRole("radio", { name: new RegExp(REMOTE) });
    expect(remote).toBeChecked();
    // Failed addresses are tucked away until asked for.
    expect(screen.queryByText("http://172.17.0.2:32400")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 1 address that failed" }));
    expect(screen.getByRole("radio", { name: /172\.17\.0\.2/ })).toBeDisabled();
  });

  it("warns about relays and saves the chosen address", async () => {
    const calls = mockApi({
      "GET /plex": () => signedIn,
      "GET /plex/servers": () => ({ servers: [seedbox] }),
      "POST /plex/connect": () => ({ ...signedIn, config: { ...signedIn.config, url: RELAY } }),
    });
    renderPage();

    fireEvent.click(await screen.findByRole("radio", { name: new RegExp(RELAY) }));
    expect(screen.getByText(/This is a Plex relay/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use this address" }));

    expect(await screen.findByText("Saved to config.yml")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /plex/connect")?.body).toEqual({ server_id: "srv1", uri: RELAY });
  });

  it("explains when the sign-in window is closed early", async () => {
    vi.spyOn(window, "open").mockReturnValue({ location: { href: "" }, closed: true, close: vi.fn() } as unknown as Window);
    mockApi({
      "GET /plex": () => signedOut,
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
      "POST /plex/pin": () => ({ id: 42, auth_url: "https://app.plex.tv/auth/#!?code=abcd" }),
      "GET /plex/pin/42": () => ({ status: "waiting" }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Plex" }));
    const link = await screen.findByRole("link", { name: "Open the Plex sign-in page" });
    expect(link).toHaveAttribute("href", "https://app.plex.tv/auth/#!?code=abcd");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("tests and saves a typed address", async () => {
    const calls = mockApi({
      "GET /plex": () => signedOut,
      "POST /plex/test": (body) =>
        (body as { token: string }).token === "good"
          ? { ok: true, name: "Seedbox", version: "1.41.2.9200", url: "https://plex.example.com" }
          : { ok: false, error: "The server rejected the token" },
      "POST /plex/connect": () => signedOut,
    });
    renderPage();

    const form = (await screen.findByRole("heading", { name: "Enter an address" })).closest("section")!;
    fireEvent.change(within(form).getByLabelText("Server URL"), { target: { value: "https://plex.example.com" } });
    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "bad" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("rejected the token");

    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "good" } });
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Connected to Seedbox (Plex 1.41.2.9200)")).toBeInTheDocument();

    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByText("Saved to config.yml")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /plex/connect")?.body).toEqual({ url: "https://plex.example.com", token: "good" });
  });

  it("shows the server's reason when saving fails", async () => {
    mockApi({
      "GET /plex": () => signedOut,
      "POST /plex/connect": () =>
        new Response(JSON.stringify({ detail: "Studio couldn't connect with that address: No answer within 5 s" }), { status: 422 }),
    });
    renderPage();
    const form = (await screen.findByRole("heading", { name: "Enter an address" })).closest("section")!;
    fireEvent.change(within(form).getByLabelText("Server URL"), { target: { value: "https://plex.example.com" } });
    fireEvent.change(within(form).getByLabelText("Plex token"), { target: { value: "t" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("No answer within 5 s");
  });
});
