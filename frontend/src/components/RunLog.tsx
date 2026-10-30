// A run's log: the tail so far, then new lines live while the run is going (server-sent events).

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { api, type RunStatus } from "../api";

const MAX_LINES = 5000; // the full log is a download away

function lineClass(line: string): string {
  if (/\b(error|critical|traceback)\b/i.test(line)) return "text-err";
  if (/\bwarning\b/i.test(line)) return "text-warn";
  if (line.startsWith("Kometa Studio:")) return "text-accent";
  return "";
}

export function RunLog({ runId, onEnd }: { runId: number; onEnd?: (status: RunStatus) => void }) {
  // `cut`: earlier lines were left out, by the server or to stay under MAX_LINES.
  const [{ lines, cut }, setLog] = useState<{ lines: string[]; cut: boolean }>({ lines: [], cut: false });
  const [live, setLive] = useState(true);
  const [follow, setFollow] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const onEndRef = useRef(onEnd);

  useEffect(() => {
    onEndRef.current = onEnd;
  });

  useEffect(() => {
    const source = new EventSource(api.runs.streamUrl(runId));
    // Every (re)connection starts with the log so far, so start over rather than repeat lines.
    source.onopen = () => {
      setLog({ lines: [], cut: false });
      setLive(true);
    };
    source.addEventListener("truncated", () => setLog((log) => ({ ...log, cut: true })));
    source.addEventListener("lines", (event) => {
      const batch = JSON.parse((event as MessageEvent).data) as string[];
      setLog((log) => {
        const next = log.lines.concat(batch);
        return next.length > MAX_LINES ? { lines: next.slice(-MAX_LINES), cut: true } : { lines: next, cut: log.cut };
      });
    });
    source.addEventListener("end", (event) => {
      const end = JSON.parse((event as MessageEvent).data) as { status: RunStatus; dropped: boolean };
      source.close();
      if (end.dropped) {
        setAttempt((n) => n + 1); // this browser fell behind; reconnect and catch up
        return;
      }
      setLive(false);
      onEndRef.current?.(end.status);
    });
    return () => source.close();
  }, [runId, attempt]);

  useLayoutEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines, follow]);

  const onScroll = () => {
    const el = box.current;
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span role="status">
          {live ? "Live" : "Finished"} · {lines.length} line{lines.length === 1 ? "" : "s"}
          {cut && " (earlier lines are in the full log)"}
        </span>
        <span className="flex items-center gap-3">
          {!follow && (
            <button type="button" className="min-h-11 underline" onClick={() => setFollow(true)}>
              Jump to the end
            </button>
          )}
          <a className="min-h-11 content-center underline" href={api.runs.logUrl(runId)}>
            Download full log
          </a>
        </span>
      </div>
      <div
        ref={box}
        onScroll={onScroll}
        className="h-[28rem] overflow-auto rounded-control border border-border bg-bg p-3 font-mono text-xs leading-5"
        aria-label="Run log"
        tabIndex={0}
      >
        {lines.length === 0 ? (
          <p className="text-muted">{live ? "Waiting for Kometa's output…" : "No output."}</p>
        ) : (
          lines.map((line, index) => (
            <div key={index} className={`whitespace-pre ${lineClass(line)}`}>
              {line || " "}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
