// Muted request tallies on a collection card/tile, plus Request N titles and Turn off download-missing.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestsApi, summaryHasCounts, type RequestSummary } from "../requestsApi";
import { Button } from "./ui";

export function formatRequestCounts(summary: RequestSummary): string {
  const parts: string[] = [];
  if (summary.waiting > 0) parts.push(`${summary.waiting} waiting`);
  if (summary.requested > 0) parts.push(`${summary.requested} requested`);
  if (summary.downloading > 0) parts.push(`${summary.downloading} downloading`);
  if (summary.imported > 0) parts.push(`${summary.imported} imported`);
  if (summary.failed > 0) parts.push(`${summary.failed} failed`);
  return parts.join(" · ");
}

export function RequestCountsLine({ summary }: { summary: RequestSummary | null | undefined }) {
  if (!summaryHasCounts(summary)) return null;
  const parts: { text: string; err?: boolean }[] = [];
  if (summary!.waiting > 0) parts.push({ text: `${summary!.waiting} waiting` });
  if (summary!.requested > 0) parts.push({ text: `${summary!.requested} requested` });
  if (summary!.downloading > 0) parts.push({ text: `${summary!.downloading} downloading` });
  if (summary!.imported > 0) parts.push({ text: `${summary!.imported} imported` });
  if (summary!.failed > 0) parts.push({ text: `${summary!.failed} failed`, err: true });
  return (
    <span className="text-xs text-muted">
      {parts.map((part, index) => (
        <span key={part.text}>
          {index > 0 && " · "}
          <span className={part.err ? "text-err" : undefined}>{part.text}</span>
        </span>
      ))}
    </span>
  );
}

export function DownloadMissingBadge({
  id,
  downloadMissing,
  library,
}: {
  id: number;
  downloadMissing: boolean;
  library?: string;
}) {
  const queryClient = useQueryClient();
  const turnOff = useMutation({
    mutationFn: () => requestsApi.setDownloadMissing(id, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["collections", library] });
      queryClient.invalidateQueries({ queryKey: ["ready-made"] });
      queryClient.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  if (!downloadMissing) return null;
  return (
    <span className="text-xs text-muted">
      Downloads missing
      {" · "}
      <button
        type="button"
        className="underline hover:text-text"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          turnOff.mutate();
        }}
        disabled={turnOff.isPending}
      >
        Turn off
      </button>
    </span>
  );
}

export function RequestWaitingButton({
  id,
  waiting,
  library,
}: {
  id: number;
  waiting: number;
  library?: string;
}) {
  const queryClient = useQueryClient();
  const request = useMutation({
    mutationFn: () => requestsApi.requestMissing(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["collections", library] });
      queryClient.invalidateQueries({ queryKey: ["ready-made"] });
      queryClient.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  if (waiting <= 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={() => request.mutate()} disabled={request.isPending}>
        {request.isPending ? "Requesting…" : `Request ${waiting} titles`}
      </Button>
      {request.isError && <span className="text-xs text-err">{request.error.message}</span>}
    </div>
  );
}
