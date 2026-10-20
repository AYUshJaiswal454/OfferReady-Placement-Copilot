"""OfferReady ASGI application."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import get_settings
from .db import get_db, now_iso
from .metrics import metrics
from .security import hash_password

log = logging.getLogger("offerready")
STATIC_DIR = Path(__file__).parent / "static"

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=(self)",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


class HeadersAndMetricsMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                existing = {k.decode().lower() for k, _ in headers}
                for key, value in SECURITY_HEADERS.items():
                    if key not in existing:
                        headers.append((key.encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path.startswith("/api/"):
                endpoint = scope.get("endpoint")
                label = getattr(endpoint, "__name__", None) or "unmatched"
                metrics.observe(scope.get("method", "GET"), label, status_holder["status"], time.perf_counter() - start)


def seed() -> None:
    settings = get_settings()
    db = get_db()
    if not db.fetchone("SELECT id FROM users WHERE email = ?", (settings.admin_email,)):
        db.insert("users", {
            "email": settings.admin_email, "password_hash": hash_password(settings.admin_password),
            "name": "MSOT Placement Cell", "role": "admin", "created_at": now_iso(), "consent_at": now_iso(),
            "consent_version": "admin", "settings": {}, "target_locations": [],
        })
        log.info("Seeded admin account %s", settings.admin_email)
    if settings.seed_demo and not db.fetchone("SELECT id FROM users WHERE email = ?", ("demo@student.msot.edu",)):
        db.insert("users", {
            "email": "demo@student.msot.edu", "password_hash": hash_password("demo12345"), "name": "Demo Student",
            "role": "student", "roll_no": "MSOT24CS001", "batch_year": 2026, "branch": "CSE",
            "target_role": "Full Stack Developer", "job_type": "internship",
            "target_locations": ["Bangalore", "Remote"], "created_at": now_iso(), "settings": {},
        })


def register_handlers() -> None:
    """Import modules that register background task handlers and schedules."""
    from . import pipelines  # noqa: F401


def _spa_index(request: Request) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not found", "code": "not_found"}, status_code=404)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index, headers={"cache-control": "no-cache"})
    return PlainTextResponse("Frontend not built. Run `npm run build` in frontend/.", status_code=503)


async def health(request: Request) -> Response:
    from .llm.providers import provider_status

    db_ok = True
    try:
        get_db().scalar("SELECT 1")
    except Exception:  # pragma: no cover
        db_ok = False
    queued = get_db().scalar("SELECT COUNT(*) FROM tasks WHERE status = 'queued'")
    return JSONResponse({"ok": db_ok, "time": now_iso(), "queue_depth": queued, "ai": provider_status()})


async def metrics_endpoint(request: Request) -> Response:
    queued = get_db().scalar("SELECT COUNT(*) FROM tasks WHERE status = 'queued'") or 0
    running = get_db().scalar("SELECT COUNT(*) FROM tasks WHERE status = 'running'") or 0
    return PlainTextResponse(metrics.render(extra={"offerready_queue_depth": queued, "offerready_tasks_running": running}))


def create_app(start_worker: bool | None = None) -> Starlette:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    from .api import routes as api_routes

    register_handlers()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        get_db()
        seed()
        from .jobs.pipeline import warm_job_index

        asyncio.get_running_loop().run_in_executor(None, warm_job_index)
        stop = asyncio.Event()
        background: list[asyncio.Task] = []
        worker = None
        run_worker = settings.embedded_worker if start_worker is None else start_worker
        if run_worker:
            from .tasks import Worker, scheduler_loop

            worker = Worker(concurrency=settings.worker_concurrency)
            background.append(asyncio.create_task(worker.run()))
            background.append(asyncio.create_task(scheduler_loop(stop, worker.id)))
        try:
            yield
        finally:
            stop.set()
            if worker:
                await worker.stop()
            for task in background:
                task.cancel()

    routes = [
        Route("/api/health", health),
        Route("/metrics", metrics_endpoint),
        *api_routes(),
    ]
    if (STATIC_DIR / "assets").exists():
        routes.append(Mount("/assets", app=StaticFiles(directory=STATIC_DIR / "assets"), name="assets"))
    routes.append(Route("/favicon.svg", lambda r: FileResponse(STATIC_DIR / "favicon.svg") if (STATIC_DIR / "favicon.svg").exists() else PlainTextResponse("", 404)))
    routes.append(Route("/{path:path}", _spa_index))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(HeadersAndMetricsMiddleware)
    return app


app = create_app()
