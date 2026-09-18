"""Settings API schemas for the single AppSettings singleton row."""

from pydantic import BaseModel, ConfigDict


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_name: str
    poll_interval_seconds: float
    latency_warn_ms: float
    latency_crit_ms: float
    flap_threshold: int


class SettingsUpdate(BaseModel):
    """PATCH body: every field optional so callers can send partial updates.

    ``id`` is intentionally excluded -- the singleton row is not addressable
    and can never be re-pointed.
    """

    site_name: str | None = None
    poll_interval_seconds: float | None = None
    latency_warn_ms: float | None = None
    latency_crit_ms: float | None = None
    flap_threshold: int | None = None