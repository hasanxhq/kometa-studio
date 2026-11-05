// Settings → Requests: turn missing-title downloads on, choose Radarr/Sonarr or Seerr, set limits.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";

import { ConfirmDialog } from "../components/ConfirmDialog";
import { Button, Card, Checkbox, ConfirmButton, Field, inputClass } from "../components/ui";
import {
  requestsApi,
  type RequestSettings,
  type RequestsSettingsState,
  type SeerrIn,
  type SeerrJson,
} from "../requestsApi";

function Outcome({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span role={ok ? "status" : "alert"} className={`text-sm ${ok ? "text-ok" : "text-err"}`}>
      {children}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-4 border-t border-border pt-5 first:border-0 first:pt-0">
      <h3 className="font-display text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

const AVAILABILITY: { value: RequestSettings["radarr"]["minimum_availability"]; label: string }[] = [
  { value: "announced", label: "Announced" },
  { value: "inCinemas", label: "In cinemas" },
  { value: "released", label: "Released" },
];

const MONITOR: { value: RequestSettings["sonarr"]["monitor"]; label: string }[] = [
  { value: "all", label: "All episodes" },
  { value: "future", label: "Future episodes" },
  { value: "missing", label: "Missing episodes" },
  { value: "existing", label: "Existing episodes" },
  { value: "firstSeason", label: "First season" },
  { value: "latestSeason", label: "Latest season" },
  { value: "pilot", label: "Pilot" },
];

const SERIES_TYPE: { value: RequestSettings["sonarr"]["series_type"]; label: string }[] = [
  { value: "standard", label: "Standard" },
  { value: "anime", label: "Anime" },
  { value: "daily", label: "Daily" },
];

function SeerrForm({ current }: { current: SeerrJson | null }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState(current?.url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [proxy, setProxy] = useState(current?.username !== null && current?.username !== undefined);
  const [username, setUsername] = useState(current?.username ?? "");
  const [password, setPassword] = useState("");
  const body = (): SeerrIn => ({
    url,
    api_key: apiKey || null,
    username: proxy ? username || null : null,
    password: proxy ? password || null : null,
  });
  const done = (data: RequestsSettingsState) => {
    queryClient.setQueryData(["requests", "settings"], data);
    setApiKey("");
    setPassword("");
    test.reset();
  };
  const test = useMutation({ mutationFn: () => requestsApi.testSeerr(body()) });
  const save = useMutation({ mutationFn: () => requestsApi.saveSeerr(body()), onSuccess: done });
  const remove = useMutation({ mutationFn: () => requestsApi.removeSeerr(), onSuccess: done });
  const changed = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    test.reset();
    save.reset();
  };
  const tested = test.data?.ok === true;
  const ready = url.trim() !== "" && (apiKey !== "" || current?.api_key !== null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (tested) save.mutate();
  };

  return (
    <form className="flex flex-col gap-3" onSubmit={submit} aria-label="Seerr connection">
      <div className="flex flex-wrap gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <Field label="URL">
            <input
              className={inputClass}
              value={url}
              onChange={(e) => changed(setUrl)(e.target.value)}
              placeholder="http://seerr:5055"
              inputMode="url"
              spellCheck={false}
            />
          </Field>
        </div>
        <div className="min-w-0 flex-1 basis-64">
          <Field label="API key">
            <input
              className={inputClass}
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => changed(setApiKey)(e.target.value)}
              placeholder={current?.api_key ? `Saved (${current.api_key}), leave empty to keep it` : ""}
            />
          </Field>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <Checkbox checked={proxy} onChange={changed(setProxy)}>
          Behind a proxy that asks for a login
          <span className="block text-xs text-muted">Optional HTTP Basic login. Only Studio uses it.</span>
        </Checkbox>
        {proxy && (
          <div className="flex flex-wrap gap-3">
            <div className="min-w-0 flex-1 basis-48">
              <Field label="Username">
                <input className={inputClass} autoComplete="off" value={username} onChange={(e) => changed(setUsername)(e.target.value)} />
              </Field>
            </div>
            <div className="min-w-0 flex-1 basis-48">
              <Field label="Password">
                <input
                  className={inputClass}
                  type="password"
                  autoComplete="off"
                  value={password}
                  onChange={(e) => changed(setPassword)(e.target.value)}
                  placeholder={current?.has_password ? "Saved (leave empty to keep it)" : ""}
                />
              </Field>
            </div>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate()} disabled={!ready || test.isPending}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button variant="primary" type="submit" disabled={!tested || save.isPending} title={tested ? undefined : "Test the connection first"}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {current && (
          <ConfirmButton
            label="Remove"
            confirm="Remove"
            warning="Studio stops sending requests through Seerr, and its seerr: section leaves Kometa's config.yml."
            onConfirm={() => remove.mutate()}
            busy={remove.isPending}
          />
        )}
        {test.data && (test.data.ok ? <Outcome ok>Connected.</Outcome> : <Outcome ok={false}>{test.data.error}</Outcome>)}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved.</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
        {remove.isError && <Outcome ok={false}>{remove.error.message}</Outcome>}
      </div>
    </form>
  );
}

function SettingsForm({ state }: { state: RequestsSettingsState }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(state.settings);
  const [askEnable, setAskEnable] = useState(false);
  const options = useQuery({ queryKey: ["requests", "options"], queryFn: requestsApi.options });
  const save = useMutation({
    mutationFn: () => requestsApi.saveSettings(draft),
    onSuccess: (data) => {
      queryClient.setQueryData(["requests", "settings"], data);
      setDraft(data.settings);
    },
  });

  useEffect(() => {
    setDraft(state.settings);
  }, [state.settings]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  const setEnabled = (enabled: boolean) => {
    if (enabled && !draft.enabled) {
      setAskEnable(true);
      return;
    }
    setDraft({ ...draft, enabled });
    save.reset();
  };

  const firstOption = (label: string) => <option value="">{`${label}'s first`}</option>;

  return (
    <>
      <form className="flex flex-col gap-5" onSubmit={submit} aria-label="Requests settings">
        <Checkbox checked={draft.enabled} onChange={setEnabled}>
          Requests
          <span className="block text-xs text-muted">Ask Radarr, Sonarr or Seerr for titles a collection is missing.</span>
        </Checkbox>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm text-muted">Send requests to</legend>
          {(
            [
              {
                value: "auto" as const,
                label: "Automatic",
                hint: "Seerr when connected, else Radarr/Sonarr",
                ok: state.connected.seerr || state.connected.radarr || state.connected.sonarr,
                why: "Connect Radarr, Sonarr or Seerr first",
              },
              {
                value: "arr" as const,
                label: "Radarr and Sonarr",
                hint: null,
                ok: state.connected.radarr || state.connected.sonarr,
                why: "Connect Radarr or Sonarr under Settings → Connect",
              },
              {
                value: "seerr" as const,
                label: "Seerr",
                hint: null,
                ok: state.connected.seerr,
                why: "Connect Seerr below",
              },
            ] as const
          ).map((option) => (
            <label key={option.value} className={`flex min-h-11 items-start gap-2 text-sm ${option.ok ? "" : "opacity-60"}`}>
              <input
                type="radio"
                className="mt-1 accent-accent"
                name="via"
                checked={draft.via === option.value}
                disabled={!option.ok}
                onChange={() => {
                  setDraft({ ...draft, via: option.value });
                  save.reset();
                }}
              />
              <span>
                {option.label}
                {option.hint && <span className="block text-xs text-muted">{option.hint}</span>}
                {!option.ok && <span className="block text-xs text-muted">{option.why}</span>}
              </span>
            </label>
          ))}
        </fieldset>

        <Section title="Radarr">
          {state.connected.radarr ? (
            <>
              {options.data?.errors.radarr && <p className="text-sm text-warn">{options.data.errors.radarr}</p>}
              <div className="flex flex-wrap gap-3">
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Default quality profile" hint="A collection can pick another in the builder.">
                    <select
                      className={inputClass}
                      value={draft.radarr.quality_profile ?? ""}
                      onChange={(e) => setDraft({ ...draft, radarr: { ...draft.radarr, quality_profile: e.target.value || null } })}
                    >
                      {firstOption("Radarr")}
                      {(options.data?.radarr?.quality_profiles ?? []).map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Root folder">
                    <select
                      className={inputClass}
                      value={draft.radarr.root_folder ?? ""}
                      onChange={(e) => setDraft({ ...draft, radarr: { ...draft.radarr, root_folder: e.target.value || null } })}
                    >
                      {firstOption("Radarr")}
                      {(options.data?.radarr?.root_folders ?? []).map((path) => (
                        <option key={path} value={path}>
                          {path}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Minimum availability">
                    <select
                      className={inputClass}
                      value={draft.radarr.minimum_availability}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          radarr: { ...draft.radarr, minimum_availability: e.target.value as RequestSettings["radarr"]["minimum_availability"] },
                        })
                      }
                    >
                      {AVAILABILITY.map((entry) => (
                        <option key={entry.value} value={entry.value}>
                          {entry.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              </div>
              <Checkbox checked={draft.radarr.search} onChange={(search) => setDraft({ ...draft, radarr: { ...draft.radarr, search } })}>
                Search when added
              </Checkbox>
            </>
          ) : (
            <p className="text-sm text-muted">
              Radarr isn&apos;t connected.{" "}
              <Link className="underline hover:text-text" to="/settings/connect">
                Settings → Connect
              </Link>
            </p>
          )}
        </Section>

        <Section title="Sonarr">
          {state.connected.sonarr ? (
            <>
              {options.data?.errors.sonarr && <p className="text-sm text-warn">{options.data.errors.sonarr}</p>}
              <div className="flex flex-wrap gap-3">
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Default quality profile" hint="A collection can pick another in the builder.">
                    <select
                      className={inputClass}
                      value={draft.sonarr.quality_profile ?? ""}
                      onChange={(e) => setDraft({ ...draft, sonarr: { ...draft.sonarr, quality_profile: e.target.value || null } })}
                    >
                      {firstOption("Sonarr")}
                      {(options.data?.sonarr?.quality_profiles ?? []).map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Root folder">
                    <select
                      className={inputClass}
                      value={draft.sonarr.root_folder ?? ""}
                      onChange={(e) => setDraft({ ...draft, sonarr: { ...draft.sonarr, root_folder: e.target.value || null } })}
                    >
                      {firstOption("Sonarr")}
                      {(options.data?.sonarr?.root_folders ?? []).map((path) => (
                        <option key={path} value={path}>
                          {path}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Monitor">
                    <select
                      className={inputClass}
                      value={draft.sonarr.monitor}
                      onChange={(e) => setDraft({ ...draft, sonarr: { ...draft.sonarr, monitor: e.target.value as RequestSettings["sonarr"]["monitor"] } })}
                    >
                      {MONITOR.map((entry) => (
                        <option key={entry.value} value={entry.value}>
                          {entry.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <Field label="Series type">
                    <select
                      className={inputClass}
                      value={draft.sonarr.series_type}
                      onChange={(e) =>
                        setDraft({ ...draft, sonarr: { ...draft.sonarr, series_type: e.target.value as RequestSettings["sonarr"]["series_type"] } })
                      }
                    >
                      {SERIES_TYPE.map((entry) => (
                        <option key={entry.value} value={entry.value}>
                          {entry.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              </div>
              <Checkbox checked={draft.sonarr.search} onChange={(search) => setDraft({ ...draft, sonarr: { ...draft.sonarr, search } })}>
                Search when added
              </Checkbox>
            </>
          ) : (
            <p className="text-sm text-muted">
              Sonarr isn&apos;t connected.{" "}
              <Link className="underline hover:text-text" to="/settings/connect">
                Settings → Connect
              </Link>
            </p>
          )}
        </Section>

        <Section title="Limits">
          <div className="flex flex-wrap gap-3">
            <div className="min-w-0 flex-1 basis-48">
              <Field label="Most titles per collection per day" hint="Empty means no limit.">
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={draft.daily_cap ?? ""}
                  onChange={(e) => {
                    const raw = e.target.value.trim();
                    setDraft({ ...draft, daily_cap: raw === "" ? null : Number.parseInt(raw, 10) });
                    save.reset();
                  }}
                  placeholder="No limit"
                />
              </Field>
            </div>
            <div className="min-w-0 flex-1 basis-48">
              <Field label="Ask before requesting more than">
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={draft.confirm_over}
                  onChange={(e) => {
                    setDraft({ ...draft, confirm_over: Number.parseInt(e.target.value || "25", 10) });
                    save.reset();
                  }}
                />
              </Field>
            </div>
          </div>
        </Section>

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" type="submit" disabled={save.isPending || JSON.stringify(draft) === JSON.stringify(state.settings)}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {save.isSuccess && <Outcome ok>Saved.</Outcome>}
          {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
        </div>
      </form>

      {askEnable && (
        <ConfirmDialog
          title="Turn on requests"
          confirm="Turn on requests"
          onConfirm={() => {
            setDraft({ ...draft, enabled: true });
            setAskEnable(false);
            save.reset();
          }}
          onCancel={() => setAskEnable(false)}
        >
          Studio will ask Radarr and Sonarr (or Seerr) to download titles your collections are missing. That uses disk space, bandwidth and your
          indexers&apos; limits. Nothing is requested until you tick Download missing on a collection.
        </ConfirmDialog>
      )}
    </>
  );
}

export function SettingsRequests() {
  const settings = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Requests">
        {settings.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : settings.isError ? (
          <p role="alert" className="text-err">
            {settings.error.message}
          </p>
        ) : (
          <SettingsForm key={JSON.stringify(settings.data.settings) + JSON.stringify(settings.data.connected)} state={settings.data} />
        )}
      </Card>
      <Card title="Seerr">
        <p className="mb-4 text-sm text-muted">
          Optional. When connected and Send requests to is Automatic or Seerr, Studio files requests there. The URL and API key are saved in Kometa&apos;s
          config.yml (<code className="font-mono text-xs">seerr:</code>); Studio still does the asking, with your limits.
        </p>
        {settings.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : settings.isError ? (
          <p role="alert" className="text-err">
            {settings.error.message}
          </p>
        ) : (
          <SeerrForm key={JSON.stringify(settings.data.seerr)} current={settings.data.seerr} />
        )}
      </Card>
    </div>
  );
}
