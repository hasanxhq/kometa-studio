// Local picks for Ready-made: add/remove refs per library, kept in sessionStorage so a refresh keeps them.

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { ReadyMadeEntry, ReadyMadeRef } from "./api";

export type LibraryPicks = { add: ReadyMadeRef[]; remove: ReadyMadeRef[] };

type Store = Record<string, LibraryPicks>;

const STORAGE_KEY = "studio:ready-made-picks";

const empty: LibraryPicks = { add: [], remove: [] };

function sameRef(a: ReadyMadeRef, b: ReadyMadeRef): boolean {
  return a.category === b.category && a.block === b.block && a.key === b.key;
}

function readStore(): Store {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Store;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeStore(store: Store) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // page still works without persistence
  }
}

export function refOf(category: string, entry: Pick<ReadyMadeEntry, "block" | "key">): ReadyMadeRef {
  return { category, block: entry.block, key: entry.key };
}

/** Whether the tile shows as selected given server desired and local add/remove. */
export function isSelected(entry: Pick<ReadyMadeEntry, "desired" | "block" | "key">, category: string, picks: LibraryPicks): boolean {
  const ref = refOf(category, entry);
  const locallyPicked = picks.add.some((r) => sameRef(r, ref));
  const locallyUnpicked = picks.remove.some((r) => sameRef(r, ref));
  return (entry.desired === true && !locallyUnpicked) || locallyPicked;
}

type PicksApi = {
  picks: (library: string) => LibraryPicks;
  setPicked: (library: string, category: string, entry: Pick<ReadyMadeEntry, "desired" | "block" | "key">, picked: boolean) => void;
  selectAll: (library: string, category: string, entries: ReadyMadeEntry[]) => void;
  clearCategory: (library: string, category: string, entries: ReadyMadeEntry[]) => void;
  clearLibrary: (library: string) => void;
  changeCount: (library: string) => number;
};

const PicksContext = createContext<PicksApi | null>(null);

export function ReadyMadePicksProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<Store>(() => readStore());

  const api = useMemo<PicksApi>(() => {
    const update = (library: string, next: LibraryPicks) => {
      setStore((current) => {
        const cleaned = next.add.length === 0 && next.remove.length === 0 ? (() => {
          const { [library]: _, ...rest } = current;
          return rest;
        })() : { ...current, [library]: next };
        writeStore(cleaned);
        return cleaned;
      });
    };

    const picks = (library: string) => store[library] ?? empty;

    return {
      picks,
      setPicked: (library, category, entry, picked) => {
        const current = picks(library);
        const ref = refOf(category, entry);
        const inAdd = current.add.some((r) => sameRef(r, ref));
        const inRemove = current.remove.some((r) => sameRef(r, ref));
        if (picked) {
          // Re-picking something marked for removal cancels the removal.
          if (inRemove) {
            update(library, { ...current, remove: current.remove.filter((r) => !sameRef(r, ref)) });
            return;
          }
          // Already desired and not removed: no-op.
          if (entry.desired === true) return;
          if (inAdd) return;
          update(library, { ...current, add: [...current.add, ref] });
          return;
        }
        // Unpicking.
        if (inAdd) {
          update(library, { ...current, add: current.add.filter((r) => !sameRef(r, ref)) });
          return;
        }
        if (entry.desired === true && !inRemove) {
          update(library, { ...current, remove: [...current.remove, ref] });
        }
      },
      selectAll: (library, category, entries) => {
        let next = picks(library);
        for (const entry of entries) {
          if (isSelected(entry, category, next)) continue;
          const ref = refOf(category, entry);
          if (next.remove.some((r) => sameRef(r, ref))) {
            next = { ...next, remove: next.remove.filter((r) => !sameRef(r, ref)) };
          } else if (entry.desired !== true) {
            next = { ...next, add: [...next.add, ref] };
          }
        }
        update(library, next);
      },
      clearCategory: (library, category, entries) => {
        let next = picks(library);
        for (const entry of entries) {
          if (!isSelected(entry, category, next)) continue;
          const ref = refOf(category, entry);
          if (next.add.some((r) => sameRef(r, ref))) {
            next = { ...next, add: next.add.filter((r) => !sameRef(r, ref)) };
          } else if (entry.desired === true && !next.remove.some((r) => sameRef(r, ref))) {
            next = { ...next, remove: [...next.remove, ref] };
          }
        }
        update(library, next);
      },
      clearLibrary: (library) => update(library, empty),
      changeCount: (library) => {
        const p = picks(library);
        return p.add.length + p.remove.length;
      },
    };
  }, [store]);

  return <PicksContext.Provider value={api}>{children}</PicksContext.Provider>;
}

export function useReadyMadePicks(): PicksApi {
  const value = useContext(PicksContext);
  if (!value) throw new Error("useReadyMadePicks needs ReadyMadePicksProvider");
  return value;
}
