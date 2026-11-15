"""Root-cause vs. collateral incident classification.

Every unhealthy device (status ``down`` or ``degraded``) is classified as a
ROOT CAUSE (it failed by itself) or as COLLATERAL (it is out of reach because
of a failure somewhere else). There are two rules. Which one applies depends
on whether the topology has extra links.

WITHOUT LINKS: the device tree only
-----------------------------------
The original rule, unchanged. A device is judged against its parent:

* **root_cause** -- the parent is healthy (or the device is top-level), so this
  device caused its own outage.
* **collateral** -- the parent is also down/degraded, so this device went down
  as a consequence of an outage higher up the tree.

The parents are expected to form a tree. If they form a loop anyway (the API
and the seed loader both refuse one, so this is damaged data), the walk below
a root cause still ends: each device is visited once.

WITH LINKS: tree edges plus ``device_link`` rows
------------------------------------------------
A device can now have more than one way up, so looking at its parent is not
enough. The rule is about REACHABILITY in the graph that
app/services/topology_graph.py builds:

* "Unhealthy" means ``down`` or ``degraded``, as above. Every other status
  (``healthy``, ``unknown``, never polled) counts as healthy here: a missing
  measurement is not treated as a failure.
* A device is REACHABLE when a path leads to it from a root (a device with no
  parent) on which every INTERMEDIATE device is healthy. The device's own
  status does not matter, and a root is always reachable.
* **root_cause** -- unhealthy and reachable. The network gets as far as this
  device, so the fault is its own.
* **collateral** -- unhealthy and not reachable. Every way to it is blocked.
* The FAILURE REGION of a root cause is everything that can be reached from
  it by moving through unhealthy devices only: a connected group of unhealthy
  devices. A collateral device is attributed to every root cause whose region
  contains it, and is listed in the ``downstream_affected`` of each of them.
  ``downstream_affected`` holds collateral devices only, never another root
  cause, and is sorted by device id.

What follows from that:

* Losing one of two uplinks causes no collateral: the device behind them is
  still reachable through the other one. Losing both does.
* Root causes in the same region share its collateral devices. The analysis
  cannot tell which of them is to blame.
* Reachability is decided from the roots only. A device that answers is not
  taken as proof that the way to it works. So when a healthy device sits
  between two failures, the far one is collateral but in nobody's region: it
  is in the result, with no root cause listing it.

Both rules are pure: plain data in (devices, a status snapshot, links), plain
data out. No DB session and no FastAPI dependencies.
"""

from collections.abc import Sequence

from app.models.device import Device
from app.models.device_link import DeviceLink
from app.schemas.device import DeviceDTO
from app.schemas.incident import IncidentOut
from app.services.device_links import device_graph
from app.services.ping_engine import DeviceStatus
from app.services.topology_graph import DisjointSet, reachable_from_roots

UNHEALTHY = {"down", "degraded"}


def _status_of(device_id: str, statuses: dict[str, DeviceStatus]) -> str:
    """Live status for a device, defaulting to "unknown" if unseen."""
    status = statuses.get(device_id)
    return status.status if status is not None else "unknown"


def analyze_incidents(
    devices: list[Device],
    statuses: dict[str, DeviceStatus],
    links: Sequence[DeviceLink] | None = None,
) -> list[IncidentOut]:
    """Classify every currently unhealthy device into root causes and collateral.

    ``links`` are the extra links between devices. With none (None or an empty
    list) the tree rule applies, exactly as it always has. With links the
    reachability rule applies. Both are described in the module docstring.

    The response lists ALL root-cause entries first, then ALL collateral
    entries, each group sorted by ``device.id`` for deterministic ordering.
    """
    if links:
        return _analyze_with_links(devices, statuses, links)

    by_id = {device.id: device for device in devices}
    children: dict[str | None, list[Device]] = {}
    for device in devices:
        children.setdefault(device.parent_id, []).append(device)

    def impacted(device: Device) -> bool:
        return _status_of(device.id, statuses) in UNHEALTHY

    def downstream_affected(root_id: str) -> list[Device]:
        """Every descendant of ``root_id`` whose status is also unhealthy."""
        affected: list[Device] = []
        # In a tree nothing is reached twice. ``seen`` is for a parent loop in
        # the data (a hand-edited seed file): without it this walk never ends.
        seen = {root_id}
        stack = list(children.get(root_id, []))
        while stack:
            node = stack.pop()
            if node.id in seen:
                continue
            seen.add(node.id)
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


def _analyze_with_links(
    devices: list[Device],
    statuses: dict[str, DeviceStatus],
    links: Sequence[DeviceLink],
) -> list[IncidentOut]:
    """The reachability rule (see the module docstring).

    1. Search from the roots, not passing through unhealthy devices. An
       unhealthy device that is reached is a root cause; one that is not is
       collateral.
    2. Group the unhealthy devices that are joined to each other (union-find):
       each group is a failure region.
    3. Give every root cause the collateral devices of its own region.

    Time O((V + E) * alpha(V) + U log U) for V devices, E edges and U
    unhealthy devices (the sorting). Space O(V + E).
    """
    by_id = {device.id: device for device in devices}
    graph = device_graph(devices, links)
    unhealthy = {
        device.id for device in devices if _status_of(device.id, statuses) in UNHEALTHY
    }
    reachable = reachable_from_roots(graph, unhealthy)
    collateral_ids = sorted(unhealthy - reachable)

    regions = DisjointSet(unhealthy)
    for device_id in unhealthy:
        for neighbour in graph.adjacency[device_id]:
            if neighbour in unhealthy:
                regions.union(device_id, neighbour)
    collateral_of_region: dict[str, list[DeviceDTO]] = {}
    for device_id in collateral_ids:  # sorted, so each list is sorted too
        collateral_of_region.setdefault(regions.find(device_id), []).append(
            DeviceDTO.model_validate(by_id[device_id])
        )

    def incident(device_id: str, category: str, affected: list[DeviceDTO]) -> IncidentOut:
        status = statuses.get(device_id)
        return IncidentOut(
            device=DeviceDTO.model_validate(by_id[device_id]),
            status=_status_of(device_id, statuses),
            latency_ms=status.latency_ms if status is not None else None,
            category=category,
            downstream_affected=affected,
        )

    return [
        incident(device_id, "root_cause", collateral_of_region.get(regions.find(device_id), []))
        for device_id in sorted(unhealthy & reachable)
    ] + [incident(device_id, "collateral", []) for device_id in collateral_ids]
