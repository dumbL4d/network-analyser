"""Database-backed application settings."""

from sqlmodel import Field, SQLModel


class AppSettings(SQLModel, table=True):
    """Singleton table holding the admin-editable application settings.

    EXACTLY ONE row may ever exist in this table. It is created by
    ``app.db.seed_settings.seed_default_settings`` at startup, and both the
    poll loop (read) and the admin settings API (read/write) always address it
    via ``select(...).first()`` -- the row's ``id`` is never meaningful to
    callers, so never hardcode a specific id when querying this table.

    The seeded defaults mirror the bootstrap values in
    ``app.core.config.Settings`` (10s poll, 100/500ms latency thresholds).
    Once seeded, subsequent startups keep whatever an admin last saved (the
    seeder is idempotent), so edits survive restarts. ``flap_threshold`` is
    stored now so the Phase 5 flap-detection logic has somewhere to read it
    from; it does nothing yet.
    """

    id: int | None = Field(default=None, primary_key=True)
    site_name: str = Field(default="Warehouse Network Monitor")
    poll_interval_seconds: float = Field(default=10.0)
    latency_warn_ms: float = Field(default=100.0)
    latency_crit_ms: float = Field(default=500.0)
    flap_threshold: int = Field(default=3)
    # Debouncing (app.services.debounce): how many polls in a row must agree
    # before a worse / a better status is confirmed. Allowed range 1-10; the
    # defaults mirror DEFAULT_FAILURE_THRESHOLD / DEFAULT_RECOVERY_THRESHOLD.
    failure_threshold: int = Field(default=3)
    recovery_threshold: int = Field(default=2)