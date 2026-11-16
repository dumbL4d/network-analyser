"""Measure the anomaly detectors on synthetic latency traces with known answers.

Usage (from the ``backend/`` directory; no database, no network, no Docker):

    python scripts/eval_anomaly.py                # the tables of docs/anomaly-evaluation.md
    python scripts/eval_anomaly.py --seed 7 --traces 10 --samples 50000

What it does
============

1. GENERATE. A trace is a list of latency readings, one per poll:

       reading = base + daily rhythm (a sine wave) + noise (Gaussian)

   optionally with glitches: single readings far off, which are noise, not
   anomalies. Into it, at random places, go three kinds of anomaly, and where
   each one begins and ends is written down (the ground truth):

   * spike  a few readings far above normal;
   * step   the level jumps, stays up for a while, and comes back;
   * drift  the level creeps up slowly, then comes back.

   A packet-loss trace is made the same way from the loss of 4 probes per
   poll: mostly 0%, in steps of 25%, with periods in which probes get lost
   much more often (they are scored as steps).

   Everything random comes from one ``random.Random(seed)``, so the same seed
   gives the same trace and the same results, on any machine.

2. DETECT. Three detectors read every trace, one reading at a time, with the
   same k and m:

   * static   a threshold fixed once, from the first readings, and never
              moved: what a hand-set "degraded above N ms" amounts to;
   * ewma     app.services.anomaly.EwmaDetector;
   * rolling  app.services.anomaly.RollingZScoreDetector.

   The last two are the classes the backend runs, not copies of them.

3. SCORE, per event rather than per reading. An ALARM is a run of readings in
   a row that a detector flagged.

   * recall     the share of the anomalies that were flagged at all;
   * precision  the share of the alarms that were about a real anomaly;
   * delay      for the anomalies that were caught: how many readings after
                the anomaly began the first flag came (mean);
   * false alarms per 1000 readings outside the anomalies.

   One more figure, per step: the share of its readings that were flagged.
   It tells a detector that says "still wrong" for as long as the step lasts
   from one that only marks where it began.
"""

import argparse
import math
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.anomaly import (  # noqa: E402
    WARMUP_SAMPLES,
    Detector,
    EwmaDetector,
    RollingZScoreDetector,
)

KINDS = ("spike", "step", "drift")
SAMPLES_PER_DAY = 8640  # one reading every 10 seconds


@dataclass(frozen=True)
class TraceConfig:
    """What a trace looks like. Latencies in ms, lengths in readings."""

    samples: int = 3 * SAMPLES_PER_DAY
    base: float = 20.0
    noise_std: float = 2.0
    # The daily rhythm: a sine wave of this height. 0 for a flat baseline.
    diurnal_amplitude: float = 0.0
    diurnal_period: int = SAMPLES_PER_DAY
    # Glitches: the share of readings that are far off for that one reading
    # only, and how far (in units of ``noise_std``). They are noise: a
    # detector that reports one has raised a false alarm.
    glitch_rate: float = 0.0
    glitch_height: tuple[float, float] = (8.0, 20.0)
    # Nothing is injected before this, so every detector can warm up in peace.
    lead_in: int = 300
    # The gap between two anomalies: at least ``min_gap``, about ``mean_gap``.
    min_gap: int = 20
    mean_gap: float = 600.0
    # How much of each kind, relative to the others.
    weights: tuple[float, float, float] = (5.0, 2.0, 1.0)
    # How long an anomaly lasts, and how far above normal it goes, in units
    # of ``noise_std``.
    spike_length: tuple[int, int] = (3, 8)
    spike_height: tuple[float, float] = (8.0, 20.0)
    step_length: tuple[int, int] = (60, 240)
    step_height: tuple[float, float] = (5.0, 12.0)
    drift_length: tuple[int, int] = (240, 480)
    drift_height: tuple[float, float] = (6.0, 12.0)


@dataclass(frozen=True)
class Event:
    """One injected anomaly: the readings ``start`` to ``end - 1``."""

    kind: str
    start: int
    end: int


@dataclass
class Trace:
    # None: a poll without a reading (see generate_loss_trace).
    values: list[float | None]
    events: list[Event]


def generate_trace(config: TraceConfig, seed: int) -> Trace:
    """A trace and its ground truth. Deterministic for a given seed."""
    rng = random.Random(seed)
    extra = [0.0] * config.samples  # what the anomalies add to each reading
    events: list[Event] = []

    position = config.lead_in
    while True:
        position += config.min_gap + int(rng.expovariate(1 / config.mean_gap))
        kind = rng.choices(KINDS, weights=config.weights)[0]
        low, high = getattr(config, f"{kind}_length")
        length = rng.randint(low, high)
        if position + length >= config.samples:
            break
        height = rng.uniform(*getattr(config, f"{kind}_height")) * config.noise_std
        for offset in range(length):
            # A drift climbs in a straight line to its height; the others
            # are at their height from the first reading.
            extra[position + offset] = height * (offset + 1) / length if kind == "drift" else height
        events.append(Event(kind, position, position + length))
        position += length

    values: list[float | None] = []
    for t in range(config.samples):
        value = (
            config.base
            + config.diurnal_amplitude * math.sin(2 * math.pi * t / config.diurnal_period)
            + rng.gauss(0.0, config.noise_std)
            + extra[t]
        )
        if rng.random() < config.glitch_rate:
            value += rng.uniform(*config.glitch_height) * config.noise_std
        values.append(max(0.1, value))
    return Trace(values, events)


@dataclass(frozen=True)
class LossConfig:
    """What a packet-loss trace looks like: the loss of ``probes`` probes per
    poll, in percent."""

    samples: int = 3 * SAMPLES_PER_DAY
    probes: int = 4
    # The chance that a probe is lost when all is well ...
    base_rate: float = 0.01
    # ... and during a lossy period, which lasts this many polls.
    lossy_rate: tuple[float, float] = (0.25, 0.6)
    lossy_length: tuple[int, int] = (20, 120)
    lead_in: int = 300
    min_gap: int = 20
    mean_gap: float = 600.0


def generate_loss_trace(config: LossConfig, seed: int) -> Trace:
    """A packet-loss trace and its ground truth. Deterministic for a seed.

    A poll in which every probe is lost has no reading (None): the backend
    calls such a device "down" and does not judge its loss.
    """
    rng = random.Random(seed)
    rate = [config.base_rate] * config.samples
    events: list[Event] = []

    position = config.lead_in
    while True:
        position += config.min_gap + int(rng.expovariate(1 / config.mean_gap))
        length = rng.randint(*config.lossy_length)
        if position + length >= config.samples:
            break
        lossy = rng.uniform(*config.lossy_rate)
        for offset in range(length):
            rate[position + offset] = lossy
        events.append(Event("step", position, position + length))
        position += length

    values: list[float | None] = []
    for t in range(config.samples):
        lost = sum(rng.random() < rate[t] for _ in range(config.probes))
        values.append(None if lost == config.probes else 100.0 * lost / config.probes)
    return Trace(values, events)


class StaticThresholdDetector(Detector):
    """The baseline to beat: a threshold that is set once and never moves.

    It learns the mean and the spread of its first readings (the warm-up)
    and then stops learning for good. That is a threshold of
    ``mean + k * std``, chosen by someone who looked at the device once.
    """

    freezes_on_anomaly = False

    def __init__(self, k: float, m: int, min_std: float) -> None:
        super().__init__(k, m, min_std)
        self._count = 0
        self._mean = 0.0
        self._variance = 0.0

    def _learn(self, value: float) -> None:
        if self._count >= self.warmup:
            return  # set once, never moved
        self._count += 1
        diff = value - self._mean
        self._mean += diff / self._count
        self._variance += (diff * (value - self._mean) - self._variance) / self._count

    def _baseline(self) -> tuple[float, float]:
        return self._mean, math.sqrt(self._variance)


@dataclass
class Score:
    """The counts behind the metrics, so that several traces can be added up."""

    events: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KINDS, 0))
    caught: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KINDS, 0))
    delay_sum: int = 0
    alarms: int = 0
    false_alarms: int = 0
    normal_samples: int = 0
    # The readings inside steps, and how many of them were flagged.
    step_samples: int = 0
    step_flagged: int = 0

    def __iadd__(self, other: "Score") -> "Score":
        for kind in KINDS:
            self.events[kind] += other.events[kind]
            self.caught[kind] += other.caught[kind]
        self.delay_sum += other.delay_sum
        self.alarms += other.alarms
        self.false_alarms += other.false_alarms
        self.normal_samples += other.normal_samples
        self.step_samples += other.step_samples
        self.step_flagged += other.step_flagged
        return self

    @property
    def step_coverage(self) -> float | None:
        return self.step_flagged / self.step_samples if self.step_samples else None

    @property
    def recall(self) -> float | None:
        total = sum(self.events.values())
        return sum(self.caught.values()) / total if total else None

    def recall_of(self, kind: str) -> float | None:
        return self.caught[kind] / self.events[kind] if self.events[kind] else None

    @property
    def precision(self) -> float | None:
        return (self.alarms - self.false_alarms) / self.alarms if self.alarms else None

    @property
    def mean_delay(self) -> float | None:
        caught = sum(self.caught.values())
        return self.delay_sum / caught if caught else None

    @property
    def false_alarms_per_1000(self) -> float | None:
        return 1000 * self.false_alarms / self.normal_samples if self.normal_samples else None


def alarms_of(flags: list[bool]) -> list[tuple[int, int]]:
    """The runs of flagged readings, each as (first, one past the last)."""
    runs = []
    start = None
    for index, flagged in enumerate(flags):
        if flagged and start is None:
            start = index
        elif not flagged and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def score(flags: list[bool], events: list[Event]) -> Score:
    """Compare what a detector flagged with what was injected."""
    result = Score()
    alarms = alarms_of(flags)
    result.alarms = len(alarms)
    result.normal_samples = len(flags) - sum(event.end - event.start for event in events)

    for event in events:
        result.events[event.kind] += 1
        first = next((t for t in range(event.start, event.end) if flags[t]), None)
        if first is not None:
            result.caught[event.kind] += 1
            result.delay_sum += first - event.start
        if event.kind == "step":
            result.step_samples += event.end - event.start
            result.step_flagged += sum(flags[event.start : event.end])

    # An alarm is about a real anomaly if it overlaps one. (Both lists are in
    # time order, so one pass over each is enough.)
    upcoming = iter(events)
    event = next(upcoming, None)
    for alarm_start, alarm_end in alarms:
        while event is not None and event.end <= alarm_start:
            event = next(upcoming, None)
        if event is None or event.start >= alarm_end:
            result.false_alarms += 1
    return result


def run(detector: Detector, values: list[float | None]) -> list[bool]:
    """What the detector flags, reading by reading. A poll without a reading
    is not shown to the detector and is not flagged, as in the backend
    (app/services/anomaly/registry.py)."""
    return [value is not None and detector.update(value).anomalous for value in values]


@dataclass(frozen=True)
class Parameters:
    k: float = 3.0
    m: int = 3
    alpha: float = 0.1
    window: int = 60


def detectors(parameters: Parameters, min_std: float) -> dict[str, Detector]:
    """A fresh instance of each detector under test."""
    p = parameters
    return {
        "static threshold": StaticThresholdDetector(p.k, p.m, min_std),
        f"EWMA (alpha {p.alpha:g})": EwmaDetector(p.alpha, p.k, p.m, min_std),
        f"rolling z-score (W {p.window})": RollingZScoreDetector(p.window, p.k, p.m, min_std),
    }


@dataclass(frozen=True)
class Scenario:
    generate: Callable[[int, int], Trace]  # (samples, seed) -> trace
    # The smallest spread a baseline is given credit for: the value the
    # backend uses for this metric (app/services/anomaly/registry.py).
    min_std: float


def _latency(**settings: float) -> Scenario:
    config = TraceConfig(**settings)
    return Scenario(lambda samples, seed: generate_trace(replace(config, samples=samples), seed), 1.0)


SCENARIOS: dict[str, Scenario] = {
    "latency, flat baseline": _latency(),
    "latency, daily rhythm": _latency(diurnal_amplitude=8.0),
    "latency, daily rhythm, 1% glitches": _latency(diurnal_amplitude=8.0, glitch_rate=0.01),
    "packet loss, 4 probes": Scenario(
        lambda samples, seed: generate_loss_trace(LossConfig(samples=samples), seed), 5.0
    ),
}


def evaluate(
    seed: int, traces: int, samples: int, parameters: Parameters
) -> dict[str, dict[str, Score]]:
    """scenario -> detector -> score, added up over ``traces`` traces (the
    seeds ``seed``, ``seed + 1``, ...). Every detector sees the same traces."""
    results: dict[str, dict[str, Score]] = {}
    for name, scenario in SCENARIOS.items():
        totals: dict[str, Score] = {}
        for offset in range(traces):
            trace = scenario.generate(samples, seed + offset)
            for label, detector in detectors(parameters, scenario.min_std).items():
                totals.setdefault(label, Score())
                totals[label] += score(run(detector, trace.values), trace.events)
        results[name] = totals
    return results


def _cell(value: float | None, pattern: str) -> str:
    return "n/a" if value is None else pattern.format(value)


def markdown(results: dict[str, dict[str, Score]]) -> str:
    """The results as two Markdown tables."""
    lines = [
        "| Scenario | Detector | Precision | Recall | Mean delay (readings) | False alarms / 1000 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for scenario, totals in results.items():
        for name, total in totals.items():
            lines.append(
                f"| {scenario} | {name} | {_cell(total.precision, '{:.2f}')} | {_cell(total.recall, '{:.2f}')} "
                f"| {_cell(total.mean_delay, '{:.1f}')} | {_cell(total.false_alarms_per_1000, '{:.2f}')} |"
            )
    lines += [
        "",
        "| Scenario | Detector | Spikes caught | Steps caught | Drifts caught | Step readings flagged |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for scenario, totals in results.items():
        for name, total in totals.items():
            cells = " | ".join(
                f"{total.caught[kind]} of {total.events[kind]} ({_cell(total.recall_of(kind), '{:.0%}')})"
                if total.events[kind]
                else "none injected"
                for kind in KINDS
            )
            lines.append(f"| {scenario} | {name} | {cells} | {_cell(total.step_coverage, '{:.0%}')} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42, help="seed of the first trace (default 42)")
    parser.add_argument("--traces", type=int, default=5, help="traces per scenario (default 5)")
    parser.add_argument(
        "--samples", type=int, default=3 * SAMPLES_PER_DAY, help="readings per trace (default three days)"
    )
    parser.add_argument("--k", type=float, default=3.0, help="standard deviations above the baseline")
    parser.add_argument("--m", type=int, default=3, help="readings in a row above it")
    parser.add_argument("--alpha", type=float, default=0.1, help="EWMA smoothing factor")
    parser.add_argument("--window", type=int, default=60, help="rolling window size")
    args = parser.parse_args(argv)
    if args.samples < 10 * WARMUP_SAMPLES:
        parser.error(f"--samples must be at least {10 * WARMUP_SAMPLES}")

    parameters = Parameters(k=args.k, m=args.m, alpha=args.alpha, window=args.window)
    return markdown(evaluate(args.seed, args.traces, args.samples, parameters))


if __name__ == "__main__":
    print(main())
