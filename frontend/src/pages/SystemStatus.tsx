import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { Button, Card } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";
import { formatTime } from "../runs";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
      <dt className="w-40 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-words font-mono text-sm">{value}</dd>
    </div>
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

  const { version, kometa, database } = status.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
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
function FullCheck() {
  const queryClient = useQueryClient();
  const last = useQuery({ queryKey: ["full-check"], queryFn: api.fullCheck.last });
  const run = useMutation({ mutationFn: api.fullCheck.run, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["full-check"] }) });
  const result = run.data ?? last.data?.last ?? null;
  return (
    <Card
      title="Full check"
      actions={
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Checking… (up to a few minutes)" : "Run full check"}
        </Button>
      }
    >
      <p className="mb-3 text-sm text-muted">
        Kometa reads your whole config and connects to Plex and every service in it (TMDb, Trakt, Radarr…) to make sure they answer. It doesn't
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
