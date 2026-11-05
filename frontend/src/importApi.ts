// Move over from Kometa: report, switch-over, undo and export.

import { request } from "./api";
import { urlBase } from "./base";

export type Landing = {
  name: string;
  result: "imported" | "ready_made" | "kept" | "studio";
  reason: string | null;
  notes: string[];
  definition: object | null;
  kept_with_file: boolean;
};

export type FileLanding = {
  kind: "file" | "folder" | "default" | "url" | "git" | "repo" | "unknown";
  value: string;
  path: string | null;
  action: "replace" | "keep" | "studio";
  reason: string | null;
  collections: Landing[];
  ready_made: { category: string; title: string; exclude: string[] } | null;
};

export type LibraryReport = {
  name: string;
  type: string | null;
  error: string | null;
  files: FileLanding[];
  overlay_files: string[];
  metadata_files: string[];
};

export type ImportReport = {
  config: boolean;
  summary: {
    collections: number;
    imported: number;
    ready_made: number;
    kept: number;
    kept_with_file: number;
    already_studio: number;
    files: { replace: number; keep: number; studio: number };
  };
  libraries: LibraryReport[];
  playlist_files: string[];
};

export type SwitchOver = {
  id: number;
  created_at: string;
  backup: string;
  imported: number;
  ready_made: number;
  kept: number;
  libraries: string[];
};

export type UndoPreview = {
  loses: {
    added: { library: string; title: string }[];
    changed: { library: string; title: string }[];
  };
  plex: { library: string; title: string }[];
  files: string[];
};

export type UndoResult = {
  restored_files: number;
  deleted_from_plex: string[];
  backup: string;
};

export const importApi = {
  report: () => request<ImportReport>("GET", "/import"),
  switchOver: () => request<{ active: SwitchOver | null }>("GET", "/import/switch-over"),
  doSwitchOver: () => request<{ switch_over: SwitchOver; run_id: number | null }>("POST", "/import/switch-over", { confirm: true }),
  undoPreview: () => request<UndoPreview>("GET", "/import/undo"),
  undo: (delete_from_plex: boolean) => request<UndoResult>("POST", "/import/undo", { confirm: true, delete_from_plex }),
  exportUrl: () => `${urlBase}/api/v1/import/export`,
};
