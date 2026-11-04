// Value control for one filter rule, chosen by the field's kind.

import type { BuilderField } from "../../builderApi";
import { inputClass } from "../ui";
import { TagMultiSelect } from "./TagMultiSelect";

/** Form-side value: numbers may be blank while the user types. */
export type DraftValue = string | number | boolean | string[];

export function emptyValue(field: BuilderField): DraftValue {
  if (field.kind === "boolean") return false;
  if (field.kind === "tag" && field.listable) return [];
  return "";
}

export function RuleValueInput({
  library,
  field,
  value,
  onChange,
}: {
  library: string;
  field: BuilderField;
  value: DraftValue;
  onChange: (value: DraftValue) => void;
}) {
  if (field.kind === "tag" && field.listable) {
    const selected = Array.isArray(value) ? value.map(String) : [];
    return <TagMultiSelect library={library} field={field.key} value={selected} onChange={onChange} />;
  }

  if (field.kind === "boolean") {
    return (
      <select className={inputClass} value={value === true ? "yes" : "no"} onChange={(event) => onChange(event.target.value === "yes")} aria-label="Value">
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    );
  }

  if (field.kind === "number" || field.kind === "float" || field.kind === "year") {
    const shown = value === "" || value === null || value === undefined ? "" : String(value);
    return (
      <input
        type="number"
        className={inputClass}
        value={shown}
        step={field.kind === "float" ? "any" : 1}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") onChange("");
          else onChange(field.kind === "float" ? Number(raw) : Number.parseInt(raw, 10));
        }}
        aria-label="Value"
      />
    );
  }

  if (field.kind === "date") {
    return (
      <input
        type="text"
        className={inputClass}
        value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
        onChange={(event) => onChange(event.target.value)}
        placeholder="A date (2024-01-31) or a number of days (30)"
        aria-label="Value"
      />
    );
  }

  return (
    <input
      type="text"
      className={inputClass}
      value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Value"
    />
  );
}
