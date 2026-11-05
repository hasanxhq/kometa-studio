from pathlib import Path

import pytest
from pydantic import ValidationError

from starr_studio.kometa_command import ALWAYS, RunRequest, UnsupportedFlag, build_command, installed_version, parse_help, timings_work

PY, ENTRY, CONFIG = Path("/.venv/bin/python3"), Path("/kometa.py"), Path("/config/config.yml")
HELP = """usage: kometa.py [-h] [--config CONFIG] [--times TIMES] [--run] [--collections-only] [--overlays-only]
  --run-libraries RUN_LIBRARIES, -rl RUN_LIBRARIES, --library RUN_LIBRARIES
                        Process only specified libraries (pipe-separated list '|')
  --no-countdown, -nc   Run without displaying the countdown
  --read-only-config, -ro
  --ignore-ghost, -ig   Run ignoring ghost logging
  --source-integrity, --no-source-integrity, -si
"""


def test_a_default_run():
    assert build_command(PY, ENTRY, CONFIG, RunRequest()) == [
        "/.venv/bin/python3",
        "/kometa.py",
        "--config",
        "/config/config.yml",
        *ALWAYS,
        "--low-priority",
    ]


def test_collections_only_for_two_libraries():
    argv = build_command(PY, ENTRY, CONFIG, RunRequest(mode="collections", libraries=["Movies", " TV Shows "], low_priority=False))
    assert argv[4:] == [*ALWAYS, "--collections-only", "--run-libraries", "Movies|TV Shows"]


def test_every_option():
    request = RunRequest(
        mode="overlays",
        libraries=["Movies"],
        collections=["Trending"],
        files=["config/Movies.yml"],
        ignore_schedules=True,
        no_missing=True,
        tests=True,
        timings=True,
    )
    assert build_command(PY, ENTRY, CONFIG, request)[4 + len(ALWAYS) :] == [
        "--overlays-only",
        "--run-libraries",
        "Movies",
        "--run-collections",
        "Trending",
        "--run-files",
        "config/Movies.yml",
        "--ignore-schedules",
        "--no-missing",
        "--tests",
        "--timings",
        "--low-priority",
    ]


def test_flags_the_installed_kometa_lacks_are_refused():
    supported = parse_help(HELP)
    build_command(PY, ENTRY, CONFIG, RunRequest(mode="collections", low_priority=False), supported)
    with pytest.raises(UnsupportedFlag, match="--low-priority"):
        build_command(PY, ENTRY, CONFIG, RunRequest(), supported)


def test_help_parsing():
    flags = parse_help(HELP)
    assert {"--run", "--run-libraries", "--library", "--no-source-integrity", "--read-only-config"} <= flags
    assert "-rl" not in flags  # short options aren't used


def test_names_with_a_pipe_are_refused():
    with pytest.raises(ValidationError, match="can't contain"):
        RunRequest(libraries=["Movies|TV"])


def test_unknown_modes_are_refused():
    with pytest.raises(ValidationError):
        RunRequest(mode="delete-collections")


@pytest.mark.parametrize(
    ("version", "works"),
    [
        ("2.5.4", True),
        ("2.5.4\n", True),
        ("2.5.4-build2", True),
        ("2.5.10", True),
        ("2.6.0", True),
        ("3.0.0", True),
        ("2.5.3", False),  # crashes on --timings at startup (Kometa-Team/Kometa#3719)
        ("2.5.3-build9", False),
        ("2.4.1", False),
        ("1.21.0", False),
        ("nightly", False),
        ("", False),
        (None, False),
    ],
)
def test_timings_work_from_kometa_2_5_4(version, works):
    assert timings_work(version) is works


def test_installed_version_reads_the_version_file_beside_kometa_py(tmp_path):
    entry = tmp_path / "kometa.py"
    assert installed_version(entry) is None
    (tmp_path / "VERSION").write_text("2.5.4\n")
    assert installed_version(entry) == "2.5.4"
