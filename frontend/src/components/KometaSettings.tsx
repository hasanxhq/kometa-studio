// Kometa's own settings: block in config.yml, as a form: one field per setting, the control chosen from Kometa's
// schema, grouped, each with the installed Kometa's default. A setting left empty is taken out, so Kometa's default applies.

import { useMutation, useQuery, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, type SaveResult } from "../api";
import { mappingKeys, loadSchema, type JsonSchema, type KeyInfo } from "../yaml/schema";
import { SettingField } from "./forms/fields";
import { Button, Card, StickyActions } from "./ui";
import { SaveError, ValidationReport } from "./ValidationReport";

type Values = Record<string, unknown>;

const WIKI = "https://kometa.wiki/en/latest/config/settings/";

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

function label(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function describeDefault(value: unknown): string {
  if (value === null) return "none";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function hint(info: KeyInfo | undefined, defaults: Values, key: string): string | undefined {
  const description = info?.description?.split("\n")[0]?.replace(/^Used to /, "") ?? "";
  const sentence = description ? description.charAt(0).toUpperCase() + description.slice(1).replace(/\.?$/, ".") : "";
  const fallback = key in defaults ? `Kometa's default: ${describeDefault(defaults[key])}.` : "";
  return [sentence, fallback].filter(Boolean).join(" ") || undefined;
}

type Save = UseMutationResult<SaveResult, Error, { base: Values; values: Values }>;

function SettingsForm({ saved, defaults, root, save }: { saved: Values; defaults: Values; root: JsonSchema | null; save: Save }) {
  const [values, setValues] = useState<Values>(saved);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const known = useMemo(() => {
    const keys = root ? mappingKeys(root, root.properties?.settings).keys : [];
    return new Map(keys.map((key) => [key.name, key]));
  }, [root]);
  // Every setting Kometa's schema or its source knows, or config.yml has, in a group; the ungrouped ones under Other.
  const sections = useMemo(() => {
    const grouped = new Set(groups.flatMap((group) => group.keys));
    const other = [...new Set([...known.keys(), ...Object.keys(defaults), ...Object.keys(saved)])].filter((key) => !grouped.has(key)).sort();
    return [...groups, ...(other.length ? [{ title: "Other", keys: other }] : [])];
  }, [known, defaults, saved]);
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
      aria-label="Kometa's settings"
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && badYaml.size === 0) save.mutate({ base: saved, values });
      }}
    >
      <p className="text-sm text-muted">
        The <code className="font-mono text-xs">settings:</code> block in config.yml, for every library (a library's own settings override these). A setting left
        empty is taken out of config.yml, so Kometa's default applies. Kometa checks every save.{" "}
        <a className="underline hover:text-text" href={WIKI} target="_blank" rel="noreferrer">
          Kometa's wiki on settings
        </a>
      </p>
      {sections.map((section, index) => {
        const setHere = section.keys.filter((key) => key in values).length;
        return (
          <details key={section.title} open={index === 0} className="rounded-control border border-border">
            <summary className="flex min-h-11 cursor-pointer items-center gap-2 px-3 text-sm font-semibold">
              {section.title}
              <span className="text-xs font-normal text-muted">{setHere > 0 ? `${setHere} set` : "all Kometa's defaults"}</span>
            </summary>
            <div className="grid gap-4 border-t border-border p-3 sm:grid-cols-2">
              {section.keys.map((key) => (
                <SettingField
                  key={key}
                  name={key}
                  label={label(key)}
                  root={root}
                  schema={known.get(key)?.schema}
                  value={values[key]}
                  onChange={(next) => set(key, next)}
                  onValidity={(ok) => validity(key, ok)}
                  hint={hint(known.get(key), defaults, key)}
                  unset={key in defaults ? `Default (${describeDefault(defaults[key])})` : undefined}
                />
              ))}
            </div>
          </details>
        );
      })}
      <StickyActions>
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
        {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML in {[...badYaml].join(", ")} first.</span>}
      </StickyActions>
      {save.isSuccess && <ValidationReport validation={save.data.validation} saved />}
      <SaveError error={save.error} />
    </form>
  );
}

export function KometaSettings() {
  const settings = useQuery({ queryKey: ["config", "settings"], queryFn: api.config.settings });
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const queryClient = useQueryClient();
  // Here, not in the form: the form starts afresh after a save, and Kometa's verdict should stay on screen.
  const save: Save = useMutation({
    mutationFn: ({ base, values }) => api.config.saveSettings(base, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
  });
  return (
    <Card title="Kometa's settings">
      {settings.isPending || schema.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : settings.isError ? (
        <p role="alert" className="text-err">
          {settings.error.message}
        </p>
      ) : (
        // A fresh form after each save, from what config.yml now says.
        <SettingsForm key={JSON.stringify(settings.data.values)} saved={settings.data.values} defaults={settings.data.defaults} root={schema.data?.root ?? null} save={save} />
      )}
    </Card>
  );
}
