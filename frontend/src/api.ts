// Typed calls to the Studio API (/api/v1).

import { urlBase } from "./base";
import type { SchemaKind } from "./yaml/schema";

export type HealthCheck = { source: string; level: "error" | "warning" | "info"; message: string; link: string | null };

// What the newest Kometa run learned: Kometa checks for a new version as each run starts.
export type KometaUpdates = { installed: string | null; checked_at: string | null; latest: string | null; notes: string | null; available: boolean };

export type Status = {
  version: string;
  kometa: { version: string | null; config: string | null; updates: KometaUpdates };
  database: { schema_version: number };
  health: HealthCheck[];
  runs: { current: number | null; queued: number; next_scheduled: { at: string; schedule_id: number; name: string } | null };
};

// --- Sign-in and Settings → General ---

export type AuthStatus = {
  allowed: boolean;
  reason: "login" | "setup" | "cross_site" | null; // why not, when not allowed
  message: string | null;
  configured: boolean; // a username and password are set
  signed_in: boolean; // through a session cookie (so Sign out means something)
  local: boolean;
};

export type AuthRequired = "enabled" | "disabled_for_local";

export type GeneralSettings = {
  auth: { configured: boolean; username: string | null; required: AuthRequired };
  api_key: string;
  timezone: string;
  host: string;
  port: number;
  reverse_proxy: ReverseProxy;
  you: { address: string | null; peer: string | null; proxied: boolean; trusted_proxy: boolean; local: boolean }; // how Studio sees this browser
};

export type ReverseProxy = { url_base: string; trusted: string[] };

export type AuthInput = { username: string; password: string | null; required: AuthRequired; current_password: string | null };

// Any 401 means the session ended (or sign-in was switched on): the app shows the login page.
export const SIGNED_OUT_EVENT = "studio:signed-out";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown, // FastAPI's `detail`, when it's more than a message (e.g. Kometa's verdict)
  ) {
    super(message);
  }
}

export type PlexState = {
  config: { path: string | null; url: string | null; token: string | null; error: string | null; custom: boolean };
  account: { name: string } | null;
};

/** One test of the server saved in config.yml. */
export type PlexConnectionCheck = {
  status: "ok" | "error" | "unset";
  name: string | null;
  version: string | null;
  latency_ms: number | null;
  error: string | null;
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

export type RunTrigger = "manual" | "schedule" | "catch_up" | "arr" | "maintainerr";

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

// Radarr and Sonarr (Settings → Connect). Their URL and key are Kometa's, in config.yml.
export type ArrKind = "radarr" | "sonarr";

/** When to run Kometa after one app's imports. */
export type AppRuns = { enabled: boolean; trigger: "any" | "relevant"; mode: RunMode; wait_minutes: number; libraries: string[] };

export type ArrSettings = Record<ArrKind, AppRuns>;

export type ArrConnection = {
  url: string | null; // from config.yml
  token: string | null; // masked, e.g. "…1234"; the key itself never leaves the server
  root_folder_path: string | null;
  quality_profile: string | null;
  username: string | null; // for a proxy in front of the app (Studio's own)
  has_password: boolean;
  status: { checked_at: string; ok: boolean; error: string | null } | null;
};

export type ArrConnectionInput = {
  url: string;
  api_key: string | null; // null: keep the key in config.yml
  username: string | null;
  password: string | null; // null: keep the saved one
  root_folder_path: string | null;
  quality_profile: string | null;
};

export type ArrTest = { ok: true; app: string; version: string; root_folders: string[]; quality_profiles: string[] } | { ok: false; error: string };

export type ArrPending = { first_at: string; last_at: string; due_at: string; imports: number; titles: string[] };

/** What Studio can tell about a library, for "only imports that matter". */
export type LibraryRelevance = {
  library: string;
  reports: boolean; // Kometa's missing report (save_report) is on
  reported_at: string | null; // when Kometa last reported on all its collections
  changed: boolean; // the collection files changed since
  wanted: number; // items its collections want that Plex doesn't have
  ids: number; // items named by ID in its collections
  lists: number; // list-based collections
  rule: string[]; // collections that search Plex: every import counts
  unreadable: string[];
  overlays: boolean;
};

export type ArrState = {
  settings: ArrSettings;
  connections: Record<ArrKind, ArrConnection>;
  pending: Partial<Record<ArrKind, ArrPending>>;
  skipped: Record<ArrKind, { at: string; title: string; libraries: string }[]>;
  libraries: LibraryRelevance[];
};

// The Overlays page: per library, what draws overlays and Kometa's Original Posters backup.
export type OverlayLibrary = {
  library: string; // the name in config.yml
  plex_name: string;
  off: boolean; // remove_overlays is set: Kometa keeps the original posters and draws none
  files: { kind: string; value: string; error: string | null; files: { path: string; title: string | null; docs_url: string | null; overlays: string[] }[] }[];
  backup: { posters: number; bytes: number } | null;
  last_pass: { run_id: number; status: RunStatus; started_at: string | null; finished_at: string | null } | null;
  maintainerr: { collections: string[]; on_top: boolean } | null; // Maintainerr collections with overlays in this library
};

// Kometa's calls per service today (from --timings), and MDBList's daily allowance (System → Status).
export type Usage = {
  today: Record<string, number>;
  mdblist: { limit: number; used: number; checked_at: string } | null;
  limit_share: number; // runs after imports wait at this share of MDBList's allowance
  held: string | null;
};

// Settings → Network: a proxy, DNS over HTTPS for chosen services, IPv4 first, and a connection check.
export type NetworkState = {
  proxy_url: string | null; // http://host:port, https://host:port or socks5://host:port
  proxy_username: string | null;
  has_password: boolean;
  no_proxy: string[];
  doh_provider: "cloudflare" | "google";
  doh_services: string[];
  prefer_ipv4: boolean;
  local: string[]; // always reached directly
  services: { id: string; name: string; domains: string[] }[];
  providers: { id: "cloudflare" | "google"; name: string }[];
};

export type ProxyInput = { url: string | null; username: string | null; password: string | null; no_proxy: string[] };

export type NetworkCheck = {
  name: string;
  url: string;
  host: string;
  via: "direct" | "proxy";
  system_dns: string[];
  system_dns_error?: string;
  doh_dns: string[] | null;
  doh_dns_error?: string;
  ok: boolean;
  status: number | null;
  ms: number | null;
  error: string | null;
  verdict: string;
};

// TMDb and MDBList (Settings → Connect): Kometa's keys, in config.yml.
export type ServiceName = "tmdb" | "mdblist";
export type ServicesState = Record<ServiceName, { apikey: string | null }>; // apikey masked
export type ServiceTest = { ok: true; limit?: number | null; used?: number | null } | { ok: false; error: string };

export type TautulliState = { url: string | null; apikey: string | null }; // apikey masked
export type TautulliInput = { url: string; apikey: string | null }; // apikey null: keep the saved one
export type TautulliTest = { ok: true; version: string | null } | { ok: false; error: string };

// Kometa's own log files (System → Logs).
export type LogLevel = "TRACE" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
export type LogFile = { path: string; size: number; modified: number };
export type LogView = { path: string; lines: { level: LogLevel; text: string }[]; truncated: boolean; size: number };

// Maintainerr (Settings → Connect).
export type MaintainerrState = {
  url: string | null;
  username: string | null; // for a proxy in front of Maintainerr, as on a seedbox
  has_password: boolean; // a password is saved (it's never sent back)
  leave_overlays_alone: boolean;
  collections: { title: string; library: string | null; overlays: boolean }[];
  overlays_enabled: boolean;
  error: string | null;
  checked_seconds_ago: number | null;
  risks: string[]; // ways Kometa's config would touch Maintainerr's collections
  // With "Leave Maintainerr overlays alone", Studio holds Maintainerr's own overlay schedule and has it draw daily, after Kometa.
  schedule: { taken_over: boolean; own_cron: string | null; last_redraw: string | null; next_redraw: string | null };
};

export type MaintainerrInput = { url: string | null; username: string | null; password: string | null; leave_overlays_alone: boolean };

// --- Settings → Notifications ---

export type NotificationServiceName = "notifiarr" | "gotify" | "ntfy" | "apprise";

// One config.yml key. A secret's value never comes back: `masked` says one is saved (e.g. "…ab12").
export type NotificationKey = { name: string; label: string; secret: boolean; value: string | null; masked: string | null };

export type NotificationService = { name: NotificationServiceName; label: string; configured: boolean; keys: NotificationKey[] };

export type WebhookEvent = "error" | "version" | "run_start" | "run_end" | "changes" | "delete";

// A column of the webhook grid. A URL's id hides it ("url:…"); "studio" is Studio's own receiver, which only Studio changes.
export type WebhookTarget = { id: string; label: string; kind: "service" | "url" | "studio"; configured: boolean };

export type NotificationsState = {
  path: string;
  hash: string | null; // config.yml's, which a save must match
  error: string | null;
  services: NotificationService[];
  webhooks: { targets: WebhookTarget[]; events: Record<WebhookEvent, string[]> };
  saved?: SaveResult;
};

export type NotificationValues = Record<string, string | null>; // a secret left null keeps the saved one

export type NotificationTest = { ok: true; message: string } | { ok: false; error: string };

// The jobs drawer (Bazarr-style): everything running, waiting, or recently finished.
export type JobStatus = "running" | "pending" | "failed" | "completed";

export type Job = {
  id: string;
  kind: "run" | "task" | "arr" | "maintainerr";
  title: string;
  status: JobStatus;
  label: string; // e.g. Queued, Timed out, Retrying
  message: string | null; // a running run's latest log line
  progress: { value: number; max: number } | null;
  started_at: string | null;
  finished_at: string | null;
  due_at?: string;
  link: string;
  run_id: number | null;
  cancellable: boolean;
};

// Studio's own tasks on System → Tasks.
export type TaskName = "full_backup" | "full_check";

export type BuiltinTask = {
  name: TaskName;
  label: string;
  enabled: boolean;
  days: number[]; // 0 = Monday ... 6 = Sunday
  time: string;
  timezone: string;
  options: { keep?: number };
  next_run: string | null;
  running: boolean;
  last: { started_at: string; finished_at: string | null; status: "running" | "succeeded" | "failed" | "interrupted"; message: string | null } | null;
};

export type BuiltinTaskInput = Pick<BuiltinTask, "enabled" | "days" | "time" | "options"> & { timezone?: string | null };

export type FullBackup = { name: string; size: number; created: string };

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

export type DefaultEntry = {
  name: string; // what `default:` takes
  group: "chart" | "award" | "both" | "movie" | "show" | "overlays";
  types: string[]; // the Plex library types it suits: movie, show
  title: string | null;
  docs_url: string | null;
};

export type DefaultsCatalogue = { collections: DefaultEntry[]; overlays: DefaultEntry[] };

export type DefaultKind = "collection" | "overlay";

// --- Plex ---

export type PlexLibrarySummary = { key: string; title: string; type: string; items?: number | null; collections: number; managed: number; maintainerr?: number };

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
  maintainerr?: boolean; // Maintainerr made it: Kometa leaves it alone
};

export type PlexItem = {
  rating_key: string;
  title: string;
  type: string; // movie, show, …
  year: number | null;
  thumb: string | null;
  ids: { tmdb?: string; imdb?: string; tvdb?: string };
  content_rating: string | null;
  audience_rating: number | null;
  episodes: number | null; // shows only
  added_at: number | null;
};

export type PlexCollectionPage = { collection: PlexCollection; items: PlexItem[]; start: number; total: number };

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

// --- Editing (milestone 6) ---

export type Validation = {
  ok: boolean;
  errors: string[]; // problems this change would introduce
  warnings: string[];
  existing_errors: string[]; // problems the files already had; they don't block a save
  checked_by_kometa: boolean;
  crashed: boolean;
  output: string;
};

export type EditableFile = { path: string; text: string; hash: string; hidden: number; kind: SchemaKind };

export type FileEdit = { path: string; text: string; base_hash: string | null };

export type SaveResult = { backup: string; files: { path: string; hash: string }[]; validation: Validation };

export type SaveRefusal = { message: string; path: string | null; validation: Validation | null };

export type Backup = { id: string; created: string | null; reason: string; files: string[]; new_files: string[] };

export type FullCheck = Validation & { at: string };

export type ItemSection = "collections" | "dynamic_collections" | "overlays" | "templates" | "metadata" | "playlists";

export type Item = { path: string; hash: string; section: ItemSection; name: string; value: Record<string, unknown>; kind: SchemaKind };

export type ItemSave = {
  path: string;
  base_hash: string | null; // null: a new file, started with this item and added to `library` in config.yml
  section: ItemSection;
  name: string;
  value: Record<string, unknown> | null; // null removes it
  create?: boolean;
  rename?: string | null;
  library?: string | null;
};

export type KometaInfo = {
  flags: string[] | null;
  flags_error: string | null;
  problem: string | null;
  paths?: { python: string | null; entry: string | null; config: string | null; schemas: string | null };
  run_timeout?: number; // seconds
  kill_after?: number;
};

// FastAPI puts the reason in `detail`: a string from most errors, a list from request validation,
// and {message, path, validation} from a refused save.
async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // not JSON (a proxy's error page, say)
  }
  let message = `${response.status} ${response.statusText}`;
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail)) message = detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
  else if (detail && typeof detail === "object" && "message" in detail) message = String((detail as { message: unknown }).message);
  return new ApiError(response.status, message, detail);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${urlBase}/api/v1${path}`, {
    method,
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth")) window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    throw await errorFrom(response);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  status: () => request<Status>("GET", "/status"),
  auth: {
    status: () => request<AuthStatus>("GET", "/auth"),
    login: (username: string, password: string) => request<{ ok: true }>("POST", "/auth/login", { username, password }),
    logout: () => request<{ ok: true }>("POST", "/auth/logout"),
  },
  general: {
    get: () => request<GeneralSettings>("GET", "/settings/general"),
    setAuth: (body: AuthInput) => request<GeneralSettings>("PUT", "/settings/auth", body),
    newApiKey: () => request<GeneralSettings>("POST", "/settings/api-key"),
    setTimezone: (timezone: string) => request<GeneralSettings>("PUT", "/settings/timezone", { timezone }),
    setReverseProxy: (body: ReverseProxy) => request<GeneralSettings>("PUT", "/settings/reverse-proxy", body),
  },
  plex: {
    state: () => request<PlexState>("GET", "/plex"),
    startSignIn: () => request<PlexPin>("POST", "/plex/pin"),
    pollSignIn: (id: number) => request<PlexPinStatus>("GET", `/plex/pin/${id}`),
    signOut: () => request<void>("DELETE", "/plex/account"),
    connection: () => request<PlexConnectionCheck>("GET", "/plex/connection"),
    servers: () => request<{ servers: PlexServer[] }>("GET", "/plex/servers"),
    test: (url: string, token: string) => request<PlexTestResult>("POST", "/plex/test", { url, token }),
    connect: (body: PlexConnectRequest) => request<PlexState>("POST", "/plex/connect", body),
  },
  kometa: () => request<KometaInfo>("GET", "/kometa"),
  config: {
    overview: () => request<{ path: string; libraries: LibraryCounts[]; playlist_files: FileReference[] }>("GET", "/config"),
    library: (name: string) => request<ConfigLibrary>("GET", `/config/libraries/${encodeURIComponent(name)}`),
    file: (path: string) => request<{ path: string; text: string }>("GET", `/config/file?path=${encodeURIComponent(path)}`),
    addLibrary: (name: string) => request<SaveResult>("POST", "/config/libraries", { name }),
    defaults: () => request<DefaultsCatalogue>("GET", "/config/defaults"),
    useDefault: (library: string, kind: DefaultKind, name: string, variables: Record<string, unknown>) =>
      request<SaveResult>("PUT", `/config/libraries/${encodeURIComponent(library)}/defaults/${kind}/${encodeURIComponent(name)}`, { template_variables: variables }),
    dropDefault: (library: string, kind: DefaultKind, name: string) =>
      request<SaveResult>("DELETE", `/config/libraries/${encodeURIComponent(library)}/defaults/${kind}/${encodeURIComponent(name)}`),
    setLibraryVariables: (library: string, variables: Record<string, unknown>) =>
      request<SaveResult>("PUT", `/config/libraries/${encodeURIComponent(library)}/template-variables`, { template_variables: variables }),
  },
  plexLibraries: {
    list: () => request<{ libraries: PlexLibrarySummary[] }>("GET", "/plex/libraries"),
    collections: (key: string) =>
      request<{ library: Omit<PlexLibrarySummary, "collections" | "managed">; collections: PlexCollection[] }>(
        "GET",
        `/plex/libraries/${encodeURIComponent(key)}/collections`,
      ),
    collection: (key: string, ratingKey: string, start = 0, size = 100) =>
      request<PlexCollectionPage>("GET", `/plex/libraries/${encodeURIComponent(key)}/collections/${encodeURIComponent(ratingKey)}?start=${start}&size=${size}`),
    imageUrl: (path: string, width = 240, height = 360) =>
      `${urlBase}/api/v1/plex/image?path=${encodeURIComponent(path)}&width=${width}&height=${height}`,
  },
  files: {
    open: (path: string) => request<EditableFile>("GET", `/config/edit?path=${encodeURIComponent(path)}`),
    check: (files: FileEdit[]) => request<Validation>("POST", "/config/check", { files }),
    save: (files: FileEdit[], reason: string) => request<SaveResult>("PUT", "/config/files", { files, reason }),
  },
  items: {
    get: (path: string, section: ItemSection, name: string) =>
      request<Item>("GET", `/config/item?path=${encodeURIComponent(path)}&section=${section}&name=${encodeURIComponent(name)}`),
    save: (body: ItemSave) => request<SaveResult>("POST", "/config/item", body),
  },
  backups: {
    list: () => request<{ backups: Backup[]; keep: number }>("GET", "/backups"),
    file: (id: string, path: string) =>
      request<{ path: string; backup: string; current: string | null }>("GET", `/backups/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`),
    restore: (id: string) =>
      request<{ backup: string; restored: string[]; removed: string[]; validation: Validation }>("POST", `/backups/${encodeURIComponent(id)}/restore`),
  },
  arr: {
    get: () => request<ArrState>("GET", "/settings/arr"),
    saveRuns: (kind: ArrKind, runs: AppRuns) => request<ArrState>("PUT", `/settings/arr/${kind}/runs`, runs),
    connect: (kind: ArrKind, body: ArrConnectionInput) => request<ArrState>("PUT", `/settings/arr/${kind}`, body),
    test: (kind: ArrKind, body: ArrConnectionInput) => request<ArrTest>("POST", `/settings/arr/${kind}/test`, body),
    remove: (kind: ArrKind) => request<ArrState>("DELETE", `/settings/arr/${kind}`),
    turnOnReports: () => request<ArrState>("POST", "/settings/arr/reports"),
  },
  services: {
    get: () => request<ServicesState>("GET", "/settings/services"),
    test: (name: ServiceName, apikey: string | null) => request<ServiceTest>("POST", `/settings/services/${name}/test`, { apikey }),
    save: (name: ServiceName, apikey: string | null) => request<ServicesState>("PUT", `/settings/services/${name}`, { apikey }),
    remove: (name: ServiceName) => request<ServicesState>("DELETE", `/settings/services/${name}`),
  },
  tautulli: {
    get: () => request<TautulliState>("GET", "/settings/tautulli"),
    test: (body: TautulliInput) => request<TautulliTest>("POST", "/settings/tautulli/test", body),
    save: (body: TautulliInput) => request<TautulliState>("PUT", "/settings/tautulli", body),
    remove: () => request<TautulliState>("DELETE", "/settings/tautulli"),
  },

  logs: {
    list: () => request<{ files: LogFile[] }>("GET", "/logs"),
    read: (path: string, level: LogLevel, q: string) =>
      request<LogView>("GET", `/logs/file?${new URLSearchParams({ path, level, q }).toString()}`),
    downloadUrl: (path: string) => `${urlBase}/api/v1/logs/download?path=${encodeURIComponent(path)}`,
  },
  maintainerr: {
    get: () => request<MaintainerrState>("GET", "/settings/maintainerr"),
    save: (body: MaintainerrInput) => request<MaintainerrState>("PUT", "/settings/maintainerr", body),
    test: (url: string, username: string | null, password: string | null) =>
      request<{ ok: true; collections: number; overlays_enabled: boolean } | { ok: false; error: string }>("POST", "/settings/maintainerr/test", {
        url,
        username,
        password,
      }),
  },
  notifications: {
    get: () => request<NotificationsState>("GET", "/settings/notifications"),
    test: (name: NotificationServiceName, values: NotificationValues) =>
      request<NotificationTest>("POST", `/settings/notifications/${name}/test`, { values }),
    save: (name: NotificationServiceName, values: NotificationValues, baseHash: string | null) =>
      request<NotificationsState>("PUT", `/settings/notifications/${name}`, { values, base_hash: baseHash }),
    remove: (name: NotificationServiceName, baseHash: string) =>
      request<NotificationsState>("DELETE", `/settings/notifications/${name}?base_hash=${encodeURIComponent(baseHash)}`),
    saveWebhooks: (events: Record<WebhookEvent, string[]>, baseHash: string | null) =>
      request<NotificationsState>("PUT", "/settings/notifications/webhooks", { events, base_hash: baseHash }),
  },
  jobs: () => request<{ jobs: Job[]; at: string }>("GET", "/jobs"),
  usage: () => request<Usage>("GET", "/usage"),
  network: {
    get: () => request<NetworkState>("GET", "/settings/network"),
    testProxy: (body: ProxyInput) => request<{ ok: true; ip: string } | { ok: false; error: string }>("POST", "/settings/network/proxy/test", body),
    saveProxy: (body: ProxyInput) => request<NetworkState>("PUT", "/settings/network/proxy", body),
    testDoh: (provider: string, services: string[]) =>
      request<{ ok: true; found: Record<string, string> } | { ok: false; error: string }>("POST", "/settings/network/doh/test", { provider, services }),
    saveDoh: (provider: string, services: string[]) => request<NetworkState>("PUT", "/settings/network/doh", { provider, services }),
    saveIpv4: (prefer_ipv4: boolean) => request<NetworkState>("PUT", "/settings/network/ipv4", { prefer_ipv4 }),
    check: () => request<{ results: NetworkCheck[] }>("POST", "/network/check"),
  },
  overlays: {
    list: () => request<{ libraries: OverlayLibrary[] }>("GET", "/overlays"),
    apply: (library: string) => request<{ run_id: number }>("POST", `/overlays/${encodeURIComponent(library)}/apply`),
    off: (library: string) => request<{ run_id: number }>("POST", `/overlays/${encodeURIComponent(library)}/off`),
    on: (library: string) => request<{ run_id: number }>("POST", `/overlays/${encodeURIComponent(library)}/on`),
  },
  tasks: {
    list: () => request<{ tasks: BuiltinTask[] }>("GET", "/tasks"),
    update: (name: TaskName, body: BuiltinTaskInput) => request<BuiltinTask>("PUT", `/tasks/${name}`, body),
    run: (name: TaskName) => request<BuiltinTask>("POST", `/tasks/${name}/run`),
  },
  fullBackups: {
    list: () => request<{ backups: FullBackup[] }>("GET", "/backups/full"),
    remove: (name: string) => request<void>("DELETE", `/backups/full/${encodeURIComponent(name)}`),
    url: (name: string) => `${urlBase}/api/v1/backups/full/${encodeURIComponent(name)}`,
  },
  fullCheck: {
    last: () => request<{ last: FullCheck | null }>("GET", "/kometa/full-check"),
    run: () => request<FullCheck>("POST", "/kometa/full-check"),
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
    logUrl: (id: number) => `${urlBase}/api/v1/runs/${id}/log`,
    streamUrl: (id: number) => `${urlBase}/api/v1/runs/${id}/stream`,
  },
};

/** The refusal behind a failed save, if that's what the error is. */
export function saveRefusal(error: unknown): SaveRefusal | null {
  if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "message" in error.detail) {
    return error.detail as SaveRefusal;
  }
  return null;
}
