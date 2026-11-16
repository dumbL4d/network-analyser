"""The evaluation script (scripts/eval_anomaly.py): the trace generators, the
scoring, and that the figures in docs/anomaly-evaluation.md are what it
prints. No database, no network."""

import re
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.anomaly import WARMUP_SAMPLES
from app.services.anomaly.registry import METRICS, AnomalyConfig
from scripts import eval_anomaly as ev

BACKEND = Path(__file__).resolve().parents[1]
REPORT = BACKEND.parent / "docs" / "anomaly-evaluation.md"


# =============================================================================
# The trace generators
# =============================================================================


def test_the_same_seed_gives_the_same_trace_and_another_seed_another():
    config = ev.TraceConfig(samples=5000, diurnal_amplitude=8.0, glitch_rate=0.01)

    first, again, other = (ev.generate_trace(config, seed) for seed in (7, 7, 8))

    assert (first.values, first.events) == (again.values, again.events)
    assert first.values != other.values and first.events != other.events


def test_the_ground_truth_is_in_time_order_inside_the_trace_and_never_overlaps():
    config = ev.TraceConfig(samples=30_000)
    trace = ev.generate_trace(config, 3)

    assert len(trace.values) == 30_000 and len(trace.events) > 20
    assert {event.kind for event in trace.events} == set(ev.KINDS)
    previous_end = config.lead_in
    for event in trace.events:
        low, high = getattr(config, f"{event.kind}_length")
        assert low <= event.end - event.start <= high
        assert event.start >= previous_end + config.min_gap  # room between two anomalies
        assert event.end <= config.samples
        previous_end = event.end


def test_the_anomalies_are_in_the_readings_where_the_ground_truth_says():
    config = ev.TraceConfig(samples=30_000)  # base 20 ms, noise 2 ms
    trace = ev.generate_trace(config, 3)
    inside = {t for event in trace.events for t in range(event.start, event.end)}
    normal = [value for t, value in enumerate(trace.values) if t not in inside]

    assert statistics.fmean(normal) == pytest.approx(20.0, abs=0.1)
    assert statistics.pstdev(normal) == pytest.approx(2.0, abs=0.1)
    for event in trace.events:
        readings = trace.values[event.start : event.end]
        if event.kind == "drift":
            # Climbs: it begins near normal and ends at least 6 noise widths up.
            assert statistics.fmean(readings[:20]) < 24.0
            assert statistics.fmean(readings[-20:]) > 20.0 + 5 * 2.0
        else:
            low, _ = getattr(config, f"{event.kind}_height")
            assert statistics.fmean(readings) > 20.0 + (low - 3) * 2.0


def test_the_daily_rhythm_raises_and_lowers_the_baseline():
    config = ev.TraceConfig(samples=ev.SAMPLES_PER_DAY, diurnal_amplitude=8.0, mean_gap=1e9)  # no anomalies
    values = ev.generate_trace(config, 1).values
    quarter = ev.SAMPLES_PER_DAY // 4

    peak = statistics.fmean(values[quarter - 200 : quarter + 200])
    trough = statistics.fmean(values[3 * quarter - 200 : 3 * quarter + 200])

    assert peak == pytest.approx(28.0, abs=0.5) and trough == pytest.approx(12.0, abs=0.5)


def test_glitches_are_single_readings_and_not_in_the_ground_truth():
    quiet = ev.TraceConfig(samples=20_000, mean_gap=1e9)  # no anomalies
    values = ev.generate_trace(ev.TraceConfig(**{**quiet.__dict__, "glitch_rate": 0.01}), 5)

    far_off = [t for t, value in enumerate(values.values) if value > 20.0 + 6 * 2.0]

    assert values.events == []
    assert 150 < len(far_off) < 250  # about 1% of 20000
    assert ev.generate_trace(quiet, 5).events == [] and max(ev.generate_trace(quiet, 5).values) < 32.0


def test_a_loss_trace_is_in_steps_of_a_quarter_and_lossy_where_the_ground_truth_says():
    config = ev.LossConfig(samples=30_000)
    trace = ev.generate_loss_trace(config, 2)
    inside = {t for event in trace.events for t in range(event.start, event.end)}

    assert set(trace.values) <= {0.0, 25.0, 50.0, 75.0, None}  # None: all four probes lost
    assert {event.kind for event in trace.events} == {"step"} and len(trace.events) > 20
    normal = [value for t, value in enumerate(trace.values) if t not in inside and value is not None]
    lossy = [value for t, value in enumerate(trace.values) if t in inside and value is not None]
    assert statistics.fmean(normal) == pytest.approx(1.0, abs=0.3)  # 1% of the probes
    assert statistics.fmean(lossy) > 20.0
    assert ev.generate_loss_trace(config, 2).values == trace.values  # deterministic


# =============================================================================
# The scoring
# =============================================================================


def flags_from(length: int, *runs: tuple[int, int]) -> list[bool]:
    flags = [False] * length
    for start, end in runs:
        flags[start:end] = [True] * (end - start)
    return flags


def test_alarms_are_the_runs_of_flagged_readings():
    flags = flags_from(12, (0, 2), (5, 6), (9, 12))

    assert ev.alarms_of(flags) == [(0, 2), (5, 6), (9, 12)]
    assert ev.alarms_of([False] * 5) == [] and ev.alarms_of([True] * 5) == [(0, 5)]


def test_the_metrics_on_a_case_worked_out_by_hand():
    events = [ev.Event("spike", 10, 14), ev.Event("step", 20, 30), ev.Event("drift", 34, 38)]
    # A false alarm; one inside the spike; one that begins in the step's last
    # reading and runs on after it. Nothing during the drift.
    flags = flags_from(40, (5, 7), (11, 13), (29, 33))

    result = ev.score(flags, events)

    assert (result.alarms, result.false_alarms) == (3, 1)
    assert result.precision == pytest.approx(2 / 3)
    assert result.caught == {"spike": 1, "step": 1, "drift": 0} and result.recall == pytest.approx(2 / 3)
    assert (result.recall_of("spike"), result.recall_of("drift")) == (1.0, 0.0)
    assert result.mean_delay == pytest.approx((1 + 9) / 2)  # readings 11 and 29, events from 10 and 20
    assert result.normal_samples == 40 - 4 - 10 - 4
    assert result.false_alarms_per_1000 == pytest.approx(1000 / 22)
    assert result.step_coverage == pytest.approx(1 / 10)  # one of the step's ten readings


def test_an_alarm_that_only_begins_after_an_anomaly_has_ended_is_a_false_alarm():
    result = ev.score(flags_from(30, (14, 16)), [ev.Event("spike", 10, 14)])

    assert (result.alarms, result.false_alarms, result.caught["spike"]) == (1, 1, 0)


def test_one_long_alarm_over_two_anomalies_catches_both_and_is_one_alarm():
    result = ev.score(flags_from(40, (8, 30)), [ev.Event("spike", 10, 14), ev.Event("step", 20, 28)])

    assert (result.alarms, result.false_alarms) == (1, 0)
    assert result.caught == {"spike": 1, "step": 1, "drift": 0}
    assert result.mean_delay == 0.0  # already flagged when each began


def test_metrics_that_cannot_be_computed_are_left_empty():
    silent = ev.score([False] * 20, [ev.Event("spike", 5, 8)])
    nothing_to_find = ev.score([False] * 20, [])

    assert (silent.precision, silent.recall, silent.mean_delay) == (None, 0.0, None)
    assert silent.false_alarms_per_1000 == 0.0
    assert (nothing_to_find.recall, nothing_to_find.step_coverage) == (None, None)


def test_scores_of_several_traces_add_up():
    total = ev.Score()
    total += ev.score(flags_from(40, (11, 13)), [ev.Event("spike", 10, 14)])
    total += ev.score(flags_from(40, (2, 4)), [ev.Event("spike", 10, 14), ev.Event("step", 20, 30)])

    assert total.events == {"spike": 2, "step": 1, "drift": 0}
    assert (total.alarms, total.false_alarms, total.recall) == (2, 1, pytest.approx(1 / 3))
    assert total.normal_samples == 36 + 26 and total.step_samples == 10


def test_a_poll_without_a_reading_is_neither_shown_to_the_detector_nor_flagged():
    detector = ev.StaticThresholdDetector(k=3, m=1, min_std=1.0)
    values = [10.0] * 30 + [None, 50.0, None, 50.0]

    assert ev.run(detector, values)[-4:] == [False, True, False, True]
    assert detector.seen == 32


def test_the_static_threshold_is_set_during_the_warm_up_and_never_moves():
    detector = ev.StaticThresholdDetector(k=3, m=3, min_std=0.5)
    for value in [8.0, 12.0] * 15:
        detector.update(value)
    assert detector._baseline() == (pytest.approx(10.0), pytest.approx(2.0))

    for _ in range(500):
        detector.update(100.0)  # a new level for good: it is never learned

    assert detector._baseline() == (pytest.approx(10.0), pytest.approx(2.0))


# =============================================================================
# The script as a whole
# =============================================================================

SMALL = ["--traces", "1", "--samples", "4000"]


def rows(table: str) -> list[list[str]]:
    """The data rows of the Markdown tables, cell by cell."""
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in table.splitlines()
        if line.startswith("|") and not line.startswith("| ---") and not line.startswith("| Scenario")
    ]


def test_the_evaluation_runs_and_is_deterministic_for_a_seed():
    first = ev.main(SMALL)

    assert ev.main(SMALL) == first
    assert ev.main([*SMALL, "--seed", "43"]) != first

    table = rows(first)
    assert len(table) == 2 * len(ev.SCENARIOS) * 3  # two tables, three detectors per scenario
    assert {row[0] for row in table} == set(ev.SCENARIOS)
    assert {row[1] for row in table} == {"static threshold", "EWMA (alpha 0.1)", "rolling z-score (W 60)"}
    for _, _, precision, recall, delay, false_alarms in table[: len(table) // 2]:
        assert 0.0 <= float(recall) <= 1.0 and float(false_alarms) >= 0.0
        assert precision == "n/a" or 0.0 <= float(precision) <= 1.0
        assert delay == "n/a" or float(delay) >= 0.0


def test_the_parameters_of_the_detectors_can_be_changed():
    default = ev.main(SMALL)
    other = ev.main([*SMALL, "--k", "5", "--m", "2", "--alpha", "0.3", "--window", "120"])

    assert other != default
    assert "EWMA (alpha 0.3)" in other and "rolling z-score (W 120)" in other


def test_the_evaluation_uses_the_detectors_the_backend_runs():
    created = ev.detectors(ev.Parameters(k=2.5, m=4, alpha=0.2, window=90), min_std=5.0)

    static, ewma, rolling = created.values()
    assert (type(ewma).__module__, type(rolling).__module__) == ("app.services.anomaly.detectors",) * 2
    assert (ewma.alpha, rolling.window) == (0.2, 90)
    for detector in (static, ewma, rolling):
        assert (detector.k, detector.m, detector.min_std, detector.warmup) == (2.5, 4, 5.0, WARMUP_SAMPLES)


def test_the_evaluation_is_run_the_way_the_backend_runs_the_detectors():
    # The same smallest spread per metric, and the seeded k, m, alpha and window.
    floors = {name: scenario.min_std for name, scenario in ev.SCENARIOS.items()}
    backend = AnomalyConfig()

    assert floors.pop("packet loss, 4 probes") == METRICS["loss"][1] == 5.0
    assert set(floors.values()) == {METRICS["latency"][1]} == {1.0}
    assert ev.Parameters() == ev.Parameters(k=backend.k, m=backend.m, alpha=backend.alpha, window=backend.window)


def test_a_trace_too_short_to_warm_up_on_is_refused(capsys):
    with pytest.raises(SystemExit):
        ev.main(["--samples", "100"])

    assert "--samples must be at least 300" in capsys.readouterr().err


def test_the_script_runs_from_the_command_line():
    done = subprocess.run(
        [sys.executable, "scripts/eval_anomaly.py", *SMALL], cwd=BACKEND, capture_output=True, text=True
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ev.main(SMALL)


def test_the_documented_results_are_what_the_script_prints():
    # docs/anomaly-evaluation.md quotes the output of the script run without
    # arguments. If the detectors or the script change, so must the document.
    documented = re.search(r"<!-- results:begin -->\n(.*?)\n<!-- results:end -->", REPORT.read_text(), re.S)

    assert documented is not None, "the results block is missing from docs/anomaly-evaluation.md"
    assert documented.group(1).strip() == ev.main([])
