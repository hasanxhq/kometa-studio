// Activity → Queue: start a run, follow the running one, and see recent runs (handoff v2 §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useAdvanced } from "../advanced";
import { api, type KometaInfo, type Run, type RunMode, type RunRequest } from "../api";
import { RunLog } from "../components/RunLog";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";
import { describeRequest, formatDuration, formatTime, isActive, modes, splitNames, statusLabels, statusTones } from "../runs";

const supports = (kometa: KometaInfo | undefined, flag: string | null) => !flag || !kometa?.flags || kometa.flags.includes(flag);

function Checkbox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`flex min-h-11 items-center gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="size-4 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function RunForm({ kometa, onQueued }: { kometa: KometaInfo | undefined; onQueued: () => void }) {
  const { showAdvanced } = useAdvanced();
  const [mode, setMode] = useState<RunMode>("all");
  const [libraries, setLibraries] = useState("");
  const [collections, setCollections] = useState("");
  const [files, setFiles] = useState("");
  const [options, setOptions] = useState({ ignore_schedules: false, no_missing: false, tests: false, timings: false, low_priority: true });
  const create = useMutation({ mutationFn: (body: RunRequest) => api.runs.create(body), onSuccess: onQueued });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // Advanced fields only count while they're shown.
    create.mutate({
      mode,
      libraries: splitNames(libraries),
      collections: showAdvanced ? splitNames(collections) : [],
      files: showAdvanced ? splitNames(files) : [],
      ...(showAdvanced ? options : { ignore_schedules: false, no_missing: false, tests: false, timings: false, low_priority: true }),
    });
  };
  const option = (key: keyof typeof options, label: string, flag: string) => (
    <Checkbox
      label={label}
      checked={options[key]}
      disabled={!supports(kometa, flag)}
      onChange={(value) => setOptions({ ...options, [key]: value })}
    />
  );

  return (
    <Card title="Run Kometa">
      {kometa?.problem && (
        <p role="alert" className="mb-4 text-warn">
          {kometa.problem}
        </p>
      )}
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <fieldset>
          <legend className="mb-1.5 text-sm text-muted">What to run</legend>
          <div className="flex flex-wrap gap-2">
            {modes.map((m) => {
              const available = supports(kometa, m.flag);
              return (
                <label
                  key={m.value}
                  className={[
                    "flex min-h-11 items-center rounded-control border px-3 text-sm",
                    mode === m.value ? "border-accent bg-surface-2 text-accent" : "border-border-strong",
                    available ? "cursor-pointer" : "opacity-50",
                  ].join(" ")}
                >
                  <input
                    type="radio"
                    name="mode"
                    className="sr-only"
                    value={m.value}
                    checked={mode === m.value}
                    disabled={!available}
                    onChange={() => setMode(m.value)}
                  />
                  {m.label}
                </label>
              );
            })}
          </div>
        </fieldset>
        <Field label="Libraries" hint="Names as in config.yml, separated by commas. Leave empty for every library.">
          <input className={inputClass} value={libraries} onChange={(e) => setLibraries(e.target.value)} placeholder="All libraries" />
        </Field>
        {showAdvanced && (
          <>
            <Field label="Collections" hint="Only these collections, separated by commas.">
              <input className={inputClass} value={collections} onChange={(e) => setCollections(e.target.value)} placeholder="All collections" />
            </Field>
            <Field label="Files" hint="Only these collection, overlay or playlist files, separated by commas.">
              <input className={inputClass} value={files} onChange={(e) => setFiles(e.target.value)} placeholder="All files" />
            </Field>
            <div className="grid gap-x-6 sm:grid-cols-2">
              {option("low_priority", "Low priority (gentler on this computer)", "--low-priority")}
              {option("ignore_schedules", "Ignore schedules", "--ignore-schedules")}
              {option("no_missing", "Skip missing-item reports", "--no-missing")}
              {option("tests", "Only collections marked test: true", "--tests")}
              {option("timings", "Record timings", "--timings")}
            </div>
          </>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" type="submit" disabled={create.isPending || !!kometa?.problem}>
            {create.isPending ? "Queueing…" : "Run now"}
          </Button>
          {create.isSuccess && (
            <span role="status" className="text-sm text-ok">
              Queued as <Link className="underline" to={`/activity/queue/${create.data.id}`}>run #{create.data.id}</Link>
            </span>
          )}
          {create.isError && (
            <span role="alert" className="text-sm text-err">
              {create.error.message}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

export function RunRow({ run }: { run: Run }) {
  const summary = run.summary;
  return (
    <li>
      <Link
        to={`/activity/queue/${run.id}`}
        className="flex min-h-11 flex-col gap-1 border-b border-border py-3 last:border-0 hover:bg-surface-2 sm:flex-row sm:items-center sm:gap-4 sm:px-2"
      >
        <span className="flex w-36 shrink-0 items-center gap-2">
          <Tag tone={statusTones[run.status]}>{statusLabels[run.status]}</Tag>
          <span className="text-xs text-muted">#{run.id}</span>
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">{describeRequest(run.request)}</span>
        <span className="flex flex-wrap gap-x-3 text-xs text-muted">
          {summary && (
            <span>
              <span className="text-ok">+{summary.items_added ?? 0}</span> <span className="text-err">−{summary.items_removed ?? 0}</span> items
            </span>
          )}
          {run.error_events > 0 && <span className="text-err">{run.error_events} error{run.error_events === 1 ? "" : "s"}</span>}
          <span>{formatTime(run.started_at ?? run.queued_at)}</span>
          {run.started_at && <span>{formatDuration(run.started_at, run.finished_at)}</span>}
        </span>
      </Link>
    </li>
  );
}

export function ActivityQueue() {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs.list,
    refetchInterval: (query) => (query.state.data?.runs.some((r) => isActive(r.status)) ? 3000 : 15000),
  });
  const kometa = useQuery({
    queryKey: ["kometa"],
    queryFn: api.kometa,
    // The --help probe takes a few seconds after Studio starts.
    refetchInterval: (query) => (query.state.data && query.state.data.flags === null && !query.state.data.flags_error ? 2000 : false),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["runs"] });
  const cancel = useMutation({ mutationFn: api.runs.cancel, onSuccess: refresh });

  const all = runs.data?.runs ?? [];
  const running = all.find((r) => r.status === "running");
  const queued = all.filter((r) => r.status === "queued");
  const finished = all.filter((r) => !isActive(r.status));

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <RunForm kometa={kometa.data} onQueued={refresh} />

      <Card
        title={running ? `Running: ${describeRequest(running.request)}` : "Running"}
        actions={
          running && (
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted">{formatDuration(running.started_at, null)}</span>
              {/* The run's own page keeps the log once the run is over. */}
              <Link to={`/activity/queue/${running.id}`} className="min-h-11 content-center text-sm underline">
                Details
              </Link>
              <Button onClick={() => cancel.mutate(running.id)} disabled={cancel.isPending}>
                Cancel
              </Button>
            </div>
          )
        }
      >
        {runs.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : runs.isError ? (
          <p role="alert" className="text-err">
            Can't reach the Studio API: {runs.error.message}
          </p>
        ) : running ? (
          <RunLog key={running.id} runId={running.id} onEnd={refresh} />
        ) : (
          <p className="text-muted">Nothing is running.</p>
        )}
        {queued.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold">Waiting</h3>
            <ul>
              {queued.map((run) => (
                <li key={run.id} className="flex min-h-11 items-center justify-between gap-3 border-b border-border py-2 last:border-0">
                  <span className="min-w-0 truncate text-sm">
                    <span className="text-muted">#{run.id}</span> {describeRequest(run.request)}
                  </span>
                  <Button onClick={() => cancel.mutate(run.id)}>Remove</Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <Card title="Recent runs">
        {runs.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : finished.length === 0 ? (
          <p className="text-muted">{runs.isError ? "Can't load runs." : "No runs yet."}</p>
        ) : (
          <ul>
            {finished.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
