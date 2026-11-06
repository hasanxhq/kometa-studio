// One Ready-made collection, opened from its tile: its poster, what it would hold (a Plex filter run, or its chart's
// list with what's missing), and Pick / Customise / its collection page once built.

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router";

import { ApiError, type ReadyMadeEntry } from "../api";
import { builderApi } from "../builderApi";
import { PreviewBody } from "./builder/ListPreview";
import { Button } from "./ui";

export function ReadyMadePreview({
  library,
  category,
  entry,
  art,
  status,
  selected,
  onToggle,
  customise,
  onClose,
}: {
  library: string;
  category: string;
  entry: ReadyMadeEntry;
  art: ReactNode;
  status: string;
  selected: boolean;
  onToggle: () => void;
  customise?: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    dialog.current?.focus(); // keyboard and screen reader users land in the panel
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const preview = useQuery({
    queryKey: ["ready-made", "preview", library, category, entry.block, entry.key],
    queryFn: () => builderApi.readyMadePreview(library, category, entry.block, entry.key),
    staleTime: 60_000,
  });
  const built = entry.state === "in_plex" && entry.rating_key;

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/40" onClick={onClose} />
      <aside
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={entry.title}
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col border-l border-border bg-sidebar outline-none"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
          <h2 className="font-display text-lg font-semibold">{entry.title}</h2>
          <Button onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-5">
          <div className="flex gap-4">
            <div className="w-32 shrink-0">{art}</div>
            <div className="flex min-w-0 flex-col gap-2 text-sm">
              <p className="text-muted">{status}</p>
              {entry.items != null && <p className="text-muted">{entry.items} in your library</p>}
              <div className="flex flex-wrap gap-2 pt-1">
                <Button variant={selected ? undefined : "primary"} onClick={onToggle} aria-pressed={selected}>
                  {selected ? "Unpick" : "Pick"}
                </Button>
                {customise && (
                  <Link className="inline-flex min-h-11 items-center px-2 text-sm underline" to={customise}>
                    Customise
                  </Link>
                )}
                {built && (
                  <Link
                    className="inline-flex min-h-11 items-center px-2 text-sm underline"
                    to={`/libraries/${encodeURIComponent(library)}/collections/${encodeURIComponent(entry.rating_key!)}`}
                  >
                    Open its page
                  </Link>
                )}
              </div>
            </div>
          </div>
          <section className="flex flex-col gap-3" aria-label="What it would hold">
            <h3 className="text-[15px] font-semibold">{built ? "What it holds" : "What it would hold"}</h3>
            {preview.isPending ? (
              <p className="text-sm text-muted">Loading preview…</p>
            ) : preview.isError ? (
              <p role="alert" className="text-sm text-err">
                {preview.error instanceof ApiError ? preview.error.message : "Couldn't load the preview"}
              </p>
            ) : (
              <PreviewBody preview={preview.data} updating={preview.isFetching} />
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
