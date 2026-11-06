// The overlay designer, the concept's fourth screen, built on what Kometa has: a layer is an overlay default the library uses, moved
// and styled with that default's template variables. Every change is one save of config.yml that Kometa checks, and the next overlay
// run draws it. What runs overlays and what protects Maintainerr's stay on the Overlays page and in their own hooks.

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { stringify } from "yaml";

import { ApiError, api, type ConfigLibrary, type DefaultEntry, type FileReference, type OverlayLibrary, type PlexItem } from "../api";
import { LeaveGuard, useLeaveEditor } from "../components/LeaveGuard";
import { AnchorGrid, OffsetInput, OverlayPoster, SamplePicker, useSamples } from "../components/OverlayPreview";
import { ConfirmButton, Field, inputClass } from "../components/ui";
import { SaveError } from "../components/ValidationReport";
import { shortTitle } from "../defaults";
import { useLibrary } from "../library";
import { layerBoxes, layerText, resolveLayout, whereItIs, type Box } from "../overlayLayout";
import { defaultVariablesSchema, loadSchema, type JsonSchema } from "../yaml/schema";
import { VariablesEditor, useSave, type Featured, type Values } from "../components/DefaultVariables";

// Read by the controls above the variables, so they stay out of "More variables".
const PLACEMENT = ["horizontal_align", "vertical_align", "horizontal_offset", "vertical_offset", "horizontal_position", "vertical_position"];

type Layer = { name: string; title: string; entry: DefaultEntry | undefined; reference: FileReference; variables: Values };

const titleOf = (reference: FileReference, entry: DefaultEntry | undefined) => shortTitle(entry?.title ?? reference.files[0]?.title ?? reference.value);

/** The controls this default has, besides the anchor. */
function controls(name: string, moved: "align" | "position" | undefined, libraryType: string | null): Featured[] {
  return [
    ...(name === "ratings"
      ? [1, 2, 3].flatMap((n) => [
          { key: `rating${n}`, label: `Rating ${n}` },
          // Kometa works it out from sources such as IMDb and TMDb; critic, audience and user ratings don't say whose they are.
          { key: `rating${n}_image`, label: `Rating ${n} logo`, hint: "Needed for critic, audience and user ratings." },
        ])
      : []),
    ...(name === "ratings" ? [{ key: "rating_alignment", label: "Ratings run" }] : []),
    ...(name === "resolution"
      ? [
          { key: "use_resolution", label: "Resolution badges", switchOn: true },
          { key: "use_edition", label: "Edition badges", switchOn: true },
        ]
      : []),
    ...(name === "streaming" ? [{ key: "originals_only", label: "Originals only", switchOn: false }] : []),
    ...(libraryType === "show" ? [{ key: "builder_level", label: "Draw on", options: { show: "Shows", season: "Seasons", episode: "Episodes" } }] : []),
    { key: "back_color", label: "Back colour", hint: "A hex colour, such as #00000099. The last two digits are opacity." },
    ...(moved === "align" ? [{ key: "back_radius", label: "Radius" }] : []),
  ];
}

function Properties({
  library,
  layer,
  libraryVariables,
  root,
  libraryType,
  onValues,
  onUnsaved,
  onTurnOff,
  turningOff,
}: {
  library: string;
  layer: Layer;
  libraryVariables: Values;
  root: JsonSchema | null;
  libraryType: string | null;
  onValues: (values: Values) => void;
  onUnsaved: (unsaved: boolean) => void;
  onTurnOff: () => void;
  turningOff: boolean;
}) {
  const { name, title, entry, variables } = layer;
  const save = useSave((values: Values) => api.config.useDefault(library, "overlay", name, values));
  const layout = entry?.layout;
  const position = layout?.moved_by === "position";
  const toggles = (entry?.toggles ?? []).filter((toggle) => !libraryType || toggle.types.includes(libraryType));
  // What it starts from, so that putting something back to that takes the variable out again.
  const starting = useMemo(() => resolveLayout(layout, libraryVariables), [layout, libraryVariables]);
  const preview = (values: Values) => stringify([{ default: name, ...(Object.keys(values).length > 0 && { template_variables: values }) }], { lineWidth: 0 }).trimEnd();
  const unlessStarting = (key: string, value: string) => (value === String(starting[key] ?? "") ? undefined : value);

  return (
    <>
      <div>
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {entry?.docs_url && (
          <a className="text-[13px] text-muted underline hover:text-text" href={entry.docs_url} target="_blank" rel="noreferrer">
            Kometa wiki
          </a>
        )}
      </div>
      <VariablesEditor
        key={JSON.stringify(variables)}
        label={`Variables for ${title}`}
        root={root}
        schema={root ? defaultVariablesSchema(root, "overlay", name) : undefined}
        saved={variables}
        onSave={(values) => save.mutate(values)}
        saving={save.isPending}
        error={save.error}
        saveLabel="Apply on next run"
        toggles={toggles}
        togglesLegend="Show when"
        preview={preview}
        onValues={onValues}
        onUnsaved={onUnsaved}
        featured={controls(name, layout?.moved_by, libraryType)}
        designed={PLACEMENT}
        noToggles={
          <p className="text-[13px] text-muted">
            {name === "resolution"
              ? "Show when: Kometa picks the badge from each title's own resolution and edition. Turn either kind off below."
              : "Show when: Kometa decides this from each title's own details, and this default has no choices to make there. For your own rules, use an overlay file."}
          </p>
        }
        top={(values, set) => {
          const vars = resolveLayout(layout, { ...libraryVariables, ...values });
          const horizontalKey = position ? "horizontal_position" : "horizontal_align";
          const verticalKey = position ? "vertical_position" : "vertical_align";
          const side = (value: unknown, fallback: string) => String(value ?? fallback).split(/[_0-9]/)[0];
          // Without its own offsets, what the alignment gives is what shows.
          const offsets = resolveLayout(layout, { ...libraryVariables, ...values, horizontal_offset: undefined, vertical_offset: undefined });
          return (
            <>
              <AnchorGrid
                horizontal={side(vars[horizontalKey], "left")}
                vertical={side(vars[verticalKey], "top")}
                onChange={(horizontal, vertical) => {
                  set(horizontalKey, unlessStarting(horizontalKey, horizontal));
                  set(verticalKey, unlessStarting(verticalKey, vertical));
                }}
              />
              {!position && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Offset X">
                    <OffsetInput label="Offset X" value={values.horizontal_offset} onChange={(next) => set("horizontal_offset", next)} placeholder={String(offsets.horizontal_offset ?? 0)} />
                  </Field>
                  <Field label="Offset Y">
                    <OffsetInput label="Offset Y" value={values.vertical_offset} onChange={(next) => set("vertical_offset", next)} placeholder={String(offsets.vertical_offset ?? 0)} />
                  </Field>
                </div>
              )}
            </>
          );
        }}
      />
      {save.isSuccess && (
        <p role="status" className="text-sm text-ok">
          Saved. Kometa draws it on the next overlay run.{" "}
          <Link className="underline" to="/overlays">
            Apply it now
          </Link>
        </p>
      )}
      <ConfirmButton label="Turn off" confirm={`Turn off ${title}`} warning="Kometa stops drawing it. Posters update on the next overlay run." onConfirm={onTurnOff} busy={turningOff} />
    </>
  );
}

function Designer({ config, libraryType, status }: { config: ConfigLibrary; libraryType: string | null; status: OverlayLibrary | undefined }) {
  const library = config.name;
  const catalogue = useQuery({ queryKey: ["config", "defaults"], queryFn: api.config.defaults, staleTime: Infinity });
  const schema = useQuery({ queryKey: ["schema", "config"], queryFn: () => loadSchema("config"), staleTime: Infinity });
  const samples = useSamples(library);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [live, setLive] = useState<Values | null>(null); // what the panel holds, saved or not
  const [unsaved, setUnsaved] = useState(false);
  const { leave, dialog } = useLeaveEditor(unsaved);
  const add = useSave((name: string) => api.config.useDefault(library, "overlay", name, {}));
  const drop = useSave((name: string) => api.config.dropDefault(library, "overlay", name));
  const order = useSave((names: string[]) => api.config.setOverlayOrder(library, names));

  const defaults = config.overlay_files.filter((reference) => reference.kind === "default");
  const entryOf = (name: string) => catalogue.data?.overlays.find((entry) => entry.name === name);
  const layers: Layer[] = [...new Set(defaults.map((reference) => reference.value))].map((name) => {
    const reference = defaults.find((candidate) => candidate.value === name)!; // the first, if listed twice: that's the one saves change
    return { name, title: titleOf(reference, entryOf(name)), entry: entryOf(name), reference, variables: reference.template_variables as Values };
  });
  const ownFiles = config.overlay_files.filter((reference) => reference.kind !== "default");
  const selected = layers.find((layer) => layer.name === selectedName) ?? layers[0] ?? null;
  const libraryVariables = config.template_variables as Values;
  const addable = (catalogue.data?.overlays ?? []).filter((entry) => !layers.some((layer) => layer.name === entry.name) && (!libraryType || !entry.types.length || entry.types.includes(libraryType)));

  const variablesOf = (layer: Layer) => ({ ...libraryVariables, ...(layer.name === selected?.name && live ? live : layer.variables) });
  const boxes = (item: PlexItem | null): Box[] => layers.flatMap((layer) => layerBoxes(layer.name, layerText(layer.name, layer.title, item), layer.entry?.layout, variablesOf(layer)));
  const select = (name: string) => {
    if (name !== selected?.name) leave(() => setSelectedName(name));
  };
  const move = (index: number, by: number) => {
    const names = layers.map((layer) => layer.name);
    [names[index], names[index + by]] = [names[index + by], names[index]];
    order.mutate(names);
  };

  return (
    <div className="grid items-start gap-6 xl:grid-cols-[17rem_minmax(0,1fr)_21rem]">
      <LeaveGuard dirty={unsaved} query />
      {dialog}
      <section aria-labelledby="layers" className="flex flex-col gap-2">
        <h2 id="layers" className="text-[15px] font-semibold">
          Layers · {library}
        </h2>
        {layers.length === 0 && <p className="text-sm text-muted">No overlay defaults yet. Add a layer to start.</p>}
        <ol className="flex flex-col gap-1.5">
          {layers.map((layer, index) => (
            <li key={layer.name} className="flex items-center gap-1">
              <button
                type="button"
                aria-pressed={layer.name === selected?.name}
                onClick={() => select(layer.name)}
                className={`flex min-h-11 min-w-0 flex-1 items-center justify-between gap-2 rounded-control border px-2.5 text-left text-sm ${layer.name === selected?.name ? "border-accent bg-surface-2" : "border-transparent text-muted hover:bg-surface-2"}`}
              >
                <span className="min-w-0 truncate" title={layer.title}>
                  {layer.title}
                </span>
                <span className="shrink-0 text-xs text-muted">{whereItIs(layer.entry?.layout, variablesOf(layer))}</span>
              </button>
              <button type="button" aria-label={`Draw ${layer.title} earlier`} disabled={index === 0 || order.isPending} onClick={() => move(index, -1)} className="size-9 rounded-control text-muted hover:bg-surface-2 disabled:opacity-30">
                ↑
              </button>
              <button type="button" aria-label={`Draw ${layer.title} later`} disabled={index === layers.length - 1 || order.isPending} onClick={() => move(index, 1)} className="size-9 rounded-control text-muted hover:bg-surface-2 disabled:opacity-30">
                ↓
              </button>
            </li>
          ))}
        </ol>
        <label className="mt-2 flex flex-col gap-1.5 text-sm">
          <span className="text-muted">Add a layer</span>
          <select
            className={inputClass}
            value=""
            disabled={add.isPending || addable.length === 0}
            onChange={(event) => {
              const name = event.target.value;
              if (!name) return;
              add.mutate(name);
              if (!unsaved) setSelectedName(name); // adding doesn't touch the panel; picking it would
            }}
          >
            <option value="">{add.isPending ? "Kometa is checking…" : `Choose from ${addable.length}…`}</option>
            {addable.map((entry) => (
              <option key={entry.name} value={entry.name}>
                {shortTitle(entry.title ?? entry.name)}
              </option>
            ))}
          </select>
        </label>
        <SaveError error={add.error ?? drop.error ?? order.error} />
        <p className="pt-2 text-xs text-muted">Kometa draws layers in this order, so a lower one lands on top where they overlap. Moving a layer saves straight away, and Kometa checks it.</p>
        {ownFiles.length > 0 && (
          <p className="pt-2 text-xs text-muted">
            Also draws {ownFiles.length} of your own overlay file{ownFiles.length === 1 ? "" : "s"}, not shown here.{" "}
            <Link className="underline" to={`/libraries/${encodeURIComponent(library)}?tab=overlays`}>
              Edit them in {library}
            </Link>
          </p>
        )}
      </section>

      <section aria-label="Preview" className="flex min-w-0 flex-col items-center gap-4">
        <SamplePicker samples={samples} />
        {samples.error && (
          <p role="alert" className="text-sm text-warn">
            Can't get posters from Plex: {samples.error.message}. Placement still shows.
          </p>
        )}
        <OverlayPoster
          item={samples.sample}
          boxes={boxes(samples.sample)}
          selected={selected?.name}
          onPick={(box) => select(box.key.replace(/-\d+$/, ""))}
          label={`Overlays on ${samples.sample?.title ?? "a poster"}`}
          className="w-full max-w-[340px] shadow-[0_20px_50px_rgba(0,0,0,0.45)]"
        />
        <p className="text-xs text-muted">Placement only: Kometa draws the real overlays, with their own images.</p>
        {samples.found.length > 1 && (
          <div className="flex flex-wrap items-end justify-center gap-2.5" aria-label="The same layers on other titles">
            {samples.found
              .filter((item) => item.rating_key !== samples.sample?.rating_key)
              .slice(0, 4)
              .map((item) => (
                <OverlayPoster key={item.rating_key} item={item} boxes={boxes(item)} label={`Overlays on ${item.title}`} className="w-16 rounded-md" fontSize="11cqw" />
              ))}
          </div>
        )}
      </section>

      <aside aria-label="Layer settings" className="flex min-w-0 flex-col gap-[18px] rounded-card border border-border bg-surface p-5">
        {status?.off && (
          <p className="text-sm text-warn">
            Overlays are turned off for {library}, so nothing is drawn until they're back on.{" "}
            <Link className="underline" to="/overlays">
              Overlays
            </Link>
          </p>
        )}
        {status?.maintainerr?.on_top && <p className="text-sm text-muted">Maintainerr's overlays still go on top of these.</p>}
        {selected ? (
          <Properties
            key={selected.name}
            library={library}
            layer={selected}
            libraryVariables={libraryVariables}
            root={schema.data?.root ?? null}
            libraryType={libraryType}
            onValues={setLive}
            onUnsaved={setUnsaved}
            onTurnOff={() => leave(() => drop.mutate(selected.name))}
            turningOff={drop.isPending}
          />
        ) : (
          <p className="text-sm text-muted">Pick a layer to move and style it.</p>
        )}
      </aside>
    </div>
  );
}

export function OverlayDesigner() {
  const { library, libraries: names, setLibrary, libraryType, overview } = useLibrary();
  const overlays = useQuery({ queryKey: ["overlays"], queryFn: api.overlays.list });
  const config = useQuery({ queryKey: ["config", "library", library], queryFn: () => api.config.library(library!), enabled: library !== null });

  if (overview.isPending) return <p className="text-muted">Loading…</p>;
  if (overview.isError) {
    return (
      <p role="alert" className="text-err">
        {overview.error instanceof ApiError ? overview.error.message : "Can't read the config"}
      </p>
    );
  }
  if (library === null) {
    return (
      <p className="text-muted">
        Overlays are set per library, and config.yml has none yet.{" "}
        <Link className="underline hover:text-text" to="/libraries">
          Add one from Libraries
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="flex max-w-[1400px] flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[13px] text-muted">Kometa's overlays, placed on your posters</p>
          <h2 className="mt-1 text-[32px] leading-tight font-semibold">Overlay designer</h2>
        </div>
        <label className="flex items-center gap-2 text-[13px] text-muted">
          Library
          <select
            className="min-h-11 rounded-control border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent focus:outline-none"
            value={library}
            onChange={(event) => setLibrary(event.target.value)}
          >
            {names.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
      </header>
      {config.isPending ? (
        <p className="text-muted">Loading…</p>
      ) : config.isError ? (
        <p role="alert" className="text-err">
          {config.error.message}
        </p>
      ) : (
        <Designer key={library} config={config.data} libraryType={libraryType === "movie" || libraryType === "show" ? libraryType : null} status={overlays.data?.libraries.find((entry) => entry.library === library)} />
      )}
    </div>
  );
}
