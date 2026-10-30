// System → Tasks: schedules, arr-style, with next run, last run and Run now (handoff v2 §6, §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useAdvanced } from "../advanced";
import { api, type KometaInfo, type Schedule, type ScheduleInput } from "../api";
import { RunRequestFields, draftFromRequest, emptyDraft, requestFromDraft, type RunDraft } from "../components/RunRequestFields";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";
import { dayNames, describeDays, describeRequest, formatRelative, formatTime, statusLabels, statusTones, triggerLabels } from "../runs";

type Draft = { name: string; run: RunDraft; days: number[]; time: string; timezone: string; catch_up: Schedule["catch_up"]; enabled: boolean };

const presets: { label: string; days: number[] }[] = [
  { label: "Every day", days: [0, 1, 2, 3, 4, 5, 6] },
  { label: "Weekdays", days: [0, 1, 2, 3, 4] },
  { label: "Weekends", days: [5, 6] },
];

const timezones: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
})();

function draftFrom(schedule: Schedule | null, defaultTimezone: string): Draft {
  if (!schedule) {
    return { name: "", run: emptyDraft, days: presets[0].days, time: "03:00", timezone: defaultTimezone, catch_up: "run_once", enabled: true };
  }
  return {
    name: schedule.name,
    run: draftFromRequest(schedule.request),
    days: schedule.days,
    time: schedule.time,
    timezone: schedule.timezone,
    catch_up: schedule.catch_up,
    enabled: schedule.enabled,
  };
}

function ScheduleForm({
  schedule,
  defaultTimezone,
  kometa,
  onDone,
}: {
  schedule: Schedule | null; // null: a new one
  defaultTimezone: string;
  kometa: KometaInfo | undefined;
  onDone: () => void;
}) {
  const { showAdvanced } = useAdvanced();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(schedule, defaultTimezone));
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const save = useMutation({
    mutationFn: (body: ScheduleInput) => (schedule ? api.schedules.update(schedule.id, body) : api.schedules.create(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      onDone();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate({
      name: draft.name,
      // A schedule keeps its advanced options even while Show Advanced hides them.
      request: requestFromDraft(draft.run, true),
      days: draft.days,
      time: draft.time,
      timezone: draft.timezone,
      catch_up: draft.catch_up,
      enabled: draft.enabled,
    });
  };
  const toggleDay = (day: number) =>
    set({ days: draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day].sort() });

  return (
    <form className="flex flex-col gap-4 rounded-control border border-accent/60 p-4" onSubmit={submit} aria-label={schedule ? `Edit ${schedule.name}` : "New schedule"}>
      <Field label="Name">
        <input className={inputClass} value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="Nightly collections" required />
      </Field>
      <RunRequestFields value={draft.run} onChange={(run) => set({ run })} kometa={kometa} keepsHiddenOptions />
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
        <div className="mt-1 flex flex-wrap gap-x-4 text-sm">
          {presets.map((preset) => (
            <button key={preset.label} type="button" className="min-h-11 text-muted underline hover:text-text" onClick={() => set({ days: preset.days })}>
              {preset.label}
            </button>
          ))}
        </div>
      </fieldset>
      <Field label="Time">
        <input type="time" className={`${inputClass} w-40`} value={draft.time} onChange={(e) => set({ time: e.target.value })} required />
      </Field>
      {showAdvanced ? (
        <>
          <Field label="Timezone" hint="The time above is in this timezone. Daylight saving changes are handled.">
            <input className={inputClass} list="studio-timezones" value={draft.timezone} onChange={(e) => set({ timezone: e.target.value })} />
          </Field>
          <datalist id="studio-timezones">
            {timezones.map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
          <Field label="If Studio was off when this was due">
            <select className={inputClass} value={draft.catch_up} onChange={(e) => set({ catch_up: e.target.value as Draft["catch_up"] })}>
              <option value="run_once">Run it once when Studio starts again (within 24 hours)</option>
              <option value="skip">Skip it and wait for the next time</option>
            </select>
          </Field>
        </>
      ) : (
        <p className="text-sm text-muted">
          At {draft.time} {draft.timezone}. {draft.catch_up === "run_once" ? "Missed runs are made up once when Studio starts again." : "Missed runs are skipped."}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={save.isPending || draft.days.length === 0}>
          {save.isPending ? "Saving…" : schedule ? "Save" : "Add schedule"}
        </Button>
        <Button onClick={onDone}>Cancel</Button>
        {draft.days.length === 0 && <span className="text-sm text-warn">Pick at least one day.</span>}
        {save.isError && (
          <span role="alert" className="text-sm text-err">
            {save.error.message}
          </span>
        )}
      </div>
    </form>
  );
}

function ScheduleRow({ schedule, onEdit }: { schedule: Schedule; onEdit: () => void }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["schedules"] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
  };
  const runNow = useMutation({ mutationFn: () => api.schedules.run(schedule.id), onSuccess: refresh });
  const toggle = useMutation({
    mutationFn: () => api.schedules.update(schedule.id, { ...schedule, enabled: !schedule.enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: () => api.schedules.remove(schedule.id), onSuccess: refresh });
  const last = schedule.last_run;

  return (
    // A fixed grid on wider screens, so the run columns line up from row to row.
    <li className="flex flex-col gap-3 border-b border-border py-4 last:border-0 md:grid md:grid-cols-[minmax(0,1fr)_15rem_22rem] md:items-center md:gap-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{schedule.name}</span>
          {!schedule.enabled && <Tag>Paused</Tag>}
        </div>
        <div className="text-sm text-muted">
          {describeRequest(schedule.request)} · {describeDays(schedule.days)} at {schedule.time}
        </div>
      </div>
      <dl className="grid grid-cols-[6rem_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">Next run</dt>
        <dd>{schedule.next_run ? <span title={formatTime(schedule.next_run)}>{formatRelative(schedule.next_run)}</span> : "–"}</dd>
        <dt className="text-muted">Last run</dt>
        <dd>
          {last ? (
            <Link to={`/activity/queue/${last.id}`} className="inline-flex items-center gap-1.5 underline-offset-2 hover:underline">
              <Tag tone={statusTones[last.status]}>{statusLabels[last.status]}</Tag>
              {last.trigger === "catch_up" && <span className="text-xs text-muted">{triggerLabels.catch_up}</span>}
            </Link>
          ) : (
            "Never"
          )}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-2 md:justify-end">
        <Button onClick={() => runNow.mutate()} disabled={runNow.isPending}>
          Run now
        </Button>
        <Button onClick={onEdit}>Edit</Button>
        <Button onClick={() => toggle.mutate()} disabled={toggle.isPending}>
          {schedule.enabled ? "Pause" : "Resume"}
        </Button>
        {confirming ? (
          <>
            <Button onClick={() => remove.mutate()} className="border-err/60 text-err">
              Delete it
            </Button>
            <Button onClick={() => setConfirming(false)}>Keep</Button>
          </>
        ) : (
          <Button onClick={() => setConfirming(true)}>Delete</Button>
        )}
      </div>
      {(runNow.isError || toggle.isError || remove.isError) && (
        <p role="alert" className="text-sm text-err md:col-span-3">
          {(runNow.error ?? toggle.error ?? remove.error)?.message}
        </p>
      )}
      {runNow.isSuccess && (
        <p role="status" className="text-sm text-ok md:col-span-3">
          Queued as <Link className="underline" to={`/activity/queue/${runNow.data.id}`}>run #{runNow.data.id}</Link>
        </p>
      )}
    </li>
  );
}

export function SystemTasks() {
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules.list, refetchInterval: 30_000 });
  const kometa = useQuery({ queryKey: ["kometa"], queryFn: api.kometa });
  const [editing, setEditing] = useState<number | "new" | null>(null);

  if (schedules.isPending) return <p className="text-muted">Loading…</p>;
  if (schedules.isError)
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {schedules.error.message}
      </p>
    );

  const { schedules: list, timezone, catch_ups } = schedules.data;
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      {catch_ups.length > 0 && (
        <section role="status" className="rounded-card border border-info/40 bg-surface p-4 text-sm">
          <p className="font-semibold text-info">Studio caught up on missed runs</p>
          <p className="mt-1 text-muted">Studio was off when these were due, so each ran once when it started again:</p>
          <ul className="mt-2 flex flex-col gap-1">
            {catch_ups.map((run) => (
              <li key={run.id}>
                {run.name}:{" "}
                <Link className="underline" to={`/activity/queue/${run.id}`}>
                  run #{run.id}
                </Link>{" "}
                <span className="text-muted">({statusLabels[run.status].toLowerCase()}, {formatTime(run.queued_at)})</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Card
        title="Schedules"
        actions={
          editing !== "new" && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              Add schedule
            </Button>
          )
        }
      >
        {editing === "new" && (
          <div className="mb-4">
            <ScheduleForm schedule={null} defaultTimezone={timezone} kometa={kometa.data} onDone={() => setEditing(null)} />
          </div>
        )}
        {list.length === 0 && editing !== "new" ? (
          <p className="text-muted">No schedules yet. Kometa only runs when you start it from the Queue.</p>
        ) : (
          <ul>
            {list.map((schedule) =>
              editing === schedule.id ? (
                <li key={schedule.id} className="py-4">
                  <ScheduleForm schedule={schedule} defaultTimezone={timezone} kometa={kometa.data} onDone={() => setEditing(null)} />
                </li>
              ) : (
                <ScheduleRow key={schedule.id} schedule={schedule} onEdit={() => setEditing(schedule.id)} />
              ),
            )}
          </ul>
        )}
      </Card>
    </div>
  );
}
