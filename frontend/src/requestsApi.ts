// Missing-media requests: settings, the Requests page, and collection download-missing helpers.

import { ApiError, request } from "./api";

export type RequestVia = "auto" | "arr" | "seerr";

export type RequestSettings = {
  enabled: boolean;
  via: RequestVia;
  radarr: {
    quality_profile: string | null;
    root_folder: string | null;
    minimum_availability: "announced" | "inCinemas" | "released";
    search: boolean;
  };
  sonarr: {
    quality_profile: string | null;
    root_folder: string | null;
    monitor: "all" | "future" | "missing" | "existing" | "firstSeason" | "latestSeason" | "pilot";
    search: boolean;
    series_type: "standard" | "anime" | "daily";
  };
  daily_cap: number | null;
  confirm_over: number;
};

export type SeerrJson = {
  kind: "overseerr" | "jellyseerr";
  url: string;
  api_key: string | null;
  username: string | null;
  has_password: boolean;
};

export type SeerrIn = {
  kind: "overseerr" | "jellyseerr";
  url: string;
  api_key: string | null;
  username: string | null;
  password: string | null;
};

export type RequestsSettingsState = {
  settings: RequestSettings;
  seerr: SeerrJson | null;
  connected: { radarr: boolean; sonarr: boolean; seerr: boolean };
};

export type ArrOptions = { quality_profiles: string[]; root_folders: string[] };

export type RequestsOptions = {
  radarr: ArrOptions | null;
  sonarr: ArrOptions | null;
  errors: Record<string, string>;
};

export type SeerrTest = { ok: true; version?: string | null } | { ok: false; error: string };

export type RequestStatus = "requested" | "downloading" | "imported" | "failed" | "cancelled" | "exists";

export type RequestRow = {
  id: number;
  item: string;
  media: "movie" | "show";
  title: string | null;
  year: number | null;
  library: string;
  collection_id: number | null;
  via: string;
  external_id: string | null;
  status: RequestStatus;
  error: string | null;
  requested_at: string;
  updated_at: string;
  imported_at: string | null;
  labelled_at: string | null;
};

export type RequestCounts = Record<RequestStatus, number>;

export type RequestsList = { requests: RequestRow[]; counts: RequestCounts };

export type RequestSummary = {
  waiting: number;
  requested: number;
  downloading: number;
  imported: number;
  failed: number;
};

export type RequestOutcome = {
  requested: number;
  exists: number;
  failed: number;
  capped: number;
  skipped: number;
  items: { item: string; status: string; error: string | null }[];
};

export type NeedsConfirm = { message: string; needs_confirm: true; count: number };

export const emptySummary = (): RequestSummary => ({ waiting: 0, requested: 0, downloading: 0, imported: 0, failed: 0 });

export function summaryHasCounts(summary: RequestSummary | null | undefined): boolean {
  if (!summary) return false;
  return summary.waiting > 0 || summary.requested > 0 || summary.downloading > 0 || summary.imported > 0 || summary.failed > 0;
}

/** 409 from create/update when download_missing would request more than confirm_over. */
export function needsConfirm(error: unknown): NeedsConfirm | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = error.detail;
  if (!detail || typeof detail !== "object" || !("needs_confirm" in detail)) return null;
  const body = detail as { needs_confirm?: unknown; count?: unknown; message?: unknown };
  if (body.needs_confirm !== true || typeof body.count !== "number") return null;
  return {
    message: typeof body.message === "string" ? body.message : `Request ${body.count} titles now?`,
    needs_confirm: true,
    count: body.count,
  };
}

export const requestsApi = {
  settings: () => request<RequestsSettingsState>("GET", "/requests/settings"),
  saveSettings: (body: RequestSettings) => request<RequestsSettingsState>("PUT", "/requests/settings", body),
  options: () => request<RequestsOptions>("GET", "/requests/options"),
  testSeerr: (body: SeerrIn) => request<SeerrTest>("POST", "/requests/seerr/test", body),
  saveSeerr: (body: SeerrIn) => request<RequestsSettingsState>("PUT", "/requests/seerr", body),
  removeSeerr: () => request<RequestsSettingsState>("DELETE", "/requests/seerr"),
  list: (filters: { status?: RequestStatus | ""; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    params.set("limit", String(filters.limit ?? 200));
    return request<RequestsList>("GET", `/requests?${params}`);
  },
  refresh: () => request<Record<string, number>>("POST", "/requests/refresh"),
  cancel: (id: number) => request<RequestRow>("POST", `/requests/${id}/cancel`),
  requestMissing: (id: number) => request<RequestOutcome>("POST", `/collections/${id}/request-missing`),
  setDownloadMissing: (id: number, download_missing: boolean) =>
    request<{ download_missing: boolean }>("PUT", `/collections/${id}/download-missing`, { download_missing }),
};
