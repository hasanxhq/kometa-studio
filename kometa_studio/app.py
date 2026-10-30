"""FastAPI application: the JSON API under /api/v1 plus the built React app."""

from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .crypto import SecretBox
from .db import open_database, schema_version
from .plex_routes import router as plex_router
from .settings import Settings

STATIC_DIR = Path(str(files("kometa_studio") / "static"))


def kometa_version(settings: Settings) -> str | None:
    """Read the installed Kometa's VERSION file, which sits next to kometa.py."""
    if settings.kometa_entry is None:
        return None
    version_file = settings.kometa_entry.parent / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


api = APIRouter(prefix="/api/v1")


@api.get("/status")
def status(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    return {
        "version": __version__,
        "kometa": {
            "version": kometa_version(settings),
            "config": str(settings.kometa_config) if settings.kometa_config else None,
        },
        "database": {"schema_version": schema_version(request.app.state.db)},
    }


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA, sending every non-API path to index.html so client-side routes work."""
    index = static_dir / "index.html"
    if not index.is_file():
        return  # API-only: `npm run dev` serves the frontend during development

    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(
    settings: Settings | None = None,
    static_dir: Path = STATIC_DIR,
    http_transport: httpx.AsyncBaseTransport | None = None,  # tests pass a mock
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = open_database(settings.db_path)
        app.state.secrets = SecretBox.load_or_create(settings.data_dir)
        app.state.http = httpx.AsyncClient(transport=http_transport)
        try:
            yield
        finally:
            await app.state.http.aclose()
            app.state.db.close()

    app = FastAPI(title="Kometa Studio", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api)
    app.include_router(plex_router)
    mount_frontend(app, static_dir)
    return app
