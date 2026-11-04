// Pick a list source for a collection: paste a link, or fill in a kind from GET /builder/sources.

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "../../api";
import { builderApi, type SourceKind, type SourceSearchResult } from "../../builderApi";
import { Button, Field, inputClass } from "../ui";

export type ListSourceValue = { builder: string; value: string; label: string | null };

const GROUP_ORDER: SourceKind["group"][] = ["TMDb", "IMDb", "Letterboxd", "MDBList"];

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

function groupSources(sources: SourceKind[]): { group: SourceKind["group"]; kinds: SourceKind[] }[] {
  const map = new Map<SourceKind["group"], SourceKind[]>();
  for (const kind of sources) {
    const list = map.get(kind.group) ?? [];
    list.push(kind);
    map.set(kind.group, list);
  }
  return GROUP_ORDER.filter((group) => map.has(group)).map((group) => ({ group, kinds: map.get(group)! }));
}

function PasteLink({
  library,
  onPicked,
}: {
  library: string;
  onPicked: (next: ListSourceValue) => void;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const parse = useMutation({
    mutationFn: () => builderApi.sourceFromLink({ library, url: url.trim() }),
    onSuccess: (result) => {
      setError(null);
      onPicked({ builder: result.builder, value: result.value, label: result.label });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Couldn't read that link");
    },
  });

  const submit = () => {
    if (!url.trim() || parse.isPending) return;
    parse.mutate();
  };

  return (
    <div className="flex flex-col gap-2">
      <Field label="Paste a link">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className={inputClass}
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              if (error) setError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Paste a link from TMDb, IMDb, Letterboxd or MDBList"
            aria-label="Paste a link"
            aria-invalid={error ? true : undefined}
          />
          <Button variant="primary" onClick={submit} disabled={!url.trim() || parse.isPending}>
            {parse.isPending ? "Checking…" : "Use link"}
          </Button>
        </div>
      </Field>
      {error && (
        <p role="alert" className="text-sm text-err">
          {error}
        </p>
      )}
    </div>
  );
}

function SearchKind({
  library,
  kind,
  selected,
  onPicked,
}: {
  library: string;
  kind: SourceKind;
  selected: ListSourceValue | null;
  onPicked: (next: ListSourceValue) => void;
}) {
  const [q, setQ] = useState("");
  const debounced = useDebounced(q.trim(), 300);
  const search = useQuery({
    queryKey: ["builder", "sources", "search", library, kind.builder, debounced],
    queryFn: () => builderApi.searchSource(library, kind.builder, debounced),
    enabled: debounced.length >= 2,
  });

  const pick = (result: SourceSearchResult) => {
    onPicked({ builder: kind.builder, value: result.value, label: result.title });
  };

  const isSelected = selected?.builder === kind.builder;

  return (
    <div className="flex flex-col gap-2">
      <Field label="Search">
        <input
          className={inputClass}
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder={kind.placeholder ?? "Search…"}
          aria-label={`Search ${kind.label}`}
          disabled={!kind.available}
        />
      </Field>
      {isSelected && selected?.label && (
        <p className="text-sm text-muted">
          Selected: <span className="text-text">{selected.label}</span>
        </p>
      )}
      {debounced.length >= 2 && (
        <div className="flex flex-col gap-2">
          {search.isPending && <p className="text-sm text-muted">Searching…</p>}
          {search.isError && (
            <p role="alert" className="text-sm text-err">
              {search.error.message}
            </p>
          )}
          {search.data && search.data.results.length === 0 && <p className="text-sm text-muted">No results.</p>}
          {search.data && search.data.results.length > 0 && (
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(5.5rem,1fr))] gap-3" aria-label={`${kind.label} results`}>
              {search.data.results.map((result) => (
                <li key={result.value}>
                  <button
                    type="button"
                    className={`flex w-full flex-col gap-1 rounded-control text-left transition hover:bg-surface-2 ${
                      isSelected && selected?.value === result.value ? "ring-2 ring-accent" : ""
                    }`}
                    onClick={() => pick(result)}
                  >
                    <div className="aspect-[2/3] overflow-hidden rounded-control border border-border bg-surface-2">
                      {result.poster ? (
                        <img src={result.poster} alt="" className="size-full object-cover" loading="lazy" />
                      ) : (
                        <div className="flex size-full items-center justify-center p-2 text-center text-xs text-muted">{result.title}</div>
                      )}
                    </div>
                    <span className="line-clamp-2 text-xs font-medium">{result.title}</span>
                    {result.year != null && <span className="text-xs text-muted">{result.year}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function LinkKind({
  kind,
  selected,
  onPicked,
}: {
  kind: SourceKind;
  selected: ListSourceValue | null;
  onPicked: (next: ListSourceValue) => void;
}) {
  const current = selected?.builder === kind.builder ? selected.value : "";
  const [text, setText] = useState(current);
  useEffect(() => {
    setText(current);
  }, [current]);

  const commit = (raw: string) => {
    const value = raw.trim();
    if (!value) return;
    onPicked({ builder: kind.builder, value, label: value });
  };

  return (
    <Field label="URL or id">
      <input
        className={inputClass}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => commit(text)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit(text);
          }
        }}
        placeholder={kind.placeholder ?? undefined}
        aria-label={kind.label}
        disabled={!kind.available}
      />
    </Field>
  );
}

function ChoiceKind({
  kind,
  selected,
  onPicked,
}: {
  kind: SourceKind;
  selected: ListSourceValue | null;
  onPicked: (next: ListSourceValue) => void;
}) {
  const value = selected?.builder === kind.builder ? selected.value : "";
  return (
    <Field label="Choice">
      <select
        className={inputClass}
        value={value}
        onChange={(event) => {
          const choice = kind.choices?.find((entry) => entry.value === event.target.value);
          if (!choice) return;
          onPicked({ builder: kind.builder, value: choice.value, label: choice.label });
        }}
        aria-label={kind.label}
        disabled={!kind.available}
      >
        <option value="">Choose…</option>
        {(kind.choices ?? []).map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

function CountKind({
  kind,
  selected,
  onPicked,
}: {
  kind: SourceKind;
  selected: ListSourceValue | null;
  onPicked: (next: ListSourceValue) => void;
}) {
  const current = selected?.builder === kind.builder ? selected.value : "20";
  const [text, setText] = useState(current);

  useEffect(() => {
    setText(current);
  }, [current]);

  const commit = (raw: string) => {
    const n = Number.parseInt(raw, 10);
    if (!Number.isFinite(n)) return;
    const clamped = Math.min(500, Math.max(1, n));
    onPicked({ builder: kind.builder, value: String(clamped), label: kind.label });
  };

  return (
    <Field label="How many titles">
      <input
        type="number"
        min={1}
        max={500}
        className={inputClass}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onFocus={() => {
          if (selected?.builder !== kind.builder) commit(text || "20");
        }}
        onBlur={() => commit(text)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit(text);
          }
        }}
        aria-label={`${kind.label} count`}
        disabled={!kind.available}
      />
    </Field>
  );
}

function KindInput({
  library,
  kind,
  selected,
  onPicked,
}: {
  library: string;
  kind: SourceKind;
  selected: ListSourceValue | null;
  onPicked: (next: ListSourceValue) => void;
}) {
  switch (kind.input) {
    case "search":
      return <SearchKind library={library} kind={kind} selected={selected} onPicked={onPicked} />;
    case "link":
      return <LinkKind kind={kind} selected={selected} onPicked={onPicked} />;
    case "choice":
      return <ChoiceKind kind={kind} selected={selected} onPicked={onPicked} />;
    case "count":
      return <CountKind kind={kind} selected={selected} onPicked={onPicked} />;
  }
}

export function ListSource({
  library,
  value,
  onChange,
}: {
  library: string;
  value: ListSourceValue | null;
  onChange: (next: ListSourceValue) => void;
}) {
  const sources = useQuery({
    queryKey: ["builder", "sources", library],
    queryFn: () => builderApi.sources(library),
  });

  const groups = sources.data ? groupSources(sources.data.sources) : [];

  return (
    <div className="flex flex-col gap-5">
      <PasteLink library={library} onPicked={onChange} />

      {value && (
        <p className="text-sm text-muted" aria-label="Chosen source">
          Using <span className="text-text">{value.label ?? value.builder}</span>
        </p>
      )}

      {sources.isPending && <p className="text-sm text-muted">Loading sources…</p>}
      {sources.isError && (
        <p role="alert" className="text-sm text-err">
          {sources.error.message}
        </p>
      )}

      {groups.map((group) => (
        <section key={group.group} className="flex flex-col gap-3" aria-labelledby={`source-group-${group.group}`}>
          <h4 id={`source-group-${group.group}`} className="text-[13px] font-semibold text-muted">
            {group.group}
          </h4>
          <ul className="flex flex-col gap-3">
            {group.kinds.map((kind) => {
              const active = value?.builder === kind.builder;
              return (
                <li
                  key={kind.builder}
                  className={`rounded-control border p-3 ${
                    active ? "border-accent bg-surface-2" : "border-border bg-surface-2/40"
                  } ${!kind.available ? "opacity-60" : ""}`}
                >
                  <div className="mb-2 flex flex-col gap-0.5">
                    <span className="text-sm font-medium">{kind.label}</span>
                    {!kind.available && kind.why && <span className="text-xs text-muted">{kind.why}</span>}
                  </div>
                  <fieldset disabled={!kind.available} className="min-w-0">
                    <legend className="sr-only">{kind.label}</legend>
                    <KindInput library={library} kind={kind} selected={value} onPicked={onChange} />
                  </fieldset>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
