// First-run setup: what Kometa can't run without, in order (Plex, TMDb, a library), then sign-in, which it can.
// Each step is the form Settings uses, so there's one of each. Overview sends a new install here, and Health links
// here while anything is missing.

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { AddLibrary } from "../components/AddLibrary";
import { Card, Tag } from "../components/ui";
import { libraryTypeLabels, mergeLibraries } from "../libraries";
import { ServiceForm, services } from "./SettingsConnect";
import { SignIn } from "./SettingsGeneral";
import { SettingsPlex } from "./SettingsPlex";

function Step({ number, title, done, open, locked, optional, children }: { number: number; title: string; done: boolean; open: boolean; locked?: boolean; optional?: boolean; children: ReactNode }) {
  const heading = (
    <>
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs">{number}</span>
      <span className="min-w-0 flex-1 break-words">{title}</span>
      {done ? <Tag tone="ok">Done</Tag> : optional ? <Tag>Optional</Tag> : locked ? <Tag>After the step above</Tag> : <Tag tone="warn">Needed</Tag>}
    </>
  );
  if (locked) return <div className="flex min-h-11 items-center gap-2 rounded-card border border-border bg-surface p-4 font-semibold text-muted">{heading}</div>;
  return (
    <details open={open} className="rounded-card border border-border bg-surface">
      <summary className="flex min-h-11 cursor-pointer items-center gap-2 p-4 font-semibold">{heading}</summary>
      <div className="border-t border-border p-4">{children}</div>
    </details>
  );
}

function Tmdb() {
  const keys = useQuery({ queryKey: ["services"], queryFn: api.services.get });
  const tmdb = services.find((service) => service.name === "tmdb")!;
  if (keys.isPending) return <p className="text-muted">Loading…</p>;
  if (keys.isError)
    return (
      <p role="alert" className="text-err">
        {keys.error.message}
      </p>
    );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">Kometa won't start without a TMDb key, even for collections that don't use TMDb. The key is free with a TMDb account.</p>
      <ServiceForm key={JSON.stringify(keys.data.tmdb)} {...tmdb} saved={keys.data.tmdb.apikey} />
      <p className="text-xs text-muted">
        If the test can't reach TMDb, your network may be blocking it.{" "}
        <Link className="underline" to="/settings/network">
          Settings → Network
        </Link>{" "}
        has a proxy and DNS over HTTPS.
      </p>
    </div>
  );
}

function Libraries() {
  const plex = useQuery({ queryKey: ["plex", "libraries"], queryFn: api.plexLibraries.list, retry: false, staleTime: 60_000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  if (plex.isPending || config.isPending) return <p className="text-muted">Loading…</p>;
  if (plex.isError)
    return (
      <p role="alert" className="text-err">
        {plex.error.message}
      </p>
    );
  const libraries = mergeLibraries(plex.data.libraries, config.data?.libraries).filter((entry) => entry.plex);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">Pick the Plex libraries Kometa should work on. It needs at least one, and you can add more later.</p>
      {libraries.length === 0 && <p className="text-sm text-warn">This Plex server has no libraries yet.</p>}
      <ul className="flex flex-col">
        {libraries.map((entry) => (
          <li key={entry.name} className="flex min-h-14 flex-wrap items-center gap-2 border-b border-border py-2 last:border-0">
            <span className="min-w-0 flex-1 break-words font-semibold">{entry.name}</span>
            <span className="text-sm text-muted">{libraryTypeLabels[entry.plex!.type] ?? entry.plex!.type}</span>
            {entry.config ? <Tag tone="ok">Added</Tag> : <AddLibrary name={entry.name} variant="secondary" />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SignInStep() {
  const general = useQuery({ queryKey: ["general"], queryFn: api.general.get });
  if (general.isPending) return <p className="text-muted">Loading…</p>;
  if (general.isError)
    return (
      <p role="alert" className="text-err">
        {general.error.message}
      </p>
    );
  return <SignIn settings={general.data} />;
}

function Ready() {
  return (
    <Card title="Kometa is ready to run">
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">It won't do much until a library has something to build, so start with a collection.</p>
        <div className="flex flex-wrap items-center gap-3">
          <Link to="/libraries" className="inline-flex min-h-11 items-center justify-center rounded-control bg-accent px-4 font-medium text-on-accent transition hover:brightness-110">
            Add a collection
          </Link>
          <Link to="/" className="min-h-11 content-center text-muted underline hover:text-text">
            Go to Overview
          </Link>
        </div>
        <p className="text-muted">
          You can do these any time:{" "}
          <Link className="underline" to="/settings/connect">
            connect Radarr, Sonarr, MDBList and Tautulli
          </Link>
          , and{" "}
          <Link className="underline" to="/settings/notifications">
            set up notifications
          </Link>
          .
        </p>
      </div>
    </Card>
  );
}

export function Setup() {
  const setup = useQuery({ queryKey: ["config", "setup"], queryFn: api.config.setup, retry: false });
  const signIn = useQuery({ queryKey: ["general"], queryFn: api.general.get });
  if (setup.isPending) return <p className="text-muted">Loading…</p>;
  if (setup.isError)
    return (
      <p role="alert" className="text-err">
        {setup.error.message}
      </p>
    );
  const { plex, tmdb, library, done } = setup.data;
  const current = !plex ? 1 : !tmdb ? 2 : !library ? 3 : 4;
  const signedIn = signIn.data?.auth.configured ?? false;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-muted">Kometa needs three things before it can run: your Plex server, a TMDb key and at least one library. Studio saves them to Kometa's config.yml.</p>
      {/* Keyed on the step, so each one opens and closes as the one before it is finished. */}
      <Step key={`plex-${current}`} number={1} title="Connect Plex" done={plex} open={current === 1}>
        <SettingsPlex />
      </Step>
      <Step key={`tmdb-${current}`} number={2} title="Add your TMDb key" done={tmdb} open={current === 2} locked={!plex}>
        <Tmdb />
      </Step>
      <Step key={`library-${current}`} number={3} title="Choose your libraries" done={library} open={current === 3} locked={!plex || !tmdb}>
        <Libraries />
      </Step>
      <Step key={`sign-in-${current}`} number={4} title="Protect Studio with a sign-in" done={signedIn} open={current === 4 && !signedIn} optional>
        <SignInStep />
      </Step>
      {done && <Ready />}
    </div>
  );
}
