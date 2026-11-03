// The Ready-made build bar: local picks for one library, dry-run confirm, then one Kometa run.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, type ReadyMadeBuildPlan, type ReadyMadeBuildResult } from "../api";
import { useReadyMadePicks } from "../readyMadePicks";
import { SaveError } from "./ValidationReport";
import { Button, StickyActions } from "./ui";

export function BuildBar({ library }: { library: string }) {
  const queryClient = useQueryClient();
  const { picks, clearLibrary, changeCount } = useReadyMadePicks();
  const local = picks(library);
  const total = changeCount(library);
  const [plan, setPlan] = useState<ReadyMadeBuildPlan | null>(null);
  const [done, setDone] = useState<ReadyMadeBuildResult | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const dryRun = useMutation({
    mutationFn: () => api.readyMade.build({ library, add: local.add, remove: local.remove, dry_run: true }),
    onMutate: () => {
      setError(null);
      setDone(null);
    },
    onSuccess: (result) => setPlan(result),
    onError: (err: Error) => setError(err),
  });

  const confirm = useMutation({
    mutationFn: () => api.readyMade.build({ library, add: local.add, remove: local.remove, dry_run: false }),
    onMutate: () => setError(null),
    onSuccess: (result) => {
      clearLibrary(library);
      setPlan(null);
      setDone(result as ReadyMadeBuildResult);
      queryClient.invalidateQueries({ queryKey: ["ready-made"] });
    },
    onError: (err: Error) => setError(err),
  });

  if (total === 0 && !plan && !done && !error && !dryRun.isPending) return null;

  const parts: string[] = [];
  if (local.add.length > 0) parts.push(`Build ${local.add.length}`);
  if (local.remove.length > 0) parts.push(`Remove ${local.remove.length}`);
  const label = parts.join(" · ");

  const discard = () => {
    if (total > 5 && !window.confirm(`Discard ${total} changes for ${library}?`)) return;
    clearLibrary(library);
    setPlan(null);
    setDone(null);
    setError(null);
  };

  const closeDialog = () => {
    setPlan(null);
    setError(null);
    if (!done) dryRun.reset();
  };

  return (
    <>
      {(total > 0 || dryRun.isPending) && (
        <StickyActions>
          <span className="text-sm font-medium" aria-live="polite">
            {label || "Ready-made"}
          </span>
          <Button variant="primary" onClick={() => dryRun.mutate()} disabled={dryRun.isPending || total === 0}>
            {dryRun.isPending ? "Checking…" : "Build"}
          </Button>
          <Button onClick={discard} disabled={total === 0}>
            Discard
          </Button>
        </StickyActions>
      )}

      {done?.run_id != null && (
        <p role="status" className="text-sm text-ok">
          Building in{" "}
          <Link className="underline" to={`/activity/queue/${done.run_id}`}>
            run #{done.run_id}
          </Link>
        </p>
      )}
      {done && done.run_id == null && (
        <p role="status" className="text-sm text-ok">
          Done
          {done.removed.length > 0 && ` · removed ${done.removed.length}`}
          {done.kept.length > 0 && ` · kept ${done.kept.length}`}.{" "}
          <Link className="underline" to="/activity/queue">
            Activity → Queue
          </Link>
        </p>
      )}

      {(plan || error || dryRun.isPending) && (
        <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={closeDialog}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="ready-made-build-title"
            className="flex max-h-[90vh] w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-card border border-border-strong bg-surface p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="ready-made-build-title" className="font-semibold">
              {plan ? "Confirm build" : "Build"}
            </h2>
            {plan && (
              <>
                {plan.build.length > 0 && (
                  <section>
                    <h3 className="text-sm font-semibold">Will build</h3>
                    <ul className="mt-1 list-disc pl-5 text-sm">
                      {plan.build.map((item) => (
                        <li key={`${item.category}:${item.title}`}>
                          {item.title}
                          <span className="text-muted"> ({item.category})</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {plan.remove.length > 0 && (
                  <section>
                    <h3 className="text-sm font-semibold">Will delete from Plex</h3>
                    <ul className="mt-1 list-disc pl-5 text-sm">
                      {plan.remove.map((item) => (
                        <li key={`${item.category}:${item.title}`}>
                          {item.deletable ? (
                            <>
                              {item.title}
                              <span className="text-muted"> ({item.category})</span>
                            </>
                          ) : (
                            <>
                              <span className="text-warn">won't be deleted: {item.title}</span>
                              {item.reason && <span className="text-muted"> — {item.reason}</span>}
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {plan.build.length === 0 && plan.remove.length === 0 && <p className="text-sm text-muted">Nothing to build or remove.</p>}
              </>
            )}
            <SaveError error={error} />
            <div className="flex flex-wrap gap-3">
              {plan && (
                <Button variant="primary" onClick={() => confirm.mutate()} disabled={confirm.isPending} autoFocus>
                  {confirm.isPending ? "Starting…" : "Confirm"}
                </Button>
              )}
              <Button onClick={closeDialog}>Cancel</Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
