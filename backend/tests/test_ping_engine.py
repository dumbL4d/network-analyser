"""Ping engine: status classification and the injectable probe."""

import asyncio

import pytest
from icmplib import Host, NameLookupError, SocketPermissionError

from app.services.ping_engine import classify_status, ping_all, ping_one
from tests.helpers import FakePing

WARN = 100.0
CRIT = 500.0


@pytest.mark.parametrize(
    ("reachable", "latency_ms", "expected"),
    [
        # Unreachable always wins, whatever latency is reported.
        (False, None, "down"),
        (False, 5.0, "down"),
        # Reachable, but no latency measurement.
        (True, None, "unknown"),
        # At or below the warn threshold.
        (True, 0.0, "healthy"),
        (True, 99.999, "healthy"),
        (True, 100.0, "healthy"),  # exactly warn: the comparison is strict (>)
        # Above warn.
        (True, 100.001, "degraded"),
        (True, 499.999, "degraded"),
        (True, 500.0, "degraded"),  # exactly crit
        # Above crit is still "degraded": there is no separate critical status
        # (kept on purpose from the legacy tool, see classify_status).
        (True, 500.001, "degraded"),
        (True, 10_000.0, "degraded"),
    ],
)
def test_classify_status(reachable, latency_ms, expected):
    result = classify_status(
        reachable, latency_ms, warn_threshold=WARN, crit_threshold=CRIT
    )
    assert result == expected


def test_classify_status_uses_the_thresholds_it_is_given():
    assert classify_status(True, 60.0, warn_threshold=50.0, crit_threshold=80.0) == "degraded"
    assert classify_status(True, 60.0, warn_threshold=70.0, crit_threshold=80.0) == "healthy"


async def _ping_one(ping: FakePing, ip: str = "10.0.0.1"):
    return await ping_one(
        ip,
        "dev-1",
        timeout=2.0,
        privileged=True,
        warn_threshold=WARN,
        crit_threshold=CRIT,
        ping=ping,
    )


async def test_ping_one_fast_reply_is_healthy():
    status = await _ping_one(FakePing(default=(True, 12.5)))

    assert (status.device_id, status.status, status.latency_ms) == ("dev-1", "healthy", 12.5)
    assert status.timestamp.utcoffset().total_seconds() == 0  # timezone-aware UTC


async def test_ping_one_slow_reply_is_degraded():
    status = await _ping_one(FakePing(default=(True, 250.0)))

    assert (status.status, status.latency_ms) == ("degraded", 250.0)


async def test_ping_one_no_reply_is_down_without_latency():
    # icmplib reports avg_rtt 0.0 for a host that did not answer.
    status = await _ping_one(FakePing(default=(False, 0.0)))

    assert (status.status, status.latency_ms) == ("down", None)


@pytest.mark.parametrize(
    "error",
    [
        SocketPermissionError(privileged=True),  # no root / CAP_NET_RAW
        NameLookupError("not-a-host"),  # unresolvable address
        OSError("Network is unreachable"),
        RuntimeError("anything else"),
    ],
    ids=lambda error: type(error).__name__,
)
async def test_ping_one_probe_exception_is_reported_as_unknown(error):
    ping = FakePing()
    ping.outcomes["10.0.0.1"] = error

    status = await _ping_one(ping)

    assert (status.device_id, status.status, status.latency_ms) == ("dev-1", "unknown", None)


async def test_ping_one_reply_without_a_round_trip_time_is_unknown():
    status = await _ping_one(FakePing(default=(True, None)))

    assert (status.status, status.latency_ms) == ("unknown", None)


async def test_ping_one_sends_one_probe_with_the_given_timeout_and_mode():
    ping = FakePing()

    await ping_one(
        "10.0.0.9",
        "dev-1",
        timeout=1.5,
        privileged=False,
        warn_threshold=WARN,
        crit_threshold=CRIT,
        ping=ping,
    )

    assert ping.calls == [("10.0.0.9", {"count": 1, "timeout": 1.5, "privileged": False})]


async def test_ping_all_classifies_every_device_independently():
    ping = FakePing()
    ping.outcomes.update(
        {
            "10.0.0.1": (True, 3.0),
            "10.0.0.2": (False, 0.0),
            "10.0.0.3": SocketPermissionError(privileged=True),
            "10.0.0.4": (True, 180.0),
        }
    )
    devices = [("a", "10.0.0.1"), ("b", "10.0.0.2"), ("c", "10.0.0.3"), ("d", "10.0.0.4")]

    results = await ping_all(
        devices,
        timeout=2.0,
        privileged=True,
        warn_threshold=WARN,
        crit_threshold=CRIT,
        ping=ping,
    )

    assert [(r.device_id, r.status, r.latency_ms) for r in results] == [
        ("a", "healthy", 3.0),
        ("b", "down", None),
        ("c", "unknown", None),
        ("d", "degraded", 180.0),
    ]


async def test_ping_all_runs_concurrently_and_keeps_input_order():
    release = asyncio.Event()
    finished: list[str] = []

    async def ping(address: str, **kwargs):
        if address == "10.0.0.1":
            # The first device only answers after the last one has. A
            # sequential ping_all would wait here forever.
            await release.wait()
        finished.append(address)
        if address == "10.0.0.3":
            release.set()
        return Host(address, 1, [1.0])

    devices = [("a", "10.0.0.1"), ("b", "10.0.0.2"), ("c", "10.0.0.3")]
    results = await asyncio.wait_for(
        ping_all(
            devices,
            timeout=2.0,
            privileged=True,
            warn_threshold=WARN,
            crit_threshold=CRIT,
            ping=ping,
        ),
        timeout=5,
    )

    assert finished == ["10.0.0.2", "10.0.0.3", "10.0.0.1"]  # completion order
    assert [r.device_id for r in results] == ["a", "b", "c"]  # input order


async def test_ping_all_with_no_devices_returns_an_empty_list():
    ping = FakePing()

    results = await ping_all(
        [], timeout=2.0, privileged=True, warn_threshold=WARN, crit_threshold=CRIT, ping=ping
    )

    assert results == []
    assert ping.calls == []
