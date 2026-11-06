// Move over from Kometa: report, switch-over, undo, export, and uploading a collection file.

import { ApiError, SIGNED_OUT_EVENT, request } from "./api";
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
  ready_made: { category: string; title: string; exclude: string[]; entries: { block: string; key: string; kometa_name: string; title: string }[] } | null;
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
  run_id: number | null;
};

export type UndoPreview = {
  loses: {
    added: { library: string; title: string }[];
    changed: { library: string; title: string }[];
  };
  plex: { library: string; title: string }[];
  /** What the switch-over moved into Studio: Undo takes Studio's label off them in Plex (they're Kometa's again). */
  unlabels?: { library: string; title: string }[];
  files: string[]; // put back
  removes: string[]; // Studio's files that weren't there before
};

export type UndoResult = {
  restored_files: number;
  deleted_from_plex: string[];
  unlabelled_in_plex?: string[];
  problems: string[]; // what Undo couldn't do in Plex (delete, take the label off), and why
  backup: string;
};

export type UploadStaging = {
  token: string;
  library: string;
  file: FileLanding;
};

export type UploadAddResult = {
  action: "replace" | "keep";
  imported: string[];
  kept_file: string | null;
  run_id: number;
  studio?: string[];
};

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // not JSON
  }
  let message = `${response.status} ${response.statusText}`;
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail)) message = detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
  else if (detail && typeof detail === "object" && "message" in detail) message = String((detail as { message: unknown }).message);
  return new ApiError(response.status, message, detail);
}

export const importApi = {
  report: () => request<ImportReport>("GET", "/import"),
  switchOver: () => request<{ active: SwitchOver | null }>("GET", "/import/switch-over"),
  doSwitchOver: () => request<{ switch_over: SwitchOver; run_id: number | null }>("POST", "/import/switch-over", { confirm: true }),
  undoPreview: () => request<UndoPreview>("GET", "/import/undo"),
  undo: (delete_from_plex: boolean) => request<UndoResult>("POST", "/import/undo", { confirm: true, delete_from_plex }),
  exportUrl: () => `${urlBase}/api/v1/import/export`,
  /** Stage a collection YAML file (raw body, no multipart). */
  upload: async (library: string, text: string, filename: string): Promise<UploadStaging> => {
    const response = await fetch(`${urlBase}/api/v1/import/upload?library=${encodeURIComponent(library)}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-yaml",
        "X-Filename": filename,
      },
      body: text,
    });
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
      throw await errorFrom(response);
    }
    return response.json();
  },
  addUpload: (token: string, library: string) =>
    request<UploadAddResult>("POST", `/import/upload/${encodeURIComponent(token)}/add`, { library, confirm: true }),
};
