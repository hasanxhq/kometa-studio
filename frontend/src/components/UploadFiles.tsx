// Adding YAML files to Kometa's config folder from the browser. All or nothing, checked by Kometa first.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, saveRefusal, type Validation } from "../api";
import { Button, Card, Field, inputClass } from "./ui";
import { ValidationReport } from "./ValidationReport";

export function UploadFiles({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [folder, setFolder] = useState("");
  const [verdict, setVerdict] = useState<{ validation: Validation; saved: boolean } | null>(null);
  const target = (name: string) => [folder.trim().replace(/^\/+|\/+$/g, ""), name].filter(Boolean).join("/");

  const upload = useMutation({
    mutationFn: async () => {
      const edits = await Promise.all(files.map(async (file) => ({ path: target(file.name), text: await file.text(), base_hash: null })));
      return api.files.save(edits, `Uploaded ${edits.map((e) => e.path).join(", ")}`);
    },
    onMutate: () => setVerdict(null),
    onSuccess: (result) => {
      setVerdict({ validation: result.validation, saved: true });
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: (error) => {
      const refusal = saveRefusal(error);
      if (refusal?.validation) setVerdict({ validation: refusal.validation, saved: false });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (files.length) upload.mutate();
  };

  return (
    <Card title="Add files" actions={<Button onClick={onDone}>Close</Button>}>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <p className="text-sm text-muted">
          Collection, overlay, metadata or playlist files (.yml) go into Kometa's config folder. Kometa checks them first, and nothing is added if it
          finds a problem. An existing file is never replaced; edit it instead.
        </p>
        <Field label="Files">
          <input
            type="file"
            multiple
            accept=".yml,.yaml"
            className="min-h-11 text-sm file:mr-3 file:min-h-11 file:rounded-control file:border file:border-border-strong file:bg-surface-2 file:px-4 file:text-text"
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
              setVerdict(null);
              upload.reset();
            }}
          />
        </Field>
        <Field label="Folder inside the config folder" hint={files.length ? `Saved as ${files.map((f) => target(f.name)).join(", ")}` : "Leave empty for the config folder itself."}>
          <input className={inputClass} value={folder} onChange={(event) => setFolder(event.target.value)} placeholder="e.g. collections" />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" type="submit" disabled={!files.length || upload.isPending}>
            {upload.isPending ? "Kometa is checking…" : `Check and add ${files.length || ""} file${files.length === 1 ? "" : "s"}`}
          </Button>
          {upload.isError && !verdict && (
            <span role="alert" className="text-sm text-err">
              {upload.error.message}
            </span>
          )}
        </div>
        {verdict && <ValidationReport validation={verdict.validation} saved={verdict.saved} />}
        {verdict?.saved && (
          <p className="text-sm text-muted">
            Kometa uses a file once a library lists it. Add it under a library's <span className="font-mono">collection_files</span> or{" "}
            <span className="font-mono">overlay_files</span> in <Link className="underline" to="/files?path=config.yml">config.yml</Link>.
          </p>
        )}
      </form>
    </Card>
  );
}
