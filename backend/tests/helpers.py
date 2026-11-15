"""Plain helpers shared by the test modules (fixtures live in conftest.py)."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from icmplib import Host
from sqlalchemy import Table, inspect, select
from sqlmodel import Session

from app.core.config import settings
from app.db.session import engine
from app.models.device import Device
from app.models.incident import Incident, IncidentEvent
from app.services.debounce import debouncer
from app.services.flap_store import flap_store
from app.services.history_store import history_store
from app.services.incident_tracker import incident_tracker
from app.services.persistence import warm_caches
from app.services.ping_engine import DeviceStatus, PingFn, StatusKey
from app.services.poll_loop import run_poll_loop
from app.services.status_store import status_store


def make_status(
    device_id: str,
    status: StatusKey,
    latency_ms: float | None = None,
    timestamp: datetime | None = None,
) -> DeviceStatus:
    return DeviceStatus(
        device_id=device_id,
        status=status,
        latency_ms=latency_ms,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def stored(table: Table, *columns: str) -> list[tuple]:
    """The rows of a table in insertion order, as tuples of ``columns``."""
    with engine.connect() as connection:
        rows = connection.execute(select(table).order_by(table.c.id)).all()
    return [tuple(getattr(row, column) for column in columns) for row in rows]


def store_incident(
    root_device_id: str,
    opened_at: datetime,
    *,
    first_failure_at: datetime | None = None,
    resolved_at: datetime | None = None,
    acknowledged_by: str | None = None,
    peak_affected_count: int = 0,
    affected_device_ids: tuple[str, ...] = (),
) -> int:
    """Insert an incident row directly and return its id. Its state follows
    from the arguments: resolved, acknowledged, or open."""
    state = "resolved" if resolved_at else "acknowledged" if acknowledged_by else "open"
    with Session(engine) as session:
        incident = Incident(
            root_device_id=root_device_id,
            state=state,
            opened_at=opened_at,
            first_failure_at=first_failure_at or opened_at,
            acknowledged_at=opened_at if acknowledged_by else None,
            acknowledged_by=acknowledged_by,
            resolved_at=resolved_at,
            peak_affected_count=peak_affected_count,
            affected_device_ids=list(affected_device_ids),
        )
        session.add(incident)
        session.flush()
        session.add(IncidentEvent(incident_id=incident.id, ts=opened_at, type="opened", details={}))
        session.commit()
        return incident.id


def restart_backend(now: datetime | None = None) -> None:
    """What a backend restart does to its memory: every in-memory store is
    emptied, then startup refills them from the database."""
    for store in (status_store, history_store, flap_store, debouncer, incident_tracker):
        store.__init__()
    warm_caches(now)


def wipe_database() -> None:
    """Drop every table, ``alembic_version`` included, leaving an empty
    database that the next ``init_db()`` builds from the first migration."""
    with engine.begin() as connection:
        for table in inspect(connection).get_table_names():
            connection.exec_driver_sql(f'DROP TABLE "{table}"')


def seed_devices() -> list[Device]:
    """The 11-device warehouse tree the suite is seeded with
    (``tests/data/classic_tree.seed.json``) as plain ``Device`` objects, in
    file order. No database involved."""
    items = json.loads(Path(str(settings.SEED_PATH)).read_text())
    return [
        Device(
            id=item["id"],
            name=item["name"],
            type=item["type"],
            ip=item["ip"],
            zone=item["zone"],
            parent_id=item["parentId"],
        )
        for item in items
    ]


def ip_of(device_id: str) -> str:
    """The seeded IP address of a device (the fake ping is keyed by IP)."""
    return next(device.ip for device in seed_devices() if device.id == device_id)


class FakePing:
    """Drop-in for ``icmplib.async_ping`` that never sends a packet.

    ``outcomes`` maps an IP address to what the probes of one call do:

    * ``(is_alive, avg_rtt)``: every probe is answered in ``avg_rtt`` ms, or
      (``is_alive`` False) none is;
    * a list with one entry per probe: its round-trip time in ms, or None for
      a probe that got no reply, e.g. ``[10.0, None, 12.0, 30.0]``;
    * an exception to raise.

    Addresses that are not listed get ``default``. Every call is recorded in
    ``calls`` as ``(address, keyword_arguments)``.
    """

    Outcome = tuple[bool, float | None] | list[float | None] | Exception

    def __init__(self, default: "FakePing.Outcome" = (True, 1.0)) -> None:
        self.default = default
        self.outcomes: dict[str, FakePing.Outcome] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, address: str, **kwargs: Any) -> Any:
        self.calls.append((address, kwargs))
        outcome = self.outcomes.get(address, self.default)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, list):
            # The real thing: what icmplib returns for these replies.
            return Host(address, len(outcome), [rtt for rtt in outcome if rtt is not None])
        is_alive, avg_rtt = outcome
        count = kwargs.get("count", 1)
        return SimpleNamespace(
            is_alive=is_alive,
            avg_rtt=avg_rtt,
            min_rtt=avg_rtt,
            max_rtt=avg_rtt,
            rtts=[avg_rtt] * count if is_alive and avg_rtt is not None else [],
            packets_sent=count,
        )


class StopLoop(BaseException):
    """Raised by a fake sleep to end a background loop. A ``BaseException``,
    so the loop's own ``except Exception`` can never swallow it."""


async def run_cycles(
    n: int, ping: PingFn, after_cycle: Callable[[int], None] | None = None
) -> list[float]:
    """Run the REAL poll loop for exactly ``n`` cycles, without waiting.

    The loop calls the injected sleep once per cycle, after the stores have
    been updated. ``after_cycle(k)`` (1-based) runs at that moment, so a test
    can change settings or probe outcomes "while the loop sleeps". Returns the
    interval, in seconds, that the loop asked to sleep after each cycle.
    """
    intervals: list[float] = []

    async def fake_sleep(delay: float) -> None:
        intervals.append(delay)
        if after_cycle is not None:
            after_cycle(len(intervals))
        if len(intervals) >= n:
            raise StopLoop

    try:
        await run_poll_loop(ping=ping, sleep=fake_sleep)
    except StopLoop:
        pass
    return intervals
