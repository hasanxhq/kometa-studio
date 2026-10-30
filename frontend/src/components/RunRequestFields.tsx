// The "what to run" fields shared by Run now (Queue) and schedules (Tasks).

import { useId } from "react";

import { useAdvanced } from "../advanced";
import type { KometaInfo, RunMode, RunRequest } from "../api";
import { modes, splitNames } from "../runs";
import { Field, inputClass } from "./ui";

type Options = Pick<RunRequest, "ignore_schedules" | "no_missing" | "tests" | "timings" | "low_priority">;

// Name lists stay as typed text until the form is sent.
export type RunDraft = { mode: RunMode; libraries: string; collections: string; files: string; options: Options };

const defaultOptions: Options = { ignore_schedules: false, no_missing: false, tests: false, timings: false, low_priority: true };

export const emptyDraft: RunDraft = { mode: "all", libraries: "", collections: "", files: "", options: defaultOptions };

export function draftFromRequest(request: RunRequest): RunDraft {
  const { mode, libraries, collections, files, ...options } = request;
  return { mode, libraries: libraries.join(", "), collections: collections.join(", "), files: files.join(", "), options };
}

/** ``withAdvanced`` false drops whatever only Show Advanced reveals. */
export function requestFromDraft(draft: RunDraft, withAdvanced: boolean): RunRequest {
  return {
    mode: draft.mode,
    libraries: splitNames(draft.libraries),
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

function Checkbox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`flex min-h-11 items-center gap-2 text-sm ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="size-4 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
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
                  "flex min-h-11 items-center rounded-control border px-3 text-sm",
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
      </fieldset>
      <Field label="Libraries" hint="Names as in config.yml, separated by commas. Leave empty for every library.">
        <input className={inputClass} value={value.libraries} onChange={(e) => set({ libraries: e.target.value })} placeholder="All libraries" />
      </Field>
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
