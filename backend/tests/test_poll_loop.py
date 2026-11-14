"""The real poll loop, stepped one cycle at a time.

``run_cycles`` (tests/helpers.py) runs ``run_poll_loop`` with a fake ping and a
fake sleep, so these tests send no ICMP and never wait.
"""

import pytest
from sqlmodel import Session, select

from app.db.session import engine
from app.models.settings import AppSettings
from app.services import poll_loop
from app.services.flap_store import flap_store
from app.services.history_store import history_store
from app.services.status_store import status_store
from tests.helpers import FakePing, ip_of, run_cycles, seed_devices

# Every test here starts from a freshly seeded database.
pytestmark = pytest.mark.usefixtures("db")


def current_statuses() -> dict[str, str]:
    return {device_id: status.status for device_id, status in status_store.get_all().items()}


async def test_one_cycle_pings_every_device_and_feeds_the_three_stores():
    ping = FakePing(default=(True, 12.0))
    ping.outcomes[ip_of("sw-ot")] = (False, 0.0)

    intervals = await run_cycles(1, ping)

    assert intervals == [10.0]  # seeded poll interval
    assert sorted(address for address, _ in ping.calls) == sorted(d.ip for d in seed_devices())
    # One probe per device, with the timeout and mode from the static settings.
    assert all(
        kwargs == {"count": 1, "timeout": 2.0, "privileged": True} for _, kwargs in ping.calls
    )

    statuses = current_statuses()
    assert len(statuses) == 11
    assert statuses.pop("sw-ot") == "down"
    assert set(statuses.values()) == {"healthy"}
    assert [sample.latency_ms for sample in history_store.get_history("fw-01")] == [12.0]
    assert [sample.latency_ms for sample in history_store.get_history("sw-ot")] == [None]
    assert flap_store.get_flap_counts() == {}  # a first observation is never a flap


async def test_every_cycle_appends_history_and_counts_status_changes():
    ping = FakePing(default=(True, 1.0))

    def after_cycle(cycle: int) -> None:
        # sw-ot stops answering after cycle 1 and comes back after cycle 2.
        ping.outcomes[ip_of("sw-ot")] = (False, 0.0) if cycle == 1 else (True, 1.0)

    await run_cycles(3, ping, after_cycle)

    assert [sample.latency_ms for sample in history_store.get_history("sw-ot")] == [1.0, None, 1.0]
    assert len(history_store.get_history("fw-01")) == 3
    assert flap_store.get_flap_counts() == {"sw-ot": 2}
    assert current_statuses()["sw-ot"] == "healthy"


async def test_settings_update_takes_effect_on_the_next_cycle(client, admin_headers):
    ping = FakePing(default=(True, 150.0))  # every device answers in 150 ms
    seen: list[str] = []

    def after_cycle(cycle: int) -> None:
        seen.append(current_statuses()["fw-01"])
        if cycle == 1:
            # An admin edits the settings while the loop is sleeping.
            response = client.patch(
                "/api/settings",
                headers=admin_headers,
                json={"latency_warn_ms": 200.0, "poll_interval_seconds": 30.0},
            )
            assert response.status_code == 200

    intervals = await run_cycles(2, ping, after_cycle)

    # Cycle 1 used warn=100 (150 ms is degraded) and slept the old 10 s.
    # Cycle 2 used warn=200 (150 ms is healthy) and slept the new 30 s.
    assert seen == ["degraded", "healthy"]
    assert intervals == [10.0, 30.0]


async def test_devices_are_reloaded_every_cycle(client, admin_headers):
    def after_cycle(cycle: int) -> None:
        if cycle == 1:
            response = client.post(
                "/api/devices",
                headers=admin_headers,
                json={
                    "id": "plc-new",
                    "name": "New PLC",
                    "type": "plc",
                    "ip": "10.99.0.50",
                    "zone": "ot-tier",
                    "parent_id": "sw-ot",
                },
            )
            assert response.status_code == 201

    ping = FakePing()
    await run_cycles(2, ping, after_cycle)

    assert current_statuses()["plc-new"] == "healthy"
    assert len(history_store.get_history("plc-new")) == 1  # polled in cycle 2 only
    assert len(ping.calls) == 11 + 12


async def test_loop_keeps_going_after_a_failed_cycle(monkeypatch):
    real_load_devices = poll_loop._load_devices
    attempts = 0

    def flaky_load_devices() -> list[tuple[str, str]]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("database is locked")
        return real_load_devices()

    monkeypatch.setattr(poll_loop, "_load_devices", flaky_load_devices)
    devices_seen: list[int] = []

    intervals = await run_cycles(
        2, FakePing(), after_cycle=lambda cycle: devices_seen.append(len(status_store.get_all()))
    )

    assert devices_seen == [0, 11]  # cycle 1 failed, cycle 2 polled normally
    assert intervals == [10.0, 10.0]  # the loop still slept between them


async def test_missing_settings_row_falls_back_to_the_env_defaults():
    with Session(engine) as session:
        session.delete(session.exec(select(AppSettings)).one())
        session.commit()

    intervals = await run_cycles(1, FakePing(default=(True, 150.0)))

    assert intervals == [10.0]  # PING_INTERVAL_SECONDS
    assert set(current_statuses().values()) == {"degraded"}  # LATENCY_WARN_MS=100
