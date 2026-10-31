// Wording and formatting for Kometa runs, shared by the Queue and run pages.

import type { RunMode, RunRequest, RunStatus, RunTrigger } from "./api";

export const modes: { value: RunMode; label: string; flag: string | null }[] = [
  { value: "all", label: "Everything", flag: null },
  { value: "collections", label: "Collections", flag: "--collections-only" },
  { value: "overlays", label: "Overlays", flag: "--overlays-only" },
  { value: "operations", label: "Operations", flag: "--operations-only" },
  { value: "metadata", label: "Metadata", flag: "--metadata-only" },
  { value: "playlists", label: "Playlists", flag: "--playlists-only" },
];

export function describeRequest(request: RunRequest): string {
  const mode = request.mode === "all" ? "Everything" : `${modes.find((m) => m.value === request.mode)?.label} only`;
  const scope = [request.libraries.join(", "), request.collections.join(", "), request.files.join(", ")].filter(Boolean);
  return scope.length ? `${mode} · ${scope.join(" · ")}` : mode;
}

export const statusLabels: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  timed_out: "Timed out",
};

export const statusTones: Record<RunStatus, "muted" | "ok" | "warn" | "err" | "info"> = {
  queued: "muted",
  running: "info",
  succeeded: "ok",
  failed: "err",
  cancelled: "muted",
  interrupted: "warn",
  timed_out: "warn",
};

export const isActive = (status: RunStatus) => status === "queued" || status === "running";

export function formatDuration(start: string | null, end: string | null, now = Date.now()): string {
  if (!start) return "–";
  const seconds = Math.max(0, Math.round(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function formatTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function splitNames(text: string): string[] {
  return text
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
}

export const triggerLabels: Record<RunTrigger, string> = {
  manual: "Manual",
  schedule: "Scheduled",
  catch_up: "Catch-up",
  arr: "Radarr/Sonarr",
  maintainerr: "Before Maintainerr's redraw",
};

export const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function describeDays(days: number[]): string {
  const key = [...days].sort().join("");
  if (key === "0123456") return "Every day";
  if (key === "01234") return "Weekdays";
  if (key === "56") return "Weekends";
  return [...days].sort().map((day) => dayNames[day]).join(", ");
}

export function formatRelative(iso: string, now = Date.now()): string {
  const minutes = Math.round((Date.parse(iso) - now) / 60000);
  if (minutes === 0) return "just now";
  const future = minutes > 0;
  const size = Math.abs(minutes);
  const amount = size < 60 ? `${size} min` : size < 48 * 60 ? `${Math.round(size / 60)} h` : `${Math.round(size / 1440)} days`;
  return future ? `in ${amount}` : `${amount} ago`;
}
