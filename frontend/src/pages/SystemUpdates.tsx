// System → Updates: the installed Kometa and Studio, and what Kometa's last run said about new versions (handoff v2 §8).

import { useQuery } from "@tanstack/react-query";

import { api, type KometaUpdates } from "../api";
import { Card } from "../components/ui";
import { formatTime } from "../runs";

function KometaVersion({ updates }: { updates: KometaUpdates }) {
  if (!updates.installed) return <p className="text-sm text-muted">Studio doesn't know where Kometa is installed.</p>;
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        Installed: <span className="font-mono">{updates.installed}</span>
      </p>
      {updates.available ? (
        <div className="rounded-control border border-info/40 p-3">
          <p className="font-semibold text-info">Kometa {updates.latest} is out.</p>
          {updates.notes && <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap font-mono text-xs text-muted">{updates.notes}</pre>}
        </div>
      ) : updates.checked_at ? (
        <p className="text-ok">Up to date when Kometa last checked ({formatTime(updates.checked_at)}).</p>
      ) : (
        <p className="text-muted">Not checked yet. Kometa looks for a new version each time it runs.</p>
      )}
      <p className="text-muted">
        Kometa comes with Studio's Docker image, so you update it by updating the image: pull the new Kometa Studio image and recreate the
        container. Your config folder, schedules and history stay.
      </p>
    </div>
  );
}

export function SystemUpdates() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  if (status.isPending) return <p className="text-muted">Loading…</p>;
  if (status.isError)
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {status.error.message}
      </p>
    );
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <Card title="Kometa">
        <KometaVersion updates={status.data.kometa.updates} />
      </Card>
      <Card title="Kometa Studio">
        <p className="text-sm">
          Installed: <span className="font-mono">{status.data.version}</span>
        </p>
      </Card>
    </div>
  );
}
