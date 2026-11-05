"""Building Kometa command lines (handoff v2 §5.1), and learning which flags the installed Kometa has."""

import asyncio
import re
import shlex
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Every run is one pass that exits (Studio is the scheduler), never prompts, and leaves config.yml to Studio.
ALWAYS = ["--run", "--no-countdown", "--read-only-config", "--ignore-ghost"]

MODES = {
    "all": None,
    "collections": "--collections-only",
    "overlays": "--overlays-only",
    "operations": "--operations-only",
    "metadata": "--metadata-only",
    "playlists": "--playlists-only",
}

Mode = Literal["all", "collections", "overlays", "operations", "metadata", "playlists"]


class RunRequest(BaseModel):
    """What a run should do. Deliberately no free-form flags: the UI can't ask for
    --delete-collections, --delete-labels, --log-requests or --times (handoff v2 §5.1)."""

    mode: Mode = "all"
    libraries: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    ignore_schedules: bool = False
    no_missing: bool = False
    tests: bool = False
    timings: bool = False  # never passed on (Kometa 2.5.3 crashes on --timings; see usage.py), kept so stored requests load
    low_priority: bool = True

    @field_validator("libraries", "collections", "files")
    @classmethod
    def clean_names(cls, names: list[str]) -> list[str]:
        cleaned = [name.strip() for name in names if name.strip()]
        for name in cleaned:
            if "|" in name:
                raise ValueError(f"Names can't contain '|' (Kometa uses it to separate them): {name}")
        return cleaned


class UnsupportedFlag(ValueError):
    pass


def build_command(
    python: Path,
    entry: Path,
    config: Path,
    request: RunRequest,
    supported: set[str] | None = None,
) -> list[str]:
    """The argv for one Kometa run. ``supported`` is the flag set from ``--help``; None skips the check."""
    flags = list(ALWAYS)
    if mode_flag := MODES[request.mode]:
        flags.append(mode_flag)
    for flag, names in (
        ("--run-libraries", request.libraries),
        ("--run-collections", request.collections),
        ("--run-files", request.files),
    ):
        if names:
            flags += [flag, "|".join(names)]
    for flag, wanted in (
        ("--ignore-schedules", request.ignore_schedules),
        ("--no-missing", request.no_missing),
        ("--tests", request.tests),
        ("--low-priority", request.low_priority),
    ):
        if wanted:
            flags.append(flag)

    if supported is not None:
        missing = [f for f in flags if f.startswith("--") and f not in supported]
        if missing:
            raise UnsupportedFlag(f"This Kometa doesn't support {', '.join(missing)}")
    return [str(python), str(entry), "--config", str(config), *flags]


def display(argv: list[str]) -> str:
    return shlex.join(argv)


FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def parse_help(text: str) -> set[str]:
    """The long flags listed in ``kometa.py --help`` output."""
    return set(FLAG.findall(text))


async def probe_flags(python: Path, entry: Path, timeout: float = 60) -> set[str]:
    """Run ``kometa.py --help`` and return its flags. Raises RuntimeError if it doesn't work."""
    try:
        process = await asyncio.create_subprocess_exec(
            str(python),
            str(entry),
            "--help",
            cwd=entry.parent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as error:
        raise RuntimeError(f"Can't start Kometa: {error}") from None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError) as error:
        try:
            process.kill()
        except ProcessLookupError:
            pass  # it finished on its own just as it was stopped
        await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise RuntimeError(f"kometa.py --help didn't finish within {timeout:g} s") from None
    flags = parse_help(output.decode(errors="replace"))
    if process.returncode != 0 or "--run" not in flags:
        raise RuntimeError(f"kometa.py --help failed (exit {process.returncode})")
    return flags
