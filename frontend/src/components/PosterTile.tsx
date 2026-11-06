// Shared poster tile: one open control (link or dialog), optional pick tick and status badge overlays.

import { type ReactNode } from "react";
import { Link } from "react-router";

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

function Dot({ className }: { className: string }) {
  return <span className={`inline-block size-2 shrink-0 rounded-full ${className}`} aria-hidden="true" />;
}

export function StatusBadge({ state }: { state: StatusBadgeState }) {
  const shell =
    "inline-flex max-w-full items-center gap-1 rounded-full border border-white/10 bg-black/55 px-2 py-0.5 text-[11px] font-medium leading-tight text-text backdrop-blur-sm";
  switch (state.kind) {
    case "in_plex": {
      const coming = state.coming ?? 0;
      const count = state.count;
      if (coming > 0) {
        const label =
          count != null && count !== 0 ? `${count} · ${coming} coming` : `${coming} coming`;
        const title =
          count != null ? `In Plex · ${count} titles · ${coming} coming` : `In Plex · ${coming} titles coming`;
        return (
          <span className={shell} title={title}>
            <Dot className="bg-info" />
            <span className="min-w-0 truncate">{label}</span>
          </span>
        );
      }
      if (count != null) {
        return (
          <span className={shell} title={`In Plex · ${count} titles`}>
            <Dot className="bg-ok" />
            <span className="min-w-0 truncate">{String(count)}</span>
          </span>
        );
      }
      return (
        <span className={shell} title="In Plex">
          <Dot className="bg-ok" />
          <span>In Plex</span>
        </span>
      );
    }
    case "queued":
      return (
        <span className={shell} title="Queued">
          <Dot className="bg-info" />
          <span>Queued</span>
        </span>
      );
    case "building":
      return (
        <span className={shell} title="Building">
          <Dot className="bg-info" />
          <span>Building</span>
        </span>
      );
    case "removing":
      return (
        <span className={shell} title="Removing">
          <Dot className="bg-info" />
          <span>Removing</span>
        </span>
      );
    case "missing":
      return (
        <span className={shell} title="Not built">
          <span className="inline-block size-2 shrink-0 rounded-full border border-dashed border-muted bg-transparent" aria-hidden="true" />
          <span>Not built</span>
        </span>
      );
    case "failed":
      return (
        <span className={shell} title="Failed">
          <Dot className="bg-err" />
          <span>Failed</span>
        </span>
      );
    case "will_remove":
      return (
        <span className={shell} title="Will be removed">
          <Dot className="bg-warn" />
          <span className="min-w-0 truncate">Will be removed</span>
        </span>
      );
    case "changed":
      return (
        <span className={shell} title="Changed">
          <Dot className="bg-accent" />
          <span>Changed</span>
        </span>
      );
    default:
      return null;
  }
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
      <Link to={props.to} aria-label={title} className={openClasses}>
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
