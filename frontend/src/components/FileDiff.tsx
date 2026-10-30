// A line diff of two texts, with long unchanged stretches folded.

import { diffLines } from "diff";

const CONTEXT = 3;

type Line = { kind: "same" | "added" | "removed" | "fold"; text: string };

function lines(before: string, after: string): Line[] {
  const out: Line[] = [];
  for (const part of diffLines(before, after)) {
    const kind: Line["kind"] = part.added ? "added" : part.removed ? "removed" : "same";
    const texts = part.value.replace(/\n$/, "").split("\n");
    if (kind === "same" && texts.length > CONTEXT * 2 + 1) {
      out.push(...texts.slice(0, CONTEXT).map((text) => ({ kind, text })));
      out.push({ kind: "fold", text: `… ${texts.length - CONTEXT * 2} unchanged lines …` });
      out.push(...texts.slice(-CONTEXT).map((text) => ({ kind, text })));
    } else {
      out.push(...texts.map((text) => ({ kind, text })));
    }
  }
  return out;
}

const styles: Record<Line["kind"], string> = {
  same: "text-muted",
  added: "bg-ok/10 text-ok",
  removed: "bg-err/10 text-err",
  fold: "text-muted italic",
};
const marks: Record<Line["kind"], string> = { same: " ", added: "+", removed: "−", fold: " " };

export function FileDiff({ before, after, labels }: { before: string; after: string; labels: [string, string] }) {
  if (before === after) return <p className="text-sm text-muted">No differences: the file is the same as in this backup.</p>;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted">
        <span className="text-err">− {labels[0]}</span> · <span className="text-ok">+ {labels[1]}</span>
      </p>
      <pre className="max-h-[28rem] overflow-auto rounded-control border border-border bg-bg py-2 font-mono text-xs leading-5">
        {lines(before, after).map((line, index) => (
          <div key={index} className={`px-3 ${styles[line.kind]}`}>
            <span aria-hidden className="mr-2 select-none">
              {marks[line.kind]}
            </span>
            {line.text || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
