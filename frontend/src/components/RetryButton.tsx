// "Retry" on a collection whose last build failed: builds it again as it stands.

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "./ui";

/** ``run`` starts the build; it resolves to a reason when Studio wouldn't build it, or null. */
export function RetryButton({ title, run, onDone }: { title: string; run: () => Promise<string | null>; onDone: () => void }) {
  const [message, setMessage] = useState<string | null>(null);
  const retry = useMutation({
    mutationFn: run,
    onMutate: () => setMessage(null),
    onSuccess: (reason) => {
      setMessage(reason);
      onDone();
    },
    onError: (error: Error) => setMessage(error.message),
  });
  return (
    <div className="flex flex-col gap-1">
      <Button aria-label={`Retry ${title}`} onClick={() => retry.mutate()} disabled={retry.isPending}>
        {retry.isPending ? "Retrying…" : "Retry"}
      </Button>
      {message && (
        <p role="alert" className="text-xs text-err">
          {message}
        </p>
      )}
    </div>
  );
}
