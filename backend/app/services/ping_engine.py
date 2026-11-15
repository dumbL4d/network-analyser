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

Several probes per cycle
========================

A device is sent ``pings`` echo requests per poll cycle (``pings_per_cycle`` in
the settings), ``gap_seconds`` apart, with one call to
``icmplib.async_ping(address, count=..., interval=...)``. From the replies:

* ``latency_ms``: the average round-trip time (with its minimum and maximum);
* ``loss_pct``: the share of the probes that got no reply;
* ``jitter_ms``: how much the round-trip time varies from one probe to the
  next (the mean absolute difference of consecutive round-trip times).

One probe says "answered or not". Several say how reliable and how steady the
path is, which is what real-time traffic such as PLC polling cares about.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from typing import Any, Literal

from icmplib import async_ping
from pydantic import BaseModel

logger = logging.getLogger(__name__)

StatusKey = Literal["healthy", "degraded", "down", "unknown"]

# The probe used for one device: any coroutine function that can be called like
# ``icmplib.async_ping`` and returns an object like its ``Host``: ``is_alive``,
# ``avg_rtt``, ``min_rtt``, ``max_rtt``, ``rtts`` (the round-trip times of the
# probes that were answered) and ``packets_sent``. It is a parameter
# (defaulting to the real ICMP ping) so tests can inject a fake and never send
# a packet.
PingFn = Callable[..., Awaitable[Any]]

# What the poll loop falls back on when the settings row is missing. The same
# values are the defaults of the AppSettings columns.
DEFAULT_PINGS_PER_CYCLE = 4
DEFAULT_PING_GAP_MS = 200
DEFAULT_LOSS_WARN_PCT = 20.0
DEFAULT_JITTER_WARN_MS = 30.0

MIN_PINGS_PER_CYCLE, MAX_PINGS_PER_CYCLE = 1, 10
MIN_PING_GAP_MS, MAX_PING_GAP_MS = 10, 5000
# The probes of one cycle may take up at most this share of the poll interval.
PROBE_BUDGET_SHARE = 0.8


class DeviceStatus(BaseModel):
    """Transient (non-persisted) runtime status for a single device.

    Straight out of the ping engine, ``status`` is the raw classification of
    this poll. The poll loop then passes each reading through the debouncer
    (:mod:`app.services.debounce`), which replaces ``status`` with the
    confirmed status and fills in the remaining fields.
    """

    device_id: str
    status: StatusKey
    latency_ms: float | None
    timestamp: datetime
    raw_status: StatusKey | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    # When the current run of non-healthy raw results began (the first failing
    # probe of the streak), or None. Used for an incident's first_failure_at.
    failing_since: datetime | None = None
    # This cycle's probes. ``latency_ms`` above is their average round-trip
    # time; these are its minimum and maximum, the share of probes without a
    # reply, and the jitter (None unless at least two probes were answered).
    # All None when the probe itself failed.
    latency_min_ms: float | None = None
    latency_max_ms: float | None = None
    loss_pct: float | None = None
    jitter_ms: float | None = None


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


def loss_pct(sent: int, received: int) -> float:
    """Packet loss in percent: the share of ``sent`` probes without a reply.

    ``loss_pct(4, 3)`` is 25.0. Nothing sent counts as everything lost. O(1).
    """
    if sent <= 0:
        return 100.0
    return 100.0 * (sent - received) / sent


def jitter_ms(rtts: Sequence[float]) -> float | None:
    """Jitter: the mean absolute difference of consecutive round-trip times.

    For 10, 12 and 30 ms the differences are 2 and 18, so the jitter is 10 ms.
    Only the order matters, not how far apart the probes were sent. None with
    fewer than two round-trip times: there is nothing to compare. O(n).
    """
    if len(rtts) < 2:
        return None
    differences = [abs(later - earlier) for earlier, later in zip(rtts, rtts[1:])]
    return sum(differences) / len(differences)


def classify_probes(
    pings: int,
    reachable: bool,
    latency_ms: float | None,
    loss: float,
    jitter: float | None,
    warn_threshold: float,
    crit_threshold: float,
    loss_warn_pct: float,
    jitter_warn_ms: float,
) -> StatusKey:
    """Classify a device from the probes of one cycle.

    With a single probe per cycle this is exactly :func:`classify_status`,
    as it was before there were several. With several:

    * no reply at all (100% loss)                      -> down
    * loss >= ``loss_warn_pct``                        -> degraded
    * jitter >= ``jitter_warn_ms``                     -> degraded
    * average latency above the latency thresholds     -> degraded
    * otherwise                                        -> healthy
    """
    status = classify_status(reachable, latency_ms, warn_threshold, crit_threshold)
    if pings == 1 or status != "healthy":
        return status
    if loss >= loss_warn_pct or (jitter is not None and jitter >= jitter_warn_ms):
        return "degraded"
    return "healthy"


def probe_budget_problem(
    pings: int, gap_ms: float, timeout_seconds: float, poll_interval_seconds: float
) -> str | None:
    """Why these probe settings do not fit the poll interval, or None if they do.

    The probes of one cycle are sent ``gap_ms`` apart and the last reply is
    waited for up to the ping timeout: ``pings x gap + timeout``. That has to
    fit inside ``PROBE_BUDGET_SHARE`` (80%) of the poll interval, so that a
    cycle is over well before the next one is due.
    """
    needed = pings * gap_ms / 1000 + timeout_seconds
    allowed = PROBE_BUDGET_SHARE * poll_interval_seconds
    if needed <= allowed:
        return None
    return (
        f"pings_per_cycle x ping_gap_ms + the ping timeout is {needed:g} s "
        f"({pings} x {gap_ms:g} ms + {timeout_seconds:g} s), which does not fit comfortably "
        f"inside the poll interval of {poll_interval_seconds:g} s: at most {allowed:g} s "
        f"({PROBE_BUDGET_SHARE:.0%} of it). Lower pings_per_cycle or ping_gap_ms, or raise "
        f"poll_interval_seconds."
    )


async def ping_one(
    ip: str,
    device_id: str,
    timeout: float,
    privileged: bool,
    warn_threshold: float,
    crit_threshold: float,
    ping: PingFn = async_ping,
    *,
    pings: int = 1,
    gap_seconds: float = DEFAULT_PING_GAP_MS / 1000,
    loss_warn_pct: float = DEFAULT_LOSS_WARN_PCT,
    jitter_warn_ms: float = DEFAULT_JITTER_WARN_MS,
) -> DeviceStatus:
    """Probe a single device ``pings`` times and return its :class:`DeviceStatus`.

    The thresholds come from the caller (the poll loop supplies the live
    DB-backed ``AppSettings`` row) rather than being read from the static .env
    config.

    Any exception raised while probing (permission errors, socket errors, ...)
    is caught and reported as ``status="unknown"`` instead of propagating.

    ``ping`` is the probe to use (see :data:`PingFn`); production code leaves
    the default.
    """
    reachable = False
    latency_ms = latency_min_ms = latency_max_ms = None

    # With one probe the call is the one it has always been.
    probes: dict[str, Any] = {"count": pings}
    if pings > 1:
        probes["interval"] = gap_seconds

    try:
        host = await ping(ip, **probes, timeout=timeout, privileged=privileged)
        reachable = host.is_alive
        rtts = list(host.rtts)
        loss = loss_pct(host.packets_sent, len(rtts))
        if reachable:
            latency_ms = float(host.avg_rtt) if host.avg_rtt is not None else None
            if latency_ms is not None:
                latency_min_ms, latency_max_ms = float(host.min_rtt), float(host.max_rtt)
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

    jitter = jitter_ms(rtts)
    status = classify_probes(
        pings,
        reachable,
        latency_ms,
        loss,
        jitter,
        warn_threshold=warn_threshold,
        crit_threshold=crit_threshold,
        loss_warn_pct=loss_warn_pct,
        jitter_warn_ms=jitter_warn_ms,
    )
    return DeviceStatus(
        device_id=device_id,
        status=status,
        latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc),
        latency_min_ms=latency_min_ms,
        latency_max_ms=latency_max_ms,
        loss_pct=loss,
        jitter_ms=jitter,
    )


async def ping_all(
    devices: list[tuple[str, str]],
    timeout: float,
    privileged: bool,
    warn_threshold: float,
    crit_threshold: float,
    ping: PingFn = async_ping,
    *,
    pings: int = 1,
    gap_seconds: float = DEFAULT_PING_GAP_MS / 1000,
    loss_warn_pct: float = DEFAULT_LOSS_WARN_PCT,
    jitter_warn_ms: float = DEFAULT_JITTER_WARN_MS,
) -> list[DeviceStatus]:
    """Concurrently probe ``devices`` (a list of ``(device_id, ip)`` tuples).

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
                ping,
                pings=pings,
                gap_seconds=gap_seconds,
                loss_warn_pct=loss_warn_pct,
                jitter_warn_ms=jitter_warn_ms,
            )
            for device_id, ip in devices
        ]
    )
