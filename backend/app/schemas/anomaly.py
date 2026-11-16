"""Response models for anomaly events."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

AnomalyMetric = Literal["latency", "loss"]
DetectorKind = Literal["ewma", "rolling"]


class AnomalyEventOut(BaseModel):
    """One anomaly a detector found. Advisory: it changed no status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    metric: AnomalyMetric
    detector: DetectorKind
    started_at: datetime
    # None while the anomaly is still going on.
    ended_at: datetime | None
    # The reading that confirmed it, the baseline it was compared with, and
    # how many standard deviations above the baseline it was.
    value: float
    expected: float
    score: float
