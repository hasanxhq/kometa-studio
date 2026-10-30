// Settings → Connect: services Studio talks to. Radarr and Sonarr, for runs after imports (handoff v2 §4.5, §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  api,
  type ArrConnection,
  type ArrConnectionInput,
  type ArrKind,
  type ArrSettings,
  type ArrSource,
  type ArrState,
  type MaintainerrState,
  type RunMode,
} from "../api";
import { Button, Card, Field, inputClass } from "../components/ui";
import { formatRelative, formatTime, modes } from "../runs";

const apps: { kind: ArrKind; label: string }[] = [
  { kind: "radarr", label: "Radarr" },
  { kind: "sonarr", label: "Sonarr" },
];

function ArrConnectionForm({ kind, label, connection }: { kind: ArrKind; label: string; connection: ArrConnection }) {
  const queryClient = useQueryClient();
  const [source, setSource] = useState<ArrSource>(connection.source);
  const [url, setUrl] = useState(connection.url ?? "");
  const [apiKey, setApiKey] = useState("");
  const body = (): ArrConnectionInput => (source === "studio" ? { source, url, api_key: apiKey || null } : { source });
  const test = useMutation({ mutationFn: () => api.arr.test(kind, body()) });
  const save = useMutation({
    mutationFn: () => api.arr.connect(kind, body()),
    onSuccess: (data) => {
      queryClient.setQueryData(["arr"], data);
      setApiKey("");
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const status = connection.status;
  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label={label}>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-sm font-semibold">{label}</legend>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" className="accent-accent" checked={source === "config"} onChange={() => setSource("config")} />
          <span>
            Kometa's, from config.yml <span className="font-mono text-xs text-muted">{connection.config_url ?? "(config.yml has no url and token)"}</span>
          </span>
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" className="accent-accent" checked={source === "studio"} onChange={() => setSource("studio")} />
          Enter it here
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="radio" className="accent-accent" checked={source === "off"} onChange={() => setSource("off")} />
          Don't use {label}
        </label>
      </fieldset>
      {source === "studio" && (
        <div className="flex flex-wrap gap-3">
          <div className="min-w-0 flex-1 basis-64">
            <Field label="URL">
              <input
                className={inputClass}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={kind === "radarr" ? "http://radarr:7878" : "http://sonarr:8989"}
              />
            </Field>
          </div>
          <div className="min-w-0 flex-1 basis-64">
            <Field label="API key" hint={`${label} → Settings → General → API Key`}>
              <input
                className={inputClass}
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={connection.has_key ? "Saved (leave empty to keep it)" : ""}
              />
            </Field>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          Save
        </Button>
        {source !== "off" && (
          <Button onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? "Testing…" : "Test"}
          </Button>
        )}
        {test.data &&
          (test.data.ok ? (
            <span role="status" className="text-sm text-ok">
              {test.data.app} {test.data.version} answered.
            </span>
          ) : (
            <span role="alert" className="text-sm text-err">
              {test.data.error}
            </span>
          ))}
        {save.isError && (
          <span role="alert" className="text-sm text-err">
            {save.error.message}
          </span>
        )}
      </div>
      {status && (
        <p className={`text-xs ${status.ok ? "text-muted" : "text-warn"}`}>
          {status.ok ? `Imports checked ${formatRelative(status.checked_at)}.` : `Last check failed (${formatRelative(status.checked_at)}): ${status.error}`}
        </p>
      )}
    </form>
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
                  <input
                    type="checkbox"
                    className="size-4 accent-accent"
                    checked={draft.libraries[kind].includes(name)}
                    onChange={() => toggleLibrary(kind, name)}
                  />
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

function Pending({ state }: { state: ArrState }) {
  const { pending } = state;
  if (!pending) return null;
  return (
    <p role="status" className="text-sm text-info">
      {pending.imports} import{pending.imports === 1 ? "" : "s"} waiting ({pending.titles.join(", ")}). Kometa runs{" "}
      <span title={formatTime(pending.due_at)}>{formatRelative(pending.due_at)}</span> unless more arrive.
    </p>
  );
}

function MaintainerrForm({ current }: { current: MaintainerrState }) {
  const queryClient = useQueryClient();
  const [draftUrl, setUrl] = useState(current.url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [draftLeave, setLeaveOverlays] = useState(current.leave_overlays_alone);
  const test = useMutation({ mutationFn: () => api.maintainerr.test(draftUrl, apiKey || null) });
  const save = useMutation({
    mutationFn: (disconnect: boolean) =>
      api.maintainerr.save(
        disconnect
          ? { url: null, api_key: "", leave_overlays_alone: draftLeave }
          : { url: draftUrl, api_key: apiKey || null, leave_overlays_alone: draftLeave },
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["maintainerr"], data);
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["plex"] });
      setUrl(data.url ?? "");
      setApiKey("");
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(false);
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Maintainerr">
      <p className="text-sm text-muted">
        With Maintainerr connected, Kometa leaves its collections alone: Studio refuses any change, and holds any run, that would let Kometa delete them, change
        their mode, or take one over with a collection of the same name.
      </p>
      <div className="flex flex-wrap gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <Field label="URL">
            <input className={inputClass} value={draftUrl} onChange={(e) => setUrl(e.target.value)} placeholder="http://maintainerr:6246" />
          </Field>
        </div>
        <div className="min-w-0 flex-1 basis-48">
          <Field label="API key (if it has one)">
            <input
              className={inputClass}
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={current.has_key ? "Saved (leave empty to keep it)" : ""}
            />
          </Field>
        </div>
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1 size-4 accent-accent" checked={draftLeave} onChange={(e) => setLeaveOverlays(e.target.checked)} />
        <span>
          Leave Maintainerr overlays alone
          <span className="block text-xs text-muted">
            Maintainerr's overlays take precedence over Kometa's. Before a Kometa run that can change posters, Maintainerr puts back the posters under its
            overlays; afterwards it draws them again, on top of Kometa's. Kometa never sees a countdown, so it can't keep one as an item's original poster. If
            Maintainerr doesn't answer, those runs wait.
          </span>
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={save.isPending || !draftUrl}>
          Save
        </Button>
        <Button onClick={() => test.mutate()} disabled={test.isPending || !draftUrl}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        {current.url && <Button onClick={() => save.mutate(true)}>Disconnect</Button>}
        {test.data &&
          (test.data.ok ? (
            <span role="status" className="text-sm text-ok">
              Maintainerr answered: {test.data.collections} collection{test.data.collections === 1 ? "" : "s"}, overlays{" "}
              {test.data.overlays_enabled ? "on" : "off"}.
            </span>
          ) : (
            <span role="alert" className="text-sm text-err">
              {test.data.error}
            </span>
          ))}
        {save.isError && (
          <span role="alert" className="text-sm text-err">
            {save.error.message}
          </span>
        )}
      </div>
      {current.url && (
        <div className="flex flex-col gap-2 text-sm">
          {current.error && <p className="text-warn">Can't read Maintainerr: {current.error}</p>}
          {current.risks.length > 0 && (
            <div role="alert" className="rounded-control border border-err/40 p-3">
              <p className="font-semibold text-err">Kometa's config would touch Maintainerr's collections</p>
              <p className="text-xs text-muted">Runs that would do this are held until it's fixed.</p>
              <ul className="mt-2 list-disc pl-5">
                {current.risks.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-muted">
            Protecting {current.collections.length} collection{current.collections.length === 1 ? "" : "s"}
            {current.collections.length > 0 ? ":" : "."}
          </p>
          {current.collections.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {current.collections.map((c) => (
                <li key={`${c.library}/${c.title}`} className="rounded border border-border px-2 py-1 text-xs">
                  {c.title} <span className="text-muted">· {c.library ?? "unknown library"}</span>
                  {c.overlays && current.overlays_enabled && <span className="text-info"> · overlays</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </form>
  );
}

function MaintainerrCard() {
  const state = useQuery({ queryKey: ["maintainerr"], queryFn: api.maintainerr.get });
  return (
    <Card title="Maintainerr">
      {state.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : state.isError ? (
        <p role="alert" className="text-err">
          {state.error.message}
        </p>
      ) : (
        <MaintainerrForm current={state.data} />
      )}
    </Card>
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
              When Radarr or Sonarr imports a movie or episode, Kometa can run for its library, so new items get their overlays and join their collections
              without waiting for the next schedule. Studio checks their import history every 2 minutes, so they don't need to reach Studio.
            </p>
            {apps.map(({ kind, label }) => (
              <ArrConnectionForm
                key={`${kind}-${arr.data.connections[kind].source}-${arr.data.connections[kind].url}`}
                kind={kind}
                label={label}
                connection={arr.data.connections[kind]}
              />
            ))}
            <ArrForm key={JSON.stringify(arr.data.settings)} state={arr.data} libraries={libraries} />
            <Pending state={arr.data} />
          </div>
        )}
      </Card>
      <MaintainerrCard />
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
