from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# The time ranges /api/history/{id}?window=... accepts.
HistoryWindow = Literal["1h", "6h", "24h", "7d", "30d"]


class HistorySampleOut(BaseModel):
    """A single historical latency sample returned by the history endpoint."""

    latency_ms: float | None
    timestamp: datetime


class HistoryPointOut(BaseModel):
    """One point of a windowed history: a raw reading, or a time bucket.

    For a raw reading ``latency_ms`` is that reading, ``min_ms`` and ``max_ms``
    equal it and ``sample_count`` is 1. For a bucket ``latency_ms`` is the
    average over the polls that got a reply (None if none did) and
    ``fail_count`` says how many polls did not.
    """

    timestamp: datetime
    latency_ms: float | None
    min_ms: float | None
    max_ms: float | None
    sample_count: int
    fail_count: int


class HistoryWindowOut(BaseModel):
    """Latency history of one device over a time range."""

    device_id: str
    window: HistoryWindow
    # "raw", or the bucket size that was used: "1m", "5m", "30m", "2h".
    resolution: str
    # The bucket size in seconds; None for raw readings.
    resolution_seconds: int | None
    points: list[HistoryPointOut]
