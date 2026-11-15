import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.deps import get_current_user, get_stream_user
from app.db.seed import seed_devices_from_json
from app.db.seed_settings import seed_default_settings
from app.db.seed_users import seed_default_users
from app.db.session import init_db
from app.models.user import User
from app.routers.analysis import router as analysis_router
from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.chaos import router as chaos_router
from app.routers.devices import router as devices_router
from app.routers.flaps import router as flaps_router
from app.routers.history import router as history_router
from app.routers.incidents import router as incidents_router
from app.routers.links import router as links_router
from app.routers.playbooks import router as playbooks_router
from app.routers.settings import router as settings_router
from app.routers.stats import router as stats_router
from app.routers.users import router as users_router
from app.schemas.auth import StreamTicketOut
from app.services.chaos import report_leftover_faults
from app.services.persistence import warm_caches
from app.services.ping_engine import DeviceStatus
from app.services.poll_loop import run_poll_loop
from app.services.retention import run_retention_loop
from app.services.status_store import status_store
from app.services.stream_tickets import stream_tickets

logging.basicConfig(level=logging.INFO)

SEED_PATH = Path(__file__).resolve().parents[2] / "infra" / "devices.seed.json"


def resolve_seed_path() -> Path:
    """Locate the devices seed JSON with production container deploy in mind.

    Priority:
    1. ``SEED_PATH`` env var (configurable via ``settings``) -- lets a
       deployment point at a mounted read-only copy of ``devices.seed.json``.
    2. Repo-root layout (``<repo>/infra/devices.seed.json``) -- local
       development from a git checkout.
    3. ``./infra/devices.seed.json`` relative to the working directory -- the
       ``/app`` layout assumption inside the production image.
    """
    if settings.SEED_PATH is not None:
        return Path(settings.SEED_PATH)
    repo_layout = Path(__file__).resolve().parents[2] / "infra" / "devices.seed.json"
    if repo_layout.exists():
        return repo_layout
    return Path.cwd() / "infra" / "devices.seed.json"


def serialize_snapshot(snapshot: dict[str, DeviceStatus]) -> dict:
    """Shape the store's state into the JSON payload sent to clients.

    ``status`` is the confirmed (debounced) status. ``raw_status`` and the two
    counters were added with debouncing, and the last four keys with multi-ping
    probing (``latency_ms`` is the average of a cycle's probes); the first
    three keys are unchanged.
    """
    return {
        device_id: {
            "status": status.status,
            "latency_ms": status.latency_ms,
            "timestamp": status.timestamp.isoformat(),
            "raw_status": status.raw_status or status.status,
            "consecutive_failures": status.consecutive_failures,
            "consecutive_successes": status.consecutive_successes,
            "latency_min_ms": status.latency_min_ms,
            "latency_max_ms": status.latency_max_ms,
            "loss_pct": status.loss_pct,
            "jitter_ms": status.jitter_ms,
        }
        for device_id, status in snapshot.items()
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_devices_from_json(str(resolve_seed_path()))
    seed_default_users()
    seed_default_settings()
    # Refill the in-memory stores, so history and flap counts survive a restart.
    warm_caches()
    # Faults injected before a restart are still in place: say so in the log.
    # In a thread, so a slow or absent chaos agent cannot hold up the startup.
    if settings.CHAOS_AGENT_URL and settings.CHAOS_AGENT_TOKEN:
        app.state.chaos_report = asyncio.create_task(asyncio.to_thread(report_leftover_faults))

    # The background tasks: the poll loop and the hourly retention job. Keep a
    # reference on app.state so they are not garbage collected.
    # POLL_ENABLED=False (the test suite) starts the API without them.
    app.state.poll_task = app.state.retention_task = None
    if settings.POLL_ENABLED:
        app.state.poll_task = asyncio.create_task(run_poll_loop())
        app.state.retention_task = asyncio.create_task(run_retention_loop())
    tasks = [t for t in (app.state.poll_task, app.state.retention_task) if t is not None]

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Strict CORS: only the origins listed in CORS_ORIGINS (exact origins, never a
# wildcard: see config.py), only the methods and headers the frontend uses,
# and no credentials. The API is authenticated by the Authorization header,
# never by a cookie, so a browser has nothing to attach on another site's
# behalf.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(analysis_router)
app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(chaos_router)
app.include_router(devices_router)
app.include_router(flaps_router)
app.include_router(history_router)
app.include_router(incidents_router)
app.include_router(links_router)
app.include_router(playbooks_router)
app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(users_router)


@app.get("/api/health", status_code=200)
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/api/status")
def get_status(current_user: User = Depends(get_current_user)):
    """Non-streaming snapshot of the latest known status of every device."""
    return serialize_snapshot(status_store.get_all())


@app.post("/api/stream/ticket", response_model=StreamTicketOut)
def create_stream_ticket(current_user: User = Depends(get_current_user)) -> StreamTicketOut:
    """A single-use ticket that opens the status stream once, within 30 s."""
    return StreamTicketOut(
        ticket=stream_tickets.issue(current_user.username),
        expires_in=int(stream_tickets.ttl_seconds),
    )


@app.get("/api/stream/status")
async def stream_status(
    current_user: User = Depends(get_stream_user),
):
    """Server-Sent Events stream of full status snapshots.

    Auth note: this endpoint is the ONLY one that does not read the
    ``Authorization`` header, because the browser ``EventSource`` API cannot
    set custom request headers. Clients first get a ticket from
    POST /api/stream/ticket, then connect as
    ``/api/stream/status?ticket=<ticket>``. A ticket works once, so every
    (re)connection needs a new one. See ``app.core.deps.get_stream_user``.

    Each client gets its own queue. The generator is cancelled by
    ``EventSourceResponse`` when the client disconnects, which triggers the
    ``finally`` block that unsubscribes the queue.
    """

    async def event_generator():
        queue = status_store.subscribe()
        try:
            yield {
                "event": "status",
                "data": json.dumps(serialize_snapshot(status_store.get_all())),
            }
            while True:
                snapshot = await queue.get()
                yield {
                    "event": "status",
                    "data": json.dumps(serialize_snapshot(snapshot)),
                }
        finally:
            status_store.unsubscribe(queue)

    return EventSourceResponse(event_generator())
