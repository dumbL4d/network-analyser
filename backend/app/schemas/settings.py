"""Settings API schemas for the single AppSettings singleton row."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.anomaly import DetectorKind


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_name: str
    poll_interval_seconds: float
    latency_warn_ms: float
    latency_crit_ms: float
    flap_threshold: int
    failure_threshold: int
    recovery_threshold: int
    pings_per_cycle: int
    ping_gap_ms: int
    loss_warn_pct: float
    jitter_warn_ms: float
    anomaly_enabled: bool
    anomaly_detector: DetectorKind
    anomaly_k: float
    anomaly_m: int
    anomaly_alpha: float
    anomaly_window: int


class SettingsUpdate(BaseModel):
    """PATCH body: every field optional so callers can send partial updates.

    ``id`` is intentionally excluded -- the singleton row is not addressable
    and can never be re-pointed. The ranges of the numbers are checked in
    app/routers/settings.py, where the message can name the field.
    """

    site_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None
    ) = None
    poll_interval_seconds: float | None = None
    latency_warn_ms: float | None = None
    latency_crit_ms: float | None = None
    flap_threshold: int | None = None
    failure_threshold: int | None = None
    recovery_threshold: int | None = None
    pings_per_cycle: int | None = None
    ping_gap_ms: int | None = None
    loss_warn_pct: float | None = None
    jitter_warn_ms: float | None = None
    anomaly_enabled: bool | None = None
    anomaly_detector: DetectorKind | None = None
    anomaly_k: float | None = None
    anomaly_m: int | None = None
    anomaly_alpha: float | None = None
    anomaly_window: int | None = None