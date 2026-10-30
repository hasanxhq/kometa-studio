// "Add to Kometa": puts a Plex library into config.yml, empty. Its collection files, overlay files and
// defaults come next, from the library's page. Kometa checks the save like any other.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, saveRefusal } from "../api";
import { Button } from "./ui";

export function AddLibrary({ name, variant = "primary" }: { name: string; variant?: "primary" | "secondary" }) {
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: () => api.config.addLibrary(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
  const refusal = add.isError ? saveRefusal(add.error) : null;
  return (
    <div className="flex flex-col gap-1.5">
      <Button variant={variant} onClick={() => add.mutate()} disabled={add.isPending} className="self-start">
        {add.isPending ? "Kometa is checking…" : "Add to Kometa"}
      </Button>
      {add.isError && (
        <p role="alert" className="text-sm text-err">
          {add.error.message}
          {refusal?.validation?.errors.map((error) => (
            <span key={error} className="block break-words font-mono text-xs">
              {error}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
