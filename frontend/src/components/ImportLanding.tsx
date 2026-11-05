// How an uploaded or Move-over collection file lands: per-file action and each collection's result.

import { Tag, type Tone } from "./ui";
import type { FileLanding, Landing } from "../importApi";

const fileActionLabel: Record<FileLanding["action"], string> = {
  replace: "Replaced by Studio",
  keep: "Kept as a Kometa file",
  studio: "Studio's own",
};

const fileActionTone: Record<FileLanding["action"], Tone> = {
  replace: "info",
  keep: "muted",
  studio: "ok",
};

const resultLabel: Record<Landing["result"], string> = {
  imported: "Imported",
  ready_made: "Ready-made",
  kept: "Kept",
  studio: "Studio's own",
};

const resultTone: Record<Landing["result"], Tone> = {
  imported: "ok",
  ready_made: "info",
  kept: "muted",
  studio: "ok",
};

export function CollectionLanding({ landing }: { landing: Landing }) {
  return (
    <li className="flex flex-col gap-1 border-b border-border py-2 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 break-words font-medium">{landing.name}</span>
        <Tag tone={resultTone[landing.result]}>{resultLabel[landing.result]}</Tag>
      </div>
      {landing.reason && <p className="text-sm text-muted">{landing.reason}</p>}
      {landing.notes.length > 0 && (
        <ul className="list-inside list-disc text-sm text-muted">
          {landing.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function FileBlock({ file }: { file: FileLanding }) {
  const label = file.path ?? file.value;
  const openByDefault = file.action !== "studio";
  return (
    <details open={openByDefault} className="rounded-control border border-border">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-2 px-3 py-2">
        <span className="min-w-0 flex-1 break-all font-mono text-xs">{label}</span>
        <Tag tone={fileActionTone[file.action]}>{fileActionLabel[file.action]}</Tag>
      </summary>
      <div className="border-t border-border px-3 py-2">
        {file.reason && <p className="mb-2 text-sm text-muted">{file.reason}</p>}
        {file.collections.length === 0 ? (
          <p className="text-sm text-muted">No collections in this file.</p>
        ) : (
          <ul>
            {file.collections.map((landing) => (
              <CollectionLanding key={landing.name} landing={landing} />
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
