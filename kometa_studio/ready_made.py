"""The ready-made catalogue: what each Kometa default makes, per library.

Lists categories and collection entries from Kometa's shipped defaults,
without modifying or importing Kometa internals.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from kometa_studio import tmdb_languages
from kometa_studio.kometa_files import _banner, _read
from kometa_studio.plex_library import PlexServer


@dataclass
class Entry:
    block: str  # '' for static
    key: str
    kometa_name: str
    title: str
    items: int | None = None  # titles in this library that would go in it, when Plex can tell cheaply


@dataclass
class Category:
    name: str  # default name, e.g. 'genre'
    title: str  # from the file's banner (kometa_files._banner), falling back to the name
    group: str  # folder: chart / award / both / movie / show
    kind: str  # 'fixed' (chart lists), 'award', 'per_value' (one per value in the library), 'helper' (collectionless)
    listable: bool  # False when Studio can't list its collections yet
    reason: str | None  # why not, in plain words for the UI, e.g. "Kometa picks these from TMDb at build time"
    collections: list[Entry]
    count_error: str | None = None  # set by count(): why the counted list couldn't be made, shown instead of it


@dataclass(frozen=True)
class DynamicTypeSource:
    source: str  # "file", "plex", or "external"
    tag: str | None = None  # Plex tag name (e.g. "genre", "contentRating")
    listable: bool = True  # Whether Studio can list its collections in phase 1
    reason: str | None = None  # Reason when listable is False


# Kometa's auto types per library type (modules/meta.py: lines 16-23: all_auto, ms_auto, auto)
_ALL_AUTO = ["genre", "number", "custom"]
_MS_AUTO = [
    "actor", "year", "content_rating", "original_language", "tmdb_popular_people",
    "studio", "subtitle_language", "audio_language", "resolution", "decade", "imdb_awards",
]
AUTO_TYPES: dict[str, set[str]] = {
    "movie": set(["tmdb_collection", "edition", "country", "director", "producer", "writer", "letterboxd_user_lists"] + _ALL_AUTO + _MS_AUTO),
    "show": set(["edition", "network", "origin_country", "episode_year"] + _ALL_AUTO + _MS_AUTO),
}

# Mapping of Kometa dynamic collection types to their data sources and listability.
# Cites modules/meta.py: lines 825-1186. Checked on Kometa updates against auto in meta.py.
DYNAMIC_TYPE_SOURCES: dict[str, DynamicTypeSource] = {
    # File-based types: keys come from the default file itself (data or numeric/award range)
    "custom": DynamicTypeSource(source="file", listable=True),
    "number": DynamicTypeSource(source="file", listable=True),
    "imdb_awards": DynamicTypeSource(source="file", listable=True),

    # Plex-based types: keys come from the library's Plex tag values
    "genre": DynamicTypeSource(source="plex", tag="genre", listable=True),
    "decade": DynamicTypeSource(source="plex", tag="decade", listable=True),
    "year": DynamicTypeSource(source="plex", tag="year", listable=True),
    "content_rating": DynamicTypeSource(source="plex", tag="contentRating", listable=True),
    "studio": DynamicTypeSource(source="plex", tag="studio", listable=True),
    "country": DynamicTypeSource(source="plex", tag="country", listable=True),
    "network": DynamicTypeSource(source="plex", tag="network", listable=True),
    "resolution": DynamicTypeSource(source="plex", tag="resolution", listable=True),
    "audio_language": DynamicTypeSource(source="plex", tag="audioLanguage", listable=True),
    "subtitle_language": DynamicTypeSource(source="plex", tag="subtitleLanguage", listable=True),

    # External / unlistable types: require TMDb, Trakt, or library-wide appearance ranking
    "tmdb_collection": DynamicTypeSource(source="external", listable=False, reason="Kometa picks these from TMDb at build time"),
    "actor": DynamicTypeSource(source="external", listable=False, reason="Requires scanning the library and ranking actors by appearances"),
    "director": DynamicTypeSource(source="external", listable=False, reason="Requires scanning the library and ranking directors by appearances"),
    "producer": DynamicTypeSource(source="external", listable=False, reason="Requires scanning the library and ranking producers by appearances"),
    "writer": DynamicTypeSource(source="external", listable=False, reason="Requires scanning the library and ranking writers by appearances"),
    "origin_country": DynamicTypeSource(source="external", listable=False, reason="Kometa queries TMDb for each show's origin country at build time"),
    "original_language": DynamicTypeSource(source="external", listable=False, reason="Requires looking up original languages on TMDb"),
    "tmdb_popular_people": DynamicTypeSource(source="external", listable=False, reason="Requires fetching popular people from TMDb"),
    "letterboxd_user_lists": DynamicTypeSource(source="external", listable=False, reason="Requires fetching user lists from Letterboxd"),
    "edition": DynamicTypeSource(source="external", listable=False, reason="Edition collections are not supported in phase 1"),
    "episode_year": DynamicTypeSource(source="external", listable=False, reason="Episode year collections are not supported in phase 1"),
    "mood": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
    "style": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
    "album_genre": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
    "album_mood": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
    "album_style": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
    "track_mood": DynamicTypeSource(source="external", listable=False, reason="Music collections are not supported in phase 1"),
}


# Kometa reads these from episodes in a show library (meta.py: library.get_tags(f"episode.{search_tag}")).
EPISODE_TYPES = {"resolution", "audio_language", "subtitle_language"}
LANGUAGE_TYPES = {"audio_language", "subtitle_language"}
NO_LANGUAGE_NAMES = (
    "Kometa names these collections with TMDb's language names, and Studio couldn't get them. "
    "Check the TMDb key in Settings → Connect, then count again."
)


def _yaml() -> YAML:
    return YAML(typ="safe", pure=True)


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return [str(value)]


def _is_separator(collection_attrs: dict) -> bool:
    templates = collection_attrs.get("template")
    if not templates:
        return False
    if isinstance(templates, str):
        return templates == "separator"
    if isinstance(templates, dict):
        return templates.get("name") == "separator"
    if isinstance(templates, list):
        for t in templates:
            if isinstance(t, str) and t == "separator":
                return True
            if isinstance(t, dict) and t.get("name") == "separator":
                return True
    return False


def _is_library_allowed(attrs: dict, library_type: str) -> bool:
    al = attrs.get("allowed_libraries")
    if al is None and "variables" in attrs and isinstance(attrs["variables"], dict):
        al = attrs["variables"].get("allowed_libraries")
    if al is None and "template" in attrs:
        templates = attrs["template"]
        if isinstance(templates, dict):
            al = templates.get("allowed_libraries")
        elif isinstance(templates, list):
            for t in templates:
                if isinstance(t, dict) and "allowed_libraries" in t:
                    al = t["allowed_libraries"]
                    break
    if al is None:
        return True
    if isinstance(al, str):
        return al.lower() == library_type.lower()
    if isinstance(al, list):
        return library_type.lower() in [str(x).lower() for x in al]
    return True


def _is_dynamic_key_allowed(key: str, template_vars: dict, library_type: str) -> bool:
    al = template_vars.get("allowed_libraries")
    if al is None:
        return True
    if isinstance(al, str):
        return al.lower() == library_type.lower()
    if isinstance(al, dict):
        if key in al:
            val = al[key]
            return val.lower() == library_type.lower() if isinstance(val, str) else True
        if "default" in al:
            val = al["default"]
            return val.lower() == library_type.lower() if isinstance(val, str) else True
    if isinstance(al, list):
        return library_type.lower() in [str(x).lower() for x in al]
    return True


def _build_dynamic_title(
    key: str,
    value: str,
    library_type: str,
    auto_type: str,
    title_format: str | None,
    key_name_override: dict,
    title_override: dict,
    remove_prefix: list[str],
    remove_suffix: list[str],
    template_vars: dict | None = None,
) -> str:
    key_str = str(key)
    # meta.py line 1333: key_name_override
    if key_str in key_name_override:
        key_name = str(key_name_override[key_str])
    elif key in key_name_override:
        key_name = str(key_name_override[key])
    else:
        key_name = str(value)
        # meta.py lines 1337-1342: remove_prefix and remove_suffix
        for prefix in remove_prefix:
            if key_name.startswith(prefix):
                key_name = key_name[len(prefix):].strip()
        for suffix in remove_suffix:
            if key_name.endswith(suffix):
                key_name = key_name[:-len(suffix)].strip()

    # meta.py line 1363: title_override
    if key_str in title_override:
        return str(title_override[key_str])
    if key in title_override:
        return str(title_override[key])

    # Default title formats (meta.py lines 869, 947-960)
    if not title_format:
        if auto_type == "resolution":
            title_format = "<<key_name>> <<library_type>>s"
        elif auto_type == "decade":
            title_format = "Best <<library_type>>s of the <<key_name>>"
        elif auto_type == "year":
            title_format = "Best <<library_type>>s of <<key_name>>"
        elif auto_type == "custom":
            title_format = "<<key_name>>"
        else:
            title_format = "Top <<key_name>> <<library_type>>s"

    title = title_format.replace("<<key_name>>", key_name).replace("<<title>>", key_name)
    title = title.replace("<<library_type>>", library_type.lower())
    title = title.replace("<<library_typeU>>", library_type.capitalize())
    if template_vars:
        for k, v in template_vars.items():
            if f"<<{k}>>" in title and not isinstance(v, (dict, list)):
                title = title.replace(f"<<{k}>>", str(v))
    return title


def _expand_file_dynamic(
    block_name: str,
    dynamic_data: dict,
    library_type: str,
) -> list[Entry]:
    auto_type = dynamic_data.get("type", "custom")
    title_format = dynamic_data.get("title_format")
    key_name_override = {str(k): v for k, v in (dynamic_data.get("key_name_override") or {}).items()}
    title_override = {str(k): v for k, v in (dynamic_data.get("title_override") or {}).items()}
    remove_prefix = _to_str_list(dynamic_data.get("remove_prefix"))
    remove_suffix = _to_str_list(dynamic_data.get("remove_suffix"))
    template_vars = dynamic_data.get("template_variables") or {}

    og_exclude = [str(x) for x in _to_str_list(dynamic_data.get("exclude"))]
    include = [str(x) for x in _to_str_list(dynamic_data.get("include"))]
    addons = {str(k): [str(x) for x in _to_str_list(v)] for k, v in (dynamic_data.get("addons") or {}).items()}

    # meta.py line 868: addons child values added to exclude
    exclude = list(og_exclude)
    for k, v in addons.items():
        exclude.extend([y for y in v if y != k and y not in exclude])

    auto_list: dict[str, str] = {}

    if auto_type == "custom":
        data = dynamic_data.get("data") or {}
        if isinstance(data, dict):
            for k, v in data.items():
                k_str, v_str = str(k), str(v)
                if k_str not in exclude and v_str not in exclude:
                    auto_list[k_str] = v_str

    elif auto_type == "number":
        data = dynamic_data.get("data") or {}
        current_year = datetime.now().year
        start_raw = str(data.get("starting", 0))
        end_raw = str(data.get("ending", 0))
        if start_raw.startswith("current_year"):
            parts = start_raw.split("-")
            start = current_year - (int(parts[1].strip()) if len(parts) > 1 else 0)
        else:
            start = int(start_raw)
        if end_raw.startswith("current_year"):
            parts = end_raw.split("-")
            end = current_year - (int(parts[1].strip()) if len(parts) > 1 else 0)
        else:
            end = int(end_raw)
        inc = int(data.get("increment", 1))
        curr = start
        while curr <= end:
            s_curr = str(curr)
            if s_curr not in exclude and curr not in exclude:
                auto_list[s_curr] = s_curr
            curr += inc

    elif auto_type == "imdb_awards":
        data = dynamic_data.get("data") or {}
        current_year = datetime.now().year
        start_raw = str(data.get("starting", "latest"))
        end_raw = str(data.get("ending", "latest"))

        def parse_award_pos(val: str) -> int:
            if val.startswith(("latest", "current_year")):
                parts = val.split("-")
                return current_year - (int(parts[1].strip()) if len(parts) > 1 else 0)
            if val.startswith("first"):
                parts = val.split("+")
                return (int(parts[1].strip()) if len(parts) > 1 else 0)
            return int(val)

        start = parse_award_pos(start_raw)
        end = parse_award_pos(end_raw)
        inc = int(data.get("increment", 1))
        curr = start
        while curr <= end:
            s_curr = str(curr)
            if s_curr not in exclude:
                auto_list[s_curr] = s_curr
            curr += inc

    if include:
        auto_list = {k: v for k, v in auto_list.items() if k in include}

    entries: list[Entry] = []
    for k, v in auto_list.items():
        if not _is_dynamic_key_allowed(k, template_vars, library_type):
            continue
        title = _build_dynamic_title(
            key=k,
            value=v,
            library_type=library_type,
            auto_type=auto_type,
            title_format=title_format,
            key_name_override=key_name_override,
            title_override=title_override,
            remove_prefix=remove_prefix,
            remove_suffix=remove_suffix,
            template_vars=template_vars,
        )
        # meta.py line 1412: self.collections[collection_title] = col
        entries.append(Entry(block=block_name, key=k, kometa_name=title, title=title))
    return entries


def categories(kometa_root: Path, library_type: str) -> list[Category]:
    """Categories and collection entries known from default files alone."""
    library_type = library_type.lower()
    if library_type not in ("movie", "show"):
        return []
    defaults_folder = kometa_root / "defaults" if (kometa_root / "defaults").is_dir() else kometa_root
    if not defaults_folder.is_dir():
        return []

    folders = [library_type, "both", "chart", "award"]
    seen_stems: set[str] = set()
    result: list[Category] = []

    for folder in folders:
        folder_path = defaults_folder / folder
        if not folder_path.is_dir():
            continue
        for path in sorted(folder_path.glob("*.yml")):
            name = path.stem
            if name in ("separator_award", "separator_chart"):
                continue
            if name in seen_stems:
                continue

            text = _read(path)
            if not text:
                continue
            try:
                data = _yaml().load(text)
            except YAMLError:
                continue
            if not isinstance(data, dict):
                continue

            # Check file-level allowed_libraries (e.g. chart/letterboxd.yml)
            et = data.get("external_templates") or {}
            tv = et.get("template_variables") or {}
            al = tv.get("allowed_libraries")
            if al and str(al).lower() != library_type:
                continue

            banner_title, _ = _banner(text)
            title = banner_title if banner_title else name

            # Category kind
            if name == "collectionless":
                kind = "helper"
            elif folder == "chart":
                kind = "fixed"
            elif folder == "award":
                kind = "award"
            else:
                kind = "per_value"

            static_cols = data.get("collections") or {}
            dynamic_cols = data.get("dynamic_collections") or {}

            # Static collections (meta.py line 805)
            entries: list[Entry] = []
            for col_name, col_attrs in static_cols.items():
                if not isinstance(col_attrs, dict):
                    col_attrs = {}
                if _is_separator(col_attrs):
                    continue
                if not _is_library_allowed(col_attrs, library_type):
                    continue
                entries.append(Entry(block="", key=str(col_name), kometa_name=str(col_name), title=str(col_name)))

            listable = True
            reason = None

            # Dynamic collections
            if isinstance(dynamic_cols, dict) and dynamic_cols:
                for block_name, block_attrs in dynamic_cols.items():
                    if not isinstance(block_attrs, dict):
                        continue
                    auto_type = str(block_attrs.get("type", "")).lower()
                    if auto_type not in AUTO_TYPES.get(library_type, set()):
                        continue
                    type_info = DYNAMIC_TYPE_SOURCES.get(auto_type)
                    if type_info is None or not type_info.listable:
                        listable = False
                        reason = type_info.reason if type_info else f"Type {auto_type} is not supported"
                        entries = []
                        break
                    elif type_info.source == "file":
                        dyn_entries = _expand_file_dynamic(str(block_name), block_attrs, library_type)
                        entries.extend(dyn_entries)
                    elif type_info.source == "plex":
                        pass

            has_dynamic = bool(dynamic_cols)
            has_static = bool(entries)
            if not has_static and not has_dynamic:
                continue
            if not has_static and has_dynamic:
                valid_dyn = any(
                    isinstance(b, dict) and str(b.get("type", "")).lower() in AUTO_TYPES.get(library_type, set())
                    for b in dynamic_cols.values()
                )
                if not valid_dyn:
                    continue
                dyn_allowed = False
                for b in dynamic_cols.values():
                    if isinstance(b, dict):
                        b_al = (b.get("template_variables") or {}).get("allowed_libraries")
                        if b_al is None:
                            dyn_allowed = True
                        elif isinstance(b_al, str) and b_al.lower() == library_type:
                            dyn_allowed = True
                        elif isinstance(b_al, dict):
                            if b_al.get("default", "").lower() == library_type:
                                dyn_allowed = True
                            elif any(str(v).lower() == library_type for v in b_al.values()):
                                dyn_allowed = True
                        elif isinstance(b_al, list) and library_type in [str(x).lower() for x in b_al]:
                            dyn_allowed = True
                if not dyn_allowed:
                    continue

            seen_stems.add(name)
            result.append(Category(
                name=name,
                title=title,
                group=folder,
                kind=kind,
                listable=listable,
                reason=reason,
                collections=entries,
            ))

    return result


async def count(
    plex: PlexServer,
    library_key: str,
    library_type: str,
    kometa_root: Path,
    languages: dict[str, str] | None = None,
) -> list[Category]:
    """Categories with dynamic collections expanded and counted against Plex.

    ``languages`` is TMDb's English names (``tmdb_languages.english_names``); without it, language categories
    get a ``count_error`` instead of titles that wouldn't match Kometa's.
    """
    library_type = library_type.lower()
    categories_list = categories(kometa_root, library_type)
    defaults_folder = kometa_root / "defaults" if (kometa_root / "defaults").is_dir() else kometa_root
    folders = [library_type, "both", "chart", "award"]

    for cat in categories_list:
        if not cat.listable:
            continue

        file_path = None
        for folder in folders:
            candidate = defaults_folder / folder / f"{cat.name}.yml"
            if candidate.is_file():
                file_path = candidate
                break
        if not file_path:
            continue

        text = _read(file_path)
        try:
            data = _yaml().load(text) or {}
        except YAMLError:
            continue
        if not isinstance(data, dict):
            continue

        dynamic_cols = data.get("dynamic_collections") or {}
        if not isinstance(dynamic_cols, dict):
            continue

        for block_name, block_attrs in dynamic_cols.items():
            if not isinstance(block_attrs, dict):
                continue
            auto_type = str(block_attrs.get("type", "")).lower()
            type_info = DYNAMIC_TYPE_SOURCES.get(auto_type)
            if not type_info or type_info.source != "plex":
                continue

            title_format = block_attrs.get("title_format")
            key_name_override = {str(k): v for k, v in (block_attrs.get("key_name_override") or {}).items()}
            title_override = {str(k): v for k, v in (block_attrs.get("title_override") or {}).items()}
            remove_prefix = _to_str_list(block_attrs.get("remove_prefix"))
            remove_suffix = _to_str_list(block_attrs.get("remove_suffix"))
            template_vars = block_attrs.get("template_variables") or {}

            og_exclude = [str(x) for x in _to_str_list(block_attrs.get("exclude"))]
            include = [str(x) for x in _to_str_list(block_attrs.get("include"))]
            addons = {str(k): [str(x) for x in _to_str_list(v)] for k, v in (block_attrs.get("addons") or {}).items()}

            exclude = list(og_exclude)
            for k, v in addons.items():
                exclude.extend([y for y in v if y != k and y not in exclude])

            all_keys: dict[str, str] = {}
            auto_list: dict[str, str] = {}
            item_query_tags: dict[str, str] = {}

            if auto_type == "decade" and library_type == "show":
                raw_tags = await plex.tag_values(library_key, "year", library_type)
                decade_years: dict[str, list[str]] = {}
                for title_val, key_val in raw_tags:
                    year_str = str(key_val or title_val)
                    if year_str.isdigit():
                        y = int(year_str)
                        dec = str((y // 10) * 10)
                        decade_years.setdefault(dec, []).append(year_str)
                        all_keys[year_str] = year_str
                for dec, yrs in decade_years.items():
                    addons[dec] = yrs
                    if dec not in exclude and f"{dec}s" not in exclude:
                        auto_list[dec] = f"{dec}s"
                    item_query_tags[dec] = "year"
            else:
                tag_name = type_info.tag or auto_type
                episode = library_type == "show" and auto_type in EPISODE_TYPES
                raw_tags = await plex.tag_values(library_key, tag_name, library_type, episode=episode)
                query_name = f"episode.{tag_name}" if episode else tag_name

                if auto_type in LANGUAGE_TYPES:
                    if languages is None:
                        cat.count_error = NO_LANGUAGE_NAMES
                        continue
                    # meta.py: final_title is TMDb's english_name for the key, else Plex's title.
                    for title_val, key_val in raw_tags:
                        k = str(key_val)
                        final_title = tmdb_languages.kometa_title(languages, k, str(title_val))
                        all_keys[k] = final_title
                        if all(x not in exclude for x in (final_title, str(title_val), k)):
                            auto_list[k] = final_title
                        item_query_tags[k] = query_name
                elif auto_type in ("resolution", "decade"):
                    for title_val, key_val in raw_tags:
                        k = str(key_val)
                        all_keys[k] = title_val
                        if title_val not in exclude and k not in exclude:
                            auto_list[k] = title_val
                        item_query_tags[k] = query_name
                else:
                    for title_val, key_val in raw_tags:
                        t = str(title_val)
                        all_keys[t] = t
                        if t not in exclude:
                            auto_list[t] = t
                        item_query_tags[t] = tag_name

                custom_keys = True
                for add_key, combined_keys in list(addons.items()):
                    if add_key not in all_keys and add_key not in og_exclude:
                        final_keys = [ck for ck in combined_keys if ck in all_keys]
                        if custom_keys and final_keys:
                            if add_key not in auto_list:
                                auto_list[add_key] = add_key
                            addons[add_key] = final_keys
                            item_query_tags[add_key] = query_name

            if include:
                auto_list = {k: v for k, v in auto_list.items() if k in include}

            entries: list[Entry] = []
            for k, v in auto_list.items():
                if not _is_dynamic_key_allowed(k, template_vars, library_type):
                    continue
                col_title = _build_dynamic_title(
                    key=k,
                    value=v,
                    library_type=library_type,
                    auto_type=auto_type,
                    title_format=title_format,
                    key_name_override=key_name_override,
                    title_override=title_override,
                    remove_prefix=remove_prefix,
                    remove_suffix=remove_suffix,
                    template_vars=template_vars,
                )
                entries.append(Entry(block=str(block_name), key=k, kometa_name=col_title, title=col_title))

            if len(entries) > 60:
                cat.collections.extend(entries)
            else:
                kept_entries: list[Entry] = []
                for entry in entries:
                    query_tag = item_query_tags.get(entry.key, type_info.tag or auto_type)
                    keys_to_count = []
                    if entry.key in all_keys:
                        keys_to_count.append(entry.key)
                    if entry.key in addons:
                        keys_to_count.extend([a for a in addons[entry.key] if a in all_keys and a != entry.key])
                    if not keys_to_count and entry.key in item_query_tags:
                        keys_to_count.append(entry.key)

                    total_items = 0
                    for qk in keys_to_count:
                        cnt = await plex.count_where(library_key, library_type, {query_tag: qk})
                        total_items += cnt

                    if total_items > 0:
                        entry.items = total_items
                        kept_entries.append(entry)

                cat.collections.extend(kept_entries)

    return categories_list
