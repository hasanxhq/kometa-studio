// Shared poster tile: one open control (link or dialog), optional pick tick and status badge overlays.

import { type ReactNode } from "react";
import { Link } from "react-router";

import type { RequestSummary } from "../requestsApi";

/** Visual state for the pill on the poster's top-right; always paired with text (never colour-only). */
export type StatusBadgeState =
  | { kind: "in_plex"; count?: number | null; coming?: number }
  | { kind: "queued" }
  | { kind: "building" }
  | { kind: "removing" }
  | { kind: "missing" }
  | { kind: "failed" }
  | { kind: "will_remove" }
  | { kind: "changed" };

const looks: Record<Exclude<StatusBadgeState["kind"], "in_plex">, { dot: string; text: string }> = {
  queued: { dot: "bg-info", text: "Queued" },
  building: { dot: "bg-info", text: "Building" },
  removing: { dot: "bg-info", text: "Removing" },
  missing: { dot: "border border-dashed border-muted", text: "Not built" },
  failed: { dot: "bg-err", text: "Failed" },
  will_remove: { dot: "bg-warn", text: "Will be removed" },
  changed: { dot: "bg-accent", text: "Changed" },
};

function inPlex(count: number | null | undefined, coming: number): { dot: string; text: string; title: string } {
  const titles = count != null ? `In Plex · ${count} titles` : "In Plex";
  if (coming > 0) return { dot: "bg-info", text: count ? `${count} · ${coming} coming` : `${coming} coming`, title: `${titles} · ${coming} coming` };
  return { dot: "bg-ok", text: count != null ? String(count) : "In Plex", title: titles };
}

/** A collection's own state as a badge, or null when there's nothing to show (e.g. a Ready-made tile not picked). */
export function badgeFor(entry: { state: string | null; plex_items?: number | null; requests?: RequestSummary | null }): StatusBadgeState | null {
  if (entry.state === "in_plex") return { kind: "in_plex", count: entry.plex_items, coming: (entry.requests?.requested ?? 0) + (entry.requests?.downloading ?? 0) };
  return entry.state && entry.state in looks ? ({ kind: entry.state } as StatusBadgeState) : null;
}

export function StatusBadge({ state }: { state: StatusBadgeState }) {
  const look = state.kind === "in_plex" ? inPlex(state.count, state.coming ?? 0) : { ...looks[state.kind], title: looks[state.kind].text };
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 rounded-full border border-white/10 bg-black/55 px-2 py-0.5 text-[11px] leading-tight font-medium text-text backdrop-blur-sm"
      title={look.title}
    >
      <span aria-hidden="true" className={`inline-block size-2 shrink-0 rounded-full ${look.dot}`} />
      <span className="min-w-0 truncate">{look.text}</span>
    </span>
  );
}

export function PickTick({ title, selected, onToggle }: { title: string; selected: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`Pick ${title}`}
      title={selected ? "Picked" : "Pick"}
      onClick={onToggle}
      className="pointer-events-auto absolute right-0 bottom-0 flex size-11 items-center justify-center"
    >
      <span
        aria-hidden="true"
        className={`flex size-7 items-center justify-center rounded-full border-2 text-sm font-bold shadow ${
          selected ? "border-accent bg-accent text-black" : "border-white/80 bg-black/55 text-transparent hover:text-white/80"
        }`}
      >
        ✓
      </span>
    </button>
  );
}

type PosterTileBase = {
  title: string;
  art: ReactNode;
  badge?: ReactNode;
  pick?: { selected: boolean; onToggle: () => void };
  selected?: boolean;
  children: ReactNode;
  footer?: ReactNode;
  /** Extra classes on the link or dialog button (e.g. hover ring). */
  controlClassName?: string;
  /** Extra classes on the outer `li` (e.g. card chrome). */
  liClassName?: string;
};

export type PosterTileProps = PosterTileBase & ({ to: string; onOpen?: undefined } | { to?: undefined; onOpen: () => void });

export function PosterTile(props: PosterTileProps) {
  const { title, art, badge, pick, selected, children, footer, controlClassName = "", liClassName = "" } = props;
  const openClasses =
    `flex min-h-11 w-full grow flex-col text-left ${selected ? "ring-2 ring-accent " : ""}` + controlClassName;
  const posterBlock = (
    <div className="relative w-full shrink-0">
      {badge ? <div className="pointer-events-none absolute top-1 right-1 z-10 max-w-[calc(100%-0.5rem)]">{badge}</div> : null}
      {art}
    </div>
  );
  const main =
    props.to !== undefined ? (
      <Link to={props.to} className={openClasses}>
        {posterBlock}
        {children}
      </Link>
    ) : (
      <button type="button" aria-haspopup="dialog" aria-label={title} onClick={props.onOpen} className={openClasses}>
        {posterBlock}
        {children}
      </button>
    );
  return (
    <li aria-label={title} className={`relative flex flex-col ${liClassName}`.trim()}>
      {pick ? (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 aspect-[2/3]">
          <PickTick title={title} selected={pick.selected} onToggle={pick.onToggle} />
        </div>
      ) : null}
      {main}
      {footer}
    </li>
  );
}
