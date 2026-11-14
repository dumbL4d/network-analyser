"""What the topology says about failures.

* ``spof_report``: the single points of failure, each with its blast radius
  and the devices it would cut off.
* ``what_if``: "what would happen if these devices failed?".

Both are pure calculations on the devices and links they are given. They read
nothing else and change nothing: not the live status, not the stored
incidents. The graph algorithms are in app/services/topology_graph.py.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from app.models.device import Device
from app.models.device_link import DeviceLink
from app.schemas.analysis import SpofOut, WhatIfOut
from app.services.device_links import device_graph
from app.services.incident_analysis import analyze_incidents
from app.services.ping_engine import DeviceStatus
from app.services.topology_graph import blast_radius, cut_off


class UnknownDevices(ValueError):
    """A what-if names devices that do not exist."""


def spof_report(devices: Sequence[Device], links: Sequence[DeviceLink]) -> list[SpofOut]:
    """Every single point of failure, largest blast radius first.

    A device is a single point of failure when at least one other device
    would lose every path to a root (a device with no parent) if it failed.
    Devices with the same blast radius are ordered by id.

    One blast-radius pass over the whole graph, O(V + E), then the list of
    cut-off devices for each of the S single points of failure:
    O(S * (V + E) * alpha(V)). Space O(V + E).
    """
    graph = device_graph(devices, links)
    radius = blast_radius(graph)
    return [
        SpofOut(
            device_id=device_id,
            blast_radius=radius[device_id],
            cut_off_device_ids=sorted(cut_off(graph, [device_id])),
        )
        for device_id in sorted(radius, key=lambda device_id: (-radius[device_id], device_id))
        if radius[device_id] > 0
    ]


def what_if(
    devices: Sequence[Device],
    links: Sequence[DeviceLink],
    failed_device_ids: Iterable[str],
) -> WhatIfOut:
    """What the incident analysis would report if these devices all failed.

    The imagined snapshot starts from a fully healthy network, whatever the
    live status is at the moment:

    * every device in ``failed_device_ids`` is down;
    * every other device that would lose all its paths to a root is down too
      (it could no longer be pinged). These are the ``unreachable`` devices,
      and their number is the total blast radius;
    * everything else is healthy.

    That snapshot goes through the same ``analyze_incidents`` as the live
    one, so the answer has the shape of GET /api/incidents. A failed device
    that is still reachable is a root cause; everything else that is down is
    collateral.

    Raises ``UnknownDevices`` if an id is not a device. Repeated ids count once.

    Time O((V + E) * alpha(V)) plus the analysis, space O(V + E).
    """
    failed = set(failed_device_ids)
    unknown = sorted(failed - {device.id for device in devices})
    if unknown:
        raise UnknownDevices("Unknown device(s): " + ", ".join(unknown))

    unreachable = cut_off(device_graph(devices, links), failed)
    now = datetime.now(timezone.utc)
    statuses = {
        device.id: DeviceStatus(
            device_id=device.id,
            status="down" if device.id in failed or device.id in unreachable else "healthy",
            latency_ms=None,
            timestamp=now,
        )
        for device in devices
    }
    return WhatIfOut(
        incidents=analyze_incidents(devices, statuses, links),
        unreachable_device_ids=sorted(unreachable),
        total_blast_radius=len(unreachable),
    )
