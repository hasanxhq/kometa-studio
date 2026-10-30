// Overlays (feedback round 1): Kometa's overlays per library. What draws them, when (schedules and
// imports), Kometa's Original Posters backup, Maintainerr's overlays on top, and turning them off and on.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, type ArrState, type OverlayLibrary, type RunRequest, type Schedule } from "../api";
import { Button, Card, ConfirmButton, Field, Tag, inputClass } from "../components/ui";
import { describeDays, formatRelative, statusLabels, statusTones } from "../runs";

const blank: RunRequest = {
  mode: "overlays",
  libraries: [],
  collections: [],
  files: [],
  ignore_schedules: false,
  no_missing: false,
  tests: false,
  timings: false,
  low_priority: true,
};

function size(bytes: number): string {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

/** Whether a run request draws this library's overlays. */
function drawsOverlays(request: RunRequest, library: string): boolean {
  return (request.mode === "all" || request.mode === "overlays") && request.collections.length === 0 && (request.libraries.length === 0 || request.libraries.includes(library));
}

function Files({ library }: { library: OverlayLibrary }) {
  if (library.files.length === 0)
    return (
      <p className="text-sm text-muted">
        No overlay files.{" "}
        <Link className="text-accent underline" to={`/libraries/${encodeURIComponent(library.library)}?tab=overlays`}>
          Add some in Libraries → {library.library}
        </Link>
        .
      </p>
    );
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {library.files.map((reference, index) => (
        <li key={index} className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-mono text-xs text-muted">
            {reference.kind}: {reference.value}
          </span>
          {reference.error && <span className="text-xs text-warn">{reference.error}</span>}
          {reference.files.map((file) => (
            <span key={file.path}>
              {file.docs_url ? (
                <a className="underline" href={file.docs_url} target="_blank" rel="noreferrer">
                  {file.title ?? file.path}
                </a>
              ) : (
                (file.title ?? `${file.overlays.length} overlay${file.overlays.length === 1 ? "" : "s"}`)
              )}
              {file.overlays.length > 0 && !file.docs_url && <span className="text-muted">: {file.overlays.slice(0, 6).join(", ")}{file.overlays.length > 6 ? ", …" : ""}</span>}
            </span>
          ))}
        </li>
      ))}
      <li>
        <Link className="text-sm text-accent underline" to={`/libraries/${encodeURIComponent(library.library)}?tab=overlays`}>
          Edit them in Libraries → {library.library}
        </Link>
      </li>
    </ul>
  );
}

function Schedules({ library, schedules }: { library: string; schedules: Schedule[] }) {
  const queryClient = useQueryClient();
  const [time, setTime] = useState("04:00");
  const add = useMutation({
    mutationFn: () =>
      api.schedules.create({
        name: `Overlays · ${library}`,
        request: { ...blank, libraries: [library] },
        days: [0, 1, 2, 3, 4, 5, 6],
        time,
        timezone: null,
        enabled: true,
        catch_up: "run_once",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const mine = schedules.filter((schedule) => drawsOverlays(schedule.request, library));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };
  return (
    <div className="flex flex-col gap-2 text-sm">
      {mine.length === 0 ? (
        <p className="text-muted">No schedule draws overlays here.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {mine.map((schedule) => (
            <li key={schedule.id}>
              <span className="font-semibold">{schedule.name}</span>{" "}
              <span className="text-muted">
                {describeDays(schedule.days)} at {schedule.time}
                {schedule.request.mode === "all" ? " (everything)" : ""}
                {!schedule.enabled ? " · paused" : schedule.next_run ? ` · next ${formatRelative(schedule.next_run)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-end gap-2" onSubmit={submit} aria-label={`Daily overlay pass for ${library}`}>
        <Field label="Daily overlay pass at">
          <input type="time" className={`${inputClass} w-32`} value={time} onChange={(e) => setTime(e.target.value)} required />
        </Field>
        <Button type="submit" disabled={add.isPending}>
          Add
        </Button>
        <Link className="min-h-11 content-center text-muted underline" to="/system/tasks">
          All schedules
        </Link>
        {add.isError && (
          <span role="alert" className="text-err">
            {add.error.message}
          </span>
        )}
      </form>
    </div>
  );
}

function Imports({ library, arr }: { library: string; arr: ArrState | undefined }) {
  if (!arr) return null;
  const lines = (["radarr", "sonarr"] as const)
    .filter((kind) => arr.settings[kind].enabled && drawsOverlays({ ...blank, mode: arr.settings[kind].mode, libraries: arr.settings[kind].libraries }, library))
    .map((kind) => `${kind === "radarr" ? "Radarr" : "Sonarr"} imports (${arr.settings[kind].trigger === "relevant" ? "those that matter" : "every one"})`);
  return (
    <p className="text-sm text-muted">
      {lines.length ? `Also drawn after ${lines.join(" and ")}. ` : "Not drawn after imports. "}
      <Link className="underline" to="/settings/connect">
        Settings → Connect
      </Link>
    </p>
  );
}

function LibraryCard({ library, schedules, arr }: { library: OverlayLibrary; schedules: Schedule[]; arr: ArrState | undefined }) {
  const queryClient = useQueryClient();
  const [queued, setQueued] = useState<number | null>(null);
  const done = ({ run_id }: { run_id: number }) => {
    setQueued(run_id);
    queryClient.invalidateQueries({ queryKey: ["overlays"] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
  const apply = useMutation({ mutationFn: () => api.overlays.apply(library.library), onSuccess: done });
  const off = useMutation({ mutationFn: () => api.overlays.off(library.library), onSuccess: done });
  const on = useMutation({ mutationFn: () => api.overlays.on(library.library), onSuccess: done });
  const error = apply.error ?? off.error ?? on.error;
  const state = library.off ? <Tag tone="warn">Off</Tag> : library.files.length ? <Tag tone="ok">On</Tag> : <Tag>None</Tag>;

  return (
    <Card title={library.library} actions={state}>
      <div className="flex flex-col gap-4">
        {library.off && (
          <p className="text-sm text-warn">
            Turned off: Kometa keeps the original posters here and draws none (remove_overlays is set in config.yml).
          </p>
        )}
        <Files library={library} />
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted">Last overlay pass</dt>
          <dd>
            {library.last_pass ? (
              <Link className="underline" to={`/activity/queue/${library.last_pass.run_id}`}>
                <Tag tone={statusTones[library.last_pass.status]}>{statusLabels[library.last_pass.status]}</Tag>
                {library.last_pass.finished_at ? ` ${formatRelative(library.last_pass.finished_at)}` : ""}
              </Link>
            ) : (
              <span className="text-muted">None yet</span>
            )}
          </dd>
          <dt className="text-muted">Original Posters</dt>
          <dd>
            {library.backup && library.backup.posters > 0 ? (
              `${library.backup.posters} poster${library.backup.posters === 1 ? "" : "s"} backed up (${size(library.backup.bytes)})`
            ) : (
              <span className="text-muted">No backup yet: Kometa makes one the first time it draws overlays here.</span>
            )}
          </dd>
          {library.maintainerr && (
            <>
              <dt className="text-muted">Maintainerr</dt>
              <dd className={library.maintainerr.on_top ? "" : "text-warn"}>
                {library.maintainerr.on_top
                  ? `Its overlays go on top of Kometa's (${library.maintainerr.collections.join(", ")}).`
                  : `Has overlays here (${library.maintainerr.collections.join(", ")}). Turn on “Leave Maintainerr overlays alone” in Settings → Connect so they go on top.`}
              </dd>
            </>
          )}
        </dl>
        {library.files.length > 0 && !library.off && (
          <>
            <Schedules library={library.library} schedules={schedules} />
            <Imports library={library.library} arr={arr} />
          </>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {!library.off && library.files.length > 0 && (
            <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending}>
              Apply now
            </Button>
          )}
          {library.off ? (
            <Button onClick={() => on.mutate()} disabled={on.isPending}>
              Turn overlays on
            </Button>
          ) : (
            library.files.length > 0 && (
              <ConfirmButton
                label="Turn overlays off"
                confirm={`Take them off ${library.library}`}
                warning={
                  library.maintainerr?.on_top
                    ? "Kometa puts the original posters back; Maintainerr's go back on top after."
                    : "Kometa puts the original posters back from its backup."
                }
                onConfirm={() => off.mutate()}
                busy={off.isPending}
              />
            )
          )}
          {queued !== null && (
            <span role="status" className="text-sm text-ok">
              Queued as{" "}
              <Link className="underline" to={`/activity/queue/${queued}`}>
                run #{queued}
              </Link>
            </span>
          )}
          {error && (
            <span role="alert" className="text-sm text-err">
              {error.message}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}

export function Overlays() {
  const overlays = useQuery({ queryKey: ["overlays"], queryFn: api.overlays.list });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules.list });
  const arr = useQuery({ queryKey: ["arr"], queryFn: api.arr.get });
  if (overlays.isPending) return <p className="text-muted">Loading…</p>;
  if (overlays.isError)
    return (
      <p role="alert" className="text-err">
        {overlays.error.message}
      </p>
    );
  if (overlays.data.libraries.length === 0) return <p className="text-muted">No libraries in config.yml yet.</p>;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-muted">
        Kometa's overlays, library by library. A pass only redraws posters whose overlay changed, but it reads every item, which takes a while against a
        remote Plex. Overlay runs never touch collections.
      </p>
      {overlays.data.libraries.map((library) => (
        <LibraryCard key={library.library} library={library} schedules={schedules.data?.schedules ?? []} arr={arr.data} />
      ))}
    </div>
  );
}
