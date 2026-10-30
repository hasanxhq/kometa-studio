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
    "--low-priority --validate --validate-level --validate-schema"
)

if "--help" in sys.argv:
    print("usage: kometa.py [-h] " + " ".join(f"[{flag}]" for flag in FLAGS.split()))
    sys.exit(0)

config = Path(sys.argv[sys.argv.index("--config") + 1])
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
