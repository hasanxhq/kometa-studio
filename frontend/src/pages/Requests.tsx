// Libraries → Requests: every missing-title request Studio has filed, with status filters and cancel.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { ConfirmDialog } from "../components/ConfirmDialog";
import { Button, Card, Tag, type Tone } from "../components/ui";
import { formatRelative, formatTime } from "../runs";
import { requestsApi, type RequestRow, type RequestStatus } from "../requestsApi";

const STATUS_FILTERS: { value: RequestStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "requested", label: "Requested" },
  { value: "downloading", label: "Downloading" },
  { value: "imported", label: "Imported" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "exists", label: "Already there" },
];

const STATUS_TONE: Record<RequestStatus, Tone> = {
  requested: "info",
  downloading: "info",
  imported: "ok",
  failed: "err",
  cancelled: "muted",
  exists: "muted",
};

const STATUS_LABEL: Record<RequestStatus, string> = {
  requested: "Requested",
  downloading: "Downloading",
  imported: "Imported",
  failed: "Failed",
  cancelled: "Cancelled",
  exists: "Already there",
};

const VIA_LABEL: Record<string, string> = {
  radarr: "Radarr",
  sonarr: "Sonarr",
  overseerr: "Overseerr",
  jellyseerr: "Jellyseerr",
};

function viaLabel(via: string): string {
  return VIA_LABEL[via] ?? via;
}

function titleLine(row: RequestRow): string {
  const name = row.title?.trim() || row.item;
  return row.year != null ? `${name} (${row.year})` : name;
}

function Row({ row, onCancel }: { row: RequestRow; onCancel: (row: RequestRow) => void }) {
  const canCancel = row.status === "requested" || row.status === "downloading";
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{titleLine(row)}</p>
        <p className="text-xs text-muted">
          {row.library} · {viaLabel(row.via)}
          {row.status === "failed" && row.error ? ` · ${row.error}` : ""}
        </p>
      </div>
      <Tag tone={STATUS_TONE[row.status]}>{STATUS_LABEL[row.status]}</Tag>
      <span className="w-24 shrink-0 text-xs text-muted" title={formatTime(row.requested_at)}>
        {formatRelative(row.requested_at)}
      </span>
      {canCancel && (
        <Button onClick={() => onCancel(row)} className="shrink-0">
          Cancel
        </Button>
      )}
    </li>
  );
}

export function Requests() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<RequestStatus | "">("");
  const [pendingCancel, setPendingCancel] = useState<RequestRow | null>(null);
  const settings = useQuery({ queryKey: ["requests", "settings"], queryFn: requestsApi.settings });
  const list = useQuery({
    queryKey: ["requests", "list", status],
    queryFn: () => requestsApi.list({ status, limit: 200 }),
    refetchInterval: (query) => {
      const rows = query.state.data?.requests ?? [];
      return rows.some((row) => row.status === "requested" || row.status === "downloading") ? 30_000 : false;
    },
  });
  const refresh = useMutation({
    mutationFn: () => requestsApi.refresh(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["requests"] }),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => requestsApi.cancel(id),
    onSuccess: () => {
      setPendingCancel(null);
      queryClient.invalidateQueries({ queryKey: ["requests"] });
    },
  });

  const counts = list.data?.counts;
  const rows = list.data?.requests ?? [];
  const allCount = counts ? Object.values(counts).reduce((sum, n) => sum + n, 0) : null;

  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[32px] leading-tight font-semibold">Requests</h2>
          <p className="mt-1 max-w-xl text-[13px] text-muted">Titles Studio asked Radarr, Sonarr or Overseerr/Jellyseerr to download for your collections.</p>
        </div>
        <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          {refresh.isPending ? "Checking…" : "Check now"}
        </Button>
      </header>

      {settings.data && !settings.data.settings.enabled && (
        <p className="text-sm text-muted">
          Requests are off.{" "}
          <Link className="underline hover:text-text" to="/settings/requests">
            Settings → Requests
          </Link>
        </p>
      )}

      <Card title="Status">
        <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Status filter">
          {STATUS_FILTERS.map((filter) => {
            const count = filter.value === "" ? allCount : counts?.[filter.value];
            const active = status === filter.value;
            return (
              <button
                key={filter.value || "all"}
                type="button"
                aria-pressed={active}
                className={`inline-flex min-h-9 items-center gap-1.5 rounded-control border px-3 text-sm ${
                  active ? "border-accent bg-surface-2 text-text" : "border-border text-muted hover:text-text"
                }`}
                onClick={() => setStatus(filter.value)}
              >
                {filter.label}
                {count != null && <span className="text-xs text-muted">{count}</span>}
              </button>
            );
          })}
        </div>

        {list.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : list.isError ? (
          <p role="alert" className="text-err">
            {list.error.message}
          </p>
        ) : rows.length === 0 ? (
          <p className="text-muted">Nothing requested yet.</p>
        ) : (
          <ul aria-label="Requests">
            {rows.map((row) => (
              <Row key={row.id} row={row} onCancel={setPendingCancel} />
            ))}
          </ul>
        )}
        {refresh.isError && (
          <p role="alert" className="mt-3 text-sm text-err">
            {refresh.error.message}
          </p>
        )}
        {cancel.isError && (
          <p role="alert" className="mt-3 text-sm text-err">
            {cancel.error.message}
          </p>
        )}
      </Card>

      {pendingCancel && (
        <ConfirmDialog
          title="Stop requesting"
          confirm="Stop requesting"
          danger
          busy={cancel.isPending}
          onConfirm={() => cancel.mutate(pendingCancel.id)}
          onCancel={() => setPendingCancel(null)}
        >
          Stop requesting {titleLine(pendingCancel)}? Studio unmonitors it in Radarr/Sonarr (or removes the Overseerr request). Nothing is deleted.
        </ConfirmDialog>
      )}
    </div>
  );
}
