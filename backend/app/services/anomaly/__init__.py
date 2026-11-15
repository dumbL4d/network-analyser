"""Statistical anomaly detection on latency and packet loss.

``detectors`` has the two detectors (pure classes); ``registry`` keeps one of
them per device and metric and feeds them the poll loop's readings.

Anomalies are ADVISORY. They are shown next to a device's status and never
change it, and they never open an incident.
"""

from app.services.anomaly.detectors import (
    DETECTORS,
    WARMUP_SAMPLES,
    Detector,
    EwmaDetector,
    RollingZScoreDetector,
    Verdict,
    make_detector,
)

__all__ = [
    "DETECTORS",
    "WARMUP_SAMPLES",
    "Detector",
    "EwmaDetector",
    "RollingZScoreDetector",
    "Verdict",
    "make_detector",
]
