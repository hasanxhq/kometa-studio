import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Backup, Validation } from "../api";
import { mockApi, renderAt } from "../test-utils";

// CodeMirror doesn't run in jsdom; a textarea stands in (the checking logic has its own tests in src/yaml).
vi.mock("../components/YamlEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (text: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

const MOVIES = "collections:\n  Trending:\n    tmdb_trending_weekly: 30\n";
const passed: Validation = { ok: true, errors: [], warnings: [], existing_errors: [], checked_by_kometa: true, crashed: false, output: "" };

function refusal(status: number, message: string, validation: Validation | null = null) {
  return () => new Response(JSON.stringify({ detail: { message, path: "Movies.yml", validation } }), { status });
}

describe("Editing a file", () => {
  it("saves after Kometa's check and says where the backup is", async () => {
    let saved = MOVIES;
    const calls = mockApi({
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: saved, hash: saved === MOVIES ? "h1" : "h2", hidden: 0, kind: "collection" }),
      "PUT /config/files": (body) => {
        saved = (body as { files: { text: string }[] }).files[0].text;
        return { backup: "20261030T050000.000000Z", files: [{ path: "Movies.yml", hash: "h2" }], validation: passed };
      },
    });
    renderAt("/files?path=Movies.yml");

    const editor = await screen.findByLabelText("Contents of Movies.yml");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // nothing changed yet
    fireEvent.change(editor, { target: { value: MOVIES + "  Pixar:\n    tmdb_company: 3\n" } });
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Kometa checked it, and it's saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.route === "PUT /config/files")?.body).toEqual({
      files: [{ path: "Movies.yml", text: MOVIES + "  Pixar:\n    tmdb_company: 3\n", base_hash: "h1" }],
      reason: "Edited Movies.yml in Studio",
    });
    expect(screen.getByRole("link", { name: "System → Backup" })).toHaveAttribute("href", "/system/backup");
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument());
  });

  it("shows Kometa's reasons when it refuses, separating problems already there", async () => {
    mockApi({
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: MOVIES, hash: "h1", hidden: 0, kind: "collection" }),
      "PUT /config/files": refusal(422, "Kometa found problems, so nothing was saved.", {
        ...passed,
        ok: false,
        errors: ["library 'Movies' collection_files: path not found: config/Nope.yml"],
        existing_errors: ["config.yml [config-schema.json] at (root): 'tmdb' is a required property"],
      }),
    });
    renderAt("/files?path=Movies.yml");

    fireEvent.change(await screen.findByLabelText("Contents of Movies.yml"), { target: { value: MOVIES + "x: 1\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const report = await screen.findByRole("alert");
    expect(report).toHaveTextContent("Kometa found problems in this change, so nothing was saved.");
    expect(within(report).getByText(/path not found: config\/Nope.yml/)).toHaveClass("break-words");
    expect(report).toHaveTextContent("Already in your files (these don't block saving)");
    expect(report).toHaveTextContent("'tmdb' is a required property");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument(); // the edit is still there to fix
  });

  it("offers a reload when the file changed on disk meanwhile", async () => {
    mockApi({
      "GET /config/edit?path=Movies.yml": () => ({ path: "Movies.yml", text: MOVIES, hash: "h1", hidden: 0, kind: "collection" }),
      "PUT /config/files": refusal(409, "Movies.yml changed on disk since you opened it. Reload it to see the new version."),
    });
    renderAt("/files?path=Movies.yml");
    fireEvent.change(await screen.findByLabelText("Contents of Movies.yml"), { target: { value: "x: 1\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("button", { name: "Reload from disk" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("changed on disk");
  });

  it("explains hidden secrets", async () => {
    mockApi({ "GET /config/edit?path=config.yml": () => ({ path: "config.yml", text: "plex:\n  token: ••••(1)\n", hash: "h", hidden: 1, kind: "config" }) });
    renderAt("/files?path=config.yml");
    expect(await screen.findByLabelText("Contents of config.yml")).toHaveValue("plex:\n  token: ••••(1)\n");
    expect(screen.getByText(/1 secret is hidden as ••••\(n\)/)).toBeInTheDocument();
  });
});

describe("Adding files", () => {
  it("refuses an upload Kometa doesn't accept", async () => {
    const calls = mockApi({
      "GET /plex/libraries": () => ({ libraries: [] }),
      "GET /config": () => ({ path: "/config/config.yml", libraries: [], playlist_files: [] }),
      "PUT /config/files": refusal(422, "Kometa found problems, so nothing was saved.", {
        ...passed,
        ok: false,
        errors: ["Test.yml: [collection-schema.json] at collections -> Test -> sync_mode: 'sometimes' is not one of ['sync', 'append']"],
      }),
    });
    renderAt("/libraries");

    fireEvent.click(await screen.findByRole("button", { name: "Add files…" }));
    const file = new File(["collections:\n  Test:\n    sync_mode: sometimes\n"], "Test.yml", { type: "application/x-yaml" });
    fireEvent.change(screen.getByLabelText("Files"), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("Folder inside the config folder"), { target: { value: "/collections/" } });
    expect(screen.getByText("Saved as collections/Test.yml")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check and add 1 file" }));

    expect(await screen.findByText(/'sometimes' is not one of/)).toBeInTheDocument();
    expect(calls.find((c) => c.route === "PUT /config/files")?.body).toEqual({
      files: [{ path: "collections/Test.yml", text: "collections:\n  Test:\n    sync_mode: sometimes\n", base_hash: null }],
      reason: "Uploaded collections/Test.yml",
    });
    expect(screen.getByRole("link", { name: "Edit config.yml" })).toHaveAttribute("href", "/files?path=config.yml");
  });
});

describe("System → Backup", () => {
  const backup: Backup = { id: "b1", created: "2026-10-30T05:00:00Z", reason: "Edited Movies.yml in Studio", files: ["Movies.yml"], new_files: ["New.yml"] };

  it("compares a backup with today's file and restores it", async () => {
    const calls = mockApi({
      "GET /backups": () => ({ backups: [backup], keep: 30 }),
      "GET /backups/b1/file?path=Movies.yml": () => ({ path: "Movies.yml", backup: MOVIES, current: MOVIES.replace("30", "50") }),
      "POST /backups/b1/restore": () => ({ backup: "b2", restored: ["Movies.yml"], removed: ["New.yml"], validation: passed }),
    });
    renderAt("/system/backup");

    expect(await screen.findByText("Edited Movies.yml in Studio")).toBeInTheDocument();
    expect(screen.getByText(/new then; restoring removes it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Movies.yml · compare" }));
    expect(await screen.findByText("tmdb_trending_weekly: 30", { exact: false, selector: ".text-err" })).toBeInTheDocument();
    expect(screen.getByText("tmdb_trending_weekly: 50", { exact: false, selector: ".text-ok" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore…" }));
    expect(calls.some((c) => c.route === "POST /backups/b1/restore")).toBe(false); // asks first
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByText(/Restored Movies.yml, New.yml \(removed\)\. Kometa's check of the files now passes\./)).toBeInTheDocument();
  });
});
