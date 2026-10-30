import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AuthStatus, GeneralSettings } from "../api";
import { mockApi, renderAt, signedIn } from "../test-utils";

const notSetUp: AuthStatus = { ...signedIn, configured: false, signed_in: false };

const general: GeneralSettings = {
  auth: { configured: false, username: null, required: "disabled_for_local" },
  api_key: "0123456789abcdef0123456789abcdef",
  timezone: "Asia/Kolkata",
  host: "0.0.0.0",
  port: 8484,
};

describe("Signing in", () => {
  it("shows the login page when Studio wants a password, then the app", async () => {
    let allowed = false;
    const calls = mockApi({
      "GET /auth": () => (allowed ? signedIn : { ...signedIn, allowed: false, reason: "login", message: "Sign in first", signed_in: false }),
      "POST /auth/login": () => {
        allowed = true;
        return { ok: true };
      },
      "GET /status": () => ({ version: "0.1.0", kometa: { version: "2.5.3", config: null, updates: { installed: "2.5.3", checked_at: null, latest: null, notes: null, available: false } }, database: { schema_version: 4 }, health: [] }),
      "GET /kometa/full-check": () => ({ last: null }),
    });
    renderAt("/system/status");

    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "hasan" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("2.5.3")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "POST /auth/login")?.body).toEqual({ username: "hasan", password: "correct horse" });
    expect(screen.getAllByRole("button", { name: "Sign out" }).length).toBeGreaterThan(0); // header, and the phone menu
  });

  it("says why when sign-in isn't set up and this address isn't local", async () => {
    mockApi({ "GET /auth": () => ({ ...notSetUp, allowed: false, reason: "setup", message: "Open Studio from your local network.", local: false }) });
    renderAt("/libraries");
    expect(await screen.findByText("Sign-in isn't set up yet")).toBeInTheDocument();
    expect(screen.getByText("Open Studio from your local network.")).toBeInTheDocument();
  });

  it("goes back to the login page when a request finds the session over", async () => {
    let expired = false;
    mockApi({
      "GET /auth": () => (expired ? { ...signedIn, allowed: false, reason: "login", signed_in: false } : signedIn),
      "GET /settings/general": () => {
        expired = true;
        return new Response(JSON.stringify({ detail: { reason: "login", message: "Sign in first" } }), { status: 401 });
      },
    });
    renderAt("/settings/general");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("Settings → General", () => {
  it("sets up sign-in, and the notice goes away", async () => {
    let auth = notSetUp;
    const calls = mockApi({
      "GET /auth": () => auth,
      "GET /settings/general": () => general,
      "PUT /settings/auth": () => {
        auth = signedIn;
        return { ...general, auth: { configured: true, username: "hasan", required: "enabled" } };
      },
    });
    renderAt("/settings/general");

    expect(await screen.findByText(/anyone on your local network can use Studio/)).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Authentication required"), { target: { value: "enabled" } });
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "hasan" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Set up sign-in" }));

    await waitFor(() => expect(screen.queryByText(/anyone on your local network can use Studio/)).toBeNull());
    expect(calls.find((c) => c.route === "PUT /settings/auth")?.body).toEqual({
      username: "hasan",
      password: "correct horse",
      required: "enabled",
      current_password: null,
    });
    // Set up: the fields fold away behind a link.
    expect(await screen.findByRole("button", { name: "Change username or password" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).toBeNull();
  });

  it("once set up, shows the username and asks for the current password only to change something", async () => {
    const configured: GeneralSettings = { ...general, auth: { configured: true, username: "hasan", required: "enabled" } };
    const calls = mockApi({
      "GET /settings/general": () => configured,
      "PUT /settings/auth": () => ({ ...configured, auth: { ...configured.auth, username: "hasanq" } }),
    });
    renderAt("/settings/general");

    expect(await screen.findByText("hasan")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Sign-in" });
    for (const label of ["Username", "New password", "Current password"]) expect(screen.queryByLabelText(label)).toBeNull();
    expect(within(form).queryByRole("button", { name: "Save" })).toBeNull();

    // Changing who has to sign in still needs the current password; Cancel puts it back.
    fireEvent.change(screen.getByLabelText("Authentication required"), { target: { value: "disabled_for_local" } });
    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByLabelText("Authentication required")).toHaveValue("enabled");
    expect(screen.queryByLabelText("Current password")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Change username or password" }));
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "hasanq" } });
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "correct horse" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
    expect(screen.queryByLabelText("Username")).toBeNull();
    expect(screen.getByText("hasanq")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "PUT /settings/auth")?.body).toEqual({
      username: "hasanq",
      password: null,
      required: "enabled",
      current_password: "correct horse",
    });
  });

  it("replaces the API key only after a second click", async () => {
    const calls = mockApi({
      "GET /settings/general": () => general,
      "POST /settings/api-key": () => ({ ...general, api_key: "fedcba9876543210fedcba9876543210" }),
    });
    renderAt("/settings/general");
    expect(await screen.findByLabelText("API key")).toHaveValue(general.api_key);
    fireEvent.click(screen.getByRole("button", { name: "New key" }));
    expect(calls.some((c) => c.route === "POST /settings/api-key")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Replace it" }));
    await waitFor(() => expect(screen.getByLabelText("API key")).toHaveValue("fedcba9876543210fedcba9876543210"));
  });

  it("saves a timezone chosen from the UTC-offset list", async () => {
    const calls = mockApi({
      "GET /settings/general": () => general,
      "PUT /settings/timezone": () => ({ ...general, timezone: "UTC" }),
    });
    renderAt("/settings/general");

    const select = await screen.findByLabelText("Schedules and tasks use");
    expect(within(select).getByRole("option", { name: /UTC \+05:30 \(Asia\/Kolkata\)/ })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "UTC" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/timezone")?.body).toEqual({ timezone: "UTC" }));
  });
});
