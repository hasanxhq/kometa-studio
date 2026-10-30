// Small building blocks shared by the pages.

import type { ButtonHTMLAttributes, ReactNode } from "react";

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

export const inputClass =
  "min-h-11 w-full rounded-control border border-border-strong bg-bg px-3 font-mono text-sm text-text placeholder:text-muted/60 focus:border-accent focus:outline-none";
