"""Saving Kometa's YAML files safely (handoff v2 §7.3–7.4).

A save is all or nothing:
1. Every file must be unchanged on disk since the browser read it (hash), or the save is refused.
2. Hidden secrets (••••(n)) are put back, and each file must parse as YAML.
3. Kometa checks the result in a sandbox: a mirror of the config folder with the edited files
   written in and everything else linked, and the webhooks section removed so a draft never
   notifies anyone. config.yml and the files it references get `--validate --validate-level
   structure --validate-schema`; edited files get `--validate-dir` too, which covers files
   config.yml doesn't reference yet (an upload, say).
4. Studio's own guard (``guard``: Maintainerr's collections) mustn't find a problem the files didn't have.
5. Only then are the current versions backed up and the new ones written, atomically.

Only the files that were edited are ever written.
"""

import asyncio
import hashlib
import io
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from . import backups
from .config_items import ItemProblem, apply_item
from .kometa_config import write_atomic
from .kometa_files import mask_secrets, unmask_secrets
from .settings import Settings

VALIDATE_TIMEOUT = 180.0
FULL_CHECK_TIMEOUT = 600.0
YAML_SUFFIXES = (".yml", ".yaml")


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Edit:
    path: str  # relative to the config folder
    text: str
    base_hash: str | None  # None: a new file, which must not exist yet


@dataclass
class Validation:
    ok: bool
    errors: list[str] = field(default_factory=list)  # problems this change would introduce
    warnings: list[str] = field(default_factory=list)
    existing_errors: list[str] = field(default_factory=list)  # problems the files already had; they don't block a save
    checked_by_kometa: bool = True
    crashed: bool = False  # Kometa's check didn't produce a verdict; never treated as "already there"
    output: str = ""  # the end of Kometa's output, for when the report doesn't say enough


class SaveRefused(Exception):
    def __init__(self, status: int, message: str, validation: Validation | None = None, path: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.validation = validation
        self.path = path

    def detail(self) -> dict:
        return {"message": self.message, "path": self.path, "validation": asdict(self.validation) if self.validation else None}


def parse_report(output: str) -> tuple[list[str], list[str]]:
    """Kometa's validation report: the lines under `Errors (n):` and `Warnings (n):`.

    The `--validate-dir` report names each file first (`File: …`), so its errors are prefixed
    with the file. A separator line (`|====…|`) ends a section.
    """
    errors: list[str] = []
    warnings: list[str] = []
    section: list[str] | None = None
    current_file: str | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            line = line[1:-1].strip()  # Kometa's console border
        if not line:
            continue
        if line.startswith("="):
            section, current_file = None, None
        elif line.startswith("File: "):
            section, current_file = None, line.removeprefix("File: ")
        elif line.startswith("Errors (") and line.endswith("):"):
            section = errors
        elif line.startswith("Warnings (") and line.endswith("):"):
            section = warnings
        elif section is not None:
            section.append(f"{current_file}: {line}" if current_file and section is errors else line)
    return errors, warnings


class ConfigWriter:
    def __init__(self, settings: Settings):
        if settings.kometa_config is None:
            raise SaveRefused(409, "Studio doesn't know where Kometa's config.yml is. Set STUDIO_KOMETA_CONFIG.")
        self.settings = settings
        self.config_path = settings.kometa_config
        self.config_dir = settings.kometa_config.parent
        self.data_dir = settings.data_dir
        self.backup_root = settings.data_dir / "backups"
        self.root = settings.kometa_entry.parent if settings.kometa_entry else self.config_dir.parent
        self.lock = asyncio.Lock()
        # Studio's own rules on top of Kometa's check: (config.yml path, Kometa's folder) → problems.
        # A save is refused only for problems it adds. Set by the Maintainerr integration.
        self.guard: Callable[[Path, Path], list[str]] | None = None

    # --- Which files ----------------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """An editable file: .yml/.yaml under the config folder, never in Studio's data or Kometa's logs."""
        path = (self.config_dir / relative).resolve()
        config_dir = self.config_dir.resolve()
        if (
            path.suffix not in YAML_SUFFIXES
            or not path.is_relative_to(config_dir)
            or path.is_relative_to(self.data_dir.resolve())
            or path.is_relative_to(config_dir / "logs")
            or path == config_dir
        ):
            raise SaveRefused(403, f"Studio only edits .yml files inside Kometa's config folder: {relative}", path=relative)
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.config_dir.resolve()).as_posix()

    def read(self, relative: str) -> dict:
        path = self.resolve(relative)
        if not path.is_file():
            raise SaveRefused(404, f"{relative} doesn't exist", path=relative)
        data = path.read_bytes()
        try:
            masked, secrets = mask_secrets(data.decode("utf-8"))
        except UnicodeDecodeError:
            raise SaveRefused(422, f"{relative} isn't UTF-8 text", path=relative) from None
        return {"path": self.relative(path), "text": masked, "hash": file_hash(data), "hidden": len(secrets)}

    # --- Preparing a save -----------------------------------------------------------

    def _prepare(self, edits: list[Edit]) -> dict[Path, str]:
        """Check hashes, put secrets back and parse each file. Returns the new text per path."""
        if not edits:
            raise SaveRefused(422, "Nothing to save")
        prepared: dict[Path, str] = {}
        for edit in edits:
            path = self.resolve(edit.path)
            if path in prepared:
                raise SaveRefused(422, f"{edit.path} is in this save twice", path=edit.path)
            current = path.read_bytes() if path.exists() else None
            if edit.base_hash is None and current is not None:
                raise SaveRefused(409, f"{edit.path} already exists. Open it to change it, or choose another name.", path=edit.path)
            if edit.base_hash is not None and (current is None or file_hash(current) != edit.base_hash):
                raise SaveRefused(
                    409, f"{edit.path} changed on disk since you opened it. Reload it to see the new version.", path=edit.path
                )
            secrets = mask_secrets(current.decode("utf-8"))[1] if current is not None else []
            try:
                text = unmask_secrets(edit.text, secrets)
            except ValueError as error:
                raise SaveRefused(422, f"{edit.path}: {error}", path=edit.path) from None
            syntax = yaml_problem(text)
            if syntax:
                raise SaveRefused(422, f"{edit.path}: {syntax}", Validation(False, [f"{edit.path}: {syntax}"], checked_by_kometa=False), edit.path)
            prepared[path] = text
        return prepared

    # --- Kometa's check ---------------------------------------------------------------

    def _kometa_ready(self) -> bool:
        s = self.settings
        return s.kometa_python is not None and s.kometa_entry is not None and s.kometa_entry.exists()

    async def validate(self, changes: dict[Path, str], level: str = "structure") -> Validation:
        """Kometa's verdict on ``changes``: refused only for problems the change introduces.

        The files are checked before and after the change; errors that were already there are
        reported separately and don't block the save, so an incomplete config can be built up a
        step at a time. A check that crashed is never counted as "already there".
        """
        if not self._kometa_ready():
            return Validation(True, warnings=["Kometa isn't installed where Studio expects it, so only the YAML syntax was checked."], checked_by_kometa=False)
        if not changes or level != "structure":
            return await self._check(changes, level)
        config_path = self.config_path.resolve()
        current = {path: path.read_text(encoding="utf-8") for path in changes if path != config_path and path.exists()}
        before, after = await asyncio.gather(self._check({}, level, current), self._check(changes, level))
        if after.crashed:
            return after
        new = [e for e in after.errors if e not in before.errors or before.crashed]
        existing = [e for e in after.errors if e not in new]
        return Validation(not new and (after.ok or bool(existing)), new, after.warnings, existing, output=after.output)

    async def _check(self, changes: dict[Path, str], level: str, per_file: dict[Path, str] | None = None) -> Validation:
        """One sandboxed check: config.yml and its files, plus ``per_file`` (default: the changed files) on their own."""
        config_path = self.config_path.resolve()
        if per_file is None:
            per_file = {path: text for path, text in changes.items() if path != config_path}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="validate-", dir=self.data_dir) as temp:
            sandbox = Path(temp)
            mirror_config = self._mirror(sandbox, changes)
            base = ["--config", str(mirror_config), "--no-source-integrity", "--read-only-config", "--width", "300"]
            if self.settings.kometa_schemas is not None:
                base += ["--schema-path", str(self.settings.kometa_schemas)]
            checks = [self._kometa([*base, "--validate", "--validate-level", level, "--validate-schema"], sandbox, level)]
            if per_file and level == "structure":
                staged = sandbox / "_edited"
                staged.mkdir()
                for path, text in per_file.items():
                    (staged / path.name).write_text(text, encoding="utf-8")
                checks.append(self._kometa([*base, "--validate-dir", str(staged)], sandbox, level))
            results = await asyncio.gather(*checks)
        merged = Validation(all(r.ok for r in results), crashed=any(r.crashed for r in results))
        for result in results:
            merged.errors += [e for e in result.errors if e not in merged.errors]
            merged.warnings += [w for w in result.warnings if w not in merged.warnings]
        merged.output = "\n".join(r.output for r in results if not r.ok)[-6000:]
        return _readable(merged, sandbox, self.config_dir)

    def _mirror(self, sandbox: Path, changes: dict[Path, str]) -> Path:
        """The config folder inside ``sandbox``, where Kometa resolves `file: config/…` from its working directory."""
        config_dir = self.config_dir.resolve()
        try:
            place = config_dir.relative_to(self.root.resolve())
        except ValueError:
            place = Path(config_dir.name)
        mirror = sandbox / place
        changed = dict(changes)
        config_path = self.config_path.resolve()
        config_text = changed.pop(config_path, None)
        if config_text is None and config_path.exists():
            config_text = config_path.read_text(encoding="utf-8")
        skip = {self.data_dir.resolve(), (config_dir / "logs").resolve()}
        self._link_tree(config_dir, mirror, set(changed) | {config_path}, skip)
        for path, text in changed.items():
            target = mirror / path.relative_to(config_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            target.write_text(text, encoding="utf-8")
        (mirror / config_path.name).write_text(without_webhooks(config_text or ""), encoding="utf-8")
        return mirror / config_path.name

    def _link_tree(self, source: Path, target: Path, replaced: set[Path], skip: set[Path]) -> None:
        """Link everything under ``source`` into ``target``, descending only into folders that hold replaced files."""
        target.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            resolved = entry.resolve()
            if resolved in skip or resolved in replaced:
                continue
            if entry.is_dir() and any(path.is_relative_to(resolved) for path in replaced):
                self._link_tree(entry, target / entry.name, replaced, skip)
            else:
                (target / entry.name).symlink_to(resolved, target_is_directory=entry.is_dir())

    async def _kometa(self, args: list[str], cwd: Path, level: str) -> Validation:
        timeout = FULL_CHECK_TIMEOUT if level == "full" else VALIDATE_TIMEOUT
        assert self.settings.kometa_python and self.settings.kometa_entry
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.settings.kometa_python),
                str(self.settings.kometa_entry),
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=os.environ | {"PYTHONUNBUFFERED": "1"},
            )
        except OSError as error:
            return Validation(False, [f"Can't start Kometa to check the files: {error}"], crashed=True)
        try:
            raw, _ = await asyncio.wait_for(process.communicate(), timeout)
        except (TimeoutError, asyncio.CancelledError) as error:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # it finished on its own just as it was stopped
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            return Validation(False, [f"Kometa's check didn't finish within {timeout:g} s"], crashed=True)
        output = raw.decode("utf-8", errors="replace")
        errors, warnings = parse_report(output)
        ok = process.returncode == 0
        crashed = not ok and not errors
        if crashed:
            errors = ["Kometa's check failed without a report; its output is below."]
        return Validation(ok, errors, warnings, crashed=crashed, output="\n".join(output.splitlines()[-60:]))

    # --- Saving -----------------------------------------------------------------------

    async def check(self, edits: list[Edit]) -> Validation:
        """Kometa's verdict on edits, without saving anything."""
        try:
            changes = self._prepare(edits)
        except SaveRefused as refused:
            if refused.validation is not None:
                return refused.validation
            raise
        return await self.validate(changes)

    async def save(self, edits: list[Edit], reason: str) -> dict:
        async with self.lock:  # one save at a time, so hashes can't go stale between check and write
            changes = self._prepare(edits)
            validation = await self.validate(changes)
            if not validation.ok:
                raise SaveRefused(422, "Kometa found problems, so nothing was saved.", validation)
            added = self._guarded(changes)
            if added:
                raise SaveRefused(
                    422, "This would let Kometa touch Maintainerr's collections, so nothing was saved.", Validation(False, added, checked_by_kometa=False)
                )
            # Hashes again: a file may have changed while Kometa was checking.
            self._prepare(edits)
            backup = backups.take_backup(self.backup_root, self.config_dir.resolve(), list(changes), reason)
            for path, text in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(path, text)
        return {
            "backup": backup.name,
            "files": [{"path": self.relative(path), "hash": file_hash(path.read_bytes())} for path in changes],
            "validation": asdict(validation),
        }

    def _guarded(self, changes: dict[Path, str]) -> list[str]:
        """Problems ``guard`` finds with the changes that it doesn't find in the files as they are."""
        if self.guard is None:
            return []
        before = self.guard(self.config_path, self.root)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="guard-", dir=self.data_dir) as temp:
            after = self.guard(self._mirror(Path(temp), changes), Path(temp))
        return [problem for problem in after if problem not in before]

    async def edit_item(
        self,
        relative: str,
        base_hash: str,
        section: str,
        name: str,
        value: dict | None,
        *,
        create: bool,
        rename: str | None,
        reason: str,
    ) -> dict:
        """Change one collection, overlay or template in a file, then save it like any edit (checked and backed up)."""
        path = self.resolve(relative)
        if path == self.config_path.resolve():
            raise SaveRefused(422, "config.yml is edited as a whole file", path=relative)
        if not path.is_file():
            raise SaveRefused(404, f"{relative} doesn't exist", path=relative)
        current = path.read_bytes()
        if file_hash(current) != base_hash:
            raise SaveRefused(409, f"{relative} changed on disk since you opened it. Reload it to see the new version.", path=relative)
        try:
            text = apply_item(current.decode("utf-8"), section, name, value, create=create, rename=rename)
        except ItemProblem as problem:
            raise SaveRefused(problem.status, problem.message, path=relative) from None
        return await self.save([Edit(relative, text, base_hash)], reason)

    async def restore(self, backup_id: str) -> dict:
        """Put a backup's files back. Always allowed: it's the way out. The current files are backed up first."""
        async with self.lock:
            folder = backups.backup_folder(self.backup_root, backup_id)
            if folder is None:
                raise SaveRefused(404, "No such backup")
            entry = next(b for b in backups.list_backups(self.backup_root) if b["id"] == backup_id)
            restored = [self.resolve(relative) for relative in entry["files"]]
            removed = [self.resolve(relative) for relative in entry["new_files"]]
            before = backups.take_backup(self.backup_root, self.config_dir.resolve(), restored + removed, f"Before restoring the backup from {entry['created']}")
            for path in restored:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(path, (folder / self.relative(path)).read_text(encoding="utf-8"))
            for path in removed:
                path.unlink(missing_ok=True)
        validation = await self.validate({})
        return {
            "backup": before.name,
            "restored": [self.relative(p) for p in restored],
            "removed": [self.relative(p) for p in removed],
            "validation": asdict(validation),
        }

    async def full_check(self) -> Validation:
        """Tier 3: Kometa connects to Plex and every service in config.yml, and changes nothing."""
        return await self.validate({}, level="full")


def yaml_problem(text: str) -> str | None:
    """Why ``text`` isn't valid YAML, with the line, or None."""
    try:
        YAML().load(text)
    except MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        return f"YAML error at {where}{error.problem or error.context}"
    except YAMLError as error:
        return f"YAML error: {error}"
    return None


def without_webhooks(text: str) -> str:
    """config.yml for the sandbox: no webhooks, globally or per library, so checking never notifies anyone."""
    yaml = YAML()
    try:
        document = yaml.load(text)
    except YAMLError:
        return text
    if not isinstance(document, dict):
        return text
    document.pop("webhooks", None)
    libraries = document.get("libraries")
    if isinstance(libraries, dict):
        for library in libraries.values():
            if isinstance(library, dict):
                library.pop("webhooks", None)
    buffer = io.StringIO()
    yaml.dump(document, buffer)
    return buffer.getvalue()


def _readable(validation: Validation, sandbox: Path, config_dir: Path) -> Validation:
    """Kometa names files by their sandbox paths; show them relative to the config folder."""

    def tidy(message: str) -> str:
        for prefix in (str(sandbox / "_edited") + os.sep, str(sandbox) + os.sep):
            message = message.replace(prefix, "")
        return message.replace(str(config_dir) + os.sep, "")

    validation.errors = [tidy(e) for e in validation.errors]
    validation.warnings = [tidy(w) for w in validation.warnings]
    validation.output = tidy(validation.output)
    return validation
