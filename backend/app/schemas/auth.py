"""Auth-related response schemas."""

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    # True: until the password is changed, the token is only good for
    # /api/auth/me and /api/auth/change-password.
    must_change_password: bool = False


class MeResponse(BaseModel):
    username: str
    role: str
    must_change_password: bool = False


class StreamTicketOut(BaseModel):
    """A single-use ticket for GET /api/stream/status?ticket=..."""

    ticket: str
    # Seconds until the ticket expires if it is not used.
    expires_in: int
