"""App startup: database seeding and the POLL_ENABLED switch."""

import asyncio

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import main
from app.core.config import settings
from app.db.seed import seed_devices_from_json
from app.db.session import engine
from app.models import AppSettings, Device, User
from tests.helpers import wipe_database


def _row_counts() -> tuple[int, int, int]:
    with Session(engine) as session:
        return (
            len(session.exec(select(Device)).all()),
            len(session.exec(select(User)).all()),
            len(session.exec(select(AppSettings)).all()),
        )


def test_startup_creates_and_seeds_an_empty_database():
    wipe_database()

    with TestClient(main.app):  # startup runs the migrations, then the seeds
        assert _row_counts() == (11, 2, 1)  # devices, users, settings rows


def test_restarting_does_not_duplicate_rows_or_undo_admin_edits(db):
    with Session(engine) as session:
        scanner = session.get(Device, "scanner-1")
        scanner.name = "Dock Scanner"
        app_settings = session.exec(select(AppSettings)).one()
        app_settings.poll_interval_seconds = 30.0
        session.add_all([scanner, app_settings])
        session.commit()

    for _ in range(2):  # two restarts
        with TestClient(main.app):
            pass

    assert _row_counts() == (11, 2, 1)
    with Session(engine) as session:
        assert session.get(Device, "scanner-1").name == "Dock Scanner"
        assert session.exec(select(AppSettings)).one().poll_interval_seconds == 30.0


def test_a_missing_seed_file_is_skipped_not_fatal(db, tmp_path):
    seed_devices_from_json(str(tmp_path / "missing.json"))

    assert _row_counts()[0] == 11


def test_background_tasks_are_not_started_when_poll_enabled_is_false(db):
    assert settings.POLL_ENABLED is False  # pinned in conftest.py

    with TestClient(main.app):
        assert main.app.state.poll_task is None
        assert main.app.state.retention_task is None


def test_background_tasks_run_for_the_lifetime_of_the_app_when_enabled(db, monkeypatch):
    started: list[str] = []

    def fake_loop(name: str):
        async def loop() -> None:
            started.append(name)
            await asyncio.Event().wait()  # like the real loops: runs until cancelled

        return loop

    monkeypatch.setattr(main, "run_poll_loop", fake_loop("poll"))
    monkeypatch.setattr(main, "run_retention_loop", fake_loop("retention"))
    monkeypatch.setattr(settings, "POLL_ENABLED", True)

    with TestClient(main.app) as client:
        poll_task = main.app.state.poll_task
        retention_task = main.app.state.retention_task
        assert client.get("/api/health").status_code == 200
        assert sorted(started) == ["poll", "retention"]
        assert not poll_task.done() and not retention_task.done()

    # Shutdown cancelled both.
    assert poll_task.cancelled() and retention_task.cancelled()
