"""Admin-editable application settings endpoints.

GET is available to any authenticated user (viewers may inspect the poll
interval and latency thresholds); PATCH is reserved for admins -- this router
is the FIRST use of ``require_role("admin")`` in the codebase.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.debounce import MAX_THRESHOLD, MIN_THRESHOLD

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Matches the original tool's documented minimum poll interval.
MIN_POLL_INTERVAL_SECONDS = 5.0


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

    for field, value in updates.items():
        setattr(row, field, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return SettingsOut.model_validate(row)