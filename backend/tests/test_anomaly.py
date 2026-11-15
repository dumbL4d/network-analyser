"""Anomaly detection: the two detectors, the registry that keeps one per
device and metric, and what the poll loop, the database and the API do with
their findings. The evaluation script is in test_eval_anomaly.py."""

import math
import random
import statistics
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from app.db.session import engine
from app.models.incident import Incident
from app.models.settings import AppSettings
from app.services.anomaly import (
    DETECTORS,
    WARMUP_SAMPLES,
    Detector,
    EwmaDetector,
    RollingZScoreDetector,
    Verdict,
    make_detector,
)
from app.services.anomaly.detectors import RELEARN_AFTER_SAMPLES
from app.services.anomaly.registry import METRICS, AnomalyConfig, AnomalyEnd, AnomalyRegistry, AnomalyStart, anomaly_registry
from app.services.persistence import ANOMALIES, SAMPLES, persist_cycle, recent_anomalies
from app.services.retention import run_retention
from app.services.status_store import status_store
from tests.helpers import FakePing, ip_of, make_status, restart_backend, run_cycles, stored

K, M = 3.0, 3


def ewma(alpha: float = 0.1, k: float = K, m: int = M, min_std: float = 0.5) -> EwmaDetector:
    return EwmaDetector(alpha, k, m, min_std)


def rolling(window: int = 200, k: float = K, m: int = M, min_std: float = 0.5) -> RollingZScoreDetector:
    return RollingZScoreDetector(window, k, m, min_std)


BOTH = pytest.mark.parametrize("make", [ewma, rolling], ids=["ewma", "rolling"])


def noise(n: int, mean: float = 10.0, std: float = 1.0, seed: int = 1) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(mean, std) for _ in range(n)]


def warmed_up(detector: Detector, readings: list[float] | None = None) -> Detector:
    """``detector`` after 200 quiet readings around 10 with a spread of about
    1: well past the warm-up, and enough to fill the rolling window, so that
    a few high readings do not move its baseline much."""
    for value in readings or noise(200):
        detector.update(value)
    return detector


def flags(detector: Detector, values: list[float]) -> list[bool]:
    return [detector.update(value).anomalous for value in values]


# =============================================================================
# What both detectors share
# =============================================================================


@BOTH
def test_nothing_is_judged_during_the_warm_up(make):
    detector = make()

    # Wild readings, and still no verdict: there is no baseline to judge by.
    verdicts = [detector.update(value) for value in [10.0, 5000.0, 10.0] * 10]

    assert WARMUP_SAMPLES == 30 and len(verdicts) == 30
    assert verdicts == [Verdict(anomalous=False, score=None, expected=None)] * 30


@BOTH
def test_the_first_reading_after_the_warm_up_is_judged(make):
    detector = warmed_up(make(), noise(WARMUP_SAMPLES))  # exactly thirty readings

    verdict = detector.update(10.0)

    assert verdict.score is not None and abs(verdict.score) < 1
    assert verdict.expected == pytest.approx(10.0, abs=0.5)
    assert verdict.anomalous is False


@BOTH
def test_a_warm_up_shorter_than_30_readings_is_refused(make):
    with pytest.raises(ValueError, match="at least 30"):
        type(make())(0.1 if make is ewma else 40, K, M, 0.5, warmup=29)


@BOTH
def test_a_longer_warm_up_can_be_asked_for(make):
    detector = type(make())(0.1 if make is ewma else 60, K, M, 0.5, warmup=50)

    scores = [detector.update(value).score for value in noise(51)]

    assert scores[:50] == [None] * 50 and scores[50] is not None


@BOTH
def test_it_takes_m_readings_in_a_row_above_the_threshold(make):
    detector = warmed_up(make())

    # Two high readings, a normal one, then three high ones.
    assert flags(detector, [30.0, 30.0, 10.0, 30.0, 30.0, 30.0]) == [False, False, False, False, False, True]


@BOTH
def test_an_anomaly_lasts_while_the_readings_stay_high_and_ends_with_the_first_normal_one(make):
    detector = warmed_up(make(m=2))

    assert flags(detector, [40.0, 40.0, 40.0, 40.0, 10.0, 10.0]) == [False, True, True, True, False, False]


@BOTH
def test_with_m_of_1_a_single_high_reading_is_enough(make):
    detector = warmed_up(make(m=1))

    assert flags(detector, [10.0, 40.0, 10.0]) == [False, True, False]


@BOTH
def test_only_readings_above_the_baseline_count(make):
    detector = warmed_up(make())

    verdicts = [detector.update(0.5) for _ in range(6)]  # far BELOW normal

    assert verdicts[0].score < -K  # as far out as an anomaly, on the other side
    assert not any(verdict.anomalous for verdict in verdicts)


@BOTH
def test_the_score_is_how_many_standard_deviations_above_the_mean_the_reading_is(make):
    readings = noise(WARMUP_SAMPLES)
    detector = warmed_up(make(), readings)
    mean, std = statistics.fmean(readings), statistics.pstdev(readings)

    verdict = detector.update(mean + 2 * std)

    assert verdict.score == pytest.approx(2.0)
    assert verdict.expected == pytest.approx(mean)


@BOTH
def test_a_score_of_exactly_k_is_not_above_the_threshold(make):
    # Readings of 8 and 12 in turn: mean 10, standard deviation exactly 2.
    detector = warmed_up(make(m=1), [8.0, 12.0] * 15)

    at_k = detector.update(16.0)  # exactly 3 standard deviations up

    assert at_k.score == pytest.approx(3.0) and at_k.anomalous is False


@BOTH
def test_just_over_k_is_above_the_threshold(make):
    detector = warmed_up(make(m=1), [8.0, 12.0] * 15)

    assert detector.update(16.01).anomalous is True


@BOTH
def test_a_flat_baseline_is_given_a_minimum_spread(make):
    # Thirty identical readings: a standard deviation of zero. Without the
    # floor, the smallest wobble would be infinitely many deviations out.
    small = warmed_up(make(m=1, min_std=1.0), [10.0] * 30).update(12.9)
    large = warmed_up(make(m=1, min_std=1.0), [10.0] * 30).update(13.1)

    assert small.score == pytest.approx(2.9) and small.anomalous is False
    assert large.score == pytest.approx(3.1) and large.anomalous is True


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"k": 0}, "k must be above 0"),
        ({"k": -1}, "k must be above 0"),
        ({"m": 0}, "m must be at least 1"),
        ({"min_std": 0}, "min_std must be above 0"),
    ],
)
@BOTH
def test_parameters_that_make_no_sense_are_refused(make, arguments, message):
    with pytest.raises(ValueError, match=message):
        make(**arguments)


def test_the_two_detectors_are_interchangeable():
    assert DETECTORS == ("ewma", "rolling")
    settings = {"k": 3.0, "m": 3, "alpha": 0.2, "window": 50, "min_std": 1.0}

    first, second = make_detector("ewma", **settings), make_detector("rolling", **settings)

    assert isinstance(first, EwmaDetector) and isinstance(second, RollingZScoreDetector)
    assert (first.alpha, second.window) == (0.2, 50)
    for detector in (first, second):
        assert isinstance(detector, Detector)
        assert (detector.k, detector.m, detector.min_std) == (3.0, 3, 1.0)
        assert isinstance(detector.update(1.0), Verdict)


def test_an_unknown_detector_is_refused():
    with pytest.raises(ValueError, match="unknown detector 'median'"):
        make_detector("median", k=3, m=3, alpha=0.1, window=60, min_std=1)


# =============================================================================
# EWMA: the formulas, and the frozen baseline
# =============================================================================


def test_the_ewma_warm_up_is_a_plain_mean_and_variance():
    readings = noise(WARMUP_SAMPLES, mean=20.0, std=3.0, seed=5)
    detector = warmed_up(ewma(alpha=0.02), readings)

    mean, std = detector._baseline()

    # Whatever alpha is: all thirty readings count the same.
    assert mean == pytest.approx(statistics.fmean(readings))
    assert std == pytest.approx(statistics.pstdev(readings))


def test_the_ewma_update_by_hand():
    # Warm-up of 8 and 12 in turn: mean 10, variance 4.
    detector = warmed_up(ewma(alpha=0.5), [8.0, 12.0] * 15)

    detector.update(12.0)  # a normal reading: one standard deviation up

    # mean     = 10 + 0.5 * (12 - 10)            = 11
    # variance = (1 - 0.5) * (4 + 0.5 * (12 - 10)^2) = 3
    mean, std = detector._baseline()
    assert (mean, std) == (pytest.approx(11.0), pytest.approx(math.sqrt(3.0)))


@pytest.mark.parametrize("alpha", [0.02, 0.1, 0.5])
def test_the_ewma_running_statistics_equal_a_recomputation_from_scratch(alpha):
    rng = random.Random(alpha)
    readings = [rng.uniform(5.0, 15.0) for _ in range(400)]
    # k so large that nothing is ever above the threshold: every reading is learned.
    detector = EwmaDetector(alpha, k=1e9, m=1, min_std=0.5)

    for count, reading in enumerate(readings, start=1):
        detector.update(reading)
        if count < WARMUP_SAMPLES or count % 37:
            continue
        # From scratch: the plain mean and variance of the warm-up, then every
        # later reading weighted by how long ago it was. O(n) each time.
        warm, later = readings[:WARMUP_SAMPLES], readings[WARMUP_SAMPLES:count]
        mean, variance = statistics.fmean(warm), statistics.pvariance(warm)
        means = [mean]
        for value in later:
            means.append(means[-1] + alpha * (value - means[-1]))
        n = len(later)
        expected_mean = (1 - alpha) ** n * mean + sum(
            alpha * (1 - alpha) ** (n - 1 - i) * value for i, value in enumerate(later)
        )
        expected_variance = (1 - alpha) ** n * variance + sum(
            alpha * (1 - alpha) ** (n - i) * (value - means[i]) ** 2 for i, value in enumerate(later)
        )
        got_mean, got_std = detector._baseline()
        assert got_mean == pytest.approx(expected_mean, rel=1e-9)
        assert got_std**2 == pytest.approx(expected_variance, rel=1e-9)


def test_the_ewma_baseline_is_frozen_while_the_readings_are_above_the_threshold():
    detector = warmed_up(ewma())
    before = detector._baseline()

    verdicts = [detector.update(50.0) for _ in range(200)]  # far above, for a long time

    # Not one of them was learned: the baseline is exactly what it was, and
    # every reading is still compared with it.
    assert detector._baseline() == before
    assert all(verdict.expected == before[0] for verdict in verdicts)
    assert [verdict.anomalous for verdict in verdicts] == [False, False] + [True] * 198


def test_the_ewma_baseline_does_not_learn_from_a_spike_too_short_to_be_flagged():
    detector = warmed_up(ewma())
    before = detector._baseline()

    assert flags(detector, [50.0, 50.0]) == [False, False]  # two readings, m is three

    assert detector._baseline() == before


def test_the_ewma_baseline_learns_again_once_the_readings_are_normal():
    detector = warmed_up(ewma())
    for _ in range(10):
        detector.update(50.0)
    frozen = detector._baseline()

    detector.update(10.5)  # within the threshold

    mean, _ = detector._baseline()
    assert mean == pytest.approx(frozen[0] + 0.1 * (10.5 - frozen[0]))


def test_the_ewma_baseline_follows_a_slow_change():
    detector = warmed_up(ewma(), [10.0 + 0.01 * step for step in range(30)])
    readings = [10.3 + 0.01 * step for step in range(2000)]  # climbs to 30 without ever jumping

    assert not any(flags(detector, readings))
    assert detector._baseline()[0] == pytest.approx(30.2, abs=0.2)


def test_the_ewma_detector_accepts_a_level_that_has_stayed_for_360_readings():
    assert RELEARN_AFTER_SAMPLES == 360  # 48 minutes, at the default of one reading every 8 seconds
    detector = warmed_up(ewma())
    frozen = detector._baseline()

    # A new level, for good. For 359 readings it is an anomaly, measured
    # against the baseline of before it began ...
    assert flags(detector, [25.0] * 359) == [False, False] + [True] * 357
    assert detector._baseline() == frozen
    # ... and so is the 360th, after which the detector starts over.
    assert detector.update(25.0).anomalous is True

    verdicts = [detector.update(25.0) for _ in range(100)]

    # Thirty readings of warm-up on the new level, and then it is normal.
    assert [verdict.score for verdict in verdicts[:30]] == [None] * 30
    assert [verdict.expected for verdict in verdicts[30:]] == [pytest.approx(25.0)] * 70
    assert not any(verdict.anomalous for verdict in verdicts)
    assert detector._baseline() == (pytest.approx(25.0), pytest.approx(0.0, abs=1e-9))


def test_one_reading_within_the_threshold_starts_the_count_towards_acceptance_again():
    detector = warmed_up(ewma())
    flags(detector, [25.0] * 359)

    detector.update(10.0)  # back to normal, for one reading
    result = flags(detector, [25.0] * 359)

    # 359 in a row, twice: never 360. Still an anomaly against the old baseline.
    assert result == [False, False] + [True] * 357
    assert detector._baseline()[0] == pytest.approx(10.0, abs=0.6)


def test_after_accepting_a_level_a_further_rise_stands_out_again():
    detector = warmed_up(ewma())
    flags(detector, [25.0] * 360)  # accepted
    flags(detector, [25.0] * 60)  # warmed up on it

    assert flags(detector, [25.0, 60.0, 60.0, 60.0, 25.0]) == [False, False, False, True, False]


def test_the_rolling_detector_never_starts_over():
    detector = warmed_up(rolling(window=1000), noise(1000))

    # Too little time for the window to fill with the new level; and unlike
    # the EWMA detector it has no other way of accepting it.
    result = flags(detector, [25.0] * 400)

    assert detector.seen == 1400 and len(detector._values) == 1000
    assert result[2] is True  # flagged where it began


@pytest.mark.parametrize("alpha", [0, -0.1, 1.01])
def test_alpha_must_be_above_0_and_at_most_1(alpha):
    with pytest.raises(ValueError, match="alpha must be above 0 and at most 1"):
        ewma(alpha=alpha)


# =============================================================================
# Rolling z-score: running sums over a window
# =============================================================================


@pytest.mark.parametrize("window", [30, 60, 250])
def test_the_rolling_sums_equal_a_recomputation_of_the_window(window):
    rng = random.Random(window)
    detector = RollingZScoreDetector(window, k=3, m=3, min_std=0.5)
    seen: list[float] = []

    for _ in range(2000):
        # Mostly quiet, sometimes far off: values that stress the subtraction.
        reading = rng.gauss(50.0, 5.0) + (rng.uniform(100, 5000) if rng.random() < 0.02 else 0)
        detector.update(reading)
        seen.append(reading)
        last = seen[-window:]  # what a naive detector would add up again, O(W) per reading
        mean, std = detector._baseline()
        assert mean == pytest.approx(statistics.fmean(last), rel=1e-9)
        assert std == pytest.approx(statistics.pstdev(last), rel=1e-6, abs=1e-6)


def test_the_rolling_window_never_holds_more_than_w_readings():
    detector = rolling(window=40)

    for reading in noise(1000):
        detector.update(reading)

    assert len(detector._values) == 40


def test_the_rolling_sums_do_not_drift_over_a_long_run():
    detector = rolling(window=60)
    readings = noise(100_000, mean=250.0, std=20.0, seed=3)

    for reading in readings:
        detector.update(reading)

    mean, std = detector._baseline()
    assert mean == pytest.approx(statistics.fmean(readings[-60:]), rel=1e-9)
    assert std == pytest.approx(statistics.pstdev(readings[-60:]), rel=1e-7)


def test_identical_readings_have_a_spread_of_practically_zero_whatever_the_rounding():
    # sum_of_squares / n - mean^2 is zero for identical readings, give or
    # take rounding. Give: a tiny spread. Take: the square root of a negative
    # number, unless it is clamped.
    rng = random.Random(8)
    for _ in range(300):
        constant = rng.uniform(0.01, 5000.0)
        detector = rolling(window=30)
        for _ in range(45):
            detector.update(constant)

        mean, std = detector._baseline()

        assert mean == pytest.approx(constant)
        assert 0.0 <= std < 1e-4 * constant


def test_the_rolling_detector_learns_from_anomalous_readings_too():
    detector = warmed_up(rolling(window=40), noise(40))
    before, _ = detector._baseline()

    result = flags(detector, [25.0] * 100)  # a new level, for good

    # Flagged where it began, and "normal" once the window is full of it.
    assert result[2] is True and not any(result[40:])
    assert detector._baseline()[0] == pytest.approx(25.0) and before == pytest.approx(10.0, abs=0.5)


def test_a_spike_in_the_window_hides_a_second_spike():
    quiet = noise(200, seed=9)
    spike = [60.0] * 5
    first_then_second = quiet[:60] + spike + quiet[60:80] + spike + quiet[80:120]

    alone = flags(warmed_up(rolling(window=40), quiet[:30]), quiet[30:80] + spike)
    masked = flags(warmed_up(rolling(window=40), quiet[:30]), first_then_second[30:])
    frozen = flags(warmed_up(ewma(), quiet[:30]), first_then_second[30:])

    assert any(alone[-5:])  # a spike on a clean window is caught
    assert any(masked[30:35]) and not any(masked[55:60])  # the second one, 20 readings later, is not
    assert any(frozen[30:35]) and any(frozen[55:60])  # the EWMA detector, whose baseline froze, catches both


@pytest.mark.parametrize("window", [29, 0])
def test_the_window_must_hold_at_least_the_warm_up(window):
    with pytest.raises(ValueError, match="window must hold at least the warm-up"):
        rolling(window=window)


# =============================================================================
# The registry: one detector per device and metric
# =============================================================================

T0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
CONFIG = AnomalyConfig()  # the seeded defaults: EWMA, k = 3, m = 3


def reading(device_id: str, latency: float | None, loss: float | None = 0.0, cycle: int = 0):
    status = "healthy" if latency is not None else "down"
    return make_status(device_id, status, latency, T0 + timedelta(seconds=10 * cycle)).model_copy(
        update={"loss_pct": loss}
    )


def feed(registry: AnomalyRegistry, cycles: list[list], config: AnomalyConfig = CONFIG) -> tuple[list, list, list]:
    """Run cycles of readings through the registry; the outcome of the last."""
    outcome = ([], [], [])
    for readings in cycles:
        outcome = registry.observe(readings, config)
    return outcome


def quiet_cycles(n: int, *device_ids: str, start: int = 0) -> list[list]:
    """``n`` cycles in which every device answers in about 10 ms, losing nothing."""
    rng = random.Random(4)
    return [
        [reading(device_id, rng.gauss(10.0, 1.0), cycle=start + cycle) for device_id in device_ids]
        for cycle in range(n)
    ]


def test_the_defaults_of_the_registry_are_the_seeded_settings():
    assert CONFIG == AnomalyConfig(enabled=True, detector="ewma", k=3.0, m=3, alpha=0.1, window=60)
    assert set(METRICS) == {"latency", "loss"}


def test_every_device_gets_a_detector_for_each_metric():
    registry = AnomalyRegistry()

    feed(registry, quiet_cycles(1, "fw-01", "sw-ot"))

    assert registry.detector_keys() == {
        ("fw-01", "latency"), ("fw-01", "loss"), ("sw-ot", "latency"), ("sw-ot", "loss"),
    }


def test_a_latency_anomaly_is_added_to_the_reading_and_reported_once():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01", "sw-ot"))
    high = [[reading("fw-01", 10.0, cycle=30 + n), reading("sw-ot", 60.0, cycle=30 + n)] for n in range(4)]

    outcomes = [registry.observe(cycle, CONFIG) for cycle in high]

    # Confirmed with the third high reading, and reported as begun only then.
    assert [len(started) for _, started, _ in outcomes] == [0, 0, 1, 0]
    assert [ended for _, _, ended in outcomes] == [[], [], [], []]
    (start,) = outcomes[2][1]
    assert (start.device_id, start.metric, start.detector, start.at, start.value) == (
        "sw-ot", "latency", "ewma", T0 + timedelta(seconds=320), 60.0,
    )
    assert start.expected == pytest.approx(10.0, abs=0.5) and start.score > 3

    for readings, _, _ in outcomes[2:]:
        quiet, anomalous = readings
        assert quiet.anomaly is None
        assert set(anomalous.anomaly) == {"latency"}
        finding = anomalous.anomaly["latency"]
        assert (finding.value, finding.since) == (60.0, T0 + timedelta(seconds=320))
        assert (finding.expected, finding.score) == (start.expected, start.score)


def test_the_readings_come_back_in_the_same_order_with_their_status_untouched():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01", "sw-ot"))
    cycle = [reading("sw-ot", 60.0), reading("fw-01", 10.0)]

    for _ in range(3):
        annotated, _, _ = registry.observe(cycle, CONFIG)

    assert [r.device_id for r in annotated] == ["sw-ot", "fw-01"]
    assert annotated[0].anomaly is not None
    # Everything but ``anomaly`` is what went in.
    assert [r.model_copy(update={"anomaly": None}) for r in annotated] == cycle


def test_an_anomaly_ends_with_the_first_normal_reading():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    feed(registry, [[reading("fw-01", 60.0, cycle=30 + n)] for n in range(3)])

    readings, started, ended = registry.observe([reading("fw-01", 10.0, cycle=33)], CONFIG)

    assert readings[0].anomaly is None and started == []
    assert ended == [AnomalyEnd("fw-01", "latency", T0 + timedelta(seconds=330))]


def test_packet_loss_has_its_own_detector_and_baseline():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    lossy = [[reading("fw-01", 10.0, loss=50.0, cycle=30 + n)] for n in range(3)]

    readings, started, _ = feed(registry, lossy)

    assert set(readings[0].anomaly) == {"loss"}
    assert [(s.metric, s.value, s.expected) for s in started] == [("loss", 50.0, 0.0)]


def test_a_little_loss_on_a_link_that_never_loses_anything_is_within_the_minimum_spread():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))  # a baseline of exactly 0% loss

    # 10% is 2 "standard deviations" of the 5-point floor; 25% is 5.
    below, _, _ = feed(registry, [[reading("fw-01", 10.0, loss=10.0)]] * 5)
    above, _, _ = feed(registry, [[reading("fw-01", 10.0, loss=25.0)]] * 3)

    assert below[0].anomaly is None and set(above[0].anomaly) == {"loss"}


def test_both_metrics_can_be_anomalous_at_once():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))

    readings, started, _ = feed(registry, [[reading("fw-01", 60.0, loss=75.0)]] * 3)

    assert set(readings[0].anomaly) == {"latency", "loss"}
    assert {s.metric for s in started} == {"latency", "loss"}


def test_a_poll_without_a_reply_is_not_judged_and_teaches_nothing():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    baseline = registry._detectors[("fw-01", "latency")]._baseline()
    loss_seen = registry._detectors[("fw-01", "loss")].seen

    readings, started, ended = feed(registry, [[reading("fw-01", None, loss=100.0)]] * 10)

    # 100% loss is "down", which is the status's business, not an anomaly.
    assert readings[0].anomaly is None and (started, ended) == ([], [])
    assert registry._detectors[("fw-01", "latency")]._baseline() == baseline
    assert registry._detectors[("fw-01", "loss")].seen == loss_seen


def test_an_anomaly_in_progress_ends_when_the_device_stops_answering():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    feed(registry, [[reading("fw-01", 60.0)]] * 3)

    readings, _, ended = registry.observe([reading("fw-01", None, loss=100.0, cycle=40)], CONFIG)

    assert readings[0].anomaly is None
    assert ended == [AnomalyEnd("fw-01", "latency", T0 + timedelta(seconds=400))]


def test_a_probe_that_failed_has_neither_latency_nor_loss_to_judge():
    registry = AnomalyRegistry()

    readings, started, ended = feed(registry, [[reading("fw-01", None, loss=None)]] * 40)

    assert readings[0].anomaly is None and (started, ended) == ([], [])
    assert registry.detector_keys() == set()  # nothing was ever measured


def test_a_level_that_stays_for_360_readings_ends_the_anomaly_and_becomes_the_baseline():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))

    outcomes = [registry.observe([reading("fw-01", 60.0, cycle=30 + n)], CONFIG) for n in range(361)]

    # One anomaly: it began with the third reading and ended with the 361st,
    # the first one after the detector had started over.
    assert [n for n, (_, started, _) in enumerate(outcomes) if started] == [2]
    assert [n for n, (_, _, ended) in enumerate(outcomes) if ended] == [360]
    assert outcomes[359][0][0].anomaly is not None and outcomes[360][0][0].anomaly is None

    # Once it has warmed up, 60 ms is what is normal, and a further rise stands out.
    settled, _, _ = feed(registry, [[reading("fw-01", 60.0)]] * 40)
    higher, started, _ = feed(registry, [[reading("fw-01", 150.0)]] * 3)
    assert settled[0].anomaly is None
    assert higher[0].anomaly["latency"].expected == pytest.approx(60.0) and len(started) == 1


def test_a_deleted_device_loses_its_detectors_in_the_next_cycle():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01", "sw-ot"))
    feed(registry, [[reading("fw-01", 10.0), reading("sw-ot", 60.0)]] * 3)  # sw-ot is anomalous

    _, started, ended = registry.observe([reading("fw-01", 10.0)], CONFIG)  # sw-ot is no longer polled

    assert registry.detector_keys() == {("fw-01", "latency"), ("fw-01", "loss")}
    assert started == [] and [(e.device_id, e.metric) for e in ended] == [("sw-ot", "latency")]

    # A device of the same name later starts from nothing.
    again, _, _ = feed(registry, [[reading("fw-01", 10.0), reading("sw-ot", 60.0)]] * 5)
    assert again[1].anomaly is None


@pytest.mark.parametrize(
    "change",
    [{"k": 4.0}, {"m": 2}, {"alpha": 0.2}, {"window": 90}, {"detector": "rolling"}],
    ids=lambda change: next(iter(change)),
)
def test_changing_a_setting_starts_every_detector_afresh(change):
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    feed(registry, [[reading("fw-01", 60.0)]] * 3)  # anomalous
    changed = AnomalyConfig(**{**CONFIG.__dict__, **change})

    readings, started, ended = registry.observe([reading("fw-01", 60.0)], changed)

    # The anomaly in progress ends, and the new detector is warming up.
    assert readings[0].anomaly is None and started == []
    assert [(e.device_id, e.metric) for e in ended] == [("fw-01", "latency")]
    assert registry._detectors[("fw-01", "latency")].seen == 1
    expected_type = RollingZScoreDetector if changed.detector == "rolling" else EwmaDetector
    assert type(registry._detectors[("fw-01", "latency")]) is expected_type


def test_the_same_settings_again_change_nothing():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))

    registry.observe([reading("fw-01", 10.0)], AnomalyConfig())  # an equal config, another object

    assert registry._detectors[("fw-01", "latency")].seen == 31


def test_switched_off_nothing_is_detected_and_no_detector_is_kept():
    registry = AnomalyRegistry()
    feed(registry, quiet_cycles(30, "fw-01"))
    feed(registry, [[reading("fw-01", 60.0)]] * 3)  # anomalous
    off = AnomalyConfig(enabled=False)
    cycle = [reading("fw-01", 60.0)]

    readings, started, ended = registry.observe(cycle, off)

    assert readings == cycle and started == []
    assert [(e.device_id, e.metric) for e in ended] == [("fw-01", "latency")]  # the one in progress ends
    assert registry.detector_keys() == set()
    assert registry.observe(cycle, off) == (cycle, [], [])


def test_an_anomaly_names_the_detector_that_found_it():
    registry = AnomalyRegistry()
    config = AnomalyConfig(detector="rolling", window=30)
    feed(registry, quiet_cycles(30, "fw-01"), config)

    _, started, _ = feed(registry, [[reading("fw-01", 60.0)]] * 3, config)

    assert [(start.metric, start.detector) for start in started] == [("latency", "rolling")]


def test_the_registry_uses_the_detector_and_the_parameters_it_is_told_to():
    registry = AnomalyRegistry()
    config = AnomalyConfig(detector="rolling", k=2.5, m=4, alpha=0.3, window=45)

    feed(registry, quiet_cycles(1, "fw-01"), config)

    latency, loss = registry._detectors[("fw-01", "latency")], registry._detectors[("fw-01", "loss")]
    assert isinstance(latency, RollingZScoreDetector)
    assert (latency.window, latency.k, latency.m) == (45, 2.5, 4)
    # The smallest spread a baseline gets credit for: 1 ms, and 5 points of loss.
    assert (latency.min_std, loss.min_std) == (1.0, 5.0)

    feed(registry, quiet_cycles(1, "fw-01"), AnomalyConfig(alpha=0.3))
    assert registry._detectors[("fw-01", "latency")].alpha == 0.3


# =============================================================================
# The poll loop, the database and the API
# =============================================================================

QUIET = [10.0, 11.0, 10.0, 11.0]  # the four probes of a cycle: about 10.5 ms, nothing lost
SLOW = [60.0, 61.0, 60.0, 61.0]  # far above that, and still far below the 100 ms warn threshold


def set_settings(**fields) -> None:
    with Session(engine) as session:
        row = session.exec(select(AppSettings)).one()
        for field, value in fields.items():
            setattr(row, field, value)
        session.add(row)
        session.commit()


async def warm_up(ping: FakePing, cycles: int = 30) -> None:
    await run_cycles(cycles, ping)


def events(*columns: str) -> list[tuple]:
    return stored(ANOMALIES, *columns)


@pytest.mark.usefixtures("db")
async def test_an_anomaly_is_advisory_it_changes_no_status_and_opens_no_incident(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW

    await run_cycles(5, ping)

    status = status_store.get_all()["sw-ot"]
    assert set(status.anomaly) == {"latency"}
    # The status is what it would be without any detector: confirmed and raw.
    assert (status.status, status.raw_status, status.consecutive_failures) == ("healthy", "healthy", 0)
    assert client.get("/api/incidents", headers=admin_headers).json() == []
    assert client.get("/api/incidents/history", headers=admin_headers).json()["total"] == 0
    with Session(engine) as session:
        assert session.exec(select(Incident)).all() == []
    assert client.get("/api/flaps", headers=admin_headers).json()[0]["flap_count"] == 0


@pytest.mark.usefixtures("db")
async def test_the_snapshot_says_what_is_unusual_and_since_when(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW
    await run_cycles(3, ping)

    body = client.get("/api/status", headers=admin_headers).json()

    assert body["fw-01"]["anomaly"] is None
    anomaly = body["sw-ot"]["anomaly"]
    assert set(anomaly) == {"latency"} and set(anomaly["latency"]) == {"value", "expected", "score", "since"}
    assert anomaly["latency"]["value"] == 60.5
    assert anomaly["latency"]["expected"] == pytest.approx(10.5)
    assert anomaly["latency"]["score"] == pytest.approx(50.0)  # 50 ms over, with the 1 ms floor
    assert anomaly["latency"]["since"] == body["sw-ot"]["timestamp"]  # confirmed in this very cycle


@pytest.mark.usefixtures("db")
async def test_an_anomaly_is_stored_when_it_begins_and_closed_when_it_ends(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW
    await run_cycles(4, ping)

    (open_event,) = client.get("/api/anomalies", headers=admin_headers).json()
    assert set(open_event) == {
        "id", "device_id", "metric", "detector", "started_at", "ended_at", "value", "expected", "score",
    }
    assert (open_event["device_id"], open_event["metric"], open_event["detector"]) == ("sw-ot", "latency", "ewma")
    assert (open_event["value"], open_event["ended_at"]) == (60.5, None)
    assert open_event["started_at"].endswith("Z")

    ping.outcomes[ip_of("sw-ot")] = QUIET
    await run_cycles(1, ping)

    (closed,) = client.get("/api/anomalies", headers=admin_headers).json()
    assert closed["id"] == open_event["id"] and closed["started_at"] == open_event["started_at"]
    assert closed["ended_at"] > closed["started_at"]
    assert status_store.get_all()["sw-ot"].anomaly is None


@pytest.mark.usefixtures("db")
async def test_anomalies_are_listed_newest_first_and_can_be_narrowed_to_a_device(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    for device_id in ("sw-ot", "fw-01", "scanner-1"):  # one after the other
        ping.outcomes[ip_of(device_id)] = SLOW
        await run_cycles(3, ping)

    def listed(**params) -> list[str]:
        response = client.get("/api/anomalies", headers=admin_headers, params=params)
        assert response.status_code == 200
        return [event["device_id"] for event in response.json()]

    assert listed() == ["scanner-1", "fw-01", "sw-ot"]
    assert listed(limit=2) == ["scanner-1", "fw-01"]
    assert listed(device_id="fw-01") == ["fw-01"]
    assert listed(device_id="no-such-device") == []


@pytest.mark.parametrize("limit", [0, 201, "all"])
def test_the_limit_of_the_anomaly_list_is_1_to_200(client, admin_headers, limit):
    assert client.get("/api/anomalies", headers=admin_headers, params={"limit": limit}).status_code == 422


def test_a_viewer_can_read_the_anomalies(client, viewer_headers):
    assert client.get("/api/anomalies", headers=viewer_headers).json() == []


@pytest.mark.usefixtures("db")
async def test_the_anomaly_settings_are_re_read_every_cycle(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW
    await run_cycles(3, ping)
    assert status_store.get_all()["sw-ot"].anomaly is not None

    assert client.patch("/api/settings", headers=admin_headers, json={"anomaly_enabled": False}).status_code == 200
    await run_cycles(1, ping)

    assert status_store.get_all()["sw-ot"].anomaly is None
    assert anomaly_registry.detector_keys() == set()
    assert [ended_at is not None for (ended_at,) in events("ended_at")] == [True]  # the open event was closed

    # Switched on again with the rolling detector: it warms up from nothing.
    settings = {"anomaly_enabled": True, "anomaly_detector": "rolling", "anomaly_window": 30}
    assert client.patch("/api/settings", headers=admin_headers, json=settings).status_code == 200
    await run_cycles(1, ping)

    detector = anomaly_registry._detectors[("sw-ot", "latency")]
    assert isinstance(detector, RollingZScoreDetector) and (detector.window, detector.seen) == (30, 1)


@pytest.mark.usefixtures("db")
async def test_with_detection_switched_off_the_poll_loop_finds_and_stores_nothing():
    set_settings(anomaly_enabled=False)
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW

    await run_cycles(5, ping)

    assert all(status.anomaly is None for status in status_store.get_all().values())
    assert events("id") == []


@pytest.mark.usefixtures("db")
async def test_deleting_a_device_drops_its_detectors(client, admin_headers):
    ping = FakePing(default=QUIET)
    await warm_up(ping, cycles=2)
    assert ("scanner-1", "latency") in anomaly_registry.detector_keys()

    assert client.delete("/api/devices/scanner-1", headers=admin_headers).status_code == 204
    await run_cycles(1, ping)

    assert {device_id for device_id, _ in anomaly_registry.detector_keys()} == {
        device["id"] for device in client.get("/api/devices", headers=admin_headers).json()
    }
    assert len(anomaly_registry.detector_keys()) == 10 * 2  # ten devices left, two metrics each


@pytest.mark.usefixtures("db")
async def test_an_anomaly_still_open_at_a_restart_is_closed():
    ping = FakePing(default=QUIET)
    await warm_up(ping)
    ping.outcomes[ip_of("sw-ot")] = SLOW
    await run_cycles(4, ping)
    assert events("ended_at") == [(None,)]
    newest_sample = max(ts for (ts,) in stored(SAMPLES, "ts"))

    anomaly_registry.__init__()  # the detectors live in memory: a restart empties them
    restart_backend()

    # Closed at the last moment anything was measured.
    assert events("ended_at") == [(newest_sample,)]
    # And afterwards the same level is not reported until the detector has warmed up again.
    await run_cycles(5, ping)
    assert status_store.get_all()["sw-ot"].anomaly is None and len(events("id")) == 1


@pytest.mark.usefixtures("db")
def test_a_restart_closes_the_open_events_and_leaves_the_closed_ones_alone():
    def start(device_id: str) -> AnomalyStart:
        return AnomalyStart(device_id, "latency", "rolling", T0, 60.0, 10.0, 50.0)

    persist_cycle([reading("fw-01", 10.0, cycle=90)], [], [start("fw-01"), start("sw-ot")], [])
    persist_cycle([], [], [], [AnomalyEnd("fw-01", "latency", T0 + timedelta(minutes=5))])

    restart_backend()

    assert events("device_id", "detector", "ended_at") == [
        ("fw-01", "rolling", T0 + timedelta(minutes=5)),  # as it was
        ("sw-ot", "rolling", T0 + timedelta(seconds=900)),  # closed at the newest sample
    ]


@pytest.mark.usefixtures("db")
def test_anomaly_events_are_kept_as_long_as_status_transitions():
    now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    def start(days_ago: float) -> AnomalyStart:
        return AnomalyStart("fw-01", "latency", "ewma", now - timedelta(days=days_ago), 60.0, 10.0, 50.0)

    persist_cycle([], [], [start(31), start(29)], [])

    report = run_retention(now)  # TRANSITION_RETENTION_DAYS is 30

    assert report.anomalies_deleted == 1
    assert events("started_at") == [(now - timedelta(days=29),)]


@pytest.mark.usefixtures("db")
def test_an_end_closes_the_open_event_of_that_device_and_metric_only():
    def start(device_id: str, metric: str, minutes: int) -> AnomalyStart:
        return AnomalyStart(device_id, metric, "ewma", T0 + timedelta(minutes=minutes), 60.0, 10.0, 50.0)

    persist_cycle([], [], [start("fw-01", "latency", 0), start("fw-01", "loss", 0), start("sw-ot", "latency", 0)], [])
    persist_cycle([], [], [], [AnomalyEnd("fw-01", "latency", T0 + timedelta(minutes=5))])
    # The same device and metric again: one cycle ends nothing and begins a new event.
    persist_cycle(
        [], [], [start("fw-01", "latency", 9)], [AnomalyEnd("fw-01", "latency", T0 + timedelta(minutes=9))]
    )

    assert events("device_id", "metric", "started_at", "ended_at") == [
        ("fw-01", "latency", T0, T0 + timedelta(minutes=5)),
        ("fw-01", "loss", T0, None),
        ("sw-ot", "latency", T0, None),
        ("fw-01", "latency", T0 + timedelta(minutes=9), None),
    ]
    assert [row.device_id for row in recent_anomalies("fw-01")] == ["fw-01"] * 3
    assert [row.metric for row in recent_anomalies(limit=1)] == ["latency"]
