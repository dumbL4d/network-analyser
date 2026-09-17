import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.seed import seed_devices_from_json
from app.db.session import init_db
from app.routers.devices import router as devices_router
from app.services.ping_engine import DeviceStatus
from app.services.poll_loop import run_poll_loop
from app.services.status_store import status_store

logging.basicConfig(level=logging.INFO)

SEED_PATH = Path(__file__).resolve().parents[2] / "infra" / "devices.seed.json"


def serialize_snapshot(snapshot: dict[str, DeviceStatus]) -> dict:
    """Shape the store's state into the JSON payload sent to clients."""
    return {
        device_id: {
            "status": status.status,
            "latency_ms": status.latency_ms,
            "timestamp": status.timestamp.isoformat(),
        }
        for device_id, status in snapshot.items()
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_devices_from_json(str(SEED_PATH))

    # Keep a reference on app.state so the task is not garbage collected.
    app.state.poll_task = asyncio.create_task(run_poll_loop())

    try:
        yield
    finally:
        task = app.state.poll_task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(devices_router)


@app.get("/api/health", status_code=200)
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/api/status")
def get_status():
    """Non-streaming snapshot of the latest known status of every device."""
    return serialize_snapshot(status_store.get_all())


@app.get("/api/stream/status")
async def stream_status():
    """Server-Sent Events stream of full status snapshots.

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
