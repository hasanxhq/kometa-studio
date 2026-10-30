// The jobs drawer, after Bazarr's Jobs Manager: a header button that spins while anything runs, and a
// drawer from the right with Running, Waiting, Failed and Finished jobs (the last ten finished).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, type Job, type JobStatus } from "../api";
import { formatRelative, formatTime } from "../runs";
import { Button } from "./ui";

const CLEARED_KEY = "studio.jobs.clearedAt"; // finished jobs before this are hidden, in this browser

const sections: { status: JobStatus; label: string; colour: string }[] = [
  { status: "running", label: "Running", colour: "border-l-info" },
  { status: "pending", label: "Waiting", colour: "border-l-warn" },
  { status: "failed", label: "Failed", colour: "border-l-err" },
  { status: "completed", label: "Finished", colour: "border-l-ok" },
];

function readCleared(): string {
  try {
    return localStorage.getItem(CLEARED_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Polls quickly while something runs or waits, or while the drawer is open. */
export function useJobs(open: boolean) {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
    refetchInterval: (query) => (open || query.state.data?.jobs.some((j) => j.status === "running" || j.status === "pending") ? 2000 : 15_000),
  });
}

function Ring({ value, max }: { value: number; max: number }) {
  const share = max > 0 ? Math.min(value / max, 1) : 0;
  const circumference = 2 * Math.PI * 18;
  return (
    <svg viewBox="0 0 44 44" className="size-11 shrink-0" role="img" aria-label={`${value} of ${max}`}>
      <circle cx="22" cy="22" r="18" fill="none" strokeWidth="4" className="stroke-border-strong" />
      <circle
        cx="22"
        cy="22"
        r="18"
        fill="none"
        strokeWidth="4"
        strokeLinecap="round"
        className="stroke-accent transition-[stroke-dashoffset]"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - share)}
        transform="rotate(-90 22 22)"
      />
      <text x="22" y="26" textAnchor="middle" className="fill-text text-[10px] font-semibold">
        {Math.round(share * 100)}%
      </text>
    </svg>
  );
}

function Spinner({ className = "size-5" }: { className?: string }) {
  return <span aria-hidden className={`inline-block animate-spin rounded-full border-2 border-border-strong border-t-accent ${className}`} />;
}

function StatusIcon({ job }: { job: Job }) {
  if (job.progress && job.status === "running") return <Ring value={job.progress.value} max={job.progress.max} />;
  return (
    <span className="flex size-11 shrink-0 items-center justify-center">
      {job.status === "running" ? (
        <Spinner />
      ) : job.status === "pending" ? (
        <span className="text-lg text-warn" aria-hidden>
          ⏳
        </span>
      ) : job.status === "failed" ? (
        <span className="text-lg text-err" aria-hidden>
          ✕
        </span>
      ) : (
        <span className="text-lg text-ok" aria-hidden>
          ✓
        </span>
      )}
    </span>
  );
}

function JobCard({ job, colour, onNavigate }: { job: Job; colour: string; onNavigate: () => void }) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => api.runs.cancel(job.run_id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
  const when = job.finished_at ?? (job.status === "pending" ? (job.due_at ?? null) : job.started_at);
  return (
    <li className={`flex gap-3 rounded-control border border-border border-l-4 bg-surface p-3 ${colour}`} aria-label={job.title}>
      <StatusIcon job={job} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          <Link to={job.link} onClick={onNavigate} className="min-w-0 break-words text-sm font-semibold hover:underline">
            {job.title}
          </Link>
          <span className="text-xs text-muted">
            {job.label}
            {when && (
              <span title={formatTime(when)}>
                {" "}
                · {job.status === "pending" && job.due_at ? `runs ${formatRelative(when)}` : job.status === "running" ? `started ${formatRelative(when)}` : formatRelative(when)}
              </span>
            )}
          </span>
        </div>
        {job.message && <p className="break-words font-mono text-xs text-muted">{job.message}</p>}
        {job.cancellable && (
          <div>
            <Button className="min-h-9 px-3 text-xs" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              {job.status === "running" ? "Stop" : "Cancel"}
            </Button>
          </div>
        )}
        {cancel.isError && (
          <p role="alert" className="text-xs text-err">
            {cancel.error.message}
          </p>
        )}
      </div>
    </li>
  );
}

export function JobsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const jobs = useJobs(open);
  const [collapsed, setCollapsed] = useState<Partial<Record<JobStatus, boolean>>>({});
  const [cleared, setCleared] = useState(readCleared);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open, onClose]);

  if (!open) return null;

  const clear = () => {
    const now = new Date().toISOString();
    setCleared(now);
    try {
      localStorage.setItem(CLEARED_KEY, now);
    } catch {
      // kept until reload
    }
  };
  const visible = (jobs.data?.jobs ?? []).filter((job) => !job.finished_at || !cleared || job.finished_at > cleared);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/40" onClick={onClose} />
      <aside role="dialog" aria-label="Jobs" className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-sidebar">
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <h2 className="font-display text-lg font-semibold">Jobs</h2>
          <button type="button" aria-label="Close jobs" className="flex size-11 items-center justify-center rounded-control text-muted hover:bg-surface-2" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {jobs.isPending ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : jobs.isError ? (
            <p role="alert" className="text-sm text-err">
              {jobs.error.message}
            </p>
          ) : visible.length === 0 ? (
            <p className="text-sm text-muted">Nothing running, waiting or recently finished.</p>
          ) : (
            sections.map(({ status, label, colour }) => {
              const group = visible.filter((job) => job.status === status);
              if (group.length === 0) return null;
              const finished = status === "failed" || status === "completed";
              return (
                <section key={status} className="mb-5">
                  <div className="mb-2 flex items-center justify-between">
                    <button
                      type="button"
                      className="flex min-h-11 items-center gap-2 text-sm font-semibold"
                      aria-expanded={!collapsed[status]}
                      onClick={() => setCollapsed({ ...collapsed, [status]: !collapsed[status] })}
                    >
                      <span className="text-xs text-muted">{collapsed[status] ? "▸" : "▾"}</span>
                      {label}
                      <span className="rounded border border-border px-1.5 text-xs text-muted">{group.length}</span>
                    </button>
                    {finished && (
                      <button type="button" className="min-h-11 text-xs text-muted underline hover:text-text" onClick={clear}>
                        Clear
                      </button>
                    )}
                  </div>
                  {!collapsed[status] && (
                    <ul className="flex flex-col gap-2">
                      {group.map((job) => (
                        <JobCard key={job.id} job={job} colour={colour} onNavigate={onClose} />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })
          )}
        </div>
      </aside>
    </>
  );
}

/** The header button: a spinner while anything runs, and a count of running and waiting jobs. */
export function JobsButton({ onOpen }: { onOpen: () => void }) {
  const jobs = useJobs(false);
  const list = jobs.data?.jobs ?? [];
  const running = list.filter((j) => j.status === "running").length;
  const busy = running + list.filter((j) => j.status === "pending").length;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={busy ? `Jobs: ${running} running, ${busy - running} waiting` : "Jobs"}
      className="relative flex size-11 shrink-0 items-center justify-center rounded-control text-muted hover:bg-surface-2 hover:text-text"
    >
      {running ? (
        <Spinner />
      ) : (
        <svg viewBox="0 0 20 20" className="size-5" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M3 5h2M3 10h2M3 15h2M8 5h9M8 10h9M8 15h9" strokeLinecap="round" />
        </svg>
      )}
      {busy > 0 && <span className="absolute right-1 top-1 rounded-full bg-accent px-1 text-[10px] font-semibold leading-4 text-on-accent">{busy}</span>}
    </button>
  );
}
