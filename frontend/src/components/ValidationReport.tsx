// Kometa's verdict on a change: new problems block a save; problems already in the files don't.

import type { Validation } from "../api";

function List({ title, items, className }: { title: string; items: string[]; className: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-semibold">{title}</h4>
      <ul className={`mt-1 flex list-disc flex-col gap-1 pl-5 font-mono text-xs ${className}`}>
        {items.map((item) => (
          <li key={item} className="break-words">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ValidationReport({ validation, saved, verdict: given }: { validation: Validation; saved?: boolean; verdict?: string }) {
  const verdict = given ?? (validation.ok
    ? validation.checked_by_kometa
      ? saved
        ? "Kometa checked it, and it's saved."
        : "Kometa's check passed. Nothing has been saved yet."
      : saved
        ? "Saved. Only the YAML syntax could be checked."
        : "Only the YAML syntax could be checked."
    : validation.crashed
      ? "Kometa's check didn't finish, so nothing was saved."
      : "Kometa found problems in this change, so nothing was saved.");
  return (
    <section role={validation.ok ? "status" : "alert"} className="flex flex-col gap-3 rounded-control border border-border bg-surface-2 p-3">
      <p className={validation.ok ? "text-ok" : "text-err"}>{verdict}</p>
      <List title="Problems this change would add" items={validation.errors} className="text-err" />
      <List title="Already in your files (these don't block saving)" items={validation.existing_errors} className="text-warn" />
      <List title="Warnings" items={validation.warnings} className="text-muted" />
      {validation.output && !validation.ok && (
        <details>
          <summary className="min-h-11 cursor-pointer content-center text-sm text-muted">Kometa's output</summary>
          <pre className="max-h-72 overflow-auto rounded-control bg-bg p-2 font-mono text-xs">{validation.output}</pre>
        </details>
      )}
    </section>
  );
}
