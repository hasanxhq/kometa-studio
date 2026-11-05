"""Smart filter rules engine for Kometa and Plex.

Validates filter specifications, formats them as Kometa smart_filter mapping YAML,
and translates them to Plex query parameters for live collection preview.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

if TYPE_CHECKING:
    from starr_studio.plex_library import PlexServer


# ══════════════════════════════════════════════════════════════════════════════
# Kometa mappings and tables
# from kometa/modules/plex.py and builder.py, v2.5.4
# ══════════════════════════════════════════════════════════════════════════════

# from kometa/modules/plex.py, v2.5.4 line 166 (music-only entries left out)
SEARCH_TRANSLATION: dict[str, str] = {
    "episode_actor": "episode.actor",
    "episode_title": "episode.title",
    "network": "show.network",
    "edition": "editionTitle",
    "critic_rating": "rating",
    "audience_rating": "audienceRating",
    "episode_critic_rating": "episode.rating",
    "episode_audience_rating": "episode.audienceRating",
    "user_rating": "userRating",
    "episode_user_rating": "episode.userRating",
    "content_rating": "contentRating",
    "commonsense_rating": "contentRatingAge",
    "episode_year": "episode.year",
    "release": "originallyAvailableAt",
    "show_unmatched": "show.unmatched",
    "episode_unmatched": "episode.unmatched",
    "episode_duplicate": "episode.duplicate",
    "added": "addedAt",
    "episode_added": "episode.addedAt",
    "episode_air_date": "episode.originallyAvailableAt",
    "plays": "viewCount",
    "episode_plays": "episode.viewCount",
    "last_played": "lastViewedAt",
    "episode_last_played": "episode.lastViewedAt",
    "unplayed": "unwatched",
    "episode_unplayed": "episode.unwatched",
    "dovi": "dovi",
    "subtitle_language": "subtitleLanguage",
    "audio_language": "audioLanguage",
    "progress": "inProgress",
    "episode_progress": "episode.inProgress",
    "unplayed_episodes": "show.unwatchedLeaves",
    "season_collection": "season.collection",
    "episode_collection": "episode.collection",
    "season_label": "season.label",
    "episode_label": "episode.label",
}

# from kometa/modules/plex.py, v2.5.4 line 283
SHOW_TRANSLATION: dict[str, str] = {
    "title": "show.title",
    "country": "show.country",
    "studio": "show.studio",
    "rating": "show.rating",
    "audienceRating": "show.audienceRating",
    "userRating": "show.userRating",
    "contentRating": "show.contentRating",
    "year": "show.year",
    "originallyAvailableAt": "show.originallyAvailableAt",
    "unmatched": "show.unmatched",
    "genre": "show.genre",
    "collection": "show.collection",
    "actor": "show.actor",
    "addedAt": "show.addedAt",
    "viewCount": "show.viewCount",
    "lastViewedAt": "show.lastViewedAt",
    "editionTitle": "show.editionTitle",
    "resolution": "episode.resolution",
    "hdr": "episode.hdr",
    "dovi": "episode.dovi",
    "subtitleLanguage": "episode.subtitleLanguage",
    "audioLanguage": "episode.audioLanguage",
    "trash": "episode.trash",
    "label": "show.label",
}

# HDR10+ and Dolby Atmos (new in Kometa 2.5.4) have no fixed Plex key: Kometa takes the first of these that Plex's own
# filter list has for the search's level, and refuses the collection if Plex has neither (kometa/modules/builder.py,
# v2.5.4 line 4866). Studio's preview uses the first, which is what the Plex filter is called on a server that has it.
MEDIA_BOOLEANS: dict[str, tuple[str, str]] = {
    "hdr10plus": ("hdr10plus", "episode.hdr10plus"),  # (movie library, show library)
    "atmos": ("atmos", "episode.atmos"),
}

# from kometa/modules/plex.py, v2.5.4 line 310
MODIFIER_TRANSLATION: dict[str, str] = {
    "": "",
    ".not": "!",
    ".is": "%3D",
    ".isnot": "!%3D",
    ".gt": "%3E%3E",
    ".gte": "%3E",
    ".lt": "%3C%3C",
    ".lte": "%3C",
    ".before": "%3C%3C",
    ".after": "%3E%3E",
    ".begins": "%3C",
    ".ends": "%3E",
    ".regex": "",
    ".rated": "",
}

# from kometa/modules/plex.py, v2.5.4 line 546
MOVIE_ONLY_SEARCHES: list[str] = [
    "director",
    "director.not",
    "producer",
    "producer.not",
    "writer",
    "writer.not",
    "decade",
    "duplicate",
    "unplayed",
    "progress",
    "duration.gt",
    "duration.gte",
    "duration.lt",
    "duration.lte",
]

# from kometa/modules/plex.py, v2.5.4 line 562
SHOW_ONLY_SEARCHES: list[str] = [
    "network",
    "network.not",
    "season_collection",
    "season_collection.not",
    "episode_collection",
    "episode_collection.not",
    "season_label",
    "season_label.not",
    "episode_label",
    "episode_label.not",
    "episode_title",
    "episode_title.not",
    "episode_title.is",
    "episode_title.isnot",
    "episode_title.begins",
    "episode_title.ends",
    "episode_added",
    "episode_added.not",
    "episode_added.before",
    "episode_added.after",
    "episode_air_date",
    "episode_air_date.not",
    "episode_air_date.before",
    "episode_air_date.after",
    "episode_last_played",
    "episode_last_played.not",
    "episode_last_played.before",
    "episode_last_played.after",
    "episode_plays.gt",
    "episode_plays.gte",
    "episode_plays.lt",
    "episode_plays.lte",
    "episode_user_rating.gt",
    "episode_user_rating.gte",
    "episode_user_rating.lt",
    "episode_user_rating.lte",
    "episode_user_rating.rated",
    "episode_critic_rating.gt",
    "episode_critic_rating.gte",
    "episode_critic_rating.lt",
    "episode_critic_rating.lte",
    "episode_critic_rating.rated",
    "episode_audience_rating.gt",
    "episode_audience_rating.gte",
    "episode_audience_rating.lt",
    "episode_audience_rating.lte",
    "episode_audience_rating.rated",
    "episode_year",
    "episode_year.not",
    "episode_year.gt",
    "episode_year.gte",
    "episode_year.lt",
    "episode_year.lte",
    "unplayed_episodes",
    "episode_unplayed",
    "episode_duplicate",
    "episode_progress",
    "episode_unmatched",
    "show_unmatched",
]

# from kometa/modules/plex.py, v2.5.4 line 731
NO_NOT_MODS: list[str] = ["resolution", "decade", "album_decade"]

# from kometa/modules/plex.py, v2.5.4 line 746
MOVIE_SORTS: dict[str, str] = {
    "title.asc": "titleSort",
    "title.desc": "titleSort%3Adesc",
    "year.asc": "year",
    "year.desc": "year%3Adesc",
    "originally_available.asc": "originallyAvailableAt",
    "originally_available.desc": "originallyAvailableAt%3Adesc",
    "release.asc": "originallyAvailableAt",
    "release.desc": "originallyAvailableAt%3Adesc",
    "critic_rating.asc": "rating",
    "critic_rating.desc": "rating%3Adesc",
    "audience_rating.asc": "audienceRating",
    "audience_rating.desc": "audienceRating%3Adesc",
    "user_rating.asc": "userRating",
    "user_rating.desc": "userRating%3Adesc",
    "content_rating.asc": "contentRating",
    "content_rating.desc": "contentRating%3Adesc",
    "duration.asc": "duration",
    "duration.desc": "duration%3Adesc",
    "progress.asc": "viewOffset",
    "progress.desc": "viewOffset%3Adesc",
    "plays.asc": "viewCount",
    "plays.desc": "viewCount%3Adesc",
    "added.asc": "addedAt",
    "added.desc": "addedAt%3Adesc",
    "viewed.asc": "lastViewedAt",
    "viewed.desc": "lastViewedAt%3Adesc",
    "resolution.asc": "mediaHeight",
    "resolution.desc": "mediaHeight%3Adesc",
    "bitrate.asc": "mediaBitrate",
    "bitrate.desc": "mediaBitrate%3Adesc",
    "random": "random",
}

# from kometa/modules/plex.py, v2.5.4 line 779
SHOW_SORTS: dict[str, str] = {
    "title.asc": "titleSort",
    "title.desc": "titleSort%3Adesc",
    "year.asc": "year",
    "year.desc": "year%3Adesc",
    "originally_available.asc": "originallyAvailableAt",
    "originally_available.desc": "originallyAvailableAt%3Adesc",
    "episode_originally_available.asc": "episode.originallyAvailableAt",
    "episode_originally_available.desc": "episode.originallyAvailableAt%3Adesc",
    "release.asc": "originallyAvailableAt",
    "release.desc": "originallyAvailableAt%3Adesc",
    "episode_release.asc": "episode.originallyAvailableAt",
    "episode_release.desc": "episode.originallyAvailableAt%3Adesc",
    "critic_rating.asc": "rating",
    "critic_rating.desc": "rating%3Adesc",
    "audience_rating.asc": "audienceRating",
    "audience_rating.desc": "audienceRating%3Adesc",
    "user_rating.asc": "userRating",
    "user_rating.desc": "userRating%3Adesc",
    "content_rating.asc": "contentRating",
    "content_rating.desc": "contentRating%3Adesc",
    "unplayed.asc": "unviewedLeafCount",
    "unplayed.desc": "unviewedLeafCount%3Adesc",
    "episode_added.asc": "episode.addedAt",
    "episode_added.desc": "episode.addedAt%3Adesc",
    "added.asc": "addedAt",
    "added.desc": "addedAt%3Adesc",
    "viewed.asc": "lastViewedAt",
    "viewed.desc": "lastViewedAt%3Adesc",
    "random": "random",
}

SORT_LABELS: dict[str, str] = {
    "title.asc": "Title (A–Z)",
    "title.desc": "Title (Z–A)",
    "year.asc": "Year (oldest first)",
    "year.desc": "Year (newest first)",
    "release.asc": "Release date (oldest first)",
    "release.desc": "Release date (newest first)",
    "originally_available.asc": "Release date (oldest first)",
    "originally_available.desc": "Release date (newest first)",
    "critic_rating.asc": "Critic rating (lowest first)",
    "critic_rating.desc": "Critic rating (highest first)",
    "audience_rating.asc": "Audience rating (lowest first)",
    "audience_rating.desc": "Audience rating (highest first)",
    "user_rating.asc": "User rating (lowest first)",
    "user_rating.desc": "User rating (highest first)",
    "content_rating.asc": "Content rating (A–Z)",
    "content_rating.desc": "Content rating (Z–A)",
    "duration.asc": "Duration (shortest first)",
    "duration.desc": "Duration (longest first)",
    "progress.asc": "Progress (least first)",
    "progress.desc": "Progress (most first)",
    "plays.asc": "Plays (least first)",
    "plays.desc": "Plays (most first)",
    "added.asc": "Date added (oldest first)",
    "added.desc": "Date added (newest first)",
    "viewed.asc": "Date viewed (oldest first)",
    "viewed.desc": "Date viewed (newest first)",
    "resolution.asc": "Resolution (lowest first)",
    "resolution.desc": "Resolution (highest first)",
    "bitrate.asc": "Bitrate (lowest first)",
    "bitrate.desc": "Bitrate (highest first)",
    "random": "Random",
    "episode_release.asc": "Episode release date (oldest first)",
    "episode_release.desc": "Episode release date (newest first)",
    "episode_originally_available.asc": "Episode release date (oldest first)",
    "episode_originally_available.desc": "Episode release date (newest first)",
    "episode_added.asc": "Episode date added (oldest first)",
    "episode_added.desc": "Episode date added (newest first)",
    "unplayed.asc": "Unplayed episodes (least first)",
    "unplayed.desc": "Unplayed episodes (most first)",
}


class SmartFilterError(ValueError):
    """Raised when a smart filter specification is invalid or cannot be resolved."""


@dataclass(frozen=True)
class Field:
    key: str                       # Kometa attribute, e.g. "genre"
    label: str                     # "Genre"
    kind: str                      # "tag" | "string" | "number" | "float" | "date" | "boolean" | "year"
    modifiers: tuple[tuple[str, str], ...]   # (modifier without dot, label), e.g. (("", "is"), ("not", "is not"))
    group: str                     # UI grouping, e.g. "Details", "Media", "People", "Ratings", "Dates", "Watch status"
    plex_tag: str | None = None    # for tag fields: the /library/sections/<key>/<tag> directory to list values from (e.g. "genre", "contentRating"); None if values can't be listed
    episode: bool = False          # True when Kometa reads this attribute from episodes in a show library


# Common modifier sets
MODS_TAG: tuple[tuple[str, str], ...] = (("", "is"), ("not", "is not"))
MODS_TAG_NO_NOT: tuple[tuple[str, str], ...] = (("", "is"),)
MODS_YEAR: tuple[tuple[str, str], ...] = (
    ("", "is"),
    ("not", "is not"),
    ("gt", "greater than"),
    ("gte", "greater than or equal"),
    ("lt", "less than"),
    ("lte", "less than or equal"),
)
MODS_DECADE: tuple[tuple[str, str], ...] = (("", "is"),)
MODS_DATE: tuple[tuple[str, str], ...] = (
    ("", "in the last"),
    ("not", "not in the last"),
    ("before", "before"),
    ("after", "after"),
)
MODS_STRING: tuple[tuple[str, str], ...] = (
    ("", "contains"),
    ("not", "does not contain"),
    ("is", "is"),
    ("isnot", "is not"),
    ("begins", "begins with"),
    ("ends", "ends with"),
)
MODS_FLOAT_RATING: tuple[tuple[str, str], ...] = (
    ("gt", "greater than"),
    ("gte", "greater than or equal"),
    ("lt", "less than"),
    ("lte", "less than or equal"),
    ("rated", "is rated"),
)
MODS_FLOAT_NUM: tuple[tuple[str, str], ...] = (
    ("gt", "greater than"),
    ("gte", "greater than or equal"),
    ("lt", "less than"),
    ("lte", "less than or equal"),
)
MODS_NUMBER: tuple[tuple[str, str], ...] = (
    ("gt", "greater than"),
    ("gte", "greater than or equal"),
    ("lt", "less than"),
    ("lte", "less than or equal"),
)
MODS_COMMONSENSE: tuple[tuple[str, str], ...] = (
    ("", "is"),
    ("gt", "greater than"),
    ("gte", "greater than or equal"),
    ("lt", "less than"),
    ("lte", "less than or equal"),
)
MODS_BOOLEAN: tuple[tuple[str, str], ...] = (("", "is"),)


def _build_movie_fields() -> list[Field]:
    return [
        # Top most-used fields
        Field("genre", "Genre", "tag", MODS_TAG, "Details", plex_tag="genre"),
        Field("year", "Year", "year", MODS_YEAR, "Details"),
        Field("decade", "Decade", "year", MODS_DECADE, "Details"),
        Field("content_rating", "Content rating", "tag", MODS_TAG, "Details", plex_tag="contentRating"),
        Field("studio", "Studio", "tag", MODS_TAG, "Details", plex_tag="studio"),
        Field("actor", "Actor", "tag", MODS_TAG, "People", plex_tag="actor"),
        Field("director", "Director", "tag", MODS_TAG, "People", plex_tag="director"),
        Field("resolution", "Resolution", "tag", MODS_TAG_NO_NOT, "Media", plex_tag="resolution"),
        Field("unplayed", "Unplayed", "boolean", MODS_BOOLEAN, "Watch status"),
        Field("added", "Added", "date", MODS_DATE, "Dates"),
        Field("user_rating", "User rating", "float", MODS_FLOAT_RATING, "Ratings"),
        Field("critic_rating", "Critic rating", "float", MODS_FLOAT_RATING, "Ratings"),
        Field("audience_rating", "Audience rating", "float", MODS_FLOAT_RATING, "Ratings"),
        # Other details
        Field("country", "Country", "tag", MODS_TAG, "Details", plex_tag="country"),
        Field("collection", "Collection", "tag", MODS_TAG, "Details", plex_tag="collection"),
        Field("label", "Label", "tag", MODS_TAG, "Details", plex_tag="label"),
        Field("edition", "Edition", "string", MODS_STRING, "Details"),
        Field("title", "Title", "string", MODS_STRING, "Details"),
        Field("folder_location", "Folder location", "tag", MODS_TAG, "Details", plex_tag=None),
        # People
        Field("producer", "Producer", "tag", MODS_TAG, "People", plex_tag="producer"),
        Field("writer", "Writer", "tag", MODS_TAG, "People", plex_tag="writer"),
        # Media
        Field("hdr", "HDR", "boolean", MODS_BOOLEAN, "Media"),
        Field("dovi", "Dolby Vision", "boolean", MODS_BOOLEAN, "Media"),
        Field("hdr10plus", "HDR10+", "boolean", MODS_BOOLEAN, "Media"),
        Field("atmos", "Dolby Atmos", "boolean", MODS_BOOLEAN, "Media"),
        Field("audio_language", "Audio language", "tag", MODS_TAG, "Media", plex_tag="audioLanguage"),
        Field("subtitle_language", "Subtitle language", "tag", MODS_TAG, "Media", plex_tag="subtitleLanguage"),
        Field("duration", "Duration", "float", MODS_FLOAT_NUM, "Media"),
        # Watch status
        Field("progress", "In progress", "boolean", MODS_BOOLEAN, "Watch status"),
        Field("plays", "Plays", "number", MODS_NUMBER, "Watch status"),
        # Dates
        Field("release", "Release date", "date", MODS_DATE, "Dates"),
        Field("last_played", "Last played", "date", MODS_DATE, "Dates"),
        # Ratings
        Field("commonsense_rating", "Common Sense rating", "number", MODS_COMMONSENSE, "Ratings"),
        # Status
        Field("duplicate", "Duplicate", "boolean", MODS_BOOLEAN, "Status"),
        Field("unmatched", "Unmatched", "boolean", MODS_BOOLEAN, "Status"),
        Field("trash", "Trash", "boolean", MODS_BOOLEAN, "Status"),
    ]


def _build_show_fields() -> list[Field]:
    return [
        # Top most-used fields
        Field("genre", "Genre", "tag", MODS_TAG, "Details", plex_tag="genre"),
        Field("year", "Year", "year", MODS_YEAR, "Details"),
        Field("content_rating", "Content rating", "tag", MODS_TAG, "Details", plex_tag="contentRating"),
        Field("network", "Network", "tag", MODS_TAG, "Details", plex_tag="network"),
        Field("studio", "Studio", "tag", MODS_TAG, "Details", plex_tag="studio"),
        Field("actor", "Actor", "tag", MODS_TAG, "People", plex_tag="actor"),
        Field("resolution", "Resolution", "tag", MODS_TAG_NO_NOT, "Media", plex_tag="resolution", episode=True),
        Field("unplayed_episodes", "Unplayed episodes", "boolean", MODS_BOOLEAN, "Watch status"),
        Field("added", "Added", "date", MODS_DATE, "Dates"),
        Field("user_rating", "User rating", "float", MODS_FLOAT_RATING, "Ratings"),
        Field("critic_rating", "Critic rating", "float", MODS_FLOAT_RATING, "Ratings"),
        Field("audience_rating", "Audience rating", "float", MODS_FLOAT_RATING, "Ratings"),
        # Other details
        Field("country", "Country", "tag", MODS_TAG, "Details", plex_tag="country"),
        Field("collection", "Collection", "tag", MODS_TAG, "Details", plex_tag="collection"),
        Field("season_collection", "Season collection", "tag", MODS_TAG, "Details", plex_tag="collection"),
        Field("episode_collection", "Episode collection", "tag", MODS_TAG, "Details", plex_tag="collection", episode=True),
        Field("label", "Label", "tag", MODS_TAG, "Details", plex_tag="label"),
        Field("season_label", "Season label", "tag", MODS_TAG, "Details", plex_tag="label"),
        Field("episode_label", "Episode label", "tag", MODS_TAG, "Details", plex_tag="label", episode=True),
        Field("edition", "Edition", "string", MODS_STRING, "Details"),
        Field("title", "Title", "string", MODS_STRING, "Details"),
        Field("episode_title", "Episode title", "string", MODS_STRING, "Details", episode=True),
        Field("episode_year", "Episode year", "year", MODS_YEAR, "Details", episode=True),
        Field("folder_location", "Folder location", "tag", MODS_TAG, "Details", plex_tag=None),
        # People
        Field("episode_actor", "Episode actor", "tag", MODS_TAG, "People", plex_tag="actor", episode=True),
        # Media
        Field("hdr", "HDR", "boolean", MODS_BOOLEAN, "Media", episode=True),
        Field("dovi", "Dolby Vision", "boolean", MODS_BOOLEAN, "Media", episode=True),
        Field("hdr10plus", "HDR10+", "boolean", MODS_BOOLEAN, "Media", episode=True),
        Field("atmos", "Dolby Atmos", "boolean", MODS_BOOLEAN, "Media", episode=True),
        Field("audio_language", "Audio language", "tag", MODS_TAG, "Media", plex_tag="audioLanguage", episode=True),
        Field("subtitle_language", "Subtitle language", "tag", MODS_TAG, "Media", plex_tag="subtitleLanguage", episode=True),
        # Watch status
        Field("episode_unplayed", "Episode unplayed", "boolean", MODS_BOOLEAN, "Watch status", episode=True),
        Field("episode_progress", "Episode in progress", "boolean", MODS_BOOLEAN, "Watch status", episode=True),
        Field("plays", "Plays", "number", MODS_NUMBER, "Watch status"),
        Field("episode_plays", "Episode plays", "number", MODS_NUMBER, "Watch status", episode=True),
        # Dates
        Field("release", "Release date", "date", MODS_DATE, "Dates"),
        Field("last_played", "Last played", "date", MODS_DATE, "Dates"),
        Field("episode_added", "Episode added", "date", MODS_DATE, "Dates", episode=True),
        Field("episode_air_date", "Episode air date", "date", MODS_DATE, "Dates", episode=True),
        Field("episode_last_played", "Episode last played", "date", MODS_DATE, "Dates", episode=True),
        # Ratings
        Field("commonsense_rating", "Common Sense rating", "number", MODS_COMMONSENSE, "Ratings"),
        Field("episode_user_rating", "Episode user rating", "float", MODS_FLOAT_RATING, "Ratings", episode=True),
        Field("episode_critic_rating", "Episode critic rating", "float", MODS_FLOAT_RATING, "Ratings", episode=True),
        Field("episode_audience_rating", "Episode audience rating", "float", MODS_FLOAT_RATING, "Ratings", episode=True),
        # Status
        Field("show_unmatched", "Show unmatched", "boolean", MODS_BOOLEAN, "Status"),
        Field("episode_unmatched", "Episode unmatched", "boolean", MODS_BOOLEAN, "Status", episode=True),
        Field("episode_duplicate", "Episode duplicate", "boolean", MODS_BOOLEAN, "Status", episode=True),
        Field("unmatched", "Unmatched", "boolean", MODS_BOOLEAN, "Status"),
        Field("trash", "Trash", "boolean", MODS_BOOLEAN, "Status"),
    ]


_MOVIE_FIELDS = _build_movie_fields()
_SHOW_FIELDS = _build_show_fields()
_MOVIE_FIELDS_BY_KEY = {f.key: f for f in _MOVIE_FIELDS}
_SHOW_FIELDS_BY_KEY = {f.key: f for f in _SHOW_FIELDS}


def fields(library_type: str) -> list[Field]:
    """Filter fields supported for a movie or show library, ordered for a picker."""
    lib = library_type.lower()
    if lib == "movie":
        return list(_MOVIE_FIELDS)
    if lib == "show":
        return list(_SHOW_FIELDS)
    return []


def sorts(library_type: str) -> list[tuple[str, str]]:
    """Sort options supported for a library type as (Kometa sort key, label) pairs."""
    lib = library_type.lower()
    if lib == "movie":
        return [(k, SORT_LABELS.get(k, k)) for k in MOVIE_SORTS]
    if lib == "show":
        return [(k, SORT_LABELS.get(k, k)) for k in SHOW_SORTS]
    return []


def validate(library_type: str, spec: dict, sort_by: str | None = None) -> list[str]:
    """Validate a smart filter spec and optional sort_by against Kometa's rules."""
    problems: list[str] = []
    lib = library_type.lower()
    if lib not in ("movie", "show"):
        return [f"Unknown library type '{library_type}'"]

    if not isinstance(spec, dict):
        return ["Filter spec must be a dictionary"]

    match = spec.get("match")
    if match not in ("all", "any"):
        problems.append(f"Invalid match '{match}'; must be 'all' or 'any'")

    rules = spec.get("rules")
    if rules is None or not isinstance(rules, list) or len(rules) == 0:
        problems.append("Rule list cannot be empty")
        return problems

    if sort_by is not None:
        allowed_sorts = dict(sorts(lib))
        if sort_by not in allowed_sorts:
            problems.append(f"Unknown sort '{sort_by}' for {lib} library")

    field_map = _MOVIE_FIELDS_BY_KEY if lib == "movie" else _SHOW_FIELDS_BY_KEY
    other_field_map = _SHOW_FIELDS_BY_KEY if lib == "movie" else _MOVIE_FIELDS_BY_KEY

    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            problems.append(f"Rule {idx + 1} must be a dictionary")
            continue

        field_key = rule.get("field")
        if not field_key:
            problems.append(f"Rule {idx + 1} is missing 'field'")
            continue

        if field_key not in field_map:
            if field_key in other_field_map:
                target_lib = "show" if lib == "movie" else "movie"
                problems.append(f"Field '{field_key}' only works for {target_lib} libraries")
            else:
                problems.append(f"Unknown field '{field_key}'")
            continue

        field_obj = field_map[field_key]
        modifier = rule.get("modifier", "")
        if not isinstance(modifier, str):
            problems.append(f"Field '{field_key}' modifier must be a string")
            continue

        allowed_mods = [m[0] for m in field_obj.modifiers]
        if modifier not in allowed_mods:
            problems.append(f"Field '{field_key}' does not support modifier '{modifier}'")
            continue

        if "value" not in rule:
            problems.append(f"Field '{field_key}' is missing 'value'")
            continue

        value = rule["value"]
        if value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and len(value) == 0):
            problems.append(f"Field '{field_key}' value cannot be empty")
            continue

        # Kind-specific validations
        if field_obj.kind == "boolean":
            if not isinstance(value, bool):
                problems.append(f"Field '{field_key}' value must be a boolean")
        elif field_obj.kind == "string":
            if not isinstance(value, str) or isinstance(value, bool):
                problems.append(f"Field '{field_key}' value must be a string")
        elif field_obj.kind == "tag":
            if isinstance(value, str) and not isinstance(value, bool):
                pass
            elif isinstance(value, list) and all(isinstance(v, str) and not isinstance(v, bool) and v.strip() for v in value):
                pass
            else:
                problems.append(f"Field '{field_key}' value must be a string or list of strings")
        elif field_obj.kind == "number":
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"Field '{field_key}' value must be an integer")
            elif value < 0:
                problems.append(f"Field '{field_key}' value must be non-negative")
        elif field_obj.kind == "year":
            def _valid_year(y: object) -> bool:
                if isinstance(y, int) and not isinstance(y, bool) and y >= 0:
                    return True
                if isinstance(y, str):
                    if y.isdigit():
                        return True
                    if y.startswith("current_year"):
                        parts = y.split("-")
                        if len(parts) == 1:
                            return True
                        if len(parts) == 2 and parts[1].strip().isdigit():
                            return True
                return False

            if modifier in ("", "not"):
                items = value if isinstance(value, list) else [value]
                if not all(_valid_year(it) for it in items):
                    problems.append(f"Field '{field_key}' value must be a valid year")
            else:
                if not _valid_year(value):
                    problems.append(f"Field '{field_key}' value must be a valid year")
        elif field_obj.kind == "float":
            if modifier == "rated":
                if not isinstance(value, bool):
                    problems.append(f"Field '{field_key}' value for 'rated' modifier must be a boolean")
            else:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.append(f"Field '{field_key}' value must be a number")
                elif field_key != "duration":
                    if value < 0 or value > 10:
                        problems.append(f"Field '{field_key}' value must be between 0 and 10")
                else:
                    if value < 0:
                        problems.append(f"Field '{field_key}' value must be non-negative")
        elif field_obj.kind == "date":
            if modifier in ("", "not"):
                if isinstance(value, int) and not isinstance(value, bool):
                    if value < 0:
                        problems.append(f"Field '{field_key}' value must be non-negative")
                elif isinstance(value, str):
                    s = value.strip()
                    if s.endswith(("s", "m", "h", "d", "w", "o", "y")):
                        s = s[:-1]
                    if not s.isdigit():
                        problems.append(f"Field '{field_key}' value must be an integer or duration (e.g. 30, '30d')")
                else:
                    problems.append(f"Field '{field_key}' value must be an integer or duration (e.g. 30, '30d')")
            elif modifier in ("before", "after"):
                if not isinstance(value, str):
                    problems.append(f"Field '{field_key}' value must be a date string")
                elif value.strip().lower() != "today":
                    parsed = False
                    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
                        try:
                            datetime.strptime(value.strip(), fmt)
                            parsed = True
                            break
                        except ValueError:
                            pass
                    if not parsed:
                        problems.append(f"Field '{field_key}' value must be a valid date (YYYY-MM-DD)")

    return problems


def to_kometa(spec: dict, sort_by: str | None = None, limit: int | None = None) -> dict:
    """Turn a spec into Kometa's smart_filter mapping for Studio's generated YAML."""
    match = spec.get("match", "all")
    inner: dict = {}

    for rule in spec.get("rules", []):
        field = rule["field"]
        modifier = rule.get("modifier", "")
        key = f"{field}.{modifier}" if modifier else field
        val = rule["value"]

        # If duplicate tag field and modifier rule exists, merge into one list
        if key in inner:
            existing = inner[key]
            existing_list = existing if isinstance(existing, list) else [existing]
            new_list = val if isinstance(val, list) else [val]
            for item in new_list:
                if item not in existing_list:
                    existing_list.append(item)
            inner[key] = existing_list
        else:
            inner[key] = val

    result: dict = {match: inner}
    if sort_by is not None:
        result["sort_by"] = sort_by
    if limit is not None:
        result["limit"] = limit
    return result


def _normalize_date_arg(value: object) -> str:
    """Normalize date argument for before/after filter (kometa/modules/builder.py validate_attribute, line 5175)."""
    val_str = str(value).strip()
    if val_str.lower() == "today":
        return datetime.now().strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return val_str


async def plex_query(
    plex: PlexServer,
    library_key: str,
    library_type: str,
    spec: dict,
    sort_by: str | None = None,
) -> list[tuple[str, str]]:
    """Build the parameter pairs for GET /library/sections/<library_key>/all matching Kometa's smart collection query.

    Resolves tag titles to Plex keys via ``plex.tag_values(...)``.
    Includes ``type`` and ``sort`` parameters, and mirrors Kometa's push/or/pop grouping for 'any'.
    Raises SmartFilterError on validation error or unknown tag values.
    """
    problems = validate(library_type, spec, sort_by=sort_by)
    if problems:
        raise SmartFilterError("; ".join(problems))

    lib = library_type.lower()
    field_map = _MOVIE_FIELDS_BY_KEY if lib == "movie" else _SHOW_FIELDS_BY_KEY

    # 1. Type parameter: 1 for movie, 2 for show (kometa/modules/plex.py line 921 sort_types)
    type_key = "1" if lib == "movie" else "2"

    # 2. Sort parameter: title.asc if not given. Kometa's own default for smart_filter is random (builder.py lines 1720, 4825),
    #    which would reshuffle the preview on every look
    sort_dict = MOVIE_SORTS if lib == "movie" else SHOW_SORTS
    sort_key = sort_by if sort_by is not None else "title.asc"
    sort_param_value = sort_dict[sort_key]

    params: list[tuple[str, str]] = [("type", type_key), ("sort", sort_param_value)]

    is_all = spec.get("match", "all") == "all"
    conjunction = ("and", "1") if is_all else ("or", "1")

    # Collect rule parameter pairs
    rule_pairs: list[tuple[str, str]] = []

    for rule in spec.get("rules", []):
        field_key = rule["field"]
        modifier = rule.get("modifier", "")
        raw_val = rule["value"]
        field_obj = field_map[field_key]

        # Determine Plex search key (kometa/modules/builder.py build_url_arg, lines 4865-4876; plex.py get_search_key, lines 1564-1583)
        arg_key = SEARCH_TRANSLATION.get(field_key, field_key)
        if lib == "show" and arg_key in SHOW_TRANSLATION:
            arg_key = SHOW_TRANSLATION[arg_key]
        if field_key == "folder_location":
            arg_key = "episode.source" if lib == "show" else "source"
        if field_key in MEDIA_BOOLEANS:
            arg_key = MEDIA_BOOLEANS[field_key][1 if lib == "show" else 0]

        dot_mod = f".{modifier}" if modifier else ""

        # Case 1: Tag attributes (kometa/modules/builder.py lines 4941-4960 & 5140-5177)
        if field_obj.kind == "tag":
            mod_code = MODIFIER_TRANSLATION.get(dot_mod, dot_mod)
            tag_name = field_obj.plex_tag
            raw_items = raw_val if isinstance(raw_val, list) else [raw_val]
            resolved_keys: list[str] = []

            if tag_name is not None:
                available_tags = await plex.tag_values(
                    library_key,
                    tag_name,
                    library_type=lib,
                    episode=field_obj.episode,
                )
                tag_map: dict[str, str] = {}
                for title, key in available_tags:
                    tag_map[title.lower()] = key
                    tag_map[key.lower()] = key

                for item in raw_items:
                    item_str = str(item)
                    if item_str.lower() in tag_map:
                        resolved_keys.append(tag_map[item_str.lower()])
                    else:
                        raise SmartFilterError(f"Tag value '{item}' not found for field '{field_key}'")
            else:
                # Untyped/unlisted tag attribute (e.g. folder_location)
                resolved_keys = [str(item) for item in raw_items]

            for key_val in resolved_keys:
                rule_pairs.append((f"{arg_key}{mod_code}", key_val))

        # Case 2: String attributes (kometa/modules/builder.py line 4958: quote string)
        elif field_obj.kind == "string":
            mod_code = MODIFIER_TRANSLATION.get(dot_mod, dot_mod)
            raw_items = raw_val if isinstance(raw_val, list) else [raw_val]
            for item in raw_items:
                rule_pairs.append((f"{arg_key}{mod_code}", quote(str(item))))

        # Case 3: Date attributes (kometa/modules/builder.py lines 4920-4932)
        elif field_obj.kind == "date":
            if modifier in ("", "not"):
                # in the last N days (or duration)
                last_mod = "%3E%3E" if modifier == "" else "%3C%3C"
                s = str(raw_val).strip()
                unit = "d"
                if s.endswith(("s", "m", "h", "d", "w", "o", "y")):
                    unit = s[-1]
                    s = s[:-1]
                if unit == "o":
                    validation = f"{s}mon"
                else:
                    validation = f"{s}{unit}"
                rule_pairs.append((f"{arg_key}{last_mod}", f"-{validation}"))
            elif modifier in ("before", "after"):
                mod_code = MODIFIER_TRANSLATION.get(dot_mod, dot_mod)
                date_str = _normalize_date_arg(raw_val)
                rule_pairs.append((f"{arg_key}{mod_code}", date_str))

        # Case 4: Duration (kometa/modules/builder.py line 4933: minutes to ms)
        elif field_key == "duration":
            mod_code = MODIFIER_TRANSLATION.get(dot_mod, dot_mod)
            ms = int(float(raw_val) * 60000)
            rule_pairs.append((f"{arg_key}{mod_code}", str(ms)))

        # Case 5: Float ratings with .rated modifier (kometa/modules/builder.py line 4935)
        elif modifier == "rated":
            bool_mod = "!" if bool(raw_val) else ""
            rule_pairs.append((f"{arg_key}{bool_mod}", "-1"))

        # Case 6: Booleans (kometa/modules/builder.py line 4937: value 1 with mod ! if false)
        elif field_obj.kind == "boolean":
            bool_mod = "" if bool(raw_val) else "!"
            rule_pairs.append((f"{arg_key}{bool_mod}", "1"))

        # Case 7: Numbers, years, and regular floats
        else:
            mod_code = MODIFIER_TRANSLATION.get(dot_mod, dot_mod)
            raw_items = raw_val if isinstance(raw_val, list) else [raw_val]
            for item in raw_items:
                rule_pairs.append((f"{arg_key}{mod_code}", str(item)))

    if not rule_pairs:
        return [(unquote(key), unquote(value)) for key, value in params]

    # Interleave with conjunctions and push/pop wrapper for 'any' (kometa/modules/builder.py lines 5007-5008)
    if is_all:
        for idx, pair in enumerate(rule_pairs):
            if idx > 0:
                params.append(conjunction)
            params.append(pair)
    else:
        params.append(("push", "1"))
        for idx, pair in enumerate(rule_pairs):
            if idx > 0:
                params.append(conjunction)
            params.append(pair)
        params.append(("pop", "1"))

    # Kometa writes these into a URI by hand, already %-encoded (``%3E`` for ``>``). Studio passes them to httpx,
    # which encodes them itself, so hand back the decoded form; otherwise Plex would get ``year%253E`` and ignore it.
    return [(unquote(key), unquote(value)) for key, value in params]
