from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.seed import seed_devices_from_json
from app.db.session import init_db

SEED_PATH = Path(__file__).resolve().parents[2] / "infra" / "devices.seed.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_devices_from_json(str(SEED_PATH))
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.get("/api/health", status_code=200)
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}
