"""Admin-editable application settings endpoints.

GET is available to any authenticated user (viewers may inspect the poll
interval and latency thresholds); PATCH is reserved for admins -- this router
is the FIRST use of ``require_role("admin")`` in the codebase.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.deps import Audit, get_current_user, require_role
from app.db.session import get_session
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.anomaly import WARMUP_SAMPLES
from app.services.debounce import MAX_THRESHOLD, MIN_THRESHOLD
from app.services.ping_engine import (
    MAX_PING_GAP_MS,
    MAX_PINGS_PER_CYCLE,
    MIN_PING_GAP_MS,
    MIN_PINGS_PER_CYCLE,
    probe_budget_problem,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Matches the original tool's documented minimum poll interval.
MIN_POLL_INTERVAL_SECONDS = 5.0

# Anomaly detection. k: standard deviations above the baseline. m: readings in
# a row above it. alpha: how fast the EWMA detector forgets. window: how many
# readings the rolling detector looks back on, at least its warm-up.
ANOMALY_K_RANGE = (1, 10)
ANOMALY_M_RANGE = (1, 20)
ANOMALY_ALPHA_RANGE = (0.01, 0.5)
ANOMALY_WINDOW_RANGE = (WARMUP_SAMPLES, 1000)


def _get_singleton(session: Session) -> AppSettings:
    """Fetch (or, defensively, create) the single AppSettings row.

    The row is seeded at startup; the create-on-demand branch only runs against
    a DB that predates this table, keeping the API functional regardless.
    """
    row = session.exec(select(AppSettings)).first()
    if row is None:
        row = AppSettings()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@router.get("", response_model=SettingsOut)
def get_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SettingsOut:
    return SettingsOut.model_validate(_get_singleton(session))


@router.patch("", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
    audit: Audit = Depends(),
) -> SettingsOut:
    row = _get_singleton(session)
    # Only the fields the caller actually sent (PATCH semantics). Explicit
    # ``exclude_none=True`` is redundant with ``exclude_unset`` here but makes
    # the intent obvious: nulls are "not provided", never "reset to default".
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)

    if (
        "poll_interval_seconds" in updates
        and updates["poll_interval_seconds"] < MIN_POLL_INTERVAL_SECONDS
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"poll_interval_seconds must be at least "
                f"{MIN_POLL_INTERVAL_SECONDS} seconds"
            ),
        )

    # Validate the EFFECTIVE thresholds: incoming values over stored ones. This
    # makes a single-field patch (e.g. only latency_crit_ms) compare against the
    # other field's current stored value, not just when both are sent together.
    effective_warn = updates.get("latency_warn_ms", row.latency_warn_ms)
    effective_crit = updates.get("latency_crit_ms", row.latency_crit_ms)
    if effective_warn >= effective_crit:
        raise HTTPException(
            status_code=422,
            detail="latency_warn_ms must be less than latency_crit_ms",
        )

    # Debounce thresholds: how many polls in a row must agree (see
    # app.services.debounce).
    for field in ("failure_threshold", "recovery_threshold"):
        if field in updates and not MIN_THRESHOLD <= updates[field] <= MAX_THRESHOLD:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}",
            )

    # Probing (see app.services.ping_engine) and anomaly detection (see
    # app.services.anomaly): each value in its range ...
    ranges = {
        "pings_per_cycle": (MIN_PINGS_PER_CYCLE, MAX_PINGS_PER_CYCLE),
        "ping_gap_ms": (MIN_PING_GAP_MS, MAX_PING_GAP_MS),
        "anomaly_k": ANOMALY_K_RANGE,
        "anomaly_m": ANOMALY_M_RANGE,
        "anomaly_alpha": ANOMALY_ALPHA_RANGE,
        "anomaly_window": ANOMALY_WINDOW_RANGE,
    }
    for field, (lowest, highest) in ranges.items():
        if field in updates and not lowest <= updates[field] <= highest:
            raise HTTPException(
                status_code=422, detail=f"{field} must be between {lowest} and {highest}"
            )
    if "loss_warn_pct" in updates and not 0 < updates["loss_warn_pct"] <= 100:
        raise HTTPException(
            status_code=422, detail="loss_warn_pct must be above 0 and at most 100"
        )
    if "jitter_warn_ms" in updates and not updates["jitter_warn_ms"] > 0:
        raise HTTPException(status_code=422, detail="jitter_warn_ms must be above 0")

    # ... and together they have to fit the poll interval. Checked on the
    # EFFECTIVE values (incoming over stored), whenever one of the three
    # changes.
    if updates.keys() & {"pings_per_cycle", "ping_gap_ms", "poll_interval_seconds"}:
        problem = probe_budget_problem(
            updates.get("pings_per_cycle", row.pings_per_cycle),
            updates.get("ping_gap_ms", row.ping_gap_ms),
            settings.PING_TIMEOUT_SECONDS,
            updates.get("poll_interval_seconds", row.poll_interval_seconds),
        )
        if problem is not None:
            raise HTTPException(status_code=422, detail=problem)

    changes = {
        field: {"from": getattr(row, field), "to": value}
        for field, value in updates.items()
        if getattr(row, field) != value
    }
    for field, value in updates.items():
        setattr(row, field, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    updated = SettingsOut.model_validate(row)
    audit.record(current_user.username, "settings.updated", changes=changes)
    return updated