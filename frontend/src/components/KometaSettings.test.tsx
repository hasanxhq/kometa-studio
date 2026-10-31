import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderAt } from "../test-utils";

// Shaped like Kometa's config schema's settings definition.
const configSchema = {
  type: "object",
  properties: { settings: { $ref: "#/definitions/settings" } },
  definitions: {
    settings: {
      type: "object",
      properties: {
        cache: { type: "boolean", description: "Used to control Kometa's cache database.\nMore detail." },
        sync_mode: { enum: ["sync", "append"], description: "Used to set the sync_mode for collections and playlists." },
        run_order: { type: "array", items: { type: "string" }, description: "Used to specify the run order of the library components." },
      },
    },
  },
};

const kometa = { flags: [], flags_error: null, problem: null, paths: { python: null, entry: null, config: null, schemas: null } };

describe("Kometa's settings", () => {
  it("shows each setting with Kometa's default, and saves only what changed against what it started from", async () => {
    const calls = mockApi({
      "GET /kometa": () => kometa,
      "GET /config/schemas/config": () => configSchema,
      "GET /config/settings": () => ({ values: { sync_mode: "append", tvdb_lang: "en" }, defaults: { cache: true, sync_mode: "append", run_order: ["operations", "metadata", "collections", "overlays"] } }),
      "PUT /config/settings": () => ({ backup: "b1", files: [], validation: { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" } }),
    });
    renderAt("/settings/kometa");

    const form = await screen.findByRole("form", { name: "Kometa's settings" });
    const sync = await within(form).findByLabelText(/Sync mode/);
    expect(sync).toHaveValue("append");
    expect(within(form).getByLabelText("Cache (cache)")).toHaveDisplayValue("Default (Yes)");
    expect(within(form).getByText("Set the sync_mode for collections and playlists. Kometa's default: append.")).toBeInTheDocument();
    expect(within(form).getByText("Control Kometa's cache database. Kometa's default: Yes.")).toBeInTheDocument();
    expect(within(form).getByText(/Kometa's default: operations, metadata, collections, overlays\./)).toBeInTheDocument();
    expect(within(form).getByText("Other")).toBeInTheDocument(); // tvdb_lang: in config.yml, unknown to the schema, kept as YAML

    const save = within(form).getByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Cache (cache)"), { target: { value: "false" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((call) => call.route === "PUT /config/settings")).toBe(true));
    expect(calls.find((call) => call.route === "PUT /config/settings")?.body).toEqual({
      base: { sync_mode: "append", tvdb_lang: "en" },
      values: { sync_mode: "append", tvdb_lang: "en", cache: false },
    });
    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
  });
});
