"""Reading Kometa's config.yml and the files it points to, read-only, for the Libraries pages.

References are resolved the way Kometa 2.5.3 resolves them (modules/util.py load_files,
modules/meta.py): ``file`` paths are relative to Kometa's working directory, ``folder`` means
every .yml/.yaml in it, ``default`` names a file in Kometa's own defaults folder, and ``url``,
``git`` and ``repo`` are remote, so Studio lists them without fetching them.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

FILE_LISTS = ("collection_files", "overlay_files", "metadata_files")
REFERENCE_KINDS = ("default", "pmm", "file", "folder", "url", "git", "repo")
# Library keys shown on their own tabs or in the file lists; everything else is a library setting.
LIBRARY_SECTIONS = {*FILE_LISTS, "metadata_path", "overlay_path", "operations", "template_variables"}

# Builder keys start with the source they come from (Kometa's modules/*.py `builders` lists).
BUILDER_SOURCES = (
    "anidb anilist flicklist floppy icheckmovies imdb letterboxd mal mdblist mojo plex radarr reciperr "
    "serializd sonarr stevenlu tautulli tmdb trakt tvdb wetrakr"
).split()
SMART_BUILDERS = {"smart_filter", "smart_label"}

BANNER_URL = re.compile(r"https?://kometa\.wiki/\S+")


def _yaml() -> YAML:
    return YAML(typ="safe", pure=True)


def load_yaml(path: Path) -> Any:
    return _yaml().load(path.read_text(encoding="utf-8"))


@dataclass
class Reference:
    """One entry of a library's collection_files / overlay_files / metadata_files (or playlist_files)."""

    kind: str  # default, file, folder, url, git, repo
    value: str
    template_variables: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)  # schedule, asset_directory, ...
    files: list["FileSummary"] = field(default_factory=list)  # what Studio could read locally
    error: str | None = None


@dataclass
class FileSummary:
    path: str
    title: str | None = None  # a default's own title, from its header
    docs_url: str | None = None
    collections: list[dict] = field(default_factory=list)
    overlays: list[dict] = field(default_factory=list)
    playlists: list[dict] = field(default_factory=list)
    metadata: int = 0
    templates: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Library:
    name: str
    collection_files: list[Reference]
    overlay_files: list[Reference]
    metadata_files: list[Reference]
    operations: dict
    template_variables: dict
    settings: dict


@dataclass
class KometaConfig:
    path: Path
    libraries: list[Library]
    playlist_files: list[Reference]


class ConfigReader:
    def __init__(self, config_path: Path, kometa_root: Path | None):
        self.config_path = config_path
        # Kometa runs with its install folder as the working directory; `file:` paths are relative to it.
        self.root = kometa_root or config_path.parent.parent
        self.defaults = self.root / "defaults"

    # --- config.yml -------------------------------------------------------------

    def read(self) -> KometaConfig:
        """Raises FileNotFoundError, or ValueError when config.yml can't be used."""
        try:
            data = load_yaml(self.config_path)
        except YAMLError as error:
            raise ValueError(f"config.yml isn't valid YAML: {error}") from None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("config.yml doesn't contain a mapping at the top level")
        libraries = data.get("libraries") or {}
        if not isinstance(libraries, dict):
            raise ValueError("`libraries` in config.yml isn't a mapping")
        return KometaConfig(
            path=self.config_path,
            libraries=[self._library(str(name), body or {}) for name, body in libraries.items()],
            playlist_files=self._references(data.get("playlist_files"), overlay=False),
        )

    def _library(self, name: str, body: Any) -> Library:
        if not isinstance(body, dict):
            body = {}
        # Old names Kometa still accepts (modules/config.py).
        collection_files = body.get("collection_files", body.get("metadata_path"))
        overlay_files = body.get("overlay_files", body.get("overlay_path"))
        metadata_files = body.get("metadata_files", body.get("metadata_path"))
        operations = body.get("operations")
        template_variables = body.get("template_variables")
        return Library(
            name=name,
            collection_files=self._references(collection_files, overlay=False),
            overlay_files=self._references(overlay_files, overlay=True),
            metadata_files=self._references(metadata_files, overlay=False, defaults_allowed=False),
            operations=operations if isinstance(operations, dict) else {},
            template_variables=template_variables if isinstance(template_variables, dict) else {},
            settings={key: value for key, value in body.items() if key not in LIBRARY_SECTIONS},
        )

    # --- references -------------------------------------------------------------

    def _references(self, entries: Any, *, overlay: bool, defaults_allowed: bool = True) -> list[Reference]:
        if entries is None:
            return []
        if not isinstance(entries, list):
            entries = [entries]
        references = []
        for entry in entries:
            if isinstance(entry, str):  # a bare path, as older configs had
                entry = {"file": entry}
            if not isinstance(entry, dict):
                references.append(Reference("unknown", str(entry), error="Kometa expects each entry to be a mapping like `- file: …`"))
                continue
            kinds = [kind for kind in REFERENCE_KINDS if kind in entry]
            if not kinds:
                references.append(Reference("unknown", str(entry), error="No file, folder, default, url, git or repo in this entry"))
                continue
            kind = "default" if kinds[0] == "pmm" else kinds[0]
            value = str(entry[kinds[0]] or "")
            reference = Reference(
                kind,
                value,
                template_variables=entry.get("template_variables") if isinstance(entry.get("template_variables"), dict) else {},
                options={key: entry[key] for key in entry if key not in (*REFERENCE_KINDS, "template_variables")},
            )
            if kind == "git" and value.startswith("PMM/"):  # Kometa treats these as defaults
                reference.kind, reference.value = "default", value[4:]
            if reference.kind == "default" and not defaults_allowed:
                reference.error = "metadata_files can't use Kometa's defaults"
            elif not value:
                reference.error = f"`{kinds[0]}` is blank"
            else:
                self._load(reference, overlay)
            references.append(reference)
        return references

    def _load(self, reference: Reference, overlay: bool) -> None:
        if reference.kind in ("url", "git", "repo"):
            return  # remote: listed, not fetched
        if reference.kind == "folder":
            folder = self._local(reference.value)
            if not folder.is_dir():
                reference.error = f"Folder not found: {folder}"
                return
            paths = sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")])
            if not paths:
                reference.error = f"No .yml or .yaml files in {folder}"
            reference.files = [self.summarise(path) for path in paths]
            return
        path = self._default(reference.value, overlay) if reference.kind == "default" else self._local(reference.value)
        if path is None or not path.is_file():
            reference.error = f"Not found: {path or reference.value}"
            return
        reference.files = [self.summarise(path, default=reference.kind == "default")]

    def _local(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def _default(self, name: str, overlay: bool) -> Path | None:
        """Where Kometa finds `default: name` (modules/meta.py). Without Plex, Studio can't know a library's type, so it tries each folder."""
        if not name.endswith((".yml", ".yaml")):
            name = f"{name}.yml"
        if overlay:
            name = name.removeprefix("overlays/")
            candidates = [self.defaults / "overlays" / name]
        else:
            for prefix in ("movie/", "chart/", "award/", "show/", "both/"):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            candidates = [self.defaults / name] + [self.defaults / folder / name for folder in ("movie", "show", "both", "chart", "award")]
        return next((path for path in candidates if path.is_file()), None)

    # --- one YAML file ------------------------------------------------------------

    def display_path(self, path: Path) -> str:
        for base in (self.config_path.parent, self.root):
            try:
                return str(path.relative_to(base))
            except ValueError:
                continue
        return str(path)

    def summarise(self, path: Path, default: bool = False) -> FileSummary:
        summary = FileSummary(self.display_path(path))
        try:
            text = path.read_text(encoding="utf-8")
            data = _yaml().load(text) or {}
        except (OSError, YAMLError) as error:
            summary.error = f"Can't read {summary.path}: {error}"
            return summary
        if default:
            summary.title, summary.docs_url = _banner(text)
        if not isinstance(data, dict):
            summary.error = f"{summary.path} doesn't contain a mapping at the top level"
            return summary
        for key, dynamic in (("collections", False), ("dynamic_collections", True)):
            for name, body in _mapping(data.get(key)).items():
                summary.collections.append(_collection(str(name), body, dynamic))
        summary.overlays = [_overlay(str(name), body) for name, body in _mapping(data.get("overlays")).items()]
        summary.playlists = [{"name": str(name), "libraries": _mapping(body).get("libraries")} for name, body in _mapping(data.get("playlists")).items()]
        summary.metadata = len(_mapping(data.get("metadata")))
        summary.templates = [str(name) for name in _mapping(data.get("templates"))]
        return summary


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _banner(text: str) -> tuple[str | None, str | None]:
    """A default's title and wiki link, from the ### banner at its top."""
    title = None
    url = None
    for line in text.splitlines()[:8]:
        if not line.startswith("#"):
            break
        content = line.strip("#").strip()
        if match := BANNER_URL.search(content):
            url = match.group(0)
        elif content and title is None and "EDITING THIS FILE" not in content and not content.lower().startswith("created by"):
            title = content
    return title, url


def _is_builder(key: str) -> bool:
    return key in SMART_BUILDERS or key.split("_", 1)[0] in BUILDER_SOURCES and "_" in key


def _collection(name: str, body: Any, dynamic: bool) -> dict:
    body = _mapping(body)
    templates = body.get("template")
    if isinstance(templates, dict):
        templates = [templates]
    template_names = [str(t.get("name")) if isinstance(t, dict) else str(t) for t in (templates or []) if t]
    return {
        "name": name,
        "dynamic": dynamic,
        "type": str(body["type"]) if dynamic and "type" in body else None,
        "builders": [key for key in body if _is_builder(str(key))],
        "templates": template_names,
        "sync_mode": body.get("sync_mode"),
        "schedule": body.get("schedule"),
    }


def _overlay(name: str, body: Any) -> dict:
    body = _mapping(body)
    overlay = body.get("overlay")
    overlay = overlay if isinstance(overlay, dict) else {"name": overlay} if overlay else {}
    templates = body.get("template")
    if isinstance(templates, dict):
        templates = [templates]
    return {
        "name": name,
        "overlay": str(overlay.get("name")) if overlay.get("name") is not None else None,
        "position": {key: overlay[key] for key in ("horizontal_align", "vertical_align", "horizontal_offset", "vertical_offset") if key in overlay},
        "builders": [key for key in body if _is_builder(str(key))],
        "templates": [str(t.get("name")) if isinstance(t, dict) else str(t) for t in (templates or []) if t],
    }


# --- Showing raw files --------------------------------------------------------------

SECRET_KEYS = re.compile(
    r"^(?P<key>\s*-?\s*(?:token|apikey|api_key|password|client_secret|client_id|access_token|refresh_token|secret|pin|session)\s*:\s*)"
    r"(?P<value>[^#\s][^#]*?)(?P<rest>\s+#.*)?$",
    re.IGNORECASE,
)
SECRET_URL_PARTS = [
    (re.compile(r"([?&](?:token|apikey|api_key|key)=)[^&\s#]+", re.IGNORECASE), r"\1••••"),
    (re.compile(r"(https://(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services)/)\S+"), r"\1••••"),
]


def mask_secrets(text: str) -> str:
    """Hide tokens, API keys and passwords before a file is shown in the browser."""
    lines = []
    for line in text.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        body = line[: len(line) - len(ending)]
        match = SECRET_KEYS.match(body)
        if match:
            body = f"{match['key']}••••{match['rest'] or ''}"
        for pattern, replacement in SECRET_URL_PARTS:
            body = pattern.sub(replacement, body)
        lines.append(body + ending)
    return "".join(lines)
