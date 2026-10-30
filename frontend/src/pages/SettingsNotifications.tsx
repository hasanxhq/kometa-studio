// Settings → Notifications: Kometa's notification services (Notifiarr, Gotify, ntfy, Apprise) and which webhook events go where.
// Each service that's set up has its own card; the "Add notification provider" card after them sets up one of the rest, and moves
// along as each is added. A service is saved only after Test passes for the values as they are; any edit clears the pass, and the
// server tests again before it saves.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  ApiError,
  api,
  saveRefusal,
  type NotificationService,
  type NotificationServiceName,
  type NotificationsState,
  type NotificationValues,
  type Validation,
  type WebhookEvent,
  type WebhookTarget,
} from "../api";
import { ValidationReport } from "../components/ValidationReport";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";

type KeyHelp = { placeholder?: string; hint?: string };

const help: Record<NotificationServiceName, { summary: string; intro: string; keys: Record<string, KeyHelp> }> = {
  notifiarr: {
    summary: "Discord, through notifiarr.com.",
    intro: "Notifiarr passes Kometa's notifications on to Discord. Test checks the API key the way Kometa does when it starts; it sends no message.",
    keys: { apikey: { hint: "Your API key from notifiarr.com." } },
  },
  gotify: {
    summary: "Your own Gotify server.",
    intro: "Your own Gotify server. Test sends one message, titled “Kometa Studio test notification”.",
    keys: {
      url: { placeholder: "https://gotify.example.com" },
      token: { hint: "An application's token: in Gotify, Apps → Create Application." },
    },
  },
  ntfy: {
    summary: "The public ntfy.sh, or your own ntfy server.",
    intro: "The public ntfy.sh or your own ntfy server. Test sends one message to the topic, titled “Kometa Studio test notification”.",
    keys: {
      url: { placeholder: "https://ntfy.sh" },
      token: { placeholder: "tk_…", hint: "In ntfy, Account → Access tokens." },
      topic: { hint: "Anyone who knows a public topic's name can read it, so pick one that's hard to guess." },
    },
  },
  apprise: {
    summary: "Discord, Telegram, Pushover, email and many more, through Apprise.",
    intro:
      "Apprise sends to Discord, Telegram, Pushover, email and many more, as listed in its own configuration. Test reads that configuration and checks it lists at least one service; Apprise sends the messages, so no test message is sent.",
    keys: { config: { placeholder: "/config/apprise.yml", hint: "A path as Kometa sees it, or a URL. A relative path starts in Kometa's folder." } },
  },
};

const events: { event: WebhookEvent; label: string }[] = [
  { event: "error", label: "An error happens" },
  { event: "version", label: "A newer Kometa is out" },
  { event: "run_start", label: "A run starts" },
  { event: "run_end", label: "A run ends" },
  { event: "changes", label: "A collection is made or changes" },
  { event: "delete", label: "A collection or playlist is deleted" },
];

const STUDIO_MARK = "managed by Kometa Studio";

type Verdict = { validation: Validation; saved: boolean };

// How a save went: Kometa's verdict if there is one, else the message. A 409 (config.yml changed meanwhile) reloads the page's data.
function useOutcome(onConflict: () => void) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const clear = () => {
    setVerdict(null);
    setProblem(null);
    setNote(null);
  };
  const refused = (error: Error) => {
    const refusal = saveRefusal(error);
    if (refusal?.validation) setVerdict({ validation: refusal.validation, saved: false });
    if (error instanceof ApiError && error.status === 409) {
      onConflict();
      setProblem(`${error.message} Studio has loaded it again; try once more.`);
    } else setProblem(error.message);
  };
  const saved = (state: NotificationsState) => {
    if (state.saved) setVerdict({ validation: state.saved.validation, saved: true });
    else setNote("config.yml already says this, so nothing changed.");
  };
  return { verdict, problem, note, clear, refused, saved };
}

function Outcome({ verdict, problem, note }: { verdict: Verdict | null; problem: string | null; note: string | null }) {
  return (
    <>
      {note && (
        <p role="status" className="text-sm text-muted">
          {note}
        </p>
      )}
      {problem && !verdict && (
        <p role="alert" className="text-sm text-err">
          {problem}
        </p>
      )}
      {verdict && <ValidationReport validation={verdict.validation} saved={verdict.saved} />}
      {verdict?.saved && (
        <p className="text-sm text-muted">
          The previous config.yml is in{" "}
          <Link className="underline" to="/system/backup">
            System → Backup
          </Link>
          .
        </p>
      )}
    </>
  );
}

// --- One service ------------------------------------------------------------------

function emptyValues(service: NotificationService): Record<string, string> {
  return Object.fromEntries(service.keys.map((key) => [key.name, key.secret ? "" : (key.value ?? "")]));
}

function ServiceForm({
  service,
  hash,
  onSaved: onSavedOutside,
  onRemoved,
}: {
  service: NotificationService;
  hash: string | null;
  onSaved?: () => void; // the Add card: the service now has a card of its own
  onRemoved?: () => void; // its card goes; the service is offered on the Add card again
}) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState(() => emptyValues(service));
  const [confirming, setConfirming] = useState(false);
  const outcome = useOutcome(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }));
  const body = (): NotificationValues => Object.fromEntries(service.keys.map((key) => [key.name, values[key.name].trim() || null]));
  const test = useMutation({ mutationFn: (tested: NotificationValues) => api.notifications.test(service.name, tested) });
  const onSaved = (data: NotificationsState, cleared: Record<string, string>) => {
    queryClient.setQueryData(["notifications"], data);
    setValues(cleared);
    test.reset();
    outcome.saved(data);
  };
  const save = useMutation({
    mutationFn: () => api.notifications.save(service.name, body(), hash),
    onMutate: outcome.clear,
    // Secrets go back to empty: the saved one is kept, and shown masked.
    onSuccess: (data) => {
      onSaved(data, Object.fromEntries(service.keys.map((key) => [key.name, key.secret ? "" : values[key.name]])));
      onSavedOutside?.();
    },
    onError: outcome.refused,
  });
  const remove = useMutation({
    mutationFn: () => api.notifications.remove(service.name, hash ?? ""),
    onMutate: outcome.clear,
    onSuccess: (data) => {
      setConfirming(false);
      onSaved(data, Object.fromEntries(service.keys.map((key) => [key.name, ""])));
      onRemoved?.();
    },
    onError: outcome.refused,
  });

  const filled = service.keys.every((key) => values[key.name].trim() !== "" || (key.secret && key.masked !== null));
  // The pass counts only for the values it was given: editing a field resets it too.
  const passed = test.data?.ok === true && JSON.stringify(test.variables) === JSON.stringify(body());
  const busy = test.isPending || save.isPending || remove.isPending;
  const edit = (name: string, value: string) => {
    setValues({ ...values, [name]: value });
    test.reset();
    save.reset();
    outcome.clear();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (passed) save.mutate();
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label={service.label}>
      <p className="text-sm text-muted">{help[service.name].intro}</p>
      <div className="flex flex-wrap gap-3">
        {service.keys.map((key) => {
          const extra = help[service.name].keys[key.name] ?? {};
          return (
            <div key={key.name} className="min-w-0 flex-1 basis-64">
              <Field label={key.label} hint={extra.hint}>
                <input
                  className={inputClass}
                  type={key.secret ? "password" : "text"}
                  value={values[key.name]}
                  onChange={(e) => edit(key.name, e.target.value)}
                  placeholder={key.secret && key.masked ? `Saved: ${key.masked} (leave empty to keep it)` : extra.placeholder}
                  autoComplete="off"
                  spellCheck={false}
                />
              </Field>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate(body())} disabled={!filled || busy}>
          {test.isPending ? "Testing…" : "Test"}
        </Button>
        <Button variant="primary" type="submit" disabled={!passed || busy} title={passed ? undefined : "Test it first"}>
          {save.isPending ? "Testing and saving…" : "Save"}
        </Button>
        {service.configured &&
          (confirming ? (
            <>
              <Button className="border-err/60 text-err" onClick={() => remove.mutate()} disabled={busy}>
                Remove {service.label}
              </Button>
              <Button onClick={() => setConfirming(false)}>Keep</Button>
            </>
          ) : (
            <Button onClick={() => setConfirming(true)} disabled={busy}>
              Remove…
            </Button>
          ))}
        {test.data &&
          (test.data.ok ? (
            <span role="status" className="text-sm text-ok">
              {test.data.message}
            </span>
          ) : (
            <span role="alert" className="text-sm text-err">
              {test.data.error}
            </span>
          ))}
        {test.isError && (
          <span role="alert" className="text-sm text-err">
            {test.error.message}
          </span>
        )}
      </div>
      {confirming && (
        <p className="text-sm text-muted">
          This takes the {service.name}: section out of config.yml, and {service.name} out of every webhook event. The old file goes to System → Backup.
        </p>
      )}
      <Outcome verdict={outcome.verdict} problem={outcome.problem} note={outcome.note} />
    </form>
  );
}

// --- Webhook events -----------------------------------------------------------------

function TargetHeading({ target }: { target: WebhookTarget }) {
  return (
    <span className="flex flex-col items-center gap-1">
      <span className={target.kind === "url" ? "max-w-48 break-all font-mono text-xs" : ""}>{target.label}</span>
      {target.kind === "studio" && <Tag>Locked: {STUDIO_MARK}</Tag>}
      {target.kind === "service" && !target.configured && <Tag tone="warn">not set up</Tag>}
    </span>
  );
}

type Outcomes = ReturnType<typeof useOutcome>;

// Remounted whenever the saved events change (see WebhookEvents), so it always starts from config.yml.
function WebhookGrid({ state, outcome }: { state: NotificationsState; outcome: Outcomes }) {
  const queryClient = useQueryClient();
  const [targets, setTargets] = useState<WebhookTarget[]>(state.webhooks.targets);
  const [chosen, setChosen] = useState(state.webhooks.events);
  const [newUrl, setNewUrl] = useState("");
  const save = useMutation({
    // Studio's own entries aren't sent: the server keeps them as they are.
    mutationFn: () =>
      api.notifications.saveWebhooks(
        Object.fromEntries(events.map(({ event }) => [event, chosen[event].filter((id) => id !== "studio")])) as Record<WebhookEvent, string[]>,
        state.hash,
      ),
    onMutate: outcome.clear,
    onSuccess: (data) => {
      queryClient.setQueryData(["notifications"], data);
      outcome.saved(data);
    },
    onError: outcome.refused,
  });
  const dirty = JSON.stringify(chosen) !== JSON.stringify(state.webhooks.events);
  const urlOk = /^https?:\/\/[^\s<>/]+/.test(newUrl.trim());

  const toggle = (event: WebhookEvent, id: string) => {
    const current = chosen[event];
    setChosen({ ...chosen, [event]: current.includes(id) ? current.filter((t) => t !== id) : [...current, id] });
    outcome.clear();
  };
  const addUrl = () => {
    const url = newUrl.trim();
    if (!targets.some((t) => t.id === url)) setTargets([...targets.filter((t) => t.kind !== "studio"), { id: url, label: url, kind: "url", configured: true }, ...targets.filter((t) => t.kind === "studio")]);
    setNewUrl("");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (dirty) save.mutate();
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Webhook events">
      <p className="text-sm text-muted">
        Tick where each of Kometa's events goes. A service needs setting up above before Kometa can use it; a URL gets Kometa's JSON (Discord and Slack webhook
        URLs get a message in their own format). Studio's own entries record each run's changes for Activity → History; Studio adds them before every run, so
        they can't be changed here.
      </p>
      {targets.length === 0 ? (
        <p className="text-sm text-muted">Nothing to send to yet: set up a service above, or add a URL.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="py-2 pr-3 text-left font-normal text-muted">
                  When
                </th>
                {targets.map((target) => (
                  <th key={target.id} scope="col" className="px-2 py-2 text-center font-normal">
                    <TargetHeading target={target} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map(({ event, label }) => (
                <tr key={event} className="border-b border-border last:border-0">
                  <th scope="row" className="py-1 pr-3 text-left font-normal">
                    {label} <span className="font-mono text-xs text-muted">{event}</span>
                  </th>
                  {targets.map((target) => {
                    const locked = target.kind === "studio";
                    return (
                      <td key={target.id} className="px-2 py-1 text-center">
                        <label className="inline-flex min-h-11 min-w-11 items-center justify-center">
                          <input
                            type="checkbox"
                            className="size-4 accent-accent"
                            checked={chosen[event].includes(target.id)}
                            disabled={locked || save.isPending}
                            onChange={() => toggle(event, target.id)}
                            aria-label={`${event} → ${target.label}${locked ? ` (${STUDIO_MARK})` : ""}`}
                          />
                        </label>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 basis-64">
            <Field label="Add a webhook URL">
              <input
                className={inputClass}
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (urlOk) addUrl();
                  }
                }}
                placeholder="https://discord.com/api/webhooks/…"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          </div>
          <Button onClick={addUrl} disabled={!urlOk}>
            Add URL
          </Button>
        </div>
        <span className="text-xs text-muted">A complete http:// or https:// address, such as a Discord channel's webhook. It becomes a column above.</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? "Kometa is checking…" : "Save"}
        </Button>
        <Button onClick={() => setChosen(state.webhooks.events)} disabled={!dirty || save.isPending}>
          Undo my changes
        </Button>
        {dirty && <span className="text-sm text-muted">Unsaved changes</span>}
      </div>
      <p className="text-xs text-muted">A library's own webhooks (its changes event) stay as they are in config.yml.</p>
    </form>
  );
}

function WebhookEvents({ state }: { state: NotificationsState }) {
  const queryClient = useQueryClient();
  const outcome = useOutcome(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }));
  return (
    <div className="flex flex-col gap-4">
      <WebhookGrid key={JSON.stringify(state.webhooks)} state={state} outcome={outcome} />
      <Outcome verdict={outcome.verdict} problem={outcome.problem} note={outcome.note} />
    </div>
  );
}

// --- Adding a service -------------------------------------------------------------

function AddProvider({ services, hash, notice, onAdded }: { services: NotificationService[]; hash: string | null; notice: string | null; onAdded: (service: NotificationService) => void }) {
  const [picked, setPicked] = useState<NotificationServiceName | null>(null);
  const choice = services.find((service) => service.name === picked) ?? null;
  return (
    <Card title="Add notification provider">
      {notice && (
        <p role="status" className="mb-3 text-sm text-muted">
          {notice}
        </p>
      )}
      {choice ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{choice.label}</h3>
            <button type="button" className="min-h-11 text-sm text-muted underline hover:text-text" onClick={() => setPicked(null)}>
              Choose another
            </button>
          </div>
          <ServiceForm key={choice.name} service={choice} hash={hash} onSaved={() => onAdded(choice)} />
        </div>
      ) : (
        <fieldset>
          <legend className="mb-2 text-sm text-muted">Pick one to set up. It's saved once its test passes.</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {services.map((service) => (
              <button
                key={service.name}
                type="button"
                className="flex min-h-11 flex-col items-start gap-0.5 rounded-control border border-border-strong p-3 text-left hover:border-accent"
                onClick={() => setPicked(service.name)}
              >
                <span className="font-semibold">{service.label}</span>
                <span className="text-xs text-muted">{help[service.name].summary}</span>
              </button>
            ))}
          </div>
        </fieldset>
      )}
    </Card>
  );
}

// --- Page ---------------------------------------------------------------------------

export function SettingsNotifications() {
  const state = useQuery({ queryKey: ["notifications"], queryFn: api.notifications.get });
  // What just happened, said where it shows: on the new service's card, or on the Add card after a removal.
  const [added, setAdded] = useState<NotificationServiceName | null>(null);
  const [removed, setRemoved] = useState<string | null>(null);

  if (state.isPending) return <p className="text-muted">Loading…</p>;
  if (state.isError)
    return (
      <p role="alert" className="text-err">
        {state.error.message}
      </p>
    );
  const data = state.data;
  const configured = data.services.filter((service) => service.configured);
  const remaining = data.services.filter((service) => !service.configured);

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      {data.error && (
        <p role="alert" className="text-err">
          {data.error}
        </p>
      )}
      {configured.map((service) => (
        <Card key={service.name} title={service.label} actions={<Tag tone="ok">Set up in config.yml</Tag>}>
          {added === service.name && (
            <p role="status" className="mb-3 text-sm text-ok">
              {service.label} is set up. Kometa uses it from its next run; pick the events it gets under Webhook events.
            </p>
          )}
          <ServiceForm
            service={service}
            hash={data.hash}
            onRemoved={() => {
              setAdded(null);
              setRemoved(`${service.label} was taken out of config.yml. The old file is in System → Backup.`);
            }}
          />
        </Card>
      ))}
      {remaining.length > 0 && (
        <AddProvider
          key={remaining.map((service) => service.name).join()}
          services={remaining}
          hash={data.hash}
          notice={removed}
          onAdded={(service) => {
            setRemoved(null);
            setAdded(service.name);
          }}
        />
      )}
      <Card title="Webhook events">
        <WebhookEvents state={data} />
      </Card>
    </div>
  );
}
