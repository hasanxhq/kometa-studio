// Shared "current library" for Collections, Ready-made and the overlay designer: URL `?library=`, then localStorage, then the first config library.

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";

import { api } from "./api";
import { useLibraryType } from "./libraries";

const STORAGE_KEY = "studio:library";

function readStored(names: string[]): string | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return names.includes(raw) ? raw : null;
  } catch {
    return null;
  }
}

function writeStored(name: string) {
  try {
    localStorage.setItem(STORAGE_KEY, name);
  } catch {
    // private window, quota, or storage disabled
  }
}

export function useLibrary() {
  const [searchParams, setSearchParams] = useSearchParams();
  const overview = useQuery({ queryKey: ["config"], queryFn: api.config.overview, retry: false });
  const names = useMemo(() => overview.data?.libraries.map((entry) => entry.name) ?? [], [overview.data?.libraries]);
  const askedParam = searchParams.get("library");

  const library = useMemo(() => {
    if (!overview.isSuccess || names.length === 0) return null;
    if (askedParam && names.includes(askedParam)) return askedParam;
    const stored = readStored(names);
    if (stored) return stored;
    return names[0] ?? null;
  }, [overview.isSuccess, names, askedParam]);

  const setLibrary = useCallback(
    (name: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("library", name);
          return next;
        },
        { replace: true },
      );
      writeStored(name);
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!overview.isSuccess || names.length === 0 || !askedParam || !names.includes(askedParam)) return;
    writeStored(askedParam);
  }, [overview.isSuccess, names, askedParam]);

  const libraryType = useLibraryType(library);

  return { library, libraries: names, setLibrary, libraryType, overview };
}
