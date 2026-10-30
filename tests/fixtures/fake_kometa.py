"""Stands in for kometa.py in tests.

``--help`` prints a flag list like Kometa 2.5.3's. Otherwise it reads ``fake.json`` next to
the --config file and does what that says:

    lines        lines to print
    exit         exit code (default 0)
    wait_for     a path: block until it exists, then print ``after`` lines
    after        lines to print once wait_for exists
    ignore_term  ignore SIGTERM, so only SIGKILL stops it
    child_pid    a path: start a child process (like Kometa's worker) and write its PID there
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FLAGS = (
    "--config --times --run --tests --debug --trace --log-requests --timings --source-integrity --no-source-integrity "
    "--timeout --no-verify-ssl --collections-only --metadata-only --playlists-only --operations-only --overlays-only "
    "--run-collections --run-libraries --run-files --ignore-schedules --ignore-ghost --delete-collections "
    "--delete-labels --resume --no-countdown --no-missing --no-report --read-only-config --divider --width "
    "--low-priority --validate --validate-level --validate-schema --validate-dir"
)

if "--help" in sys.argv:
    print("usage: kometa.py [-h] " + " ".join(f"[{flag}]" for flag in FLAGS.split()))
    sys.exit(0)

config = Path(sys.argv[sys.argv.index("--config") + 1])


def report(lines: list[str]) -> None:
    """Print like Kometa's console: every line inside | … | borders."""
    for line in lines:
        print(f"| {line:<98} |")


def validate() -> int:
    """--validate: fail on any sandboxed file containing BROKEN. --validate-dir: fail on SCHEMA-BAD."""
    log = (config.parent / "fake.json").resolve().parent if (config.parent / "fake.json").exists() else config.parent
    seen = {path.relative_to(config.parent).as_posix(): path.read_text() for path in sorted(config.parent.rglob("*.yml")) if path.is_file()}
    with open(log / "validate_calls.jsonl", "a") as calls:
        calls.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "files": seen}) + "\n")
    if "--validate-dir" in sys.argv:
        folder = Path(sys.argv[sys.argv.index("--validate-dir") + 1])
        bad = [path for path in sorted(folder.iterdir()) if "SCHEMA-BAD" in path.read_text()]
        for path in bad:
            report(["=" * 62, f" File: {path}", " Schema: collection-schema.json", " Errors (1):", "   [collection-schema.json] at collections: not allowed"])
        report(["=" * 98])
        return 1 if bad else 0
    errors = [f"{name}: Collection Error: BROKEN is not a builder" for name, text in seen.items() if "BROKEN" in text]
    if "webhooks:" in seen.get(config.name, ""):
        errors.append("webhooks reached the sandbox")
    lines = ["", "=" * 62, " Validation Report (structure+schema)", "=" * 62, f" Config: {config}"]
    if errors:
        lines += ["", f" Errors ({len(errors)}):", *[f"   {e}" for e in errors]]
    report(lines + ["=" * 98])
    return 1 if errors else 0


if "--validate" in sys.argv or "--validate-dir" in sys.argv:
    sys.exit(validate())

plan = json.loads((config.parent / "fake.json").read_text())
print("ARGS " + " ".join(sys.argv[1:]), flush=True)

if plan.get("ignore_term"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if plan.get("child_pid"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path(plan["child_pid"]).write_text(str(child.pid))

for line in plan.get("lines", []):
    print(line, flush=True)

if plan.get("wait_for"):
    while not os.path.exists(plan["wait_for"]):
        time.sleep(0.02)
    for line in plan.get("after", []):
        print(line, flush=True)

sys.exit(plan.get("exit", 0))
