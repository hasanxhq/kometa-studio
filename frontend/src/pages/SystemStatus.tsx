import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0 sm:flex-row sm:gap-4">
      <dt className="w-40 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 break-words font-mono text-sm">{value}</dd>
    </div>
  );
}

export function SystemStatus() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });

  if (status.isPending) {
    return <p className="text-muted">Loading…</p>;
  }
  if (status.isError) {
    return (
      <p role="alert" className="text-err">
        Can't reach the Studio API: {status.error.message}
      </p>
    );
  }

  const { version, kometa, database } = status.data;
  return (
    <section className="max-w-2xl rounded-card border border-border bg-surface px-6 py-3">
      <h2 className="py-2 text-base font-semibold">About</h2>
      <dl>
        <Row label="Studio" value={version} />
        <Row label="Kometa" value={kometa.version ?? "Not configured"} />
        <Row label="Kometa config" value={kometa.config ?? "Not configured"} />
        <Row label="Database schema" value={`v${database.schema_version}`} />
      </dl>
    </section>
  );
}
