// A library's settings: overrides as a form from Kometa's config schema. Empty means the global
// settings: block (or Kometa's default) applies; clearing every field removes the section.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, type SaveResult } from "../../api";
import { LeaveGuard } from "../LeaveGuard";
import { Button, Card } from "../ui";
import { SaveError, ValidationReport } from "../ValidationReport";
import { loadSchema, type JsonSchema } from "../../yaml/schema";
import { formableKeys, MappingFields, ReadOnlyFields, type Values } from "./schemaFields";

const WIKI = "https://kometa.wiki/en/latest/config/settings/";

// Same groups as Settings → Kometa; a library only overrides what it sets.
const groups: { title: string; keys: string[] }[] = [
  {
    title: "Collections",
    keys: [
      "sync_mode",
      "minimum_items",
      "delete_below_minimum",
      "delete_not_scheduled",
      "default_collection_order",
      "missing_only_released",
      "only_filter_missing",
      "run_again_delay",
      "item_refresh_delay",
      "ignore_ids",
      "ignore_imdb_ids",
      "auto_sort_hubs",
      "hub_priority",
    ],
  },
  {
    title: "Assets (your own posters)",
    keys: [
      "asset_directory",
      "asset_folders",
      "asset_depth",
      "create_asset_folders",
      "prioritize_assets",
      "dimensional_asset_rename",
      "download_url_assets",
      "show_missing_assets",
      "show_missing_season_assets",
      "show_missing_episode_assets",
      "show_asset_not_needed",
    ],
  },
  { title: "Overlays", keys: ["overlay_artwork_filetype", "overlay_artwork_quality"] },
  { title: "Playlists", keys: ["playlist_sync_to_users", "playlist_exclude_users", "playlist_report"] },
  { title: "Reports and log detail", keys: ["save_report", "show_missing", "show_unmanaged", "show_unconfigured", "show_filtered", "show_unfiltered", "show_options"] },
  { title: "How Kometa runs", keys: ["run_order", "cache", "cache_expiration", "threading", "verify_ssl", "tvdb_language", "custom_repo"] },
];

function SettingsEditor({ library, saved, root, schema }: { library: string; saved: Values; root: JsonSchema | null; schema: JsonSchema | undefined }) {
  const [values, setValues] = useState<Values>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const save = useMutation<SaveResult, Error, { base: Values; values: Values }>({
    mutationFn: ({ base, values: next }) => api.config.saveLibrarySettings(library, base, next),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
  const known = useMemo(() => formableKeys(root, schema), [root, schema]);
  const sections = useMemo(() => {
    const byName = new Map(known.map((key) => [key.name, key]));
    const grouped = new Set(groups.flatMap((group) => group.keys));
    const other = known.map((key) => key.name).filter((key) => !grouped.has(key));
    const listed = groups
      .map((group) => ({ title: group.title, keys: group.keys.map((name) => byName.get(name)).filter((key): key is NonNullable<typeof key> => !!key) }))
      .filter((group) => group.keys.length > 0);
    return [...listed, ...(other.length ? [{ title: "Other", keys: other.map((name) => byName.get(name)!).filter(Boolean) }] : [])];
  }, [known]);
  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  const set = (key: string, value: unknown) =>
    setValues((current) => {
      const next = { ...current };
      if (value === undefined) delete next[key];
      else next[key] = value;
      return next;
    });
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
      aria-label="Library settings"
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && badYaml.size === 0) save.mutate({ base: saved, values });
      }}
    >
      <LeaveGuard dirty={dirty || badYaml.size > 0} />
      <p className="text-sm text-muted">
        Overrides of Kometa's <code className="font-mono text-xs">settings:</code> for this library only. A setting left empty is taken out, so the global
        settings (or Kometa's default) apply.{" "}
        <a className="underline hover:text-text" href={WIKI} target="_blank" rel="noreferrer">
          Kometa's wiki on settings
        </a>
      </p>
      {sections.map((section, index) => {
        const setHere = section.keys.filter((key) => key.name in values).length;
        return (
          <details key={section.title} open={index === 0 || setHere > 0} className="rounded-control border border-border">
            <summary className="flex min-h-11 cursor-pointer items-center gap-2 px-3 text-sm font-semibold">
              {section.title}
              <span className="text-xs font-normal text-muted">{setHere > 0 ? `${setHere} set` : "all defaults"}</span>
            </summary>
            <div className="border-t border-border p-3">
              <MappingFields root={root} values={values} onChange={set} onValidity={validity} keys={section.keys} />
            </div>
          </details>
        );
      })}
      <ReadOnlyFields root={root} schema={schema} values={values} />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" type="submit" disabled={!dirty || badYaml.size > 0 || save.isPending}>
          {save.isPending ? "Kometa is checking…" : "Save settings"}
        </Button>
        {dirty && (
          <Button
            onClick={() => {
              setValues(saved);
              save.reset();
            }}
          >
            Undo my changes
          </Button>
        )}
        {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML first.</span>}
      </div>
      {save.isSuccess && <ValidationReport validation={save.data.validation} saved />}
      <SaveError error={save.error} />
    </form>
  );
}

export function LibrarySettingsForm({ library, settings }: { library: string; settings: Values }) {
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const root = schema.data?.root ?? null;
  // Library settings use the same definition as the global settings: block.
  const settingsSchema = root?.definitions?.settings ?? root?.properties?.settings;
  return (
    <Card title="Library settings">
      {schema.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : (
        <SettingsEditor key={JSON.stringify(settings)} library={library} saved={settings} root={root} schema={settingsSchema} />
      )}
    </Card>
  );
}
