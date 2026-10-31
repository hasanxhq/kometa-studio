// Asks before leaving an editor with unsaved changes: closing the tab, or going anywhere else in Studio.

import { useEffect, type RefObject } from "react";
import { useBlocker } from "react-router";

import { Button } from "./ui";

/**
 * Staying on the same page never asks, so an editor can change its own query string. `released` lets an editor
 * leave on purpose, such as after deleting what's being edited, before `dirty` has caught up.
 */
export function LeaveGuard({ dirty, released }: { dirty: boolean; released?: RefObject<boolean> }) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !released?.current && nextLocation.pathname !== currentLocation.pathname);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (blocker.state !== "blocked") return null;
  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/50 p-4 sm:items-center">
      <div role="alertdialog" aria-modal="true" aria-labelledby="leave-title" className="flex w-full max-w-md flex-col gap-4 rounded-card border border-border-strong bg-surface p-6">
        <p id="leave-title" className="font-semibold">
          You have unsaved changes
        </p>
        <p className="text-sm text-muted">If you leave now, they're lost.</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="primary" onClick={() => blocker.reset()} autoFocus>
            Stay here
          </Button>
          <Button className="border-err/60 text-err" onClick={() => blocker.proceed()}>
            Leave without saving
          </Button>
        </div>
      </div>
    </div>
  );
}
