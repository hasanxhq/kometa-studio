import type { Page } from "../nav";

export function Placeholder({ page }: { page: Page }) {
  return (
    <section className="max-w-2xl rounded-card border border-border bg-surface p-6">
      <p className="text-muted">{page.summary}</p>
      <p className="mt-4 text-sm text-muted">Not built yet.</p>
    </section>
  );
}
