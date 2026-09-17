import json
from pathlib import Path

from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device


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


def seed_devices_from_json(json_path: str) -> None:
    devices_data = json.loads(Path(json_path).read_text())

    inserted = 0
    skipped = 0

    with Session(engine) as session:
        existing_ids = set(session.exec(select(Device.id)).all())

        for item in _topological_order(devices_data):
            if item["id"] in existing_ids:
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
            existing_ids.add(item["id"])
            inserted += 1

        session.commit()

    print(f"Device seed complete: {inserted} inserted, {skipped} skipped")
