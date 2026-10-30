// Matching Plex's libraries with the ones in Kometa's config.yml.

import type { LibraryCounts, PlexLibrarySummary } from "./api";

export type LibraryEntry = {
  name: string; // the Plex title, or the config name for a library Plex doesn't have
  plex: PlexLibrarySummary | null;
  config: LibraryCounts | null;
};

/** Plex's libraries in Plex's order, each with its config entry if it has one, then config entries Plex lacks. */
export function mergeLibraries(plex: PlexLibrarySummary[] | undefined, config: LibraryCounts[] | undefined): LibraryEntry[] {
  const configs = config ?? [];
  const used = new Set<string>();
  const entries: LibraryEntry[] = (plex ?? []).map((library) => {
    const match = configs.find((c) => c.plex_name === library.title) ?? null;
    if (match) used.add(match.name);
    return { name: library.title, plex: library, config: match };
  });
  for (const library of configs) {
    if (!used.has(library.name)) entries.push({ name: library.name, plex: null, config: library });
  }
  return entries;
}

export const libraryTypeLabels: Record<string, string> = { movie: "Movies", show: "TV", artist: "Music", photo: "Photos" };

export function libraryPath(name: string): string {
  return `/libraries/${encodeURIComponent(name)}`;
}

export function collectionPath(library: string, ratingKey: string): string {
  return `${libraryPath(library)}/collections/${encodeURIComponent(ratingKey)}`;
}
