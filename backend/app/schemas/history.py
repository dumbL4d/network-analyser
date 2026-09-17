from datetime import datetime

from pydantic import BaseModel


class HistorySampleOut(BaseModel):
    """A single historical latency sample returned by the history endpoint."""

    latency_ms: float | None
    timestamp: datetime
