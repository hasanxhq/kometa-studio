"""The ``starr-studio`` command.

``serve`` runs the web app. ``create-user`` and ``set-proxy`` set up sign-in and the reverse proxy from a shell, before
the first start, so an install on a shared server (a seedbox) never has a moment where Studio answers without a
password (``deploy/install-seedbox.sh`` runs them). Both read the same ``STUDIO_*`` settings as ``serve``.
"""

import argparse
import getpass
import sys
from pathlib import Path

from . import __version__

MIN_PASSWORD = 8  # as Settings → General asks


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="starr-studio", description="Arr-style web GUI for Kometa.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the web app")
    serve.add_argument("--host", help="Address to bind (env STUDIO_HOST, default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="Port to listen on (env STUDIO_PORT, default 8484)")
    serve.add_argument("--data-dir", type=Path, help="Where Studio keeps its database and logs (env STUDIO_DATA_DIR)")

    user = commands.add_parser("create-user", help="Set the username and password Studio asks for (before or after the first start)")
    user.add_argument("--username", required=True)
    user.add_argument("--password-stdin", action="store_true", help="Read the password from standard input instead of asking")
    user.add_argument("--if-missing", action="store_true", help="Do nothing if a user is already set up")
    user.add_argument("--replace", action="store_true", help="Replace the user that is set up (signs every browser out)")
    user.add_argument("--data-dir", type=Path, help="Studio's data folder (env STUDIO_DATA_DIR)")

    proxy = commands.add_parser("set-proxy", help="Set the URL base and the trusted reverse proxies (Settings → General)")
    proxy.add_argument("--url-base", help="The path Studio is served under, such as /starr-studio")
    proxy.add_argument("--trusted", action="append", default=None, help="A proxy's address or network; repeat for more")
    proxy.add_argument("--data-dir", type=Path, help="Studio's data folder (env STUDIO_DATA_DIR)")

    args = parser.parse_args(argv)
    if args.command == "serve":
        _serve(args)
    elif args.command == "create-user":
        sys.exit(_create_user(args))
    elif args.command == "set-proxy":
        sys.exit(_set_proxy(args))


def _settings(args):
    from .settings import Settings

    values = {"host": getattr(args, "host", None), "port": getattr(args, "port", None), "data_dir": args.data_dir}
    return Settings(**{key: value for key, value in values.items() if value is not None})


def _serve(args) -> None:
    import uvicorn

    from .app import create_app

    settings = _settings(args)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


def _db(args):
    from .db import open_database

    return open_database(_settings(args).db_path)


def _read_password(from_stdin: bool) -> str | None:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        print("The two passwords don't match.", file=sys.stderr)
        return None
    return first


def _create_user(args) -> int:
    from . import auth
    from .db import get_setting, set_setting

    username = args.username.strip()
    if not username:
        print("The username can't be empty.", file=sys.stderr)
        return 2
    db = _db(args)
    try:
        current = get_setting(db, auth.AUTH)
        if current and args.if_missing:
            print(f"A user ({current.get('username')}) is already set up; left as it is.")
            return 0
        if current and not args.replace:
            print(f"A user ({current.get('username')}) is already set up. Use --replace to replace it.", file=sys.stderr)
            return 3
        password = _read_password(args.password_stdin)
        if password is None:
            return 2
        if len(password) < MIN_PASSWORD:
            print(f"Use a password of at least {MIN_PASSWORD} characters.", file=sys.stderr)
            return 2
        set_setting(db, auth.AUTH, {"username": username, "password": auth.hash_password(password), "required": "enabled"})
        auth.end_all_sessions(db)
    finally:
        db.close()
    print(f"Sign-in is set up for {username}. Everyone signs in, local addresses included.")
    return 0


def _set_proxy(args) -> int:
    from pydantic import ValidationError

    from . import reverse_proxy
    from .db import set_setting

    db = _db(args)
    try:
        values = reverse_proxy.load(db).model_dump()
        if args.url_base is not None:
            values["url_base"] = args.url_base
        if args.trusted is not None:
            values["trusted"] = args.trusted
        try:
            settings = reverse_proxy.ReverseProxySettings.model_validate(values)
        except ValidationError as error:
            print(error.errors()[0]["msg"].removeprefix("Value error, "), file=sys.stderr)
            return 2
        set_setting(db, reverse_proxy.SETTING, settings.model_dump())
    finally:
        db.close()
    print(f"URL base: {settings.url_base or '/'}; trusted proxies: {', '.join(settings.trusted) or 'none'}")
    return 0
