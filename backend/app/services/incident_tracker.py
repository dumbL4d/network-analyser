"""Incident lifecycle: from the stateless analysis to stored incidents.

``analyze_incidents`` (app/services/incident_analysis.py) answers "what is
wrong right now?" and remembers nothing. This module adds the memory. After
every poll cycle the poll loop calls the tracker, which compares the analysis
with the unresolved incidents in the database, keyed by root-cause device:

* a root cause with no unresolved incident    -> a new incident is OPENED;
* the downstream devices of an incident change -> AFFECTED_CHANGED is logged;
* the root device is confirmed healthy again   -> the incident is RESOLVED.

Two cases are deliberately left alone. If the root device becomes collateral
of an outage further up, its incident stays as it is (it is still down). If
its status is "unknown" (the probe itself fails), the incident stays open: not
being able to measure is not a recovery.

An incident's affected set holds its collateral devices: the unhealthy devices
below the root that have no incident of their own. A device below it that does
have one, and whatever that incident covers, is left out, so a device is never
counted for an incident and again for the one above it. (Collateral that
several root causes cut off together is still listed under each of them.)

Because the incidents live in the database and the tracker keeps no other
state, a backend restart needs no special code: the first cycle after it
continues the incidents whose root is still unhealthy, resolves the ones that
recovered meanwhile, and opens new ones, without ever creating a duplicate.

The comparison itself (``diff_incidents``) is a pure function.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.models.incident import Incident, IncidentEvent
from app.schemas.incident import IncidentOut
from app.services.incident_analysis import analyze_incidents
from app.services.ping_engine import DeviceStatus

OPEN = "open"
ACKNOWLEDGED = "acknowledged"
RESOLVED = "resolved"


# --- what a poll cycle can change ------------------------------------------------


@dataclass(frozen=True)
class Opened:
    root_device_id: str
    at: datetime
    first_failure_at: datetime
    status: str
    affected: tuple[str, ...]
    # True when the device was already down as collateral of another incident
    # and has only now become a root cause.
    promoted: bool


@dataclass(frozen=True)
class AffectedChanged:
    incident_id: int
    at: datetime
    affected: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class Resolved:
    incident_id: int
    at: datetime
    reason: str  # "recovered" or "device_deleted"


Change = Opened | AffectedChanged | Resolved


def diff_incidents(
    unresolved: list[Incident],
    analysis: list[IncidentOut],
    readings: dict[str, DeviceStatus],
    existing_device_ids: set[str],
    cycle_time: datetime,
) -> list[Change]:
    """Work out what one poll cycle changes. Pure: nothing is read or written.

    ``unresolved`` are the open and acknowledged incidents, ``analysis`` is the
    output of ``analyze_incidents`` for this cycle and ``readings`` the cycle's
    confirmed readings by device id. Resolutions and affected-set changes come
    first, then newly opened incidents.
    """
    root_causes = {
        incident.device.id: incident for incident in analysis if incident.category == "root_cause"
    }
    by_root = {incident.root_device_id: incident for incident in unresolved}
    collateral_until_now = {
        device_id for incident in unresolved for device_id in incident.affected_device_ids
    }

    def covered_by(device_id: str) -> set[str]:
        """What the incident rooted at ``device_id`` covers below it: every
        unhealthy descendant of a root cause, or the stored affected set of an
        incident whose root is collateral itself at the moment."""
        if device_id in root_causes:
            return {device.id for device in root_causes[device_id].downstream_affected}
        return set(by_root[device_id].affected_device_ids)

    def affected_by(root_id: str) -> set[str]:
        """The devices that count as collateral of the root cause ``root_id``.

        A device below it that has an incident of its own (it is a root cause
        too, or the root of an unresolved incident) is left out, together with
        everything that incident covers. So no device is counted for an
        incident and again for the one above it, and none that has its own
        incident counts as suppressed.
        """
        affected = covered_by(root_id)
        for owner in affected & (root_causes.keys() | by_root.keys()):
            affected -= {owner} | covered_by(owner)
        return affected

    def seen_at(device_id: str) -> datetime:
        reading = readings.get(device_id)
        return reading.timestamp if reading is not None else cycle_time

    changes: list[Change] = []
    for incident in unresolved:
        device_id = incident.root_device_id
        reading = readings.get(device_id)
        if device_id not in existing_device_ids:
            changes.append(Resolved(incident.id, cycle_time, "device_deleted"))
        elif reading is not None and reading.status == "healthy":
            changes.append(Resolved(incident.id, reading.timestamp, "recovered"))
        elif device_id in root_causes:
            before = set(incident.affected_device_ids)
            now = affected_by(device_id)
            if now != before:
                changes.append(
                    AffectedChanged(
                        incident_id=incident.id,
                        at=seen_at(device_id),
                        affected=tuple(sorted(now)),
                        added=tuple(sorted(now - before)),
                        removed=tuple(sorted(before - now)),
                    )
                )
        # Otherwise the root device is still down but is now collateral of an
        # outage further up, or its status is unknown: leave the incident as is.

    for device_id, root_cause in root_causes.items():
        if device_id in by_root:
            continue
        reading = readings.get(device_id)
        at = seen_at(device_id)
        promoted = device_id in collateral_until_now
        # A device that was already known to be down (as collateral) has no
        # detection delay of its own: its failure was never unnoticed.
        if promoted or reading is None or reading.failing_since is None:
            first_failure_at = at
        else:
            first_failure_at = reading.failing_since
        changes.append(
            Opened(
                root_device_id=device_id,
                at=at,
                first_failure_at=first_failure_at,
                status=root_cause.status,
                affected=tuple(sorted(affected_by(device_id))),
                promoted=promoted,
            )
        )
    return changes


# --- the tracker called by the poll loop -------------------------------------------


class IncidentTracker:
    def __init__(self) -> None:
        # True until the first cycle after the backend started has been handled.
        self._first_run = True

    def track(self, readings: list[DeviceStatus]) -> list[Change]:
        """Bring the stored incidents in line with one poll cycle.

        ``readings`` are the cycle's CONFIRMED readings. Everything is written
        in one transaction. Synchronous: the poll loop runs it in a worker
        thread after every cycle.
        """
        statuses = {reading.device_id: reading for reading in readings}
        cycle_time = max(
            (reading.timestamp for reading in readings), default=datetime.now(timezone.utc)
        )
        with Session(engine) as session:
            devices = session.exec(select(Device)).all()
            links = session.exec(select(DeviceLink)).all()
            unresolved = session.exec(select(Incident).where(Incident.state != RESOLVED)).all()
            changes = diff_incidents(
                unresolved,
                analyze_incidents(devices, statuses, links),
                statuses,
                {device.id for device in devices},
                cycle_time,
            )
            by_id = {incident.id: incident for incident in unresolved}
            for change in changes:
                self._apply(session, change, by_id)
            session.commit()
        self._first_run = False
        return changes

    def _apply(self, session: Session, change: Change, by_id: dict[int, Incident]) -> None:
        if isinstance(change, Opened):
            incident = Incident(
                root_device_id=change.root_device_id,
                state=OPEN,
                opened_at=change.at,
                first_failure_at=change.first_failure_at,
                peak_affected_count=len(change.affected),
                affected_device_ids=list(change.affected),
            )
            session.add(incident)
            session.flush()  # assigns incident.id
            details: dict = {"status": change.status, "affected": list(change.affected)}
            if change.promoted:
                details["promoted_from_collateral"] = True
            session.add(IncidentEvent(incident_id=incident.id, ts=change.at, type="opened", details=details))
            return

        incident = by_id[change.incident_id]
        if isinstance(change, AffectedChanged):
            incident.affected_device_ids = list(change.affected)
            incident.peak_affected_count = max(incident.peak_affected_count, len(change.affected))
            event_type = "affected_changed"
            details = {
                "added": list(change.added),
                "removed": list(change.removed),
                "affected_count": len(change.affected),
            }
        else:
            incident.state = RESOLVED
            incident.resolved_at = change.at
            event_type = "resolved"
            details = {"reason": change.reason}
            if self._first_run:
                # The first poll after a (re)start: the recovery itself may
                # have happened while the backend was not running.
                details["after_restart"] = True
        session.add(incident)
        session.add(IncidentEvent(incident_id=incident.id, ts=change.at, type=event_type, details=details))


incident_tracker = IncidentTracker()


# --- reading and operator actions (used by the API) ----------------------------------


class IncidentNotFound(LookupError):
    pass


class IncidentStateConflict(ValueError):
    pass


def list_incidents(
    session: Session,
    states: list[str] | None = None,
    device_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Incident]]:
    """One page of incidents, most recently opened first, and the total number
    that match the filters."""
    filters = []
    if states:
        filters.append(Incident.state.in_(states))
    if device_id is not None:
        filters.append(Incident.root_device_id == device_id)
    total = session.exec(select(func.count()).select_from(Incident).where(*filters)).one()
    items = session.exec(
        select(Incident)
        .where(*filters)
        .order_by(Incident.opened_at.desc(), Incident.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return total, list(items)


def get_incident(session: Session, incident_id: int) -> tuple[Incident, list[IncidentEvent]]:
    """An incident and its timeline, oldest event first."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise IncidentNotFound(incident_id)
    events = session.exec(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.ts, IncidentEvent.id)
    ).all()
    return incident, list(events)


def acknowledge_incident(
    session: Session, incident_id: int, username: str, now: datetime | None = None
) -> None:
    """Mark an open incident as acknowledged by ``username``."""
    now = now or datetime.now(timezone.utc)
    # A conditional UPDATE, so that an incident the tracker resolves at the
    # same moment cannot be flipped back to "acknowledged".
    result = session.exec(
        update(Incident)
        .where(Incident.id == incident_id, Incident.state == OPEN)
        .values(state=ACKNOWLEDGED, acknowledged_at=now, acknowledged_by=username)
    )
    if result.rowcount == 0:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise IncidentNotFound(incident_id)
        raise IncidentStateConflict(f"Incident is already {incident.state}")
    session.add(
        IncidentEvent(incident_id=incident_id, ts=now, type="acknowledged", details={"by": username})
    )
    session.commit()


def add_incident_note(
    session: Session, incident_id: int, username: str, text: str, now: datetime | None = None
) -> None:
    """Add a note to an incident's timeline (allowed in any state)."""
    if session.get(Incident, incident_id) is None:
        raise IncidentNotFound(incident_id)
    session.add(
        IncidentEvent(
            incident_id=incident_id,
            ts=now or datetime.now(timezone.utc),
            type="note",
            details={"by": username, "text": text},
        )
    )
    session.commit()
