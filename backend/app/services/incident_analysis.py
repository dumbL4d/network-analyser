"""Tree-based root-cause vs. collateral incident classification.

Every unhealthy device (status ``down`` or ``degraded``) is classified against
the live status of its parent in the device tree:

* **root_cause** -- the parent is healthy (or the device is top-level), so this
  device caused its own outage.
* **collateral** -- the parent is also down/degraded, so this device went down
  as a consequence of an outage higher up the tree.

This is a pure function: plain data in (devices + a status snapshot), plain
data out. No DB session and no FastAPI dependencies, so it is easy to reason
about and to unit-test later.
"""

from app.models.device import Device
from app.schemas.device import DeviceDTO
from app.schemas.incident import IncidentOut
from app.services.ping_engine import DeviceStatus

UNHEALTHY = {"down", "degraded"}


def _status_of(device_id: str, statuses: dict[str, DeviceStatus]) -> str:
    """Live status for a device, defaulting to "unknown" if unseen."""
    status = statuses.get(device_id)
    return status.status if status is not None else "unknown"


def analyze_incidents(
    devices: list[Device], statuses: dict[str, DeviceStatus]
) -> list[IncidentOut]:
    """Classify every currently unhealthy device into root causes and collateral.

    The response lists ALL root-cause entries first, then ALL collateral
    entries, each group sorted by ``device.id`` for deterministic ordering.
    """
    by_id = {device.id: device for device in devices}
    children: dict[str | None, list[Device]] = {}
    for device in devices:
        children.setdefault(device.parent_id, []).append(device)

    def impacted(device: Device) -> bool:
        return _status_of(device.id, statuses) in UNHEALTHY

    def downstream_affected(root_id: str) -> list[Device]:
        """Every descendant of ``root_id`` whose status is also unhealthy."""
        affected: list[Device] = []
        stack = list(children.get(root_id, []))
        while stack:
            node = stack.pop()
            if impacted(node):
                affected.append(node)
            stack.extend(children.get(node.id, []))
        return affected

    root_causes: list[IncidentOut] = []
    collateral: list[IncidentOut] = []

    for device in devices:
        if not impacted(device):
            continue

        parent = by_id.get(device.parent_id) if device.parent_id is not None else None
        parent_unhealthy = parent is not None and impacted(parent)

        status = statuses.get(device.id)
        base = {
            "device": DeviceDTO.model_validate(device),
            "status": _status_of(device.id, statuses),
            "latency_ms": status.latency_ms if status is not None else None,
        }

        if parent_unhealthy:
            collateral.append(
                IncidentOut(**base, category="collateral", downstream_affected=[])
            )
        else:
            affected = downstream_affected(device.id)
            root_causes.append(
                IncidentOut(
                    **base,
                    category="root_cause",
                    downstream_affected=[
                        DeviceDTO.model_validate(child) for child in affected
                    ],
                )
            )

    root_causes.sort(key=lambda incident: incident.device.id)
    collateral.sort(key=lambda incident: incident.device.id)
    return root_causes + collateral