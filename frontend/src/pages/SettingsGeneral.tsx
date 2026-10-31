// Settings → General: sign-in, the API key, the timezone, and the address behind a reverse proxy (handoff v2 §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, type AuthRequired, type GeneralSettings } from "../api";
import { urlBase } from "../base";
import { Button, Card, Field, inputClass } from "../components/ui";
import { timezoneOptions } from "../timezones";

export function SignIn({ settings }: { settings: GeneralSettings }) {
  const queryClient = useQueryClient();
  const { configured } = settings.auth;
  const [username, setUsername] = useState(settings.auth.username ?? "");
  const [password, setPassword] = useState("");
  const [required, setRequired] = useState<AuthRequired>(settings.auth.required);
  const [current, setCurrent] = useState("");
  // Once sign-in is set up, the username and password fields stay hidden until asked for.
  const [changing, setChanging] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      api.general.setAuth({
        username,
        password: password || null,
        required,
        current_password: configured ? current : null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["general"], data);
      queryClient.invalidateQueries({ queryKey: ["auth"] });
      setPassword("");
      setCurrent("");
      setChanging(false);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  const cancel = () => {
    setUsername(settings.auth.username ?? "");
    setPassword("");
    setCurrent("");
    setRequired(settings.auth.required);
    setChanging(false);
    save.reset();
  };
  const editing = !configured || changing;
  const dirty = editing || required !== settings.auth.required;

  return (
    <Card title="Sign-in">
      <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Sign-in">
        <p className="text-sm text-muted">
          {configured
            ? "Studio asks for this username and password on its login page."
            : "Not set up yet: Studio only answers this computer and your local network, without asking who you are. Set a username and password before you reach it from anywhere else."}
        </p>
        <Field label="Authentication required">
          <select className={inputClass} value={required} onChange={(e) => setRequired(e.target.value as AuthRequired)}>
            <option value="enabled">Enabled: everyone signs in</option>
            <option value="disabled_for_local">Disabled for local addresses: only the internet signs in</option>
          </select>
        </Field>
        {editing ? (
          <>
            <Field label="Username">
              <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </Field>
            <Field
              label={configured ? "New password" : "Password"}
              hint={configured ? "Leave empty to keep the current one." : "At least 8 characters."}
            >
              <input
                className={inputClass}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required={!configured}
              />
            </Field>
          </>
        ) : (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
            <span className="text-muted">Username</span>
            <span className="font-semibold">{settings.auth.username}</span>
            <button type="button" className="min-h-11 text-accent underline hover:no-underline" onClick={() => setChanging(true)}>
              Change username or password
            </button>
          </div>
        )}
        {configured && dirty && (
          <Field label="Current password" hint="Needed to change anything here. Changing the username or password signs out every other browser.">
            <input
              className={inputClass}
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
        )}
        {(dirty || save.isSuccess) && (
          <div className="flex flex-wrap items-center gap-3">
            {dirty && (
              <>
                <Button variant="primary" type="submit" disabled={save.isPending}>
                  {save.isPending ? "Saving…" : configured ? "Save" : "Set up sign-in"}
                </Button>
                {configured && <Button onClick={cancel}>Cancel</Button>}
              </>
            )}
            {save.isError && (
              <span role="alert" className="text-sm text-err">
                {save.error.message}
              </span>
            )}
            {save.isSuccess && !dirty && (
              <span role="status" className="text-sm text-ok">
                Saved.
              </span>
            )}
          </div>
        )}
      </form>
    </Card>
  );
}

function ApiKey({ settings }: { settings: GeneralSettings }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);
  const renew = useMutation({
    mutationFn: api.general.newApiKey,
    onSuccess: (data) => {
      queryClient.setQueryData(["general"], data);
      setConfirming(false);
    },
  });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(settings.api_key);
      setCopied(true);
    } catch {
      // no clipboard (plain http): the key is selectable instead
    }
  };
  return (
    <Card title="API key">
      <p className="mb-3 text-sm text-muted">
        For dashboards and scripts: send it as an <code className="font-mono">X-Api-Key</code> header, and every endpoint answers, e.g.{" "}
        <code className="font-mono">/api/v1/status</code>.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${inputClass} max-w-md`} value={settings.api_key} readOnly aria-label="API key" onFocus={(e) => e.target.select()} />
        <Button onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
        {confirming ? (
          <>
            <Button className="border-err/60 text-err" onClick={() => renew.mutate()} disabled={renew.isPending}>
              Replace it
            </Button>
            <Button onClick={() => setConfirming(false)}>Keep</Button>
          </>
        ) : (
          <Button onClick={() => setConfirming(true)}>New key</Button>
        )}
      </div>
      {confirming && <p className="mt-2 text-sm text-warn">Anything using the current key stops working until you give it the new one.</p>}
    </Card>
  );
}

function Timezone({ settings }: { settings: GeneralSettings }) {
  const queryClient = useQueryClient();
  const [timezone, setTimezone] = useState(settings.timezone);
  const options = timezoneOptions(undefined, [settings.timezone, timezone]);
  const save = useMutation({
    mutationFn: () => api.general.setTimezone(timezone),
    onSuccess: (data) => {
      queryClient.setQueryData(["general"], data);
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  return (
    <Card title="Timezone">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <div className="min-w-60 flex-1">
          <Field label="Schedules and tasks use" hint="Kometa schedules and Studio's built-in tasks share this timezone. Daylight saving changes are handled.">
            <select className={inputClass} value={timezone} onChange={(e) => setTimezone(e.target.value)} aria-label="Schedules and tasks use">
              {options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Button type="submit" disabled={save.isPending || timezone === settings.timezone}>
          Save
        </Button>
      </form>
      {save.isError && (
        <p role="alert" className="mt-2 text-sm text-err">
          {save.error.message}
        </p>
      )}
    </Card>
  );
}

function Address({ settings }: { settings: GeneralSettings }) {
  const queryClient = useQueryClient();
  const saved = settings.reverse_proxy;
  const [base, setBase] = useState(saved.url_base);
  const [trusted, setTrusted] = useState(saved.trusted.join("\n"));
  const entries = trusted.split(/[\n,\s]+/).map((entry) => entry.trim()).filter(Boolean);
  const changed = base.trim() !== saved.url_base || entries.join(",") !== saved.trusted.join(",");
  const save = useMutation({
    mutationFn: () => api.general.setReverseProxy({ url_base: base, trusted: entries }),
    onSuccess: (data) => {
      queryClient.setQueryData(["general"], data);
      setBase(data.reverse_proxy.url_base);
      setTrusted(data.reverse_proxy.trusted.join("\n"));
    },
  });
  const you = settings.you;
  const newBase = save.data && save.data.reverse_proxy.url_base !== urlBase ? save.data.reverse_proxy.url_base : null;
  return (
    <Card title="Address">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">
          Studio listens on port <span className="font-mono text-text">{settings.port}</span>. In Docker, choose the port people use in the
          container's port mapping; outside Docker, set <code className="font-mono">STUDIO_HOST</code> and{" "}
          <code className="font-mono">STUDIO_PORT</code>.
        </p>
        <form
          className="flex flex-col gap-4"
          aria-label="Reverse proxy"
          onSubmit={(event) => {
            event.preventDefault();
            if (changed) save.mutate();
          }}
        >
          <Field
            label="URL base"
            hint="For a reverse proxy that serves Studio under a path, such as /kometa. Studio answers with and without it, so the proxy may pass the path on or strip it."
          >
            <input className={`${inputClass} font-mono`} value={base} onChange={(e) => setBase(e.target.value)} placeholder="None" spellCheck={false} />
          </Field>
          <Field
            label="Trusted proxies"
            hint="Addresses or networks, one per line or separated by commas. Only for requests from these does Studio believe X-Forwarded-For about who is visiting, so local visitors through the proxy count as local for sign-in. Other proxied requests never do."
          >
            <textarea
              className={`${inputClass} min-h-20 py-2 font-mono`}
              value={trusted}
              onChange={(e) => setTrusted(e.target.value)}
              placeholder="e.g. 172.18.0.0/16"
              spellCheck={false}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!changed || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            {save.isError && (
              <span role="alert" className="text-sm text-err">
                {save.error.message}
              </span>
            )}
            {save.isSuccess && !newBase && (
              <span role="status" className="text-sm text-ok">
                Saved.
              </span>
            )}
          </div>
          {newBase !== null && (
            <p role="status" className="text-sm text-ok">
              Saved. Studio now answers at{" "}
              <a className="underline" href={`${newBase}/settings/general`}>
                {window.location.origin}
                {newBase}/
              </a>
              {newBase === "" ? " with no URL base" : ""}.
            </p>
          )}
        </form>
        <p className="text-sm text-muted" aria-label="How Studio sees you">
          Studio sees this browser as <span className="font-mono text-text">{you.address ?? "unknown"}</span>
          {you.proxied ? (
            you.trusted_proxy ? (
              <>
                {" "}
                through the trusted proxy <span className="font-mono">{you.peer}</span>
              </>
            ) : (
              <>
                , a proxy Studio doesn't trust, so it can't tell who is behind it
              </>
            )
          ) : null}
          : {you.local ? "a local address." : "not a local address."}
        </p>
      </div>
    </Card>
  );
}

export function SettingsGeneral() {
  const general = useQuery({ queryKey: ["general"], queryFn: api.general.get });
  if (general.isPending) return <p className="text-muted">Loading…</p>;
  if (general.isError)
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {general.error.message}
      </p>
    );
  const settings = general.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <SignIn settings={settings} />
      <ApiKey settings={settings} />
      <Timezone settings={settings} />
      <Address settings={settings} />
    </div>
  );
}
