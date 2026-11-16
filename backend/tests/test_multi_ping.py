"""Several probes per cycle: packet loss and jitter.

From the two formulas, through classification and the engine, to what the
poll loop stores and the API returns. Settings validation is in
test_settings.py, the rollup arithmetic in test_rollup.py.
"""

import itertools
import random
from datetime import datetime, timedelta, timezone

import pytest
from icmplib import Host, SocketPermissionError
from sqlmodel import Session, select

from app.core.config import Settings
from app.db.session import engine
from app.models.settings import AppSettings
from app.services.history_store import history_store
from app.services.persistence import ROLLUPS, SAMPLES, history_window, persist_cycle
from app.services.ping_engine import (
    DEFAULT_JITTER_WARN_MS,
    DEFAULT_LOSS_WARN_PCT,
    DEFAULT_PING_GAP_MS,
    DEFAULT_PINGS_PER_CYCLE,
    classify_probes,
    classify_status,
    jitter_ms,
    loss_pct,
    ping_one,
    probe_budget_problem,
)
from app.services.retention import run_retention
from app.services.status_store import status_store
from tests.helpers import FakePing, ip_of, make_status, restart_backend, run_cycles, stored

WARN, CRIT = 100.0, 500.0  # latency thresholds, as seeded
LOSS_WARN, JITTER_WARN = 20.0, 30.0  # as seeded


# =============================================================================
# The two formulas, on lists small enough to check by hand
# =============================================================================


@pytest.mark.parametrize(
    ("sent", "received", "expected"),
    [
        (4, 4, 0.0),
        (4, 3, 25.0),
        (4, 2, 50.0),
        (4, 1, 75.0),
        (4, 0, 100.0),
        (1, 1, 0.0),
        (1, 0, 100.0),
        (10, 9, 10.0),
        (10, 1, 90.0),
        (3, 2, pytest.approx(33.3333, abs=1e-4)),
        (0, 0, 100.0),  # nothing could be sent, so nothing got through
    ],
)
def test_loss_is_the_share_of_probes_without_a_reply(sent, received, expected):
    assert loss_pct(sent, received) == expected


@pytest.mark.parametrize(
    ("rtts", "expected"),
    [
        ([10.0, 12.0, 30.0], 10.0),  # |12-10| = 2 and |30-12| = 18: (2 + 18) / 2
        ([10.0, 10.0, 10.0, 10.0], 0.0),  # perfectly steady
        ([1.0, 2.0, 3.0, 4.0], 1.0),  # a steady climb: every step is 1
        ([10.0, 20.0, 10.0, 20.0], 10.0),  # bouncing between two values
        ([30.0, 10.0], 20.0),  # a drop counts like a rise
        ([1.5, 2.0, 1.0], 0.75),  # (0.5 + 1.0) / 2
        ([5.0, 105.0, 5.0, 5.0], pytest.approx(66.6667, abs=1e-4)),  # one spike: (100 + 100 + 0) / 3
    ],
)
def test_jitter_is_the_mean_absolute_difference_of_consecutive_round_trip_times(rtts, expected):
    assert jitter_ms(rtts) == expected


@pytest.mark.parametrize("rtts", [[], [12.5]], ids=["no-reply", "one-reply"])
def test_jitter_needs_two_round_trip_times(rtts):
    assert jitter_ms(rtts) is None


def test_jitter_depends_on_the_order_of_the_replies():
    assert jitter_ms([10.0, 12.0, 30.0]) == 10.0
    assert jitter_ms([10.0, 30.0, 12.0]) == 19.0  # the same three values: (20 + 18) / 2


def test_jitter_agrees_with_icmplib_on_random_lists():
    rng = random.Random(7)
    for _ in range(200):
        rtts = [rng.uniform(0.1, 300.0) for _ in range(rng.randint(2, 10))]
        # icmplib rounds its own figure to three decimals.
        assert jitter_ms(rtts) == pytest.approx(Host("10.0.0.1", len(rtts), rtts).jitter, abs=1e-3)


# =============================================================================
# Classification
# =============================================================================


def classify(
    pings: int = 4,
    reachable: bool = True,
    latency: float | None = 10.0,
    loss: float = 0.0,
    jitter: float | None = 1.0,
    loss_warn: float = LOSS_WARN,
    jitter_warn: float = JITTER_WARN,
) -> str:
    return classify_probes(pings, reachable, latency, loss, jitter, WARN, CRIT, loss_warn, jitter_warn)


def test_a_device_that_answers_every_probe_quickly_and_steadily_is_healthy():
    assert classify() == "healthy"


def test_no_reply_at_all_is_down():
    assert classify(reachable=False, latency=None, loss=100.0, jitter=None) == "down"


@pytest.mark.parametrize(
    ("loss", "expected"),
    [(0.0, "healthy"), (19.999, "healthy"), (20.0, "degraded"), (25.0, "degraded"), (75.0, "degraded")],
)
def test_loss_at_or_above_its_threshold_is_degraded(loss, expected):
    assert classify(loss=loss) == expected


@pytest.mark.parametrize(
    ("jitter", "expected"),
    [(0.0, "healthy"), (29.999, "healthy"), (30.0, "degraded"), (30.001, "degraded"), (400.0, "degraded")],
)
def test_jitter_at_or_above_its_threshold_is_degraded(jitter, expected):
    assert classify(jitter=jitter) == expected


@pytest.mark.parametrize(
    ("latency", "expected"),
    [(100.0, "healthy"), (100.001, "degraded"), (500.0, "degraded"), (500.001, "degraded")],
)
def test_average_latency_above_the_latency_thresholds_is_degraded_as_before(latency, expected):
    # Strictly above, unlike loss and jitter: the latency rule is the old one.
    assert classify(latency=latency) == expected


def test_jitter_that_could_not_be_measured_does_not_count_against_a_device():
    # One reply out of ten: no two round-trip times to compare.
    assert classify(pings=10, loss=90.0, jitter=None, loss_warn=95.0) == "healthy"


def test_the_thresholds_it_is_given_are_the_ones_it_uses():
    assert classify(loss=25.0, loss_warn=30.0) == "healthy"
    assert classify(loss=25.0, loss_warn=25.0) == "degraded"
    assert classify(jitter=40.0, jitter_warn=50.0) == "healthy"
    assert classify(jitter=40.0, jitter_warn=40.0) == "degraded"


def test_a_reply_without_a_round_trip_time_stays_unknown():
    assert classify(latency=None, loss=0.0, jitter=None) == "unknown"


def test_one_reason_is_enough_and_several_change_nothing():
    assert classify(latency=250.0, loss=50.0, jitter=80.0) == "degraded"
    assert classify(reachable=False, latency=250.0, loss=100.0, jitter=80.0) == "down"


# --- one probe per cycle: exactly what it was ------------------------------------

LATENCIES = [None, 0.0, 99.9, 100.0, 100.001, 499.0, 500.0, 500.001, 9999.0]


@pytest.mark.parametrize(("reachable", "latency"), list(itertools.product([True, False], LATENCIES)))
def test_with_one_probe_the_classification_is_exactly_the_old_one(reachable, latency):
    expected = classify_status(reachable, latency, WARN, CRIT)

    # Whatever loss and jitter say, and however low their thresholds are.
    for loss, jitter, loss_warn, jitter_warn in itertools.product(
        [0.0, 100.0], [None, 0.0, 500.0], [0.001, 20.0, 100.0], [0.001, 30.0]
    ):
        assert classify_probes(1, reachable, latency, loss, jitter, WARN, CRIT, loss_warn, jitter_warn) == expected


async def legacy_ping_one(ip: str, ping: FakePing) -> tuple[str, float | None]:
    """What ping_one did before there were several probes, kept here as the
    reference: one probe, and classify_status on the result."""
    try:
        host = await ping(ip, count=1, timeout=2.0, privileged=True)
        reachable = host.is_alive
        latency_ms = float(host.avg_rtt) if reachable and host.avg_rtt is not None else None
    except Exception:
        return "unknown", None
    return classify_status(reachable, latency_ms, WARN, CRIT), latency_ms


@pytest.mark.parametrize(
    "outcome",
    [
        (True, 12.5),
        (True, 100.0),
        (True, 250.0),
        (True, 600.0),
        (False, 0.0),
        (True, None),
        [3.2],  # as icmplib reports one answered probe
        [None],  # ... and one unanswered probe
        SocketPermissionError(privileged=True),
        OSError("Network is unreachable"),
    ],
    ids=["fast", "at-warn", "slow", "very-slow", "lost", "no-rtt", "host-reply", "host-lost", "no-permission", "os-error"],
)
async def test_with_one_probe_ping_one_does_what_it_always_did(outcome):
    old, new = FakePing(default=outcome), FakePing(default=outcome)
    expected = await legacy_ping_one("10.0.0.1", old)

    # Thresholds that would mark everything degraded, if they were looked at.
    status = await ping_one(
        "10.0.0.1", "dev-1", 2.0, True, WARN, CRIT, new, pings=1, loss_warn_pct=0.001, jitter_warn_ms=0.001
    )

    assert (status.status, status.latency_ms) == expected
    assert new.calls == old.calls == [("10.0.0.1", {"count": 1, "timeout": 2.0, "privileged": True})]


# =============================================================================
# The engine: one call, several probes
# =============================================================================


async def probe(replies: list[float | None], **kwargs):
    ping = FakePing(default=replies)
    status = await ping_one("10.0.0.1", "dev-1", 2.0, True, WARN, CRIT, ping, pings=len(replies), **kwargs)
    return status, ping


@pytest.mark.parametrize(
    ("replies", "status", "latency", "low", "high", "loss", "jitter"),
    [
        # All four answered, steadily.
        ([10.0, 12.0, 11.0, 12.0], "healthy", 11.25, 10.0, 12.0, 0.0, pytest.approx(4 / 3)),
        # One of four lost: 25% is over the 20% threshold. Jitter: (2 + 18) / 2.
        ([10.0, None, 12.0, 30.0], "degraded", 17.333, 10.0, 30.0, 25.0, 10.0),
        # Nothing lost, but the round-trip time swings by 70 ms each time.
        ([10.0, 80.0, 10.0, 80.0], "degraded", 45.0, 10.0, 80.0, 0.0, 70.0),
        # Steady and complete, but slow.
        ([150.0, 150.0, 150.0, 150.0], "degraded", 150.0, 150.0, 150.0, 0.0, 0.0),
        # A single reply: 75% loss, and no jitter to speak of.
        ([None, None, 9.0, None], "degraded", 9.0, 9.0, 9.0, 75.0, None),
        # No reply at all.
        ([None, None, None, None], "down", None, None, None, 100.0, None),
    ],
    ids=["steady", "one-lost", "jittery", "slow", "one-reply", "no-reply"],
)
async def test_ping_one_measures_latency_loss_and_jitter(replies, status, latency, low, high, loss, jitter):
    result, _ = await probe(replies)

    assert result.status == status
    assert (result.latency_ms, result.latency_min_ms, result.latency_max_ms) == (latency, low, high)
    assert (result.loss_pct, result.jitter_ms) == (loss, jitter)


async def test_ping_one_sends_the_probes_in_one_call_with_a_gap_between_them():
    _, ping = await probe([1.0] * 6, gap_seconds=0.35)

    assert ping.calls == [("10.0.0.1", {"count": 6, "interval": 0.35, "timeout": 2.0, "privileged": True})]


async def test_ping_one_uses_the_loss_and_jitter_thresholds_it_is_given():
    one_lost = [10.0, None, 12.0, 30.0]  # 25% loss, 10 ms jitter

    assert (await probe(one_lost, loss_warn_pct=25.1))[0].status == "healthy"
    assert (await probe(one_lost, loss_warn_pct=25.0))[0].status == "degraded"
    assert (await probe(one_lost, loss_warn_pct=50.0, jitter_warn_ms=10.0))[0].status == "degraded"


async def test_loss_is_counted_against_the_probes_that_were_actually_sent():
    # Two of the four probes could not be sent at all (icmplib leaves those
    # out of packets_sent); both that went out were answered.
    ping = FakePing(default=[10.0, 12.0])

    status = await ping_one("10.0.0.1", "dev-1", 2.0, True, WARN, CRIT, ping, pings=4)

    assert (status.status, status.loss_pct, status.jitter_ms) == ("healthy", 0.0, 2.0)


async def test_a_device_that_no_probe_could_be_sent_to_is_down():
    ping = FakePing(default=[])

    status = await ping_one("10.0.0.1", "dev-1", 2.0, True, WARN, CRIT, ping, pings=4)

    assert (status.status, status.latency_ms, status.loss_pct, status.jitter_ms) == ("down", None, 100.0, None)


async def test_a_probe_that_fails_measures_nothing():
    ping = FakePing(default=SocketPermissionError(privileged=True))

    status = await ping_one("10.0.0.1", "dev-1", 2.0, True, WARN, CRIT, ping, pings=4)

    assert status.status == "unknown"
    assert (status.latency_ms, status.latency_min_ms, status.latency_max_ms) == (None, None, None)
    assert (status.loss_pct, status.jitter_ms) == (None, None)


def test_the_fallback_defaults_are_the_seeded_ones():
    seeded = AppSettings()

    assert (DEFAULT_PINGS_PER_CYCLE, DEFAULT_PING_GAP_MS, DEFAULT_LOSS_WARN_PCT, DEFAULT_JITTER_WARN_MS) == (
        4, 200, 20.0, 30.0,
    )  # fmt: skip
    assert (seeded.pings_per_cycle, seeded.ping_gap_ms, seeded.loss_warn_pct, seeded.jitter_warn_ms) == (
        4, 200, 20.0, 30.0,
    )  # fmt: skip
    # So is the poll interval's, in the .env settings (this suite pins the
    # variable itself, so the default is read off the class).
    assert Settings.model_fields["PING_INTERVAL_SECONDS"].default == seeded.poll_interval_seconds == 8.0


# =============================================================================
# Do the probes fit in the poll interval?
# =============================================================================


@pytest.mark.parametrize(
    ("pings", "gap_ms", "timeout", "interval"),
    [
        (4, 200, 2.0, 8.0),  # the defaults: 2.8 s of the 6.4 s allowed
        (4, 200, 2.0, 5.0),  # the shortest poll interval: 2.8 s of 4 s
        (10, 200, 2.0, 5.0),  # exactly the 4 s allowed
        (1, 5000, 2.0, 10.0),  # 7 s of 8 s
    ],
)
def test_probes_that_fit_inside_80_percent_of_the_poll_interval_are_fine(pings, gap_ms, timeout, interval):
    assert probe_budget_problem(pings, gap_ms, timeout, interval) is None


def test_probes_that_do_not_fit_are_explained():
    assert probe_budget_problem(10, 700, 2.0, 10.0) == (
        "pings_per_cycle x ping_gap_ms + the ping timeout is 9 s (10 x 700 ms + 2 s), which does not "
        "fit comfortably inside the poll interval of 10 s: at most 8 s (80% of it). Lower "
        "pings_per_cycle or ping_gap_ms, or raise poll_interval_seconds."
    )


@pytest.mark.parametrize(
    ("pings", "gap_ms", "timeout", "interval"),
    [
        (10, 201, 2.0, 5.0),  # 4.01 s, a hair over 4 s
        (4, 200, 2.0, 3.4),  # 2.8 s of 2.72 s
        (4, 200, 8.0, 10.0),  # a long ping timeout uses the budget up: 8.8 s of 8 s
        (2, 5000, 2.0, 10.0),
    ],
)
def test_probes_that_take_more_than_80_percent_of_the_poll_interval_are_refused(pings, gap_ms, timeout, interval):
    assert probe_budget_problem(pings, gap_ms, timeout, interval) is not None


# =============================================================================
# The poll loop, the database and the API
# =============================================================================

ONE_LOST = [10.0, None, 12.0, 30.0]  # 25% loss, 10 ms jitter, 17.333 ms on average
HALF_LOST = [10.0, None, None, 12.0]  # 50% loss, 2 ms jitter
STEADY = [10.0, 12.0, 11.0, 12.0]  # no loss, 1.33 ms jitter


def set_settings(**fields) -> None:
    with Session(engine) as session:
        row = session.exec(select(AppSettings)).one()
        for field, value in fields.items():
            setattr(row, field, value)
        session.add(row)
        session.commit()


def snapshot(device_id: str):
    return status_store.get_all()[device_id]


@pytest.mark.usefixtures("db")
async def test_the_poll_loop_probes_with_the_stored_settings_and_re_reads_them_every_cycle(client, admin_headers):
    ping = FakePing(default=STEADY)

    def after_cycle(cycle: int) -> None:
        if cycle == 1:
            fields = {"pings_per_cycle": 2, "ping_gap_ms": 50}
            assert client.patch("/api/settings", headers=admin_headers, json=fields).status_code == 200

    await run_cycles(2, ping, after_cycle)

    first, second = ping.calls[0][1], ping.calls[-1][1]
    assert first == {"count": 4, "interval": 0.2, "timeout": 2.0, "privileged": True}
    assert second == {"count": 2, "interval": 0.05, "timeout": 2.0, "privileged": True}


@pytest.mark.usefixtures("db")
async def test_with_one_ping_per_cycle_the_poll_loop_behaves_as_it_did_before():
    # Thresholds that would mark everything degraded, if they were looked at.
    set_settings(pings_per_cycle=1, loss_warn_pct=0.001, jitter_warn_ms=0.001)
    ping = FakePing(default=(True, 12.0))
    ping.outcomes.update(
        {
            ip_of("sw-ot"): (False, 0.0),
            ip_of("srv-prod-1"): (True, 250.0),
            ip_of("scanner-1"): (True, None),
            ip_of("hmi-panel-1"): SocketPermissionError(privileged=True),
        }
    )

    await run_cycles(1, ping)

    # The same call as before this feature: one probe, and no interval.
    assert all(kwargs == {"count": 1, "timeout": 2.0, "privileged": True} for _, kwargs in ping.calls)
    statuses = {device_id: (status.status, status.latency_ms) for device_id, status in status_store.get_all().items()}
    assert statuses.pop("sw-ot") == ("down", None)
    assert statuses.pop("srv-prod-1") == ("degraded", 250.0)
    assert statuses.pop("scanner-1") == ("unknown", None)
    assert statuses.pop("hmi-panel-1") == ("unknown", None)
    assert set(statuses.values()) == {("healthy", 12.0)}


@pytest.mark.usefixtures("db")
async def test_the_status_reports_what_the_probes_measured(client, admin_headers):
    ping = FakePing(default=STEADY)
    ping.outcomes[ip_of("sw-ot")] = ONE_LOST
    ping.outcomes[ip_of("scanner-1")] = [None] * 4

    await run_cycles(1, ping)

    body = client.get("/api/status", headers=admin_headers).json()
    lossy, dead, fine = body["sw-ot"], body["scanner-1"], body["fw-01"]
    assert (lossy["status"], lossy["latency_ms"], lossy["latency_min_ms"], lossy["latency_max_ms"]) == (
        "degraded", 17.333, 10.0, 30.0,
    )
    assert (lossy["loss_pct"], lossy["jitter_ms"]) == (25.0, 10.0)
    assert (dead["status"], dead["latency_ms"], dead["loss_pct"], dead["jitter_ms"]) == ("down", None, 100.0, None)
    assert (fine["status"], fine["loss_pct"], fine["jitter_ms"]) == ("healthy", 0.0, pytest.approx(4 / 3))


@pytest.mark.usefixtures("db")
async def test_the_loss_and_jitter_thresholds_are_re_read_every_cycle(client, admin_headers):
    ping = FakePing(default=STEADY)
    ping.outcomes[ip_of("sw-ot")] = ONE_LOST  # 25% loss, 10 ms jitter, every cycle
    raw = []

    def after_cycle(cycle: int) -> None:
        raw.append(snapshot("sw-ot").raw_status)
        changes = {1: {"loss_warn_pct": 30}, 2: {"jitter_warn_ms": 10}, 3: {"jitter_warn_ms": 10.5}}
        if cycle in changes:
            assert client.patch("/api/settings", headers=admin_headers, json=changes[cycle]).status_code == 200

    await run_cycles(4, ping, after_cycle)

    assert raw == ["degraded", "healthy", "degraded", "healthy"]


@pytest.mark.usefixtures("db")
async def test_a_status_from_loss_goes_through_the_debouncer_like_any_other():
    ping = FakePing(default=STEADY)
    seen = []

    def after_cycle(cycle: int) -> None:
        status = snapshot("sw-ot")
        seen.append((status.status, status.raw_status, status.consecutive_failures))
        ping.outcomes[ip_of("sw-ot")] = HALF_LOST  # lossy from the second cycle on

    await run_cycles(4, ping, after_cycle)

    # Confirmed after three bad cycles in a row (the seeded failure threshold).
    assert seen == [
        ("healthy", "healthy", 0),
        ("healthy", "degraded", 1),
        ("healthy", "degraded", 2),
        ("degraded", "degraded", 3),
    ]


@pytest.mark.usefixtures("db")
async def test_loss_and_jitter_are_stored_with_every_sample_and_served_by_the_history_api(client, admin_headers):
    ping = FakePing(default=STEADY)
    ping.outcomes[ip_of("sw-ot")] = ONE_LOST

    await run_cycles(2, ping)

    rows = [row for row in stored(SAMPLES, "device_id", "latency_ms", "loss_pct", "jitter_ms") if row[0] == "sw-ot"]
    assert rows == [("sw-ot", 17.333, 25.0, 10.0)] * 2
    live = client.get("/api/history/sw-ot", headers=admin_headers).json()
    assert [(s["latency_ms"], s["loss_pct"], s["jitter_ms"]) for s in live] == [(17.333, 25.0, 10.0)] * 2
    hour = client.get("/api/history/sw-ot", headers=admin_headers, params={"window": "1h"}).json()
    assert [
        (p["latency_ms"], p["loss_pct"], p["loss_max_pct"], p["jitter_ms"], p["jitter_max_ms"]) for p in hour["points"]
    ] == [(17.333, 25.0, 25.0, 10.0, 10.0)] * 2

    restart_backend()  # the live history is refilled from the database
    assert [(s.loss_pct, s.jitter_ms) for s in history_store.get_history("sw-ot")] == [(25.0, 10.0)] * 2


# --- rollups ---------------------------------------------------------------------

NOW = datetime(2026, 11, 15, 12, 0, 30, tzinfo=timezone.utc)
OLD_MINUTE = datetime(2026, 11, 14, 11, 58, 0, tzinfo=timezone.utc)  # older than the 24 h of raw samples


def save_sample(device_id: str, at: datetime, latency: float | None, loss: float | None, jitter: float | None) -> None:
    reading = make_status(device_id, "healthy", latency, at).model_copy(update={"loss_pct": loss, "jitter_ms": jitter})
    persist_cycle([reading], [])


@pytest.mark.usefixtures("db")
def test_the_rollup_keeps_the_average_and_the_maximum_of_loss_and_jitter():
    second = timedelta(seconds=1)
    save_sample("fw-01", OLD_MINUTE, 10.0, 0.0, 2.0)
    save_sample("fw-01", OLD_MINUTE + 10 * second, 12.0, 25.0, 4.0)
    save_sample("fw-01", OLD_MINUTE + 20 * second, 9.0, 75.0, None)  # one reply: no jitter
    save_sample("fw-01", OLD_MINUTE + 30 * second, None, 100.0, None)  # no reply
    save_sample("fw-01", OLD_MINUTE + 40 * second, None, None, None)  # the probe itself failed

    run_retention(NOW)

    columns = ("sample_count", "fail_count", "loss_avg", "loss_max", "loss_count", "jitter_avg", "jitter_max", "jitter_count")
    # Loss over the four polls that measured it: (0 + 25 + 75 + 100) / 4.
    # Jitter over the two that did: (2 + 4) / 2.
    assert stored(ROLLUPS, *columns) == [(5, 2, 50.0, 100.0, 4, 3.0, 4.0, 2)]
    assert stored(SAMPLES, "id") == []


@pytest.mark.usefixtures("db")
def test_a_rollup_of_samples_from_before_loss_was_measured_has_none():
    save_sample("fw-01", OLD_MINUTE, 10.0, None, None)
    save_sample("fw-01", OLD_MINUTE + timedelta(seconds=10), 12.0, None, None)

    run_retention(NOW)

    columns = ("sample_count", "loss_avg", "loss_max", "loss_count", "jitter_avg", "jitter_max", "jitter_count")
    assert stored(ROLLUPS, *columns) == [(2, None, None, 0, None, None, 0)]


@pytest.mark.usefixtures("db")
def test_a_bucketed_window_shows_the_average_and_the_peak_of_loss_and_jitter():
    now = datetime.now(timezone.utc)
    slot = datetime.fromtimestamp(int(now.timestamp()) // 300 * 300 - 1800, tz=timezone.utc)  # a 5-minute slot, 30 min ago
    save_sample("fw-01", slot + timedelta(seconds=5), 10.0, 0.0, 1.0)
    save_sample("fw-01", slot + timedelta(seconds=65), 20.0, 50.0, 5.0)
    save_sample("fw-01", slot + timedelta(seconds=125), None, 100.0, None)

    out = history_window("fw-01", "24h", now)

    assert out.resolution == "5m"
    (point,) = out.points
    assert (point.sample_count, point.fail_count) == (3, 1)
    assert (point.loss_pct, point.loss_max_pct) == (50.0, 100.0)  # (0 + 50 + 100) / 3
    assert (point.jitter_ms, point.jitter_max_ms) == (3.0, 5.0)  # (1 + 5) / 2: the lost poll has none


@pytest.mark.usefixtures("db")
def test_history_from_before_loss_was_measured_reports_none():
    now = datetime.now(timezone.utc)
    save_sample("fw-01", now - timedelta(minutes=5), 10.0, None, None)

    raw = history_window("fw-01", "1h", now).points
    bucketed = history_window("fw-01", "24h", now).points

    for point in (*raw, *bucketed):
        assert (point.loss_pct, point.loss_max_pct, point.jitter_ms, point.jitter_max_ms) == (None, None, None, None)
