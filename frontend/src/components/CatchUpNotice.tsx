// The notice after Studio caught up on schedules it missed while it was off (handoff §4.3), on the Overview and System → Tasks.

import { Link } from "react-router";

import type { Schedules } from "../api";
import { formatTime, statusLabels } from "../runs";

export function CatchUpNotice({ catchUps }: { catchUps: Schedules["catch_ups"] }) {
  if (catchUps.length === 0) return null;
  return (
    <section role="status" className="rounded-card border border-info/40 bg-surface p-4 text-sm">
      <p className="font-semibold text-info">Studio caught up on missed runs</p>
      <p className="mt-1 text-muted">Studio was off when these were due, so each ran once when it started again:</p>
      <ul className="mt-2 flex flex-col gap-1">
        {catchUps.map((run) => (
          <li key={run.id}>
            {run.name}:{" "}
            <Link className="underline" to={`/activity/queue/${run.id}`}>
              run #{run.id}
            </Link>{" "}
            <span className="text-muted">({statusLabels[run.status].toLowerCase()}, {formatTime(run.queued_at)})</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
