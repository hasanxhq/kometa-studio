// System → Logs: Kometa's own logs (meta.log, per library and collection), filtered by level (handoff v2 §8).
// Each run's own log is on its run page.

import { useQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, type LogLevel } from "../api";
import { Card, Field, inputClass } from "../components/ui";

const levels: { value: LogLevel; label: string }[] = [
  { value: "TRACE", label: "Everything" },
  { value: "DEBUG", label: "Debug and above" },
  { value: "INFO", label: "Info and above" },
  { value: "WARNING", label: "Warnings and errors" },
  { value: "ERROR", label: "Errors only" },
];

// Kometa's lines: "[2026-10-30 04:00:02,200] builder.py   WARNING    | message   |". Continuations: spaces, then "| message |".
const ENTRY = /^\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)[,.]\d+\] \S+\s+\[?[A-Z]+\]?\s+\| ?(.*?)\s*\|?$/;
const CONTINUED = /^\s+\| ?(.*?)\s*\|?$/;

/** The time and message of a line, without Kometa's fixed-width columns, so it fits a phone. */
export function splitLine(text: string): { time: string | null; message: string } {
  const entry = ENTRY.exec(text);
  if (entry) return { time: entry[1], message: entry[2] };
  const continued = CONTINUED.exec(text);
  return { time: null, message: continued ? continued[1] : text };
}

const lineColours: Partial<Record<LogLevel, string>> = { WARNING: "text-warn", ERROR: "text-err", CRITICAL: "text-err", DEBUG: "text-muted", TRACE: "text-muted" };

export function SystemLogs() {
  const files = useQuery({ queryKey: ["logs"], queryFn: api.logs.list });
  const [chosen, setChosen] = useState<string | null>(null);
  const [level, setLevel] = useState<LogLevel>("INFO");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const path = chosen ?? files.data?.files[0]?.path ?? null;
  const log = useQuery({
    queryKey: ["logs", path, level, q],
    queryFn: () => api.logs.read(path!, level, q),
    enabled: path !== null,
    placeholderData: (previous) => previous,
  });

  if (files.isPending) return <p className="text-muted">Loading…</p>;
  if (files.isError)
    return (
      <p role="alert" className="text-err">
        {files.error.message}
      </p>
    );
  if (files.data.files.length === 0)
    return (
      <Card title="Kometa's logs">
        <p className="text-sm text-muted">Kometa hasn't written any logs yet. They appear after its first run.</p>
      </Card>
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <Field label="Log">
            <select className={inputClass} value={path ?? ""} onChange={(e) => setChosen(e.target.value)}>
              {files.data.files.map((file) => (
                <option key={file.path} value={file.path}>
                  {file.path}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="basis-48">
          <Field label="Show">
            <select className={inputClass} value={level} onChange={(e) => setLevel(e.target.value as LogLevel)}>
              {levels.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="min-w-0 flex-1 basis-48">
          <Field label="Search">
            <input className={inputClass} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. TMDb" />
          </Field>
        </div>
        {path && (
          <a
            href={api.logs.downloadUrl(path)}
            className="inline-flex min-h-11 items-center rounded-control border border-border-strong bg-surface-2 px-4 text-sm font-medium hover:border-muted"
          >
            Download
          </a>
        )}
      </div>
      <p className="text-xs text-muted">
        Each run's own log is on its page in <Link to="/activity/queue" className="underline">Activity → Queue</Link>.
      </p>
      {log.isError && (
        <p role="alert" className="text-err">
          {log.error.message}
        </p>
      )}
      {log.data && (
        <section aria-label="Log lines" className="rounded-card border border-border bg-bg p-3">
          {log.data.truncated && <p className="mb-2 text-xs text-muted">Showing the end of the log. Download it for all of it.</p>}
          {log.data.lines.length === 0 ? (
            <p className="text-sm text-muted">Nothing matches.</p>
          ) : (
            <div className="font-mono text-xs leading-5">
              {log.data.lines.map((line, index) => {
                const { time, message } = splitLine(line.text);
                return (
                  <div key={index} className={`flex gap-3 ${lineColours[line.level] ?? ""}`} title={line.text}>
                    <span className="w-16 shrink-0 text-muted">{time ?? ""}</span>
                    <span className="min-w-0 whitespace-pre-wrap break-words">{message}</span>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
