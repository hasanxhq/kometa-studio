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

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => getJson<Status>("/status"),
};
