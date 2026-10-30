// Studio's built-in tasks (full backup, full check): when they run, how they last went, and Run now.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, type BuiltinTask, type BuiltinTaskInput } from "../api";
import { describeDays, dayNames, formatRelative, formatTime } from "../runs";
import { Button, Field, Tag, inputClass, type Tone } from "./ui";

const lastTones: Record<NonNullable<BuiltinTask["last"]>["status"], Tone> = {
  running: "info",
  succeeded: "ok",
  failed: "err",
  interrupted: "warn",
};

const lastLabels: Record<NonNullable<BuiltinTask["last"]>["status"], string> = {
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  interrupted: "Interrupted",
};

const descriptions: Record<BuiltinTask["name"], string> = {
  full_backup: "A zip of Kometa's config folder, including the Original Posters, and Studio's database. Waits while Kometa runs.",
  full_check: "Kometa reads the whole config and connects to Plex and every service in it. Changes nothing.",
};

/** Polls while a task runs, so its outcome shows when it ends. */
export function useBuiltinTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks.list,
    refetchInterval: (query) => (query.state.data?.tasks.some((t) => t.running) ? 2000 : 30_000),
  });
}

function TaskForm({ task, onDone }: { task: BuiltinTask; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<BuiltinTaskInput>({
    enabled: task.enabled,
    days: task.days,
    time: task.time,
    timezone: null, // Settings → General
    options: task.options,
  });
  const save = useMutation({
    mutationFn: () => api.tasks.update(task.name, draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onDone();
    },
  });
  const toggleDay = (day: number) =>
    setDraft({ ...draft, days: draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day].sort() });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <form className="flex flex-col gap-4 rounded-control border border-accent/60 p-4" onSubmit={submit} aria-label={`Edit ${task.label}`}>
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input type="checkbox" className="size-4 accent-accent" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
        Run on a schedule
      </label>
      <fieldset>
        <legend className="mb-1.5 text-sm text-muted">Days</legend>
        <div className="flex flex-wrap gap-2">
          {dayNames.map((name, day) => (
            <label
              key={name}
              className={[
                "flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded-control border px-2 text-sm",
                draft.days.includes(day) ? "border-accent bg-surface-2 text-accent" : "border-border-strong",
              ].join(" ")}
            >
              <input type="checkbox" className="sr-only" checked={draft.days.includes(day)} onChange={() => toggleDay(day)} />
              {name}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-4">
        <Field label="Time" hint={`In ${task.timezone} (Settings → General).`}>
          <input type="time" className={`${inputClass} w-40`} value={draft.time} onChange={(e) => setDraft({ ...draft, time: e.target.value })} required />
        </Field>
        {task.name === "full_backup" && (
          <Field label="Backups to keep">
            <input
              type="number"
              min={1}
              max={100}
              className={`${inputClass} w-28`}
              value={draft.options.keep ?? 4}
              onChange={(e) => setDraft({ ...draft, options: { keep: Number(e.target.value) } })}
            />
          </Field>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={save.isPending || draft.days.length === 0}>
          Save
        </Button>
        <Button onClick={onDone}>Cancel</Button>
        {save.isError && (
          <span role="alert" className="text-sm text-err">
            {save.error.message}
          </span>
        )}
      </div>
    </form>
  );
}

export function BuiltinTaskRow({ task }: { task: BuiltinTask }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const run = useMutation({ mutationFn: () => api.tasks.run(task.name), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }) });
  if (editing) {
    return (
      <li className="py-4">
        <TaskForm task={task} onDone={() => setEditing(false)} />
      </li>
    );
  }
  const status = task.running ? "running" : task.last?.status;
  return (
    <li className="flex flex-col gap-3 border-b border-border py-4 last:border-0 md:grid md:grid-cols-[minmax(0,1fr)_15rem_14rem] md:items-center md:gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{task.label}</span>
          {!task.enabled && <Tag>Off</Tag>}
        </div>
        <div className="text-sm text-muted">{task.enabled ? `${describeDays(task.days)} at ${task.time} (${task.timezone})` : "Only when you run it"}</div>
        <div className="text-xs text-muted">{descriptions[task.name]}</div>
      </div>
      <dl className="grid grid-cols-[5rem_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">Next run</dt>
        <dd>{task.next_run ? <span title={formatTime(task.next_run)}>{formatRelative(task.next_run)}</span> : "–"}</dd>
        <dt className="text-muted">Last run</dt>
        <dd className="min-w-0">
          {status ? (
            <span className="flex flex-col gap-0.5">
              <span>
                <Tag tone={lastTones[status]}>{lastLabels[status]}</Tag>{" "}
                {task.last?.finished_at && <span className="text-xs text-muted">{formatRelative(task.last.finished_at)}</span>}
              </span>
              {task.last?.message && !task.running && <span className="break-words text-xs text-muted">{task.last.message}</span>}
            </span>
          ) : (
            "Never"
          )}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-2 md:justify-end">
        <Button onClick={() => run.mutate()} disabled={task.running || run.isPending}>
          {task.running ? "Running…" : "Run now"}
        </Button>
        <Button onClick={() => setEditing(true)}>Edit</Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-err md:col-span-3">
          {run.error.message}
        </p>
      )}
    </li>
  );
}
