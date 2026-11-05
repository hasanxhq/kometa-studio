// System → Backup: every save's previous versions, compared with today's files, and restore (handoff v2 §8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, type Backup, type FullBackup } from "../api";
import { BuiltinTaskRow, useBuiltinTasks } from "../components/BuiltinTasks";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FileDiff } from "../components/FileDiff";
import { Button, Card, Checkbox, Tag } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";
import { importApi, type SwitchOver, type UndoPreview, type UndoResult } from "../importApi";
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

function size(bytes: number): string {
  return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function FullBackupRow({ backup }: { backup: FullBackup }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({ mutationFn: () => api.fullBackups.remove(backup.name), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["full-backups"] }) });
  return (
    <li className="flex flex-col gap-2 border-b border-border py-3 last:border-0 sm:flex-row sm:items-center sm:gap-4">
      <span className="text-sm text-muted sm:w-44">{formatTime(backup.created)}</span>
      <span className="min-w-0 flex-1 break-all font-mono text-xs">
        {backup.name} <span className="text-muted">· {size(backup.size)}</span>
      </span>
      <span className="flex flex-wrap gap-2">
        <a
          href={api.fullBackups.url(backup.name)}
          download
          className="inline-flex min-h-11 items-center rounded-control border border-border-strong bg-surface-2 px-4 text-sm font-medium hover:border-muted"
        >
          Download
        </a>
        {confirming ? (
          <>
            <Button className="border-err/60 text-err" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Delete it
            </Button>
            <Button onClick={() => setConfirming(false)}>Keep</Button>
          </>
        ) : (
          <Button onClick={() => setConfirming(true)}>Delete</Button>
        )}
      </span>
    </li>
  );
}

function FullBackups() {
  const tasks = useBuiltinTasks();
  const task = tasks.data?.tasks.find((t) => t.name === "full_backup");
  const list = useQuery({ queryKey: ["full-backups", task?.last?.finished_at], queryFn: api.fullBackups.list });
  return (
    <Card title="Full backups">
      <p className="mb-2 text-sm text-muted">
        Everything needed to rebuild this setup: Kometa's config folder with the Original Posters Kometa needs to remove its overlays, and
        Studio's schedules, history and settings. They hold your Plex token and API keys, so keep downloads private. To restore one, stop
        Studio and unzip it as its README says.
      </p>
      {task && (
        <ul className="mb-2">
          <BuiltinTaskRow task={task} />
        </ul>
      )}
      {list.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : list.isError ? (
        <p role="alert" className="text-err">
          {list.error.message}
        </p>
      ) : list.data.backups.length === 0 ? (
        <p className="text-muted">No full backups yet.</p>
      ) : (
        <ul>
          {list.data.backups.map((backup) => (
            <FullBackupRow key={backup.name} backup={backup} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function LossList({ label, items }: { label: string; items: { library: string; title: string }[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="font-medium text-text">{label}</p>
      <ul className="mt-1 list-inside list-disc">
        {items.map((item) => (
          <li key={`${item.library}:${item.title}`}>
            {item.library}: {item.title}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UndoDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [deleteFromPlex, setDeleteFromPlex] = useState(false);
  const preview = useQuery({ queryKey: ["import", "undo"], queryFn: importApi.undoPreview, retry: false });
  const undo = useMutation({
    mutationFn: () => importApi.undo(deleteFromPlex),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["import"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });

  if (undo.isSuccess) {
    const result: UndoResult = undo.data;
    return (
      <ConfirmDialog title="Undone" confirm="Done" onConfirm={onClose} onCancel={onClose}>
        <p>
          Restored {result.restored_files} file{result.restored_files === 1 ? "" : "s"} from {result.backup}.
        </p>
        {result.deleted_from_plex.length > 0 && (
          <ul className="mt-2 list-inside list-disc">
            {result.deleted_from_plex.map((title) => (
              <li key={title}>Deleted from Plex: {title}</li>
            ))}
          </ul>
        )}
      </ConfirmDialog>
    );
  }

  if (preview.isPending) {
    return (
      <ConfirmDialog title="Undo move over" confirm="Undo" onConfirm={() => {}} onCancel={onClose}>
        <p>Loading…</p>
      </ConfirmDialog>
    );
  }

  if (preview.isError) {
    return (
      <ConfirmDialog title="Undo move over" confirm="Close" onConfirm={onClose} onCancel={onClose}>
        <p role="alert" className="text-err">
          {preview.error.message}
        </p>
      </ConfirmDialog>
    );
  }

  const data: UndoPreview = preview.data;
  return (
    <ConfirmDialog
      title="Undo move over"
      confirm="Undo"
      danger
      busy={undo.isPending}
      onConfirm={() => undo.mutate()}
      onCancel={onClose}
    >
      <div className="flex flex-col gap-3">
        <p>This puts every file back from the switch-over backup. You will lose:</p>
        <LossList label="Collections added since" items={data.loses.added} />
        <LossList label="Collections changed since" items={data.loses.changed} />
        {data.files.length > 0 && (
          <div>
            <p className="font-medium text-text">Files put back</p>
            <ul className="mt-1 list-inside list-disc font-mono text-xs">
              {data.files.map((path) => (
                <li key={path}>{path}</li>
              ))}
            </ul>
          </div>
        )}
        {data.plex.length > 0 && (
          <Checkbox checked={deleteFromPlex} onChange={setDeleteFromPlex}>
            Also delete these collections from Plex
            <ul className="mt-1 list-inside list-disc text-muted">
              {data.plex.map((item) => (
                <li key={`${item.library}:${item.title}`}>
                  {item.library}: {item.title}
                </li>
              ))}
            </ul>
          </Checkbox>
        )}
        {undo.isError && (
          <p role="alert" className="text-err">
            {undo.error.message}
          </p>
        )}
      </div>
    </ConfirmDialog>
  );
}

function MoveOverSection({ active }: { active: SwitchOver | null }) {
  const [undoOpen, setUndoOpen] = useState(false);
  if (!active) {
    return (
      <Card title="Move over from Kometa">
        <p className="text-sm text-muted">
          Bring an existing Kometa setup into Studio.{" "}
          <Link className="underline" to="/setup/move-over">
            Move over from Kometa
          </Link>
        </p>
      </Card>
    );
  }
  return (
    <Card title="Move over from Kometa">
      <p className="mb-3 text-sm text-muted">
        Switched over on {formatTime(active.created_at)}. Undo puts every file back; Export downloads a zip of what Studio wrote.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => setUndoOpen(true)}>Undo</Button>
        <a
          href={importApi.exportUrl()}
          download
          className="inline-flex min-h-11 items-center rounded-control border border-border-strong bg-surface-2 px-4 text-sm font-medium hover:border-muted"
        >
          Export
        </a>
      </div>
      {undoOpen && <UndoDialog onClose={() => setUndoOpen(false)} />}
    </Card>
  );
}

export function SystemBackup() {
  const list = useQuery({ queryKey: ["backups"], queryFn: api.backups.list });
  const switchOver = useQuery({ queryKey: ["import", "switch-over"], queryFn: importApi.switchOver });
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      {switchOver.isPending ? null : switchOver.isError ? (
        <Card title="Move over from Kometa">
          <p role="alert" className="text-err">
            {switchOver.error.message}
          </p>
        </Card>
      ) : (
        <MoveOverSection active={switchOver.data.active} />
      )}
      <FullBackups />
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
