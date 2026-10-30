// Typed calls to the Studio API (/api/v1).

export type Status = {
  version: string;
  kometa: { version: string | null; config: string | null };
  database: { schema_version: number };
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export type PlexState = {
  config: { path: string | null; url: string | null; token: string | null; error: string | null };
  account: { name: string } | null;
};

export type PlexConnection = {
  uri: string;
  local: boolean;
  relay: boolean;
  secure: boolean;
  ok: boolean;
  error: string | null;
  latency_ms: number | null;
};

export type PlexServer = { id: string; name: string; version: string; connections: PlexConnection[]; best: string | null };

export type PlexPin = { id: number; auth_url: string };

export type PlexPinStatus = { status: "waiting" | "expired" } | { status: "signed_in"; account: { name: string } };

export type PlexTestResult = { ok: true; name: string; version: string; url: string } | { ok: false; error: string };

export type PlexConnectRequest = { server_id: string; uri: string } | { url: string; token: string };

export type RunMode = "all" | "collections" | "overlays" | "operations" | "metadata" | "playlists";

export type RunRequest = {
  mode: RunMode;
  libraries: string[];
  collections: string[];
  files: string[];
  ignore_schedules: boolean;
  no_missing: boolean;
  tests: boolean;
  timings: boolean;
  low_priority: boolean;
};

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted" | "timed_out";

// Kometa's run_end webhook payload.
export type RunSummary = {
  run_time?: string;
  collections_created?: number;
  collections_modified?: number;
  collections_deleted?: number;
  items_added?: number;
  items_removed?: number;
  added_to_radarr?: number;
  added_to_sonarr?: number;
};

export type RunTrigger = "manual" | "schedule" | "catch_up" | "arr";

export type Run = {
  id: number;
  status: RunStatus;
  trigger: RunTrigger;
  schedule_id: number | null;
  request: RunRequest;
  command: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error: string | null;
  summary: RunSummary | null;
  error_events: number;
};

export type RunEvent = {
  event: "error" | "changes" | "delete" | "version";
  received_at: string;
  error?: string;
  critical?: boolean;
  library_name?: string;
  collection?: string;
  playlist?: string;
  created?: boolean;
  message?: string;
  current?: string;
  latest?: string;
  additions?: number;
  removals?: number;
};

export type RunDetail = Run & { events: RunEvent[] };

export type Schedule = {
  id: number;
  name: string;
  request: RunRequest;
  days: number[]; // 0 = Monday ... 6 = Sunday
  time: string; // HH:MM in the schedule's timezone
  timezone: string;
  enabled: boolean;
  catch_up: "run_once" | "skip";
  next_run: string | null;
  last_run: { id: number; status: RunStatus; trigger: RunTrigger; started_at: string | null; finished_at: string | null } | null;
};

export type ScheduleInput = Pick<Schedule, "name" | "request" | "days" | "time" | "enabled" | "catch_up"> & { timezone: string | null };

export type Schedules = {
  schedules: Schedule[];
  timezone: string; // what new schedules use
  catch_ups: { id: number; status: RunStatus; queued_at: string; name: string }[];
};

// --- Kometa's config (read-only) ---

export type ConfigCollection = {
  name: string;
  dynamic: boolean;
  type: string | null;
  builders: string[];
  templates: string[];
  sync_mode: string | null;
  schedule: unknown;
};

export type ConfigOverlay = {
  name: string;
  overlay: string | null;
  position: Record<string, string | number>;
  builders: string[];
  templates: string[];
};

export type FileSummary = {
  path: string;
  title: string | null;
  docs_url: string | null;
  collections: ConfigCollection[];
  overlays: ConfigOverlay[];
  playlists: { name: string; libraries: unknown }[];
  metadata: number;
  templates: string[];
  error: string | null;
};

export type FileReference = {
  kind: "default" | "file" | "folder" | "url" | "git" | "repo" | "unknown";
  value: string;
  template_variables: Record<string, unknown>;
  options: Record<string, unknown>;
  files: FileSummary[];
  error: string | null;
};

export type LibraryCounts = {
  name: string;
  plex_name: string;
  collection_files: number;
  overlay_files: number;
  metadata_files: number;
  defaults: number;
  collections: number;
  overlays: number;
  operations: number;
  problems: string[];
};

export type ConfigLibrary = {
  name: string;
  collection_files: FileReference[];
  overlay_files: FileReference[];
  metadata_files: FileReference[];
  operations: Record<string, unknown>;
  template_variables: Record<string, unknown>;
  settings: Record<string, unknown>;
  counts: LibraryCounts;
};

// --- Plex ---

export type PlexLibrarySummary = { key: string; title: string; type: string; collections: number; managed: number };

export type PlexCollection = {
  rating_key: string;
  title: string;
  items: number;
  managed: boolean;
  smart: boolean;
  summary: string;
  thumb: string | null;
  added_at: number | null;
  updated_at: number | null;
};

// --- History ---

export type HistoryItem = { title: string | null; tmdb_id: number | null; tvdb_id: number | null };

export type HistoryEvent = {
  id: number;
  run_id: number | null;
  event: "changes" | "delete";
  received_at: string;
  library: string | null;
  collection: string | null;
  playlist: string | null;
  message: string | null;
  created: boolean;
  poster_url: string | null;
  additions: HistoryItem[];
  removals: HistoryItem[];
  radarr_adds: HistoryItem[];
  sonarr_adds: HistoryItem[];
};

export type HistoryPage = { events: HistoryEvent[]; libraries: string[]; next: number | null };

export type KometaInfo = { flags: string[] | null; flags_error: string | null; problem: string | null };

// FastAPI puts the reason in `detail`: a string from our own errors, a list from request validation.
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
  } catch {
    // not JSON (a proxy's error page, say)
  }
  return `${response.status} ${response.statusText}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  status: () => request<Status>("GET", "/status"),
  plex: {
    state: () => request<PlexState>("GET", "/plex"),
    startSignIn: () => request<PlexPin>("POST", "/plex/pin"),
    pollSignIn: (id: number) => request<PlexPinStatus>("GET", `/plex/pin/${id}`),
    signOut: () => request<void>("DELETE", "/plex/account"),
    servers: () => request<{ servers: PlexServer[] }>("GET", "/plex/servers"),
    test: (url: string, token: string) => request<PlexTestResult>("POST", "/plex/test", { url, token }),
    connect: (body: PlexConnectRequest) => request<PlexState>("POST", "/plex/connect", body),
  },
  kometa: () => request<KometaInfo>("GET", "/kometa"),
  config: {
    overview: () => request<{ path: string; libraries: LibraryCounts[]; playlist_files: FileReference[] }>("GET", "/config"),
    library: (name: string) => request<ConfigLibrary>("GET", `/config/libraries/${encodeURIComponent(name)}`),
    file: (path: string) => request<{ path: string; text: string }>("GET", `/config/file?path=${encodeURIComponent(path)}`),
  },
  plexLibraries: {
    list: () => request<{ libraries: PlexLibrarySummary[] }>("GET", "/plex/libraries"),
    collections: (key: string) =>
      request<{ library: Omit<PlexLibrarySummary, "collections" | "managed">; collections: PlexCollection[] }>(
        "GET",
        `/plex/libraries/${encodeURIComponent(key)}/collections`,
      ),
    imageUrl: (path: string, width = 240, height = 360) =>
      `/api/v1/plex/image?path=${encodeURIComponent(path)}&width=${width}&height=${height}`,
  },
  history: (filters: { library?: string; q?: string; before?: number }) => {
    const params = new URLSearchParams();
    if (filters.library) params.set("library", filters.library);
    if (filters.q) params.set("q", filters.q);
    if (filters.before !== undefined) params.set("before", String(filters.before));
    const query = params.toString();
    return request<HistoryPage>("GET", `/history${query ? `?${query}` : ""}`);
  },
  schedules: {
    list: () => request<Schedules>("GET", "/schedules"),
    create: (body: ScheduleInput) => request<Schedule>("POST", "/schedules", body),
    update: (id: number, body: ScheduleInput) => request<Schedule>("PUT", `/schedules/${id}`, body),
    remove: (id: number) => request<void>("DELETE", `/schedules/${id}`),
    run: (id: number) => request<Run>("POST", `/schedules/${id}/run`),
  },
  runs: {
    list: () => request<{ runs: Run[]; current: number | null }>("GET", "/runs"),
    get: (id: number) => request<RunDetail>("GET", `/runs/${id}`),
    create: (body: RunRequest) => request<Run>("POST", "/runs", body),
    cancel: (id: number) => request<Run>("POST", `/runs/${id}/cancel`),
    logUrl: (id: number) => `/api/v1/runs/${id}/log`,
    streamUrl: (id: number) => `/api/v1/runs/${id}/stream`,
  },
};
