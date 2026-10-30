// Form building blocks for the designed editors: one control per Kometa setting, chosen from its schema.

import { useEffect, useId, useRef, useState } from "react";
import { parse, stringify } from "yaml";

import { controlFor, type JsonSchema } from "../../yaml/schema";
import { inputClass } from "../ui";

export function Problems({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null;
  return (
    <ul className="text-xs text-err">
      {messages.map((m) => (
        <li key={m}>{m}</li>
      ))}
    </ul>
  );
}

function toYaml(value: unknown): string {
  return value === undefined ? "" : stringify(value, { lineWidth: 0 }).replace(/\n$/, "");
}

/**
 * A small YAML box for a setting with several possible shapes. The value only changes when the text
 * parses; until then the box shows the YAML error and the form keeps the last good value.
 */
export function YamlBox({
  value,
  onChange,
  onValidity,
  label,
  rows = 3,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  onValidity?: (ok: boolean) => void;
  label: string;
  rows?: number;
}) {
  const [text, setText] = useState(() => toYaml(value));
  const [error, setError] = useState<string | null>(null);
  // Follow changes from outside (e.g. Undo), but not the echo of our own typing.
  const typed = useRef(text);
  typed.current = text;
  useEffect(() => {
    try {
      if (JSON.stringify(parse(typed.current) ?? null) !== JSON.stringify(value ?? null)) setText(toYaml(value));
    } catch {
      // mid-edit: leave the user's text alone
    }
  }, [value]);
  return (
    <div className="flex flex-col gap-1">
      <textarea
        aria-label={label}
        className={`${inputClass} min-h-0 py-2 leading-5`}
        rows={Math.max(rows, text.split("\n").length)}
        value={text}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            const parsed = next.trim() === "" ? undefined : parse(next);
            setError(null);
            onValidity?.(true);
            onChange(parsed);
          } catch (problem) {
            setError((problem as Error).message.split("\n")[0]);
            onValidity?.(false);
          }
        }}
      />
      {error && <p className="text-xs text-err">YAML: {error}</p>}
    </div>
  );
}

/** One setting, with the control its schema calls for. Empty means "not set" (the key is removed). */
export function SettingField({
  name,
  label,
  root,
  schema,
  value,
  onChange,
  onValidity,
  problems,
  hint,
}: {
  name: string;
  label?: string;
  root: JsonSchema | null;
  schema: JsonSchema | undefined;
  value: unknown;
  onChange: (value: unknown) => void;
  onValidity?: (ok: boolean) => void;
  problems?: string[];
  hint?: string;
}) {
  const id = useId();
  const control = root && schema ? controlFor(root, schema) : { kind: "yaml" as const };
  let input;
  if (control.kind === "boolean") {
    input = (
      <select id={id} className={inputClass} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "true")}>
        <option value="">Not set</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else if (control.kind === "enum") {
    input = (
      <select id={id} className={inputClass} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)}>
        <option value="">Not set</option>
        {control.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  } else if (control.kind === "integer" || control.kind === "number") {
    input = (
      <input
        id={id}
        type="number"
        className={inputClass}
        min={control.minimum}
        max={control.maximum}
        step={control.kind === "integer" ? 1 : "any"}
        value={typeof value === "number" ? value : ""}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  } else if (control.kind === "string") {
    input = <input id={id} className={inputClass} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)} />;
  } else {
    return (
      <div className="flex flex-col gap-1.5 text-sm">
        <span className="text-muted">
          {label ?? name} <span className="font-mono text-xs">({name}, YAML)</span>
        </span>
        <YamlBox label={label ?? name} value={value} onChange={onChange} onValidity={onValidity} />
        {hint && <span className="text-xs text-muted">{hint}</span>}
        <Problems messages={problems} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <label htmlFor={id} className="text-muted">
        {label ?? name} {label && <span className="font-mono text-xs">({name})</span>}
      </label>
      {input}
      {hint && <span className="text-xs text-muted">{hint}</span>}
      <Problems messages={problems} />
    </div>
  );
}
