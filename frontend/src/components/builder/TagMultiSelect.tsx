// Checkbox list of listable tag values from /builder/values, with a search box.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { builderApi } from "../../builderApi";
import { inputClass } from "../ui";

export function TagMultiSelect({
  library,
  field,
  value,
  onChange,
}: {
  library: string;
  field: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const options = useQuery({
    queryKey: ["builder", "values", library, field],
    queryFn: () => builderApi.values(library, field),
  });
  const q = search.trim().toLowerCase();
  const values = (options.data?.values ?? []).filter((entry) => !q || entry.title.toLowerCase().includes(q) || entry.key.toLowerCase().includes(q));
  const selected = new Set(value);

  return (
    <div className="flex flex-col gap-2">
      <input
        type="search"
        className={inputClass}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search values"
        aria-label="Search values"
      />
      {options.isPending ? (
        <p className="text-xs text-muted">Loading values…</p>
      ) : options.isError ? (
        <p role="alert" className="text-xs text-err">
          {options.error.message}
        </p>
      ) : values.length === 0 ? (
        <p className="text-xs text-muted">No values match.</p>
      ) : (
        <ul className="max-h-48 overflow-y-auto rounded-control border border-border bg-surface-2 p-1" role="listbox" aria-multiselectable="true" aria-label="Tag values">
          {values.map((entry) => {
            const checked = selected.has(entry.key);
            return (
              <li key={entry.key}>
                <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-control px-2 text-sm hover:bg-surface">
                  <input
                    type="checkbox"
                    className="size-4 accent-accent"
                    checked={checked}
                    onChange={() => onChange(checked ? value.filter((key) => key !== entry.key) : [...value, entry.key])}
                  />
                  <span>{entry.title}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {value.length > 0 && (
        <p className="text-xs text-muted">
          {value.length} selected
          {value.length > 0 && (
            <>
              {" · "}
              <button type="button" className="underline hover:text-text" onClick={() => onChange([])}>
                Clear
              </button>
            </>
          )}
        </p>
      )}
    </div>
  );
}
