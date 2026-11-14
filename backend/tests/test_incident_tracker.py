"""The incident tracker: how the live analysis becomes stored incidents.

Two layers are tested: ``diff_incidents`` (pure, no database), and the whole
lifecycle driven through the real poll loop with a fake ping.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.session import engine
from app.models.incident import Incident, IncidentEvent
from app.services import poll_loop
from app.services.incident_analysis import analyze_incidents
from app.services.incident_tracker import (
    AffectedChanged,
    Opened,
    Resolved,
    diff_incidents,
)
from app.services.persistence import SAMPLES
from app.services.ping_engine import DeviceStatus
from app.services.status_store import status_store
from tests.helpers import (
    FakePing,
    ip_of,
    make_status,
    restart_backend,
    run_cycles,
    seed_devices,
    store_incident,
    stored,
)

REPLY = (True, 1.0)
LOST = (False, 0.0)
OT_CHILDREN = ["ap-aisle-1", "ap-aisle-2", "hmi-panel-1", "plc-conveyor-1", "scanner-1"]

T0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


# =============================================================================
# diff_incidents: pure
# =============================================================================


def readings(
    now: datetime,
    down: tuple[str, ...] = (),
    unknown: tuple[str, ...] = (),
    failing_since: dict[str, datetime] | None = None,
) -> dict[str, DeviceStatus]:
    """A confirmed reading for every seeded device at ``now``: healthy unless listed."""
    result = {}
    for device in seed_devices():
        status = "down" if device.id in down else "unknown" if device.id in unknown else "healthy"
        reading = make_status(device.id, status, 1.0 if status == "healthy" else None, now)
        result[device.id] = reading.model_copy(
            update={"failing_since": (failing_since or {}).get(device.id)}
        )
    return result


def diff(unresolved: list[Incident], statuses: dict[str, DeviceStatus], now: datetime, deleted: tuple[str, ...] = ()):
    devices = [device for device in seed_devices() if device.id not in deleted]
    return diff_incidents(
        unresolved, analyze_incidents(devices, statuses), statuses, {device.id for device in devices}, now
    )


def open_incident(incident_id: int, root_device_id: str, affected: tuple[str, ...] = ()) -> Incident:
    return Incident(
        id=incident_id,
        root_device_id=root_device_id,
        state="open",
        opened_at=T0,
        first_failure_at=T0,
        peak_affected_count=len(affected),
        affected_device_ids=list(affected),
    )


def test_nothing_unhealthy_and_nothing_tracked_changes_nothing():
    assert diff([], readings(at(0)), at(0)) == []


def test_a_new_root_cause_opens_an_incident():
    statuses = readings(at(20), down=("sw-ot", "scanner-1"), failing_since={"sw-ot": at(0), "scanner-1": at(0)})

    assert diff([], statuses, at(20)) == [
        Opened(
            root_device_id="sw-ot",
            at=at(20),  # the poll that confirmed it
            first_failure_at=at(0),  # the first failing probe of the streak
            status="down",
            affected=("scanner-1",),  # collateral: no incident of its own
            promoted=False,
        )
    ]


def test_without_a_known_streak_start_the_first_failure_is_the_opening_poll():
    (opened,) = diff([], readings(at(20), down=("scanner-1",)), at(20))

    assert (opened.at, opened.first_failure_at) == (at(20), at(20))


def test_a_root_cause_that_already_has_an_incident_is_not_opened_again():
    tracked = [open_incident(1, "sw-ot", ("scanner-1",))]

    assert diff(tracked, readings(at(30), down=("sw-ot", "scanner-1")), at(30)) == []


def test_a_change_in_the_downstream_devices_is_reported_with_what_was_added_and_removed():
    tracked = [open_incident(1, "sw-ot", ("plc-conveyor-1", "scanner-1"))]
    statuses = readings(at(30), down=("sw-ot", "scanner-1", "ap-aisle-1", "ap-aisle-2"))

    assert diff(tracked, statuses, at(30)) == [
        AffectedChanged(
            incident_id=1,
            at=at(30),
            affected=("ap-aisle-1", "ap-aisle-2", "scanner-1"),
            added=("ap-aisle-1", "ap-aisle-2"),
            removed=("plc-conveyor-1",),
        )
    ]


def test_a_root_device_that_is_healthy_again_resolves_its_incident():
    tracked = [open_incident(1, "sw-ot", ("scanner-1",))]

    assert diff(tracked, readings(at(60)), at(60)) == [Resolved(1, at(60), "recovered")]


def test_an_incident_stays_open_while_its_root_device_cannot_be_probed():
    tracked = [open_incident(1, "sw-ot", ("scanner-1",))]

    # "unknown" is not a recovery: the incident is neither resolved nor changed.
    assert diff(tracked, readings(at(60), unknown=("sw-ot",)), at(60)) == []


def test_a_deleted_root_device_resolves_its_incident():
    tracked = [open_incident(1, "scanner-1")]
    statuses = {k: v for k, v in readings(at(60)).items() if k != "scanner-1"}

    assert diff(tracked, statuses, at(60), deleted=("scanner-1",)) == [Resolved(1, at(60), "device_deleted")]


def test_an_outage_further_up_leaves_the_existing_incident_alone_and_opens_one_for_the_new_root():
    tracked = [open_incident(1, "sw-ot", ("scanner-1",))]
    # sw-edge (the parent of sw-ot) is now down too: sw-ot becomes collateral.
    statuses = readings(at(90), down=("sw-edge", "sw-ot", "scanner-1"), failing_since={"sw-edge": at(70)})

    assert diff(tracked, statuses, at(90)) == [
        Opened("sw-edge", at(90), at(70), "down", affected=("scanner-1", "sw-ot"), promoted=False)
    ]


def test_a_child_still_down_when_its_parent_recovers_is_promoted_to_its_own_incident():
    tracked = [open_incident(1, "sw-ot", ("scanner-1",))]
    # The switch is back; the scanner behind it is still down.
    statuses = readings(at(120), down=("scanner-1",), failing_since={"scanner-1": at(0)})

    assert diff(tracked, statuses, at(120)) == [
        Resolved(1, at(120), "recovered"),
        # It was already known to be down, so there is no detection delay:
        # first_failure_at is the opening poll, not the start of its streak.
        Opened("scanner-1", at(120), at(120), "down", affected=(), promoted=True),
    ]


def test_independent_root_causes_each_get_an_incident():
    statuses = readings(at(20), down=("srv-prod-1", "scanner-1"))

    assert [(change.root_device_id, change.affected) for change in diff([], statuses, at(20))] == [
        ("scanner-1", ()),
        ("srv-prod-1", ()),
    ]


# =============================================================================
# The lifecycle through the real poll loop
# =============================================================================

pytest_db = pytest.mark.usefixtures("db")


def incidents() -> list[Incident]:
    with Session(engine) as session:
        return list(session.exec(select(Incident).order_by(Incident.id)).all())


def events(incident_id: int) -> list[tuple[str, dict]]:
    with Session(engine) as session:
        rows = session.exec(
            select(IncidentEvent).where(IncidentEvent.incident_id == incident_id).order_by(IncidentEvent.id)
        ).all()
        return [(row.type, row.details) for row in rows]


def poll_times(device_id: str) -> list[datetime]:
    """The time of every stored poll of a device; index 0 is cycle 1."""
    return [ts for device, ts in stored(SAMPLES, "device_id", "ts") if device == device_id]


async def run_script(ping: FakePing, cycles: int, script: dict[int, dict[str, tuple]], hook=None) -> None:
    """Run ``cycles`` poll cycles. ``script[c]`` is applied just before cycle
    ``c`` (1-based within this call): {device_id: REPLY or LOST}. ``hook(c)``
    runs after cycle ``c``."""

    def apply(cycle: int) -> None:
        for device_id, outcome in script.get(cycle, {}).items():
            ping.outcomes[ip_of(device_id)] = outcome

    def after_cycle(cycle: int) -> None:
        if hook is not None:
            hook(cycle)
        apply(cycle + 1)

    apply(1)
    await run_cycles(cycles, ping, after_cycle)


def lost(*device_ids: str) -> dict[str, tuple]:
    return {device_id: LOST for device_id in device_ids}


def reply(*device_ids: str) -> dict[str, tuple]:
    return {device_id: REPLY for device_id in device_ids}


@pytest_db
async def test_lifecycle_open_grow_acknowledge_resolve(client, admin_headers):
    ping = FakePing(default=REPLY)

    def hook(cycle: int) -> None:
        if cycle == 8:  # an admin acknowledges while the outage is ongoing
            (incident,) = incidents()
            response = client.post(f"/api/incidents/{incident.id}/acknowledge", headers=admin_headers)
            assert response.status_code == 200

    await run_script(
        ping,
        12,
        {
            2: lost("sw-ot", "plc-conveyor-1"),  # confirmed down at cycle 4
            5: lost("scanner-1"),  # confirmed down at cycle 7
            11: reply("sw-ot", "plc-conveyor-1", "scanner-1"),  # confirmed healthy at cycle 12
        },
        hook,
    )

    (incident,) = incidents()
    polls = poll_times("sw-ot")
    assert incident.root_device_id == "sw-ot"
    assert incident.state == "resolved"
    assert incident.first_failure_at == polls[1]  # cycle 2: the first lost ping
    assert incident.opened_at == polls[3]  # cycle 4: the third lost ping in a row
    assert incident.resolved_at == polls[11]  # cycle 12: the second reply in a row
    assert (incident.acknowledged_by, incident.acknowledged_at is not None) == ("admin", True)
    assert incident.peak_affected_count == 2
    assert incident.affected_device_ids == ["plc-conveyor-1", "scanner-1"]
    assert events(incident.id) == [
        ("opened", {"status": "down", "affected": ["plc-conveyor-1"]}),
        ("affected_changed", {"added": ["scanner-1"], "removed": [], "affected_count": 2}),
        ("acknowledged", {"by": "admin"}),
        ("resolved", {"reason": "recovered"}),
    ]


@pytest_db
async def test_one_incident_per_outage_however_long_it_lasts():
    ping = FakePing(default=REPLY)

    await run_script(ping, 14, {2: lost("sw-ot", *OT_CHILDREN)})

    (incident,) = incidents()  # the five children are collateral: no incident of their own
    assert (incident.root_device_id, incident.state) == ("sw-ot", "open")
    assert incident.affected_device_ids == OT_CHILDREN
    assert incident.peak_affected_count == 5
    assert [event_type for event_type, _ in events(incident.id)] == ["opened"]


@pytest_db
async def test_a_second_outage_of_the_same_device_is_a_new_incident():
    ping = FakePing(default=REPLY)

    await run_script(ping, 11, {2: lost("scanner-1"), 5: reply("scanner-1"), 8: lost("scanner-1")})

    first, second = incidents()
    assert first.id != second.id
    assert (first.root_device_id, first.state) == ("scanner-1", "resolved")
    assert (second.root_device_id, second.state) == ("scanner-1", "open")
    assert second.opened_at > first.resolved_at
    assert [event_type for event_type, _ in events(first.id)] == ["opened", "resolved"]


@pytest_db
async def test_a_child_still_down_after_its_parent_recovers_gets_its_own_incident():
    ping = FakePing(default=REPLY)

    await run_script(ping, 7, {2: lost("sw-ot", "scanner-1"), 5: reply("sw-ot")})

    switch_incident, scanner_incident = incidents()
    assert (switch_incident.root_device_id, switch_incident.state) == ("sw-ot", "resolved")
    assert (scanner_incident.root_device_id, scanner_incident.state) == ("scanner-1", "open")
    # Opened on the very poll the switch was confirmed healthy, with no
    # detection delay: the scanner was already known to be down.
    assert scanner_incident.opened_at == poll_times("scanner-1")[5]
    assert scanner_incident.first_failure_at == scanner_incident.opened_at
    assert events(scanner_incident.id) == [
        ("opened", {"status": "down", "affected": [], "promoted_from_collateral": True})
    ]


@pytest_db
async def test_an_incident_is_not_resolved_while_its_root_device_cannot_be_probed():
    ping = FakePing(default=REPLY)

    await run_script(
        ping, 8, {2: lost("scanner-1"), 5: {"scanner-1": PermissionError("raw sockets need root")}}
    )

    assert status_store.get_all()["scanner-1"].status == "unknown"
    (incident,) = incidents()
    assert incident.state == "open"


@pytest_db
async def test_live_incidents_endpoint_is_unchanged_by_the_tracker(client, admin_headers):
    ping = FakePing(default=REPLY)
    await run_script(ping, 4, {2: lost("sw-ot", "scanner-1")})

    live = client.get("/api/incidents", headers=admin_headers).json()

    assert [(item["device"]["id"], item["category"]) for item in live] == [
        ("sw-ot", "root_cause"),
        ("scanner-1", "collateral"),
    ]
    assert set(live[0]) == {"device", "status", "latency_ms", "category", "downstream_affected"}


# --- restart reconciliation ----------------------------------------------------

LONG_AFTER = timedelta(hours=2)  # far beyond the debouncer's memory


def later() -> datetime:
    return datetime.now(timezone.utc) + LONG_AFTER


@pytest_db
async def test_restart_continues_an_incident_that_is_still_unhealthy(client, admin_headers):
    ping = FakePing(default=REPLY)
    await run_script(ping, 4, {2: lost("sw-ot", "scanner-1")})
    (before,) = incidents()
    client.post(f"/api/incidents/{before.id}/acknowledge", headers=admin_headers)

    restart_backend()
    await run_script(ping, 3, {})  # still down

    (after,) = incidents()  # the same incident: no duplicate, nothing re-opened
    assert (after.id, after.state, after.opened_at) == (before.id, "acknowledged", before.opened_at)
    assert [event_type for event_type, _ in events(after.id)] == ["opened", "acknowledged"]


@pytest_db
async def test_restart_with_stale_state_still_does_not_duplicate_an_open_incident():
    ping = FakePing(default=REPLY)
    await run_script(ping, 4, {2: lost("sw-ot", "scanner-1")})

    restart_backend(later())  # long downtime: the debouncer starts from scratch
    await run_script(ping, 1, {})  # the first result is accepted at once: still down

    (incident,) = incidents()
    assert (incident.root_device_id, incident.state) == ("sw-ot", "open")


@pytest_db
async def test_restart_resolves_an_incident_that_recovered_while_the_backend_was_down():
    ping = FakePing(default=REPLY)
    await run_script(ping, 4, {2: lost("sw-ot", "scanner-1")})

    restart_backend(later())
    await run_script(ping, 1, {1: reply("sw-ot", "scanner-1")})  # it came back meanwhile

    (incident,) = incidents()
    assert incident.state == "resolved"
    assert incident.resolved_at == poll_times("sw-ot")[-1]  # the first poll after the restart
    assert events(incident.id)[-1] == ("resolved", {"reason": "recovered", "after_restart": True})


@pytest_db
async def test_restart_opens_an_incident_for_a_device_that_failed_while_the_backend_was_down():
    ping = FakePing(default=REPLY)
    await run_script(ping, 2, {})
    assert incidents() == []

    restart_backend(later())
    await run_script(ping, 1, {1: lost("scanner-1")})

    (incident,) = incidents()
    assert (incident.root_device_id, incident.state) == ("scanner-1", "open")
    assert incident.first_failure_at == incident.opened_at == poll_times("scanner-1")[-1]


# --- guards --------------------------------------------------------------------


@pytest_db
def test_the_database_refuses_a_second_unresolved_incident_for_the_same_device():
    store_incident("sw-ot", at(0), resolved_at=at(60))  # a past, resolved one is fine
    store_incident("sw-ot", at(100))

    with pytest.raises(IntegrityError):
        store_incident("sw-ot", at(200))

    assert [incident.state for incident in incidents()] == ["resolved", "open"]


@pytest_db
async def test_a_tracker_failure_does_not_stop_monitoring(monkeypatch):
    def broken(readings) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(poll_loop.incident_tracker, "track", broken)

    intervals = await run_cycles(2, FakePing())

    assert intervals == [10.0, 10.0]
    assert len(status_store.get_all()) == 11
    assert len(poll_times("fw-01")) == 2  # the samples were still stored


@pytest_db
async def test_the_tracker_runs_off_the_event_loop(monkeypatch):
    tracker_threads = []
    monkeypatch.setattr(
        poll_loop.incident_tracker, "track", lambda readings: tracker_threads.append(threading.current_thread())
    )

    await run_cycles(1, FakePing())

    assert len(tracker_threads) == 1  # once per cycle, not per HTTP request
    assert tracker_threads[0] is not threading.current_thread()
