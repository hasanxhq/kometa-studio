import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { api, type HealthCheck } from "../api";
import { Button, Card } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";
import { formatRelative, formatTime } from "../runs";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
      <dt className="w-40 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-words font-mono text-sm">{value}</dd>
    </div>
  );
}

const levelStyles: Record<HealthCheck["level"], { label: string; className: string }> = {
  error: { label: "Error", className: "text-err" },
  warning: { label: "Warning", className: "text-warn" },
  info: { label: "Info", className: "text-info" },
};

function Health({ checks }: { checks: HealthCheck[] }) {
  return (
    <Card title="Health">
      {checks.length === 0 ? (
        <p className="text-sm text-ok">No problems found.</p>
      ) : (
        <ul className="flex flex-col">
          {checks.map((check) => (
            <li key={check.source} className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
              <span className={`w-20 shrink-0 text-sm font-semibold ${levelStyles[check.level].className}`}>{levelStyles[check.level].label}</span>
              <span className="min-w-0 flex-1 text-sm">
                {check.message}
                {check.link && check.link !== "/system/status" && (
                  <>
                    {" "}
                    <Link to={check.link} className="whitespace-nowrap text-muted underline hover:text-text">
                      Open
                    </Link>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const serviceNames: Record<string, string> = { tmdb: "TMDb", mdblist: "MDBList", imdb: "IMDb", tvdb: "TheTVDB", omdb: "OMDb", plex: "Plex", letterboxd: "Letterboxd" };

// What today's runs asked of each service (from Kometa's --timings, which runs can't use yet; see usage.py), and how close MDBList's key is to its daily allowance.
function Usage() {
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage, refetchInterval: 60_000 });
  if (!usage.data) return null;
  const { today, mdblist, limit_share, held } = usage.data;
  const sources = Object.entries(today)
    .filter(([source]) => !source.startsWith("other:") && source !== "plex")
    .sort((a, b) => b[1] - a[1]);
  const share = mdblist ? mdblist.used / mdblist.limit : null;
  return (
    <Card title="Service use today">
      <div className="flex flex-col gap-3 text-sm">
        {sources.length === 0 ? (
          <p className="text-muted">Calls per service aren't available: this version of Kometa can't report them yet.</p>
        ) : (
          <ul className="flex flex-wrap gap-x-6 gap-y-1">
            {sources.map(([source, calls]) => (
              <li key={source}>
                <span className="text-muted">{serviceNames[source] ?? source}</span> <span className="font-mono">{calls}</span>
              </li>
            ))}
          </ul>
        )}
        {mdblist && share !== null && (
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap justify-between gap-2">
              <span>
                MDBList: {mdblist.used} of {mdblist.limit} requests today
              </span>
              <span className="text-xs text-muted">MDBList last asked {formatRelative(mdblist.checked_at)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${Math.round(share * 100)}% of MDBList's daily allowance used`}>
              <div className={`h-full ${share >= limit_share ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(share, 1) * 100}%` }} />
            </div>
          </div>
        )}
        <p className="text-xs text-muted">
          Runs after imports wait once MDBList reaches {Math.round(limit_share * 100)}% of its daily allowance, until it resets at midnight UTC. Scheduled and
          manual runs always go.
        </p>
        {held && <p className="text-warn">{held}.</p>}
      </div>
    </Card>
  );
}

export function SystemStatus() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });

  if (status.isPending) {
    return <p className="text-muted">Loading…</p>;
  }
  if (status.isError) {
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {status.error.message}
      </p>
    );
  }

  const { version, kometa, database, health } = status.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Health checks={health} />
      <Usage />
      <section className="rounded-card border border-border bg-surface px-6 py-3">
        <h2 className="py-2 text-base font-semibold">About</h2>
        <dl>
          <Row label="Studio" value={version} />
          <Row label="Kometa" value={kometa.version ?? "Not configured"} />
          <Row label="Kometa config" value={kometa.config ?? "Not configured"} />
          <Row label="Database schema" value={`v${database.schema_version}`} />
        </dl>
      </section>
      <FullCheck />
    </div>
  );
}

// Tier 3 (handoff v2 §7.3): Kometa connects to Plex and every service in config.yml, and changes nothing.
export function FullCheck({ title = "Full check" }: { title?: string }) {
  const queryClient = useQueryClient();
  const last = useQuery({ queryKey: ["full-check"], queryFn: api.fullCheck.last });
  const run = useMutation({ mutationFn: api.fullCheck.run, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["full-check"] }) });
  const result = run.data ?? last.data?.last ?? null;
  return (
    <Card
      title={title}
      actions={
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Checking… (up to a few minutes)" : "Run full check"}
        </Button>
      }
    >
      <p className="mb-3 text-sm text-muted">
        Kometa reads your whole config and connects to Plex and every service in it (TMDb, MDBList, Radarr…) to make sure they answer. It doesn't
        change anything or send notifications.
      </p>
      {run.isError && (
        <p role="alert" className="text-err">
          {run.error.message}
        </p>
      )}
      {result ? (
        <ValidationReport validation={result} verdict={`${result.ok ? "Passed" : "Found problems"} (${formatTime(result.at)})`} />
      ) : (
        !run.isPending && <p className="text-sm text-muted">Not run yet.</p>
      )}
    </Card>
  );
}
