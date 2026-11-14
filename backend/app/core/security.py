"""Password hashing (bcrypt) and JWT access-token helpers.

Token issuance/validation lives here; wiring the dependencies onto routes is a
separate ticket (auth dependencies are defined in ``app.core.deps``).
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from passlib.exc import PasswordValueError

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password into a bcrypt hash (``$2b$...``)."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the stored bcrypt ``hashed`` value.

    A password bcrypt cannot take (one with a NUL byte, or thousands of
    characters long) is nobody's password: False, not an error.
    """
    try:
        return pwd_context.verify(plain, hashed)
    except PasswordValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    """Build a signed HS256 JWT for ``subject`` (the username).

    Claims: ``sub``, ``role``, ``iat`` (when it was issued) and ``exp``
    (``settings.JWT_EXPIRE_MINUTES`` later).
    """
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a token, raising ``jose.JWTError`` on any failure.

    Callers translate the exception into an HTTP 401; it is deliberately not
    caught here.
    """
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )