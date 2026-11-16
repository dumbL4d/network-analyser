import json
import logging
from pathlib import Path

from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device
from app.models.device_link import DeviceLink
from app.services.device_links import LinkConflict, LinkError, check_link

logger = logging.getLogger(__name__)


def _topological_order(devices: list[dict]) -> list[dict]:
    """Order devices so every parent appears before its children (FK-safe)."""
    remaining = {device["id"]: device for device in devices}
    ordered: list[dict] = []
    resolved: set[str] = set()

    while remaining:
        progressed = False
        for device_id in list(remaining):
            parent_id = remaining[device_id].get("parentId")
            if parent_id is None or parent_id in resolved:
                ordered.append(remaining.pop(device_id))
                resolved.add(device_id)
                progressed = True
        if not progressed:
            # Unresolvable (cycle or missing parent): append the rest as-is.
            ordered.extend(remaining.values())
            break

    return ordered


def _closes_parent_loop(
    device_id: str, parent_id: str | None, parents: dict[str, str | None]
) -> bool:
    """Would ``device_id`` under ``parent_id`` be its own ancestor?

    ``parents`` maps every device stored so far to its parent. The walk up
    ends at a top-level device, at a parent that does not exist, or (``seen``)
    on a loop that is in the data already and does not involve this device.
    """
    seen: set[str] = set()
    current = parent_id
    while current is not None and current not in seen:
        if current == device_id:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def seed_devices_from_json(json_path: str) -> None:
    """Seed devices, and the extra links between them, from the JSON
    topology file if present.

    The file is a list of devices. A device may carry ``"links"``: the ids of
    other devices it is linked to in addition to its parent, for example
    ``{"id": "sw-edge-2", ..., "parentId": "fw-01", "links": ["sw-ot"]}``.

    Seeding is idempotent, so it runs at every startup: a device or link that
    is already stored is left alone, and only what is missing is added. A link
    that breaks a rule (see app/services/device_links.py) is skipped with a
    warning rather than stopping the startup, and so is a device that would
    close a loop of parents: the incident analysis expects a tree.

    A missing seed file is NOT a startup error: a deployment may seed devices
    via the admin API instead of a mounted file, so skip gracefully when the
    file is absent (e.g. a volume-less container). The Docker image relies on
    this to boot without a mount; infra wiring can then mount a read-only copy
    of ``infra/devices.seed.json``.
    """
    if not Path(json_path).exists():
        logger.warning("Device seed file not found at %s -- skipping device seed", json_path)
        return

    devices_data = json.loads(Path(json_path).read_text())

    inserted = 0
    skipped = 0

    with Session(engine) as session:
        # Every stored device and its parent, kept current while seeding.
        parents = {device.id: device.parent_id for device in session.exec(select(Device)).all()}

        for item in _topological_order(devices_data):
            if item["id"] in parents:
                skipped += 1
                continue
            if _closes_parent_loop(item["id"], item.get("parentId"), parents):
                logger.warning(
                    "Seed device %s skipped: under parent %s it would be its own ancestor",
                    item["id"],
                    item.get("parentId"),
                )
                skipped += 1
                continue

            session.add(
                Device(
                    id=item["id"],
                    name=item["name"],
                    type=item["type"],
                    ip=item["ip"],
                    zone=item["zone"],
                    parent_id=item.get("parentId"),
                )
            )
            session.flush()
            parents[item["id"]] = item.get("parentId")
            inserted += 1

        # Links come after the devices, so both ends of every link exist.
        links_inserted = 0
        links_skipped = 0
        stored = {
            (link.device_a_id, link.device_b_id) for link in session.exec(select(DeviceLink)).all()
        }
        for item in devices_data:
            for other_id in item.get("links", []):
                try:
                    device_a_id, device_b_id = check_link(parents, stored, item["id"], other_id)
                except LinkConflict:
                    links_skipped += 1  # stored already: nothing to do
                    continue
                except LinkError as error:
                    logger.warning("Seed link %s -- %s skipped: %s", item["id"], other_id, error)
                    links_skipped += 1
                    continue
                session.add(DeviceLink(device_a_id=device_a_id, device_b_id=device_b_id))
                stored.add((device_a_id, device_b_id))
                links_inserted += 1

        session.commit()

    print(f"Device seed complete: {inserted} inserted, {skipped} skipped")
    print(f"Link seed complete: {links_inserted} inserted, {links_skipped} skipped")
