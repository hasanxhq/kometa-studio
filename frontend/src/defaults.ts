// How the Defaults gallery sorts and describes Kometa's defaults. Kometa's files give a title and a wiki link, nothing more,
// and its docs aren't in its image, so the words are here. A default Studio doesn't know yet lands in Other, with no description.

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

export const categories = (kind: DefaultKind) => (kind === "overlay" ? overlayCategories : collectionCategories);

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

const DESCRIPTIONS: Record<string, string> = {
  "collection/anilist": "Popular, top rated and trending",
  "collection/basic": "Newly released, new episodes",
  "collection/imdb": "Popular, Top 250, lowest rated",
  "collection/letterboxd": "Top lists and film festival picks",
  "collection/myanimelist": "Popular, top rated and favourites",
  "collection/other_chart": "Common Sense, StevenLu and more",
  "collection/simkl": "Trending by day, week and month",
  "collection/tautulli": "What's popular and most watched on your server",
  "collection/tmdb": "Trending, popular, top rated",
  "collection/tracearr": "Popular and most watched, from your own history",
  "collection/actor": "Your library's most frequent actors",
  "collection/aspect": "Grouped by aspect ratio",
  "collection/audio_language": "A collection per audio language",
  "collection/based": "Based on books, comics, true stories, games",
  "collection/collectionless": "Keeps items out of collections visible in Plex",
  "collection/genre": "A collection per Plex genre",
  "collection/resolution": "A collection per resolution",
  "collection/streaming": "One collection per service you own",
  "collection/studio": "A collection per studio",
  "collection/subtitle_language": "A collection per subtitle language",
  "collection/universe": "Marvel, Star Wars, Wizarding World and more",
  "collection/year": "The best of each year",
  "collection/continent": "A collection per continent",
  "collection/country": "A collection per country",
  "collection/decade": "One collection per decade",
  "collection/director": "Your library's most frequent directors",
  "collection/franchise": "Series and universes",
  "collection/producer": "Your library's most frequent producers",
  "collection/region": "A collection per region of the world",
  "collection/seasonal": "Holidays, in season",
  "collection/writer": "Your library's most frequent writers",
  "collection/network": "A collection per TV network",
  "overlay/aspect": "Aspect ratio on each poster",
  "overlay/audio_codec": "Audio codec, such as Dolby Atmos",
  "overlay/commonsense": "Common Sense age rating",
  "overlay/content_rating_au": "Australian rating",
  "overlay/content_rating_de": "German FSK rating",
  "overlay/content_rating_nz": "New Zealand rating",
  "overlay/content_rating_uk": "British BBFC rating",
  "overlay/content_rating_us_movie": "US MPAA rating",
  "overlay/content_rating_us_show": "US TV rating",
  "overlay/direct_play": "Marks items that can't be transcoded",
  "overlay/episode_info": "Season and episode number on title cards",
  "overlay/language_count": "How many audio or subtitle languages",
  "overlay/languages": "A flag for each audio or subtitle language",
  "overlay/mediastinger": "Marks after-credits scenes",
  "overlay/network": "The show's network",
  "overlay/ratings": "IMDb, TMDb, Rotten Tomatoes and more",
  "overlay/resolution": "Resolution and edition",
  "overlay/ribbon": "Top lists, such as Oscar winners",
  "overlay/runtimes": "Running time",
  "overlay/status": "Airing, returning, ended, cancelled",
  "overlay/streaming": "The service an item is on",
  "overlay/studio": "The studio",
  "overlay/versions": "Marks items with several versions",
  "overlay/video_format": "Remux, Blu-ray, web and so on",
};

export function describeDefault(kind: DefaultKind, entry: Pick<DefaultEntry, "name" | "group">): string {
  return DESCRIPTIONS[`${kind}/${entry.name}`] ?? categoryOf(kind, entry).blurb ?? "";
}

/** A card's title: Kometa's, without the word the tab already says. */
export const shortTitle = (title: string) => title.replace(/\s+(Collections?|Overlays?)$/, "");
