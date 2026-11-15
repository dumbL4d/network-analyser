"""When the poll loop does what: the fixed rate, and the retries of suspect
devices (app/services/poll_loop.py).

The real loop runs on a simulated clock. Nothing waits: the loop's sleeps and
the time the pings would take move the clock on, so "8 s later" costs nothing
and every time below is exact. The settings are the defaults (a cycle every
8 s, 4 pings, a 2 s ping timeout, a failure confirmed by 3 results in a row, a
retry 1 s after a pass) with one exception: the pings are a second apart, not
200 ms, so that every time is a whole number of seconds.

So a pass over devices that all answer takes 3 s, one with a silent device
5 s: its last ping is sent after 3 s and waits 2 s for a reply. The last test
but one runs the same outage on the real default gap.
"""

import inspect
import math
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from icmplib import Host
from sqlmodel import Session, select

from app.db.session import engine
from app.models.device import Device
from app.models.incident import Incident
from app.models.settings import AppSettings
from app.services import poll_loop
from app.services.debounce import debouncer
from app.services.history_store import history_store
from app.services.persistence import SAMPLES, TRANSITIONS
from app.services.ping_engine import MetricAnomaly, staggered_ping
from app.services.poll_health import poll_health
from app.services.poll_loop import RETRY_INTERVAL_SECONDS, run_poll_loop
from app.services.status_store import status_store
from tests.helpers import StopLoop, ip_of, seed_devices, stored

pytestmark = pytest.mark.usefixtures("db")

DEVICES = 11  # the seeded tree
SW_OT = ip_of("sw-ot")
# sw-ot and the five devices behind it.
OT_TIER = ["sw-ot", "plc-conveyor-1", "hmi-panel-1", "ap-aisle-1", "ap-aisle-2", "scanner-1"]


class Simulation:
    """A clock and a network for the real poll loop."""

    def __init__(self) -> None:
        self.now = 0.0
        self.until = math.inf
        # When the pings of the pass now under way were sent.
        self.pass_started = 0.0
        # address -> the periods (from, until) in which it answers nothing.
        self.outages: dict[str, list[tuple[float, float]]] = {}
        # address -> (seconds its probe takes on top, in passes that start
        # before this time): a name lookup that hangs, say.
        self.delays: dict[str, tuple[float, float]] = {}
        # (address, pass start) -> how many of its pings get no reply in that
        # pass: the device fails while it is being pinged.
        self.partly: dict[tuple[str, float], int] = {}
        # time -> something that happens while the loop sleeps from then on
        # (an admin edits a device, say).
        self.meanwhile: dict[float, Callable[[], None]] = {}
        self.probes: list[tuple[float, str]] = []  # (pass start, address)
        self.sleeps: list[float] = []
        # After every pass: (time, {device: (confirmed, raw, failures in a row)}).
        self.seen: list[tuple[float, dict[str, tuple[str, str | None, int]]]] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        # The loop sleeps after every pass: that is when the pass is over.
        self.seen.append(
            (
                self.now,
                {
                    device_id: (status.status, status.raw_status, status.consecutive_failures)
                    for device_id, status in status_store.get_all().items()
                },
            )
        )
        self.sleeps.append(delay)
        self.meanwhile.pop(self.now, lambda: None)()
        self.now += delay
        self.pass_started = self.now
        if self.now >= self.until:
            raise StopLoop

    async def ping(
        self, address: str, count: int = 1, interval: float = 0.0, timeout: float = 2.0, privileged: bool = True
    ) -> Host:
        """One device's pings, as ``staggered_ping`` would send them: the last
        one leaves ``(count - 1) x interval`` after the first, and a device that
        answers nothing keeps it waiting for the timeout."""
        start = self.pass_started
        self.probes.append((start, address))
        silent = any(begin <= start < end for begin, end in self.outages.get(address, ()))
        lost = count if silent else self.partly.get((address, start), 0)
        extra, before = self.delays.get(address, (0.0, 0.0))
        took = (count - 1) * interval + (timeout if lost else 0.0) + (extra if start < before else 0.0)
        self.now = max(self.now, start + took)  # the pass lasts as long as its slowest device
        return Host(address, count, [1.0] * (count - lost))

    def silence(self, device_id: str, begin: float, end: float = math.inf) -> None:
        self.outages.setdefault(ip_of(device_id), []).append((begin, end))

    async def run(self, until: float, retry_interval: float | None = RETRY_INTERVAL_SECONDS) -> None:
        """Run the real loop until the clock reaches ``until``."""
        self.until = until
        try:
            await run_poll_loop(
                ping=self.ping, sleep=self.sleep, clock=self.clock, retry_interval=retry_interval
            )
        except StopLoop:
            pass

    def passes(self) -> list[tuple[float, int]]:
        """(when it started, how many devices it probed) for every pass."""
        starts = sorted({start for start, _ in self.probes})
        return [(start, sum(1 for began, _ in self.probes if began == start)) for start in starts]

    def probed_at(self, start: float) -> list[str]:
        return sorted(address for began, address in self.probes if began == start)

    def history(self, device_id: str) -> list[tuple[float, tuple[str, str | None, int]]]:
        """What was known about one device after every pass."""
        return [(at, statuses[device_id]) for at, statuses in self.seen]

    def confirmed_at(self, device_id: str, status: str) -> float:
        """When the device was first seen with this confirmed status."""
        return next(at for at, known in self.history(device_id) if known[0] == status)


def open_incidents() -> list[Incident]:
    with Session(engine) as session:
        return list(session.exec(select(Incident).where(Incident.state == "open")).all())


def store_settings(**values: float) -> None:
    with Session(engine) as session:
        row = session.exec(select(AppSettings)).one()
        for field, value in values.items():
            setattr(row, field, value)
        session.add(row)
        session.commit()


@pytest.fixture(autouse=True)
def pings_a_second_apart(db: None) -> None:
    store_settings(ping_gap_ms=1000)


# --- the fixed rate --------------------------------------------------------------


async def test_a_cycle_starts_every_poll_interval_whatever_the_pings_take():
    sim = Simulation()

    await sim.run(until=32)

    # Each pass takes 3 s, and the loop sleeps the 5 s that are left of the 8.
    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (16.0, DEVICES), (24.0, DEVICES)]
    assert sim.sleeps == [5.0, 5.0, 5.0, 5.0]


async def test_the_rate_holds_while_a_device_is_down():
    sim = Simulation()
    sim.silence("sw-ot", 0)

    await sim.run(until=32, retry_interval=None)

    # A pass with a silent device takes 5 s, not 3: the cycles still start 8 s
    # apart. (Before, the interval was added to it: one every 18.6 s.)
    assert [start for start, _ in sim.passes()] == [0.0, 8.0, 16.0, 24.0]
    assert sim.sleeps == [3.0, 3.0, 3.0, 3.0]


async def test_a_cycle_that_overruns_is_followed_at_once_and_the_rate_resumes():
    sim = Simulation()
    sim.delays[ip_of("fw-01")] = (9.0, 1.0)  # in the first cycle its probe takes 12 s

    await sim.run(until=30)

    # No sleep after the cycle that took longer than the interval: the next
    # one starts as it ends (the missed one is not run twice), and from there
    # the cycles are 8 s apart again.
    assert [start for start, _ in sim.passes()] == [0.0, 12.0, 20.0, 28.0]
    assert sim.sleeps == [0.0, 5.0, 5.0, 5.0]


# --- retry on suspect ------------------------------------------------------------


async def test_a_silent_device_is_confirmed_down_by_one_poll_and_two_more_results():
    sim = Simulation()
    sim.silence("sw-ot", 2)  # it stops answering just after the first cycle began

    await sim.run(until=36)

    assert sim.passes() == [
        (0.0, DEVICES),  # still answering
        (8.0, DEVICES),  # silent: over at 13, the first failure
        (14.0, 1),  # the retry, 1 s later: over at 19, the second
        (19.0, DEVICES),  # the cycle that was due at 16, as soon as the retry is over
        (27.0, DEVICES),
        (35.0, DEVICES),
    ]
    assert sim.probed_at(14.0) == [SW_OT]  # only the suspect is probed again
    assert sim.history("sw-ot") == [
        (3.0, ("healthy", "healthy", 0)),
        (13.0, ("healthy", "down", 1)),  # suspect
        (19.0, ("healthy", "down", 2)),  # still suspect, and the retry shows
        (24.0, ("down", "down", 3)),  # confirmed, 22 s after it fell silent
        (32.0, ("down", "down", 4)),
        (40.0, ("down", "down", 5)),
    ]


async def test_without_the_retry_the_same_outage_is_confirmed_later():
    sim = Simulation()
    sim.silence("sw-ot", 2)

    await sim.run(until=36, retry_interval=None)

    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (16.0, DEVICES), (24.0, DEVICES), (32.0, DEVICES)]
    assert sim.confirmed_at("sw-ot", "down") == 29.0  # 24 s with the retry


async def test_a_retry_stays_out_of_the_history_the_samples_and_the_detectors(monkeypatch):
    observed: list[int] = []
    completed: list[float] = []
    real_observe = poll_loop.anomaly_registry.observe
    sim = Simulation()

    def observe(readings, config):
        observed.append(len(readings))
        return real_observe(readings, config)

    monkeypatch.setattr(poll_loop.anomaly_registry, "observe", observe)
    monkeypatch.setattr(poll_health, "cycle_completed", lambda stale_after: completed.append(sim.now))
    sim.silence("sw-ot", 2)

    await sim.run(until=27)

    # Three cycles and one retry of sw-ot (see the test above)...
    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (14.0, 1), (19.0, DEVICES)]
    # ...and everything that expects one reading per cycle has three of sw-ot:
    assert len(history_store.get_history("sw-ot")) == 3
    assert [device_id for (device_id,) in stored(SAMPLES, "device_id")].count("sw-ot") == 3
    assert len(stored(SAMPLES, "device_id")) == 3 * DEVICES
    # the detectors were shown the three cycles, whole, and nothing else;
    assert observed == [DEVICES, DEVICES, DEVICES]
    # a device that was not retried kept its count of good polls across it;
    assert debouncer.get_states()["fw-01"].consecutive_successes == 3
    # and only a cycle counts as a completed poll for the health endpoint.
    assert completed == [3.0, 13.0, 24.0]


async def test_a_status_confirmed_by_a_retry_is_stored_and_raises_the_incident_at_once():
    sim = Simulation()
    sim.silence("sw-ot", 2)
    # With a failure threshold of 2 the retry itself is the confirming result.
    store_settings(failure_threshold=2)

    await sim.run(until=16)

    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (14.0, 1)]
    assert sim.history("sw-ot")[-1] == (19.0, ("down", "down", 2))
    # The change is stored with the time of the retry's reading, without a sample for it...
    retry_reading = status_store.get_all()["sw-ot"]
    assert stored(TRANSITIONS, "device_id", "ts", "from_status", "to_status") == [
        ("sw-ot", retry_reading.timestamp, "healthy", "down")
    ]
    assert len(stored(SAMPLES, "device_id")) == 2 * DEVICES
    # ...and the incident is open before the next cycle has run.
    assert [incident.root_device_id for incident in open_incidents()] == ["sw-ot"]


async def test_a_device_confirmed_by_a_retry_behind_a_failed_switch_is_collateral():
    sim = Simulation()
    sim.silence("sw-edge", 0)  # down from the start: a first result counts at once
    sim.silence("sw-ot", 2)  # the switch behind it follows
    store_settings(failure_threshold=2)  # so that sw-ot is confirmed by its retry

    await sim.run(until=16)

    # The retry pinged sw-ot only, but the incidents are judged on every
    # device: sw-ot is behind the switch that is already down, so it joins
    # that incident. Judged on its own it would look like a second root cause.
    assert sim.probed_at(14.0) == [SW_OT]
    assert sim.history("sw-ot")[-1] == (19.0, ("down", "down", 2))
    (incident,) = open_incidents()
    assert (incident.root_device_id, incident.affected_device_ids) == ("sw-edge", ["sw-ot"])


async def test_a_retry_that_gets_an_answer_ends_the_suspicion():
    sim = Simulation()
    sim.silence("sw-ot", 7, 9)  # silent for two seconds, around the second cycle

    await sim.run(until=32)

    # One retry, which is answered: no second one. It ran past the cycle that
    # was due at 16, which follows as soon as it is over.
    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (14.0, 1), (17.0, DEVICES), (25.0, DEVICES)]
    assert sim.history("sw-ot") == [
        (3.0, ("healthy", "healthy", 0)),
        (13.0, ("healthy", "down", 1)),
        (17.0, ("healthy", "healthy", 0)),  # the retry: 4 pings, all answered
        (20.0, ("healthy", "healthy", 0)),
        (28.0, ("healthy", "healthy", 0)),
    ]
    assert stored(TRANSITIONS, "device_id") == []


async def test_every_suspect_is_retried_in_the_same_pass_so_an_outage_is_still_one_incident():
    sim = Simulation()
    for device_id in OT_TIER:
        sim.silence(device_id, 2)

    await sim.run(until=27)

    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (14.0, 6), (19.0, DEVICES)]
    assert sim.probed_at(14.0) == sorted(ip_of(device_id) for device_id in OT_TIER)
    # All six are confirmed by the same pass, so the analysis sees the switch
    # and what is behind it together: one root cause, five collateral.
    assert {sim.confirmed_at(device_id, "down") for device_id in OT_TIER} == {24.0}
    (incident,) = open_incidents()
    assert incident.root_device_id == "sw-ot"
    assert sorted(incident.affected_device_ids) == sorted(OT_TIER[1:])


async def test_an_outage_that_begins_inside_a_probe_is_degraded_first_and_down_one_retry_later():
    sim = Simulation()
    sim.partly[(SW_OT, 8.0)] = 2  # it fails halfway through the cycle of 8: 2 of 4 pings lost
    sim.silence("sw-ot", 9)

    await sim.run(until=32)

    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (14.0, 1), (19.0, DEVICES), (25.0, 1), (30.0, DEVICES)]
    assert sim.history("sw-ot") == [
        (3.0, ("healthy", "healthy", 0)),
        (13.0, ("healthy", "degraded", 1)),  # half the pings lost: degraded, and suspect
        (19.0, ("healthy", "down", 2)),
        # Three results in a row are worse than healthy. The mildest of them is
        # confirmed; the device is still suspect, because its last result is worse...
        (24.0, ("degraded", "down", 3)),
        (30.0, ("down", "down", 4)),  # ...so it is retried once more: three times down
        (35.0, ("down", "down", 5)),
    ]
    assert stored(TRANSITIONS, "device_id", "from_status", "to_status") == [
        ("sw-ot", "healthy", "degraded"),
        ("sw-ot", "degraded", "down"),
    ]
    assert [incident.root_device_id for incident in open_incidents()] == ["sw-ot"]  # one incident for both


async def test_a_retry_pings_the_address_the_device_has_by_then():
    sim = Simulation()
    sim.silence("sw-ot", 2)

    def correct_the_address() -> None:
        # The admin sees the failed poll and gives the device the address it
        # really has, which answers.
        with Session(engine) as session:
            device = session.get(Device, "sw-ot")
            device.ip = "10.99.9.9"
            session.add(device)
            session.commit()

    sim.meanwhile[13.0] = correct_the_address  # between the cycle and its retry

    await sim.run(until=24)

    assert sim.probed_at(14.0) == ["10.99.9.9"]
    assert sim.history("sw-ot")[2] == (17.0, ("healthy", "healthy", 0))  # answered: no outage
    assert stored(TRANSITIONS, "device_id") == []
    assert open_incidents() == []


async def test_a_device_deleted_before_its_retry_is_not_pinged_again(caplog):
    sim = Simulation()
    sim.silence("scanner-1", 2)

    def delete_the_device() -> None:
        with Session(engine) as session:
            session.delete(session.get(Device, "scanner-1"))
            session.commit()

    sim.meanwhile[13.0] = delete_the_device

    await sim.run(until=32)

    # No pass at 14: the only suspect is gone. The cycles go on with ten devices.
    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (16.0, DEVICES - 1), (24.0, DEVICES - 1)]
    assert stored(TRANSITIONS, "device_id") == []
    assert "Status poll iteration failed" not in caplog.text


async def test_no_retry_is_started_once_the_next_cycle_is_due():
    sim = Simulation()
    sim.silence("sw-ot", 2)

    # A cycle with the silent device is over 5 s into the 8. A retry 3 s later
    # would start just as the next cycle is due: the cycle goes first.
    await sim.run(until=32, retry_interval=3.0)

    assert sim.passes() == [(0.0, DEVICES), (8.0, DEVICES), (16.0, DEVICES), (24.0, DEVICES)]
    assert sim.confirmed_at("sw-ot", "down") == 29.0


async def test_a_recovery_is_not_retried():
    sim = Simulation()
    sim.silence("sw-ot", 2, 40)

    await sim.run(until=64)

    # Down from 24 on (see above). It answers again from 40: the cycles of 43
    # and 51 find it healthy, and that is two in a row.
    assert [start for start, _ in sim.passes()] == [0.0, 8.0, 14.0, 19.0, 27.0, 35.0, 43.0, 51.0, 59.0]
    assert sim.confirmed_at("sw-ot", "down") == 24.0
    assert sim.history("sw-ot")[6:8] == [
        (46.0, ("down", "healthy", 0)),  # better than its status: not suspect
        (54.0, ("healthy", "healthy", 0)),
    ]


async def test_a_retry_keeps_what_the_detectors_found_at_the_last_cycle(monkeypatch):
    found = {"latency": MetricAnomaly(value=60.0, expected=10.0, score=5.0, since=datetime.now(timezone.utc))}

    def observe(readings, config):
        # The detectors find sw-ot's latency unusual at every cycle.
        return (
            [r.model_copy(update={"anomaly": found if r.device_id == "sw-ot" else None}) for r in readings],
            [],
            [],
        )

    monkeypatch.setattr(poll_loop.anomaly_registry, "observe", observe)
    sim = Simulation()
    sim.silence("sw-ot", 2)

    await sim.run(until=16)

    assert sim.probed_at(14.0) == [SW_OT]
    retried = status_store.get_all()["sw-ot"]
    assert (retried.raw_status, retried.consecutive_failures) == ("down", 2)  # the retry's reading
    assert retried.anomaly == found  # no detector saw it, and the badge does not flicker


async def test_with_the_default_gap_two_retries_start_before_the_next_cycle_is_due():
    store_settings(ping_gap_ms=200)  # the default: a pass takes 0.6 s, or 2.6 s with a silent device
    sim = Simulation()
    sim.silence("sw-ot", 2)

    await sim.run(until=24)

    # The cycle of 8 finds it silent (over at 10.6). Two retries start before
    # the cycle of 16 is due, at 11.6 and 15.2, and the second confirms the
    # outage at 17.8: 9.8 s after the cycle that first missed it. The cycle
    # that was due meanwhile follows at once.
    starts = [start for start, _ in sim.passes()]
    assert starts == pytest.approx([0.0, 8.0, 11.6, 15.2, 17.8])
    assert [probed for _, probed in sim.passes()] == [DEVICES, DEVICES, 1, 1, DEVICES]
    assert sim.confirmed_at("sw-ot", "down") == pytest.approx(17.8)
    assert [known for _, known in sim.history("sw-ot")][:4] == [
        ("healthy", "healthy", 0),
        ("healthy", "down", 1),
        ("healthy", "down", 2),
        ("down", "down", 3),
    ]


def test_the_real_loop_uses_the_staggered_ping_and_retries_after_a_second():
    parameters = inspect.signature(run_poll_loop).parameters

    assert parameters["ping"].default is staggered_ping
    assert parameters["retry_interval"].default == RETRY_INTERVAL_SECONDS == 1.0
    assert len(seed_devices()) == DEVICES
