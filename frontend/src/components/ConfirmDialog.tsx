// A modal that asks once more before doing something that uses disk, indexers or can't be undone easily.

import type { ReactNode } from "react";

import { Button } from "./ui";

export function ConfirmDialog({
  title,
  children,
  confirm,
  cancel = "Cancel",
  busy = false,
  onConfirm,
  onCancel,
  danger = false,
}: {
  title: string;
  children: ReactNode;
  confirm: string;
  cancel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className="flex w-full max-w-lg flex-col gap-4 rounded-card border border-border-strong bg-surface p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="font-semibold">
          {title}
        </h2>
        <div className="text-sm text-muted">{children}</div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="primary"
            className={danger ? "border-err/60 bg-transparent text-err hover:brightness-100" : undefined}
            onClick={onConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "Working…" : confirm}
          </Button>
          <Button onClick={onCancel} disabled={busy}>
            {cancel}
          </Button>
        </div>
      </div>
    </div>
  );
}
