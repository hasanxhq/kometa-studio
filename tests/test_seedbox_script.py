"""deploy/install-seedbox.sh: its syntax, its Kometa tag, and that sign-in is set before Studio first starts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "install-seedbox.sh"


def test_the_script_parses_and_pins_the_dockers_kometa():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    script_tag = re.search(r'^KOMETA_TAG="([^"]+)"', SCRIPT.read_text(), re.M).group(1)
    docker_tag = re.search(r"^ARG KOMETA_TAG=(\S+)", (ROOT / "Dockerfile").read_text(), re.M).group(1)
    assert script_tag == docker_tag


def test_dry_run_sets_sign_in_before_the_first_start(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("git", "systemctl"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(home)}
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--port", "34567", "--username", "me", "--wheel", "studio.whl", "--python", sys.executable],
        env=env, capture_output=True, text=True, check=True,
    )
    out = result.stdout
    assert "Dry run: nothing was changed." in out
    assert not (home / ".config").exists()
    create = out.index("create-user --username me --if-missing --password-stdin")
    proxy = out.index("set-proxy --url-base /starr-studio --trusted 127.0.0.1")
    start = out.index("systemctl --user restart starr-studio")
    assert create < proxy < start  # never a moment without a password
