"""Anomaly detectors: is this reading unusual for THIS device?

A static threshold ("degraded above 100 ms") knows nothing about what is
normal for a device: 40 ms is fine for a link to another site and alarming
for a PLC that has always answered in 2 ms. A detector learns a device's own
baseline, reading by reading, and reports the readings that stand out from it.

Both detectors here are used the same way (``Detector``):

    verdict = detector.update(reading)

and judge a reading the same way:

    score     = (reading - mean) / max(std, min_std)      a z-score
    above     = score > k
    anomalous = this reading and the m - 1 before it were all above

It is ONE-SIDED: only readings above the baseline count. A device that
answers faster than usual is not a problem.

They differ in what "mean" and "std" are: an exponentially weighted average
(``EwmaDetector``) or the last W readings (``RollingZScoreDetector``). Both
cost O(1) time per reading, whatever came before.

Pure: no clock, no database, no settings. The same classes are what
scripts/eval_anomaly.py measures.
"""

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

# No verdict before a detector has seen this many readings: a baseline of a
# handful of readings is not a baseline.
WARMUP_SAMPLES = 30


@dataclass(frozen=True)
class Verdict:
    """What a detector says about one reading."""

    # True when this reading and the m - 1 before it were above the threshold.
    anomalous: bool
    # How many standard deviations the reading is above the baseline (negative
    # when it is below). None during the warm-up.
    score: float | None
    # The baseline the reading was compared with: the mean so far. None during
    # the warm-up.
    expected: float | None


class Detector(ABC):
    """The part every detector shares: warm-up, the z-score, and the rule
    that ``m`` readings in a row have to be above the threshold.

    A subclass says what the baseline is (``_baseline``) and how a reading
    changes it (``_learn``).
    """

    #: True: a reading above the threshold is kept out of the baseline.
    freezes_on_anomaly: bool

    def __init__(self, k: float, m: int, min_std: float, warmup: int = WARMUP_SAMPLES) -> None:
        if k <= 0:
            raise ValueError("k must be above 0")
        if m < 1:
            raise ValueError("m must be at least 1")
        if min_std <= 0:
            raise ValueError("min_std must be above 0")
        if warmup < WARMUP_SAMPLES:
            raise ValueError(f"the warm-up must be at least {WARMUP_SAMPLES} readings")
        self.k = k
        self.m = m
        # The smallest spread the baseline is given credit for. A device whose
        # readings were all (nearly) the same has a standard deviation of
        # (nearly) zero, and then the smallest wobble would be "many standard
        # deviations" out.
        self.min_std = min_std
        self.warmup = warmup
        self.seen = 0  # readings so far
        self._streak = 0  # readings in a row above the threshold

    @abstractmethod
    def _baseline(self) -> tuple[float, float]:
        """(mean, standard deviation) of what has been learned. O(1)."""

    @abstractmethod
    def _learn(self, value: float) -> None:
        """Take ``value`` into the baseline. O(1)."""

    def update(self, value: float) -> Verdict:
        """Judge one reading against the baseline as it was BEFORE the
        reading, then learn from it. O(1) time."""
        self.seen += 1
        if self.seen <= self.warmup:
            self._learn(value)
            return Verdict(anomalous=False, score=None, expected=None)

        mean, std = self._baseline()
        score = (value - mean) / max(std, self.min_std)
        above = score > self.k
        self._streak = self._streak + 1 if above else 0
        if not (above and self.freezes_on_anomaly):
            self._learn(value)
        return Verdict(anomalous=self._streak >= self.m, score=score, expected=mean)


class EwmaDetector(Detector):
    """Exponentially weighted moving average and variance.

    The baseline is a mean and a variance in which a reading counts for less
    the older it is: its weight shrinks by the factor (1 - alpha) with every
    newer reading, so it has halved after about 0.7 / alpha readings (7 for
    alpha = 0.1). The baseline therefore follows slow changes, such as the
    daily rhythm of a network, and forgets old ones.

        mean     <- mean + alpha * (x - mean)
        variance <- (1 - alpha) * (variance + alpha * (x - mean)^2)

    (both with the mean from before the reading). The whole state is those
    two numbers: O(1) time and O(1) memory per reading.

    WARM-UP. The first ``warmup`` readings are averaged plainly (a running
    mean and variance, Welford's method), each with the same weight. With a
    small alpha the weighted formulas would need far more than 30 readings to
    settle, and until then the variance would be too small.

    FREEZE. A reading above the threshold is NOT learned: neither the mean
    nor the variance moves. So a spike cannot pull the baseline up and hide
    itself, and an anomaly lasts for as long as the readings stay above the
    baseline of before it began. The price is that a change which is there to
    stay keeps being reported: the baseline never accepts it. (The registry
    starts every detector afresh when the anomaly settings are changed.)
    """

    freezes_on_anomaly = True

    def __init__(self, alpha: float, k: float, m: int, min_std: float, warmup: int = WARMUP_SAMPLES) -> None:
        super().__init__(k, m, min_std, warmup)
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be above 0 and at most 1")
        self.alpha = alpha
        self._mean = 0.0
        self._variance = 0.0
        self._learned = 0

    def _learn(self, value: float) -> None:
        self._learned += 1
        diff = value - self._mean
        if self._learned <= self.warmup:
            # Welford: the plain mean and (population) variance, one reading
            # at a time.
            self._mean += diff / self._learned
            self._variance += (diff * (value - self._mean) - self._variance) / self._learned
        else:
            step = self.alpha * diff
            self._mean += step
            self._variance = (1 - self.alpha) * (self._variance + diff * step)

    def _baseline(self) -> tuple[float, float]:
        return self._mean, math.sqrt(self._variance)


class RollingZScoreDetector(Detector):
    """Mean and standard deviation of the last ``window`` readings.

    Adding the window up again for every reading would cost O(W). Instead two
    running totals are kept, the sum and the sum of squares. A new reading is
    added to both, and the reading that drops out of the window is subtracted
    from both:

        mean = sum / n          variance = sum_of_squares / n - mean^2

    So a reading costs O(1) time however large the window is. Memory is the
    window itself, O(W), in a deque (O(1) at both ends).

    This detector learns from EVERY reading, anomalous or not: that is what a
    rolling window is. Two consequences, the opposite of the EWMA detector's:

    * a spike stays in the window for W readings and widens its spread, so a
      second spike soon after the first can go unnoticed;
    * a level that is there to stay becomes the new normal once the window
      has filled with it, without anyone resetting anything.
    """

    freezes_on_anomaly = False

    def __init__(self, window: int, k: float, m: int, min_std: float, warmup: int = WARMUP_SAMPLES) -> None:
        super().__init__(k, m, min_std, warmup)
        if window < warmup:
            raise ValueError("the window must hold at least the warm-up")
        self.window = window
        self._values: deque[float] = deque()
        self._sum = 0.0
        self._sum_of_squares = 0.0

    def _learn(self, value: float) -> None:
        self._values.append(value)
        self._sum += value
        self._sum_of_squares += value * value
        if len(self._values) > self.window:
            oldest = self._values.popleft()
            self._sum -= oldest
            self._sum_of_squares -= oldest * oldest

    def _baseline(self) -> tuple[float, float]:
        n = len(self._values)
        mean = self._sum / n
        # Rounding can leave the difference a hair below zero when the
        # readings are all the same.
        variance = max(self._sum_of_squares / n - mean * mean, 0.0)
        return mean, math.sqrt(variance)


DETECTORS = ("ewma", "rolling")


def make_detector(kind: str, *, k: float, m: int, alpha: float, window: int, min_std: float) -> Detector:
    """The detector called ``kind``. ``alpha`` is for "ewma" and ``window``
    for "rolling"; the other one is ignored."""
    if kind == "ewma":
        return EwmaDetector(alpha, k, m, min_std)
    if kind == "rolling":
        return RollingZScoreDetector(window, k, m, min_std)
    raise ValueError(f"unknown detector {kind!r}: expected one of {DETECTORS}")
