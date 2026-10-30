// System → Backup: every save's previous versions, compared with today's files, and restore (handoff v2 §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Backup } from "../api";
import { FileDiff } from "../components/FileDiff";
import { Button, Card, Tag } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";
import { formatTime } from "../runs";

function Compare({ backup, path }: { backup: Backup; path: string }) {
  const file = useQuery({ queryKey: ["backups", backup.id, path], queryFn: () => api.backups.file(backup.id, path) });
  if (file.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (file.isError) return <p className="text-sm text-err">{file.error.message}</p>;
  if (file.data.current === null) return <p className="text-sm text-muted">This file doesn't exist any more. Restoring brings it back.</p>;
  return <FileDiff before={file.data.backup} after={file.data.current} labels={["in this backup", "now"]} />;
}

function BackupRow({ backup }: { backup: Backup }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const restore = useMutation({
    mutationFn: () => api.backups.restore(backup.id),
    onSuccess: () => {
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  return (
    <li className="flex flex-col gap-3 border-b border-border py-4 last:border-0">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4">
        <span className="shrink-0 text-sm text-muted sm:w-44">{formatTime(backup.created)}</span>
        <span className="min-w-0 flex-1 break-words">{backup.reason}</span>
        {confirming ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-warn">Put these files back? Today's versions are backed up first.</span>
            <Button variant="primary" onClick={() => restore.mutate()} disabled={restore.isPending}>
              {restore.isPending ? "Restoring…" : "Restore"}
            </Button>
            <Button onClick={() => setConfirming(false)}>Cancel</Button>
          </span>
        ) : (
          <Button onClick={() => setConfirming(true)} className="self-start">
            Restore…
          </Button>
        )}
      </div>
      <ul className="flex flex-wrap gap-2">
        {backup.files.map((path) => (
          <li key={path}>
            <button
              type="button"
              className={`min-h-11 rounded-control border px-3 font-mono text-xs ${open === path ? "border-accent text-accent" : "border-border-strong hover:border-muted"}`}
              aria-expanded={open === path}
              onClick={() => setOpen(open === path ? null : path)}
            >
              {path} · compare
            </button>
          </li>
        ))}
        {backup.new_files.map((path) => (
          <li key={path} className="flex min-h-11 items-center gap-2 font-mono text-xs text-muted">
            {path} <Tag>new then; restoring removes it</Tag>
          </li>
        ))}
      </ul>
      {open && <Compare backup={backup} path={open} />}
      {restore.isError && (
        <p role="alert" className="text-err">
          {restore.error.message}
        </p>
      )}
      {restore.isSuccess && (
        <ValidationReport
          validation={restore.data.validation}
          verdict={`Restored ${[...restore.data.restored, ...restore.data.removed.map((p) => `${p} (removed)`)].join(", ")}. ${
            restore.data.validation.ok ? "Kometa's check of the files now passes." : "Kometa's check of the files now reports problems:"
          }`}
        />
      )}
    </li>
  );
}

export function SystemBackup() {
  const list = useQuery({ queryKey: ["backups"], queryFn: api.backups.list });
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <Card title="Config backups">
        <p className="mb-2 text-sm text-muted">
          Before Studio writes any of Kometa's files, it keeps the previous versions here
          {list.data ? ` (the newest ${list.data.keep})` : ""}. Restoring is always allowed, and is itself backed up, so it can be undone.
        </p>
        {list.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : list.isError ? (
          <p role="alert" className="text-err">
            {list.error.message}
          </p>
        ) : list.data.backups.length === 0 ? (
          <p className="text-muted">No backups yet. One is taken the first time Studio saves a file.</p>
        ) : (
          <ul>
            {list.data.backups.map((backup) => (
              <BackupRow key={backup.id} backup={backup} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
