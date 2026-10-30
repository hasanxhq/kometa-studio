import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NetworkState } from "../api";
import { mockApi, renderAt } from "../test-utils";

const state: NetworkState = {
  proxy_url: null,
  proxy_username: null,
  has_password: false,
  no_proxy: [],
  doh_provider: "cloudflare",
  doh_services: [],
  prefer_ipv4: false,
  local: ["localhost", "192.168.0.0/16"],
  services: [
    { id: "tmdb", name: "TMDb", domains: ["themoviedb.org", "tmdb.org"] },
    { id: "mdblist", name: "MDBList", domains: ["mdblist.com"] },
  ],
  providers: [
    { id: "cloudflare", name: "Cloudflare (1.1.1.1)" },
    { id: "google", name: "Google (8.8.8.8)" },
  ],
  tmdb_quick_fix: true,
};

describe("Settings → Network", () => {
  it("saves a proxy only after a passing test, with its login and exceptions", async () => {
    const calls = mockApi({
      "GET /settings/network": () => state,
      "POST /settings/network/proxy/test": () => ({ ok: true, ip: "203.0.113.9" }),
      "PUT /settings/network/proxy": () => ({ ...state, proxy_url: "socks5://proxy.lan:1080", proxy_username: "hasan", has_password: true }),
    });
    renderAt("/settings/network");

    const form = await screen.findByRole("form", { name: "Proxy" });
    fireEvent.change(within(form).getByLabelText("Proxy"), { target: { value: "socks5" } });
    fireEvent.change(within(form).getByLabelText("Address"), { target: { value: "proxy.lan:1080" } });
    fireEvent.click(within(form).getByLabelText("The proxy asks for a login"));
    fireEvent.change(within(form).getByLabelText("Username"), { target: { value: "hasan" } });
    fireEvent.change(within(form).getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.change(within(form).getByLabelText("Don't use the proxy for"), { target: { value: "nas\n\n.example.com " } });
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Works: the internet sees Studio as 203.0.113.9.")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(calls.find((c) => c.route === "PUT /settings/network/proxy")?.body).toEqual({
        url: "socks5://proxy.lan:1080",
        username: "hasan",
        password: "secret",
        no_proxy: ["nas", ".example.com"],
      }),
    );
  });

  it("tests DNS over HTTPS for the ticked services before saving, and says the TMDb quick fix is on", async () => {
    const calls = mockApi({
      "GET /settings/network": () => state,
      "POST /settings/network/doh/test": () => ({ ok: true, found: { tmdb: "13.224.0.10" } }),
      "PUT /settings/network/doh": () => ({ ...state, doh_services: ["tmdb"], doh_provider: "google" }),
    });
    renderAt("/settings/network");

    const form = await screen.findByRole("form", { name: "DNS over HTTPS" });
    expect(within(form).getByText(/TMDb's DNS bypass, the quick fix on/)).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Provider"), { target: { value: "google" } });
    fireEvent.click(within(form).getByLabelText("TMDb"));
    expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText("Found TMDb at 13.224.0.10.")).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.route === "PUT /settings/network/doh")?.body).toEqual({ provider: "google", services: ["tmdb"] }));
  });

  it("checks connections and shows where this network's DNS and DNS over HTTPS disagree", async () => {
    mockApi({
      "GET /settings/network": () => state,
      "POST /network/check": () => ({
        results: [
          {
            name: "TMDb",
            url: "https://api.themoviedb.org/3/",
            host: "api.themoviedb.org",
            via: "direct",
            system_dns: ["49.44.79.236"],
            doh_dns: ["13.224.0.10"],
            ok: false,
            status: null,
            ms: null,
            error: "[SSL: CERTIFICATE_VERIFY_FAILED]",
            verdict: "Blocked by this network's DNS: works over DNS over HTTPS, or through a proxy",
          },
          { name: "Plex", url: "http://192.168.1.10:32400/identity", host: "192.168.1.10", via: "direct", system_dns: ["192.168.1.10"], doh_dns: null, ok: true, status: 200, ms: 12, error: null, verdict: "OK" },
        ],
      }),
    });
    renderAt("/settings/network");

    fireEvent.click(await screen.findByRole("button", { name: "Check connections" }));
    const tmdb = await screen.findByRole("listitem", { name: "TMDb" });
    expect(within(tmdb).getByText(/Blocked by this network's DNS/)).toBeInTheDocument();
    expect(within(tmdb).getByText("DNS: 49.44.79.236")).toBeInTheDocument();
    expect(within(tmdb).getByText("DNS over HTTPS: 13.224.0.10")).toHaveClass("text-warn");
    const plex = screen.getByRole("listitem", { name: "Plex" });
    expect(within(plex).getByText("HTTP 200 · 12 ms")).toBeInTheDocument();
    expect(within(plex).getByText("DNS over HTTPS: local address")).toBeInTheDocument();
  });
});
