// A library's operations: as a form from Kometa's config schema. A mapping stays a mapping; a list of
// blocks stays a list (Operation 1, Operation 2, …). Common operations first; the rest under More.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, type ConfigLibrary, type SaveResult } from "../../api";
import { LeaveGuard } from "../LeaveGuard";
import { Button, Card } from "../ui";
import { SaveError, ValidationReport } from "../ValidationReport";
import { loadSchema, type JsonSchema } from "../../yaml/schema";
import { formableKeys, MappingFields, ReadOnlyFields, type Values } from "./schemaFields";

const WIKI = "https://kometa.wiki/en/latest/config/operations/";

// The operations people reach for first; the rest sit under "More operations".
const COMMON = [
  "assets_for_all",
  "assets_for_all_collections",
  "delete_collections",
  "mass_genre_update",
  "mass_content_rating_update",
  "mass_audience_rating_update",
  "mass_critic_rating_update",
  "mass_user_rating_update",
  "mass_poster_update",
  "mass_background_update",
  "mass_collection_mode",
  "split_duplicates",
  "ignore_labels",
  "respect_ignore_ids",
  "radarr_add_all",
  "sonarr_add_all",
];

function operationBlocks(operations: ConfigLibrary["operations"]): Values[] {
  // A list keeps every block (including empty ones) so a save round-trips the same list; a mapping always gets one form.
  if (Array.isArray(operations)) return operations.map((block) => (block && typeof block === "object" ? { ...block } : {}));
  return [{ ...operations }];
}

function BlockFields({
  root,
  schema,
  values,
  onChange,
  onValidity,
}: {
  root: JsonSchema | null;
  schema: JsonSchema | undefined;
  values: Values;
  onChange: (key: string, value: unknown) => void;
  onValidity: (key: string, ok: boolean) => void;
}) {
  const keys = useMemo(() => formableKeys(root, schema), [root, schema]);
  const common = keys.filter((key) => COMMON.includes(key.name));
  const more = keys.filter((key) => !COMMON.includes(key.name));
  const moreOpen = more.some((key) => key.name in values);
  return (
    <div className="flex flex-col gap-4">
      <MappingFields root={root} values={values} onChange={onChange} onValidity={onValidity} keys={common} />
      {more.length > 0 && (
        <details open={moreOpen} className="rounded-control border border-border">
          <summary className="flex min-h-11 cursor-pointer items-center gap-2 px-3 text-sm font-semibold">
            More operations
            <span className="text-xs font-normal text-muted">{more.filter((key) => key.name in values).length} set</span>
          </summary>
          <div className="border-t border-border p-3">
            <MappingFields root={root} values={values} onChange={onChange} onValidity={onValidity} keys={more} />
          </div>
        </details>
      )}
      <ReadOnlyFields root={root} schema={schema} values={values} />
    </div>
  );
}

function OperationsEditor({
  library,
  base,
  saved,
  asList,
  root,
  schema,
}: {
  library: string;
  base: Values | Values[];
  saved: Values[];
  asList: boolean;
  root: JsonSchema | null;
  schema: JsonSchema | undefined;
}) {
  const [blocks, setBlocks] = useState<Values[]>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const save = useMutation<SaveResult, Error, { base: Values | Values[]; values: Values | Values[] }>({
    mutationFn: ({ base: from, values }) => api.config.saveLibraryOperations(library, from, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
  const dirty = JSON.stringify(blocks) !== JSON.stringify(saved);
  const payload = (): Values | Values[] => {
    const cleaned = blocks.map((block) => {
      const next: Values = {};
      for (const [key, value] of Object.entries(block)) if (value !== undefined) next[key] = value;
      return next;
    });
    if (asList) return cleaned.every((block) => Object.keys(block).length === 0) ? [] : cleaned;
    return cleaned[0] ?? {};
  };
  const set = (index: number, key: string, value: unknown) =>
    setBlocks((current) =>
      current.map((block, i) => {
        if (i !== index) return block;
        const next = { ...block };
        if (value === undefined) delete next[key];
        else next[key] = value;
        return next;
      }),
    );
  const validity = (key: string, ok: boolean) =>
    setBadYaml((current) => {
      const next = new Set(current);
      if (ok) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <form
      className="flex flex-col gap-4"
      aria-label="Library operations"
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && badYaml.size === 0) save.mutate({ base, values: payload() });
      }}
    >
      <LeaveGuard dirty={dirty || badYaml.size > 0} />
      <p className="text-sm text-muted">
        Kometa's library operations for this library. A field left empty is taken out of config.yml, so Kometa's default applies.{" "}
        <a className="underline hover:text-text" href={WIKI} target="_blank" rel="noreferrer">
          Kometa's wiki on operations
        </a>
      </p>
      {blocks.length === 0 ? (
        <p className="text-sm text-muted">None. List-form operations are edited as whole blocks; add or remove them in the file editor.</p>
      ) : (
        blocks.map((block, index) => (
          <div key={index} className={index > 0 ? "border-t border-border pt-4" : undefined}>
            {asList && <p className="mb-3 text-sm font-semibold text-muted">Operation {index + 1}</p>}
            <BlockFields root={root} schema={schema} values={block} onChange={(key, value) => set(index, key, value)} onValidity={validity} />
          </div>
        ))
      )}
      {blocks.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" type="submit" disabled={!dirty || badYaml.size > 0 || save.isPending}>
            {save.isPending ? "Kometa is checking…" : "Save operations"}
          </Button>
          {dirty && (
            <Button
              onClick={() => {
                setBlocks(saved);
                save.reset();
              }}
            >
              Undo my changes
            </Button>
          )}
          {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML first.</span>}
        </div>
      )}
      {save.isSuccess && <ValidationReport validation={save.data.validation} saved />}
      <SaveError error={save.error} />
    </form>
  );
}

export function OperationsForm({ library, operations }: { library: string; operations: ConfigLibrary["operations"] }) {
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const asList = Array.isArray(operations);
  const saved = operationBlocks(operations);
  const root = schema.data?.root ?? null;
  const operationsSchema = root?.definitions?.operations;
  // Fresh form after each save (parent refetches the library).
  const formKey = JSON.stringify(operations);
  return (
    <Card title="Operations">
      {schema.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : (
        <OperationsEditor key={formKey} library={library} base={operations} saved={saved} asList={asList} root={root} schema={operationsSchema} />
      )}
    </Card>
  );
}
