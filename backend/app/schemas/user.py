"""User management + self-service password schemas.

``UserOut`` deliberately omits ``password_hash`` -- hashes must never leave
the API, not even for admins (no operation ever needs them returned).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Shared by the admin user-creation endpoint and the self-service password
# change. Both enforce the same minimum.
MIN_PASSWORD_LENGTH = 8


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str  # plaintext; hashed server-side before persisting
    role: Literal["admin", "viewer"]


class PasswordChangeRequest(BaseModel):
    """Body for the self-service password-change endpoint.

    Requiring ``current_password`` means a stolen or left-open session cannot
    silently lock out the real user -- the attacker would need their password
    too. This is what lets the seeded credentials live up to the original
    tool's documented "should be changed after first login" expectation.
    """

    current_password: str
    new_password: str