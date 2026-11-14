"""Statistics over stored incidents and status transitions.

* ``summarize_incidents``: how many incidents, how long failures went
  unnoticed (mean detection delay), how long they took to clear (MTTR), and
  how many alerts were suppressed.
* ``downtime``: how long, and how often, a device was "down" in a period.
  ``device_availability`` applies it to every device, from the
  ``status_transition`` table.

The two calculations are pure functions; only ``device_availability`` reads
the database.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.session import engine
from app.models.device import Device
from app.models.incident import Incident
from app.schemas.stats import AvailabilityOut, DeviceAvailabilityOut, IncidentStatsOut
from app.services.persistence import ROLLUPS, SAMPLES, TRANSITIONS

AVAILABILITY_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_incidents(incidents: Iterable[Incident]) -> IncidentStatsOut:
    """Summary statistics over the given incidents (pure)."""
    incidents = list(incidents)
    resolved = [incident for incident in incidents if incident.resolved_at is not None]
    return IncidentStatsOut(
        count=len(incidents),
        open_count=len(incidents) - len(resolved),
        resolved_count=len(resolved),
        mean_detection_delay_seconds=_mean(
            [(i.opened_at - i.first_failure_at).total_seconds() for i in incidents]
        ),
        mttr_seconds=_mean([(i.resolved_at - i.opened_at).total_seconds() for i in resolved]),
        alerts_suppressed=sum(incident.peak_affected_count for incident in incidents),
    )


def downtime(
    initial_status: str | None,
    changes: list[tuple[datetime, str]],
    start: datetime,
    end: datetime,
) -> tuple[float, int]:
    """Seconds spent "down" and number of outages between ``start`` and ``end``.

    ``initial_status`` is the device's status at ``start`` and ``changes`` its
    status changes inside the period as ``(time, new status)``, oldest first.
    Only "down" counts as downtime: a degraded device still answers. An outage
    already under way at ``start`` counts as one. Pure.
    """
    seconds = 0.0
    outages = 1 if initial_status == "down" else 0
    status, since = initial_status, start
    for at, new_status in changes:
        if status == "down":
            seconds += (at - since).total_seconds()
        elif new_status == "down":
            outages += 1
        status, since = new_status, at
    if status == "down":
        seconds += (end - since).total_seconds()
    return seconds, outages


def device_availability(window: str, now: datetime | None = None) -> AvailabilityOut:
    """Uptime of every device over ``window`` (a key of AVAILABILITY_WINDOWS).

    A device's status over time is rebuilt from its status transitions. The
    period counted for a device starts at its first stored sample inside the
    window, so a device monitored for ten minutes is judged on ten minutes,
    not on a whole day of assumed uptime. Everything is read from the
    database, so the answer does not depend on what is in memory.
    """
    end = now or datetime.now(timezone.utc)
    start = end - AVAILABILITY_WINDOWS[window]

    with engine.connect() as connection:
        device_ids = connection.execute(select(Device.__table__.c.id)).scalars().all()

        in_window: dict[str, list] = {}
        for row in connection.execute(
            select(TRANSITIONS).where(TRANSITIONS.c.ts >= start).order_by(TRANSITIONS.c.ts, TRANSITIONS.c.id)
        ):
            in_window.setdefault(row.device_id, []).append(row)

        # The status each device had when the window began, for the devices
        # that did not change inside it: where its last earlier change left it.
        status_before: dict[str, str] = {}
        for row in connection.execute(
            select(TRANSITIONS.c.device_id, TRANSITIONS.c.to_status)
            .where(TRANSITIONS.c.ts < start)
            .order_by(TRANSITIONS.c.ts, TRANSITIONS.c.id)
        ):
            status_before[row.device_id] = row.to_status

        devices: list[DeviceAvailabilityOut] = []
        for device_id in device_ids:
            first_seen = [
                connection.execute(
                    select(func.min(column)).where(table.c.device_id == device_id, column >= start)
                ).scalar()
                for table, column in ((SAMPLES, SAMPLES.c.ts), (ROLLUPS, ROLLUPS.c.bucket_start))
            ]
            first_seen = [ts for ts in first_seen if ts is not None]
            if not first_seen:
                devices.append(
                    DeviceAvailabilityOut(
                        device_id=device_id, uptime_percent=None, downtime_seconds=0.0, outages=0, observed_seconds=0.0
                    )
                )
                continue

            observed_from = max(start, min(first_seen))
            changes = [row for row in in_window.get(device_id, []) if row.ts >= observed_from]
            if changes:
                initial_status = changes[0].from_status
            elif device_id in status_before:
                initial_status = status_before[device_id]
            else:
                # It has no stored status change, so its latest sample says
                # what it has been all along.
                initial_status = connection.execute(
                    select(SAMPLES.c.confirmed_status)
                    .where(SAMPLES.c.device_id == device_id)
                    .order_by(SAMPLES.c.ts.desc())
                    .limit(1)
                ).scalar()

            observed = (end - observed_from).total_seconds()
            down_seconds, outages = downtime(
                initial_status, [(row.ts, row.to_status) for row in changes], observed_from, end
            )
            devices.append(
                DeviceAvailabilityOut(
                    device_id=device_id,
                    uptime_percent=round(100 * (1 - down_seconds / observed), 3) if observed > 0 else None,
                    downtime_seconds=round(down_seconds, 3),
                    outages=outages,
                    observed_seconds=round(observed, 3),
                )
            )

    devices.sort(
        key=lambda d: (d.uptime_percent is None, d.uptime_percent if d.uptime_percent is not None else 0, d.device_id)
    )
    return AvailabilityOut(window=window, from_time=start, to_time=end, devices=devices)
