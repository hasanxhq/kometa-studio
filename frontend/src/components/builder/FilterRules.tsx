// Match-all/any radios and rule rows shared by smart filters and Plex search sources.

import type { BuilderField } from "../../builderApi";
import { Button, inputClass } from "../ui";
import { emptyValue, RuleValueInput, type DraftValue } from "./RuleValueInput";

export type DraftRule = { field: string; modifier: string; value: DraftValue };
export type DraftFilters = { match: "all" | "any"; rules: DraftRule[] };

function fieldByKey(fields: BuilderField[], key: string): BuilderField | undefined {
  return fields.find((field) => field.key === key);
}

function groupFields(fields: BuilderField[]): { group: string; fields: BuilderField[] }[] {
  const order: string[] = [];
  const map = new Map<string, BuilderField[]>();
  for (const field of fields) {
    if (!map.has(field.group)) {
      order.push(field.group);
      map.set(field.group, []);
    }
    map.get(field.group)!.push(field);
  }
  return order.map((group) => ({ group, fields: map.get(group)! }));
}

export function blankRule(fields: BuilderField[]): DraftRule {
  const field = fields[0];
  return field
    ? { field: field.key, modifier: field.modifiers[0]?.key ?? "", value: emptyValue(field) }
    : { field: "", modifier: "", value: "" };
}

function RuleRow({
  library,
  fields,
  rule,
  onChange,
  onRemove,
  canRemove,
}: {
  library: string;
  fields: BuilderField[];
  rule: DraftRule;
  onChange: (rule: DraftRule) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const field = fieldByKey(fields, rule.field) ?? fields[0];
  const groups = groupFields(fields);
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border bg-surface-2 p-3" role="group" aria-label="Filter rule">
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        {/* div (not label): a wrapping label would fold the selected option into the accessible name */}
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Field</span>
          <select
            className={inputClass}
            value={field?.key ?? ""}
            onChange={(event) => {
              const next = fieldByKey(fields, event.target.value);
              if (!next) return;
              onChange({ field: next.key, modifier: next.modifiers[0]?.key ?? "", value: emptyValue(next) });
            }}
            aria-label="Field"
          >
            {groups.map((group) => (
              <optgroup key={group.group} label={group.group}>
                {group.fields.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-muted">Modifier</span>
          <select
            className={inputClass}
            value={rule.modifier}
            onChange={(event) => onChange({ ...rule, modifier: event.target.value })}
            aria-label="Modifier"
          >
            {(field?.modifiers ?? []).map((modifier) => (
              <option key={modifier.key || "is"} value={modifier.key}>
                {modifier.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <Button onClick={onRemove} disabled={!canRemove} aria-label="Remove rule">
            Remove
          </Button>
        </div>
      </div>
      {field && <RuleValueInput library={library} field={field} value={rule.value} onChange={(value) => onChange({ ...rule, value })} />}
    </div>
  );
}

export function FilterRules({
  library,
  fields,
  value,
  onChange,
  matchName = "match",
}: {
  library: string;
  fields: BuilderField[];
  value: DraftFilters;
  onChange: (next: DraftFilters) => void;
  /** Radio name; unique when several search sources sit on one page. */
  matchName?: string;
}) {
  return (
    <div className="flex flex-col gap-3">
      <fieldset className="flex flex-wrap gap-4">
        <legend className="sr-only">Match rules</legend>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="radio"
            name={matchName}
            className="size-4 accent-accent"
            checked={value.match === "all"}
            onChange={() => onChange({ ...value, match: "all" })}
          />
          Match all of these rules
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="radio"
            name={matchName}
            className="size-4 accent-accent"
            checked={value.match === "any"}
            onChange={() => onChange({ ...value, match: "any" })}
          />
          Match any of these rules
        </label>
      </fieldset>
      <div className="flex flex-col gap-3">
        {value.rules.map((rule, index) => (
          <RuleRow
            key={index}
            library={library}
            fields={fields}
            rule={rule}
            onChange={(next) => onChange({ ...value, rules: value.rules.map((entry, i) => (i === index ? next : entry)) })}
            onRemove={() => onChange({ ...value, rules: value.rules.filter((_, i) => i !== index) })}
            canRemove={value.rules.length > 1}
          />
        ))}
      </div>
      <Button onClick={() => onChange({ ...value, rules: [...value.rules, blankRule(fields)] })} disabled={fields.length === 0}>
        Add rule
      </Button>
    </div>
  );
}
