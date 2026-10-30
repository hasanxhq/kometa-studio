// Settings → Plex: the setup wizard (handoff v2 §4). Sign in with Plex, pick a server
// connection, or type a URL and token. Saving writes plex.url and plex.token into config.yml.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { api, type PlexConnection, type PlexServer, type PlexState } from "../api";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";

// How often to ask whether the user has approved the sign-in. Tests shorten it.
export const signInTiming = { pollMs: 1000 };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
      <dt className="w-32 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-all font-mono text-sm">{children}</dd>
    </div>
  );
}

function CurrentConnection({ state }: { state: PlexState }) {
  const { config } = state;
  return (
    <Card title="Kometa's Plex connection">
      {config.path === null && (
        <p className="mb-2 text-warn">Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG to save a connection.</p>
      )}
      {config.error && (
        <p role="alert" className="mb-2 text-err">
          {config.error}
        </p>
      )}
      <dl>
        <Row label="URL">{config.url ?? <span className="text-muted">Not set</span>}</Row>
        <Row label="Token">{config.token ?? <span className="text-muted">Not set</span>}</Row>
        {config.path && <Row label="Saved in">{config.path}</Row>}
      </dl>
    </Card>
  );
}

// --- Sign in --------------------------------------------------------------------

type SignIn = { kind: "idle" } | { kind: "waiting"; authUrl?: string; popupBlocked?: boolean } | { kind: "failed"; message: string };

function useSignIn(onSignedIn: () => void) {
  const [signIn, setSignIn] = useState<SignIn>({ kind: "idle" });
  const run = useRef(0); // bumped to cancel the polling loop

  useEffect(() => () => void run.current++, []);

  const start = async () => {
    const id = ++run.current;
    // Open the window now, inside the click, or the browser blocks it; point it at Plex once we have the PIN.
    const popup = window.open("", "plex-sign-in", "width=600,height=720");
    setSignIn({ kind: "waiting" });
    try {
      const pin = await api.plex.startSignIn();
      if (popup) popup.location.href = pin.auth_url;
      setSignIn({ kind: "waiting", authUrl: pin.auth_url, popupBlocked: !popup });

      for (;;) {
        await sleep(signInTiming.pollMs);
        if (run.current !== id) return;
        const closed = popup?.closed ?? false;
        const result = await api.plex.pollSignIn(pin.id);
        if (run.current !== id) return;
        if (result.status === "signed_in") {
          popup?.close();
          setSignIn({ kind: "idle" });
          onSignedIn();
          return;
        }
        if (result.status === "expired") {
          popup?.close();
          setSignIn({ kind: "failed", message: "The sign-in code expired. Try again." });
          return;
        }
        if (closed) {
          setSignIn({ kind: "failed", message: "The Plex window was closed before sign-in finished." });
          return;
        }
      }
    } catch (error) {
      popup?.close();
      if (run.current === id) setSignIn({ kind: "failed", message: (error as Error).message });
    }
  };

  const cancel = () => {
    run.current++;
    setSignIn({ kind: "idle" });
  };

  return { signIn, start, cancel };
}

function SignInCard({ onSignedIn }: { onSignedIn: () => void }) {
  const { signIn, start, cancel } = useSignIn(onSignedIn);
  return (
    <Card title="Find your server">
      <p className="mb-4 text-muted">
        Sign in with your Plex account and Studio lists your servers and tests every address it can reach them on. Your password goes
        only to Plex.
      </p>
      {signIn.kind === "waiting" ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="status" className="text-muted">
            {signIn.popupBlocked ? (
              <>
                Your browser blocked the Plex window.{" "}
                <a className="text-accent underline" href={signIn.authUrl} target="_blank" rel="noreferrer">
                  Open the Plex sign-in page
                </a>{" "}
                and approve Kometa Studio there.
              </>
            ) : (
              "Waiting for you to approve Kometa Studio in the Plex window…"
            )}
          </p>
          <Button onClick={cancel}>Cancel</Button>
        </div>
      ) : (
        <>
          <Button variant="primary" onClick={start}>
            Sign in with Plex
          </Button>
          {signIn.kind === "failed" && (
            <p role="alert" className="mt-3 text-err">
              {signIn.message}
            </p>
          )}
        </>
      )}
    </Card>
  );
}

// --- Pick a server ---------------------------------------------------------------

function ConnectionOption({
  connection,
  name,
  checked,
  current,
  onSelect,
}: {
  connection: PlexConnection;
  name: string;
  checked: boolean;
  current: boolean;
  onSelect: () => void;
}) {
  return (
    <label
      className={[
        "flex min-h-11 items-start gap-3 rounded-control border px-3 py-2.5",
        checked ? "border-accent bg-surface-2" : "border-border",
        connection.ok ? "cursor-pointer" : "opacity-70",
      ].join(" ")}
    >
      <input
        type="radio"
        name={name}
        className="mt-1 size-4 accent-accent"
        checked={checked}
        disabled={!connection.ok}
        onChange={onSelect}
      />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="break-all font-mono text-sm">{connection.uri}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <Tag>{connection.local ? "Local" : "Remote"}</Tag>
          <Tag>{connection.secure ? "HTTPS" : "HTTP"}</Tag>
          {connection.relay && <Tag tone="warn">Relay</Tag>}
          {current && <Tag tone="ok">In use</Tag>}
          {connection.ok ? (
            <span className="text-xs text-ok">OK · {connection.latency_ms} ms</span>
          ) : (
            <span className="text-xs text-err">{connection.error}</span>
          )}
        </span>
      </span>
    </label>
  );
}

function ServerChoice({ server, currentUrl, onSaved }: { server: PlexServer; currentUrl: string | null; onSaved: () => void }) {
  const [selected, setSelected] = useState<string | null>(server.best);
  const connect = useMutation({ mutationFn: (uri: string) => api.plex.connect({ server_id: server.id, uri }), onSuccess: onSaved });
  const chosen = server.connections.find((c) => c.uri === selected);
  const [showAll, setShowAll] = useState(false);
  const failed = server.connections.filter((c) => !c.ok).length;
  const visible = showAll ? server.connections : server.connections.filter((c) => c.ok);

  return (
    <div className="rounded-control border border-border-strong p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">{server.name}</h3>
        <span className="text-xs text-muted">Plex Media Server {server.version}</span>
      </div>
      {server.best === null && (
        <p role="alert" className="mb-3 text-err">
          Studio couldn't reach this server on any address. Check it's running, or enter an address below.
        </p>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Address for {server.name}</legend>
        {visible.map((connection) => (
          <ConnectionOption
            key={connection.uri}
            connection={connection}
            name={`server-${server.id}`}
            checked={connection.uri === selected}
            current={connection.uri === currentUrl}
            onSelect={() => setSelected(connection.uri)}
          />
        ))}
      </fieldset>
      {failed > 0 && server.best !== null && (
        <button type="button" className="mt-2 min-h-11 text-sm text-muted underline" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Hide addresses that failed" : `Show ${failed} address${failed === 1 ? "" : "es"} that failed`}
        </button>
      )}
      {chosen?.relay && (
        <p className="mt-3 text-sm text-warn">
          This is a Plex relay. Relays are speed-limited, so overlay runs that download and upload every poster will be slow. Prefer a
          direct address if one works.
        </p>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={!chosen?.ok || connect.isPending} onClick={() => selected && connect.mutate(selected)}>
          {connect.isPending ? "Saving…" : "Use this address"}
        </Button>
        {connect.isSuccess && (
          <span role="status" className="text-sm text-ok">
            Saved to config.yml
          </span>
        )}
        {connect.isError && (
          <span role="alert" className="text-sm text-err">
            {connect.error.message}
          </span>
        )}
      </div>
    </div>
  );
}

function ServersCard({ state, onSaved, onSignedOut }: { state: PlexState; onSaved: () => void; onSignedOut: () => void }) {
  const servers = useQuery({ queryKey: ["plex", "servers"], queryFn: api.plex.servers, staleTime: Infinity, retry: false });
  const signOut = useMutation({ mutationFn: api.plex.signOut, onSuccess: onSignedOut });

  return (
    <Card
      title="Your servers"
      actions={
        <Button onClick={() => servers.refetch()} disabled={servers.isFetching}>
          Test again
        </Button>
      }
    >
      <p className="mb-4 flex flex-wrap items-center gap-x-2 text-sm text-muted">
        Signed in to Plex as {state.account?.name}.
        <button type="button" className="min-h-11 underline hover:text-text" onClick={() => signOut.mutate()}>
          Sign out
        </button>
      </p>
      {servers.isFetching ? (
        <p role="status" className="text-muted">
          Finding your servers and testing each address. This takes up to 5 seconds…
        </p>
      ) : servers.isError ? (
        <p role="alert" className="text-err">
          {servers.error.message}
        </p>
      ) : servers.data?.servers.length === 0 ? (
        <p className="text-muted">This Plex account doesn't own a server. Enter your server's address below instead.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {servers.data?.servers.map((server) => (
            <ServerChoice key={server.id} server={server} currentUrl={state.config.url} onSaved={onSaved} />
          ))}
        </div>
      )}
    </Card>
  );
}

// --- Manual entry ----------------------------------------------------------------

function ManualCard({ onSaved }: { onSaved: () => void }) {
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const test = useMutation({ mutationFn: () => api.plex.test(url, token) });
  const save = useMutation({ mutationFn: () => api.plex.connect({ url, token }), onSuccess: onSaved });
  const ready = url.trim() !== "" && token.trim() !== "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) save.mutate();
  };
  const reset = () => {
    test.reset();
    save.reset();
  };

  return (
    <Card title="Enter an address">
      <p className="mb-4 text-muted">
        For a server behind a reverse proxy, or an address plex.tv doesn't list. Studio tests it before saving.
      </p>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <Field label="Server URL">
          <input
            className={inputClass}
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              reset();
            }}
            placeholder="https://plex.example.com"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field
          label="Plex token"
          hint={
            <a
              className="underline"
              href="https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"
              target="_blank"
              rel="noreferrer"
            >
              How to find your token
            </a>
          }
        >
          <input
            className={inputClass}
            type="password"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              reset();
            }}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!ready || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? "Testing…" : "Test"}
          </Button>
          <Button variant="primary" type="submit" disabled={!ready || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
          {test.data &&
            (test.data.ok ? (
              <span role="status" className="text-sm text-ok">
                Connected to {test.data.name} (Plex {test.data.version})
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
          {save.isSuccess && (
            <span role="status" className="text-sm text-ok">
              Saved to config.yml
            </span>
          )}
          {save.isError && (
            <span role="alert" className="text-sm text-err">
              {save.error.message}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

// --- Page ------------------------------------------------------------------------

export function SettingsPlex() {
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: ["plex"], queryFn: api.plex.state });
  // Only the state query: refetching the server list would re-run every probe.
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["plex"], exact: true });

  if (state.isPending) {
    return <p className="text-muted">Loading…</p>;
  }
  if (state.isError) {
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {state.error.message}
      </p>
    );
  }

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <CurrentConnection state={state.data} />
      {state.data.account ? (
        <ServersCard
          state={state.data}
          onSaved={refresh}
          onSignedOut={() => {
            queryClient.removeQueries({ queryKey: ["plex", "servers"] });
            refresh();
          }}
        />
      ) : (
        <SignInCard onSignedIn={refresh} />
      )}
      <ManualCard onSaved={refresh} />
    </div>
  );
}
