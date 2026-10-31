// Run again: queue the same request as a finished run (the concept's "retry"), then open the new run.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { api, type Run } from "../api";
import { Button } from "./ui";

export function RunAgain({ run }: { run: Run }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const again = useMutation({
    mutationFn: () => api.runs.create(run.request),
    onSuccess: (queued) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
      navigate(`/activity/queue/${queued.id}`);
    },
  });
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button
        variant={run.status === "succeeded" ? "secondary" : "primary"}
        onClick={() => again.mutate()}
        disabled={again.isPending}
        title="Queue the same run: same libraries, collections, files and options"
      >
        {again.isPending ? "Queueing…" : "Run again"}
      </Button>
      {again.isError && (
        <span role="alert" className="text-sm text-err">
          {again.error.message}
        </span>
      )}
    </span>
  );
}
