// Designed forms for one collection or overlay (handoff v2 §7.1): common settings as fields, every
// other setting from Kometa's schema under Show Advanced, and settings the schema doesn't know kept
// as written. Saving changes only this item, and Kometa checks it like any save.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAdvanced } from "../advanced";
import { api, saveRefusal, type ConfigLibrary, type FileReference, type ItemSection, type SaveResult, type Validation } from "../api";
import { AddMissing, addMissingKeys, missingApp as missingAppFor } from "../components/AddMissing";
import { FilterChips } from "../components/FilterChips";
import { Problems, SettingField, YamlBox } from "../components/forms/fields";
import { Button, Card, Field, inputClass } from "../components/ui";
import { ValidationReport } from "../components/ValidationReport";
import { useLibraryType } from "../libraries";
import { itemProblems } from "../yaml/check";
import { controlFor, knownKeys, loadSchema, type JsonSchema, type KeyInfo, type SchemaKind } from "../yaml/schema";

type Value = Record<string, unknown>;

// Builder keys start with their source, as in Kometa's modules (same list as the backend's).
const SOURCES = "anidb anilist flicklist floppy icheckmovies imdb letterboxd mal mdblist mojo plex radarr reciperr serializd sonarr stevenlu tautulli tmdb trakt tvdb wetrakr".split(" ");
// Radarr and Sonarr have two builders each; radarr_add_missing, radarr_search and the rest are settings.
const ARR_BUILDERS = ["radarr_all", "radarr_taglist", "sonarr_all", "sonarr_taglist"];
export const isBuilder = (key: string) => {
  const source = key.split("_")[0];
  if (source === "radarr" || source === "sonarr") return ARR_BUILDERS.includes(key);
  return key === "smart_filter" || key === "smart_label" || (key.includes("_") && SOURCES.includes(source));
};

const COMMON_BUILDERS = [
  "tmdb_collection",
  "tmdb_movie",
  "tmdb_show",
  "tmdb_list",
  "tmdb_company",
  "tmdb_keyword",
  "tmdb_trending_weekly",
  "tmdb_popular",
  "tvdb_show",
  "imdb_list",
  "imdb_chart",
  "trakt_list",
  "trakt_chart",
  "mdblist_list",
  "letterboxd_list",
  "plex_search",
  "plex_all",
  "smart_filter",
];

const DESIGNED: Record<string, { key: string; label: string; hint?: string }[]> = {
  collections: [
    { key: "summary", label: "Summary" },
    { key: "sort_title", label: "Sort title", hint: 'Starting with "!" sorts it above other collections.' },
    { key: "sync_mode", label: "Sync mode", hint: "sync removes items the sources no longer list; append only adds." },
    { key: "collection_order", label: "Order of items", hint: "e.g. release, alpha, added, custom" },
    { key: "minimum_items", label: "Minimum items", hint: "Smaller collections aren't built." },
    { key: "visible_home", label: "Show on Home" },
    { key: "visible_library", label: "Show in the library's recommendations" },
    { key: "visible_shared", label: "Show on friends' Home" },
    { key: "schedule", label: "Schedule", hint: "e.g. daily, weekly(sunday)" },
  ],
  overlays: [],
  playlists: [
    { key: "libraries", label: "Libraries", hint: "The libraries it takes items from, as named in config.yml, separated by commas." },
    { key: "summary", label: "Summary" },
    { key: "sync_to_users", label: "Share with", hint: "Plex users who get a copy: all, or names separated by commas." },
    { key: "exclude_users", label: "But not with", hint: "Users left out when sharing with all." },
    { key: "sync_mode", label: "Sync mode", hint: "sync removes items the source no longer lists; append only adds." },
    { key: "schedule", label: "Schedule", hint: "e.g. daily, weekly(sunday)" },
  ],
};

const OVERLAY_FIELDS: { key: string; label: string }[] = [
  { key: "name", label: "Image or text" },
  { key: "horizontal_align", label: "Horizontal" },
  { key: "horizontal_offset", label: "Horizontal offset" },
  { key: "vertical_align", label: "Vertical" },
  { key: "vertical_offset", label: "Vertical offset" },
  { key: "back_color", label: "Background colour" },
  { key: "back_width", label: "Background width" },
  { key: "back_height", label: "Background height" },
  { key: "back_radius", label: "Corner radius" },
  { key: "back_padding", label: "Padding" },
  { key: "font_size", label: "Font size" },
  { key: "font_color", label: "Font colour" },
];

const OFFSET_KEYS = new Set(["horizontal_offset", "vertical_offset"]);

const NEW_FILE = "\u0000new"; // the file picker's "A new file" choice

/** The files a new item can go in: the library's collection or overlay files, or config.yml's playlist files. */
function ownFiles(library: ConfigLibrary | undefined, section: ItemSection, playlistFiles: FileReference[] | undefined): string[] {
  const references = (section === "playlists" ? playlistFiles : section === "overlays" ? library?.overlay_files : library?.collection_files) ?? [];
  return references
    .filter((r) => r.kind === "file" || r.kind === "folder")
    .flatMap((r) => r.files.map((f) => f.path))
    .filter((path) => !path.startsWith("/"));
}

/** A name for the new file that none of the library's (or the playlist) files has yet. */
function suggestedName(library: string | null, section: ItemSection, taken: string[]): string {
  const base = section === "playlists" ? "Playlists" : (library ?? "").replace(/[\\/:*?"<>|]+/g, " ").trim() || "Collections";
  const word = section === "overlays" ? "Overlays" : section === "playlists" ? "" : "Collections";
  const candidates = section === "overlays" ? [`${base} Overlays.yml`] : section === "playlists" ? [`${base}.yml`] : [`${base}.yml`, `${base} Collections.yml`];
  for (let n = 2; candidates.length < 12; n++) candidates.push(`${base}${word ? ` ${word}` : ""} ${n}.yml`);
  const lower = new Set(taken.map((t) => t.toLowerCase()));
  return candidates.find((c) => !lower.has(c.toLowerCase()))!;
}

const withSuffix = (name: string) => (/\.ya?ml$/i.test(name.trim()) ? name.trim() : `${name.trim()}.yml`);

const SOURCE_NAMES: Record<string, string> = {
  anidb: "AniDB",
  anilist: "AniList",
  flicklist: "FlickList",
  floppy: "Floppy",
  icheckmovies: "iCheckMovies",
  imdb: "IMDb",
  letterboxd: "Letterboxd",
  mal: "MyAnimeList",
  mdblist: "MDBList",
  mojo: "Box Office Mojo",
  plex: "Plex",
  radarr: "Radarr",
  reciperr: "Reciperr",
  serializd: "Serializd",
  smart: "Smart collections",
  sonarr: "Sonarr",
  stevenlu: "StevenLu",
  tautulli: "Tautulli",
  tmdb: "TMDb",
  trakt: "Trakt",
  tvdb: "TVDb",
  wetrakr: "WeTrakr",
};

// Sources Kometa refuses in the other type of library: 2.5.3's builder.py, show_only_builders and movie_only_builders.
const SHOW_ONLY = [
  "serializd_list",
  "serializd_watchlist",
  "serializd_trending",
  "serializd_popular",
  "serializd_featured",
  "tmdb_network",
  "tmdb_show",
  "tmdb_show_details",
  "tvdb_show",
  "tvdb_show_details",
  "tmdb_airing_today",
  "tmdb_on_the_air",
  "sonarr_all",
  "sonarr_taglist",
  "flicklist_up_next",
  "flicklist_tracked",
];
const MOVIE_ONLY = [
  "letterboxd_list",
  "letterboxd_list_details",
  "letterboxd_crew",
  "letterboxd_studio",
  "letterboxd_country",
  "letterboxd_language",
  "letterboxd_genre",
  "letterboxd_theme",
  "letterboxd_similar",
  "letterboxd_collection",
  "letterboxd_user_films",
  "letterboxd_user_films_details",
  "letterboxd_user_reviews",
  "letterboxd_user_reviews_details",
  "icheckmovies_list",
  "icheckmovies_list_details",
  "stevenlu_popular",
  "tmdb_collection",
  "tmdb_collection_details",
  "tmdb_movie",
  "tmdb_movie_details",
  "tmdb_now_playing",
  "tvdb_movie",
  "tvdb_movie_details",
  "tmdb_upcoming",
  "radarr_all",
  "radarr_taglist",
  "mojo_world",
  "mojo_domestic",
  "mojo_international",
  "mojo_record",
  "mojo_all_time",
  "mojo_never",
];
// A music library takes only these (builder.py: music_attributes), plus the summaries and artwork, which fill nothing.
const MUSIC_SOURCES = ["plex_search", "plex_all", "smart_filter", "smart_label"];
const MUSIC_DETAIL = /_(summary|description|biography|poster|profile|background|logo|square_art)$/;

/** Why a source can't be used in this type of library: the group it goes in, or nothing if it can. */
function libraryLimit(key: string, libraryType: string | undefined): string | undefined {
  if (libraryType === "movie" && SHOW_ONLY.includes(key)) return "TV libraries only";
  if (libraryType === "show" && MOVIE_ONLY.includes(key)) return "Movie libraries only";
  if (libraryType === "artist" && !MUSIC_SOURCES.includes(key) && !MUSIC_DETAIL.test(key)) return "Not for music libraries";
  return undefined;
}

type SourceGroup = { label: string; keys: string[]; greyed?: "setup" | "library" };

/**
 * The Add a source list: the most used, then each service by name, then what can't be used yet (a service that isn't
 * set up), then what can't be used in this library at all, whatever is set up. The last two are greyed out.
 */
export function sourceGroups(allKeys: string[], unavailable: Record<string, string>, libraryType?: string): SourceGroup[] {
  const limited = allKeys.filter((key) => libraryLimit(key, libraryType));
  const keys = allKeys.filter((key) => !limited.includes(key));
  const source = (key: string) => key.split("_")[0];
  const name = (prefix: string) => SOURCE_NAMES[prefix] ?? prefix;
  const usable = keys.filter((key) => !unavailable[source(key)]);
  const bySource = (list: string[]) =>
    [...new Set(list.map(source))].sort((a, b) => name(a).localeCompare(name(b))).map((prefix) => ({ prefix, keys: list.filter((key) => source(key) === prefix) }));
  const common = usable.filter((key) => COMMON_BUILDERS.includes(key));
  return [
    ...(common.length ? [{ label: "Most used", keys: common }] : []),
    ...bySource(usable.filter((key) => !common.includes(key))).map((group) => ({ label: name(group.prefix), keys: group.keys })),
    ...bySource(keys.filter((key) => unavailable[source(key)])).map((group) => ({ label: `${name(group.prefix)} (${unavailable[group.prefix]})`, keys: group.keys, greyed: "setup" as const })),
    ...(limited.length ? [{ label: libraryLimit(limited[0], libraryType)!, keys: limited, greyed: "library" as const }] : []),
  ];
}

function withKey(value: Value, key: string, next: unknown): Value {
  const copy = { ...value };
  if (next === undefined) delete copy[key];
  else copy[key] = next;
  return copy;
}

function starting(root: JsonSchema, schema: JsonSchema): unknown {
  const control = controlFor(root, schema);
  if (control.kind === "boolean") return true;
  if (control.kind === "enum") return control.options[0];
  if (control.kind === "integer" || control.kind === "number") return control.minimum ?? 1;
  return null; // empty: the user fills it in
}

// --- Sources -----------------------------------------------------------------------

function Sources({
  value,
  setValue,
  keys,
  root,
  problems,
  onValidity,
  single = false,
  library,
  libraryType,
}: {
  value: Value;
  setValue: (value: Value) => void;
  keys: Map<string, KeyInfo>;
  root: JsonSchema | null;
  problems: Map<string, string[]>;
  onValidity: (key: string, ok: boolean) => void;
  single?: boolean; // a playlist: Kometa takes one source
  library: string | null;
  libraryType: string | undefined;
}) {
  const present = Object.keys(value).filter(isBuilder);
  const available = [...new Set([...COMMON_BUILDERS, ...[...keys.keys()].filter(isBuilder).sort()])].filter((key) => keys.has(key) && !present.includes(key));
  // Sources whose service isn't in config.yml yet are greyed out: a run would fail on them. Until this answers, nothing is.
  const sources = useQuery({ queryKey: ["config", "sources", library], queryFn: () => api.config.sources(library), retry: false });
  const groups = sourceGroups(available, sources.data?.unavailable ?? {}, libraryType);
  return (
    <Card title="Where the items come from">
      <p className="mb-3 text-sm text-muted">
        {single ? "A playlist takes its items from one source." : "Kometa combines every source: anything any of them finds goes in."} Comments in your file stay as they are for every setting you don't change
        here; to keep comments inside a setting you're changing, use the YAML editor.
      </p>
      <div className="flex flex-col gap-4">
        {present.map((key) => (
          <div key={key} className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <SettingField
                name={key}
                root={root}
                schema={keys.get(key)?.schema}
                value={value[key]}
                // An emptied source stays (as an empty value) until it's removed with the button.
                onChange={(next) => setValue(withKey(value, key, next === undefined ? null : next))}
                onValidity={(ok) => onValidity(key, ok)}
                problems={problems.get(key)}
                hint={keys.get(key)?.description}
              />
            </div>
            <Button className="mt-6" aria-label={`Remove ${key}`} onClick={() => setValue(withKey(value, key, undefined))}>
              Remove
            </Button>
          </div>
        ))}
        {present.length === 0 && <p className="text-sm text-warn">No sources yet: this would be empty.</p>}
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="text-muted">Add a source</span>
          <select
            className={inputClass}
            value=""
            onChange={(e) => e.target.value && root && setValue({ ...value, [e.target.value]: starting(root, keys.get(e.target.value)!.schema) })}
          >
            <option value="">Choose…</option>
            {groups.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.keys.map((key) => (
                  <option key={key} value={key} disabled={!!group.greyed}>
                    {key}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {groups.some((group) => group.greyed === "setup") && (
          <p className="text-xs text-muted">
            Greyed-out sources need a service that isn't set up yet. Radarr, Sonarr, Tautulli, TMDb and MDBList connect in{" "}
            <Link className="underline" to="/settings/connect">
              Settings → Connect
            </Link>
            ; the others go in config.yml.
          </p>
        )}
      </div>
    </Card>
  );
}

// --- Overlay position --------------------------------------------------------------

function OffsetInput({ value, onChange, label }: { value: unknown; onChange: (v: unknown) => void; label: string }) {
  return (
    <input
      aria-label={label}
      className={inputClass}
      value={value === undefined ? "" : String(value)}
      placeholder="e.g. 30 or 5%"
      onChange={(e) => {
        const text = e.target.value.trim();
        onChange(text === "" ? undefined : /^-?\d+$/.test(text) ? Number(text) : text);
      }}
    />
  );
}

/** Where the badge sits on a poster, at Kometa's 1000×1500 poster size. */
function PosterPreview({ spec }: { spec: Value }) {
  const px = (v: unknown, size: number) => (typeof v === "string" && v.endsWith("%") ? (Number(v.slice(0, -1)) / 100) * size : Number(v ?? 0) || 0);
  const width = Number(spec.back_width ?? 300);
  const height = Number(spec.back_height ?? 105);
  const h = String(spec.horizontal_align ?? "left");
  const v = String(spec.vertical_align ?? "top");
  const x = h === "left" ? px(spec.horizontal_offset, 1000) : h === "right" ? 1000 - width - px(spec.horizontal_offset, 1000) : (1000 - width) / 2 + px(spec.horizontal_offset, 1000);
  const y = v === "top" ? px(spec.vertical_offset, 1500) : v === "bottom" ? 1500 - height - px(spec.vertical_offset, 1500) : (1500 - height) / 2 + px(spec.vertical_offset, 1500);
  const label = String(spec.text ?? spec.name ?? "").replace(/^text\((.*)\)$/, "$1");
  return (
    <figure className="flex flex-col items-center gap-2">
      <div className="relative aspect-[2/3] w-40 overflow-hidden rounded-control border border-border bg-gradient-to-b from-surface-2 to-bg" aria-label="Poster preview">
        <div
          className="absolute flex items-center justify-center overflow-hidden text-center font-display text-[10px] font-semibold"
          style={{
            left: `${(x / 1000) * 100}%`,
            top: `${(y / 1500) * 100}%`,
            width: `${(width / 1000) * 100}%`,
            height: `${(height / 1500) * 100}%`,
            background: typeof spec.back_color === "string" ? spec.back_color : "rgba(0,0,0,0.6)",
            color: typeof spec.font_color === "string" ? spec.font_color : "#fff",
            borderRadius: spec.back_radius ? `${(Number(spec.back_radius) / 1000) * 160}px` : undefined,
          }}
        >
          {label}
        </div>
      </div>
      <figcaption className="text-xs text-muted">Placement only; Kometa draws the real overlay.</figcaption>
    </figure>
  );
}

function OverlayDesign({
  value,
  setValue,
  root,
  name,
  problems,
}: {
  value: Value;
  setValue: (value: Value) => void;
  root: JsonSchema | null;
  name: string;
  problems: Map<string, string[]>;
}) {
  const raw = value.overlay;
  const spec: Value = typeof raw === "string" ? { name: raw } : raw && typeof raw === "object" ? (raw as Value) : {};
  const specKeys = new Map((root ? knownKeys(root, ["overlays", name || "_", "overlay"]) : []).map((k) => [k.name, k]));
  const set = (key: string, next: unknown) => {
    const updated = withKey(spec, key, next);
    // Keep Kometa's shorthand (`overlay: 4K`) while only the name is set.
    setValue({ ...value, overlay: Object.keys(updated).length === 1 && "name" in updated && typeof raw === "string" ? updated.name : updated });
  };
  return (
    <Card title="The overlay">
      <div className="flex flex-col gap-6 md:flex-row">
        <PosterPreview spec={spec} />
        <div className="grid flex-1 gap-4 sm:grid-cols-2">
          {OVERLAY_FIELDS.map(({ key, label }) =>
            OFFSET_KEYS.has(key) ? (
              <Field key={key} label={`${label} (${key})`}>
                <OffsetInput value={spec[key]} onChange={(next) => set(key, next)} label={label} />
              </Field>
            ) : (
              <SettingField key={key} name={key} label={label} root={root} schema={specKeys.get(key)?.schema} value={spec[key]} onChange={(next) => set(key, next)} />
            ),
          )}
        </div>
      </div>
      <Problems messages={problems.get("overlay")} />
    </Card>
  );
}

// --- Page ------------------------------------------------------------------------------

export default function ItemEditor() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showAdvanced } = useAdvanced();
  const path = params.get("path") ?? "";
  const section = (params.get("section") ?? "collections") as ItemSection;
  const original = params.get("name") ?? "";
  const library = params.get("library");
  const creating = params.get("new") === "1";
  const newFile = creating && !path; // a new file, added to the library's list (or playlist_files) in config.yml when it's saved
  const playlist = section === "playlists"; // playlists aren't per library: their files are config.yml's playlist_files
  const noun = section === "overlays" ? "overlay" : playlist ? "playlist" : "collection";
  const libraryConfig = useQuery({ queryKey: ["config", "library", library], queryFn: () => api.config.library(library!), enabled: creating && !!library });
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, enabled: creating && playlist, retry: false });
  const files = ownFiles(libraryConfig.data, section, overview.data?.playlist_files);
  const libraryType = useLibraryType(library); // what Plex says the library is, once it's answered
  const missingApp = section === "collections" ? missingAppFor(libraryType) : null;
  const [fileName, setFileName] = useState<string | null>(null);
  const newName = fileName ?? (library || playlist ? suggestedName(library, section, files) : "");

  const item = useQuery({
    queryKey: ["item", path, section, original, creating],
    queryFn: async () => {
      if (!creating) return api.items.get(path, section, original);
      if (!path) return { path: "", hash: "", section, name: "", value: {}, kind: (section === "overlays" ? "overlay" : section === "playlists" ? "playlist" : "collection") as SchemaKind };
      const file = await api.files.open(path);
      return { path, hash: file.hash, section, name: "", value: {}, kind: file.kind };
    },
    staleTime: Infinity,
    gcTime: 0,
  });
  const kind = (item.data?.kind ?? (section === "overlays" ? "overlay" : section === "playlists" ? "playlist" : "collection")) as SchemaKind;
  const schema = useQuery({ queryKey: ["schema", kind], queryFn: () => loadSchema(kind), staleTime: Infinity });

  const [edited, setEdited] = useState<Value | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [badYaml, setBadYaml] = useState<Set<string>>(new Set());
  const [verdict, setVerdict] = useState<{ validation: Validation; saved: boolean } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const value = edited ?? item.data?.value ?? {};
  const currentName = name ?? item.data?.name ?? "";
  const root = schema.data?.root ?? null;
  const keys = useMemo(() => new Map((root ? knownKeys(root, [section, currentName || "_"]) : []).map((k) => [k.name, k])), [root, section, currentName]);
  const problems = useMemo(
    () => (schema.data ? itemProblems(schema.data.validate, section, currentName, value) : new Map<string, string[]>()),
    [schema.data, section, currentName, value],
  );
  const dirty = edited !== null || (name !== null && name !== item.data?.name);
  const validity = (key: string, ok: boolean) =>
    setBadYaml((current) => {
      const next = new Set(current);
      if (ok) next.delete(key);
      else next.add(key);
      return next;
    });

  const afterSave = (saved: string, result: SaveResult) => {
    queryClient.invalidateQueries({ queryKey: ["config"] });
    queryClient.invalidateQueries({ queryKey: ["backups"] });
    setEdited(null);
    setName(null);
    if (saved !== original || creating) {
      const next = new URLSearchParams(params);
      next.set("name", saved);
      next.delete("new");
      if (newFile) next.set("path", result.files[0].path); // the new file comes first, then config.yml
      navigate(`/items?${next}`, { replace: true });
    } else {
      item.refetch();
    }
  };
  const save = useMutation({
    mutationFn: () =>
      api.items.save({
        path: newFile ? withSuffix(newName) : path,
        base_hash: newFile ? null : item.data!.hash,
        section,
        name: creating ? currentName : original,
        value,
        create: creating,
        rename: !creating && currentName !== original ? currentName : null,
        ...(newFile && !playlist ? { library } : {}),
      }),
    onMutate: () => setVerdict(null),
    onSuccess: (result) => {
      setVerdict({ validation: result.validation, saved: true });
      afterSave(currentName, result);
    },
    onError: (error) => {
      const refusal = saveRefusal(error);
      if (refusal?.validation) setVerdict({ validation: refusal.validation, saved: false });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.items.save({ path, base_hash: item.data!.hash, section, name: original, value: null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      navigate(playlist ? "/playlists" : library ? `/libraries/${encodeURIComponent(library)}` : "/libraries");
    },
  });
  const run = useMutation({
    mutationFn: () =>
      api.runs.create({
        mode: "collections",
        libraries: library ? [library] : [],
        collections: [original],
        files: [],
        ignore_schedules: true,
        no_missing: false,
        tests: false,
        timings: false,
        low_priority: true,
      }),
  });

  if (item.isPending) return <p className="text-muted">Loading…</p>;
  if (item.isError)
    return (
      <p role="alert" className="text-err">
        {item.error.message}
      </p>
    );

  // One set of filters is edited as chips; several sets (a list, any of which may match) stay under Show Advanced.
  const chips = (section === "collections" || playlist) && (value.filters === undefined || (typeof value.filters === "object" && value.filters !== null && !Array.isArray(value.filters)));
  const designed = new Set([...(DESIGNED[section] ?? []).map((d) => d.key), ...(section === "overlays" ? ["overlay"] : []), ...(chips ? ["filters"] : []), ...(missingApp ? addMissingKeys(missingApp) : [])]);
  const present = Object.keys(value);
  const advanced = present.filter((key) => !designed.has(key) && !isBuilder(key) && keys.has(key));
  const unknown = present.filter((key) => !keys.has(key) && !isBuilder(key) && !designed.has(key));
  const addable = [...keys.keys()].filter((key) => !present.includes(key) && !designed.has(key) && !isBuilder(key)).sort();
  const hiddenCount = advanced.length + unknown.length;
  const back = playlist ? "/playlists" : library ? `/libraries/${encodeURIComponent(library)}${section === "overlays" ? "?tab=overlays" : ""}` : "/libraries";

  const designedPart: ReactNode = (
    <>
      <Sources value={value} setValue={setEdited} keys={keys} root={root} problems={problems} onValidity={validity} single={playlist} library={library} libraryType={libraryType} />
      {chips && <FilterChips filters={value.filters as Record<string, unknown> | undefined} onChange={(next) => setEdited(withKey(value, "filters", next))} />}
      {section === "overlays" && <OverlayDesign value={value} setValue={setEdited} root={root} name={currentName} problems={problems} />}
      {(DESIGNED[section] ?? []).length > 0 && (
        <Card title="Settings">
          <div className="grid gap-4 sm:grid-cols-2">
            {DESIGNED[section].map(({ key, label, hint }) => (
              <SettingField
                key={key}
                name={key}
                label={label}
                hint={hint}
                root={root}
                schema={keys.get(key)?.schema}
                value={value[key]}
                onChange={(next) => setEdited(withKey(value, key, next))}
                onValidity={(ok) => validity(key, ok)}
                problems={problems.get(key)}
              />
            ))}
          </div>
        </Card>
      )}
      {missingApp && <AddMissing app={missingApp} value={value} setValue={setEdited} />}
    </>
  );
  const advancedPart: ReactNode = (
    <>
      {showAdvanced ? (
        <Card title="More settings">
          <div className="flex flex-col gap-4">
            {advanced.map((key) => (
              <div key={key} className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <SettingField
                    name={key}
                    root={root}
                    schema={keys.get(key)?.schema}
                    value={value[key]}
                    onChange={(next) => setEdited(withKey(value, key, next))}
                    onValidity={(ok) => validity(key, ok)}
                    problems={problems.get(key)}
                    hint={keys.get(key)?.description}
                  />
                </div>
                <Button className="mt-6" aria-label={`Remove ${key}`} onClick={() => setEdited(withKey(value, key, undefined))}>
                  Remove
                </Button>
              </div>
            ))}
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-muted">Add a setting</span>
              <select
                className={inputClass}
                value=""
                onChange={(e) => e.target.value && root && setEdited({ ...value, [e.target.value]: starting(root, keys.get(e.target.value)!.schema) })}
              >
                <option value="">Choose from Kometa's {addable.length} other settings…</option>
                {addable.map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </label>
            {unknown.length > 0 && (
              <div className="flex flex-col gap-3 border-t border-border pt-4">
                <p className="text-sm text-muted">
                  Kometa's schema doesn't list these, so they're kept as written. Usually they're template variables.
                </p>
                {unknown.map((key) => (
                  <div key={key} className="flex flex-col gap-1.5 text-sm">
                    <span className="font-mono text-xs text-muted">{key}</span>
                    <YamlBox label={key} value={value[key]} onChange={(next) => setEdited(withKey(value, key, next))} onValidity={(ok) => validity(key, ok)} />
                    <Problems messages={problems.get(key)} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      ) : (
        hiddenCount > 0 && (
          <p className="text-sm text-muted">
            {hiddenCount} more setting{hiddenCount === 1 ? " is" : "s are"} set here. Turn on Show Advanced to see {hiddenCount === 1 ? "it" : "them"}.
          </p>
        )
      )}
    </>
  );

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <Link to={back} className="min-h-11 content-center text-sm text-muted underline">
        ← {playlist ? "Playlists" : (library ?? "Libraries")}
      </Link>
      <Card title={newFile ? `New ${noun} in a new file` : creating ? `New ${noun} in ${path}` : `${currentName || original}`}>
        <div className="flex flex-col gap-3">
          <Field label="Name">
            <input className={inputClass} value={currentName} onChange={(e) => setName(e.target.value)} placeholder={section === "overlays" ? "e.g. 4K" : playlist ? "e.g. Marvel in order" : "e.g. Pixar"} />
          </Field>
          {creating && (library || playlist) && (
            <Field label="File">
              <select
                className={inputClass}
                value={path || NEW_FILE}
                onChange={(e) => {
                  const next = new URLSearchParams(params);
                  if (e.target.value === NEW_FILE) next.delete("path");
                  else next.set("path", e.target.value);
                  navigate(`/items?${next}`, { replace: true });
                }}
              >
                {[...new Set([...files, ...(path ? [path] : [])])].map((file) => (
                  <option key={file} value={file}>
                    {file}
                  </option>
                ))}
                <option value={NEW_FILE}>A new file…</option>
              </select>
            </Field>
          )}
          {newFile && (
            <Field
              label="New file's name"
              hint={
                playlist
                  ? "In Kometa's config folder. Saving creates it and adds it to playlist_files in config.yml."
                  : `In Kometa's config folder. Saving creates it and adds it to ${library}'s ${section === "overlays" ? "overlay_files" : "collection_files"} in config.yml.`
              }
            >
              <input className={`${inputClass} font-mono`} value={newName} onChange={(e) => setFileName(e.target.value)} />
            </Field>
          )}
          {newFile && !library && !playlist && (
            <p role="alert" className="text-sm text-err">
              A new file needs a library. Start from the library's page.
            </p>
          )}
          {path && (
            <p className="text-sm text-muted">
              In <span className="font-mono">{path}</span>.{" "}
              <Link className="underline" to={`/files?path=${encodeURIComponent(path)}`}>
                Edit the whole file as YAML
              </Link>
            </p>
          )}
          <Problems messages={problems.get("")} />
        </div>
      </Card>
      {designedPart}
      {advancedPart}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => save.mutate()}
          disabled={!dirty || !currentName.trim() || badYaml.size > 0 || save.isPending || (newFile && ((!library && !playlist) || !newName.trim()))}
        >
          {save.isPending ? "Kometa is checking…" : creating ? `Add ${noun}` : "Save"}
        </Button>
        {dirty && (
          <Button
            onClick={() => {
              setEdited(null);
              setName(null);
            }}
          >
            Undo my changes
          </Button>
        )}
        {!creating && section === "collections" && library && (
          <Button onClick={() => run.mutate()} disabled={dirty || run.isPending} title={dirty ? "Save first" : undefined}>
            Run just this collection
          </Button>
        )}
        {!creating &&
          (confirmDelete ? (
            <>
              <Button onClick={() => remove.mutate()} className="border-err/60 text-err" disabled={remove.isPending}>
                Delete {original}
              </Button>
              <Button onClick={() => setConfirmDelete(false)}>Keep</Button>
            </>
          ) : (
            <Button onClick={() => setConfirmDelete(true)}>Delete…</Button>
          ))}
        {badYaml.size > 0 && <span className="text-sm text-warn">Fix the YAML in {[...badYaml].join(", ")} first.</span>}
        {problems.size > 0 && badYaml.size === 0 && (
          <span className="text-sm text-warn">Kometa's schema flags {problems.size === 1 ? "a setting" : `${problems.size} settings`}; Kometa will check again on save.</span>
        )}
      </div>
      {run.isSuccess && (
        <p role="status" className="text-sm text-ok">
          Queued as <Link className="underline" to={`/activity/queue/${run.data.id}`}>run #{run.data.id}</Link>. Only {original} runs, ignoring its schedule.
        </p>
      )}
      {(save.isError && !verdict) || remove.isError || run.isError ? (
        <p role="alert" className="text-err">
          {(save.error ?? remove.error ?? run.error)?.message}
        </p>
      ) : null}
      {verdict && <ValidationReport validation={verdict.validation} saved={verdict.saved} />}
    </div>
  );
}
