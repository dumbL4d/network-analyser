"""Async ICMP ping engine built on top of :mod:`icmplib`.

Privileges / capabilities
=========================

``icmplib.async_ping(..., privileged=True)`` sends real ICMP echo requests over
a raw socket, which requires elevated privileges:

* **Docker (recommended)** -- the backend container needs the ``NET_RAW``
  capability. Add ``cap_add: [NET_RAW]`` to the ``backend`` service in
  ``infra/docker-compose.yml`` when that service is un-commented in a later
  infra ticket. Containers run as root by default, but declaring the capability
  explicitly is clearer and survives a switch to a non-root user.
* **Local, outside Docker, on Linux** -- either run uvicorn with ``sudo``, or
  grant the capability to the Python interpreter, e.g.::

      sudo setcap cap_net_raw+ep "$(readlink -f "$(which python3)")"

* **Unprivileged fallback** -- set ``PING_PRIVILEGED=False`` (see
  :class:`app.core.config.Settings`). ``icmplib`` then opens a *datagram* ICMP
  socket (``SOCK_DGRAM`` + ``IPPROTO_ICMP``) instead of a raw one. The Linux
  kernel allows this for non-root users when ``net.ipv4.ping_group_range``
  permits it, and it needs no ``sudo``. Caveats: it is not supported on
  Windows, is unreliable/unsupported on macOS, and even on Linux some hosts
  (or container images) will not answer these probes, so results are less
  reliable than raw ICMP. (Despite the common description of this mode as
  "UDP ping", ``icmplib`` still uses ICMP datagrams here -- not UDP.)

This module supports both modes via the ``privileged`` argument so the same
code path works locally and in the Docker deployment.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from icmplib import async_ping
from pydantic import BaseModel

logger = logging.getLogger(__name__)

StatusKey = Literal["healthy", "degraded", "down", "unknown"]


class DeviceStatus(BaseModel):
    """Transient (non-persisted) runtime status for a single device."""

    device_id: str
    status: StatusKey
    latency_ms: float | None
    timestamp: datetime


def classify_status(
    reachable: bool,
    latency_ms: float | None,
    warn_threshold: float,
    crit_threshold: float,
) -> StatusKey:
    """Classify a device from its reachability and latency.

    This mirrors the legacy tool's classification logic exactly. Note that the
    warn and the crit branches both currently return ``"degraded"`` -- this is
    intentional and preserves the original behavior; do not "fix" or simplify
    it here.
    """
    if not reachable:
        return "down"
    elif latency_ms is None:
        return "unknown"
    elif latency_ms > crit_threshold:
        return "degraded"
    elif latency_ms > warn_threshold:
        return "degraded"
    else:
        return "healthy"


async def ping_one(
    ip: str,
    device_id: str,
    timeout: float,
    privileged: bool,
    warn_threshold: float,
    crit_threshold: float,
) -> DeviceStatus:
    """Ping a single device and return its :class:`DeviceStatus`.

    The latency thresholds come from the caller (the poll loop now supplies
    the live DB-backed ``AppSettings`` row) rather than being read from the
    static .env config.

    Any exception raised while probing (permission errors, socket errors, ...)
    is caught and reported as ``status="unknown"`` instead of propagating.
    """
    reachable = False
    latency_ms: float | None = None

    try:
        host = await async_ping(ip, count=1, timeout=timeout, privileged=privileged)
        reachable = host.is_alive
        if reachable:
            latency_ms = float(host.avg_rtt) if host.avg_rtt is not None else None
    except Exception as err:
        logger.warning(
            "Ping failed for device_id=%s ip=%s: %s -- marking as unknown",
            device_id,
            ip,
            err,
        )
        return DeviceStatus(
            device_id=device_id,
            status="unknown",
            latency_ms=None,
            timestamp=datetime.now(timezone.utc),
        )

    status = classify_status(
        reachable,
        latency_ms,
        warn_threshold=warn_threshold,
        crit_threshold=crit_threshold,
    )
    return DeviceStatus(
        device_id=device_id,
        status=status,
        latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc),
    )


async def ping_all(
    devices: list[tuple[str, str]],
    timeout: float,
    privileged: bool,
    warn_threshold: float,
    crit_threshold: float,
) -> list[DeviceStatus]:
    """Concurrently ping ``devices`` (a list of ``(device_id, ip)`` tuples).

    ``asyncio.gather`` returns results in the same order as the input
    awaitables (independent of completion order), so the output list matches
    the input list positionally -- no re-sorting is needed.
    """
    return await asyncio.gather(
        *[
            ping_one(
                ip,
                device_id,
                timeout,
                privileged,
                warn_threshold,
                crit_threshold,
            )
            for device_id, ip in devices
        ]
    )
