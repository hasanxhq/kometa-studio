// Settings → Connect: services Studio and Kometa talk to (handoff v2 §4.5, §8).
// Radarr, Sonarr and Maintainerr share one card; TMDb and MDBList have another. Every connection
// follows the same flow: enter it, Test, and only a passing test lets you Save (the server tests again).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import {
  api,
  type AppRuns,
  type ArrConnection,
  type ArrConnectionInput,
  type ArrKind,
  type ArrPending,
  type ArrState,
  type LibraryRelevance,
  type MaintainerrState,
  type RunMode,
  type ServiceName,
} from "../api";
import { Button, Card, ConfirmButton, Field, inputClass } from "../components/ui";
import { formatRelative, formatTime, modes } from "../runs";

const apps: { kind: ArrKind; label: string }[] = [
  { kind: "radarr", label: "Radarr" },
  { kind: "sonarr", label: "Sonarr" },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-4 border-t border-border pt-5 first:border-0 first:pt-0">
      <h3 className="font-display text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Checkbox({ checked, onChange, children }: { checked: boolean; onChange: (checked: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex min-h-11 items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1 size-4 shrink-0 accent-accent" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

function Outcome({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span role={ok ? "status" : "alert"} className={`text-sm ${ok ? "text-ok" : "text-err"}`}>
      {children}
    </span>
  );
}

// A username and password for a proxy in front of an app (HTTP Basic), as seedboxes put in front of each one.
function ProxyLogin({
  app,
  enabled,
  username,
  password,
  hasPassword,
  onEnabled,
  onUsername,
  onPassword,
}: {
  app: string;
  enabled: boolean;
  username: string;
  password: string;
  hasPassword: boolean;
  onEnabled: (value: boolean) => void;
  onUsername: (value: string) => void;
  onPassword: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Checkbox checked={enabled} onChange={onEnabled}>
        {app} is behind a proxy that asks for a login
        <span className="block text-xs text-muted">Seedboxes often put one in front of each app. Only Studio uses this login.</span>
      </Checkbox>
      {enabled && (
        <div className="flex flex-wrap gap-3">
          <div className="min-w-0 flex-1 basis-48">
            <Field label="Username">
              <input className={inputClass} autoComplete="off" value={username} onChange={(e) => onUsername(e.target.value)} />
            </Field>
          </div>
          <div className="min-w-0 flex-1 basis-48">
            <Field label="Password">
              <input
                className={inputClass}
                type="password"
                autoComplete="off"
                value={password}
                onChange={(e) => onPassword(e.target.value)}
                placeholder={hasPassword ? "Saved (leave empty to keep it)" : ""}
              />
            </Field>
          </div>
        </div>
      )}
    </div>
  );
}

// --- Radarr and Sonarr -------------------------------------------------------------

function ArrConnectionForm({ kind, label, connection }: { kind: ArrKind; label: string; connection: ArrConnection }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState(connection.url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [proxy, setProxy] = useState(connection.username !== null);
  const [username, setUsername] = useState(connection.username ?? "");
  const [password, setPassword] = useState("");
  const [root, setRoot] = useState(connection.root_folder_path ?? "");
  const [profile, setProfile] = useState(connection.quality_profile ?? "");
  const body = (): ArrConnectionInput => ({
    url,
    api_key: apiKey || null,
    username: proxy ? username || null : null,
    password: proxy ? password || null : null,
    root_folder_path: root || null,
    quality_profile: profile || null,
  });
  const test = useMutation({ mutationFn: () => api.arr.test(kind, body()) });
  const done = (data: Awaited<ReturnType<typeof api.arr.get>>) => {
    queryClient.setQueryData(["arr"], data);
    queryClient.invalidateQueries({ queryKey: ["status"] });
  };
  const save = useMutation({ mutationFn: () => api.arr.connect(kind, body()), onSuccess: done });
  const remove = useMutation({ mutationFn: () => api.arr.remove(kind), onSuccess: done });
  // Any change to how Studio reaches the app needs a new test.
  const changed = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    test.reset();
    save.reset();
  };
  const tested = test.data?.ok === true ? test.data : null;
  const ready = url.trim() !== "" && (apiKey !== "" || connection.token !== null);
  const options = (found: string[] | undefined, current: string) => (found ?? (current ? [current] : []));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (tested) save.mutate();
  };

  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label={`${label} connection`}>
      <div className="flex flex-wrap gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <Field label="URL">
            <input
              className={inputClass}
              value={url}
              onChange={(e) => changed(setUrl)(e.target.value)}
              placeholder={kind === "radarr" ? "http://radarr:7878" : "http://sonarr:8989"}
              inputMode="url"
              spellCheck={false}
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
              onChange={(e) => changed(setApiKey)(e.target.value)}
              placeholder={connection.token ? `Saved (${connection.token}), leave empty to keep it` : ""}
            />
          </Field>
        </div>
      </div>
      <ProxyLogin
        app={label}
        enabled={proxy}
        username={username}
        password={password}
        hasPassword={connection.has_password}
        onEnabled={changed(setProxy)}
        onUsername={changed(setUsername)}
        onPassword={changed(setPassword)}
      />
      <div className="flex flex-wrap gap-3">
        <div className="min-w-0 flex-1 basis-48">
          <Field label="Root folder" hint="Where Kometa adds missing items. Test to list them.">
            <select className={inputClass} value={root} onChange={(e) => setRoot(e.target.value)} disabled={!tested}>
              <option value="">(none)</option>
              {options(tested?.root_folders, root).map((path) => (
                <option key={path} value={path}>
                  {path}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="min-w-0 flex-1 basis-48">
          <Field label="Quality profile" hint="For items Kometa adds.">
            <select className={inputClass} value={profile} onChange={(e) => setProfile(e.target.value)} disabled={!tested}>
              <option value="">(none)</option>
              {options(tested?.quality_profiles, profile).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate()} disabled={!ready || test.isPending}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button variant="primary" type="submit" disabled={!tested || save.isPending} title={tested ? undefined : "Test the connection first"}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {connection.url && (
          <ConfirmButton
            label="Remove"
            confirm={`Remove ${label}`}
            warning={`Kometa stops using ${label} too.`}
            onConfirm={() => remove.mutate()}
            busy={remove.isPending}
          />
        )}
        {test.data && (test.data.ok ? <Outcome ok>{`${test.data.app} ${test.data.version} answered.`}</Outcome> : <Outcome ok={false}>{test.data.error}</Outcome>)}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved to config.yml</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
        {remove.isError && <Outcome ok={false}>{remove.error.message}</Outcome>}
      </div>
      {connection.status && (
        <p className={`text-xs ${connection.status.ok ? "text-muted" : "text-warn"}`}>
          {connection.status.ok
            ? `Imports checked ${formatRelative(connection.status.checked_at)}.`
            : `Last check failed (${formatRelative(connection.status.checked_at)}): ${connection.status.error}`}
        </p>
      )}
    </form>
  );
}

// What Studio can tell about each library, so "only imports that matter" isn't a black box.
function Relevance({ libraries, mode }: { libraries: LibraryRelevance[]; mode: RunMode }) {
  const queryClient = useQueryClient();
  const turnOn = useMutation({ mutationFn: api.arr.turnOnReports, onSuccess: (data) => queryClient.setQueryData(["arr"], data) });
  const overlays = mode === "all" || mode === "overlays";
  const collections = mode === "all" || mode === "collections";
  const line = (library: LibraryRelevance): { every: boolean; text: string } => {
    if (overlays && library.overlays) return { every: true, text: "every import counts: its overlays need drawing" };
    if (!collections) return { every: false, text: "nothing in this kind of run depends on what's imported" };
    if (library.unreadable.length) return { every: true, text: `every import counts: Studio can't read ${library.unreadable[0]}` };
    if (library.rule.length)
      return { every: true, text: `every import counts: ${library.rule.slice(0, 3).map((name) => `“${name}”`).join(", ")}${library.rule.length > 3 ? " and more" : ""} search Plex` };
    if (library.lists && !library.reports) return { every: true, text: "every import counts until Kometa's missing report is on" };
    if (library.lists && !library.reported_at) return { every: true, text: "every import counts until Kometa has reported on its collections (after its next full run)" };
    if (library.changed) return { every: true, text: "every import counts until the next full run: its collection files changed" };
    if (!library.lists && !library.ids) return { every: false, text: "no collection here wants anything specific" };
    return {
      every: false,
      text: `only imports its collections want: ${library.wanted + library.ids} known${library.reported_at ? `, from Kometa's report ${formatRelative(library.reported_at)}` : ""}`,
    };
  };
  const reportsOff = libraries.some((library) => library.lists > 0 && !library.reports);
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border p-3 text-sm">
      {libraries.length === 0 ? (
        <p className="text-muted">No libraries in config.yml yet, so every import counts.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {libraries.map((library) => {
            const { every, text } = line(library);
            return (
              <li key={library.library}>
                <span className="font-semibold">{library.library}</span>: <span className={every ? "text-warn" : "text-muted"}>{text}</span>
              </li>
            );
          })}
        </ul>
      )}
      {reportsOff && (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => turnOn.mutate()} disabled={turnOn.isPending}>
            Turn on Kometa's missing report
          </Button>
          <span className="text-xs text-muted">Sets save_report in config.yml. Kometa then notes, every run, what each collection wants that Plex doesn't have.</span>
          {turnOn.isError && <Outcome ok={false}>{turnOn.error.message}</Outcome>}
        </div>
      )}
    </div>
  );
}

function AppRunsForm({
  kind,
  label,
  runs,
  libraries,
  pending,
  relevance,
  skipped,
}: {
  kind: ArrKind;
  label: string;
  runs: AppRuns;
  libraries: string[];
  pending?: ArrPending;
  relevance: LibraryRelevance[];
  skipped: ArrState["skipped"][ArrKind];
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<AppRuns>(runs);
  const save = useMutation({ mutationFn: () => api.arr.saveRuns(kind, draft), onSuccess: (data) => queryClient.setQueryData(["arr"], data) });
  const toggleLibrary = (name: string) =>
    setDraft({ ...draft, libraries: draft.libraries.includes(name) ? draft.libraries.filter((n) => n !== name) : [...draft.libraries, name] });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <form className="flex flex-col gap-3 border-t border-dashed border-border pt-4" onSubmit={submit} aria-label={`${label} imports`}>
      <Checkbox checked={draft.enabled} onChange={(enabled) => setDraft({ ...draft, enabled })}>
        Run Kometa when {label} imports something
        <span className="block text-xs text-muted">Studio checks {label}'s import history every 2 minutes, so it doesn't need to reach Studio.</span>
      </Checkbox>
      {draft.enabled && (
        <>
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
          <fieldset className="flex flex-col">
            <legend className="mb-1 text-sm text-muted">Which imports</legend>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input type="radio" className="accent-accent" checked={draft.trigger === "any"} onChange={() => setDraft({ ...draft, trigger: "any" })} />
              Every import
            </label>
            <label className="flex min-h-11 items-start gap-2 pt-2.5 text-sm">
              <input type="radio" className="mt-1 accent-accent" checked={draft.trigger === "relevant"} onChange={() => setDraft({ ...draft, trigger: "relevant" })} />
              <span>
                Only imports that matter to Kometa
                <span className="block text-xs text-muted">
                  A collection wants it, a collection that searches Plex could take it, or overlays need drawing. When only collections want it, just those
                  collections run. The others are skipped.
                </span>
              </span>
            </label>
          </fieldset>
          {draft.trigger === "relevant" && (
            <Relevance libraries={relevance.filter((library) => draft.libraries.length === 0 || draft.libraries.includes(library.library))} mode={draft.mode} />
          )}
          <fieldset>
            <legend className="mb-1.5 text-sm text-muted">Libraries to run for</legend>
            {libraries.length === 0 ? (
              <p className="text-sm text-muted">No libraries in config.yml yet, so Kometa runs for all of them.</p>
            ) : (
              <div className="flex flex-wrap gap-x-4">
                {libraries.map((name) => (
                  <label key={name} className="flex min-h-11 items-center gap-2 text-sm">
                    <input type="checkbox" className="size-4 accent-accent" checked={draft.libraries.includes(name)} onChange={() => toggleLibrary(name)} />
                    {name}
                  </label>
                ))}
              </div>
            )}
            {libraries.length > 0 && draft.libraries.length === 0 && <p className="text-xs text-muted">None ticked: Kometa runs for every library.</p>}
          </fieldset>
        </>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending || JSON.stringify(draft) === JSON.stringify(runs)}>
          Save
        </Button>
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved.</Outcome>}
      </div>
      {skipped.length > 0 && (
        <p className="text-xs text-muted">
          Skipped lately:{" "}
          {skipped
            .slice(-3)
            .reverse()
            .map((entry) => `${entry.title} (${formatRelative(entry.at)})`)
            .join(", ")}
        </p>
      )}
      {pending && (
        <p role="status" className="text-sm text-info">
          {pending.imports} import{pending.imports === 1 ? "" : "s"} waiting ({pending.titles.join(", ")}). Kometa runs{" "}
          <span title={formatTime(pending.due_at)}>{formatRelative(pending.due_at)}</span> unless more arrive.
        </p>
      )}
    </form>
  );
}

// --- Maintainerr -------------------------------------------------------------------

function MaintainerrForm({ current }: { current: MaintainerrState }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState(current.url ?? "");
  const [proxy, setProxy] = useState(current.username !== null);
  const [username, setUsername] = useState(current.username ?? "");
  const [password, setPassword] = useState("");
  const [leaveOverlays, setLeaveOverlays] = useState(current.leave_overlays_alone);
  const login = proxy ? username.trim() || null : null;
  const test = useMutation({ mutationFn: () => api.maintainerr.test(url, login, proxy ? password || null : null) });
  const save = useMutation({
    mutationFn: (disconnect: boolean) =>
      api.maintainerr.save({ url: disconnect ? null : url, username: login, password: proxy ? password || null : null, leave_overlays_alone: leaveOverlays }),
    onSuccess: (data) => {
      queryClient.setQueryData(["maintainerr"], data);
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["plex"] });
      setUrl(data.url ?? "");
      setUsername(data.username ?? "");
      setProxy(data.username !== null);
      setPassword("");
      test.reset();
    },
  });
  const changed = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    test.reset();
    save.reset();
  };
  // A new address or login needs a passing test; the overlay choice alone doesn't.
  const connectionChanged = url.trim() !== (current.url ?? "") || login !== current.username || (proxy && password !== "");
  const tested = test.data?.ok === true;
  const canSave = url.trim() !== "" && (connectionChanged ? tested : leaveOverlays !== current.leave_overlays_alone);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate(false);
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Maintainerr connection">
      <p className="text-sm text-muted">
        With Maintainerr connected, Kometa leaves its collections alone: Studio refuses any change, and holds any run, that would let Kometa delete them, change
        their mode, or take one over with a collection of the same name.
      </p>
      <Field label="URL" hint="Maintainerr's API has no key of its own.">
        <input className={inputClass} value={url} onChange={(e) => changed(setUrl)(e.target.value)} placeholder="http://maintainerr:6246" spellCheck={false} />
      </Field>
      <ProxyLogin
        app="Maintainerr"
        enabled={proxy}
        username={username}
        password={password}
        hasPassword={current.has_password}
        onEnabled={changed(setProxy)}
        onUsername={changed(setUsername)}
        onPassword={changed(setPassword)}
      />
      <Checkbox checked={leaveOverlays} onChange={setLeaveOverlays}>
        Leave Maintainerr overlays alone
        <span className="block text-xs text-muted">
          Maintainerr's overlays always go on last, over Kometa's, so putting them back gives Kometa's poster. Studio decides when Maintainerr draws: after
          every Kometa run that changes posters (Maintainerr puts its posters back first), and once a day for its countdowns. If something is new since
          Kometa last drew overlays, Kometa's go on first. Maintainerr's own overlay schedule is kept off meanwhile, and given back when you turn this off.
          If Maintainerr doesn't answer, poster runs wait.
        </span>
      </Checkbox>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate()} disabled={test.isPending || !url.trim()}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button variant="primary" type="submit" disabled={save.isPending || !canSave} title={connectionChanged && !tested ? "Test the connection first" : undefined}>
          Save
        </Button>
        {current.url && (
          <ConfirmButton
            label="Disconnect"
            confirm="Disconnect Maintainerr"
            warning="Studio stops protecting its collections."
            onConfirm={() => save.mutate(true)}
            busy={save.isPending}
          />
        )}
        {test.data &&
          (test.data.ok ? (
            <Outcome ok>
              Maintainerr answered: {test.data.collections} collection{test.data.collections === 1 ? "" : "s"}, overlays {test.data.overlays_enabled ? "on" : "off"}.
            </Outcome>
          ) : (
            <Outcome ok={false}>{test.data.error}</Outcome>
          ))}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
      </div>
      {!current.url && current.schedule.taken_over && (
        <p role="alert" className="text-sm text-warn">
          Maintainerr's own overlay schedule couldn't be given back when it was disconnected. Set it again in Maintainerr → Overlays
          {current.schedule.own_cron ? ` (it was ${current.schedule.own_cron})` : ""}.
        </p>
      )}
      {current.url && (
        <div className="flex flex-col gap-2 text-sm">
          {current.error && <p className="text-warn">Can't read Maintainerr: {current.error}</p>}
          {current.schedule.taken_over && (
            <p className="text-muted">
              Studio holds Maintainerr's overlay schedule{current.schedule.own_cron ? ` (its own: ${current.schedule.own_cron})` : ""}.
              {current.schedule.last_redraw && <> Last drew {formatRelative(current.schedule.last_redraw)}</>}
              {current.schedule.next_redraw && <>; next daily redraw {formatRelative(current.schedule.next_redraw)}</>}.
            </p>
          )}
          {!current.leave_overlays_alone && current.schedule.taken_over && (
            <p className="text-warn">Giving Maintainerr its own overlay schedule back once it answers.</p>
          )}
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

// --- TMDb and MDBList --------------------------------------------------------------

const services: { name: ServiceName; label: string; hint: ReactNode; required: boolean }[] = [
  {
    name: "tmdb",
    label: "TMDb",
    required: true,
    hint: (
      <a className="underline" href="https://www.themoviedb.org/settings/api" target="_blank" rel="noreferrer">
        themoviedb.org → Settings → API → API Key
      </a>
    ),
  },
  {
    name: "mdblist",
    label: "MDBList",
    required: false,
    hint: (
      <a className="underline" href="https://mdblist.com/preferences/" target="_blank" rel="noreferrer">
        mdblist.com → Preferences → API Key
      </a>
    ),
  },
];

function ServiceForm({ name, label, hint, required, saved }: { name: ServiceName; label: string; hint: ReactNode; required: boolean; saved: string | null }) {
  const queryClient = useQueryClient();
  const [apikey, setApikey] = useState("");
  const test = useMutation({ mutationFn: () => api.services.test(name, apikey || null) });
  const done = (data: Awaited<ReturnType<typeof api.services.get>>) => {
    queryClient.setQueryData(["services"], data);
    setApikey("");
    test.reset();
  };
  const save = useMutation({ mutationFn: () => api.services.save(name, apikey || null), onSuccess: done });
  const remove = useMutation({ mutationFn: () => api.services.remove(name), onSuccess: done });
  const tested = test.data?.ok === true;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (tested) save.mutate();
  };
  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label={label}>
      <Field label={`${label} API key`} hint={hint}>
        <input
          className={inputClass}
          type="password"
          autoComplete="off"
          value={apikey}
          onChange={(e) => {
            setApikey(e.target.value);
            test.reset();
            save.reset();
          }}
          placeholder={saved ? `Saved (${saved}), leave empty to keep it` : required ? "Kometa needs this to run" : ""}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate()} disabled={test.isPending || (!apikey && !saved)}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button variant="primary" type="submit" disabled={!tested || save.isPending || (!apikey && saved !== null)} title={tested ? undefined : "Test the key first"}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {!required && saved && (
          <ConfirmButton label="Remove" confirm={`Remove ${label}`} warning={`Kometa stops using ${label}.`} onConfirm={() => remove.mutate()} busy={remove.isPending} />
        )}
        {test.data &&
          (test.data.ok ? (
            <Outcome ok>
              {label} accepted the key
              {typeof test.data.used === "number" && typeof test.data.limit === "number" ? `: ${test.data.used} of ${test.data.limit} requests used today.` : "."}
            </Outcome>
          ) : (
            <Outcome ok={false}>{test.data.error}</Outcome>
          ))}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved to config.yml</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
        {remove.isError && <Outcome ok={false}>{remove.error.message}</Outcome>}
      </div>
    </form>
  );
}

// --- Page --------------------------------------------------------------------------

export function SettingsConnect() {
  const arr = useQuery({ queryKey: ["arr"], queryFn: api.arr.get, refetchInterval: 30_000 });
  const maintainerr = useQuery({ queryKey: ["maintainerr"], queryFn: api.maintainerr.get });
  const keys = useQuery({ queryKey: ["services"], queryFn: api.services.get });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const libraries = config.data?.libraries.map((library) => library.name) ?? [];

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Radarr, Sonarr and Maintainerr">
        <div className="flex flex-col gap-5">
          {arr.isPending ? (
            <p className="text-muted">Loading…</p>
          ) : arr.isError ? (
            <p role="alert" className="text-err">
              {arr.error.message}
            </p>
          ) : (
            apps.map(({ kind, label }) => (
              <Section key={kind} title={label}>
                <p className="text-sm text-muted">
                  Kometa's own {label} connection, in config.yml. Kometa uses it to add missing items; Studio uses it to run Kometa after imports.
                </p>
                <ArrConnectionForm key={JSON.stringify(arr.data.connections[kind])} kind={kind} label={label} connection={arr.data.connections[kind]} />
                <AppRunsForm
                  key={JSON.stringify(arr.data.settings[kind])}
                  kind={kind}
                  label={label}
                  runs={arr.data.settings[kind]}
                  libraries={libraries}
                  pending={arr.data.pending[kind]}
                  relevance={arr.data.libraries}
                  skipped={arr.data.skipped[kind]}
                />
              </Section>
            ))
          )}
          <Section title="Maintainerr">
            {maintainerr.isPending ? (
              <p className="text-muted">Loading…</p>
            ) : maintainerr.isError ? (
              <p role="alert" className="text-err">
                {maintainerr.error.message}
              </p>
            ) : (
              <MaintainerrForm current={maintainerr.data} />
            )}
          </Section>
        </div>
      </Card>
      <Card title="TMDb and MDBList">
        <div className="flex flex-col gap-5">
          <p className="text-sm text-muted">Kometa's keys for these services, in config.yml. Kometa needs TMDb to run; MDBList is optional.</p>
          {keys.isPending ? (
            <p className="text-muted">Loading…</p>
          ) : keys.isError ? (
            <p role="alert" className="text-err">
              {keys.error.message}
            </p>
          ) : (
            services.map((service) => (
              <Section key={service.name} title={service.label}>
                <ServiceForm {...service} saved={keys.data[service.name].apikey} />
              </Section>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
