// Small building blocks shared by the pages.

import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-4 md:p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" };

export function Button({ variant = "secondary", className = "", type = "button", ...props }: ButtonProps) {
  const look =
    variant === "primary"
      ? "bg-accent text-on-accent hover:brightness-110"
      : "border border-border-strong bg-surface-2 text-text hover:border-muted";
  return (
    <button
      type={type}
      className={`inline-flex min-h-11 items-center justify-center rounded-control px-4 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${look} ${className}`}
      {...props}
    />
  );
}

/** A form's Save and the like: they stay at the bottom of the page while a long form scrolls. */
export function StickyActions({ children }: { children: ReactNode }) {
  // The negative offsets are main's padding (Layout): without them, the form shows through the gap below the bar.
  return <div className="sticky -bottom-4 z-10 flex flex-wrap items-center gap-3 border-t border-border bg-bg py-3 md:-bottom-6">{children}</div>;
}

export type Tone = "muted" | "ok" | "warn" | "err" | "info";

export function Tag({ tone = "muted", children }: { tone?: Tone; children: ReactNode }) {
  const colour = { muted: "text-muted", ok: "text-ok", warn: "text-warn", err: "text-err", info: "text-info" }[tone];
  return <span className={`rounded border border-border px-1.5 py-0.5 text-xs ${colour}`}>{children}</span>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <label className="flex flex-col gap-1.5">
        <span className="text-muted">{label}</span>
        {children}
      </label>
      {/* Outside the label, so a link in the hint doesn't become part of the field's name. */}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}

export function Checkbox({ checked, onChange, children, disabled }: { checked: boolean; onChange: (checked: boolean) => void; children: ReactNode; disabled?: boolean }) {
  return (
    <label className={`flex min-h-11 items-start gap-2 text-sm ${disabled ? "opacity-60" : ""}`}>
      <input type="checkbox" className="mt-1 size-4 shrink-0 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

export const inputClass =
  "min-h-11 w-full rounded-control border border-border-strong bg-bg px-3 text-sm text-text placeholder:text-muted/60 focus:border-accent focus:outline-none";

/** A button that asks once more before doing something hard to undo. */
export function ConfirmButton({
  label,
  confirm,
  warning,
  onConfirm,
  busy,
  open = false,
  onKeep,
}: {
  label: string;
  confirm: string;
  warning: string;
  onConfirm: () => void;
  busy: boolean;
  open?: boolean; // already asking: something else was the first click
  onKeep?: () => void;
}) {
  const [asking, setAsking] = useState(open);
  if (!asking) return <Button onClick={() => setAsking(true)}>{label}</Button>;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-warn">{warning}</span>
      <Button className="border-err/60 text-err" onClick={onConfirm} disabled={busy}>
        {confirm}
      </Button>
      <Button
        onClick={() => {
          setAsking(false);
          onKeep?.();
        }}
      >
        Keep
      </Button>
    </span>
  );
}
