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
};
