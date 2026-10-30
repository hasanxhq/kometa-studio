"""The ``kometa-studio`` command."""

import argparse
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .settings import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kometa-studio", description="Arr-style web GUI for Kometa.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the web app")
    serve.add_argument("--host", help="Address to bind (env STUDIO_HOST, default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="Port to listen on (env STUDIO_PORT, default 8484)")
    serve.add_argument("--data-dir", type=Path, help="Where Studio keeps its database and logs (env STUDIO_DATA_DIR)")

    args = parser.parse_args(argv)
    overrides = {k: v for k, v in {"host": args.host, "port": args.port, "data_dir": args.data_dir}.items() if v is not None}
    settings = Settings(**overrides)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
