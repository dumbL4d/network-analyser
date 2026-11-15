"""Ping engine: status classification and the injectable probe."""

import asyncio

import pytest
from icmplib import Host, NameLookupError, SocketPermissionError

from app.services import ping_engine
from app.services.ping_engine import classify_status, ping_all, ping_one, staggered_ping
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


# --- staggered pings: the real probe -----------------------------------------------
#
# ``staggered_ping`` sends each echo request with one ``icmplib.async_ping``
# call. These tests replace that call, so no packet is sent, and none of them
# depends on how long anything takes.


class NoWaiting:
    """``asyncio`` as the ping engine sees it, with a ``sleep`` that takes no
    time and notes what it was asked for."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        await asyncio.sleep(0)

    def __getattr__(self, name: str):
        return getattr(asyncio, name)


async def test_staggered_ping_sends_every_request_on_time_without_waiting_for_a_reply(monkeypatch):
    clock = NoWaiting()
    requests: list[dict] = []
    all_sent = asyncio.Event()

    async def one_request(address: str, **kwargs) -> Host:
        requests.append(kwargs)
        if len(requests) == 4:
            all_sent.set()
        # No request is answered before the last one is out. Sent one after
        # the other, each waiting for its reply, the first would wait for ever.
        await all_sent.wait()
        return Host(address, 1, [1.0])

    monkeypatch.setattr(ping_engine, "asyncio", clock)
    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    host = await asyncio.wait_for(
        staggered_ping("10.0.0.1", count=4, interval=0.5, timeout=1.5, privileged=False), timeout=5
    )

    assert (host.packets_sent, host.rtts) == (4, [1.0, 1.0, 1.0, 1.0])
    # Each request waits for its own turn, a gap after the one before it...
    assert clock.sleeps == [0.0, 0.5, 1.0, 1.5]
    # ...and is one ping with the whole timeout to itself.
    assert requests == [{"count": 1, "timeout": 1.5, "privileged": False}] * 4


async def test_staggered_ping_lists_the_replies_in_the_order_the_requests_were_sent(monkeypatch):
    # (how long the reply takes, what icmplib reports): the first request is
    # answered last, the second not at all, and the fourth could not be sent.
    replies = iter([(0.03, (1, [30.0])), (0.0, (1, [])), (0.0, (1, [10.0])), (0.0, (0, []))])

    async def one_request(address: str, **kwargs) -> Host:
        delay, (sent, rtts) = next(replies)
        await asyncio.sleep(delay)
        return Host(address, sent, rtts)

    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    host = await staggered_ping("10.0.0.1", count=4, interval=0.001)

    # Sending order, which is what the jitter compares: |10 - 30|, not 0. And
    # the loss is counted against the three requests that went out.
    assert (host.address, host.packets_sent, host.rtts) == ("10.0.0.1", 3, [30.0, 10.0])
    assert host.is_alive


async def test_staggered_ping_with_one_request_is_one_plain_ping(monkeypatch):
    calls = []

    async def one_request(address: str, **kwargs) -> Host:
        calls.append((address, kwargs))
        return Host(address, 1, [])

    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    # A gap of an hour: with a single request there is none to wait for.
    host = await asyncio.wait_for(
        staggered_ping("10.0.0.1", count=1, interval=3600.0, timeout=1.5, privileged=True), timeout=5
    )

    assert calls == [("10.0.0.1", {"count": 1, "timeout": 1.5, "privileged": True})]
    assert (host.packets_sent, host.rtts, host.is_alive) == (1, [], False)


async def test_staggered_ping_passes_a_probe_error_on_and_sends_nothing_more(monkeypatch):
    sent = []

    async def one_request(address: str, **kwargs) -> Host:
        sent.append(address)
        raise SocketPermissionError(privileged=True)

    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    with pytest.raises(SocketPermissionError):
        await staggered_ping("10.0.0.1", count=3, interval=0.01)

    # The two requests that were still waiting for their turn are dropped:
    # well after they were due, only the first has been sent.
    await asyncio.sleep(0.05)
    assert sent == ["10.0.0.1"]


async def test_staggered_ping_looks_a_host_name_up_once_for_the_whole_probe(monkeypatch):
    lookups = []
    sent = []

    async def resolve(name: str) -> list[str]:
        lookups.append(name)
        return ["10.0.0.9", "10.0.0.10"]

    async def one_request(address: str, **kwargs) -> Host:
        sent.append(address)
        return Host(address, 1, [2.0])

    monkeypatch.setattr(ping_engine, "async_resolve", resolve)
    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    host = await staggered_ping("plc-1.plant.example", count=3, interval=0.001)

    assert lookups == ["plc-1.plant.example"]
    assert sent == ["10.0.0.9"] * 3  # every request goes to the same address
    assert (host.address, host.packets_sent) == ("10.0.0.9", 3)


async def test_staggered_ping_sends_nothing_to_a_name_that_does_not_resolve(monkeypatch):
    sent = []

    async def resolve(name: str) -> list[str]:
        raise NameLookupError(name)

    async def one_request(address: str, **kwargs) -> Host:
        sent.append(address)
        return Host(address, 1, [2.0])

    monkeypatch.setattr(ping_engine, "async_resolve", resolve)
    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    with pytest.raises(NameLookupError):
        await staggered_ping("not-a-host.example", count=3, interval=0.001)

    assert sent == []


async def test_the_staggered_ping_is_the_probe_when_none_is_injected(monkeypatch):
    requests = []

    async def one_request(address: str, **kwargs) -> Host:
        requests.append((address, kwargs))
        return Host(address, 1, [12.0])

    monkeypatch.setattr(ping_engine, "async_ping", one_request)

    (status,) = await ping_all(
        [("dev-1", "10.0.0.1")], 2.0, True, WARN, CRIT, pings=3, gap_seconds=0.001
    )

    assert requests == [("10.0.0.1", {"count": 1, "timeout": 2.0, "privileged": True})] * 3
    assert (status.status, status.latency_ms, status.loss_pct) == ("healthy", 12.0, 0.0)
