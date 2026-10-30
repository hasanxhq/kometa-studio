// One run: what it did (Kometa's run_end numbers and webhook events) and its log.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { api, type RunEvent, type RunSummary } from "../api";
import { RunLog } from "../components/RunLog";
import { Button, Card, Tag } from "../components/ui";
import { describeRequest, formatDuration, formatTime, isActive, statusLabels, statusTones, triggerLabels } from "../runs";

function Stat({ label, value, tone }: { label: string; value: number | undefined; tone?: string }) {
  return (
    <div className="rounded-control border border-border bg-surface-2 px-3 py-2">
      <div className={`font-display text-xl font-semibold ${tone ?? ""}`}>{value ?? 0}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}

function Summary({ summary }: { summary: RunSummary }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Stat label="Collections created" value={summary.collections_created} />
      <Stat label="Collections modified" value={summary.collections_modified} />
      <Stat label="Collections deleted" value={summary.collections_deleted} />
      <Stat label="Items added" value={summary.items_added} tone="text-ok" />
      <Stat label="Items removed" value={summary.items_removed} tone="text-err" />
      <Stat label="Added to Radarr" value={summary.added_to_radarr} />
      <Stat label="Added to Sonarr" value={summary.added_to_sonarr} />
    </div>
  );
}

function where(event: RunEvent): string {
  return [event.library_name, event.collection ?? event.playlist].filter(Boolean).join(" · ") || "Kometa";
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="w-28 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function RunDetail() {
  const id = Number(useParams().id);
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["runs", id],
    queryFn: () => api.runs.get(id),
    enabled: Number.isInteger(id),
    refetchInterval: (query) => (query.state.data && isActive(query.state.data.status) ? 3000 : false),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["runs"] });
  const cancel = useMutation({ mutationFn: () => api.runs.cancel(id), onSuccess: refresh });

  if (run.isPending) return <p className="text-muted">Loading…</p>;
  if (run.isError)
    return (
      <p role="alert" className="text-err">
        {run.error.message}
      </p>
    );

  const r = run.data;
  const errors = r.events.filter((e) => e.event === "error");
  const changes = r.events.filter((e) => e.event === "changes" || e.event === "delete");
  const version = r.events.find((e) => e.event === "version");

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <Link to="/activity/queue" className="min-h-11 content-center text-sm text-muted underline">
        ← Queue
      </Link>
      <Card
        title={`Run #${r.id}: ${describeRequest(r.request)}`}
        actions={
          <div className="flex items-center gap-3">
            <Tag tone={statusTones[r.status]}>{statusLabels[r.status]}</Tag>
            {isActive(r.status) && (
              <Button onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                Cancel
              </Button>
            )}
          </div>
        }
      >
        <dl className="flex flex-col gap-2 text-sm">
          <Row label="Started">{r.started_at ? formatTime(r.started_at) : `Queued ${formatTime(r.queued_at)}`}</Row>
          <Row label="Started by">
            {r.trigger === "catch_up" ? "Catch-up: Studio was off when its schedule was due" : triggerLabels[r.trigger]}
          </Row>
          {r.started_at && <Row label="Took">{formatDuration(r.started_at, r.finished_at)}</Row>}
          {r.error && (
            <Row label="Problem">
              <span className="text-err">{r.error}</span>
            </Row>
          )}
          {r.command && (
            <Row label="Command">
              <code className="break-all font-mono text-xs">{r.command}</code>
            </Row>
          )}
        </dl>
        {version && (
          <p className="mt-3 text-sm text-info">
            Kometa {version.latest} is out (this is {version.current}).
          </p>
        )}
      </Card>

      {r.summary ? (
        <Card title="What changed">
          <Summary summary={r.summary} />
        </Card>
      ) : (
        !isActive(r.status) && (
          <p className="text-sm text-muted">
            Kometa didn't report a summary for this run. That happens when it stops before the end, for example on a config error.
          </p>
        )
      )}

      {errors.length > 0 && (
        <Card title={`Errors (${errors.length})`}>
          <ul className="flex flex-col gap-2 text-sm">
            {errors.map((e, i) => (
              <li key={i} className="border-b border-border pb-2 last:border-0">
                <span className="text-muted">{where(e)}:</span> <span className={e.critical ? "text-err" : "text-warn"}>{e.error}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {changes.length > 0 && (
        <Card title={`Collections changed (${changes.length})`}>
          <ul className="flex flex-col text-sm">
            {changes.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 border-b border-border py-2 last:border-0">
                <span className="min-w-0 flex-1">{e.event === "delete" ? e.message : where(e)}</span>
                {e.created && <Tag tone="ok">New</Tag>}
                {e.event === "delete" && <Tag tone="err">Deleted</Tag>}
                {e.event === "changes" && (
                  <span className="text-xs">
                    <span className="text-ok">+{e.additions ?? 0}</span> <span className="text-err">−{e.removals ?? 0}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Log">
        {r.status === "queued" ? <p className="text-muted">Waiting for the run before it to finish.</p> : <RunLog key={r.id} runId={r.id} onEnd={refresh} />}
      </Card>
    </div>
  );
}
