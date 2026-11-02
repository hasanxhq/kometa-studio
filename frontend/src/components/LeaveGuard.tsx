// Asks before losing unsaved changes: closing the tab, or going anywhere else in Studio.

import { useEffect, type RefObject } from "react";
import { useBlocker } from "react-router";

import { Button } from "./ui";

/** The question itself, for a page that loses edits without going anywhere, such as picking another card. */
export function LeaveDialog({ onStay, onLeave }: { onStay: () => void; onLeave: () => void }) {
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/50 p-4 sm:items-center">
      <div role="alertdialog" aria-modal="true" aria-labelledby="leave-title" className="flex w-full max-w-md flex-col gap-4 rounded-card border border-border-strong bg-surface p-6">
        <p id="leave-title" className="font-semibold">
          You have unsaved changes
        </p>
        <p className="text-sm text-muted">If you leave now, they're lost.</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="primary" onClick={onStay} autoFocus>
            Stay here
          </Button>
          <Button className="border-err/60 text-err" onClick={onLeave}>
            Leave without saving
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Staying on the same page never asks, so an editor can change its own query string; `query` is for a page whose query string
 * picks what's being edited, where changing it does lose the edits. `released` lets an editor leave on purpose, such as after
 * deleting what's being edited, before `dirty` has caught up.
 */
export function LeaveGuard({ dirty, released, query = false }: { dirty: boolean; released?: RefObject<boolean>; query?: boolean }) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !released?.current && (nextLocation.pathname !== currentLocation.pathname || (query && nextLocation.search !== currentLocation.search)),
  );

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (blocker.state !== "blocked") return null;
  return <LeaveDialog onStay={() => blocker.reset()} onLeave={() => blocker.proceed()} />;
}
