"""Custom column types."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A DATETIME column that always holds UTC.

    SQLite has no timezone-aware datetime type: SQLAlchemy stores the
    wall-clock fields as text and hands back naive datetimes. This type
    converts to UTC on the way in and attaches UTC on the way out, so the
    application only ever sees timezone-aware UTC datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("expected a timezone-aware datetime, got a naive one")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=timezone.utc)
