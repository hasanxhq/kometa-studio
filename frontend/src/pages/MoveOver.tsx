// Move over from Kometa: a six-step walkthrough that reports what Studio will take over, then switches.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiError, api } from "../api";
import { FileBlock } from "../components/ImportLanding";
import { Button, Card, Checkbox, StickyActions, Tag } from "../components/ui";
import { importApi, type ImportReport, type LibraryReport, type SwitchOver } from "../importApi";
import { requestsApi } from "../requestsApi";
import { formatTime } from "../runs";

const STEPS = ["Connections", "Libraries", "Collections", "Overlays", "Schedules & more", "Switch over"] as const;

function StepNav({ step, onStep }: { step: number; onStep: (n: number) => void }) {
  return (
    <ol className="flex flex-wrap gap-2 text-sm">
      {STEPS.map((label, index) => {
        const n = index + 1;
        const current = n === step;
        return (
          <li key={label}>
            <button
              type="button"
              className={`min-h-11 rounded-control border px-3 ${current ? "border-accent text-accent" : "border-border text-muted hover:border-muted hover:text-text"}`}
              aria-current={current ? "step" : undefined}
              onClick={() => onStep(n)}
            >
              {n}. {label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function ConnectionRow({ name, connected, to }: { name: string; connected: boolean; to: string }) {
  return (
    <li className="flex min-h-11 flex-wrap items-center gap-2 border-b border-border py-2 last:border-0">
      <span className="min-w-0 flex-1 font-semibold">{name}</span>
      <Tag tone={connected ? "ok" : "warn"}>{connected ? "Connected" : "Not set up"}</Tag>
      <Link className="text-sm underline" to={to}>
        Settings
      </Link>
    </li>
  );
}

function ConnectionsStep({ canContinue }: { canContinue: (ok: boolean) => void }) {
  const setup = useQuery({ queryKey: ["config", "setup"], queryFn: api.config.setup, retry: false });
  const services = useQuery({ queryKey: ["services"], queryFn: api.services.get });
  const arr = useQuery({ queryKey: ["arr"], queryFn: api.arr.get });
  const tautulli = useQuery({ queryKey: ["tautulli"], queryFn: api.tautulli.get });
  const requests = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });

  const loading = setup.isPending || services.isPending || arr.isPending || tautulli.isPending || requests.isPending;
  const error = setup.error ?? services.error ?? arr.error ?? tautulli.error ?? requests.error;

  const plex = setup.data?.plex ?? false;
  const tmdb = Boolean(services.data?.tmdb.apikey) || (setup.data?.tmdb ?? false);

  useEffect(() => {
    canContinue(plex && tmdb);
  }, [canContinue, plex, tmdb]);

  if (loading) return <p className="text-muted">Loading…</p>;
  if (error)
    return (
      <p role="alert" className="text-err">
        {error.message}
      </p>
    );

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">Plex and TMDb are required to go on. The rest can wait.</p>
      <ul>
        <ConnectionRow name="Plex" connected={plex} to="/settings/plex" />
        <ConnectionRow name="TMDb" connected={tmdb} to="/settings/connect" />
        <ConnectionRow name="MDBList" connected={Boolean(services.data?.mdblist.apikey)} to="/settings/connect" />
        <ConnectionRow name="Radarr" connected={Boolean(arr.data?.connections.radarr.url)} to="/settings/connect" />
        <ConnectionRow name="Sonarr" connected={Boolean(arr.data?.connections.sonarr.url)} to="/settings/connect" />
        <ConnectionRow name="Tautulli" connected={Boolean(tautulli.data?.url)} to="/settings/connect" />
        <ConnectionRow name="Seerr" connected={Boolean(requests.data?.connected.seerr)} to="/settings/requests" />
      </ul>
      {!(plex && tmdb) && <p className="text-sm text-warn">Connect Plex and TMDb before continuing.</p>}
    </div>
  );
}

function LibrariesStep({ report }: { report: ImportReport }) {
  if (!report.config) {
    return <p className="text-sm text-muted">Kometa's config.yml doesn't exist yet. Add libraries in Settings after you finish first-run setup.</p>;
  }
  if (report.libraries.length === 0) {
    return (
      <p className="text-sm text-muted">
        No libraries in config.yml yet.{" "}
        <Link className="underline" to="/libraries">
          Libraries
        </Link>
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Libraries already in Kometa's config. Change them on{" "}
        <Link className="underline" to="/libraries">
          Libraries
        </Link>
        .
      </p>
      <ul>
        {report.libraries.map((library) => (
          <LibraryRow key={library.name} library={library} />
        ))}
      </ul>
    </div>
  );
}

function LibraryRow({ library }: { library: LibraryReport }) {
  return (
    <li className="flex min-h-11 flex-wrap items-center gap-2 border-b border-border py-2 last:border-0">
      <span className="min-w-0 flex-1 break-words font-semibold">{library.name}</span>
      {library.type && <span className="text-sm text-muted">{library.type}</span>}
      {library.error ? <span className="text-sm text-err">{library.error}</span> : null}
      <Link className="text-sm underline" to="/libraries">
        Libraries
      </Link>
    </li>
  );
}

function CollectionsStep({ report }: { report: ImportReport }) {
  if (!report.config) {
    return <p className="text-sm text-muted">Kometa's config.yml doesn't exist yet.</p>;
  }
  const { summary } = report;
  const empty = summary.collections === 0;
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-wrap gap-3 text-sm">
        <li>
          <Tag tone="ok">Imported</Tag> {summary.imported}
        </li>
        <li>
          <Tag tone="info">Ready-made</Tag> {summary.ready_made}
        </li>
        <li>
          <Tag>Kept</Tag> {summary.kept}
        </li>
        <li className="text-muted">
          Importable, kept with its file: {summary.kept_with_file}
        </li>
        <li className="text-muted">Already in Studio: {summary.already_studio}</li>
      </ul>
      {empty ? (
        <p className="text-sm text-muted">Nothing to move over: your Kometa files have no collections.</p>
      ) : (
        report.libraries.map((library) => (
          <div key={library.name} className="flex flex-col gap-2">
            <h3 className="font-semibold">{library.name}</h3>
            {library.files.length === 0 ? (
              <p className="text-sm text-muted">No collection files.</p>
            ) : (
              library.files.map((file) => <FileBlock key={`${file.kind}:${file.value}:${file.path ?? ""}`} file={file} />)
            )}
          </div>
        ))
      )}
    </div>
  );
}

function OverlaysStep({ report }: { report: ImportReport }) {
  if (!report.config || report.libraries.length === 0) {
    return <p className="text-sm text-muted">No libraries yet.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        Stay as they are. Change them in{" "}
        <Link className="underline" to="/overlays">
          Overlays
        </Link>
        .
      </p>
      <ul>
        {report.libraries.map((library) => (
          <li key={library.name} className="border-b border-border py-2 last:border-0">
            <div className="font-semibold">{library.name}</div>
            {library.overlay_files.length === 0 ? (
              <p className="text-sm text-muted">No overlay files.</p>
            ) : (
              <ul className="mt-1 font-mono text-xs text-muted">
                {library.overlay_files.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SchedulesStep() {
  const requests = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });
  const enabled = requests.data?.settings.enabled ?? false;
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        Set when Kometa runs on{" "}
        <Link className="underline" to="/system/tasks">
          Schedules
        </Link>
        .
      </p>
      <p>
        Wire up Notifiarr, Gotify, ntfy or Apprise in{" "}
        <Link className="underline" to="/settings/notifications">
          Settings → Notifications
        </Link>
        .
      </p>
      <p>
        Missing-media requests stay off unless you turn them on in{" "}
        <Link className="underline" to="/settings/requests">
          Settings → Requests
        </Link>
        {requests.isPending ? "." : enabled ? " (currently on)." : " (currently off)."}
      </p>
    </div>
  );
}

function SwitchOverStep({ report, active }: { report: ImportReport; active: SwitchOver | null }) {
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const switchOver = useMutation({
    mutationFn: importApi.doSwitchOver,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["import"] });
    },
  });

  if (active) {
    return (
      <div className="flex flex-col gap-3 text-sm">
        <p role="status" className="text-ok">
          Switched over on {formatTime(active.created_at)}.
        </p>
        <p>
          <Link className="underline" to="/collections">
            Collections
          </Link>
          {active.run_id !== null && (
            <>
              {" · "}
              <Link className="underline" to={`/activity/queue/${active.run_id}`}>
                Open the run
              </Link>
            </>
          )}
        </p>
        <p className="text-muted">
          Undo or export the moved-over files on{" "}
          <Link className="underline" to="/system/backup">
            System → Backup
          </Link>
          .
        </p>
      </div>
    );
  }

  if (switchOver.isSuccess) {
    const { run_id } = switchOver.data;
    return (
      <div className="flex flex-col gap-3 text-sm">
        <p role="status" className="text-ok">
          Switched over
        </p>
        <p>
          <Link className="underline" to="/collections">
            Collections
          </Link>
          {run_id !== null && (
            <>
              {" · "}
              <Link className="underline" to={`/activity/queue/${run_id}`}>
                Open the run
              </Link>
            </>
          )}
        </p>
      </div>
    );
  }

  const nothing = report.summary.imported + report.summary.ready_made === 0;
  if (nothing) {
    return <p className="text-sm text-muted">Nothing to import: no collections become Studio's and no Ready-made categories match.</p>;
  }

  const { imported, ready_made, kept } = report.summary;
  const keptFiles = report.summary.files.keep;
  const detail = switchOver.error instanceof ApiError ? switchOver.error.message : switchOver.error?.message;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 text-sm">
        <p>
          {imported} collection{imported === 1 ? "" : "s"} become Studio's, {ready_made} Ready-made categor{ready_made === 1 ? "y" : "ies"}, and {keptFiles} file
          {keptFiles === 1 ? "" : "s"} kept and running as before ({kept} collections kept).
        </p>
        <p className="text-muted">A full backup is taken first. Undo on System → Backup puts every file back.</p>
      </div>
      <Checkbox checked={confirm} onChange={setConfirm}>
        I understand Studio will change my Kometa files
      </Checkbox>
      <Button variant="primary" disabled={!confirm || switchOver.isPending} onClick={() => switchOver.mutate()}>
        {switchOver.isPending ? "Switching…" : "Switch over"}
      </Button>
      {detail && (
        <p role="alert" className="text-err">
          {detail}
        </p>
      )}
    </div>
  );
}

function StepBody({ step, report, active, onConnectionsOk }: { step: number; report: ImportReport; active: SwitchOver | null; onConnectionsOk: (ok: boolean) => void }) {
  switch (step) {
    case 1:
      return <ConnectionsStep canContinue={onConnectionsOk} />;
    case 2:
      return <LibrariesStep report={report} />;
    case 3:
      return <CollectionsStep report={report} />;
    case 4:
      return <OverlaysStep report={report} />;
    case 5:
      return <SchedulesStep />;
    case 6:
      return <SwitchOverStep report={report} active={active} />;
    default:
      return null;
  }
}

export function MoveOver() {
  const [step, setStep] = useState(1);
  const [connectionsOk, setConnectionsOk] = useState(false);
  const report = useQuery({ queryKey: ["import", "report"], queryFn: importApi.report });
  const switchOver = useQuery({ queryKey: ["import", "switch-over"], queryFn: importApi.switchOver });

  if (report.isPending || switchOver.isPending) return <p className="text-muted">Loading…</p>;
  if (report.isError)
    return (
      <p role="alert" className="text-err">
        {report.error.message}
      </p>
    );
  if (switchOver.isError)
    return (
      <p role="alert" className="text-err">
        {switchOver.error.message}
      </p>
    );

  const canNext = step === 1 ? connectionsOk : true;
  const atEnd = step >= STEPS.length;

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-muted">Bring an existing Kometa setup into Studio. Nothing is written until you Switch over on the last step.</p>
      <StepNav step={step} onStep={setStep} />
      <Card title={`${step}. ${STEPS[step - 1]}`}>
        <StepBody step={step} report={report.data} active={switchOver.data.active} onConnectionsOk={setConnectionsOk} />
      </Card>
      <StickyActions>
        <Button disabled={step <= 1} onClick={() => setStep((s) => s - 1)}>
          Back
        </Button>
        {!atEnd && (
          <Button variant="primary" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            Next
          </Button>
        )}
        {atEnd && (
          <Link className="text-sm text-muted underline" to="/system/backup">
            System → Backup
          </Link>
        )}
      </StickyActions>
    </div>
  );
}
