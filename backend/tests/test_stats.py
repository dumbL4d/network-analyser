"""Incident statistics and per-device availability, with hand-computed fixtures."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert

from app.db.session import engine
from app.models.incident import Incident
from app.services.flap_store import Transition
from app.services.incident_stats import device_availability, downtime, summarize_incidents
from app.services.persistence import ROLLUPS, persist_cycle
from tests.helpers import make_status, seed_devices, store_incident

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
HOUR = 3600.0


def clock(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, 15, hour, minute, second, tzinfo=timezone.utc)


def ago(**delta) -> datetime:
    return NOW - timedelta(**delta)


# =============================================================================
# summarize_incidents (pure)
# =============================================================================


def incident(first_failure: datetime, opened: datetime, resolved: datetime | None, peak: int) -> Incident:
    return Incident(
        root_device_id="sw-ot",
        state="resolved" if resolved else "open",
        opened_at=opened,
        first_failure_at=first_failure,
        resolved_at=resolved,
        peak_affected_count=peak,
    )


def test_stats_of_no_incidents():
    stats = summarize_incidents([])

    assert stats.model_dump() == {
        "count": 0,
        "open_count": 0,
        "resolved_count": 0,
        "mean_detection_delay_seconds": None,
        "mttr_seconds": None,
        "alerts_suppressed": 0,
    }


def test_stats_worked_example():
    incidents = [
        # failed 10:00:00, raised 10:00:20 (20 s), cleared 10:10:20 (600 s), 5 collateral
        incident(clock(10, 0, 0), clock(10, 0, 20), clock(10, 10, 20), peak=5),
        # failed 11:00:00, raised 11:00:40 (40 s), cleared 11:01:40 (60 s), none
        incident(clock(11, 0, 0), clock(11, 0, 40), clock(11, 1, 40), peak=0),
        # failed 12:00:00, raised 12:00:30 (30 s), still open, 2 collateral
        incident(clock(12, 0, 0), clock(12, 0, 30), None, peak=2),
    ]

    stats = summarize_incidents(incidents)

    assert (stats.count, stats.open_count, stats.resolved_count) == (3, 1, 2)
    assert stats.mean_detection_delay_seconds == 30.0  # (20 + 40 + 30) / 3, open ones included
    assert stats.mttr_seconds == 330.0  # (600 + 60) / 2, resolved ones only
    assert stats.alerts_suppressed == 7  # 5 + 0 + 2


def test_mttr_is_none_until_something_is_resolved():
    stats = summarize_incidents([incident(clock(12, 0, 0), clock(12, 0, 30), None, peak=1)])

    assert (stats.mttr_seconds, stats.mean_detection_delay_seconds) == (None, 30.0)


def test_incident_stats_endpoint(client, viewer_headers):
    store_incident("sw-ot", clock(10, 0, 20), first_failure_at=clock(10, 0, 0), resolved_at=clock(10, 10, 20), peak_affected_count=5)
    store_incident("scanner-1", clock(11, 0, 40), first_failure_at=clock(11, 0, 0), resolved_at=clock(11, 1, 40))
    store_incident("srv-prod-1", clock(12, 0, 30), first_failure_at=clock(12, 0, 0), peak_affected_count=2)

    response = client.get("/api/stats/incidents", headers=viewer_headers)

    assert response.status_code == 200
    assert response.json() == {
        "count": 3,
        "open_count": 1,
        "resolved_count": 2,
        "mean_detection_delay_seconds": 30.0,
        "mttr_seconds": 330.0,
        "alerts_suppressed": 7,
    }


# =============================================================================
# downtime (pure): one hour, from 11:00 to 12:00
# =============================================================================

START, END = clock(11), clock(12)


@pytest.mark.parametrize(
    ("initial", "changes", "expected_seconds", "expected_outages"),
    [
        # nothing happened
        ("healthy", [], 0, 0),
        (None, [], 0, 0),
        # down for the whole hour: one outage, already under way at the start
        ("down", [], 3600, 1),
        # down 11:10 -> 11:25: 15 minutes
        ("healthy", [(clock(11, 10), "down"), (clock(11, 25), "healthy")], 900, 1),
        # down 11:10 -> 11:20 and again from 11:40 to the end: 10 + 20 minutes
        ("healthy", [(clock(11, 10), "down"), (clock(11, 20), "healthy"), (clock(11, 40), "down")], 1800, 2),
        # already down, back at 11:15, down again at 11:50: 15 + 10 minutes
        ("down", [(clock(11, 15), "healthy"), (clock(11, 50), "down")], 1500, 2),
        # degraded is not downtime: only 11:20 -> 11:30 counts
        (
            "healthy",
            [(clock(11, 10), "degraded"), (clock(11, 20), "down"), (clock(11, 30), "degraded"), (clock(11, 40), "healthy")],
            600,
            1,
        ),
        # neither is unknown
        ("healthy", [(clock(11, 10), "unknown"), (clock(11, 30), "healthy")], 0, 0),
        # down -> unknown -> down is two separate "down" periods: 10 + 10 minutes
        ("healthy", [(clock(11, 10), "down"), (clock(11, 20), "unknown"), (clock(11, 50), "down")], 1200, 2),
    ],
)
def test_downtime(initial, changes, expected_seconds, expected_outages):
    assert downtime(initial, changes, START, END) == (expected_seconds, expected_outages)


# =============================================================================
# device_availability: from stored transitions
# =============================================================================

pytest_db = pytest.mark.usefixtures("db")


def seen_since(device_id: str, when: datetime) -> None:
    """Store one sample, so the device counts as monitored from ``when``."""
    persist_cycle([make_status(device_id, "healthy", 1.0, when)], [])


def changed(device_id: str, when: datetime, from_status: str, to_status: str) -> None:
    persist_cycle([], [Transition(device_id, when, from_status, to_status)])


def by_device(result) -> dict[str, tuple]:
    return {
        d.device_id: (d.uptime_percent, d.downtime_seconds, d.outages, d.observed_seconds) for d in result.devices
    }


@pytest_db
def test_availability_worked_example_over_24_hours():
    day_start = ago(hours=24)
    # fw-01: monitored all day, down for one hour (06:00 -> 07:00).
    seen_since("fw-01", day_start)
    changed("fw-01", ago(hours=6), "healthy", "down")
    changed("fw-01", ago(hours=5), "down", "healthy")
    # sw-ot: only monitored for the last two hours, down for the last one.
    seen_since("sw-ot", ago(hours=2))
    changed("sw-ot", ago(hours=1), "healthy", "down")
    # scanner-1: went down 30 hours ago and never came back.
    seen_since("scanner-1", day_start)
    changed("scanner-1", ago(hours=30), "healthy", "down")
    # plc-conveyor-1: monitored all day, never changed.
    seen_since("plc-conveyor-1", day_start)

    result = device_availability("24h", now=NOW)

    assert (result.window, result.from_time, result.to_time) == ("24h", day_start, NOW)
    rows = by_device(result)
    assert rows["fw-01"] == (95.833, HOUR, 1, 24 * HOUR)  # 100 * (1 - 1/24)
    assert rows["sw-ot"] == (50.0, HOUR, 1, 2 * HOUR)  # judged on the 2 hours it was monitored
    assert rows["scanner-1"] == (0.0, 24 * HOUR, 1, 24 * HOUR)  # one outage, under way all day
    assert rows["plc-conveyor-1"] == (100.0, 0.0, 0, 24 * HOUR)
    assert rows["srv-prod-1"] == (None, 0.0, 0, 0.0)  # never monitored: no figure

    # Lowest uptime first; devices without a figure last, by id.
    order = [d.device_id for d in result.devices]
    assert order[:4] == ["scanner-1", "sw-ot", "fw-01", "plc-conveyor-1"]
    assert order[4:] == sorted(d.id for d in seed_devices() if d.id not in order[:4])


@pytest_db
def test_availability_counts_only_the_part_of_an_outage_inside_the_window():
    for when in (ago(days=7), ago(hours=24)):  # monitored at the start of both windows
        seen_since("fw-01", when)
    changed("fw-01", ago(hours=30), "healthy", "down")  # before the 24 h window
    changed("fw-01", ago(hours=18), "down", "healthy")  # inside it

    day = by_device(device_availability("24h", now=NOW))["fw-01"]
    week = by_device(device_availability("7d", now=NOW))["fw-01"]

    assert day == (75.0, 6 * HOUR, 1, 24 * HOUR)  # down for the first 6 of 24 hours
    assert week == (92.857, 12 * HOUR, 1, 168 * HOUR)  # the whole 12-hour outage


@pytest_db
def test_availability_uses_the_stored_status_when_a_device_never_changed():
    # Down ever since it was first polled: there is no transition to go by,
    # and nothing in memory either (as right after a restart).
    persist_cycle([make_status("fw-01", "down", None, ago(hours=24))], [])

    assert by_device(device_availability("24h", now=NOW))["fw-01"] == (0.0, 24 * HOUR, 1, 24 * HOUR)


@pytest_db
def test_a_device_known_only_from_rollups_counts_as_monitored():
    with engine.begin() as connection:
        connection.execute(
            insert(ROLLUPS),
            [{"device_id": "fw-01", "bucket_start": ago(days=3), "min": 1.0, "avg": 1.0, "max": 1.0,
              "sample_count": 6, "fail_count": 0}],
        )

    assert by_device(device_availability("7d", now=NOW))["fw-01"] == (100.0, 0.0, 0, 72 * HOUR)


def test_availability_endpoint(client, viewer_headers):
    seen_since("fw-01", datetime.now(timezone.utc) - timedelta(hours=1))

    response = client.get("/api/stats/availability", headers=viewer_headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"window", "from_time", "to_time", "devices"}
    assert body["window"] == "24h"  # the default
    assert len(body["devices"]) == 11  # every device is listed
    first = body["devices"][0]
    assert set(first) == {"device_id", "uptime_percent", "downtime_seconds", "outages", "observed_seconds"}
    assert (first["device_id"], first["uptime_percent"], first["outages"]) == ("fw-01", 100.0, 0)
    assert 3599 <= first["observed_seconds"] <= 3605


@pytest.mark.parametrize(("window", "status"), [("24h", 200), ("7d", 200), ("30d", 200), ("1h", 422), ("", 422)])
def test_availability_window_must_be_one_of_three(client, viewer_headers, window, status):
    response = client.get("/api/stats/availability", headers=viewer_headers, params={"window": window})

    assert response.status_code == status
    if status == 200:
        assert response.json()["window"] == window
