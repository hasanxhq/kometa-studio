// Editing one of Kometa's YAML files. Kometa checks every save; nothing is written if it finds new problems.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError, api, saveRefusal, type EditableFile, type Validation } from "../api";
import { Button, Card } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";

function Editor({ file, onSaved, onReload }: { file: EditableFile; onSaved: () => void; onReload: () => void }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(file.text);
  const [verdict, setVerdict] = useState<{ validation: Validation; saved: boolean } | null>(null);
  const [problem, setProblem] = useState<{ message: string; conflict: boolean } | null>(null);
  const dirty = text !== file.text;

  // After a save, show the file as saved: a new secret typed in is masked again like the others.
  const shownHash = useRef(file.hash);
  useEffect(() => {
    if (file.hash !== shownHash.current) {
      shownHash.current = file.hash;
      setText(file.text);
    }
  }, [file.hash, file.text]);

  // Warn before leaving with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const edit = () => [{ path: file.path, text, base_hash: file.hash }];
  const check = useMutation({
    mutationFn: () => api.files.check(edit()),
    onMutate: () => {
      setVerdict(null);
      setProblem(null);
    },
    onSuccess: (validation) => setVerdict({ validation, saved: false }),
    onError: (error) => setProblem({ message: error.message, conflict: false }),
  });
  const save = useMutation({
    mutationFn: () => api.files.save(edit(), `Edited ${file.path} in Studio`),
    onMutate: () => {
      setVerdict(null);
      setProblem(null);
    },
    onSuccess: (result) => {
      setVerdict({ validation: result.validation, saved: true });
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      onSaved();
    },
    onError: (error) => {
      const refusal = saveRefusal(error);
      if (refusal?.validation) setVerdict({ validation: refusal.validation, saved: false });
      setProblem({ message: error.message, conflict: error instanceof ApiError && error.status === 409 });
    },
  });
  const busy = check.isPending || save.isPending;

  // Tab indents with two spaces, as YAML wants. Escape, then Tab, moves on (so Tab isn't a trap).
  const escaped = useRef(false);
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") {
      escaped.current = true;
      return;
    }
    const leaving = escaped.current;
    escaped.current = false;
    if (leaving || event.key !== "Tab" || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    const el = event.currentTarget;
    const { selectionStart, selectionEnd } = el;
    const next = text.slice(0, selectionStart) + "  " + text.slice(selectionEnd);
    setText(next);
    requestAnimationFrame(() => el.setSelectionRange(selectionStart + 2, selectionStart + 2));
  };

  return (
    <div className="flex flex-col gap-4">
      {file.hidden > 0 && (
        <p className="text-sm text-muted">
          {file.hidden} secret{file.hidden === 1 ? " is" : "s are"} hidden as ••••(n). Leave a placeholder exactly as it is to keep that value, or replace
          it completely to change it.
        </p>
      )}
      <textarea
        aria-label={`Contents of ${file.path}`}
        className="min-h-[28rem] w-full resize-y whitespace-pre rounded-control border border-border-strong bg-bg p-3 font-mono text-xs leading-5 text-text focus:border-accent focus:outline-none"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        spellCheck={false}
        autoCapitalize="off"
        autoComplete="off"
        wrap="off"
        aria-describedby="editor-keys"
      />
      <p id="editor-keys" className="-mt-2 text-xs text-muted">
        Tab indents two spaces. Press Esc, then Tab, to move on.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => save.mutate()} disabled={!dirty || busy}>
          {save.isPending ? "Kometa is checking…" : "Save"}
        </Button>
        <Button onClick={() => check.mutate()} disabled={busy}>
          {check.isPending ? "Checking…" : "Check with Kometa"}
        </Button>
        <Button onClick={() => setText(file.text)} disabled={!dirty || busy}>
          Undo my changes
        </Button>
        {dirty && <span className="text-sm text-muted">Unsaved changes</span>}
      </div>
      {problem && !verdict && (
        <p role="alert" className="text-err">
          {problem.message}
        </p>
      )}
      {problem?.conflict && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-warn">Your changes aren't saved. Copy anything you want to keep, then reload the file.</span>
          <Button onClick={onReload}>Reload from disk</Button>
        </div>
      )}
      {verdict && <ValidationReport validation={verdict.validation} saved={verdict.saved} />}
      {verdict?.saved && (
        <p className="text-sm text-muted">
          The previous version is in <Link className="underline" to="/system/backup">System → Backup</Link>.
        </p>
      )}
    </div>
  );
}

export function FileEditor() {
  const [params] = useSearchParams();
  const path = params.get("path") ?? "config.yml";
  const file = useQuery({ queryKey: ["edit", path], queryFn: () => api.files.open(path), staleTime: Infinity, gcTime: 0 });
  // After a save the editor keeps its text and verdict and takes the new hash; a reload starts it afresh.
  const [version, setVersion] = useState(0);
  const saved = () => file.refetch();
  const reload = () => file.refetch().then(() => setVersion((v) => v + 1));

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <Link to="/libraries" className="min-h-11 content-center text-sm text-muted underline">
        ← Libraries
      </Link>
      <Card title={path}>
        {file.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : file.isError ? (
          <p role="alert" className="text-err">
            {file.error.message}
          </p>
        ) : (
          <Editor key={version} file={file.data} onSaved={saved} onReload={reload} />
        )}
      </Card>
    </div>
  );
}
