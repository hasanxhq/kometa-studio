"""FastAPI application: the JSON API under /api/v1 plus the built React app."""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .arr import Arr
from .maintainerr import Maintainerr
from . import network
from .arr_routes import router as arr_router
from .network import NetworkTransport
from .network_routes import router as network_router
from .overlays_routes import router as overlays_router
from .usage import ApiCalls
from .usage import router as usage_router
from .wanted import WantedRecorder
from .services import router as services_router
from .tautulli import router as tautulli_router
from .auth import AuthMiddleware, LoginThrottle
from .reverse_proxy import UrlBaseMiddleware
from .auth_routes import TIMEZONE
from .auth_routes import router as auth_router
from .config_routes import router as config_router
from .config_write import ConfigWriter
from .crypto import SecretBox
from .db import get_setting, open_database, schema_version
from .health import PlexCheck, health, kometa_updates, kometa_version
from .jobs import router as jobs_router
from .logs_routes import router as logs_router
from .maintainerr_routes import router as maintainerr_router
from .notifications_routes import router as notifications_router
from .plex_routes import router as plex_router
from .runner import Runner
from .runs_routes import router as runs_router
from .runs_routes import webhook_token, webhook_url
from .scheduler import Scheduler, default_timezone
from .schedules_routes import next_scheduled
from .schedules_routes import router as schedules_router
from .settings import Settings
from .tasks import Tasks
from .tasks_routes import router as tasks_router

STATIC_DIR = Path(str(files("kometa_studio") / "static"))


api = APIRouter(prefix="/api/v1")


@api.get("/ping")
async def ping() -> dict:
    """Liveness for Docker's health check: open without sign-in, says nothing, asks nothing of Plex."""
    return {"ok": True}


@api.get("/status")
async def status(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    db = request.app.state.db
    installed = kometa_version(settings)
    return {
        "version": __version__,
        "kometa": {
            "version": installed,
            "config": str(settings.kometa_config) if settings.kometa_config else None,
            "updates": kometa_updates(db, installed),
        },
        "health": await health(
            db, settings, request.app.state.http, request.app.state.plex_check, request.app.state.runner.flags_error, request.app.state.maintainerr
        ),
        "database": {"schema_version": schema_version(request.app.state.db)},
        "runs": {
            "current": request.app.state.runner.current_run_id,
            "queued": request.app.state.db.execute("SELECT count(*) FROM runs WHERE status = 'queued'").fetchone()[0],
            "next_scheduled": next_scheduled(request.app.state.db, datetime.now(UTC)),
        },
    }


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA, sending every non-API path to index.html so client-side routes work."""
    index = static_dir / "index.html"
    if not index.is_file():
        return  # API-only: `npm run dev` serves the frontend during development

    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        base = request.scope.get("state", {}).get("url_base", "")
        if base and not request.scope.get("state", {}).get("under_url_base"):  # a page opened without the URL base
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"{base}/{path}{query}", status_code=307)
        # The page's assets and links follow <base href>, so they work under the URL base (reverse_proxy.py).
        html = index.read_text(encoding="utf-8").replace("<head>", f'<head>\n    <base href="{base}/" />', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings | None = None,
    static_dir: Path = STATIC_DIR,
    http_transport: httpx.AsyncBaseTransport | None = None,  # tests pass a mock
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = open_database(settings.db_path)
        app.state.timezone = get_setting(app.state.db, TIMEZONE) or app.state.timezone
        app.state.secrets = SecretBox.load_or_create(settings.data_dir)
        app.state.http = httpx.AsyncClient(transport=NetworkTransport(app.state.db, app.state.secrets, settings.kometa_config, http_transport))
        runner = Runner(app.state.db, settings, webhook_url(settings, webhook_token(app.state.db)))
        app.state.runner = runner
        runner.start()
        tasks = Tasks(app.state.db, settings, runner, app.state.writer)
        tasks.setup(app.state.timezone)
        app.state.tasks = tasks
        # Started after the runner has marked cut-off runs interrupted; its first tick catches up on missed runs.
        kometa_root = settings.kometa_entry.parent if settings.kometa_entry else None
        app.state.arr = Arr(app.state.db, runner, app.state.http, app.state.secrets, settings.kometa_config, kometa_root)
        app.state.arr.start()
        maintainerr = Maintainerr(app.state.db, app.state.http, app.state.secrets, settings.kometa_config, settings.kometa_entry.parent if settings.kometa_entry else None)
        app.state.maintainerr = maintainerr
        maintainerr.runner = runner
        runner.extra_env = lambda: network.kometa_env(app.state.db, app.state.secrets, settings.data_dir)
        if app.state.writer is not None:
            app.state.writer.extra_env = runner.extra_env
        runner.hooks.append(maintainerr)
        runner.hooks.append(WantedRecorder(app.state.db, runner, settings.kometa_config, kometa_root))
        runner.hooks.append(ApiCalls(app.state.db, runner, settings.kometa_config))
        if app.state.writer is not None:
            app.state.writer.guard = lambda path, root: [risk.message for risk in maintainerr.risks(path, root)]
        maintainerr.start()
        scheduler = Scheduler(app.state.db, runner, also=(tasks, app.state.arr))
        app.state.scheduler = scheduler
        scheduler.start()
        # Learn which flags this Kometa has, in the background: importing Kometa takes a few seconds.
        probe = asyncio.create_task(runner.probe_flags())
        try:
            yield
        finally:
            probe.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await probe
            await scheduler.stop()
            await tasks.stop()
            await app.state.arr.stop()
            await maintainerr.stop()
            await runner.stop()
            await app.state.http.aclose()
            app.state.db.close()

    app = FastAPI(title="Kometa Studio", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.timezone = default_timezone(settings.timezone)  # Settings → General can change it
    app.state.login_throttle = LoginThrottle()
    app.state.plex_check = PlexCheck()
    # One writer, so its lock keeps saves one at a time.
    app.state.writer = ConfigWriter(settings) if settings.kometa_config else None
    app.add_middleware(AuthMiddleware)
    app.add_middleware(UrlBaseMiddleware)  # outermost: Auth and the routes see paths without the URL base
    app.include_router(api)
    app.include_router(auth_router)
    app.include_router(plex_router)
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(config_router)
    app.include_router(tasks_router)
    app.include_router(arr_router)
    app.include_router(services_router)
    app.include_router(tautulli_router)
    app.include_router(usage_router)
    app.include_router(overlays_router)
    app.include_router(network_router)
    app.include_router(logs_router)
    app.include_router(jobs_router)
    app.include_router(maintainerr_router)
    app.include_router(notifications_router)
    mount_frontend(app, static_dir)
    return app
