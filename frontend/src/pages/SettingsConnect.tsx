// Settings → Connect: services that talk to Studio. For now, Radarr and Sonarr's import webhook (handoff v2 §4.5, §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, type ArrKind, type ArrSettings, type ArrState, type RunMode } from "../api";
import { Button, Card, Field, inputClass } from "../components/ui";
import { formatRelative, formatTime, modes } from "../runs";

const apps: { kind: ArrKind; label: string }[] = [
  { kind: "radarr", label: "Radarr" },
  { kind: "sonarr", label: "Sonarr" },
];

function WebhookAddress({ state }: { state: ArrState }) {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const renew = useMutation({
    mutationFn: api.arr.newToken,
    onSuccess: (data) => {
      queryClient.setQueryData(["arr"], data);
      setConfirming(false);
    },
  });
  const url = `${window.location.origin}${state.path}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // no clipboard over plain http: the field is selectable
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${inputClass} min-w-0 flex-1`} value={url} readOnly aria-label="Webhook URL" onFocus={(e) => e.target.select()} />
        <Button onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
        {confirming ? (
          <>
            <Button className="border-err/60 text-err" onClick={() => renew.mutate()}>
              Replace it
            </Button>
            <Button onClick={() => setConfirming(false)}>Keep</Button>
          </>
        ) : (
          <Button onClick={() => setConfirming(true)}>New URL</Button>
        )}
      </div>
      {confirming && <p className="text-sm text-warn">Radarr and Sonarr stop reaching Studio until you paste the new URL into them.</p>}
      <p className="text-xs text-muted">
        In Radarr and Sonarr: Settings → Connect → + → Webhook. Paste this URL, keep the method POST, and tick On Import and On Upgrade. If
        they reach Studio at a different address than this browser does, change the start of the URL to match. Test sends an event that
        shows below.
      </p>
    </div>
  );
}

function ArrForm({ state, libraries }: { state: ArrState; libraries: string[] }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ArrSettings>(state.settings);
  const save = useMutation({ mutationFn: () => api.arr.save(draft), onSuccess: (data) => queryClient.setQueryData(["arr"], data) });
  const toggleLibrary = (kind: ArrKind, name: string) => {
    const current = draft.libraries[kind];
    const next = current.includes(name) ? current.filter((n) => n !== name) : [...current, name];
    setDraft({ ...draft, libraries: { ...draft.libraries, [kind]: next } });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Runs after imports">
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input type="checkbox" className="size-4 accent-accent" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
        Run Kometa after Radarr or Sonarr imports something
      </label>
      <div className="flex flex-wrap gap-4">
        <Field label="Run">
          <select className={`${inputClass} w-48`} value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as RunMode })}>
            {modes.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.value === "all" ? mode.label : `${mode.label} only`}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Once imports stop for (minutes)" hint="A season pack sends many imports; Kometa runs once, at most an hour after the first.">
          <input
            type="number"
            min={1}
            max={240}
            className={`${inputClass} w-28`}
            value={draft.wait_minutes}
            onChange={(e) => setDraft({ ...draft, wait_minutes: Number(e.target.value) })}
          />
        </Field>
      </div>
      {apps.map(({ kind, label }) => (
        <fieldset key={kind}>
          <legend className="mb-1.5 text-sm text-muted">Libraries to run for {label}'s imports</legend>
          {libraries.length === 0 ? (
            <p className="text-sm text-muted">No libraries in config.yml yet, so Kometa runs for all of them.</p>
          ) : (
            <div className="flex flex-wrap gap-x-4">
              {libraries.map((name) => (
                <label key={name} className="flex min-h-11 items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-accent" checked={draft.libraries[kind].includes(name)} onChange={() => toggleLibrary(kind, name)} />
                  {name}
                </label>
              ))}
            </div>
          )}
          {libraries.length > 0 && draft.libraries[kind].length === 0 && <p className="text-xs text-muted">None ticked: Kometa runs for every library.</p>}
        </fieldset>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={save.isPending}>
          Save
        </Button>
        {save.isError && (
          <span role="alert" className="text-sm text-err">
            {save.error.message}
          </span>
        )}
        {save.isSuccess && (
          <span role="status" className="text-sm text-ok">
            Saved.
          </span>
        )}
      </div>
    </form>
  );
}

function Activity({ state }: { state: ArrState }) {
  const { last_event: last, pending } = state;
  return (
    <div className="flex flex-col gap-1 text-sm">
      {pending && (
        <p role="status" className="text-info">
          {pending.imports} import{pending.imports === 1 ? "" : "s"} waiting ({pending.titles.join(", ")}). Kometa runs{" "}
          <span title={formatTime(pending.due_at)}>{formatRelative(pending.due_at)}</span> unless more arrive.
        </p>
      )}
      <p className="text-muted">
        {last
          ? `Last heard from ${last.kind === "sonarr" ? "Sonarr" : last.kind === "radarr" ? "Radarr" : "an app"} ${formatRelative(last.at)}: ${last.event === "Test" ? "a test" : last.event}${last.title && last.event !== "Test" ? `, ${last.title}` : ""}.`
          : "Nothing received yet."}
      </p>
    </div>
  );
}

export function SettingsConnect() {
  const arr = useQuery({ queryKey: ["arr"], queryFn: api.arr.get, refetchInterval: 30_000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const libraries = config.data?.libraries.map((library) => library.name) ?? [];

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Radarr and Sonarr">
        {arr.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : arr.isError ? (
          <p role="alert" className="text-err">
            {arr.error.message}
          </p>
        ) : (
          <div className="flex flex-col gap-5">
            <p className="text-sm text-muted">
              When Radarr or Sonarr imports a movie or episode, Kometa can run for its library, so new items get their overlays and join their
              collections without waiting for the next schedule.
            </p>
            <WebhookAddress state={arr.data} />
            <ArrForm key={JSON.stringify(arr.data.settings)} state={arr.data} libraries={libraries} />
            <Activity state={arr.data} />
          </div>
        )}
      </Card>
      <Card title="TMDb, Trakt and other services">
        <p className="text-sm text-muted">
          Kometa's own connections (TMDb, Trakt, MDBList, Radarr and Sonarr for adding items, notifications) are set in{" "}
          <Link to="/files?path=config.yml" className="underline">
            config.yml
          </Link>
          . System → Status's full check tests every one of them.
        </p>
      </Card>
    </div>
  );
}
