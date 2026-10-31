// Settings → Kometa: where Kometa is, how runs are limited, and the flags this Kometa has (handoff v2 §8).
// Those are set by the container's environment, so this page shows them; Kometa's own settings: block is a form.

import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { KometaSettings } from "../components/KometaSettings";
import { Card } from "../components/ui";

function Row({ label, value, env }: { label: string; value: string | null | undefined; env: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
      <dt className="w-44 shrink-0 text-sm text-muted">
        {label}
        <div className="font-mono text-xs">{env}</div>
      </dt>
      <dd className="min-w-0 break-all font-mono text-sm">{value ?? "Not set"}</dd>
    </div>
  );
}

function duration(seconds: number | undefined): string | null {
  if (seconds === undefined) return null;
  return seconds >= 3600 && seconds % 3600 === 0 ? `${seconds / 3600} h` : seconds >= 60 ? `${Math.round(seconds / 60)} min` : `${seconds} s`;
}

export function SettingsKometa() {
  const kometa = useQuery({ queryKey: ["kometa"], queryFn: api.kometa });
  if (kometa.isPending) return <p className="text-muted">Loading…</p>;
  if (kometa.isError)
    return (
      <p role="alert" className="text-err">
        {kometa.error.message}
      </p>
    );
  const { paths, flags, flags_error: flagsError, problem } = kometa.data;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      {problem && (
        <p role="alert" className="rounded-card border border-warn/40 bg-surface p-4 text-sm text-warn">
          {problem}
        </p>
      )}
      <KometaSettings />
      <Card title="Where Kometa is">
        <p className="mb-2 text-sm text-muted">The Docker image sets these. Outside Docker, set the environment variables named under each.</p>
        <dl>
          <Row label="Python" value={paths?.python} env="STUDIO_KOMETA_PYTHON" />
          <Row label="kometa.py" value={paths?.entry} env="STUDIO_KOMETA_ENTRY" />
          <Row label="config.yml" value={paths?.config} env="STUDIO_KOMETA_CONFIG" />
          <Row label="JSON schemas" value={paths?.schemas} env="STUDIO_KOMETA_SCHEMAS" />
        </dl>
      </Card>
      <Card title="Runs">
        <dl>
          <Row label="Stop a run after" value={duration(kometa.data.run_timeout)} env="STUDIO_RUN_TIMEOUT" />
          <Row label="Then force it after" value={duration(kometa.data.kill_after)} env="STUDIO_KILL_AFTER" />
        </dl>
        <p className="mt-2 text-sm text-muted">
          Every run passes --run, --read-only-config and --no-countdown, so Kometa does one pass and leaves its config to Studio. Low priority
          and the other options are chosen per run and per schedule.
        </p>
      </Card>
      <Card title="Flags this Kometa has">
        {flagsError ? (
          <p className="text-sm text-err">Kometa's --help failed: {flagsError}</p>
        ) : flags === null ? (
          <p className="text-sm text-muted">Still asking Kometa…</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {flags.map((flag) => (
              <li key={flag} className="rounded border border-border px-1.5 py-0.5 font-mono text-xs text-muted">
                {flag}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
