"""The real poll loop, stepped one cycle at a time.

``run_cycles`` (tests/helpers.py) runs ``run_poll_loop`` with a fake ping and a
fake sleep, so these tests send no ICMP and never wait.
"""

import pytest
from sqlmodel import Session, select

from app.db.session import engine
from app.models.settings import AppSettings
from app.services import poll_loop
from app.services.debounce import debouncer
from app.services.flap_store import flap_store
from app.services.history_store import history_store
from app.services.status_store import status_store
from tests.helpers import FakePing, ip_of, run_cycles, seed_devices

# Every test here starts from a freshly seeded database.
pytestmark = pytest.mark.usefixtures("db")

REPLY = (True, 1.0)  # answers in 1 ms
LOST = (False, 0.0)  # no answer


def current_statuses() -> dict[str, str]:
    return {device_id: status.status for device_id, status in status_store.get_all().items()}


def confirmed_and_raw(device_id: str) -> tuple[str, str | None]:
    status = status_store.get_all()[device_id]
    return (status.status, status.raw_status)


async def test_one_cycle_pings_every_device_and_feeds_the_three_stores():
    ping = FakePing(default=(True, 12.0))
    ping.outcomes[ip_of("sw-ot")] = LOST

    intervals = await run_cycles(1, ping)

    assert intervals == [10.0]  # seeded poll interval
    assert sorted(address for address, _ in ping.calls) == sorted(d.ip for d in seed_devices())
    # One call per device: the seeded 4 probes, 200 ms apart, with the timeout
    # and mode from the static settings.
    assert all(
        kwargs == {"count": 4, "interval": 0.2, "timeout": 2.0, "privileged": True}
        for _, kwargs in ping.calls
    )

    statuses = current_statuses()
    assert len(statuses) == 11
    assert statuses.pop("sw-ot") == "down"  # a first-ever result is accepted at once
    assert set(statuses.values()) == {"healthy"}
    assert [sample.latency_ms for sample in history_store.get_history("fw-01")] == [12.0]
    assert [sample.latency_ms for sample in history_store.get_history("sw-ot")] == [None]
    assert flap_store.get_flap_counts() == {}  # a first observation is never a flap


# --- debouncing ----------------------------------------------------------------


async def test_a_single_lost_ping_does_not_mark_a_device_down():
    ping = FakePing(default=REPLY)
    seen = []

    def after_cycle(cycle: int) -> None:
        status = status_store.get_all()["sw-ot"]
        seen.append((status.status, status.raw_status, status.consecutive_failures))
        # sw-ot misses exactly one poll: the second.
        ping.outcomes[ip_of("sw-ot")] = LOST if cycle == 1 else REPLY

    await run_cycles(3, ping, after_cycle)

    assert seen == [
        ("healthy", "healthy", 0),
        ("healthy", "down", 1),  # confirmed status holds; the raw result is visible
        ("healthy", "healthy", 0),
    ]
    assert flap_store.get_flap_counts() == {}  # no confirmed change, so no flap
    # History keeps the raw readings, including the lost ping.
    assert [sample.latency_ms for sample in history_store.get_history("sw-ot")] == [1.0, None, 1.0]


async def test_down_after_three_lost_pings_and_healthy_after_two_replies():
    #          cycle:  1      2     3     4     5      6
    script = [REPLY, LOST, LOST, LOST, REPLY, REPLY]
    ping = FakePing(default=REPLY)
    ping.outcomes[ip_of("sw-ot")] = script[0]
    seen = []

    def after_cycle(cycle: int) -> None:
        seen.append((*confirmed_and_raw("sw-ot"), flap_store.get_flap_counts().get("sw-ot", 0)))
        if cycle < len(script):
            ping.outcomes[ip_of("sw-ot")] = script[cycle]

    await run_cycles(6, ping, after_cycle)

    assert seen == [
        # confirmed, raw, flaps so far
        ("healthy", "healthy", 0),
        ("healthy", "down", 0),
        ("healthy", "down", 0),
        ("down", "down", 1),  # third lost ping in a row: confirmed, one flap
        ("down", "healthy", 1),
        ("healthy", "healthy", 2),  # second reply in a row: recovered, second flap
    ]
    assert [sample.latency_ms for sample in history_store.get_history("sw-ot")] == [
        1.0, None, None, None, 1.0, 1.0,
    ]
    assert set(current_statuses().values()) == {"healthy"}  # nobody else was affected


async def test_the_api_reports_confirmed_status_and_raw_details(client, admin_headers):
    ping = FakePing(default=REPLY)
    incidents_seen = []
    snapshots = []

    def after_cycle(cycle: int) -> None:
        incidents = client.get("/api/incidents", headers=admin_headers).json()
        incidents_seen.append([(i["device"]["id"], i["category"]) for i in incidents])
        snapshots.append(client.get("/api/status", headers=admin_headers).json()["sw-ot"])
        ping.outcomes[ip_of("sw-ot")] = LOST  # down from the second cycle on

    await run_cycles(4, ping, after_cycle)

    # No incident while the failure is unconfirmed; one root cause once it is.
    assert incidents_seen == [[], [], [], [("sw-ot", "root_cause")]]
    pending = snapshots[1]
    assert set(pending) == {
        "status", "latency_ms", "timestamp",  # the original keys
        "raw_status", "consecutive_failures", "consecutive_successes",  # added
        "latency_min_ms", "latency_max_ms", "loss_pct", "jitter_ms",  # added with multi-ping
    }
    assert (pending["status"], pending["raw_status"], pending["consecutive_failures"]) == ("healthy", "down", 1)
    assert pending["latency_ms"] is None  # the latest reading got no reply
    confirmed = snapshots[3]
    assert (confirmed["status"], confirmed["raw_status"], confirmed["consecutive_failures"]) == ("down", "down", 3)


async def test_debounce_thresholds_are_re_read_every_cycle(client, admin_headers):
    ping = FakePing(default=REPLY)
    seen = []

    def patch_settings(**fields) -> None:
        assert client.patch("/api/settings", headers=admin_headers, json=fields).status_code == 200

    def after_cycle(cycle: int) -> None:
        seen.append(confirmed_and_raw("sw-ot"))
        if cycle == 1:
            patch_settings(failure_threshold=1)  # confirm a failure at once
            ping.outcomes[ip_of("sw-ot")] = LOST
        elif cycle == 2:
            ping.outcomes[ip_of("sw-ot")] = REPLY  # default recovery threshold is 2
        elif cycle == 3:
            patch_settings(recovery_threshold=1)  # confirm a recovery at once
            ping.outcomes[ip_of("sw-ot")] = LOST
        elif cycle == 4:
            ping.outcomes[ip_of("sw-ot")] = REPLY

    await run_cycles(5, ping, after_cycle)

    assert seen == [
        ("healthy", "healthy"),
        ("down", "down"),  # failure_threshold=1: the first lost ping is enough
        ("down", "healthy"),  # recovery_threshold still 2: one reply is not
        ("down", "down"),
        ("healthy", "healthy"),  # recovery_threshold=1: one reply is enough
    ]


async def test_debounce_state_of_a_deleted_device_is_dropped(client, admin_headers):
    def after_cycle(cycle: int) -> None:
        if cycle == 1:
            assert "scanner-1" in debouncer.get_states()
            assert client.delete("/api/devices/scanner-1", headers=admin_headers).status_code == 204

    await run_cycles(2, FakePing(default=REPLY), after_cycle)

    states = debouncer.get_states()
    assert "scanner-1" not in states
    assert len(states) == 10


# --- settings and devices are re-read every cycle ------------------------------


async def test_settings_update_takes_effect_on_the_next_cycle(client, admin_headers):
    ping = FakePing(default=(True, 150.0))  # every device answers in 150 ms
    seen = []

    def after_cycle(cycle: int) -> None:
        seen.append(confirmed_and_raw("fw-01"))
        if cycle == 1:
            # An admin edits the settings while the loop is sleeping.
            response = client.patch(
                "/api/settings",
                headers=admin_headers,
                json={"latency_warn_ms": 200.0, "poll_interval_seconds": 30.0},
            )
            assert response.status_code == 200

    intervals = await run_cycles(3, ping, after_cycle)

    # Cycle 1 used warn=100 (150 ms is degraded) and slept the old 10 s.
    # From cycle 2 on, warn=200 (150 ms is healthy) and the sleep is 30 s. The
    # raw result changes at once; the confirmed status follows after the two
    # healthy polls that the default recovery threshold asks for.
    assert seen == [
        ("degraded", "degraded"),
        ("degraded", "healthy"),
        ("healthy", "healthy"),
    ]
    assert intervals == [10.0, 30.0, 30.0]


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


# --- failure handling ----------------------------------------------------------


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


async def test_missing_settings_row_falls_back_to_the_defaults():
    with Session(engine) as session:
        session.delete(session.exec(select(AppSettings)).one())
        session.commit()
    ping = FakePing(default=(True, 150.0))
    seen = []

    def after_cycle(cycle: int) -> None:
        seen.append(confirmed_and_raw("fw-01"))
        ping.outcomes[ip_of("fw-01")] = LOST

    intervals = await run_cycles(4, ping, after_cycle)

    assert intervals == [10.0] * 4  # PING_INTERVAL_SECONDS
    assert seen == [
        ("degraded", "degraded"),  # LATENCY_WARN_MS=100, so 150 ms is degraded
        ("degraded", "down"),
        ("degraded", "down"),
        ("down", "down"),  # default failure threshold of 3
    ]
