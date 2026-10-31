// The "what to run" fields shared by Run now (Queue) and schedules (Tasks).

import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { useAdvanced } from "../advanced";
import { api, type KometaInfo, type RunMode, type RunRequest } from "../api";
import { modes, splitNames } from "../runs";
import { Field, inputClass } from "./ui";

type Options = Pick<RunRequest, "ignore_schedules" | "no_missing" | "tests" | "timings" | "low_priority">;

// Collections and files stay as typed text until the form is sent.
export type RunDraft = { mode: RunMode; libraries: string[]; collections: string; files: string; options: Options };

const defaultOptions: Options = { ignore_schedules: false, no_missing: false, tests: false, timings: false, low_priority: true };

export const emptyDraft: RunDraft = { mode: "all", libraries: [], collections: "", files: "", options: defaultOptions };

export function draftFromRequest(request: RunRequest): RunDraft {
  const { mode, libraries, collections, files, ...options } = request;
  return { mode, libraries, collections: collections.join(", "), files: files.join(", "), options };
}

/** ``withAdvanced`` false drops whatever only Show Advanced reveals. */
export function requestFromDraft(draft: RunDraft, withAdvanced: boolean): RunRequest {
  return {
    mode: draft.mode,
    libraries: draft.libraries,
    collections: withAdvanced ? splitNames(draft.collections) : [],
    files: withAdvanced ? splitNames(draft.files) : [],
    ...(withAdvanced ? draft.options : defaultOptions),
  };
}

function usesAdvanced(draft: RunDraft): boolean {
  return (
    splitNames(draft.collections).length > 0 ||
    splitNames(draft.files).length > 0 ||
    (Object.keys(defaultOptions) as (keyof Options)[]).some((key) => draft.options[key] !== defaultOptions[key])
  );
}

export const supports = (kometa: KometaInfo | undefined, flag: string | null) => !flag || !kometa?.flags || kometa.flags.includes(flag);

const choiceClass = "flex min-h-11 items-center rounded-control border px-3 text-sm";

function Checkbox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`flex min-h-11 items-center gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="size-4 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Pick from config.yml's libraries. Typing them is only for when config.yml can't be read. */
function Libraries({ value, onChange }: { value: string[]; onChange: (libraries: string[]) => void }) {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const [typed, setTyped] = useState(value.join(", "));
  const inConfig = config.data?.libraries.map((library) => library.name) ?? [];

  if (!config.isPending && inConfig.length === 0) {
    return (
      <Field label="Libraries" hint="Names as in config.yml, separated by commas. Leave empty for every library.">
        <input
          className={inputClass}
          value={typed}
          onChange={(e) => {
            setTyped(e.target.value);
            onChange(splitNames(e.target.value));
          }}
          placeholder="All libraries"
        />
      </Field>
    );
  }
  // One chosen earlier and since taken out of config.yml stays, so a schedule's request isn't changed by opening it.
  const gone = value.filter((name) => !inConfig.includes(name));
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm text-muted">Libraries</legend>
      {config.isPending ? (
        <p className="min-h-11 content-center text-sm text-muted">Loading…</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {[...inConfig, ...gone].map((name) => {
            const chosen = value.includes(name);
            return (
              <label key={name} className={[choiceClass, chosen ? "border-accent bg-surface-2 text-accent" : "border-border-strong", "cursor-pointer"].join(" ")}>
                <input type="checkbox" className="sr-only" checked={chosen} onChange={() => onChange(chosen ? value.filter((n) => n !== name) : [...value, name])} />
                {name}
                {gone.includes(name) && <span className="ml-1 text-xs text-warn">not in config.yml</span>}
              </label>
            );
          })}
        </div>
      )}
      <p className="mt-1.5 text-xs text-muted">{value.length === 0 ? "None picked: every library runs." : "Only the libraries picked here run."}</p>
    </fieldset>
  );
}

export function RunRequestFields({
  value,
  onChange,
  kometa,
  keepsHiddenOptions = false,
}: {
  value: RunDraft;
  onChange: (draft: RunDraft) => void;
  kometa: KometaInfo | undefined;
  keepsHiddenOptions?: boolean; // say so when Show Advanced is off but advanced options are in use
}) {
  const { showAdvanced } = useAdvanced();
  const modeName = useId();
  const set = (patch: Partial<RunDraft>) => onChange({ ...value, ...patch });
  const option = (key: keyof Options, label: string, flag: string) => (
    <Checkbox
      label={label}
      checked={value.options[key]}
      disabled={!supports(kometa, flag)}
      onChange={(checked) => set({ options: { ...value.options, [key]: checked } })}
    />
  );

  return (
    <>
      <fieldset>
        <legend className="mb-1.5 text-sm text-muted">What to run</legend>
        <div className="flex flex-wrap gap-2">
          {modes.map((m) => {
            const available = supports(kometa, m.flag);
            return (
              <label
                key={m.value}
                className={[
                  choiceClass,
                  value.mode === m.value ? "border-accent bg-surface-2 text-accent" : "border-border-strong",
                  available ? "cursor-pointer" : "opacity-50",
                ].join(" ")}
              >
                <input
                  type="radio"
                  name={modeName}
                  className="sr-only"
                  value={m.value}
                  checked={value.mode === m.value}
                  disabled={!available}
                  onChange={() => set({ mode: m.value })}
                />
                {m.label}
              </label>
            );
          })}
        </div>
        {value.mode === "all" && (
          <p className="mt-1.5 text-xs text-muted">Everything set up in config.yml: steps a library has nothing configured for are skipped.</p>
        )}
      </fieldset>
      <Libraries value={value.libraries} onChange={(libraries) => set({ libraries })} />
      {showAdvanced ? (
        <>
          <Field label="Collections" hint="Only these collections, separated by commas.">
            <input className={inputClass} value={value.collections} onChange={(e) => set({ collections: e.target.value })} placeholder="All collections" />
          </Field>
          <Field label="Files" hint="Only these collection, overlay or playlist files, separated by commas.">
            <input className={inputClass} value={value.files} onChange={(e) => set({ files: e.target.value })} placeholder="All files" />
          </Field>
          <div className="grid gap-x-6 sm:grid-cols-2">
            {option("low_priority", "Low priority (gentler on this computer)", "--low-priority")}
            {option("ignore_schedules", "Ignore schedules", "--ignore-schedules")}
            {option("no_missing", "Skip missing-item reports", "--no-missing")}
            {option("tests", "Only collections marked test: true", "--tests")}
            {option("timings", "Record timings", "--timings")}
          </div>
        </>
      ) : (
        keepsHiddenOptions &&
        usesAdvanced(value) && <p className="text-sm text-muted">This also uses advanced options. Turn on Show Advanced to see them.</p>
      )}
    </>
  );
}
