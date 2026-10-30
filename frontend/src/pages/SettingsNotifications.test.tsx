import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NotificationsState } from "../api";
import { mockApi, renderAt } from "../test-utils";

const DISCORD = "url:0123456789abcdef";

const validation = { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" };

const state: NotificationsState = {
  path: "/config/config.yml",
  hash: "h1",
  error: null,
  services: [
    { name: "notifiarr", label: "Notifiarr", configured: false, keys: [{ name: "apikey", label: "API key", secret: true, value: null, masked: null }] },
    {
      name: "gotify",
      label: "Gotify",
      configured: true,
      keys: [
        { name: "url", label: "Server URL", secret: false, value: "http://gotify.lan", masked: null },
        { name: "token", label: "Application token", secret: true, value: null, masked: "…oken" },
      ],
    },
    {
      name: "ntfy",
      label: "ntfy",
      configured: false,
      keys: [
        { name: "url", label: "Server URL", secret: false, value: null, masked: null },
        { name: "token", label: "Access token", secret: true, value: null, masked: null },
        { name: "topic", label: "Topic", secret: false, value: null, masked: null },
      ],
    },
    { name: "apprise", label: "Apprise", configured: false, keys: [{ name: "config", label: "Apprise configuration", secret: false, value: null, masked: null }] },
  ],
  webhooks: {
    targets: [
      { id: "gotify", label: "Gotify", kind: "service", configured: true },
      { id: DISCORD, label: "https://discord.com/api/webhooks/••••", kind: "url", configured: true },
      { id: "studio", label: "Kometa Studio", kind: "studio", configured: true },
    ],
    events: { error: ["gotify"], version: [], run_start: ["studio"], run_end: [DISCORD, "gotify", "studio"], changes: ["studio"], delete: [] },
  },
};

function form(name: string) {
  return within(screen.getByRole("form", { name }));
}

describe("Settings → Notifications", () => {
  it("is under Settings in the sidebar", async () => {
    mockApi({ "GET /settings/notifications": () => state });
    renderAt("/settings/notifications");
    expect(await screen.findByRole("link", { name: "Notifications" })).toHaveAttribute("href", "/settings/notifications");
  });

  it("fills each service in from config.yml, with secrets only as a masked placeholder", async () => {
    mockApi({ "GET /settings/notifications": () => state });
    renderAt("/settings/notifications");
    const gotify = within(await screen.findByRole("form", { name: "Gotify" }));
    expect(gotify.getByLabelText("Server URL")).toHaveValue("http://gotify.lan");
    const token = gotify.getByLabelText("Application token");
    expect(token).toHaveValue("");
    expect(token).toHaveAttribute("placeholder", "Saved: …oken (leave empty to keep it)");
    expect(gotify.getByRole("button", { name: "Remove…" })).toBeInTheDocument();
    expect(form("ntfy").getByLabelText("Topic")).toHaveValue("");
    expect(form("ntfy").queryByRole("button", { name: "Remove…" })).toBeNull();
    expect(screen.getByText("Set up in config.yml")).toBeInTheDocument();
  });

  it("keeps Save off until Test passes for the values as they are", async () => {
    const calls = mockApi({
      "GET /settings/notifications": () => state,
      "POST /settings/notifications/gotify/test": (body) =>
        (body as { values: { token: string | null } }).values.token === "bad"
          ? { ok: false, error: "Gotify refused the application token" }
          : { ok: true, message: "Gotify 2.6.1 accepted a test message." },
      "PUT /settings/notifications/gotify": () => ({ ...state, saved: { backup: "b1", files: [], validation } }),
    });
    renderAt("/settings/notifications");
    const gotify = within(await screen.findByRole("form", { name: "Gotify" }));
    const save = gotify.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    fireEvent.change(gotify.getByLabelText("Application token"), { target: { value: "bad" } });
    fireEvent.click(gotify.getByRole("button", { name: "Test" }));
    expect(await gotify.findByText("Gotify refused the application token")).toBeInTheDocument();
    expect(save).toBeDisabled();

    // The saved token is the one tested when the field is left empty.
    fireEvent.change(gotify.getByLabelText("Application token"), { target: { value: "" } });
    fireEvent.click(gotify.getByRole("button", { name: "Test" }));
    expect(await gotify.findByText("Gotify 2.6.1 accepted a test message.")).toBeInTheDocument();
    expect(save).toBeEnabled();

    // Any edit clears the pass.
    fireEvent.change(gotify.getByLabelText("Server URL"), { target: { value: "http://gotify.lan:8080" } });
    expect(save).toBeDisabled();
    expect(gotify.queryByText("Gotify 2.6.1 accepted a test message.")).toBeNull();
    fireEvent.click(gotify.getByRole("button", { name: "Test" }));
    await gotify.findByText("Gotify 2.6.1 accepted a test message.");

    fireEvent.click(save);
    expect(await gotify.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "PUT /settings/notifications/gotify")?.body).toEqual({
      values: { url: "http://gotify.lan:8080", token: null },
      base_hash: "h1",
    });
    expect(calls.filter((c) => c.route === "POST /settings/notifications/gotify/test")).toHaveLength(3);
  });

  it("shows why the server refused a save", async () => {
    mockApi({
      "GET /settings/notifications": () => state,
      "POST /settings/notifications/notifiarr/test": () => ({ ok: true, message: "Notifiarr accepted the API key." }),
      "PUT /settings/notifications/notifiarr": () =>
        new Response(JSON.stringify({ detail: { message: "The test failed, so nothing was saved: Notifiarr refused the API key", path: null, validation: null } }), {
          status: 422,
        }),
    });
    renderAt("/settings/notifications");
    const notifiarr = within(await screen.findByRole("form", { name: "Notifiarr" }));
    expect(notifiarr.getByRole("button", { name: "Test" })).toBeDisabled(); // nothing entered and nothing saved
    fireEvent.change(notifiarr.getByLabelText("API key"), { target: { value: "key" } });
    fireEvent.click(notifiarr.getByRole("button", { name: "Test" }));
    await notifiarr.findByText("Notifiarr accepted the API key.");
    fireEvent.click(notifiarr.getByRole("button", { name: "Save" }));
    expect(await notifiarr.findByText("The test failed, so nothing was saved: Notifiarr refused the API key")).toBeInTheDocument();
  });

  it("removes a service after asking", async () => {
    const removed: NotificationsState = {
      ...state,
      hash: "h2",
      services: state.services.map((s) => (s.name === "gotify" ? { ...s, configured: false, keys: s.keys.map((k) => ({ ...k, value: null, masked: null })) } : s)),
      saved: { backup: "b2", files: [], validation },
    };
    const calls = mockApi({ "GET /settings/notifications": () => state, "DELETE /settings/notifications/gotify?base_hash=h1": () => removed });
    renderAt("/settings/notifications");
    const gotify = within(await screen.findByRole("form", { name: "Gotify" }));
    fireEvent.click(gotify.getByRole("button", { name: "Remove…" }));
    fireEvent.click(gotify.getByRole("button", { name: "Remove Gotify" }));
    expect(await gotify.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect(calls.some((c) => c.route === "DELETE /settings/notifications/gotify?base_hash=h1")).toBe(true);
    expect(gotify.getByLabelText("Server URL")).toHaveValue("");
    expect(gotify.queryByRole("button", { name: "Remove…" })).toBeNull();
  });

  it("shows webhook events as a grid, with Studio's own entries locked and left out of a save", async () => {
    const calls = mockApi({
      "GET /settings/notifications": () => state,
      "PUT /settings/notifications/webhooks": (body) => ({
        ...state,
        webhooks: { ...state.webhooks, events: (body as { events: NotificationsState["webhooks"]["events"] }).events },
        saved: { backup: "b3", files: [], validation },
      }),
    });
    renderAt("/settings/notifications");
    const studio = await screen.findByRole("checkbox", { name: "run_end → Kometa Studio (managed by Kometa Studio)" });
    expect(studio).toBeChecked();
    expect(studio).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "error → Kometa Studio (managed by Kometa Studio)" })).toBeDisabled();
    expect(screen.getByText("Locked: managed by Kometa Studio")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "run_end → https://discord.com/api/webhooks/••••" })).toBeChecked();

    const grid = form("Webhook events");
    expect(grid.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "run_end → https://discord.com/api/webhooks/••••" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "version → Gotify" }));
    fireEvent.change(screen.getByLabelText("Add a webhook URL"), { target: { value: "https://example.com/kometa" } });
    fireEvent.click(screen.getByRole("button", { name: "Add URL" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "error → https://example.com/kometa" }));
    fireEvent.click(grid.getByRole("button", { name: "Save" }));

    // The grid starts again from what was saved, and says so.
    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect(form("Webhook events").getByRole("checkbox", { name: "version → Gotify" })).toBeChecked();
    expect(form("Webhook events").getByRole("button", { name: "Save" })).toBeDisabled();
    expect(calls.find((c) => c.route === "PUT /settings/notifications/webhooks")?.body).toEqual({
      base_hash: "h1",
      events: {
        error: ["gotify", "https://example.com/kometa"],
        version: ["gotify"],
        run_start: [],
        run_end: ["gotify"],
        changes: [],
        delete: [],
      },
    });
  });
});
