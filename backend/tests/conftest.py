"""Shared test setup and fixtures.

``app.core.config.settings`` and the SQLAlchemy engine are created the first
time the ``app`` package is imported, so the environment is pinned HERE, before
any ``app`` import. That is what guarantees the suite:

* uses a throwaway SQLite file, never the dev database;
* never starts the background poll loop (no ICMP, no privileges needed);
* behaves the same whatever a developer keeps in their local ``backend/.env``
  (real environment variables win over the ``.env`` file).
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="network-analyser-tests-"))
TEST_DB_PATH = _TMP_DIR / "test.db"
# The suite runs on a frozen copy of the original 11-device tree (no extra
# links), so tests about the monitoring logic do not change whenever the
# shipped topology does. Tests about the shipped topology itself load
# REAL_SEED_FILE (see test_seed_topology.py).
SEED_FILE = Path(__file__).resolve().parent / "data" / "classic_tree.seed.json"
REAL_SEED_FILE = Path(__file__).resolve().parents[2] / "infra" / "devices.seed.json"

os.environ.update(
    {
        "DATABASE_PATH": str(TEST_DB_PATH),
        "SEED_PATH": str(SEED_FILE),
        "POLL_ENABLED": "false",
        # Long enough to pass the startup check (see test_security.py).
        "JWT_SECRET_KEY": "test-only-secret-not-used-anywhere-else",
        "JWT_ALGORITHM": "HS256",
        "JWT_EXPIRE_MINUTES": "480",
        # The suite logs in as admin / admin123 and viewer / viewer123. What
        # happens without DEMO_MODE is covered in test_security.py.
        "DEMO_MODE": "true",
        "ADMIN_INITIAL_PASSWORD": "",
        "VIEWER_INITIAL_PASSWORD": "",
        "CORS_ORIGINS": '["http://localhost:5173"]',
        "PING_PRIVILEGED": "true",
        "PING_TIMEOUT_SECONDS": "2.0",
        "PING_INTERVAL_SECONDS": "10.0",
        "LATENCY_WARN_MS": "100.0",
        "LATENCY_CRIT_MS": "500.0",
        "HISTORY_MAX_SAMPLES": "36",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.core import security  # noqa: E402
from app.db.seed import seed_devices_from_json  # noqa: E402
from app.db.seed_settings import seed_default_settings  # noqa: E402
from app.db.seed_users import seed_default_users  # noqa: E402
from app.db.session import engine, init_db  # noqa: E402
from app.services.anomaly.registry import anomaly_registry  # noqa: E402
from app.services.chaos import chaos_controller  # noqa: E402
from app.main import app  # noqa: E402
from app.services.debounce import debouncer  # noqa: E402
from app.services.flap_store import flap_store  # noqa: E402
from app.services.history_store import history_store  # noqa: E402
from app.services.incident_tracker import incident_tracker  # noqa: E402
from app.services.rate_limit import login_throttle  # noqa: E402
from app.services.status_store import status_store  # noqa: E402
from app.services.stream_tickets import stream_tickets  # noqa: E402

# Hard stop if the engine is not pointing at the temp file (for example because
# ``app`` was imported before this module): the ``db`` fixture drops every table.
if Path(str(engine.url.database)) != TEST_DB_PATH:
    raise RuntimeError(
        f"Refusing to run: the engine points at {engine.url.database!r}, "
        f"not the temporary test database {str(TEST_DB_PATH)!r}"
    )

# bcrypt at its default cost takes about 0.2 s per hash or verify. Every test
# seeds two users and logs in, so use the cheapest cost here.
security.pwd_context.update(bcrypt__rounds=4)


@pytest.fixture(scope="session", autouse=True)
def _remove_temp_database() -> Iterator[None]:
    yield
    engine.dispose()
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _fresh_in_memory_stores() -> None:
    """The status/history/flap stores, the debouncer, the incident tracker,
    the anomaly detectors, the login throttle and the stream tickets are
    process-wide singletons that the app imports by name, so they are reset in
    place before every test."""
    for store in (
        anomaly_registry,
        status_store,
        history_store,
        flap_store,
        debouncer,
        incident_tracker,
        login_throttle,
        stream_tickets,
    ):
        store.__init__()
    chaos_controller.reset()  # forget injected faults and end any flap


@pytest.fixture
def db() -> None:
    """A freshly seeded database: the 11 warehouse devices, the ``admin`` and
    ``viewer`` accounts, and the default settings row.

    ``init_db`` brings the schema to the latest migration (a no-op when it is
    already there), then every row is deleted and the seeds run again.
    """
    init_db()
    with engine.begin() as connection:
        for table in reversed(SQLModel.metadata.sorted_tables):
            connection.execute(table.delete())
    seed_devices_from_json(str(SEED_FILE))
    seed_default_users()
    seed_default_settings()


@pytest.fixture
def client(db: None) -> Iterator[TestClient]:
    """HTTP client for the real app. Entering it runs the app lifespan, which
    (with ``POLL_ENABLED=false``) starts no background poll loop."""
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "admin", "admin123")


@pytest.fixture
def viewer_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "viewer", "viewer123")
