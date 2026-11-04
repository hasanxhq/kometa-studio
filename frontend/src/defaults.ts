// Categories and banners for Kometa's collection defaults (Ready-made covers) and short titles. Kometa's files give a title and a
// wiki link, nothing more, so the grouping is here. A default Studio doesn't know yet lands in Other.

import type { DefaultEntry, DefaultKind } from "./api";

export type Category = { id: string; label: string; banner: string; blurb?: string };

const collectionCategories: Category[] = [
  { id: "chart", label: "Chart", banner: "bg-banner-chart" },
  { id: "award", label: "Award", banner: "bg-banner-award", blurb: "Winners by year, plus the best overall" },
  { id: "streaming", label: "Streaming", banner: "bg-banner-streaming" },
  { id: "genre", label: "Genre & content rating", banner: "bg-banner-genre", blurb: "A collection per rating in your library" },
  { id: "studio", label: "Studio & franchise", banner: "bg-banner-studio" },
  { id: "people", label: "People", banner: "bg-banner-people" },
  { id: "time", label: "Time & place", banner: "bg-banner-time" },
  { id: "media", label: "Media", banner: "bg-banner-media" },
  { id: "separators", label: "Separators", banner: "bg-banner-plain", blurb: "Index cards between groups" },
  { id: "other", label: "Other", banner: "bg-banner-plain" },
];

const overlayCategories: Category[] = [
  { id: "rating", label: "Ratings", banner: "bg-banner-genre" },
  { id: "media", label: "Media", banner: "bg-banner-media" },
  { id: "streaming", label: "Streaming & network", banner: "bg-banner-streaming" },
  { id: "info", label: "Status & info", banner: "bg-banner-time" },
  { id: "other", label: "Other", banner: "bg-banner-plain" },
];

const categories = (kind: DefaultKind) => (kind === "overlay" ? overlayCategories : collectionCategories);

const COLLECTIONS: Record<string, string> = {
  streaming: "streaming",
  network: "streaming",
  genre: "genre",
  based: "genre",
  studio: "studio",
  franchise: "studio",
  universe: "studio",
  actor: "people",
  director: "people",
  producer: "people",
  writer: "people",
  year: "time",
  decade: "time",
  seasonal: "time",
  country: "time",
  continent: "time",
  region: "time",
  aspect: "media",
  resolution: "media",
  audio_language: "media",
  subtitle_language: "media",
};

const OVERLAYS: Record<string, string> = {
  commonsense: "rating",
  ratings: "rating",
  aspect: "media",
  audio_codec: "media",
  direct_play: "media",
  language_count: "media",
  languages: "media",
  resolution: "media",
  versions: "media",
  video_format: "media",
  network: "streaming",
  streaming: "streaming",
  studio: "streaming",
  episode_info: "info",
  mediastinger: "info",
  ribbon: "info",
  runtimes: "info",
  status: "info",
};

export function categoryOf(kind: DefaultKind, entry: Pick<DefaultEntry, "name" | "group">): Category {
  let id: string;
  if (kind === "overlay") id = entry.name.startsWith("content_rating") ? "rating" : (OVERLAYS[entry.name] ?? "other");
  else if (entry.name.startsWith("separator")) id = "separators";
  else if (entry.name.startsWith("content_rating")) id = "genre";
  else if (entry.group === "chart" || entry.group === "award") id = entry.group;
  else id = COLLECTIONS[entry.name] ?? "other";
  return categories(kind).find((category) => category.id === id)!;
}

/** A card's title: Kometa's, without the word Collections or Overlays. */
export const shortTitle = (title: string) => title.replace(/\s+(Collections?|Overlays?)$/, "");
