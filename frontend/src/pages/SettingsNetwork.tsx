// Settings → Network (feedback round 1): a proxy, DNS over HTTPS for chosen services and IPv4 first, for
// Studio's calls and Kometa's alike, and a connection check. Like the rest of Settings, the proxy and DNS
// over HTTPS are saved only after a passing test.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, type NetworkCheck, type NetworkState, type ProxyInput } from "../api";
import { Button, Card, Field, Tag, inputClass } from "../components/ui";

type ProxyKind = "none" | "http" | "https" | "socks5";

function Outcome({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span role={ok ? "status" : "alert"} className={`text-sm ${ok ? "text-ok" : "text-err"}`}>
      {children}
    </span>
  );
}

function splitProxy(url: string | null): { kind: ProxyKind; address: string } {
  const match = url?.match(/^(https?|socks5h?):\/\/(.+)$/);
  if (!match) return { kind: "none", address: "" };
  return { kind: (match[1] === "socks5h" ? "socks5" : match[1]) as ProxyKind, address: match[2] };
}

function ProxyForm({ state }: { state: NetworkState }) {
  const queryClient = useQueryClient();
  const initial = splitProxy(state.proxy_url);
  const [kind, setKind] = useState<ProxyKind>(initial.kind);
  const [address, setAddress] = useState(initial.address);
  const [login, setLogin] = useState(state.proxy_username !== null);
  const [username, setUsername] = useState(state.proxy_username ?? "");
  const [password, setPassword] = useState("");
  const [noProxy, setNoProxy] = useState(state.no_proxy.join("\n"));
  const body = (): ProxyInput => ({
    url: kind === "none" ? null : `${kind}://${address.trim()}`,
    username: kind !== "none" && login ? username || null : null,
    password: kind !== "none" && login ? password || null : null,
    no_proxy: noProxy.split(/[\n,]+/).map((entry) => entry.trim()).filter(Boolean),
  });
  const test = useMutation({ mutationFn: () => api.network.testProxy(body()) });
  const save = useMutation({ mutationFn: () => api.network.saveProxy(body()), onSuccess: (data) => queryClient.setQueryData(["network"], data) });
  const changed = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    test.reset();
    save.reset();
  };
  const tested = test.data?.ok === true;
  const canSave = kind === "none" ? state.proxy_url !== null || noProxy !== state.no_proxy.join("\n") : tested;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="Proxy">
      <p className="text-sm text-muted">
        For Studio's calls and Kometa's alike. The proxy looks names up itself, so it also gets round a network whose DNS blocks a service. Kometa doesn't
        need anything installed for SOCKS5: Studio gives it what it needs.
      </p>
      <div className="flex flex-wrap gap-3">
        <Field label="Proxy">
          <select className={`${inputClass} w-36`} value={kind} onChange={(e) => changed(setKind)(e.target.value as ProxyKind)}>
            <option value="none">None</option>
            <option value="http">HTTP</option>
            <option value="https">HTTPS</option>
            <option value="socks5">SOCKS5</option>
          </select>
        </Field>
        {kind !== "none" && (
          <div className="min-w-0 flex-1 basis-56">
            <Field label="Address" hint="host:port">
              <input className={inputClass} value={address} onChange={(e) => changed(setAddress)(e.target.value)} placeholder="proxy.example.com:3128" spellCheck={false} />
            </Field>
          </div>
        )}
      </div>
      {kind !== "none" && (
        <>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-accent" checked={login} onChange={(e) => changed(setLogin)(e.target.checked)} />
            The proxy asks for a login
          </label>
          {login && (
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
                    placeholder={state.has_password ? "Saved (leave empty to keep it)" : ""}
                  />
                </Field>
              </div>
            </div>
          )}
          <Field label="Don't use the proxy for" hint={`One per line, or separated by commas: a host, a domain (.example.com) or a network (100.64.0.0/10). Always direct: ${state.local.join(", ")}.`}>
            <textarea className={`${inputClass} min-h-20 py-2`} value={noProxy} onChange={(e) => changed(setNoProxy)(e.target.value)} spellCheck={false} />
          </Field>
        </>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {kind !== "none" && (
          <Button onClick={() => test.mutate()} disabled={test.isPending || !address.trim()}>
            {test.isPending ? "Testing…" : "Test"}
          </Button>
        )}
        <Button variant="primary" type="submit" disabled={!canSave || save.isPending} title={kind !== "none" && !tested ? "Test the proxy first" : undefined}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {test.data && (test.data.ok ? <Outcome ok>Works: the internet sees Studio as {test.data.ip}.</Outcome> : <Outcome ok={false}>{test.data.error}</Outcome>)}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved.</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
      </div>
    </form>
  );
}

function DohForm({ state }: { state: NetworkState }) {
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState(state.doh_provider);
  const [services, setServices] = useState<string[]>(state.doh_services);
  const test = useMutation({ mutationFn: () => api.network.testDoh(provider, services) });
  const save = useMutation({ mutationFn: () => api.network.saveDoh(provider, services), onSuccess: (data) => queryClient.setQueryData(["network"], data) });
  const reset = () => {
    test.reset();
    save.reset();
  };
  const toggle = (id: string) => {
    setServices(services.includes(id) ? services.filter((s) => s !== id) : [...services, id]);
    reset();
  };
  const changed = provider !== state.doh_provider || JSON.stringify([...services].sort()) !== JSON.stringify([...state.doh_services].sort());
  const tested = test.data?.ok === true;
  const canSave = changed && (services.length === 0 || tested);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };
  return (
    <form className="flex flex-col gap-4" onSubmit={submit} aria-label="DNS over HTTPS">
      <p className="text-sm text-muted">
        Look the ticked services up through DNS over HTTPS instead of this network's DNS, for Studio's calls and Kometa's. Calls that go through the proxy
        don't need it.
      </p>
      <Field label="Provider">
        <select
          className={`${inputClass} w-56`}
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value as NetworkState["doh_provider"]);
            reset();
          }}
        >
          {state.providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>
      <fieldset>
        <legend className="mb-1 text-sm text-muted">Services</legend>
        <div className="grid gap-x-4 sm:grid-cols-2">
          {state.services.map((service) => (
            <label key={service.id} className="flex min-h-11 items-center gap-2 text-sm" title={service.domains.join(", ")}>
              <input type="checkbox" className="size-4 accent-accent" checked={services.includes(service.id)} onChange={() => toggle(service.id)} />
              {service.name}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        {services.length > 0 && (
          <Button onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? "Testing…" : "Test"}
          </Button>
        )}
        <Button variant="primary" type="submit" disabled={!canSave || save.isPending} title={services.length && !tested ? "Test first" : undefined}>
          Save
        </Button>
        {test.data &&
          (test.data.ok ? (
            <Outcome ok>
              Found{" "}
              {Object.entries(test.data.found)
                .map(([id, ip]) => `${state.services.find((s) => s.id === id)?.name ?? id} at ${ip}`)
                .join(", ")}
              .
            </Outcome>
          ) : (
            <Outcome ok={false}>{test.data.error}</Outcome>
          ))}
        {test.isError && <Outcome ok={false}>{test.error.message}</Outcome>}
        {save.isSuccess && <Outcome ok>Saved.</Outcome>}
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
      </div>
    </form>
  );
}

function Ipv4Form({ state }: { state: NetworkState }) {
  const queryClient = useQueryClient();
  const [prefer, setPrefer] = useState(state.prefer_ipv4);
  const save = useMutation({ mutationFn: () => api.network.saveIpv4(prefer), onSuccess: (data) => queryClient.setQueryData(["network"], data) });
  return (
    <form
      className="flex flex-col gap-3"
      aria-label="IPv4 first"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label className="flex min-h-11 items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1 size-4 accent-accent" checked={prefer} onChange={(e) => setPrefer(e.target.checked)} />
        <span>
          Try IPv4 first
          <span className="block text-xs text-muted">For networks where IPv6 is broken and calls hang until they time out. Studio then uses IPv4 only.</span>
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={prefer === state.prefer_ipv4 || save.isPending}>
          Save
        </Button>
        {save.isError && <Outcome ok={false}>{save.error.message}</Outcome>}
      </div>
    </form>
  );
}

function Check() {
  const check = useMutation({ mutationFn: api.network.check });
  const rows: NetworkCheck[] = check.data?.results ?? [];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Studio tries each service Kometa and Studio use, the way it makes its own calls. Kometa runs from here too, so it fares the same. Each one shows what
        this network's DNS says and what DNS over HTTPS says.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => check.mutate()} disabled={check.isPending}>
          {check.isPending ? "Checking…" : "Check connections"}
        </Button>
        {check.isError && <Outcome ok={false}>{check.error.message}</Outcome>}
      </div>
      {rows.length > 0 && (
        <ul className="flex flex-col">
          {rows.map((row) => (
            <li key={row.url} className="flex flex-col gap-1 border-b border-border py-3 text-sm last:border-0" aria-label={row.name}>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="font-semibold">{row.name}</span>
                <span className={row.ok ? "text-ok" : "text-err"}>{row.verdict}</span>
                {row.ok && (
                  <span className="text-xs text-muted">
                    HTTP {row.status} · {row.ms} ms
                  </span>
                )}
                <Tag>{row.via === "proxy" ? "Through the proxy" : "Direct"}</Tag>
              </div>
              <div className="grid gap-x-4 font-mono text-xs text-muted sm:grid-cols-2">
                <span className="break-all">
                  DNS: {row.system_dns.length ? row.system_dns.join(", ") : (row.system_dns_error ?? "no answer")}
                </span>
                {row.doh_dns !== null || row.doh_dns_error ? (
                  <span className={`break-all ${row.doh_dns && row.system_dns.length && row.doh_dns[0] !== row.system_dns[0] ? "text-warn" : ""}`}>
                    DNS over HTTPS: {row.doh_dns ? row.doh_dns.join(", ") : row.doh_dns_error}
                  </span>
                ) : (
                  <span>DNS over HTTPS: local address</span>
                )}
              </div>
              {!row.ok && row.error && <span className="break-all text-xs text-muted">{row.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SettingsNetwork() {
  const network = useQuery({ queryKey: ["network"], queryFn: api.network.get });
  if (network.isPending) return <p className="text-muted">Loading…</p>;
  if (network.isError)
    return (
      <p role="alert" className="text-err">
        {network.error.message}
      </p>
    );
  const state = network.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Proxy">
        <ProxyForm key={JSON.stringify([state.proxy_url, state.proxy_username, state.no_proxy])} state={state} />
      </Card>
      <Card title="DNS over HTTPS">
        <DohForm key={JSON.stringify([state.doh_provider, state.doh_services])} state={state} />
      </Card>
      <Card title="IPv4 first">
        <Ipv4Form key={String(state.prefer_ipv4)} state={state} />
      </Card>
      <Card title="Connection check">
        <Check />
      </Card>
    </div>
  );
}
