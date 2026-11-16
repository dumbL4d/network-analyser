from datetime import datetime

from sqlalchemy import false
from sqlmodel import Field, SQLModel

from app.db.types import UTCDateTime


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    # Allowed values: "admin", "viewer"
    # (not enforced at the DB level yet; validation comes later in auth)
    role: str
    # True until the user has replaced a password they did not choose (a
    # seeded one). While it is true the API refuses everything except looking
    # at the own account and changing the password.
    must_change_password: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    # When the account was created. A token issued before this moment belongs
    # to an earlier account of the same name and is refused. NULL for accounts
    # that existed before this column did.
    created_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
