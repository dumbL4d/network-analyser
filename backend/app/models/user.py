from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    # Allowed values: "admin", "viewer"
    # (not enforced at the DB level yet; validation comes later in auth)
    role: str