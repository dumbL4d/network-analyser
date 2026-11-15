"""One detector per device and metric, fed by the poll loop.

Every cycle the loop hands over its raw readings (``observe``). Each reading's
latency and packet loss go to that device's detectors, and the readings come
back with what was found in ``anomaly``. The registry also says which
anomalies began or ended in this cycle, so that they can be stored.

Advisory only: nothing here touches a reading's status.

The detectors live in memory. They start afresh, and every anomaly in
progress ends, when the anomaly settings change (another k or alpha means
another baseline) and when the backend restarts. A device that is no longer
polled (it was deleted) loses its detectors in the next cycle.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.anomaly.detectors import Detector, make_detector
from app.services.ping_engine import DeviceStatus, MetricAnomaly


@dataclass(frozen=True)
class AnomalyConfig:
    """The anomaly settings of one poll cycle. The defaults are those of the
    AppSettings columns."""

    enabled: bool = True
    detector: str = "ewma"
    k: float = 3.0
    m: int = 3
    alpha: float = 0.1
    window: int = 60


@dataclass(frozen=True)
class AnomalyStart:
    device_id: str
    metric: str
    detector: str
    at: datetime
    value: float
    expected: float
    score: float


@dataclass(frozen=True)
class AnomalyEnd:
    device_id: str
    metric: str
    at: datetime


def _latency(reading: DeviceStatus) -> float | None:
    return reading.latency_ms


def _loss(reading: DeviceStatus) -> float | None:
    # A device that answers nothing at all is "down": that is its status, not
    # an anomaly. Loss is only judged while some probes still get through.
    return reading.loss_pct if reading.latency_ms is not None else None


# metric -> (how to read it off a reading, the smallest spread its baseline is
# given credit for: see Detector.min_std). In the metric's own unit: 1 ms of
# latency, 5 percentage points of loss.
METRICS: dict[str, tuple[Callable[[DeviceStatus], float | None], float]] = {
    "latency": (_latency, 1.0),
    "loss": (_loss, 5.0),
}


class AnomalyRegistry:
    def __init__(self) -> None:
        self._config: AnomalyConfig | None = None
        self._detectors: dict[tuple[str, str], Detector] = {}
        # The anomalies in progress: (device, metric) -> when it began.
        self._since: dict[tuple[str, str], datetime] = {}

    def observe(
        self, readings: list[DeviceStatus], config: AnomalyConfig
    ) -> tuple[list[DeviceStatus], list[AnomalyStart], list[AnomalyEnd]]:
        """Run one cycle's readings through the detectors.

        Returns the readings with ``anomaly`` filled in (same order), the
        anomalies that began in this cycle and the ones that ended.
        O(devices) per cycle: each reading costs O(1) per metric.
        """
        started: list[AnomalyStart] = []
        ended: list[AnomalyEnd] = []
        now = datetime.now(timezone.utc)

        if config != self._config:
            # Other settings, another baseline: start afresh.
            ended += [AnomalyEnd(device_id, metric, now) for device_id, metric in self._since]
            self._detectors.clear()
            self._since.clear()
            self._config = config

        # Devices that are no longer polled have been deleted.
        polled = {reading.device_id for reading in readings}
        for key in [key for key in self._detectors if key[0] not in polled]:
            del self._detectors[key]
            if self._since.pop(key, None) is not None:
                ended.append(AnomalyEnd(*key, now))

        if not config.enabled:
            return readings, started, ended

        annotated = []
        for reading in readings:
            found: dict[str, MetricAnomaly] = {}
            for metric, (read, min_std) in METRICS.items():
                key = (reading.device_id, metric)
                value = read(reading)
                if value is None:
                    # Nothing was measured: nothing can be said, and the
                    # detector is left as it is.
                    anomalous = False
                else:
                    detector = self._detectors.get(key)
                    if detector is None:
                        detector = self._detectors[key] = make_detector(
                            config.detector,
                            k=config.k,
                            m=config.m,
                            alpha=config.alpha,
                            window=config.window,
                            min_std=min_std,
                        )
                    verdict = detector.update(value)
                    anomalous = verdict.anomalous

                if anomalous:
                    if key not in self._since:
                        self._since[key] = reading.timestamp
                        started.append(
                            AnomalyStart(
                                reading.device_id,
                                metric,
                                config.detector,
                                reading.timestamp,
                                value,
                                verdict.expected,
                                verdict.score,
                            )
                        )
                    found[metric] = MetricAnomaly(
                        value=value,
                        expected=verdict.expected,
                        score=verdict.score,
                        since=self._since[key],
                    )
                elif self._since.pop(key, None) is not None:
                    ended.append(AnomalyEnd(reading.device_id, metric, reading.timestamp))

            annotated.append(reading.model_copy(update={"anomaly": found or None}))
        return annotated, started, ended

    def detector_keys(self) -> set[tuple[str, str]]:
        """The (device, metric) pairs that have a detector."""
        return set(self._detectors)


anomaly_registry = AnomalyRegistry()
