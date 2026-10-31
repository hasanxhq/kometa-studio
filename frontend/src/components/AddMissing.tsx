// A collection's "add missing items": Kometa sends what the sources list but Plex doesn't have to Radarr (movie
// libraries) or Sonarr (show libraries). config.yml's radarr:/sonarr: block can turn it on for every collection;
// radarr_add_missing (or sonarr_) here overrides that for this one, so the key is only written when it differs.

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api, type ArrKind } from "../api";
import { Card, Checkbox } from "./ui";

type Value = Record<string, unknown>;

const NAMES: Record<ArrKind, string> = { radarr: "Radarr", sonarr: "Sonarr" };

/** The keys this card owns, for an app. */
export const addMissingKeys = (app: ArrKind) => [`${app}_add_missing`, `${app}_search`];

/** Which app gets a library's missing items: Radarr for movies, Sonarr for shows, none for music or photos. */
export function missingApp(libraryType: string | undefined): ArrKind | null {
  return libraryType === "movie" ? "radarr" : libraryType === "show" ? "sonarr" : null;
}

function withKey(value: Value, key: string, next: unknown): Value {
  const copy = { ...value };
  if (next === undefined) delete copy[key];
  else copy[key] = next;
  return copy;
}

export function AddMissing({ app, value, setValue }: { app: ArrKind; value: Value; setValue: (value: Value) => void }) {
  const arr = useQuery({ queryKey: ["arr"], queryFn: api.arr.get });
  const name = NAMES[app];
  const items = app === "radarr" ? "movies" : "shows";
  const [addKey, searchKey] = addMissingKeys(app);
  const connection = arr.data?.connections[app];
  if (!connection) return null;

  const everywhere = { add: connection.add_missing, search: connection.search };
  const add = typeof value[addKey] === "boolean" ? (value[addKey] as boolean) : everywhere.add;
  const search = typeof value[searchKey] === "boolean" ? (value[searchKey] as boolean) : everywhere.search;
  // Kometa never sends a smart collection's missing items (builder.py turns add_missing off for them).
  const smart = "smart_filter" in value || "smart_url" in value;
  const disabled = !connection.url || smart;

  const setAdd = (next: boolean) => {
    let changed = withKey(value, addKey, next === everywhere.add ? undefined : next);
    if (!next) changed = withKey(changed, searchKey, undefined);
    setValue(changed);
  };
  const setSearch = (next: boolean) => setValue(withKey(value, searchKey, next === everywhere.search ? undefined : next));

  return (
    <Card title="Missing items">
      <div className="flex flex-col gap-1">
        <Checkbox checked={add && !smart} disabled={disabled} onChange={setAdd}>
          Add missing {items} to {name}{" "}
          <span className="text-warn">
            (use with caution: big lists and collections can send dozens of {items} to {name} at once)
          </span>
        </Checkbox>
        {add && !disabled && (
          <div className="pl-6">
            <Checkbox checked={search} onChange={setSearch}>
              Search for them as they're added <span className="text-muted">(otherwise {name} only monitors them, and waits for a new release)</span>
            </Checkbox>
          </div>
        )}
        <p className="text-xs text-muted">
          {!connection.url ? (
            <>
              {name} isn't connected. <Link className="underline" to="/settings/connect">Connect it in Settings → Connect</Link> first.
            </>
          ) : smart ? (
            `Kometa never sends a smart collection's missing ${items} to ${name}.`
          ) : (
            <>
              When this collection runs, Kometa sends {name} what its sources list but Plex doesn't have, after the filters. {name} adds them with config.yml's root
              folder and quality profile.
              {everywhere.add && " config.yml turns this on for every collection; unticking it here turns it off for this one."}
            </>
          )}
        </p>
      </div>
    </Card>
  );
}
