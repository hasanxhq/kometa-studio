// The Overview (handoff §6): what's running, how the last run went, what's next, what needs attention, and Run now, on one page.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Navigate } from "react-router";

import { api, type Backup, type Run, type Status } from "../api";
import { CatchUpNotice } from "../components/CatchUpNotice";
import { RunAgain } from "../components/RunAgain";
import { Card, Tag } from "../components/ui";
import { libraryPath, libraryTypeLabels, mergeLibraries } from "../libraries";
import { describeRequest, formatDuration, formatRelative, formatTime, isActive, statusLabels, statusTones, triggerLabels } from "../runs";
import { RunForm } from "./ActivityQueue";
import { Summary } from "./RunDetail";
import { FullCheck } from "./SystemStatus";

const SHOWN_SAVES = 6;
const SHOWN_CHANGES = 8;

function plural(count: number, word: string): string {
  return `${count.toLocaleString()} ${word}${count === 1 ? "" : "s"}`;
}

function Tile({ label, to, children }: { label: string; to: string; children: ReactNode }) {
  return (
    <li>
      <Link
        to={to}
        className="flex h-full flex-col gap-1.5 rounded-card border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2"
      >
        <span className="text-xs font-medium uppercase tracking-wider text-muted">{label}</span>
        {children}
      </Link>
    </li>
  );
}

function Headline({ children }: { children: ReactNode }) {
  return <span className="break-words font-display text-lg font-semibold">{children}</span>;
}

function Detail({ children }: { children: ReactNode }) {
  return <span className="break-words text-sm text-muted">{children}</span>;
}

function NowTile({ running, queued }: { running: Run | undefined; queued: number }) {
  const waiting = queued > 0 ? `${queued} waiting` : null;
  return (
    <Tile label="Now" to={running ? `/activity/queue/${running.id}` : "/activity/queue"}>
      {running ? (
        <>
          <Headline>
            <span className="text-info">Running</span> {describeRequest(running.request)}
          </Headline>
          <Detail>{[`Run #${running.id}`, formatDuration(running.started_at, null), waiting].filter(Boolean).join(" · ")}</Detail>
        </>
      ) : (
        <>
          <Headline>{waiting ? "Starting soon" : "Nothing running"}</Headline>
          <Detail>{waiting ?? "The queue is empty."}</Detail>
        </>
      )}
    </Tile>
  );
}

function LastRunTile({ run }: { run: Run | undefined }) {
  if (!run) {
    return (
      <Tile label="Last run" to="/activity/queue">
        <Headline>None yet</Headline>
        <Detail>Kometa hasn't run from Studio.</Detail>
      </Tile>
    );
  }
  const summary = run.summary;
  return (
    <Tile label="Last run" to={`/activity/queue/${run.id}`}>
      <Headline>
        <Tag tone={statusTones[run.status]}>{statusLabels[run.status]}</Tag> {describeRequest(run.request)}
      </Headline>
      <Detail>
        <span title={formatTime(run.finished_at)}>{run.finished_at ? formatRelative(run.finished_at) : formatTime(run.queued_at)}</span>
        {" · "}
        {triggerLabels[run.trigger]}
        {run.started_at && ` · took ${formatDuration(run.started_at, run.finished_at)}`}
      </Detail>
      {summary && (
        <span className="text-sm">
          <span className="text-ok">+{summary.items_added ?? 0}</span> <span className="text-err">−{summary.items_removed ?? 0}</span> items
        </span>
      )}
      {run.error_events > 0 && <span className="text-sm text-err">{plural(run.error_events, "error")}</span>}
    </Tile>
  );
}

function NextRunTile({ next }: { next: Status["runs"]["next_scheduled"] | undefined }) {
  return (
    <Tile label="Next run" to="/system/tasks">
      {next ? (
        <>
          <Headline>{next.name}</Headline>
          <Detail>
            <span title={formatTime(next.at)}>{formatRelative(next.at)}</span> · {formatTime(next.at)}
          </Detail>
        </>
      ) : (
        <>
          <Headline>No schedule</Headline>
          <Detail>Kometa only runs when you start it. Add a schedule in System → Tasks.</Detail>
        </>
      )}
    </Tile>
  );
}

function HealthTile({ health }: { health: Status["health"] | undefined }) {
  const errors = health?.filter((check) => check.level === "error") ?? [];
  const warnings = health?.filter((check) => check.level === "warning") ?? [];
  const first = errors[0] ?? warnings[0];
  return (
    <Tile label="Health" to="/system/status">
      {health === undefined ? (
        <Detail>Checking…</Detail>
      ) : first ? (
        <>
          <Headline>
            {errors.length > 0 && <span className="text-err">{plural(errors.length, "error")}</span>}
            {errors.length > 0 && warnings.length > 0 && ", "}
            {warnings.length > 0 && <span className="text-warn">{plural(warnings.length, "warning")}</span>}
          </Headline>
          <Detail>{first.message}</Detail>
        </>
      ) : (
        <>
          <Headline>
            <span className="text-ok">No problems</span>
          </Headline>
          <Detail>Plex, the services and Studio's own checks are fine.</Detail>
        </>
      )}
    </Tile>
  );
}

/** Saves made after the last successful run started: Kometa read the files as that run began, so these wait for the next one. */
export function savedSince(backups: Backup[], run: Run | undefined): Backup[] {
  const since = run?.started_at ? Date.parse(run.started_at) : null;
  return backups.filter((backup) => backup.created !== null && (since === null || Date.parse(backup.created) > since));
}

function PendingChanges({ runs }: { runs: Run[] | undefined }) {
  const backups = useQuery({ queryKey: ["backups"], queryFn: api.backups.list });
  const lastGood = runs?.find((run) => run.status === "succeeded");
  const scoped = lastGood && (lastGood.request.mode !== "all" || lastGood.request.libraries.length > 0 || lastGood.request.collections.length > 0 || lastGood.request.files.length > 0);
  const pending = backups.data && runs ? savedSince(backups.data.backups, lastGood) : null;

  return (
    <Card title="Saved since the last run">
      {backups.isError ? (
        <p role="alert" className="text-sm text-err">
          {backups.error.message}
        </p>
      ) : pending === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-muted">
            {lastGood ? (
              <>
                {pending.length === 0 ? "Nothing has been saved since " : "Saved after "}
                <Link className="underline hover:text-text" to={`/activity/queue/${lastGood.id}`}>
                  run #{lastGood.id}
                </Link>{" "}
                started ({formatRelative(lastGood.started_at!)}), the last run that succeeded.
                {pending.length > 0 && " The next run applies these."}
                {scoped && ` That run was ${describeRequest(lastGood.request)}, so it may not have applied everything saved before it.`}
              </>
            ) : pending.length === 0 ? (
              "Nothing has been saved in Studio yet."
            ) : (
              "No run has finished yet, so Kometa hasn't applied these."
            )}
          </p>
          {pending.length > 0 && (
            <ul className="flex flex-col">
              {pending.slice(0, SHOWN_SAVES).map((backup) => (
                <li key={backup.id} className="flex flex-col gap-0.5 border-b border-border py-2 last:border-0 sm:flex-row sm:items-baseline sm:gap-3">
                  <span className="min-w-0 flex-1 break-words">{backup.reason}</span>
                  <span className="break-words font-mono text-xs text-muted">{backup.files.join(", ")}</span>
                  <span className="shrink-0 text-xs text-muted" title={formatTime(backup.created)}>
                    {formatRelative(backup.created!)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {pending.length > SHOWN_SAVES && (
            <Link className="min-h-11 content-center self-start text-muted underline hover:text-text" to="/system/backup">
              {pending.length - SHOWN_SAVES} more in System → Backup
            </Link>
          )}
        </div>
      )}
    </Card>
  );
}

function LastRunChanges({ run }: { run: Run }) {
  const detail = useQuery({ queryKey: ["runs", run.id], queryFn: () => api.runs.get(run.id) });
  const changes = detail.data?.events.filter((e) => e.event === "changes" || e.event === "delete") ?? [];
  // The run's own error is shown already; count the others.
  const errors = detail.data?.events.filter((e) => e.event === "error" && e.error !== run.error) ?? [];
  return (
    <Card
      title={`Last run: #${run.id}`}
      actions={
        <span className="flex flex-wrap items-center gap-3">
          {run.status !== "succeeded" && <RunAgain run={run} />}
          <Link className="min-h-11 content-center text-sm text-muted underline hover:text-text" to={`/activity/queue/${run.id}`}>
            Open the run
          </Link>
        </span>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        {run.summary ? (
          <Summary summary={run.summary} />
        ) : (
          <p className="text-muted">Kometa didn't report a summary for this run. That happens when it stops before the end, for example on a config error.</p>
        )}
        {run.error && <p className="text-err">{run.error}</p>}
        {errors.length > 0 && (
          <p className="text-warn">
            Kometa reported {plural(errors.length, "error")}. The run's page lists them.
          </p>
        )}
        {changes.length > 0 && (
          <ul className="flex flex-col" aria-label="Collections changed">
            {changes.slice(0, SHOWN_CHANGES).map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 border-b border-border py-2 last:border-0">
                <span className="min-w-0 flex-1 break-words">
                  {e.event === "delete" ? e.message : [e.library_name, e.collection ?? e.playlist].filter(Boolean).join(" · ") || "Kometa"}
                </span>
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
        )}
        {changes.length > SHOWN_CHANGES && <p className="text-muted">And {plural(changes.length - SHOWN_CHANGES, "more collection")} on the run's page.</p>}
      </div>
    </Card>
  );
}

const itemWords: Record<string, string> = { movie: "movie", show: "show" };

function LibrarySummary() {
  const plex = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const entries = mergeLibraries(plex.data?.libraries, config.data?.libraries);
  return (
    <Card
      title="Libraries"
      actions={
        <Link className="min-h-11 content-center text-sm text-muted underline hover:text-text" to="/libraries">
          All libraries
        </Link>
      }
    >
      {plex.isError && (
        <p role="alert" className="mb-3 text-sm text-warn">
          {plex.error.message}
        </p>
      )}
      {config.isError && (
        <p role="alert" className="mb-3 text-sm text-err">
          {config.error.message}
        </p>
      )}
      {plex.isPending || config.isPending ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted">No libraries yet. Connect Plex in Settings → Plex.</p>
      ) : (
        <ul className="flex flex-col">
          {entries.map(({ name, plex: inPlex, config: inConfig }) => (
            <li key={name}>
              <Link
                to={libraryPath(name)}
                className="flex min-h-11 flex-col gap-1 border-b border-border py-3 hover:bg-surface-2 sm:flex-row sm:items-center sm:gap-4 sm:px-2"
              >
                <span className="flex min-w-0 items-center gap-2 sm:w-56 sm:shrink-0">
                  <span className="min-w-0 break-words font-semibold">{name}</span>
                  {inPlex && <Tag>{libraryTypeLabels[inPlex.type] ?? inPlex.type}</Tag>}
                </span>
                <span className="flex min-w-0 flex-1 flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                  {inPlex ? (
                    <>
                      {inPlex.items != null && itemWords[inPlex.type] && <span>{plural(inPlex.items, itemWords[inPlex.type])}</span>}
                      <span>
                        {plural(inPlex.collections, "collection")}
                        {inPlex.collections > 0 && <span className="text-accent"> · {inPlex.managed} by Kometa</span>}
                      </span>
                    </>
                  ) : (
                    plex.isSuccess && <span className="text-warn">Not in Plex</span>
                  )}
                  {inConfig ? (
                    <span>
                      {plural(inConfig.collection_files, "collection file")}, {plural(inConfig.overlay_files, "overlay file")}
                      {inConfig.defaults > 0 && `, ${plural(inConfig.defaults, "default")}`}
                    </span>
                  ) : (
                    <span>Not in Kometa's config.yml</span>
                  )}
                  {inConfig && inConfig.problems.length > 0 && <span className="text-warn">{plural(inConfig.problems.length, "problem")} in its files</span>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function Overview() {
  // Until Kometa has what it needs to run, there's nothing to show here: first-run setup comes first.
  const setup = useQuery({ queryKey: ["config", "setup"], queryFn: api.config.setup, retry: false });
  if (setup.data && !setup.data.done) return <Navigate to="/setup" replace />;
  return <Dashboard />;
}

function Dashboard() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 30_000 });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs.list,
    refetchInterval: (query) => (query.state.data?.runs.some((r) => isActive(r.status)) ? 3000 : 15_000),
  });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules.list });
  const kometa = useQuery({ queryKey: ["kometa"], queryFn: api.kometa });

  const all = runs.data?.runs;
  const running = all?.find((r) => r.status === "running");
  const queued = all?.filter((r) => r.status === "queued").length ?? 0;
  const lastRun = all?.find((r) => !isActive(r.status));
  const queuedRun = () => {
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["status"] });
  };

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <CatchUpNotice catchUps={schedules.data?.catch_ups ?? []} />
      {runs.isError && (
        <p role="alert" className="text-err">
          Can't reach the Studio API: {runs.error.message}
        </p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="At a glance">
        <NowTile running={running} queued={queued} />
        <LastRunTile run={lastRun} />
        <NextRunTile next={status.data?.runs?.next_scheduled} />
        <HealthTile health={status.data?.health} />
      </ul>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <RunForm kometa={kometa.data} onQueued={queuedRun} />
        <PendingChanges runs={all} />
      </div>
      {lastRun && <LastRunChanges run={lastRun} />}
      <LibrarySummary />
      <FullCheck title="Connections" />
    </div>
  );
}
