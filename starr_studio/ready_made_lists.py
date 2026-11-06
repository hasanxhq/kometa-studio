"""The lists a ready-made chart collection reads, worked out from its default file, for Ready-made's preview.

A chart default names its builder through a template in the same file. defaults/chart/tmdb.yml, for instance::

    templates:
      tmdb:
        default: {limit: 100, limit_<<key>>: <<limit>>, chart: <<key>>}
        tmdb_<<chart>>: <<limit_<<key>>>>
    collections:
      TMDb Top Rated:
        variables: {key: top}
        template: [{name: tmdb, chart: top_rated}, {name: shared}]

Kometa fills a template's placeholders from its ``default`` values, then the collection's ``variables``, then the
template call's own values, and resolves inner placeholders first (``<<limit_<<key>>>>``). Studio does the same, and
keeps the builders it knows as list sources (``tmdb_top_rated: 100``). Templates from Kometa's shared templates file
(``shared``, ``arr``, ``custom`` …) never name a list, so only the file's own templates are read.
"""

from pathlib import Path
from typing import Any

from starr_studio import list_sources
from starr_studio.ready_made_posters import _default_file, _load

ROUNDS = 6  # nested placeholders resolve one level per round; Kometa's defaults nest two deep


def _sub(text: str, values: dict[str, str]) -> str:
    for _ in range(ROUNDS):
        before = text
        for name, value in values.items():
            text = text.replace(f"<<{name}>>", value)
        if text == before:
            break
    return text


def _resolve(values: dict[str, Any]) -> dict[str, str]:
    """Values with placeholders in their names and values filled in from each other, as far as they go."""
    out = {str(k): str(v) for k, v in values.items() if not isinstance(v, (dict, list))}
    for _ in range(ROUNDS):
        changed = False
        resolved: dict[str, str] = {}
        for name, value in out.items():
            new_name, new_value = _sub(name, out), _sub(value, out)
            changed |= new_name != name or new_value != value
            resolved[new_name] = new_value
        out = resolved
        if not changed:
            break
    return out


def _calls(template: Any) -> list[tuple[str, dict]]:
    """A collection's ``template`` as (name, the call's own values)."""
    entries = template if isinstance(template, list) else [template]
    calls = []
    for entry in entries:
        if isinstance(entry, str):
            calls.append((entry, {}))
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            calls.append((entry["name"], {k: v for k, v in entry.items() if k != "name"}))
    return calls


def sources(kometa_root: Path, library_type: str, category: str, key: str) -> list[dict]:
    """The list sources (builder definitions) a static ready-made collection reads, or [] when it names none Studio knows."""
    path = _default_file(kometa_root, library_type, category)
    if path is None:
        return []
    data = _load(path)
    statics = data.get("collections") if isinstance(data.get("collections"), dict) else {}
    attrs = statics.get(key)
    templates = data.get("templates") if isinstance(data.get("templates"), dict) else {}
    if not isinstance(attrs, dict) or not templates:
        return []
    variables = attrs.get("variables") if isinstance(attrs.get("variables"), dict) else {}
    out: list[dict] = []
    for name, own in _calls(attrs.get("template")):
        body = templates.get(name)
        if not isinstance(body, dict):
            continue
        defaults = body.get("default") if isinstance(body.get("default"), dict) else {}
        values = _resolve(
            {
                "key": key,
                "mapping_name": key,
                "library_type": library_type,
                "library_typeU": library_type.capitalize(),
                **defaults,
                **variables,
                **own,
            }
        )
        for raw_builder, raw_value in body.items():
            if raw_builder in ("default", "optional", "conditionals") or isinstance(raw_value, (dict, list)):
                continue
            builder, value = _sub(str(raw_builder), values), _sub(str(raw_value), values)
            if "<<" in builder or "<<" in value or builder not in list_sources.BY_BUILDER:
                continue
            out.append({"kind": "list", "builder": builder, "value": value, "label": key})
    return out
